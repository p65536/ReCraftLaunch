"""Editor state and event checks with native widgets replaced; run with -B."""
import ast
import configparser
import contextlib
import importlib.util
import io
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

from test_modal_lifecycle import (
    _cleanup_on_exit,
    _modal_dialog_scope,
    _require_data_path,
    _split_list_result,
    load_functions,
)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "clnch"))

import clnch_cmdstore as cmd_store
import clnch_inisettings as ini_settings
import clnch_modifierconfig


class Window:
    windows = {}  # noqa: RUF012  # Shared test window registry.

    def __init__(self, **kwargs):
        self.options = kwargs
        self.closed = False
        self.activation_events = []
        self.handle = (1 << 40) + len(self.windows)
        self.windows[self.handle] = self

    def width(self): return self.options["width"]
    def height(self): return self.options["height"]
    def putString(self, *args): pass
    def charToClient(self, x, y): return x * 10, y * 20
    def getCharSize(self): return 10, 20
    def getFont(self): return "font"
    def getWindowRect(self): return (100, 100, 100 + self.width() * 10 + 16, 100 + 17 * 20 + 36)
    def enableIme(self, enable): pass
    def setPositionAndSize(self, *args): self.pixel_rect = args
    def clientToScreen(self, x, y): return x + 100, y + 200
    def setCursorPos(self, x, y): self.cursor = (x, y)
    def destroy(self): self.destroyed = True
    def getStringWidth(self, text): return len(text)
    def show(self, visible): self.activation_events.append(("show", visible))
    def foreground(self): self.activation_events.append(("foreground", True))
    def activate(self): self.activation_events.append(("activate", True))
    def quit(self): self.closed = True
    def getHWND(self): return self.handle


class TextPlane:
    def __init__(self, window, pos, size, priority):
        self.pos, self.size = pos, size
        self.draws = []
    def setFont(self, font): self.font = font
    def setPosition(self, pos): self.pos = pos
    def putString(self, *args): self.draws.append(args)
    def setCaretPosition(self, *args): self.cursor = args
    def destroy(self): self.destroyed = True


class Edit:
    def destroy(self): self.destroyed = True
    def __init__(self, window, x, y, width, height, text, **kwargs):
        self.x, self.y, self.width, self.height = x, y, width, height
        self.text = text
        self.keys = []
    def setPosSize(self, x, y, width, height):
        self.x, self.y, self.width, self.height = x, y, width, height
    def paint(self): pass
    def enableCursor(self, enable): pass
    def getText(self): return self.text
    def setText(self, text): self.text = text
    def setSelection(self, selection): self.selection = selection
    def onKeyDown(self, vk, mod): self.keys.append((vk, mod))
    def onChar(self, ch, mod): self.text += ch


class Choice(Edit):
    def __init__(self, window, x, y, width, height, message, items, select):
        super().__init__(window, x, y, width, height, "")
        self.item_list, self.select = items, select
    def getValue(self): return self.select
    def onKeyDown(self, vk, mod):
        if vk == 37: self.select = max(0, self.select - 1)
        if vk == 39: self.select = min(len(self.item_list) - 1, self.select + 1)


