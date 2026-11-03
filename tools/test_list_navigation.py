"""List navigation checks; command filtering also uses hidden native windows."""
import ast
import fnmatch
import importlib
import json
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from native_test_support import RUN_DIR
from test_modal_lifecycle import _cleanup_on_exit, _modal_dialog_scope

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "clnch"))
import clnch_inisettings as ini_settings


class Keymap:
    def __init__(self): self.table = {}
    def __setitem__(self, key, value): self.table[key] = value


class ListNavigationTests(unittest.TestCase):
    def setUp(self):
        keys = {35: "End", 36: "Home", 13: "Return", 27: "Escape", 38: "Up", 40: "Down"}
        self.customize = lambda name, window: None
        env = {"ckit": SimpleNamespace(Keymap=Keymap, CommandInfo=lambda: None,
            KeyEvent=lambda vk, mod: keys[vk],
            callConfigFunc=lambda name, window: self.customize(name, window)),
            "VK_HOME": 36, "VK_END": 35, "VK_RETURN": 13, "VK_ESCAPE": 27,
            "VK_UP": 38, "VK_DOWN": 40, "VK_PRIOR": 33, "VK_NEXT": 34,
            "fnmatch": fnmatch, "clnch_ini": SimpleNamespace(get=lambda *args: "partial"),
            "ini_settings": ini_settings}
        tree = ast.parse((ROOT / "clnch/clnch_isearch.py").read_text(encoding="utf-8-sig"))
        search = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "IncrementalSearch")
        exec(compile(ast.Module(body=[search], type_ignores=[]), "search-check", "exec"), env)  # noqa: S102  # Execute isolated source under test.
        env["clnch_isearch"] = SimpleNamespace(IncrementalSearch=env["IncrementalSearch"])
        tree = ast.parse((ROOT / "clnch/clnch_listwindow.py").read_text(encoding="utf-8-sig"))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "ListWindow")
        cls.bases = []
        cls.body = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in (
            "configure", "onKeyDown", "onClose", "onChar", "cancel", "getResult", "command_CursorUp", "command_CursorDown",
            "command_CursorPageUp", "command_CursorPageDown", "command_CursorFirst", "command_CursorLast",
            "command_Enter", "command_Cancel", "command_IncrementalSearch")]
        exec(compile(ast.Module(body=[cls], type_ignores=[]), "list-check", "exec"), env)  # noqa: S102  # Execute isolated source under test.
        self.cls = env["ListWindow"]
        self.env = env

    def window(self, items, onekey_search=True):
        window = self.cls()
        window.items = items
        window.select = min(1, len(items) - 1)
        window.onekey_search = onekey_search
        window.onekey_decide = False
        window.return_modkey = False
        window.result_mod = 0
        window.keydown_hook = None
        window.isearch = None
        window.closed = False
        window.quit = lambda: setattr(window, "closed", True)
        window.removeKeyMessage = window.paint = lambda: None
        window.itemsHeight = lambda: 2
        window.visible = []
        window.scroll_info = SimpleNamespace(pos=0, makeVisible=lambda index, height: window.visible.append(index))
        window.command = SimpleNamespace(**{name: getattr(window, "command_" + name) for name in (
            "CursorUp", "CursorDown", "CursorPageUp", "CursorPageDown", "CursorFirst", "CursorLast",
            "Enter", "Cancel", "IncrementalSearch")})
        window.configure()
        return window

    def test_close_cancels_selection_like_escape_in_both_result_forms(self):
        for return_modkey in (False, True):
            for close in (lambda window: window.onClose(), lambda window: window.onKeyDown(27, 0)):
                with self.subTest(return_modkey=return_modkey, close=close):
                    window = self.window(["alpha", "beta"])
                    window.return_modkey = return_modkey
                    close(window)
                    self.assertTrue(window.closed)
                    self.assertEqual(window.getResult(), (-1, 0) if return_modkey else -1)
            window = self.window(["alpha", "beta"])
            window.return_modkey = return_modkey
            window.onKeyDown(13, 0)
            self.assertTrue(window.closed)
            self.assertEqual(window.getResult(), (1, 0) if return_modkey else 1)

    def test_onekey_search_skips_empty_labels_on_both_passes_and_keeps_decide(self):
        items = ["", ("alpha", "a"), ("", "empty"), ["alpine", "b"], ["", "empty2"], "beta"]
        window = self.window(items)
        for expected in (3, 1, 3):
            window.onChar(ord("A"), 0)
            self.assertEqual(window.select, expected)
            self.assertFalse(window.closed)
        window.onekey_decide = True
        window.onChar(ord("a"), 0)
        self.assertFalse(window.closed)
        window.onChar(ord("z"), 0)
        self.assertEqual(window.select, 1)
        window.onChar(ord("b"), 4)
        self.assertEqual(window.select, 5)
        self.assertEqual(window.result_mod, 4)
        self.assertTrue(window.closed)
        window = self.window(["", ("", "empty"), ["", "empty2"]])
        window.onChar(ord("a"), 0)
        self.assertEqual(window.select, 1)
        self.assertFalse(window.closed)

    def test_remaining_search_modes(self):
        search = self.env["IncrementalSearch"]()
        for mode, name, pattern, expected in (
                ("strict", "alpha", "al", True), ("strict", "alpha", "ph", False),
                ("partial", "alpha", "ph", True), ("partial", "alpha", "xy", False),
                ("inaccurate", "alpha", "aa", True), ("inaccurate", "alpha", "az", False)):
            with self.subTest(mode=mode, pattern=pattern):
                self.assertEqual(search.fnmatch(name, pattern, mode), expected)

    def test_popup_forwards_optional_minimum_width_and_keeps_existing_default(self):
        calls = []
        events = []
        class ListWindow:
            def __init__(self, *args, **kwargs): calls.append((args, kwargs))
            def show(self, visible): events.append(("show", visible))
            def messageLoop(self): pass
            def getResult(self): return 0
            def destroy(self): pass
        tree = ast.parse((ROOT / "clnch/clnch_listwindow.py").read_text(encoding="utf-8-sig"))
        function = next(n for n in reversed(tree.body) if isinstance(n, ast.FunctionDef) and n.name == "popMenu")
        namespace = {"ExitStack": ExitStack, "_cleanup_on_exit": _cleanup_on_exit, "ListWindow": ListWindow,
                     "clnch_misc": SimpleNamespace(_modal_dialog_scope=_modal_dialog_scope, adjustWindowPosition=lambda *args, **kwargs: events.append("position"))}
        exec(compile(ast.Module(body=[function], type_ignores=[]), "popup-width-test", "exec"), namespace)  # noqa: S102  # Execute isolated source under test.
        parent = SimpleNamespace(centerOfWindowInPixel=lambda: (0, 0), enable=lambda value: None,
                                 isEnabled=lambda: True, activate=lambda: None)
        for kwargs, expected in (({}, 5), ({"min_width": 70}, 70)):
            events.clear()
            self.assertEqual(namespace["popMenu"](parent, 76, 16, "menu", ["item"], **kwargs), 0)
            self.assertEqual(calls[-1][0][2], expected)
            self.assertIs(calls[-1][1]["opaque_normal"], True)
            self.assertEqual(events, ["position", ("show", True)])

    def test_normal_home_end_select_endpoints_and_do_not_confirm(self):
        for items in ([], ["only"], ["a", "b", "c"]):
            with self.subTest(items=items):
                window = self.window(items)
                window.onKeyDown(35, 0)
                self.assertEqual(window.select, len(items) - 1)
                window.onKeyDown(36, 0)
                self.assertEqual(window.select, 0 if items else -1)
                self.assertFalse(window.closed)
                if items: self.assertEqual(window.visible[-2:], [len(items) - 1, 0])

    def test_custom_keymap_still_overrides_standard(self):
        calls = []
        def customize(name, window):
            window.keymap["Home"] = lambda info: calls.append("Home")
            window.keymap["End"] = lambda info: calls.append("End")
        self.customize = customize
        window = self.window(["a", "b", "c"])
        window.onKeyDown(36, 0)
        window.onKeyDown(35, 0)
        self.assertEqual(calls, ["Home", "End"])
        self.assertEqual(window.select, 1)

    def test_search_home_end_only_visit_matches_and_keep_search(self):
        window = self.window(["other", ("alpha", "a"), "beta", ["alpine", "b"], "omega"], False)
        window.command_IncrementalSearch(None)
        window.isearch.isearch_value = "al"
        window.onKeyDown(35, 0)
        self.assertEqual(window.select, 3)
        window.onKeyDown(36, 0)
        self.assertEqual(window.select, 1)
        self.assertEqual(window.isearch.isearch_value, "al")
        self.assertFalse(window.closed)
        window.isearch.isearch_value = "missing"
        window.onKeyDown(35, 0)
        window.onKeyDown(36, 0)
        self.assertEqual(window.select, 1)
        window.isearch.isearch_value = ""
        window.onKeyDown(35, 0)
        self.assertEqual(window.select, 4)
        window.onKeyDown(36, 0)
        self.assertEqual(window.select, 0)
        window.onKeyDown(13, 0)
        self.assertIsNone(window.isearch)
        self.assertFalse(window.closed)
        window.onKeyDown(35, 0)
        self.assertEqual(window.select, 4)


    def test_search_navigation_uses_one_search_and_observes_query_updates(self):
        window = self.window(["alpha", "beta", "alpine", "beacon", "alps"], False)
        factory = self.env["clnch_isearch"]
        with patch.object(factory, "IncrementalSearch", wraps=factory.IncrementalSearch) as create:
            window.command_IncrementalSearch(None)
            search = window.isearch
            for key, method in ((38, "cursorUp"), (40, "cursorDown"),
                                (33, "cursorPageUp"), (34, "cursorPageDown")):
                with self.subTest(key=key), patch.object(search, method, return_value=2) as move:
                    window.onKeyDown(key, 0)
                    move.assert_called_once()
                    self.assertEqual(window.select, 2)
                    self.assertIs(window.isearch, search)
            for query, last, first in (("al", 4, 0), ("be", 3, 1)):
                search.isearch_value = query
                window.onKeyDown(35, 0)
                self.assertEqual(window.select, last)
                window.onKeyDown(36, 0)
                self.assertEqual(window.select, first)
            create.assert_called_once_with()

    def test_search_restart_replaces_search_and_restores_custom_hook(self):
        window = self.window(["alpha", "beta"], False)
        original_hook = lambda vk, mod: False
        window.keydown_hook = original_hook
        window.command_IncrementalSearch(None)
        first_search = window.isearch
        first_hook = window.keydown_hook
        first_search.isearch_value = "alpha"
        window.onKeyDown(13, 0)
        self.assertIsNone(window.isearch)
        self.assertIs(window.keydown_hook, original_hook)
        window.command_IncrementalSearch(None)
        self.assertIsNot(window.isearch, first_search)
        self.assertIsNot(window.keydown_hook, first_hook)
        self.assertEqual(window.isearch.isearch_value, "")
        window.onKeyDown(27, 0)
        self.assertIsNone(window.isearch)
        self.assertIs(window.keydown_hook, original_hook)
        self.assertFalse(window.closed)

    def test_enter_and_escape_finish_search_without_confirming_list(self):
        for key in (13, 27):
            window = self.window(["alpha", "beta"])
            old_hook = window.keydown_hook
            window.command_IncrementalSearch(None)
            self.assertIsNotNone(window.isearch)
            window.onKeyDown(key, 0)
            self.assertIsNone(window.isearch)
            self.assertIs(window.keydown_hook, old_hook)
            self.assertFalse(window.closed)

class CommandFilterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path[:0] = [str(ROOT), str(ROOT / "clnch"), str(RUN_DIR / "lib")]
        sys._clnch_app_dir = str(ROOT)
        cls.ckit = importlib.import_module("ckit")
        importlib.import_module("clnch_text").initialize()
        cls.cmdlist = importlib.import_module("clnch_cmdlist")
        cls.ckit.registerWindowClass("ReClnchCommandFilterTest")
        cls.ckit.Keymap.init()

    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.ckit.setTheme("black", {})
        for name in ("show", "activate", "foreground", "enableIme"):
            self.stack.enter_context(patch.object(self.ckit.TextWindow, name))
        self.stack.enter_context(patch.object(self.ckit, "callConfigFunc"))
        self.parent = self.ckit.TextWindow(x=100, y=100, width=20, height=1, show=False)
        self.stack.callback(self.parent.destroy)
        self.names = ["backup_daily", "build_release", "file[1]", "file*", "file?",
                      "foo bar", "fork", "open_backup_folder", "restore_config", "sync_backup", "日本語"]
        self.items = [(self.cmdlist.EMPTY_LABEL, "")] + [(name, name) for name in self.names]

    def window(self, items=None, select=0, cls=None, **kwargs):
        window = (cls or self.cmdlist.CommandListWindow)(
            300, 250, 5, 1, 20, 4, self.parent, False, "Command List",
            self.items if items is None else items, initial_select=select,
            onekey_search=True, **kwargs)
        self.stack.callback(window.destroy)
        return window

    def type_text(self, window, text):
        for ch in text:
            window.onChar(ord(ch), 0)

    def start(self, window):
        window.onKeyDown(self.ckit.VK_F, self.ckit.MODKEY_CTRL)
        self.assertIsNotNone(window.isearch)

    def keys(self, window):
        return [item[1] for item in window.items]

    def test_result_boundary_preserves_public_modes_identity_and_no_modifier_read(self):
        module = self.cmdlist.clnch_listwindow
        window = self.window(select=1)
        window.result_mod = 4
        for flag, expected in ((False, 1), (True, (1, 4)), (False, 1)):
            window.return_modkey = flag
            result = window.getResult()
            self.assertEqual(result, expected)
            captured = module._split_list_result(result)
            self.assertEqual(captured, (1, 4 if flag else None))
            if flag:
                self.assertIs(captured, result)
        class Index(int):
            def __int__(self):
                raise AssertionError("result must not be converted")
        index = Index(1000)
        self.assertIs(module._split_list_result(index)[0], index)
        window.getResult = lambda: (index, 8)
        with patch.object(window, "getResult", wraps=window.getResult) as overridden:
            captured = module._split_list_result(window.getResult())
        overridden.assert_called_once_with()
        self.assertIs(captured[0], index)
        self.assertEqual(captured[1], 8)

    def test_search_result_maps_tuple_index_keeps_modifiers_and_cancel_identity(self):
        module = self.cmdlist.clnch_listwindow
        window = self.window(return_modkey=True)
        self.start(window)
        self.type_text(window, "backup")
        window.onKeyDown(self.ckit.VK_END, 0)
        window.result_mod = 4
        self.assertEqual(window.getResult(), (10, 4))
        window.return_modkey = False
        self.assertEqual(window.getResult(), 10)
        for raw in ((-1, 8), (0, 8)):
            with patch.object(module.ListWindow, "getResult", return_value=raw) as base:
                result = window.getResult()
            base.assert_called_once_with()
            if raw[0] < 0:
                self.assertIs(result, raw)
            else:
                self.assertEqual(result, (1, 8))
        error = RuntimeError("result failure")
        with patch.object(module.ListWindow, "getResult", side_effect=error) as base, \
             self.assertRaises(RuntimeError) as raised:
            window.getResult()
        self.assertIs(raised.exception, error)
        base.assert_called_once_with()
        window.isearch = None
        with patch.object(module.ListWindow, "getResult", return_value=raw):
            self.assertIs(window.getResult(), raw)

    def test_normal_cycle_wraps_with_no_query_and_plain_f_is_a_character(self):
        window = self.window()
        for expected in (1, 2, 1):
            self.type_text(window, "b")
            self.assertEqual(window.select, expected)
            self.assertIsNone(window.isearch)
        window.onKeyDown(self.ckit.VK_F, 0)
        self.type_text(window, "f")
        self.assertEqual(window.items[window.select][1], "file[1]")
        window.onKeyDown(self.ckit.VK_F, 0)
        self.type_text(window, "f")
        self.assertEqual(window.items[window.select][1], "file*")
        self.assertIsNone(window.isearch)

    def test_live_substring_backspace_and_empty_query_restore_original_order(self):
        window = self.window()
        self.start(window)
        original_search = window.isearch
        original_hook = window.keydown_hook_old
        self.start(window)
        self.assertIs(window.isearch, original_search)
        self.assertIs(window.keydown_hook_old, original_hook)
        self.type_text(window, "BACKUP")
        self.assertEqual(self.keys(window), ["backup_daily", "open_backup_folder", "sync_backup"])
        self.assertEqual(window.isearch.isearch_value, "BACKUP")
        self.type_text(window, "\b" * 6)
        self.assertEqual(window.items, self.items)
        self.assertEqual(window.isearch.isearch_value, "")

    def test_literal_symbols_spaces_unicode_and_only_command_keys_are_searched(self):
        for query, expected in (("[1]", ["file[1]"]), ("*", ["file*"]), ("?", ["file?"]),
                                (" ", ["foo bar"]), ("日本", ["日本語"]),
                                ("Empty", []), ("空欄", []), ("exe", []), (".", [])):
            with self.subTest(query=query):
                window = self.window()
                self.start(window)
                self.type_text(window, query)
                self.assertEqual(self.keys(window), expected)

    def test_no_matches_recover_and_navigation_is_safe_for_zero_one_and_many(self):
        for query, count in (("missing", 0), ("sync", 1), ("backup", 3), ("", len(self.items))):
            with self.subTest(query=query):
                window = self.window(select=10)
                self.start(window)
                self.type_text(window, query)
                self.assertEqual(len(window.items), count)
                for vk in (self.ckit.VK_END, self.ckit.VK_DOWN, self.ckit.VK_NEXT,
                           self.ckit.VK_HOME, self.ckit.VK_UP, self.ckit.VK_PRIOR):
                    window.onKeyDown(vk, 0)
                    if count:
                        self.assertTrue(0 <= window.select < count)
                        self.assertLessEqual(window.scroll_info.pos, window.select)
                        self.assertLess(window.select, window.scroll_info.pos + window.itemsHeight())
                    else:
                        self.assertEqual((window.select, window.scroll_info.pos), (-1, 0))
                self.type_text(window, "\b" * len(query))
                self.assertEqual(window.items, self.items)
                self.assertGreaterEqual(window.select, 0)

    def test_finish_keeps_key_restores_hook_title_and_single_character_search(self):
        for vk in (self.ckit.VK_RETURN, self.ckit.VK_ESCAPE):
            with self.subTest(vk=vk):
                calls = []
                hook = lambda key, mod, calls=calls: calls.append(key)
                window = self.window(keydown_hook=hook)
                with patch.object(window, "setTitle", wraps=window.setTitle) as title, \
                     patch.object(window, "quit") as quit_window:
                    self.start(window)
                    self.assertEqual(title.call_args.args[0].lstrip(), "Search : _")
                    self.type_text(window, "backup")
                    self.assertEqual(title.call_args.args[0].lstrip(), "Search : backup_")
                    window.onKeyDown(self.ckit.VK_END, 0)
                    self.assertEqual(window.getResult(), 10)
                    window.onKeyDown(vk, 0)
                    self.assertIsNone(window.isearch)
                    self.assertIs(window.keydown_hook, hook)
                    self.assertEqual(window.select, 10)
                    self.assertEqual(window.items, self.items)
                    self.assertEqual(title.call_args.args[0], "Command List")
                    quit_window.assert_not_called()
                    self.type_text(window, "b")
                    self.assertEqual(window.select, 1)
                    window.onKeyDown(vk, 0)
                    quit_window.assert_called_once()

    def test_zero_results_finish_returns_to_start_or_last_valid_key(self):
        for choose_result in (False, True):
            for vk in (self.ckit.VK_RETURN, self.ckit.VK_ESCAPE):
                window = self.window(select=9)
                self.start(window)
                if choose_result:
                    self.type_text(window, "backup")
                    window.onKeyDown(self.ckit.VK_END, 0)
                self.type_text(window, "missing")
                self.assertEqual(window.getResult(), -1)
                window.onKeyDown(vk, 0)
                self.assertEqual(window.items[window.select][1], "sync_backup" if choose_result else "restore_config")

    def test_empty_items_search_can_finish_without_indexing_a_missing_selection(self):
        window = self.window(items=[], select=-1)
        self.start(window)
        self.type_text(window, "missing")
        self.assertEqual(window.getResult(), -1)
        window.onKeyDown(self.ckit.VK_ESCAPE, 0)
        self.assertIsNone(window.isearch)
        self.assertEqual((window.items, window.select), ([], -1))

    def test_page_navigation_moves_within_filtered_candidates(self):
        items = [(f"command_{i:02}", f"command_{i:02}") for i in range(20)]
        window = self.window(items=items)
        self.start(window)
        self.type_text(window, "command")
        height = window.itemsHeight()
        for key, expected in ((self.ckit.VK_NEXT, height - 1), (self.ckit.VK_NEXT, 2 * height - 1),
                              (self.ckit.VK_PRIOR, height), (self.ckit.VK_PRIOR, 0)):
            window.onKeyDown(key, 0)
            self.assertEqual(window.select, expected)
        self.assertEqual(window.isearch.isearch_value, "command")

    def test_relayout_rebuilds_rows_and_scroll_after_filter_and_clear(self):
        items = self.items + [("long_command_" + str(i) * 25, "long_command_" + str(i) * 25) for i in range(20)]
        window = self.window(items=items, select=len(items) - 1)
        self.assertGreater(window.scroll_info.pos, 0)
        self.start(window)
        for query in ("sync", "missing", ""):
            window.isearch.isearch_value = query
            window._setSearchItems(query)
            self.assertEqual(["".join(parts) for parts in window.item_lines], [item[0] for item in window.items])
            self.assertGreaterEqual(window.height(), 1)
            self.assertGreaterEqual(window.scroll_info.pos, 0)
            window.onDpi(1.0)
            self.assertGreaterEqual(window.scroll_info.pos, 0)
            if window.items:
                self.assertLess(window.select, window.scroll_info.pos + window.itemsHeight())
        window.onKeyDown(self.ckit.VK_RETURN, 0)
        self.assertEqual(window.items, items)

    def test_customization_remains_available_and_other_lists_keep_existing_search(self):
        def customize(name, window):
            window.keymap["C-F"] = lambda info: setattr(window, "custom_called", True)
        with patch.object(self.ckit, "callConfigFunc", side_effect=customize):
            window = self.window()
        window.onKeyDown(self.ckit.VK_F, self.ckit.MODKEY_CTRL)
        self.assertTrue(window.custom_called)
        self.assertIsNone(window.isearch)
        for onekey in (True, False):
            window = self.window(cls=self.cmdlist.clnch_listwindow.ListWindow)
            window.onekey_search = onekey
            window.configure()
            window.onKeyDown(self.ckit.VK_F, self.ckit.MODKEY_CTRL)
            self.assertIsNone(window.isearch)
            if onekey:
                self.type_text(window, "b")
                self.assertEqual(window.select, 1)
            else:
                window.onKeyDown(self.ckit.VK_F, 0)
                self.assertIsNotNone(window.isearch)
                self.type_text(window, "backup")
                self.assertEqual(window.items, self.items)

    def test_destroy_restores_search_hook(self):
        window = self.window(keydown_hook=lambda vk, mod: False)
        old_hook = window.keydown_hook
        self.start(window)
        with patch.object(self.ckit.TextWindow, "destroy") as destroy:
            window.destroy()
        destroy.assert_called_once()
        self.assertIsNone(window.isearch)
        self.assertIs(window.keydown_hook, old_hook)

    def test_filtered_key_is_used_for_edit_delete_duplicate_new_and_drop_after_search(self):
        for action in ("enter", "edit", "delete", "duplicate", "new", "drop"):
            with self.subTest(action=action), tempfile.TemporaryDirectory() as temp:
                self.check_list_action(action, temp)

    def check_list_action(self, action, temp):
        ckit = self.ckit
        path = Path(temp, "commands.json")
        data = {name: {"target": {"link": name + ".exe"}} for name in self.names}
        path.write_text(json.dumps(data), encoding="utf-8")
        edited, selections = [], []
        def edit(key, parent_window, **kwargs):
            self.assertIsInstance(parent_window, self.cmdlist.CommandListWindow)
            self.assertFalse(self.parent.isEnabled())
            edited.append((key, kwargs))
        def message_loop(window):
            selections.append(window.items[window.select][1])
            if len(selections) > 1:
                window.cancel()
                return
            self.start(window)
            self.type_text(window, "backup")
            window.onKeyDown(ckit.VK_END, 0)
            with patch.object(window, "quit") as quit_window:
                for key, mod in ((ckit.VK_E, ckit.MODKEY_CTRL), (ckit.VK_INSERT, 0),
                                 (ckit.VK_INSERT, ckit.MODKEY_CTRL), (ckit.VK_DELETE, 0)):
                    window.onKeyDown(key, mod)
                drop_callbacks[-1](0, 0, ["D:/ignored.txt"])
                quit_window.assert_not_called()
            window.onKeyDown(ckit.VK_RETURN, 0)
            self.assertEqual(window.items[window.select][1], "sync_backup")
            if action == "drop":
                drop_callbacks[-1](0, 0, ["D:/drop.txt"])
            else:
                key, mod = {"enter": (ckit.VK_RETURN, 0), "edit": (ckit.VK_E, ckit.MODKEY_CTRL),
                            "delete": (ckit.VK_DELETE, 0), "duplicate": (ckit.VK_INSERT, ckit.MODKEY_CTRL),
                            "new": (ckit.VK_INSERT, 0)}[action]
                window.onKeyDown(key, mod)
        drop_callbacks = []
        original_init = ckit.TextWindow.__init__
        def init(window, **kwargs):
            drop_callbacks.append(kwargs["dropfiles_handler"])
            original_init(window, **kwargs)
        self.parent.centerOfWindowInPixel = lambda: (300, 250)
        with patch.object(ckit, "dataPath", return_value=temp), \
             patch.object(ckit.TextWindow, "__init__", init), \
             patch.object(ckit.TextWindow, "messageLoop", message_loop), \
             patch.object(self.cmdlist, "_confirm_delete", return_value=True):
            self.cmdlist.open_list(self.parent, on_edit=edit)
        result = json.loads(path.read_text(encoding="utf-8"))
        if action in ("enter", "edit"):
            self.assertEqual(edited, [("sync_backup", {})])
            self.assertEqual(selections[-1], "sync_backup")
        elif action == "delete":
            self.assertEqual(set(result), set(data) - {"sync_backup"})
        elif action == "duplicate":
            self.assertEqual(result["sync_backup_copy_1"]["target"]["link"], "sync_backup.exe")
            self.assertEqual(selections[-1], "sync_backup_copy_1")
        elif action == "new":
            self.assertEqual(edited, [(None, {})])
        else:
            self.assertEqual(edited, [(None, {"dropped_files": ["D:/drop.txt"]})])


if __name__ == "__main__":
    unittest.main()
