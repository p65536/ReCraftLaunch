"""Modifier settings and menu checks; native windows are replaced. Run with -B."""
import ast
import configparser
import io
import sys
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace

from test_modal_lifecycle import (
    _cleanup_on_exit,
    _modal_dialog_scope,
    _split_list_result,
)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "clnch"))
import clnch_modifierconfig as settings_module


def display_cells(text):
    # Include ambiguous-width symbols in the two-cell estimate.
    return sum(1 if ord(ch) < 128 else 2 for ch in text)


class Ini:
    def __init__(self):
        self.parser = configparser.RawConfigParser()
        self.writes = 0

    def get(self, section, name, default):
        return self.parser.get(section, name, fallback=default)

    def set(self, section, name, value):
        if not self.parser.has_section(section):
            self.parser.add_section(section)
        self.parser.set(section, name, value)

    def write(self):
        self.writes += 1


class ModifierSettingsTests(unittest.TestCase):
    def setUp(self):
        self.ini = Ini()
        self.events = []
        self.window = SimpleNamespace(isEnabled=lambda: True, modifier_settings=settings_module.DEFAULTS.copy(),
            enable=lambda flag: self.events.append(("enable", flag)),
            activate=lambda: self.events.append("activate"),
            centerOfWindowInPixel=lambda: (100, 100),
            getStringWidth=display_cells,
            configure=lambda: self.fail("Do not reload personal hooks"))
        self.namespace = {"ExitStack": ExitStack, "_cleanup_on_exit": _cleanup_on_exit, "sys": sys, "strings": __import__("clnch_strings"), "clnch_modifierconfig": settings_module, "_configValuePreview": lambda window, value: value, "clnch_ini": self.ini,
            "clnch_misc": SimpleNamespace(adjustWindowPosition=lambda *args, **kwargs: None,
                _modal_dialog_scope=_modal_dialog_scope),
            "clnch_listwindow": SimpleNamespace(_split_list_result=_split_list_result),
            "clnch_msgbox": SimpleNamespace(MSGBOX_TYPE_OK=0,
                popMessageBox=lambda *args: self.events.append("error")),
            "VK_INSERT": 45, "VK_DELETE": 46, "VK_UP": 38, "VK_DOWN": 40, "MODKEY_CTRL": 2}
        tree = ast.parse((ROOT / "clnch/clnch_configmenu.py").read_text(encoding="utf-8-sig"))
        nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef)
                 and (n.name.startswith("_configModifier") or n.name in ("_saveModifierSettings", "_editModifierRoot", "_iterConfigMenu"))]
        exec(compile(ast.Module(body=nodes, type_ignores=[]), "modifier-menu-test", "exec"), self.namespace)  # noqa: S102  # Execute isolated source under test.

    def test_defaults_do_not_write_ini(self):
        self.assertEqual(settings_module.read(self.ini), settings_module.DEFAULTS)
        self.assertEqual(self.ini.parser.sections(), [])
        self.assertEqual(self.ini.writes, 0)

    def test_roundtrip_keeps_source_order_unc_and_clears_values(self):
        settings = dict(settings_module.DEFAULTS, CTRL_ACTION="mapped_folder",
            SOURCE_ROOTS=(r"D:\Portable Apps", r"C:\Programs", r"\\offline\share"),
            CTRL_DESTINATION_ROOT=r"\\offline\related")
        self.ini.set("OTHER", "keep", "value")
        settings_module.write(self.ini, settings)
        stream = io.StringIO()
        self.ini.parser.write(stream)
        self.ini.parser.read_string(stream.getvalue())
        self.assertEqual(settings_module.read(self.ini), settings)
        self.assertEqual(self.ini.parser["OTHER"]["keep"], "value")
        settings_module.write(self.ini, settings_module.DEFAULTS)
        self.assertEqual(settings_module.read(self.ini), settings_module.DEFAULTS)

    def test_tab_indented_continuation_roundtrips_as_separate_paths(self):
        text = "[MODIFIER]\nsource_roots = D:\\Programs\n\tZ:\\Programs\n"
        self.ini.parser.read_string(text)
        settings = settings_module.read(self.ini)
        self.assertEqual(settings["SOURCE_ROOTS"], (r"D:\Programs", r"Z:\Programs"))
        settings_module.write(self.ini, settings)
        stream = io.StringIO()
        self.ini.parser.write(stream)
        self.assertIn("source_roots = D:\\Programs\n\tZ:\\Programs\n", stream.getvalue())
        self.ini.parser = configparser.RawConfigParser()
        self.ini.parser.read_string(stream.getvalue())
        self.assertEqual(settings_module.read(self.ini)["SOURCE_ROOTS"], settings["SOURCE_ROOTS"])

    def test_invalid_action_and_paths_rejected_before_write(self):
        for changes in ({"CTRL_ACTION": "fixed_link"}, {"SOURCE_ROOTS": ("relative",)},
                        {"CTRL_DESTINATION_ROOT": "relative"},
                        {"SOURCE_ROOTS": ("C:\\bad\nC:\\other",)}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                settings_module.write(self.ini, dict(settings_module.DEFAULTS, **changes))
        self.assertEqual(self.ini.parser.sections(), [])
        self.ini.set("MODIFIER", "ctrl_action", "invalid")
        with self.assertRaises(ValueError):
            settings_module.read(self.ini)

    def test_save_applies_only_changed_settings_and_preserves_custom_keys(self):
        self.window.cmd_keymap = {"Tab": "custom"}
        save = self.namespace["_saveModifierSettings"]
        save(self.window, CTRL_ACTION="none")
        self.assertEqual(self.ini.writes, 0)
        save(self.window, CTRL_ACTION="execute")
        self.assertEqual(self.ini.writes, 1)
        self.assertEqual(self.window.modifier_settings["CTRL_ACTION"], "execute")
        self.assertEqual(self.window.cmd_keymap, {"Tab": "custom"})
        self.assertEqual(self.events, [])

    def menu_results(self, results):
        iterator = iter(results)
        self.menus = []
        self.menu_widths = []
        def popup(window, width, height, title, items, initial, **kwargs):
            status = kwargs["statusbar_handler"](width, initial) if "statusbar_handler" in kwargs else ""
            actual_width = max(kwargs.get("min_width", 5), min(width, max(map(display_cells, items))))
            if status:
                self.assertLessEqual(display_cells(status) + 2, actual_width, title + ": " + status)
            self.assertEqual(actual_width,
                min(width, max(5, max(map(display_cells, items)), display_cells(status) + 2 if status else 0)))
            self.menus.append((title, items[:], status))
            self.menu_widths.append(actual_width)
            return next(iterator)
        self.namespace["clnch_listwindow"].popMenu = popup

    def test_parent_menu_contains_only_three_modifiers_and_routes(self):
        self.menu_results([0, 1, 2, -1])
        routes = []
        self.namespace["_configModifier"] = lambda window, modifier, label: routes.append((modifier, label))
        self.namespace["_configModifiers"](self.window)
        self.assertEqual(routes, list(settings_module.MODIFIERS))
        self.assertEqual([s.split(":")[0] for s in self.menus[0][1]], ["Ctrl", "Shift", "Ctrl+Shift"])

    def test_action_choices_conditional_roots_missing_status_and_cancel(self):
        self.menu_results([0, 3, -1])
        self.namespace["_configModifier"](self.window, "CTRL", "Ctrl")
        self.assertEqual(len(self.menus[0][1]), 1)
        self.assertEqual(self.menus[1][1], list(settings_module.ACTIONS.values()))
        self.assertEqual(len(self.menus[-1][1]), 3)
        self.assertIn("未登録", self.menus[-1][1][1])
        self.assertIn("実行されません", self.menus[-1][2])
        self.assertEqual(self.ini.writes, 1)
        self.menu_results([0, -1, -1])
        self.namespace["_configModifier"](self.window, "CTRL", "Ctrl")
        self.assertEqual(self.ini.writes, 1)

    def test_hints_fit_all_actions_and_both_missing_root_states(self):
        for modifier, label in settings_module.MODIFIERS:
            for action in settings_module.ACTIONS:
                for sources, destination in (((), ""), ((r"C:\Programs",), ""),
                                             ((r"C:\Programs",), r"D:\Related")):
                    with self.subTest(modifier=modifier, action=action, sources=sources, destination=destination):
                        self.window.modifier_settings.update(SOURCE_ROOTS=sources,
                            **{modifier + "_ACTION": action, modifier + "_DESTINATION_ROOT": destination})
                        self.menu_results([-1])
                        self.namespace["_configModifier"](self.window, modifier, label)

    def test_long_destination_uses_preview_and_is_kept_intact(self):
        destination = "D:\\" + "長いフォルダ" * 200
        self.namespace["_configValuePreview"] = lambda window, value: "D:/preview"
        self.window.modifier_settings.update(CTRL_ACTION="mapped_folder", SOURCE_ROOTS=(r"C:\Programs",),
                                            CTRL_DESTINATION_ROOT=destination)
        self.menu_results([-1])
        self.namespace["_configModifier"](self.window, "CTRL", "Ctrl")
        self.assertTrue(self.menus[0][1][-1].endswith("D:/preview"))
        self.assertEqual(self.window.modifier_settings["CTRL_DESTINATION_ROOT"], destination)

    def test_destination_can_be_set_cleared_and_cancelled(self):
        self.window.modifier_settings["CTRL_ACTION"] = "mapped_folder"
        for value in (r"\\offline\share", "", None):
            before = self.window.modifier_settings.copy()
            self.menu_results([2, -1])
            self.namespace["_editModifierRoot"] = lambda *args, **kwargs: value  # noqa: B023  # Used within this test iteration.
            self.namespace["_configModifier"](self.window, "CTRL", "Ctrl")
            self.assertEqual(self.window.modifier_settings["CTRL_DESTINATION_ROOT"],
                             before["CTRL_DESTINATION_ROOT"] if value is None else value)
        self.assertEqual(self.ini.writes, 2)

    def source_windows(self, operations):
        iterator = iter(operations)
        events = self.events
        widths = self.source_widths = []
        class ListWindow:
            def __init__(self, *args, **kwargs):
                self.items = args[9]
                self.kwargs = kwargs
                self.result = kwargs["initial_select"]
                hint = kwargs["statusbar_handler"](args[2], self.result)
                assert display_cells(hint) + 2 <= args[2]
                widths.append(max(args[2], min(args[4], max(map(display_cells, self.items)))))
            def show(self, visible): pass
            def quit(self): pass
            def cancel(self): self.result = -1
            def getResult(self): return self.result
            def messageLoop(self):
                select, key = next(iterator)
                self.result = select(self.items) if callable(select) else select
                if key:
                    if key == "close":
                        self.onClose()
                    else:
                        self.kwargs["keydown_hook"](*key)
            def destroy(self): events.append("destroy")
        self.namespace["clnch_listwindow"].ListWindow = ListWindow

    def test_source_list_uses_content_width_without_changing_paths(self):
        for roots in ((), ("D:\\" + "長いフォルダ" * 200,)):
            self.window.modifier_settings["SOURCE_ROOTS"] = roots
            self.source_windows([(-1, None)])
            self.namespace["_configModifierSources"](self.window)
            self.assertEqual(self.source_widths, [max([55, *map(display_cells, roots)])])
            self.assertEqual(self.window.modifier_settings["SOURCE_ROOTS"], roots)

    def test_sources_add_edit_reorder_delete_and_save_as_one_change(self):
        self.window.modifier_settings["SOURCE_ROOTS"] = (r"C:\Programs", r"D:\Tools")
        values = iter((r"E:\New", r"D:\Edited"))
        self.namespace["_editModifierRoot"] = lambda *args, **kwargs: next(values)
        self.source_windows([(0, (45, 0)), (1, None), (2, (38, 2)),
                             (1, (40, 2)), (0, (46, 0)), (lambda items: len(items) - 2, None)])
        self.namespace["_configModifierSources"](self.window)
        self.assertEqual(self.window.modifier_settings["SOURCE_ROOTS"], (r"D:\Edited", r"E:\New"))
        self.assertEqual(self.ini.writes, 1)
        self.assertEqual(settings_module.read(self.ini), self.window.modifier_settings)
        self.assertEqual(self.events[-3:], [("enable", True), "activate", "destroy"])

    def test_empty_sources_add_row_and_cancel_discard_draft(self):
        self.namespace["_editModifierRoot"] = lambda *args, **kwargs: r"C:\Added"
        for last, key in ((-1, None), (lambda items: len(items) - 1, None), (2, "close")):
            self.source_windows([(0, None), (last, key)])
            self.namespace["_configModifierSources"](self.window)
            self.assertEqual(self.window.modifier_settings["SOURCE_ROOTS"], ())
            self.assertEqual(self.ini.writes, 0)

    def test_delete_last_source_can_be_saved_and_reorder_stops_at_edges(self):
        self.window.modifier_settings["SOURCE_ROOTS"] = (r"C:\Only",)
        self.source_windows([(0, (38, 2)), (0, (40, 2)), (0, (46, 0)), (1, None)])
        self.namespace["_configModifierSources"](self.window)
        self.assertEqual(self.window.modifier_settings["SOURCE_ROOTS"], ())
        self.assertEqual(self.ini.writes, 1)

    def test_source_window_exception_restores_parent_and_does_not_save(self):
        self.source_windows([])
        with self.assertRaises(StopIteration):
            self.namespace["_configModifierSources"](self.window)
        self.assertEqual(self.events[-3:], [("enable", True), "activate", "destroy"])
        self.assertEqual(self.ini.writes, 0)

    def test_path_dialog_retries_invalid_input_then_accepts_offline_unc(self):
        results = iter(((1, {"path": "relative"}), (1, {"path": r" \\offline\share "})))
        events = self.events
        class Dialog:
            RESULT_OK = 1
            Edit = staticmethod(lambda *args: args)
            StaticText = staticmethod(lambda *args, **kwargs: args)
            def __init__(self, *args): pass
            def messageLoop(self): pass
            def getResult(self): return next(results)
            def destroy(self): events.append("destroy")
        self.namespace["ckit"] = SimpleNamespace(Dialog=Dialog, ALIGN_RIGHT=1)
        value = self.namespace["_editModifierRoot"](self.window, "path", "")
        self.assertEqual(value, r"\\offline\share")
        self.assertEqual(self.events.count("error"), 1)
        self.assertEqual(self.events.count("destroy"), 2)
        results = iter(((0, {"path": r"C:\Cancelled"}),))
        self.assertIsNone(self.namespace["_editModifierRoot"](self.window, "path", ""))
        results = iter(((1, {"path": ""}),))
        self.assertEqual(self.namespace["_editModifierRoot"](self.window, "path", "", allow_empty=True), "")

    def test_path_dialog_exception_restores_parent(self):
        events = self.events
        class Dialog:
            Edit = staticmethod(lambda *args: args)
            StaticText = staticmethod(lambda *args, **kwargs: args)
            def __init__(self, *args): pass
            def messageLoop(self): raise RuntimeError("dialog failed")
            def destroy(self): events.append("destroy")
        self.namespace["ckit"] = SimpleNamespace(Dialog=Dialog, ALIGN_RIGHT=1)
        with self.assertRaises(RuntimeError):
            self.namespace["_editModifierRoot"](self.window, "path", "")
        self.assertEqual(self.events[-3:], [("enable", True), "activate", "destroy"])

    def test_root_input_dialog_fits_opening_value_and_explanations_with_total_width_cap(self):
        dialogs = []
        class Dialog:
            RESULT_OK = 1
            Edit = staticmethod(lambda *args: args)
            StaticText = staticmethod(lambda *args, **kwargs: args)
            def __init__(self, parent, title, items):
                dialogs.append(items)
                self.edit = next(item for item in items if len(item) == 5)
            def messageLoop(self): pass
            def getResult(self): return (1, {"path": self.edit[4]})
            def destroy(self): pass
        self.namespace["ckit"] = SimpleNamespace(Dialog=Dialog, ALIGN_RIGHT=1)
        strings = self.namespace["strings"]
        hint_width = max(display_cells(strings.FOLDER_GUIDE), display_cells(strings.CONFIG_EDIT_GUIDE))
        label_width = display_cells("フォルダ") + 2
        for value, explanation, expected in (
                (r"D:\Archives", (), hint_width + 4),
                ("D:\\" + "a" * 50, (), label_width + 53 + 2 + 4),
                ("D:\\" + "日本語" * 8, (), label_width + 51 + 2 + 4),
                ("D:\\" + "a" * 200, (), 76),
                ("D:\\" + "日本語" * 200, (), 76),
                ("", ("説明" * 16,), 68)):
            with self.subTest(value=value, explanation=explanation):
                result = self.namespace["_editModifierRoot"](self.window, "フォルダ", value,
                    allow_empty=True, explanation=explanation)
                edit = next(item for item in dialogs[-1] if len(item) == 5)
                self.assertEqual(edit[2] + 4, expected)
                self.assertLessEqual(edit[2] + 4, 76)
                self.assertTrue(all(display_cells(item[1]) <= edit[2]
                                    for item in dialogs[-1] if len(item) == 2))
                self.assertEqual(dialogs[-1][-1], (0, strings.CONFIG_EDIT_GUIDE))
                self.assertEqual(edit[4], value)
                self.assertEqual(result, value)


if __name__ == "__main__":
    unittest.main()