class EditorTests(unittest.TestCase):
    def setUp(self):
        Window.windows = {}
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "commands.json"
        self.errors = []
        ckit = ModuleType("ckit")
        ckit.__path__ = []
        ckit.TextWindow, ckit.EditWidget = Window, Edit
        misc_tree = ast.parse((ROOT / "ckit/ckit_misc.py").read_text(encoding="utf-8-sig"))
        split = next(n for n in misc_tree.body if isinstance(n, ast.FunctionDef) and n.name == "splitLines")
        exec(compile(ast.Module(body=[split], type_ignores=[]), "split-lines", "exec"), ckit.__dict__)  # noqa: S102  # Execute isolated source under test.
        widget_tree = ast.parse((ROOT / "ckit/ckit_widget.py").read_text(encoding="utf-8-sig"))
        classes = [n for n in widget_tree.body if isinstance(n, ast.ClassDef) and n.name in ("Widget", "ChoiceWidget")]
        widget_env = {"ckit_misc": ckit, "ckitcore": SimpleNamespace(Attribute=lambda **kw: kw),
                      "ckit_theme": SimpleNamespace(getColor=lambda key: key)}
        exec(compile(ast.Module(body=classes, type_ignores=[]), "choice-widget", "exec"), widget_env)  # noqa: S102  # Execute isolated source under test.
        ckit.ChoiceWidget = widget_env["ChoiceWidget"]
        self.limits = (140, 80)
        ckit.getWindowSizeLimits = lambda window: self.limits
        ckit.TextPlane = TextPlane
        ckit.dataPath = lambda: self.temp.name
        ckit.getColor = lambda key: (0, 0, 0) if key == "bg" else (255, 255, 255)
        ckit.getHintColor = lambda: (191, 191, 191)
        ckit.Attribute = lambda **kwargs: kwargs
        const = ModuleType("ckit.ckit_const")
        constants = {"ORIGIN_X_CENTER": 0, "ORIGIN_Y_CENTER": 0, "MODKEY_SHIFT": 4, "MODKEY_ALT": 1,
            "VK_TAB": 9, "VK_RETURN": 13, "VK_ESCAPE": 27, "VK_SPACE": 32,
            "VK_LEFT": 37, "VK_RIGHT": 39, "VK_PRIOR": 33, "VK_NEXT": 34, "ORIGIN_X_LEFT": 0, "ORIGIN_Y_TOP": 0,
            "VK_E": 69, "VK_C": 67, "VK_S": 83, "VK_X": 88, "VK_1": 49, "VK_2": 50, "VK_3": 51,
            "VK_N": 78, "VK_L": 76, "VK_A": 65, "VK_W": 87, "VK_V": 86, "VK_M": 77}
        const.__dict__.update(constants)
        msgbox = SimpleNamespace(MSGBOX_TYPE_OK=0, popMessageBox=lambda *args: self.errors.append(args))
        path_namespace = {"os": os}
        load_functions("clnch/clnch_misc.py", {"replaceMacro"}, path_namespace)
        modules = {"ckit": ckit, "ckit.ckit_const": const, "clnch_msgbox": msgbox,
            "clnch_native": SimpleNamespace(getShellLinkInfo=lambda filename: ("tool.exe", "--fixed", "D:/Work", 7),
                getInternetShortcutInfo=lambda filename: "https://example.invalid/"),
            "clnch_misc": SimpleNamespace(_require_data_path=_require_data_path, _modal_dialog_scope=_modal_dialog_scope,
                replaceMacro=path_namespace["replaceMacro"], adjustWindowPosition=lambda *args, **kwargs: None)}
        modules["ckit.ckit_misc"] = SimpleNamespace(_cleanup_on_exit=_cleanup_on_exit)
        with patch.dict(sys.modules, modules):
            spec = importlib.util.spec_from_file_location("editor_test", ROOT / "clnch/clnch_cmdeditor.py")
            assert spec is not None and spec.loader is not None
            self.module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.module)
        self.module._SetFocus = lambda hwnd: Window.windows[hwnd].activation_events.append(("focus", hwnd))
        self.parent = SimpleNamespace(getWindowRect=lambda: (0, 0, 100, 100), enabled=True,
            activate=lambda: None, getDisplayScaling=lambda: 1.0,
            modifier_settings=clnch_modifierconfig.DEFAULTS.copy())
        self.parent.enable = lambda enabled: setattr(self.parent, "enabled", enabled)
        self.parent.isEnabled = lambda: self.parent.enabled

    def editor(self, data=None, target=None):
        if data is not None:
            self.path.write_text(json.dumps(data), encoding="utf-8")
        return self.module.CommandEditor(self.parent, target)

    def test_initial_position_uses_list_right_edge_or_existing_main_placement(self):
        listing = SimpleNamespace(getWindowRect=lambda: (200, 150, 450, 500), getDisplayScaling=lambda: 1.0)
        with patch.object(self.module.clnch_misc, "adjustWindowPosition") as below, \
             patch.object(self.module.CommandEditor, "setPosSize") as position, \
             patch.object(self.module.ckit, "fitWindowToWorkArea", create=True) as fit:
            direct = self.module.CommandEditor(self.parent)
            below.assert_called_once_with(self.parent, direct, default_up=False)
            fit.assert_not_called()
            below.reset_mock()
            position.reset_mock()
            for files in (None, ["D:/tool.exe"]):
                editor = self.module.CommandEditor(self.parent, dropped_files=files, parent_window=listing)
                self.assertIs(editor.options["parent_window"], listing)
                position.assert_called_with(450, 150, editor.width(), editor.height(), 0)
                fit.assert_called_with(editor)
            below.assert_not_called()

    def test_relative_link_warning_keeps_file_fields_and_allows_correction(self):
        for link in ("tools/tool.exe", r".\tool.exe", "../folder", r"\tools\tool.exe", "C:tool.exe",
                     "%RECRAFT_RELATIVE%/tool.exe", "tools/%param%"):
            with self.subTest(link=link), patch.dict(os.environ, RECRAFT_RELATIVE="tools"):
                editor = self.editor({"good": {"target": {"link": "notepad.exe"}}})
                before = self.path.read_bytes()
                editor.edit_by_id["name"].setText("bad")
                editor.edit_by_id["link"].setText(link)
                editor.edit_by_id["workdir"].setText("C:/Tools")
                self.assertFalse(editor._save())
                self.assertEqual(self.path.read_bytes(), before)
                self.assertEqual(editor.edit_by_id["link"].getText(), link)
                self.assertFalse(editor.result_saved)
                self.assertFalse(editor.closed)
                self.assertEqual(self.errors[-1][-1], self.module.strings.COMMAND_RELATIVE_LINK_GUI)
                self.assertEqual(len(self.errors[-1][-1].splitlines()), 2)
                editor.edit_by_id["link"].setText("notepad.exe")
                self.assertTrue(editor._save())
                editor.destroy()

    def test_link_validation_checks_all_edited_modifiers_but_not_other_commands(self):
        data = {"edited": {"target": {"link": "notepad.exe"}, "on_shift": {"link": "../folder"}},
                "other": {"target": {"link": "tools/other.exe"}}}
        editor = self.editor(data, "edited")
        self.assertFalse(editor._save())
        editor.draft._actions["on_shift"]["link"] = "C:/Folder"
        self.assertTrue(editor._save())
        self.assertEqual(cmd_store.load_commands(self.path)["other"]["target"]["link"], "tools/other.exe")
        editor.destroy()

    def test_editor_retains_aliases_environment_absolute_paths_and_runtime_link_macros(self):
        for link in ("notepad.exe", "ms-settings:display", "https://example.org/a/b", "child",
                     "%RECRAFT_ABSOLUTE%/tool.exe", "%param%/tool.exe"):
            with self.subTest(link=link), patch.dict(os.environ, RECRAFT_ABSOLUTE="C:/Tools"):
                editor = self.editor({"child": {"target": {"link": "C:/Tools/tool.exe"}}})
                editor.edit_by_id["name"].setText("new")
                editor.edit_by_id["link"].setText(link)
                self.assertTrue(editor._save())
                self.assertEqual(cmd_store.load_commands(self.path)["new"]["target"]["link"], link)
                editor.destroy()

    def test_control_gaps_are_independent_of_text_height_and_scale(self):
        for scale in (1.0, 1.5, 2.0):
            with self.subTest(scale=scale):
                self.parent.getDisplayScaling = lambda: scale  # noqa: B023  # Used within this test iteration.
                editor = self.editor()
                gap = round(8 * scale)
                for previous, current in zip(editor.controls, editor.controls[1:]):
                    bottom = editor.charToClient(0, previous.y + 1)[1]
                    top = editor.charToClient(0, current.y)[1]
                    self.assertEqual(top - bottom, gap)
                    self.assertFalse(editor._on_left_button_down(150, bottom, 0))
                    self.assertFalse(editor._on_left_button_down(150, top - 1, 0))
                self.assertEqual(editor.pixel_rect[3], 8 * 20 + 9 * gap + 2)
                self.assertEqual(editor._row_planes[1].size[1], 20)
                editor.setCursorPos(15, 3)
                self.assertEqual(editor._row_planes[3].cursor, (15, 0))
                self.assertEqual(editor.charToScreen(15, 3),
                    tuple(a + b for a, b in zip(editor.charToClient(15, 3), (100, 200))))
                editor.destroy()
                self.assertTrue(all(plane.destroyed for plane in editor._row_planes.values()))

    def test_modifier_hint_shows_current_default_action_regardless_of_link(self):
        editor = self.editor()
        paints = []
        editor.putString = lambda *args: paints.append(args)
        def hint():
            paints.clear()
            editor.paint()
            draw = next(args for args in paints if args[1] == 13 and args[-1].strip())
            self.assertEqual(draw[:4], (2, 13, 63, 1))
            self.assertEqual(draw[4], {"fg": (191, 191, 191)})
            return draw[-1]
        self.assertEqual(hint(), "修飾キーなしEnter時の動作")
        for index, (modifier, _) in enumerate(clnch_modifierconfig.MODIFIERS, 1):
            editor.modifier_choice.select = index
            editor._switch_modifier()
            self.parent.modifier_settings["SOURCE_ROOTS"] = ("D:/private-source",)
            self.parent.modifier_settings[modifier + "_DESTINATION_ROOT"] = "E:/private-destination"
            for action, description in clnch_modifierconfig.ACTIONS.items():
                for link in ("", "individual.exe"):
                    with self.subTest(modifier=modifier, action=action, link=link):
                        self.parent.modifier_settings[modifier + "_ACTION"] = action
                        editor.edit_by_id["link"].setText(link)
                        self.assertEqual(hint(), "未登録時: " + description)

    def test_modifier_hint_reports_each_mapping_configuration_gap(self):
        editor = self.editor()
        paints = []
        editor.putString = lambda *args: paints.append(args)
        for index, (modifier, _) in enumerate(clnch_modifierconfig.MODIFIERS, 1):
            self.parent.modifier_settings[modifier + "_ACTION"] = "mapped_folder"
            editor.modifier_choice.select = index
            editor._switch_modifier()
            cases = (
                ((), "", "基点置換（置換元・置換先が未設定）"),
                ((), "E:/private-destination", "基点置換（置換元が未登録）"),
                (("D:/private-source",), "", "基点置換（置換先が未設定）"),
                (("D:/private-source",), "E:/private-destination", "基点を置換してフォルダを開く"),
            )
            for sources, destination, description in cases:
                with self.subTest(modifier=modifier, sources=sources, destination=destination):
                    self.parent.modifier_settings["SOURCE_ROOTS"] = sources
                    self.parent.modifier_settings[modifier + "_DESTINATION_ROOT"] = destination
                    paints.clear()
                    editor.paint()
                    hint = next(args[-1] for args in paints if args[1] == 13 and args[-1].strip())
                    self.assertEqual(hint, "未登録時: " + description)

    def test_switch_keeps_four_actions_and_name(self):
        editor = self.editor()
        self.assertEqual(editor.focus_index, 0)
        editor.edit_by_id["name"].setText("test")
        for index in range(4):
            editor.modifier_choice.select = index
            editor._switch_modifier()
            editor.edit_by_id["link"].setText(f"tool{index}.exe")
            editor.edit_by_id["args"].setText(f"arg{index}")
            editor.edit_by_id["workdir"].setText(f"D:/Work{index}")
            editor.view_choice.select = index % 3
        editor.modifier_choice.select = 0
        editor._switch_modifier()
        self.assertEqual(editor.edit_by_id["link"].getText(), "tool0.exe")
        self.assertEqual(editor.edit_by_id["name"].getText(), "test")
        self.assertTrue(editor._save())
        result = json.loads(self.path.read_text(encoding="utf-8"))["test"]
        for index, key in enumerate(self.module.MODIFIERS):
            self.assertEqual(result[key], {"link": f"tool{index}.exe", "args": f"arg{index}",
                "workdir": f"D:/Work{index}", "view_mode": self.module.VIEW_MODES[index % 3]})

    def test_new_and_drop_do_not_inherit_empty_name_command(self):
        data = {"": {key: {"link": f"existing{index}.exe", "args": "--fixed",
            "workdir": "D:/Existing", "view_mode": "maximized"}
            for index, key in enumerate(self.module.MODIFIERS)}}
        for dropped in (False, True):
            with self.subTest(dropped=dropped):
                self.path.write_text(json.dumps(data), encoding="utf-8")
                editor = self.module.CommandEditor(self.parent,
                    dropped_files=["D:/New.exe"] if dropped else None)
                self.assertFalse(editor.draft.is_edit_mode)
                for index in range(4):
                    editor.modifier_choice.select = index
                    editor._switch_modifier()
                    self.assertEqual(editor.edit_by_id["link"].getText(),
                        "D:/New.exe" if dropped and index == 0 else "")
                    self.assertEqual(editor.edit_by_id["args"].getText(), "")
                    self.assertEqual(editor.edit_by_id["workdir"].getText(),
                        "D:/" if dropped and index == 0 else "")
                    self.assertEqual(editor.view_choice.getValue(), 0)
                editor.edit_by_id["name"].setText("new")
                editor.modifier_choice.select = 0
                editor._switch_modifier()
                editor.edit_by_id["link"].setText("D:/New.exe")
                self.assertTrue(editor._save())
                saved = json.loads(self.path.read_text(encoding="utf-8"))
                self.assertEqual(saved[""], data[""])
                self.assertEqual(list(saved["new"]), ["target"])

    def test_edit_empty_name_command_loads_all_modifiers(self):
        data = {"": {key: {"link": f"existing{index}.exe", "args": "--fixed",
            "workdir": "D:/Existing", "view_mode": "maximized"}
            for index, key in enumerate(self.module.MODIFIERS)}}
        editor = self.editor(data, "")
        self.assertTrue(editor.draft.is_edit_mode)
        for index in range(4):
            editor.modifier_choice.select = index
            editor._switch_modifier()
            self.assertEqual(editor.edit_by_id["link"].getText(), f"existing{index}.exe")
            self.assertEqual(editor.edit_by_id["args"].getText(), "--fixed")
            self.assertEqual(editor.edit_by_id["workdir"].getText(), "D:/Existing")
            self.assertEqual(editor.view_choice.getValue(), 2)
        self.assertTrue(editor._save())
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")), data)

    def test_empty_command_name_is_disabled_and_focus_skips_it(self):
        for data in ({}, {"": {"target": {"link": "tool.exe"}}}):
            with self.subTest(data=data):
                editor = self.editor(data, "")
                self.assertEqual(editor.focus_index, 1)
                self.assertEqual(editor.edit_by_id["name"].getText(), "")
                self.assertEqual(editor._label_draws[0][-1], "Name")
                paints = []
                editor.putString = lambda *args, draws=paints: draws.append(args)
                editor.paint()
                name_draw = next(args for args in paints if args[-1] == "(空欄コマンド)")
                self.assertEqual(name_draw[4], {"fg": (191, 191, 191)})
                editor._on_keydown(9, 4)
                self.assertEqual(editor.focus_index, 5)
                editor._on_keydown(9, 0)
                self.assertEqual(editor.focus_index, 1)
                editor._on_keydown(78, 1)
                self.assertEqual(editor.focus_index, 1)
                name = editor.edit_by_id["name"]
                x, y = editor.charToClient(name.x + 1, name.y)
                editor._on_left_button_down(x, y, 0)
                editor._on_char("x", 0)
                editor._on_keydown(86, 2)
                self.assertEqual(editor.focus_index, 1)
                self.assertEqual(name.getText(), "")
                editor._on_drop_files(x, y, ["D:/renamed.exe"])
                self.assertEqual(name.getText(), "")
                self.assertEqual(editor.edit_by_id["link"].getText(),
                    data.get("", {}).get("target", {}).get("link", "") + "x")
                editor._apply_drop("link", ["D:/updated.exe"], suggest_name=True)
                self.assertEqual(name.getText(), "")
                self.assertTrue(editor._save())
                result = json.loads(self.path.read_text(encoding="utf-8"))
                self.assertEqual(list(result), [""])
                self.assertEqual(result[""]["target"]["link"], "D:/updated.exe")

    def test_empty_editor_returns_empty_saved_key(self):
        with patch.object(self.module.CommandEditor, "messageLoop",
                lambda editor: (editor.edit_by_id["link"].setText("tool.exe"), editor._save()), create=True), \
             patch.object(Edit, "destroy", create=True):
            self.assertEqual(self.module.open_editor(self.parent, ""), "")

    def test_tab_access_keys_space_and_char_dispatch(self):
        editor = self.editor()
        for index in range(1, 6):
            editor._on_keydown(9, 0)
            self.assertEqual(editor.focus_index, index)
        editor._on_keydown(32, 0)
        self.assertEqual(editor.draft.modifier_index, 1)
        editor._on_char(" ", 0)
        self.assertEqual(editor.edit_by_id["name"].getText(), "")
        editor._on_keydown(9, 4)
        self.assertEqual(editor.focus_index, 4)
        editor._on_keydown(39, 0)
        self.assertEqual(editor.view_choice.getValue(), 1)
        editor._on_keydown(87, 1)
        self.assertEqual(editor.focus_index, 3)
        editor._on_char("日", 0)
        self.assertEqual(editor.edit_by_id["workdir"].getText(), "日")

    def test_enter_saves_from_every_control(self):
        for index in range(6):
            with self.subTest(index=index):
                editor = self.editor({})
                editor.edit_by_id["name"].setText("name")
                editor.edit_by_id["link"].setText("tool.exe")
                editor.focus_index = index
                editor._on_keydown(13, 0)
                self.assertTrue(editor.result_saved)

    def test_mouse_choices_and_input_focus(self):
        editor = self.editor()
        # ChoiceWidget paints items at x+2, separated by two character cells.
        x = editor.charToClient(editor.view_choice.x + 4 + len(editor.view_choice.item_list[0]), 9)[0]
        self.assertTrue(editor._on_left_button_down(x, editor.charToClient(0, 9)[1], 0))
        self.assertEqual(editor.view_choice.getValue(), 1)
        x = editor.charToClient(editor.modifier_choice.x + 4 + len(editor.modifier_choice.item_list[0]), 11)[0]
        self.assertTrue(editor._on_left_button_down(x, editor.charToClient(0, 11)[1], 0))
        self.assertEqual(editor.draft.modifier_index, 1)
        self.assertTrue(editor._on_left_button_down(150, editor.charToClient(0, 3)[1], 0))
        self.assertEqual(editor.focus_index, 1)
        self.assertFalse(editor._on_left_button_down(0, 0, 0))

    def test_reopen_rename_and_clear_modifier(self):
        data = {"old": {"target": {"link": "old.exe"}, "on_ctrl": {"link": "ctrl.exe"}}}
        editor = self.editor(data, "old")
        self.assertEqual(editor.focus_index, 0)
        self.assertEqual(editor.edit_by_id["link"].getText(), "old.exe")
        editor.edit_by_id["name"].setText("new")
        editor.modifier_choice.select = 1
        editor._switch_modifier()
        editor.edit_by_id["link"].setText("")
        self.assertTrue(editor._save())
        saved = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertNotIn("old", saved)
        self.assertNotIn("on_ctrl", saved["new"])
        self.assertEqual(saved["new"]["target"]["link"], "old.exe")

    def test_duplicate_json_names_block_editing_and_saving_without_data_loss(self):
        for second in ("Tool", "tool"):
            for target in (None, "tool"):
                with self.subTest(second=second, target=target):
                    self.path.write_text('{"Tool": {"target": {"link": "first.exe"}}, '
                                         '"' + second + '": {"target": {"link": "last.exe"}}}', encoding="utf-8")
                    before = self.path.read_bytes()
                    editor = self.editor(target=target)
                    error = self.module.strings.COMMAND_NAME_DUPLICATE.format(first="Tool", second=second)
                    self.assertEqual(editor.load_error, error)
                    editor.edit_by_id["name"].setText("new")
                    editor.edit_by_id["link"].setText("notepad.exe")
                    with patch.object(self.module, "save_commands") as save:
                        self.assertFalse(editor._save())
                    save.assert_not_called()
                    self.assertEqual(self.errors[-1][-2:], (self.module.strings.ERROR_LOAD_TITLE,
                        self.module.strings.COMMAND_LOAD_BLOCKED.format(error=error)))
                    self.assertEqual(editor.edit_by_id["name"].getText(), "new")
                    self.assertEqual(editor.edit_by_id["link"].getText(), "notepad.exe")
                    self.assertFalse(editor.result_saved)
                    self.assertFalse(editor.closed)
                    self.assertEqual(self.path.read_bytes(), before)
                    editor.destroy()

    def test_cancel_and_load_failure_do_not_write(self):
        original = '{"old":{"target":{"link":"old.exe"}}}'
        self.path.write_text(original, encoding="utf-8")
        editor = self.editor(target="old")
        editor.edit_by_id["link"].setText("changed.exe")
        editor._on_keydown(27, 0)
        self.assertFalse(editor.result_saved)
        self.assertEqual(self.path.read_text(encoding="utf-8"), original)
        self.path.write_text("invalid JSON", encoding="utf-8")
        editor = self.editor()
        editor.edit_by_id["name"].setText("test")
        self.assertFalse(editor._save())
        self.assertTrue(self.errors)
        self.assertEqual(self.path.read_text(encoding="utf-8"), "invalid JSON")

    def test_unfinished_action_reports_error(self):
        editor = self.editor()
        editor.edit_by_id["name"].setText("test")
        editor.edit_by_id["args"].setText("--fixed")
        self.assertFalse(editor._save())
        self.assertFalse(self.path.exists())

    def test_editor_read_failure_blocks_save_and_keeps_fields(self):
        self.path.write_text('{"tool":{"target":{"link":"tool.exe"}}}', encoding="utf-8")
        original = self.path.read_bytes()
        with patch("builtins.open", side_effect=PermissionError("locked")):
            editor = self.editor(target="tool")
        self.assertIsNotNone(editor.load_error)
        editor.edit_by_id["link"].setText("changed.exe")
        self.assertFalse(editor._save())
        self.assertEqual(editor.edit_by_id["link"].getText(), "changed.exe")
        self.assertEqual(self.path.read_bytes(), original)
        self.assertIn("locked", self.errors[-1][3])

    def test_editor_schema_failure_keeps_original_diagnostic_and_blocks_save(self):
        data = {"Tool": {"target": {"link": 1, "unknown": ""}}}
        editor = self.editor(data, "tool")
        original = self.path.read_bytes()
        self.assertEqual(editor.load_error, self.module.strings.ACTION_FORMAT_ERROR.format(name="Tool"))
        self.assertFalse(editor._save())
        self.assertEqual(self.path.read_bytes(), original)

    def test_unchanged_save_skips_file_io_and_marks_no_change(self):
        data = {"alias": {"target": {"link": "tool.exe", "args": "", "workdir": "", "view_mode": "normal"}}}
        editor = self.editor(data, "alias")
        original = self.path.read_bytes()
        with patch.object(cmd_store.tempfile, "NamedTemporaryFile", side_effect=AssertionError("unexpected write")), \
                patch.object(cmd_store.os, "replace", side_effect=AssertionError("unexpected replace")):
            self.assertTrue(editor._save())
        self.assertFalse(editor.commands_changed)
        self.assertEqual(self.path.read_bytes(), original)

    def test_sparse_actions_are_completed_on_save(self):
        data = {"alias": {key: {"link": "child"} for key in self.module.MODIFIERS}}
        editor = self.editor(data, "alias")
        paints = []
        editor.putString = lambda *args: paints.append(args[-1])
        editor.paint()
        self.assertEqual(editor.view_choice.getValue(), 0)
        self.assertFalse(any("ViewMode未指定" in text for text in paints))
        for index in (1, 2, 3, 0):
            editor.modifier_choice.select = index
            editor._switch_modifier()
        editor.edit_by_id["args"].setText("--changed")
        self.assertTrue(editor._save())
        saved = json.loads(self.path.read_text())["alias"]
        self.assertTrue(all(action["view_mode"] == "normal" and set(action) == {"link", "args", "workdir", "view_mode"} for action in saved.values()))
        self.assertEqual(saved["target"]["args"], "--changed")

    def test_explicit_view_mode_selection_is_saved_by_keys_click_and_shortcut(self):
        for select in ("access", "cycle", "click", "shortcut"):
            with self.subTest(select=select):
                editor = self.editor({"alias": {"target": {"link": "child"}}}, "alias")
                if select == "access":
                    editor._on_keydown(49, 1)
                elif select == "cycle":
                    editor.focus_index = 4
                    editor._on_keydown(32, 0)
                    editor._on_keydown(32, 4)
                elif select == "click":
                    editor._on_left_button_down(160, editor.charToClient(0, 9)[1], 0)
                else:
                    editor._apply_drop("link", ["D:/tool.lnk"])
                editor.modifier_choice.select = 1
                editor._switch_modifier()
                self.assertTrue(editor._save())
                self.assertEqual(json.loads(self.path.read_text())["alias"]["target"]["view_mode"],
                    "minimized" if select == "shortcut" else "normal")

    def test_name_collision_preserves_commands_for_rename_new_and_drop(self):
        data = {"a": {"target": {"link": "a.exe"}}, "b": {"target": {"link": "b.exe"}},
            "": {"target": {"link": "empty.exe"}}}
        for source, name in (("a", "B"), ("a", ""), (None, "b"), ("drop", "b")):
            with self.subTest(source=source, name=name):
                editor = self.editor(data, None if source == "drop" else source)
                original = self.path.read_bytes()
                if source == "drop":
                    editor._apply_drop("link", ["D:/b.exe"], suggest_name=True)
                else:
                    editor.edit_by_id["name"].setText(name)
                    editor.edit_by_id["link"].setText("replacement.exe")
                self.assertFalse(editor._save())
                self.assertFalse(editor.result_saved)
                self.assertEqual(self.path.read_bytes(), original)
                self.assertEqual(editor.draft.original_commands, data)
                self.assertTrue(self.errors)
        editor = self.editor(data, "a")
        editor.edit_by_id["name"].setText("A")
        self.assertTrue(editor._save())

    def test_failed_rename_save_preserves_original_and_retry_state(self):
        data = {"a": {"target": {"link": "a.exe"}}}
        editor = self.editor(data, "a")
        original = self.path.read_bytes()
        editor.edit_by_id["name"].setText("renamed")
        with patch.object(cmd_store.os, "replace", side_effect=PermissionError("locked")):
            self.assertFalse(editor._save())
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(editor.draft.original_commands, data)
        self.assertFalse(editor.result_saved)
        self.assertEqual(list(Path(self.temp.name).glob(".commands-*.tmp")), [])
        editor.edit_by_id["name"].setText("a")
        self.assertTrue(editor._save())
        self.assertEqual(list(json.loads(self.path.read_text())), ["a"])

    def test_semicolon_name_notifications_preserve_file_and_allow_correction(self):
        import clnch_strings_en
        import clnch_strings_ja
        data = {"old": {"target": {"link": "old.exe"}}}
        for language in (clnch_strings_ja, clnch_strings_en):
            for source in (None, "old", "drop"):
                with self.subTest(language=language.__name__, source=source):
                    editor = self.editor(data, None if source == "drop" else source)
                    original = self.path.read_bytes()
                    if source == "drop":
                        editor._apply_drop("name", [" Bad;Name "])
                    else:
                        editor.edit_by_id["name"].setText(" Bad;Name ")
                    with patch.object(self.module, "strings", language):
                        self.assertFalse(editor._save())
                    self.assertEqual(self.errors[-1][2:], (language.ERROR_INPUT_TITLE,
                        language.COMMAND_NAME_ERROR.format(name=" bad;name ")))
                    self.assertEqual(self.path.read_bytes(), original)
                    self.assertFalse(editor.result_saved)
                    self.assertFalse(editor.closed)
                    self.assertEqual(editor.draft.original_commands, data)
                    editor.edit_by_id["name"].setText("valid")
                    self.assertTrue(editor._save())
                    self.assertIn("valid", json.loads(self.path.read_text(encoding="utf-8")))

    def test_whitespace_names_preserve_input_and_file_until_corrected(self):
        data = {"old": {"target": {"link": "old.exe"}}}
        for source in (None, "old", "drop"):
            for name in (" foo", "foo ", " foo ", "foo bar", "foo \u00a0bar",
                    "foo\tbar", "foo\nbar", "foo\u3000bar", " \u00a0 "):
                with self.subTest(source=source, name=name):
                    editor = self.editor(data, None if source == "drop" else source)
                    original = self.path.read_bytes()
                    if source == "drop":
                        editor._apply_drop("name", [name])
                    else:
                        editor.edit_by_id["name"].setText(name)
                    entered = editor.edit_by_id["name"].getText()
                    self.assertFalse(editor._save())
                    self.assertEqual(editor.edit_by_id["name"].getText(), entered)
                    self.assertEqual(editor.draft.name, entered.lower())
                    self.assertEqual(self.errors[-1][2:], (self.module.strings.ERROR_INPUT_TITLE,
                        self.module.strings.COMMAND_NAME_ERROR.format(name=entered.lower())))
                    self.assertEqual(self.path.read_bytes(), original)
                    self.assertEqual(editor.draft.original_commands, data)
                    self.assertFalse(editor.result_saved)
                    self.assertFalse(editor.closed)
                    editor.edit_by_id["name"].setText("valid")
                    self.assertTrue(editor._save())
                    self.assertIn("valid", json.loads(self.path.read_text(encoding="utf-8")))

    def test_invalid_loaded_name_blocks_save_without_overwriting_file(self):
        data = {"good": {}, "bad;name": {}}
        editor = self.editor(data, "good")
        original = self.path.read_bytes()
        editor.edit_by_id["name"].setText("valid")
        self.assertFalse(editor._save())
        self.assertEqual(self.path.read_bytes(), original)
        self.assertIn(self.module.strings.COMMAND_NAME_ERROR.format(name="bad;name"), self.errors[-1][3])

    def test_validation_notifications_keep_order_text_and_modifier(self):
        editor = self.editor({"taken": {}}, "")
        self.assertFalse(editor._save())
        self.assertEqual(self.errors[-1][2:],
            (self.module.strings.ERROR_INPUT_TITLE, self.module.strings.COMMAND_LINK_REQUIRED))
        editor = self.editor({"taken": {}})
        editor.edit_by_id["name"].setText("TAKEN")
        editor.edit_by_id["args"].setText("--unfinished")
        self.assertFalse(editor._save())
        self.assertEqual(self.errors[-1][2:],
            (self.module.strings.ERROR_INPUT_TITLE, self.module.strings.COMMAND_DUPLICATE))
        editor.edit_by_id["name"].setText("new")
        for index, modifier in enumerate(self.module.MODIFIER_LABELS):
            editor.modifier_choice.select = index
            editor._switch_modifier()
            editor.edit_by_id["args"].setText("--unfinished")
            self.assertFalse(editor._save())
            self.assertEqual(self.errors[-1][2:], (self.module.strings.ERROR_INPUT_TITLE,
                self.module.strings.MODIFIER_LINK_REQUIRED.format(modifier=modifier)))
            editor.edit_by_id["args"].setText("")
        self.assertFalse(editor.closed)

    def test_read_failure_with_empty_message_blocks_before_reading_fields(self):
        self.path.write_text("{}", encoding="utf-8")
        with patch.object(self.module, "load_commands", side_effect=OSError()):
            editor = self.editor()
        self.assertEqual(self.errors, [])
        with patch.object(editor, "_store_action", side_effect=AssertionError("unexpected field read")):
            self.assertFalse(editor._save())
        self.assertEqual(self.errors[-1][2:], (self.module.strings.ERROR_LOAD_TITLE,
            self.module.strings.COMMAND_LOAD_BLOCKED.format(error="")))
        self.assertEqual(self.path.read_bytes(), b"{}")

    def test_failed_save_keeps_all_modifier_fields_and_retry_saves_once(self):
        editor = self.editor({"old": {"target": {"link": "old.exe"}}}, "old")
        original = self.path.read_bytes()
        expected = {}
        editor.edit_by_id["name"].setText("Renamed")
        for index, modifier in enumerate(self.module.MODIFIERS):
            editor.modifier_choice.select = index
            editor._switch_modifier()
            values = {"link": f"tool{index}.exe", "args": f"--{index}", "workdir": f"D:/Work{index}",
                      "view_mode": self.module.VIEW_MODES[index % 3]}
            for field in ("link", "args", "workdir"):
                editor.edit_by_id[field].setText(values[field])
            editor.view_choice.select = index % 3
            expected[modifier] = values
        with patch.object(cmd_store.os, "replace", side_effect=PermissionError("locked")):
            self.assertFalse(editor._save())
        self.assertFalse(editor.closed)
        self.assertFalse(editor.result_saved)
        self.assertFalse(editor.commands_changed)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(self.errors[-1][2:], (self.module.strings.ERROR_SAVE_TITLE,
            self.module.strings.COMMAND_SAVE_ERROR.format(error="locked")))
        for index, modifier in enumerate(self.module.MODIFIERS):
            editor.modifier_choice.select = index
            editor._switch_modifier()
            for field in ("link", "args", "workdir"):
                self.assertEqual(editor.edit_by_id[field].getText(), expected[modifier][field])
            self.assertEqual(editor.view_choice.getValue(), index % 3)
        with patch.object(cmd_store.os, "replace", wraps=cmd_store.os.replace) as replace:
            self.assertTrue(editor._save())
        replace.assert_called_once()
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")), {"renamed": expected})
        self.assertTrue(editor.closed)

    def test_real_editor_callback_runs_after_cleanup_only_when_changed(self):
        for changed in (False, True):
            with self.subTest(changed=changed):
                self.path.write_text(json.dumps({"tool": {"target": cmd_store.normalize_action({"link": "old.exe"})}}),
                                     encoding="utf-8")
                editors, events = [], []
                def loop(editor, editors=editors, changed=changed):
                    editors.append(editor)
                    editor.edit_by_id["link"].setText("changed.exe" if changed else "old.exe")
                    self.assertTrue(editor._save())
                def on_saved(editors=editors, events=events):
                    self.assertTrue(editors[0].destroyed)
                    self.assertTrue(self.parent.isEnabled())
                    events.append("reload")
                with patch.object(self.module.CommandEditor, "messageLoop", loop, create=True), \
                     patch.object(Edit, "destroy", create=True):
                    self.assertEqual(self.module.open_editor(self.parent, "tool", on_saved=on_saved), "tool")
                self.assertEqual(events, ["reload"] if changed else [])

    def test_choice_keys_cycle_in_both_directions(self):
        editor = self.editor()
        for focus in (4, 5):
            editor.focus_index = focus
            control = editor.controls[focus]
            count = len(control.item_list)
            for key in (39, 32):
                control.select = count - 1
                editor._on_keydown(key, 0)
                self.assertEqual(control.getValue(), 0)
            for key, mod in ((37, 0), (32, 4)):
                control.select = 0
                editor._on_keydown(key, mod)
                self.assertEqual(control.getValue(), count - 1)

    def test_tab_and_access_keys_select_text_without_activation_reset(self):
        editor = self.editor({"test": {"target": {"link": "tool.exe", "args": "--fixed"}}}, "test")
        self.assertEqual(editor.edits[0].selection, [0, 4])
        editor._on_keydown(9, 0)
        self.assertEqual(editor.edits[1].selection, [0, 8])
        editor.edits[1].setSelection([3, 3])
        editor._on_activate(True)
        self.assertEqual(editor.edits[1].selection, [3, 3])
        editor._on_keydown(65, 1)
        self.assertEqual(editor.edits[2].selection, [0, 7])

    def test_focus_marker_and_mouse_retained_selection(self):
        editor = self.editor({"test": {"target": {"link": "tool.exe"}}}, "test")
        paints = []
        editor.putString = lambda *args: paints.append(args)
        editor.active = True
        for index, row in ((4, 9), (5, 11)):
            editor.focus_index = index
            paints.clear()
            editor.paint()
            self.assertEqual([(args[0], args[1]) for args in paints if args[-1] == ">"], [(0, row)])
        editor._focus_field("link")
        self.assertEqual(editor.edits[1].selection, [0, 8])
        editor._on_left_button_down(150, editor.charToClient(0, 3)[1], 0)
        self.assertEqual(editor.edits[1].selection, [0, 8])
        editor.edits[1].setSelection([3, 3])
        editor._on_left_button_down(150, editor.charToClient(0, 3)[1], 0)
        self.assertEqual(editor.edits[1].selection, [3, 3])

    def test_direct_access_keys_select_and_keep_action_values(self):
        editor = self.editor()
        for index, key in enumerate((69, 67, 83, 88)):
            editor._on_keydown(key, 1)
            self.assertEqual(editor.focus_index, 5)
            self.assertEqual(editor.draft.modifier_index, index)
            editor.edit_by_id["link"].setText(f"tool{index}.exe")
            editor._on_keydown(49 + index % 3, 1)
            self.assertEqual(editor.focus_index, 4)
            self.assertEqual(editor.view_choice.getValue(), index % 3)
        for index, key in enumerate((69, 67, 83, 88)):
            editor._on_keydown(key, 1)
            self.assertEqual(editor.edit_by_id["link"].getText(), f"tool{index}.exe")
            self.assertEqual(editor.view_choice.getValue(), index % 3)

    def test_multiple_drop_targets_each_text_field_as_one_string(self):
        files = ["D:/a b.txt", "D:/second.txt"]
        expected = '"D:/a b.txt" D:/second.txt'
        for index, field in enumerate(("name", "link", "args", "workdir")):
            with self.subTest(field=field):
                editor = self.editor()
                editor.modifier_choice.select = 2
                editor._switch_modifier()
                editor._on_drop_files(150, editor.charToClient(0, 1 + index * 2)[1], files)
                self.assertEqual(editor.edit_by_id[field].getText(), expected)
                self.assertEqual(editor.draft.modifier_index, 2)
                self.assertFalse(editor.result_saved)
                self.assertFalse(self.path.exists())

    def test_drop_keeps_other_modifier_and_saves_current_action(self):
        editor = self.editor({"test": {"target": {"link": "original.exe"}, "on_ctrl": {"link": "ctrl.exe"}}}, "test")
        editor._on_keydown(67, 1)
        editor._on_drop_files(150, editor.charToClient(0, 5)[1], ["D:/a b.txt", "D:/second.txt"])
        self.assertEqual(editor.edit_by_id["args"].getText(), '"D:/a b.txt" D:/second.txt')
        self.assertTrue(editor._save())
        saved = json.loads(self.path.read_text(encoding="utf-8"))["test"]
        self.assertEqual(saved["target"]["link"], "original.exe")
        self.assertEqual(saved["on_ctrl"]["link"], "ctrl.exe")
        self.assertEqual(saved["on_ctrl"]["args"], '"D:/a b.txt" D:/second.txt')

    def test_single_shortcut_import_and_failure_preserves_values(self):
        editor = self.editor()
        editor._apply_drop("link", ["D:/My Shortcut.lnk"], suggest_name=True)
        self.assertEqual(editor.edit_by_id["name"].getText(), "MyShortcut")
        self.assertEqual(editor.edit_by_id["link"].getText(), "tool.exe")
        self.assertEqual(editor.edit_by_id["args"].getText(), "--fixed")
        self.assertEqual(editor.edit_by_id["workdir"].getText(), "D:/Work")
        self.assertEqual(editor.view_choice.getValue(), 1)
        with patch.object(self.module.clnch_native, "getShellLinkInfo", side_effect=OSError("bad shortcut")):
            editor._apply_drop("link", ["D:/bad.lnk"])
        self.assertEqual(editor.edit_by_id["link"].getText(), "tool.exe")
        self.assertTrue(self.errors)
        editor._apply_drop("link", ["D:/website.url"])
        self.assertEqual(editor.edit_by_id["link"].getText(), "https://example.invalid/")
        self.assertEqual(editor.edit_by_id["args"].getText(), "")
        self.assertEqual(editor.edit_by_id["workdir"].getText(), "")
        editor = self.editor()
        editor._apply_drop("link", ["D:/My;\u3000Site.url"], suggest_name=True)
        self.assertEqual(editor.edit_by_id["name"].getText(), "MySite")
        self.assertEqual(editor.edit_by_id["link"].getText(), "https://example.invalid/")
        self.assertEqual(editor.edit_by_id["workdir"].getText(), "")

    def test_new_drop_is_prefilled_and_cancel_does_not_save(self):
        editor = self.module.CommandEditor(self.parent, dropped_files=["D:/My Tool.exe"])
        self.assertEqual(editor.edit_by_id["name"].getText(), "MyTool")
        self.assertEqual(editor.edit_by_id["link"].getText(), "D:/My Tool.exe")
        self.assertEqual(editor.edit_by_id["workdir"].getText(), "D:/")
        self.assertEqual(editor.focus_index, 0)
        editor._on_cancel()
        self.assertFalse(self.path.exists())

    def test_new_drop_folder_keeps_dots_and_uses_itself_but_file_uses_parent(self):
        folder = Path(self.temp.name, "my.folder")
        folder.mkdir()
        file = folder / "my.file.exe"
        file.touch()
        for path, name, workdir in ((folder, "my.folder", folder),
                                   (str(folder) + os.sep, "my.folder", str(folder) + os.sep), (file, "my.file", folder)):
            with self.subTest(path=path):
                editor = self.module.CommandEditor(self.parent, dropped_files=[str(path)])
                self.assertEqual(editor.edit_by_id["name"].getText(), name)
                self.assertEqual(editor.edit_by_id["link"].getText(), str(path))
                self.assertEqual(editor.edit_by_id["workdir"].getText(), str(workdir))
                editor._on_cancel()
                self.assertFalse(self.path.exists())

    def test_auto_name_removes_semicolon_and_all_whitespace_without_touching_manual_name(self):
        whitespace = "".join(chr(code) for code in range(sys.maxunicode + 1) if chr(code).isspace())
        editor = self.editor()
        editor._apply_drop("link", ["D:/My;" + whitespace + "Tool.exe"], suggest_name=True)
        self.assertEqual(editor.edit_by_id["name"].getText(), "MyTool")
        self.assertTrue(editor._save())
        self.assertIn("mytool", json.loads(self.path.read_text(encoding="utf-8")))
        manual = " My;\u3000Name "
        editor.edit_by_id["name"].setText(manual)
        editor.edit_by_id["workdir"].setText("D:/edited")
        editor.edit_by_id["args"].setText("--edited")
        editor._apply_drop("link", ["D:/second.exe"])
        self.assertEqual(editor.edit_by_id["name"].getText(), manual)
        self.assertEqual(editor.edit_by_id["workdir"].getText(), "D:/edited")
        self.assertEqual(editor.edit_by_id["args"].getText(), "--edited")
        editor._apply_drop("link", ["D:/third.exe"], suggest_name=True)
        self.assertEqual(editor.edit_by_id["name"].getText(), manual)

    def test_drop_editor_foregrounds_after_show_before_activation(self):
        editor = self.module.CommandEditor(self.parent, dropped_files=["D:/tool.exe"])
        self.assertEqual(editor.activation_events, [("show", True), ("foreground", True), ("activate", True), ("focus", editor.getHWND())])
        self.assertGreater(editor.getHWND(), 1 << 32)
        keyboard_editor = self.editor()
        self.assertEqual(keyboard_editor.activation_events, [("show", True), ("activate", True), ("focus", keyboard_editor.getHWND())])

    def test_drop_list_opens_new_editor_and_restores_selection(self):
        self.path.write_text(json.dumps({"a": {}, "m": {}, "z": {}}), encoding="utf-8")
        windows = []
        events = []
        files = ["D:/a b.txt", "D:/c.txt"]

        class ListWindow:
            isearch = None
            def __init__(self, *args, **kwargs):
                self.options = kwargs
                self.index = len(windows)
                windows.append(self)
            def show(self, visible): pass
            def messageLoop(self):
                if self.index == 0:
                    self.options["dropfiles_handler"](0, 0, files)
            def quit(self): events.append("quit")
            def getResult(self): return 1 if self.index == 0 else -1
            def destroy(self): events.append("destroy")

        ckit = ModuleType("ckit")
        ckit.dataPath = lambda: self.temp.name
        ckit.VK_DELETE, ckit.VK_INSERT, ckit.VK_E, ckit.MODKEY_CTRL = 46, 45, 69, 2
        modules = {"ckit": ckit, "clnch_listwindow": SimpleNamespace(ListWindow=ListWindow, _split_list_result=_split_list_result),
            "clnch_msgbox": self.module.clnch_msgbox,
            "clnch_misc": SimpleNamespace(_require_data_path=_require_data_path, _modal_dialog_scope=_modal_dialog_scope, adjustWindowPosition=lambda *args, **kwargs: None)}
        modules["ckit.ckit_misc"] = SimpleNamespace(_cleanup_on_exit=_cleanup_on_exit)
        with patch.dict(sys.modules, modules):
            spec = importlib.util.spec_from_file_location("list_drop_test", ROOT / "clnch/clnch_cmdlist.py")
            assert spec is not None and spec.loader is not None
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module.CommandListWindow = ListWindow
        def edit(key, dropped_files=None, parent_window=None):
            self.assertIsNone(key)
            self.assertEqual(dropped_files, files)
            self.assertEqual(events, ["quit"])
            self.assertIs(parent_window, windows[0])
        window = SimpleNamespace(centerOfWindowInPixel=lambda: (0, 0),
            isEnabled=lambda: True, enable=lambda enabled: None, activate=lambda: None)
        module.open_list(window, on_edit=edit)
        self.assertEqual(windows[1].options["initial_select"], 1)

    def test_list_keeps_saved_name_or_cancelled_selection(self):
        for saved_key, expected in (("zz", 3), ("", 0), (None, 2)):
            with self.subTest(saved_key=saved_key):
                self.path.write_text(json.dumps({"a": {}, "m": {}, "z": {}}), encoding="utf-8")
                windows = []

                class ListWindow:
                    def __init__(self, *args, **kwargs):
                        self.index = len(windows)  # noqa: B023  # Used within this test iteration.
                        self.initial_select = kwargs["initial_select"]
                        windows.append(self)  # noqa: B023  # Used within this test iteration.
                    def show(self, visible): pass
                    def messageLoop(self): pass
                    def getResult(self): return 2 if self.index == 0 else -1
                    def destroy(self): pass

                ckit = ModuleType("ckit")
                ckit.dataPath = lambda: self.temp.name
                ckit.VK_DELETE, ckit.VK_INSERT, ckit.VK_E, ckit.MODKEY_CTRL = 46, 45, 69, 2
                modules = {"ckit": ckit, "clnch_listwindow": SimpleNamespace(ListWindow=ListWindow, _split_list_result=_split_list_result),
                    "clnch_msgbox": self.module.clnch_msgbox,
                    "clnch_misc": SimpleNamespace(_require_data_path=_require_data_path, _modal_dialog_scope=_modal_dialog_scope, adjustWindowPosition=lambda *args, **kwargs: None)}
                modules["ckit.ckit_misc"] = SimpleNamespace(_cleanup_on_exit=_cleanup_on_exit)
                with patch.dict(sys.modules, modules):
                    spec = importlib.util.spec_from_file_location("list_test", ROOT / "clnch/clnch_cmdlist.py")
                    assert spec is not None and spec.loader is not None
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    module.CommandListWindow = ListWindow
                def edit(key, parent_window=None, windows=windows):
                    self.assertEqual(key, "m")
                    self.assertIs(parent_window, windows[0])
                    if saved_key is not None:  # noqa: B023  # Used within this test iteration.
                        self.path.write_text(json.dumps({"a": {}, "z": {}, saved_key: {}}), encoding="utf-8")  # noqa: B023  # Used within this test iteration.
                    return saved_key  # noqa: B023  # Used within this test iteration.
                window = SimpleNamespace(centerOfWindowInPixel=lambda: (0, 0),
                    isEnabled=lambda: True, enable=lambda enabled: None, activate=lambda: None)
                module.open_list(window, on_edit=edit)
                self.assertEqual(windows[1].initial_select, expected)

    def test_list_delete_uses_safe_save_and_does_not_reload_on_failure(self):
        data = {key: {"target": {"link": key + ".exe"}} for key in ("a", "b", "c")}
        for failure, answer in ((False, 2), (True, 2), (False, 3), (False, 0)):
            with self.subTest(failure=failure, answer=answer):
                self.path.write_text(json.dumps(data), encoding="utf-8")
                original = self.path.read_bytes()
                windows, saved, errors, confirmations = [], [], [], []
                class ListWindow:
                    def __init__(self, *args, **kwargs):
                        self.options = kwargs
                        self.items = args[9]
                        self.index = len(windows)  # noqa: B023  # Used within this test iteration.
                        windows.append(self)  # noqa: B023  # Used within this test iteration.
                    def show(self, visible): pass
                    def messageLoop(self):
                        if self.index == 0:
                            self.options["keydown_hook"](46, 0)
                    def quit(self): pass
                    def getResult(self): return 1 if self.index == 0 else -1
                    def destroy(self): self.destroyed = True
                ckit = ModuleType("ckit")
                ckit.dataPath = lambda: self.temp.name
                ckit.VK_DELETE, ckit.VK_INSERT, ckit.VK_E, ckit.MODKEY_CTRL = 46, 45, 69, 2
                def popup(parent, kind, title, message):
                    self.assertIs(parent, window)  # noqa: B023  # Used within this test iteration.
                    self.assertTrue(windows[0].destroyed)  # noqa: B023  # Used within this test iteration.
                    self.assertFalse(window.enabled)  # noqa: B023  # Used within this test iteration.
                    (confirmations if kind == 1 else errors).append((title, message))  # noqa: B023  # Used within this test iteration.
                    return answer  # noqa: B023  # Used within this test iteration.
                msgbox = SimpleNamespace(MSGBOX_TYPE_OK=0, MSGBOX_TYPE_YESNO=1,
                    MSGBOX_RESULT_YES=2, popMessageBox=popup)
                modules = {"ckit": ckit, "clnch_listwindow": SimpleNamespace(ListWindow=ListWindow, _split_list_result=_split_list_result),
                    "clnch_msgbox": msgbox,
                    "clnch_misc": SimpleNamespace(_require_data_path=_require_data_path, _modal_dialog_scope=_modal_dialog_scope, adjustWindowPosition=lambda *args, **kwargs: None)}
                modules["ckit.ckit_misc"] = SimpleNamespace(_cleanup_on_exit=_cleanup_on_exit)
                with patch.dict(sys.modules, modules):
                    spec = importlib.util.spec_from_file_location("list_save_test", ROOT / "clnch/clnch_cmdlist.py")
                    assert spec is not None and spec.loader is not None
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    module.CommandListWindow = ListWindow
                window = SimpleNamespace(centerOfWindowInPixel=lambda: (0, 0), enabled=True, isEnabled=lambda: True,
                    activate=lambda: None)
                window.enable = lambda enabled: setattr(window, "enabled", enabled)  # noqa: B023  # Used within this test iteration.
                if failure:
                    with patch.object(cmd_store.os, "replace", side_effect=PermissionError("locked")):
                        module.open_list(window, on_saved=lambda: saved.append(True))  # noqa: B023  # Used within this test iteration.
                    self.assertEqual(self.path.read_bytes(), original)
                    self.assertEqual(saved, [])
                    self.assertEqual(len(errors), 1)
                elif answer == 2:
                    module.open_list(window, on_saved=lambda: saved.append(True))  # noqa: B023  # Used within this test iteration.
                    self.assertEqual(json.loads(self.path.read_text()), {key: {"target": {"link": key + ".exe", "args": "", "workdir": "", "view_mode": "normal"}} for key in ("b", "c")})
                    self.assertEqual(saved, [True])
                    self.assertEqual(windows[1].items[windows[1].options["initial_select"]][1], "b")
                else:
                    module.open_list(window, on_saved=lambda: saved.append(True))  # noqa: B023  # Used within this test iteration.
                    self.assertEqual(self.path.read_bytes(), original)
                    self.assertEqual(saved, [])
                self.assertEqual(confirmations, [("Command List - 削除確認", "コマンド 'a' を削除しますか？")])
                self.assertEqual(len(errors), int(failure))
                if failure:
                    self.assertEqual(errors[0][0], "保存エラー")
                    self.assertIn("locked", errors[0][1])
                self.assertEqual(list(Path(self.temp.name).glob(".commands-*.tmp")), [])

    def _run_list_actions(self, actions, on_edit=None):
        windows, saved, messages = [], [], []

        class ListWindow:
            def __init__(self, *args, **kwargs):
                self.items = args[9]
                self.options = kwargs
                self.index = len(windows)
                windows.append(self)
            def show(self, visible): self.visible = visible
            def messageLoop(self):
                if self.index < len(actions):
                    vk, mod, key = actions[self.index]
                    self.result = next(i for i, (_, name) in enumerate(self.items) if name == key)
                    if vk is not None:
                        self.handled = self.options["keydown_hook"](vk, mod)
                else:
                    self.result = -1
            def quit(self): pass
            def getResult(self): return self.result
            def destroy(self): self.destroyed = True

        ckit = ModuleType("ckit")
        ckit.dataPath = lambda: self.temp.name
        ckit.VK_DELETE, ckit.VK_INSERT, ckit.VK_E, ckit.MODKEY_CTRL = 46, 45, 69, 2
        window = SimpleNamespace(centerOfWindowInPixel=lambda: (0, 0), enabled=True, isEnabled=lambda: True,
            activate=lambda: None)
        window.enable = lambda enabled: setattr(window, "enabled", enabled)
        def edit(key, parent_window):
            self.assertFalse(window.enabled)
            self.assertIs(parent_window, windows[-1])
            self.assertTrue(parent_window.visible)
            self.assertFalse(getattr(parent_window, "destroyed", False))
            return on_edit(key)
        def popup(*args):
            self.assertIs(args[0], window)
            self.assertFalse(window.enabled)
            self.assertTrue(windows[-1].destroyed)
            messages.append(args)
        modules = {"ckit": ckit, "clnch_listwindow": SimpleNamespace(ListWindow=ListWindow, _split_list_result=_split_list_result),
            "clnch_ini": SimpleNamespace(getint=lambda section, key, default: default),
            "clnch_msgbox": SimpleNamespace(MSGBOX_TYPE_OK=0, popMessageBox=popup),
            "clnch_misc": SimpleNamespace(_require_data_path=_require_data_path, _modal_dialog_scope=_modal_dialog_scope, adjustWindowPosition=lambda *args, **kwargs: None)}
        modules["ckit.ckit_misc"] = SimpleNamespace(_cleanup_on_exit=_cleanup_on_exit)
        with patch.dict(sys.modules, modules):
            spec = importlib.util.spec_from_file_location("list_actions_test", ROOT / "clnch/clnch_cmdlist.py")
            assert spec is not None and spec.loader is not None
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module.CommandListWindow = ListWindow
        window.isEnabled = lambda: window.enabled
        try:
            module.open_list(window, on_saved=lambda: saved.append(json.loads(self.path.read_text(encoding="utf-8"))),
                on_edit=edit if on_edit else None)
        finally:
            self.assertTrue(window.enabled)
            self.assertTrue(all(w.destroyed for w in windows))
        return windows, saved, messages

    def test_list_displays_invalid_actions_and_duplicate_failure_preserves_file(self):
        self.path.write_text('{"Legacy":{"target":"old.exe"}}', encoding="utf-8")
        original = self.path.read_bytes()
        windows, saved, messages = self._run_list_actions([(45, 2, "legacy")])
        self.assertEqual(windows[0].items, [("(空欄コマンド)", ""), ("legacy", "legacy")])
        self.assertEqual(windows[1].items, windows[0].items)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(saved, [])
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0][2], self.module.strings.ERROR_SAVE_TITLE)

    def test_list_duplicate_copies_all_modifiers_and_selects_smallest_unused_name(self):
        command = {modifier: {"link": f"D:/日本語/{modifier}.exe", "args": f"--{modifier} a b",
            "workdir": f"D:/Work/{modifier}", "view_mode": mode}
            for modifier, mode in (("target", "normal"), ("on_ctrl", "minimized"),
                ("on_shift", "maximized"), ("on_ctrl_shift", "normal"))}
        data = {"tool": command, "TOOL_COPY_1": {}, "tool_copy_3": {}, "z": {}}
        self.path.write_text(json.dumps(data), encoding="utf-8")
        edits = []
        windows, saved, messages = self._run_list_actions([(45, 2, "tool")], on_edit=edits.append)
        result = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(result["tool_copy_2"], command)
        self.assertEqual(result["tool"], command)
        self.assertEqual(result["tool_copy_1"], {})
        self.assertEqual(result["tool_copy_3"], {})
        self.assertEqual(list(result), sorted(result))
        self.assertEqual(windows[1].items[windows[1].options["initial_select"]][1], "tool_copy_2")
        self.assertEqual(saved, [result])
        self.assertEqual(messages, [])
        self.assertEqual(edits, [])

    def test_list_empty_command_delete_is_blocked_without_save_or_reload(self):
        for data in ({}, {"": {"target": {"link": "tool.exe"}}, "other": {}}):
            with self.subTest(data=data):
                self.path.write_text(json.dumps(data), encoding="utf-8")
                original = self.path.read_bytes()
                with patch.object(cmd_store.tempfile, "NamedTemporaryFile", side_effect=AssertionError("unexpected save")):
                    windows, saved, messages = self._run_list_actions([(46, 0, "")])
                self.assertEqual(self.path.read_bytes(), original)
                self.assertEqual(saved, [])
                self.assertEqual(windows[0].items[0][0], "(空欄コマンド)")
                self.assertEqual(windows[1].items[windows[1].options["initial_select"]][1], "")
                self.assertEqual([message[1:] for message in messages],
                    [(0, "Command List", "空欄コマンドは削除出来ません。")])

    def test_list_always_shows_unregistered_empty_entry_without_saving(self):
        for data in (None, {}, {"tool": {}}):
            with self.subTest(data=data):
                if self.path.exists():
                    self.path.unlink()
                if data is not None:
                    self.path.write_text(json.dumps(data), encoding="utf-8")
                original = self.path.read_bytes() if self.path.exists() else None
                edits = []
                with patch.object(cmd_store.tempfile, "NamedTemporaryFile", side_effect=AssertionError("unexpected save")):
                    windows, saved, messages = self._run_list_actions([(None, 0, "")], on_edit=edits.append)
                self.assertEqual(windows[0].items[0], ("(空欄コマンド)", ""))
                self.assertEqual(edits, [""])
                self.assertEqual(self.path.read_bytes() if self.path.exists() else None, original)
                self.assertEqual(saved, [])
                self.assertEqual(messages, [])

    def test_list_first_named_registration_keeps_empty_entry_for_registration(self):
        def edit(key):
            if key == "":
                self.assertNotIn("", json.loads(self.path.read_text(encoding="utf-8")))
            editor = self.module.CommandEditor(self.parent, key)
            if key is None:
                editor.edit_by_id["name"].setText("named")
            editor.edit_by_id["link"].setText("notepad.exe")
            self.assertTrue(editor._save())
            return "named" if key is None else ""
        windows, _, messages = self._run_list_actions([(45, 0, ""), (None, 0, "")], on_edit=edit)
        self.assertEqual(windows[1].items, [("(空欄コマンド)", ""), ("named", "named")])
        self.assertEqual(windows[1].options["initial_select"], 1)
        self.assertEqual(windows[2].options["initial_select"], 0)
        self.assertEqual(set(json.loads(self.path.read_text(encoding="utf-8"))), {"", "named"})
        self.assertEqual(messages, [])

    def test_list_duplicate_suffix_uses_base_name_and_copies_selected_contents(self):
        cases = (
            ("7z_copy_1", ("7z",), "7z_copy_2"),
            ("7z_copy_1", ("7z", "7z_copy_2"), "7z_copy_3"),
            ("7z_copy_2", ("7z",), "7z_copy_1"),
            ("7z_copy_12", ("7z",), "7z_copy_1"),
            ("7z_copy_3", ("7z", "7z_copy_1"), "7z_copy_2"),
            ("unnamed_copy_1", ("",), "unnamed_copy_2"),
            ("_copy_1", (), "unnamed_copy_1"),
            ("tool_copy", (), "tool_copy_copy_1"),
            ("tool_copy_0", (), "tool_copy_0_copy_1"),
            ("tool_copy_-1", (), "tool_copy_-1_copy_1"),
            ("tool_copy_01", (), "tool_copy_01_copy_1"),
            ("tool_copy_1_extra", (), "tool_copy_1_extra_copy_1"),
        )
        command = {"target": {"link": "selected.exe", "args": "--selected", "workdir": "D:/Work", "view_mode": "minimized"}}
        for selected, occupied, expected in cases:
            with self.subTest(selected=selected, occupied=occupied):
                data = {key: {} for key in occupied}
                data[selected] = command
                self.path.write_text(json.dumps(data), encoding="utf-8")
                windows, saved, messages = self._run_list_actions([(45, 2, selected)])
                result = json.loads(self.path.read_text(encoding="utf-8"))
                self.assertEqual(result, {**data, expected: command})
                self.assertEqual(windows[1].items[windows[1].options["initial_select"]][1], expected)
                self.assertEqual(saved, [result])
                self.assertEqual(messages, [])

    def test_list_duplicate_empty_name_sparse_modifiers_and_repeated_copy(self):
        data = {"": {"target": {"link": "tool.exe"}, "on_ctrl": {"link": "ctrl.exe"}},
            "unnamed_copy_2": {}}
        self.path.write_text(json.dumps(data), encoding="utf-8")
        windows, saved, messages = self._run_list_actions([(45, 2, ""), (45, 2, "")])
        result = json.loads(self.path.read_text(encoding="utf-8"))
        expected = {modifier: {"link": action["link"], "args": "", "workdir": "", "view_mode": "normal"}
            for modifier, action in data[""].items()}
        self.assertEqual(result[""], expected)
        self.assertEqual(result["unnamed_copy_1"], expected)
        self.assertEqual(result["unnamed_copy_3"], expected)
        self.assertEqual(len(saved), 2)
        self.assertEqual(messages, [])
        for w, key in zip(windows[1:], ("unnamed_copy_1", "unnamed_copy_3")):
            self.assertEqual(w.items[w.options["initial_select"]][1], key)

    def test_list_duplicate_ignores_empty_list_and_cancel(self):
        for data, actions in (({}, [(45, 2, "")]), ({"tool": {}}, [(45, 2, "")]), ({"tool": {}}, [])):
            with self.subTest(data=data):
                self.path.write_text(json.dumps(data), encoding="utf-8")
                original = self.path.read_bytes()
                with patch.object(cmd_store.tempfile, "NamedTemporaryFile", side_effect=AssertionError("unexpected save")):
                    _, saved, messages = self._run_list_actions(actions)
                self.assertEqual(self.path.read_bytes(), original)
                self.assertEqual(saved, [])
                self.assertEqual(messages, [])

    def test_list_duplicate_failed_write_or_replace_keeps_file_selection_and_can_retry(self):
        data = {"a": {}, "tool": {"target": {"link": "tool.exe"}}}
        def partial_write(commands, output, **kwargs):
            output.write('{"partial":')
            raise OSError("write failed")
        for operation, failure in ((cmd_store.json, "dump"), (cmd_store.os, "replace")):
            with self.subTest(operation=failure):
                self.path.write_text(json.dumps(data), encoding="utf-8")
                original = self.path.read_bytes()
                error = partial_write if failure == "dump" else PermissionError("locked")
                with patch.object(operation, failure, side_effect=error):
                    windows, saved, messages = self._run_list_actions([(45, 2, "tool")])
                self.assertEqual(self.path.read_bytes(), original)
                self.assertEqual(saved, [])
                self.assertEqual(windows[1].items[windows[1].options["initial_select"]][1], "tool")
                self.assertEqual(len(messages), 1)
                self.assertEqual(messages[0][1:3], (0, "保存エラー"))
                self.assertIn("write failed" if failure == "dump" else "locked", messages[0][3])
                self.assertEqual(list(Path(self.temp.name).glob(".commands-*.tmp")), [])
                _, saved, messages = self._run_list_actions([(45, 2, "tool")])
                self.assertEqual(set(saved[0]), {"a", "tool", "tool_copy_1"})
                self.assertEqual(messages, [])

    def test_list_insert_enter_and_ctrl_e_keep_existing_editor_actions(self):
        for vk, mod, expected in ((45, 0, None), (None, 0, "tool"), (69, 2, "tool")):
            with self.subTest(vk=vk, mod=mod):
                self.path.write_text(json.dumps({"tool": {}}), encoding="utf-8")
                original = self.path.read_bytes()
                edits = []
                _, saved, messages = self._run_list_actions([(vk, mod, "tool")], on_edit=edits.append)
                self.assertEqual(edits, [expected])
                self.assertEqual(self.path.read_bytes(), original)
                self.assertEqual(saved, [])
                self.assertEqual(messages, [])

    def test_list_read_error_and_command_confirmation_use_custom_popup(self):
        self.path.write_text("{broken", encoding="utf-8")
        ckit = ModuleType("ckit")
        ckit.dataPath = lambda: self.temp.name
        ckit.VK_DELETE, ckit.VK_INSERT, ckit.VK_E, ckit.MODKEY_CTRL = 46, 45, 69, 2
        messages = []
        msgbox = SimpleNamespace(MSGBOX_TYPE_OK=0, MSGBOX_TYPE_YESNO=1,
            MSGBOX_RESULT_YES=2, popMessageBox=lambda *args: messages.append(args) or 2)
        modules = {"ckit": ckit, "clnch_msgbox": msgbox,
            "clnch_listwindow": SimpleNamespace(ListWindow=object, _split_list_result=_split_list_result), "clnch_misc": SimpleNamespace(_require_data_path=_require_data_path, )}
        modules["ckit.ckit_misc"] = SimpleNamespace(_cleanup_on_exit=_cleanup_on_exit)
        with patch.dict(sys.modules, modules):
            spec = importlib.util.spec_from_file_location("list_error_test", ROOT / "clnch/clnch_cmdlist.py")
            assert spec is not None and spec.loader is not None
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        parent = object()
        module.open_list(parent)
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0][:3], (parent, 0, "エラー"))
        self.assertIn("commands.json の読込に失敗しました:", messages[0][3])
        self.assertTrue(module._confirm_delete(parent, "tool"))
        self.assertEqual(messages[-1], (parent, 1, "Command List - 削除確認",
            "コマンド 'tool' を削除しますか？"))

    def test_open_editor_returns_saved_name_including_empty_name(self):
        for saved, changed, name, expected in ((True, True, "Renamed", "renamed"), (True, True, "", ""), (False, False, "old", None), (True, False, "old", "old")):
            with self.subTest(saved=saved, name=name):
                editor = SimpleNamespace(result_saved=saved, commands_changed=changed, draft=SimpleNamespace(name=name.lower()), edits=[],
                    messageLoop=lambda: None, destroy=lambda: None)
                events = []
                with patch.object(self.module, "CommandEditor", lambda *args, **kwargs: editor):  # noqa: B023  # Used within this test iteration.
                    result = self.module.open_editor(self.parent, "old", on_saved=lambda: events.append("saved"))  # noqa: B023  # Used within this test iteration.
                self.assertEqual(result, expected)
                self.assertEqual(events, ["saved"] if saved and changed else [])


    def test_modal_editor_prevents_hotkey_from_activating_main(self):
        tree = ast.parse((ROOT / "clnch/clnch_mainwindow.py").read_text(encoding="utf-8-sig"))
        main_class = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "MainWindow")
        hotkey = next(n for n in main_class.body if isinstance(n, ast.FunctionDef) and n.name == "hotkey_Activate")
        env = {"clnch_ini": SimpleNamespace(get=lambda *args: "activate"), "ini_settings": ini_settings}
        exec(compile(ast.Module(body=[hotkey], type_ignores=[]), "hotkey-test", "exec"), env)  # noqa: S102  # Execute isolated source under test.
        events = []
        self.parent.active = False
        state = {"focus": "other", "popup": "editor", "visible": False}
        def restore():
            events.append("restore")
            state.update(focus="main", popup="main", visible=True)
        def foreground():
            events.append("foreground")
            state["focus"] = state["popup"]
        self.parent.restore = restore
        self.parent.foreground = foreground
        self.parent.activate = lambda: events.append("main.activate")
        def loop():
            self.assertFalse(self.parent.isEnabled())
            env["hotkey_Activate"](self.parent)
            self.assertEqual(events, ["foreground"])
            self.assertEqual(state, {"focus": "editor", "popup": "editor", "visible": False})
        editor = SimpleNamespace(result_saved=False, edits=[], messageLoop=loop,
            destroy=lambda: events.append("editor.destroy"))
        with patch.object(self.module, "CommandEditor", lambda *args, **kwargs: editor):
            self.assertIsNone(self.module.open_editor(self.parent))
        self.assertTrue(self.parent.isEnabled())
        self.assertEqual(events, ["foreground", "main.activate", "editor.destroy"])
        events.clear()
        env["hotkey_Activate"](self.parent)
        self.assertEqual(events, ["restore", "foreground", "main.activate"])

    def test_ipc_commandline_returns_to_modal_without_main_input_loop(self):
        tree = ast.parse((ROOT / "clnch/clnch_ipc.py").read_text(encoding="utf-8-sig"))
        ipc_class = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "IpcData")
        command_line = next(n for n in ipc_class.body if isinstance(n, ast.FunctionDef) and n.name == "commandLine")
        events = []
        env = {"configparser": configparser, "json": json}
        exec(compile(ast.Module(body=[command_line], type_ignores=[]), "ipc-test", "exec"), env)  # noqa: S102  # Execute isolated source under test.
        ini = configparser.RawConfigParser()
        ini.add_section("COMMANDLINE")
        ini.set("COMMANDLINE", "text", json.dumps("test"))
        ipc = SimpleNamespace(ini=ini)
        main = SimpleNamespace(isEnabled=lambda: False,
            foreground=lambda: events.append("main.foreground"),
            restore=lambda: events.append("main.restore"),
            activate=lambda: events.append("main.activate"),
            activeMessageLoop=lambda **kwargs: events.append(("main.loop", kwargs)),
            resetPos=lambda: events.append("reset"))
        env["commandLine"](ipc, main)
        self.assertEqual(events, ["main.foreground"])
        events.clear()
        main.isEnabled = lambda: True
        env["commandLine"](ipc, main)
        self.assertEqual(events, ["main.restore", "main.foreground", "main.activate",
            ("main.loop", {"text": "test", "selection": [4, 4]}), "reset"])

    def test_modal_cleanup_on_message_loop_error(self):
        events = []
        editor = SimpleNamespace(edits=[],
            destroy=lambda: events.extend(["edit.destroy", "editor.destroy"]))
        def loop():
            self.assertFalse(self.parent.isEnabled())
            raise RuntimeError("test failure")
        editor.messageLoop = loop
        with (
            patch.object(self.module, "CommandEditor", lambda *args, **kwargs: editor),
            self.assertRaisesRegex(RuntimeError, "test failure"),
        ):
            self.module.open_editor(self.parent)
        self.assertTrue(self.parent.isEnabled())
        self.assertEqual(events, ["edit.destroy", "editor.destroy"])

    def test_editor_shown_callback_runs_after_creation_with_main_disabled(self):
        events = []
        editor = SimpleNamespace(result_saved=False, edits=[],
            messageLoop=lambda: events.append("loop"), destroy=lambda: events.append("destroy"))
        def created(*args, **kwargs):
            events.append("created")
            return editor
        def shown():
            self.assertFalse(self.parent.isEnabled())
            self.assertEqual(events, ["created"])
            events.append("shown")
        with patch.object(self.module, "CommandEditor", created):
            self.assertIsNone(self.module.open_editor(self.parent, on_shown=shown))
        self.assertEqual(events, ["created", "shown", "loop", "destroy"])
        self.assertTrue(self.parent.isEnabled())

    def test_editor_shown_callback_error_cleans_up(self):
        events = []
        editor = SimpleNamespace(edits=[], destroy=lambda: events.append("destroy"))
        def shown():
            raise RuntimeError("handoff failure")
        with (
            patch.object(self.module, "CommandEditor", lambda *args, **kwargs: editor),
            self.assertRaisesRegex(RuntimeError, "handoff failure"),
        ):
            self.module.open_editor(self.parent, on_shown=shown)
        self.assertTrue(self.parent.isEnabled())
        self.assertEqual(events, ["destroy"])

    def test_list_editor_error_restores_main_and_destroys_list(self):
        self.path.write_text(json.dumps({"tool": {}}), encoding="utf-8")
        def edit(key):
            raise RuntimeError("editor failure")
        with self.assertRaisesRegex(RuntimeError, "editor failure"):
            self._run_list_actions([(13, 0, "tool")], on_edit=edit)

    def test_standard_editor_error_restores_original_main_visibility(self):
        tree = ast.parse((ROOT / "clnch/clnch_standard.py").read_text(encoding="utf-8-sig"))
        function = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                        and n.name == "_open_command_editor")
        for visible in (False, True):
            with self.subTest(visible=visible):
                calls = []
                def failed(*args, **kwargs):
                    raise RuntimeError("creation failure")
                controller = SimpleNamespace(
                    window=SimpleNamespace(isVisible=lambda visible=visible: visible,
                        show=lambda *args, calls=calls: calls.append(args)),
                    reload_commands=lambda: None)
                env = {"_cleanup_on_exit": _cleanup_on_exit}
                exec(compile(ast.Module(body=[function], type_ignores=[]), "editor-recovery", "exec"), env)  # noqa: S102  # Execute isolated source under test.
                with (patch.dict(sys.modules, {"clnch_cmdeditor": SimpleNamespace(open_editor=failed)}),
                      self.assertRaisesRegex(RuntimeError, "creation failure")):
                    env["_open_command_editor"](controller, "tool")
                self.assertEqual(calls, [])


class CommandStoreTests(unittest.TestCase):
    def test_sparse_save_normalizes_all_actions_once_without_changing_input(self):
        data = {"first": {"target": {"link": "a.exe"}},
                "second": {"on_ctrl": {"link": "b.exe", "view_mode": "maximized"}},
                "empty": {}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "commands.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            with patch.object(cmd_store.os, "replace", wraps=cmd_store.os.replace) as replace:
                normalized = cmd_store.save_commands(path, data, data)
                self.assertEqual(replace.call_count, 1)
            self.assertEqual(data["first"]["target"], {"link": "a.exe"})
            self.assertEqual(normalized["first"]["target"], {"link": "a.exe", "args": "", "workdir": "", "view_mode": "normal"})
            self.assertEqual(normalized["second"]["on_ctrl"]["view_mode"], "maximized")
            self.assertEqual(set(normalized["second"]), {"on_ctrl"})
            self.assertEqual(normalized["empty"], {})
            with patch.object(cmd_store.tempfile, "NamedTemporaryFile", side_effect=AssertionError("unexpected I/O")):
                self.assertEqual(cmd_store.save_commands(path, normalized, normalized), normalized)

    def test_success_and_partial_write_or_replace_failure_preserve_original(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "commands.json"
            data = {"日本語": {"target": {"link": "tool.exe"}}}
            normalized = cmd_store.save_commands(path, data)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), normalized)
            self.assertEqual(normalized["日本語"]["target"], {"link": "tool.exe", "args": "", "workdir": "", "view_mode": "normal"})
            original = path.read_bytes()
            def partial_write(commands, output, **kwargs):
                output.write('{"partial":')
                raise OSError("write failed")
            for operation, failure in ((cmd_store.json, "dump"), (cmd_store.os, "replace")):
                with self.subTest(operation=failure):
                    with (
                        patch.object(operation, failure, side_effect=partial_write if failure == "dump" else PermissionError("locked")),
                        self.assertRaises(OSError),
                    ):
                        cmd_store.save_commands(path, {})
                    self.assertEqual(path.read_bytes(), original)
                    self.assertEqual(list(Path(directory).glob(".commands-*.tmp")), [])
            path.unlink()
            with (
                patch.object(cmd_store.os, "replace", side_effect=PermissionError("locked")),
                self.assertRaises(PermissionError),
            ):
                cmd_store.save_commands(path, data)
            self.assertFalse(path.exists())
            self.assertEqual(list(Path(directory).glob(".commands-*.tmp")), [])


class ThemeChoiceTests(unittest.TestCase):
    def test_existing_themes_and_custom_choice_colors(self):
        tree = ast.parse((ROOT / "ckit/ckit_theme.py").read_text(encoding="utf-8-sig"))
        functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                     and node.name in ("setTheme", "getColor")]
        constants = [node for node in tree.body if isinstance(node, ast.Assign)
                     and any(isinstance(target, ast.Name) and target.id in
                             ("COLOR_SECTION", "DEFAULT_COLORS", "COLOR_FALLBACKS") for target in node.targets)]
        widget_tree = ast.parse((ROOT / "ckit/ckit_widget.py").read_text(encoding="utf-8-sig"))
        choice_class = next(node for node in widget_tree.body if isinstance(node, ast.ClassDef) and node.name == "ChoiceWidget")
        for theme in ("black", "white", "gray"):
            with self.subTest(theme=theme):
                env = {"configparser": configparser, "re": re, "os": os,
                    "ckit_misc": SimpleNamespace(getAppExePath=lambda: str(ROOT))}
                exec(compile(ast.Module(body=[*constants, *functions], type_ignores=[]), "theme-test", "exec"), env)  # noqa: S102  # Execute isolated source under test.
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    env["setTheme"](theme, {})
                    fg, bg = env["getColor"]("choice_fg"), env["getColor"]("choice_bg")
                    self.assertNotEqual(bg, env["getColor"]("select_bg"))
                self.assertNotEqual(fg, bg)
                self.assertEqual(output.getvalue(), "")
                attrs = []
                misc_env = {}
                misc_tree = ast.parse((ROOT / "ckit/ckit_misc.py").read_text(encoding="utf-8-sig"))
                split = next(n for n in misc_tree.body if isinstance(n, ast.FunctionDef) and n.name == "splitLines")
                exec(compile(ast.Module(body=[split], type_ignores=[]), "split-lines", "exec"), misc_env)  # noqa: S102  # Execute isolated source under test.
                widget_env = {"ckit_misc": SimpleNamespace(**misc_env), "Widget": object, "ckitcore": SimpleNamespace(Attribute=lambda **kwargs: kwargs),
                    "ckit_theme": SimpleNamespace(getColor=env["getColor"])}
                exec(compile(ast.Module(body=[choice_class], type_ignores=[]), "choice-test", "exec"), widget_env)  # noqa: S102  # Execute isolated source under test.
                widget = widget_env["ChoiceWidget"].__new__(widget_env["ChoiceWidget"])
                widget.x, widget.y, widget.message, widget.select = 0, 0, "", 0
                widget.width, widget.row_step = 66, 1
                widget.item_list, widget.enable_cursor = ["通常", "最小化", "最大化"], False
                widget.window = SimpleNamespace(getStringWidth=len, putString=lambda *args: attrs.append(args[4]),  # noqa: B023  # Used within this test iteration.
                    setCursorPos=lambda *args: None)
                widget.paint()
                self.assertEqual(attrs[1], {"fg": fg, "bg": bg})
                widget.enable_cursor = True
                widget.paint()
                self.assertEqual(attrs[-3], {"fg": env["getColor"]("select_fg"), "bg": env["getColor"]("select_bg")})
                env["setTheme"]("nonexistent-theme-file", {"choice_fg": (1, 2, 3), "choice_bg": (4, 5, 6)})
                self.assertEqual(env["getColor"]("choice_fg"), (1, 2, 3))
                self.assertEqual(env["getColor"]("choice_bg"), (4, 5, 6))
                env["setTheme"]("nonexistent-theme-file", {})
                self.assertEqual(env["getColor"]("choice_fg"), env["getColor"]("select_fg"))
                self.assertEqual(env["getColor"]("choice_bg"), env["getColor"]("select_bg"))


if __name__ == "__main__":
    unittest.main()
