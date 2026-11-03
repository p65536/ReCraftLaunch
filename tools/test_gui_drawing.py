"""Color-only GUI drawing with native imports and a fake window; no GUI is opened."""
import contextlib
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from native_test_support import RUN_DIR

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "clnch"), str(RUN_DIR / "lib")]
sys._clnch_app_dir = str(ROOT)


import clnch_text

import ckit

clnch_text.initialize()
import clnch_configmenu
import clnch_consolewindow
import clnch_listwindow
from clnch_consolewindow import ConsoleWindow, Log

from ckit.ckit_const import VK_SPACE


class Window:
    def __init__(self):
        self.draws = []
        self.command = ckit.CommandMap(self)
        self.timers = {}
        self.cursor = None
    def putString(self, *args, **kwargs): self.draws.append(args)
    def getStringWidth(self, text, *args): return len(text)
    def getStringColumns(self, text, *args): return list(range(len(text)+1))
    def enableIme(self, *args): pass
    def setImeRect(self, *args): pass
    def setCursorPos(self, *args): self.cursor = args
    def charToClient(self, x, y): return x*10, y*20
    def setTimer(self, handler, interval): self.timers[handler] = interval
    def killTimer(self, handler): self.timers.pop(handler, None)
    def isForeground(self): return True
    def isActive(self): return True


class GuiDrawingTests(unittest.TestCase):
    def setUp(self):
        ckit.setTheme("black", {})
        self.window = Window()

    def test_opaque_list_items_preserve_selection_clear_and_status(self):
        for theme in ("black", "white", "gray"):
            ckit.setTheme(theme, {})
            for opaque in (False, True):
                for active in (False, True):
                    with self.subTest(theme=theme, opaque=opaque, active=active):
                        draws = []
                        status = SimpleNamespace(setMessage=lambda text: None)
                        window = SimpleNamespace(
                            _opaque_normal=opaque, active=active, select=1,
                            width=lambda: 20, height=lambda: 3, itemsHeight=lambda: 2,
                            getStringWidth=len,
                            scroll_info=SimpleNamespace(pos=1), items=["offscreen", "selected", "normal"],
                            item_lines=[["offscreen"], ["selected"], ["normal"]],
                            item_height=1, status_rows=1, isearch=None,
                            status_bar_layer=status, statusbar_handler=lambda width, index: "status",
                            putString=lambda *args, draws=draws: draws.append(args),
                        )
                        window.status_bar = SimpleNamespace(paint=lambda *args, draws=draws: draws.append(("status", args[2])))
                        with patch.object(ckit, "Attribute", side_effect=lambda **kw: kw):
                            clnch_listwindow.ListWindow.paint(window)
                        normal = {"fg": ckit.getColor("fg")}
                        item = {**normal, "bg": ckit.getColor("bg")} if opaque else normal
                        self.assertEqual([draw[4] for draw in draws[:3]], [normal] * 3)
                        selected = {"fg": ckit.getColor("select_fg"), "bg": ckit.getColor("select_bg")}
                        self.assertEqual(draws[3][4], selected if active else item)
                        self.assertEqual(draws[4][4], item)
                        self.assertEqual(draws[3][5], "selected")
                        self.assertEqual(draws[4][5], "normal")
                        self.assertEqual(draws[5], ("status", 2))

    def test_public_import_and_theme_contrast(self):
        for theme in ("black", "white", "gray"):
            ckit.setTheme(theme, {})
            for color in ("fg", "bar_fg"):
                self.assertNotEqual(ckit.getColor(color), ckit.getColor("bg"))
            # Both normal and IME caret brushes are XOR masks, not painted RGB values.
            for color in ("cursor0", "cursor1", "caret0", "caret1"):
                for background in ("bg", "select_bg"):
                    bg = ckit.getColor(background)
                    drawn = tuple(channel ^ mask for channel, mask in zip(bg, ckit.getColor(color)))
                    self.assertGreaterEqual(sum(abs(a-b) for a, b in zip(drawn, bg)), 128)
            if theme == "gray":
                self.assertEqual(ckit.getColor("bg"), (72, 74, 76))
                for color in ("cursor0", "caret0"):
                    self.assertEqual(ckit.getColor(color), (175, 175, 175))
                for color in ("cursor1", "caret1"):
                    self.assertEqual(ckit.getColor(color), (175, 208, 208))
            choice_colors = {
                "black": ((255, 255, 255), (96, 96, 96)),
                "gray": ((28, 32, 36), (144, 150, 156)),
                "white": ((255, 255, 255), (104, 104, 104)),
            }
            self.assertEqual((ckit.getColor("choice_fg"), ckit.getColor("choice_bg")), choice_colors[theme])

    def test_hint_color_and_shared_drawing_follow_theme(self):
        from clnch_statusbar import SimpleStatusBarLayer

        from ckit import ckit_dialog
        layer = SimpleStatusBarLayer(message="Help")
        label = ckit.Dialog.StaticText(0, "Explanation")
        self.window.width = lambda: 40
        label.build(self.window, 0, 0)
        for theme, expected in (("black", (191, 191, 191)), ("gray", (189, 191, 193)), ("white", (63, 63, 63))):
            with self.subTest(theme=theme):
                ckit.setTheme(theme, {})
                self.assertEqual(ckit.getHintColor(), expected)
                with patch.object(ckit_dialog.ckitcore, "Attribute", side_effect=lambda **kw: kw), \
                     patch.object(ckit, "Attribute", side_effect=lambda **kw: kw):
                    label.paint(False)
                    self.assertEqual(self.window.draws[-1][4], {"fg": expected})
                    layer.setMessage("Help")
                    layer.paint(self.window, 0, 0, 40, 1)
                    self.assertEqual(self.window.draws[-1][4], {"fg": expected})
                    layer.setMessage("Error", error=True)
                    layer.paint(self.window, 0, 0, 40, 1)
                    self.assertEqual(self.window.draws[-1][4], {"fg": ckit.getColor("bar_error_fg")})

    def test_status_guides_can_align_right_without_changing_the_default(self):
        from clnch_statusbar import SimpleStatusBarLayer

        for width in (12, 40, 76):
            for message in ("Help", "A long guide that fills the available row"):
                layer = SimpleStatusBarLayer(message=message)
                layer.paint(self.window, 0, 0, width, 1)
                self.assertTrue(self.window.draws[-1][-1].startswith(" "))
                layer.align = ckit.ALIGN_RIGHT
                layer.paint(self.window, 0, 0, width, 1)
                text = self.window.draws[-1][-1]
                self.assertEqual(self.window.getStringWidth(text), width)
                self.assertGreaterEqual(len(text) - len(text.rstrip()), 2)
                self.assertEqual(text.strip(), message[:width - 2].strip())

    def test_theme_reads_arbitrary_ini_stem_without_legacy_fallback(self):
        from ckit import ckit_misc
        with tempfile.TemporaryDirectory() as directory:
            themes = Path(directory) / "themes"
            themes.mkdir()
            name = "見やすい.dark"
            (themes / (name + ".INI")).write_text("[COLOR]\nfg = (1, 2, 3)\n", encoding="utf-8")
            old_themes = Path(directory) / "theme"
            old_themes.mkdir()
            (old_themes / "old-only.ini").write_text("[COLOR]\nfg = (7, 8, 9)\n", encoding="utf-8")
            legacy = themes / "legacy"
            legacy.mkdir()
            (legacy / "theme.ini").write_text("[COLOR]\nfg = (4, 5, 6)\n", encoding="utf-8")
            with patch.object(ckit_misc, "getAppExePath", return_value=directory):
                ckit.setTheme(name, {})
                self.assertEqual(ckit.getColor("fg"), (1, 2, 3))
                ckit.setTheme("legacy", {})
                self.assertEqual(ckit.getColor("fg"), (255, 255, 255))
                ckit.setTheme("old-only", {})
                self.assertEqual(ckit.getColor("fg"), (255, 255, 255))

    def test_theme_menu_lists_only_direct_ini_files_and_keeps_saved_name(self):
        with tempfile.TemporaryDirectory() as directory:
            themes = Path(directory) / "themes"
            themes.mkdir()
            names = ("black", "gray", "white", "見やすい.dark")
            for name in names:
                (themes / (name + ".INI")).write_text("[COLOR]\n", encoding="utf-8")
            (themes / "notes.txt").touch()
            (themes / "backup.ini.bak").touch()
            (themes / "folder.ini").mkdir()
            legacy = themes / "legacy"
            legacy.mkdir()
            (legacy / "theme.ini").touch()
            main = SimpleNamespace(reloadTheme=Mock())
            for saved in ("black", "gray", "white"):
                with self.subTest(saved=saved):
                    def menu(window, width, height, title, items, initial):
                        self.assertCountEqual(items, names)
                        self.assertEqual(items[initial], saved)  # noqa: B023  # Used within this test iteration.
                        return items.index("見やすい.dark")
                    with patch.object(ckit, "getAppExePath", return_value=directory), \
                         patch.object(clnch_configmenu.clnch_ini, "get", return_value=saved), \
                         patch.object(clnch_configmenu.clnch_ini, "set") as save, \
                         patch.object(clnch_configmenu.clnch_listwindow, "popMenu", side_effect=menu):
                        main.reloadTheme.reset_mock()
                        clnch_configmenu._configTheme(main)
                        save.assert_called_once_with("THEME", "name", "見やすい.dark")
                        main.reloadTheme.assert_called_once_with()

    def test_edit_selection_caret_resize_and_destroy(self):
        edit = ckit.EditWidget(self.window, 1, 2, 12, 1, "abcdef", [1, 4])
        edit.enableCursor(True)
        edit.paint()
        self.assertTrue(any(draw[-1] == "bcd" for draw in self.window.draws))
        self.assertIsNotNone(self.window.cursor)
        edit.setPosSize(2, 3, 10, 1)
        edit.paint()
        self.assertEqual((edit.x, edit.y, edit.width), (2, 3, 10))
        edit.onChar(ord("X"), 0)
        self.assertEqual(edit.getText(), "aXef")
        edit.selectAll()
        with patch("ckit.ckit_misc.getClipboardText", return_value="a\tb"):
            edit.onKeyDown(ckit.VK_V, ckit.MODKEY_CTRL)
        self.assertEqual(edit.getText(), "a\tb")
        self.assertEqual(edit.getSelection(), [3, 3])
        self.assertIn("a b", [draw[-1] for draw in self.window.draws])
        self.assertEqual(self.window.cursor, (6, 3))
        edit.selectAll()
        with patch("ckit.ckit_misc.setClipboardText") as copy:
            edit.onKeyDown(ckit.VK_C, ckit.MODKEY_CTRL)
        copy.assert_called_once_with("a\tb")
        edit.destroy()

    def test_edit_underline_color_selection_and_no_bg(self):
        from ckit import ckit_widget
        from ckit.ckit_const import LINE_BOTTOM
        for theme, color in (("black", (127, 127, 127)), ("gray", (150, 152, 154)), ("white", (127, 127, 127))):
            for no_bg in (False, True):
                with self.subTest(theme=theme, no_bg=no_bg):
                    ckit.setTheme(theme, {})
                    edit = ckit.EditWidget(self.window, 1, 2, 12, 1, "abcdef", [1, 4], no_bg=no_bg)
                    try:
                        for focused in (False, True):
                            edit.enableCursor(focused)
                            self.window.draws.clear()
                            with patch.object(ckit_widget.ckitcore, "Attribute", side_effect=lambda **kw: kw):
                                edit.paint()
                            line = None if no_bg else (LINE_BOTTOM, color)
                            self.assertTrue(self.window.draws)
                            for draw in self.window.draws:
                                self.assertEqual(draw[4]["line0"], line)
                                selected = focused and draw[-1] == "bcd"
                                self.assertEqual(draw[4]["fg"], ckit.getColor("select_fg" if selected else "fg"))
                                self.assertEqual(draw[4]["bg"], ckit.getColor("select_bg" if selected else "bg"))
                    finally:
                        edit.destroy()

    def test_font_padding_keeps_width_and_scales_line_height(self):
        from ckit import ckitcore
        for size, padding in ((12, 2), (18, 3), (24, 4)):
            with self.subTest(size=size, padding=padding):
                plain = ckitcore.Font("MS Gothic", size).getCharSize()
                padded = ckitcore.Font("MS Gothic", size, padding).getCharSize()
                self.assertEqual(padded, (plain[0], plain[1] + padding * 2))

    def test_stocked_font_distinguishes_padding(self):
        plain = ckit.getStockedFont("MS Gothic", 12, 0)
        padded = ckit.getStockedFont("MS Gothic", 12)
        self.assertIs(padded, ckit.getStockedFont("MS Gothic", 12, 2))
        self.assertIsNot(plain, padded)
        self.assertEqual(padded.getCharSize()[1] - plain.getCharSize()[1], 4)

    def test_padded_window_geometry_and_mouse_rows(self):
        ckit.registerWindowClass("ReClnchPaddingTest")
        for padding in (2, 3, 4):
            with self.subTest(padding=padding):
                window = ckit.TextWindow(width=20, height=3, show=False,
                    font=ckit.getStockedFont("MS Gothic", 12, padding))
                child = None
                try:
                    char_w, char_h = window.getCharSize()
                    self.assertEqual(window.getClientSize(), (20 * char_w + 2, 3 * char_h + 2))
                    child = ckit.TextWindow(width=10, height=2, show=False, parent_window=window)
                    self.assertEqual(child.getCharSize(), (char_w, char_h))
                    left, top = window.charToClient(0, 0)
                    for row in range(3):
                        self.assertEqual(window.charToClient(0, row), (left, top + row * char_h))
                        for offset in (0, char_h - 1):
                            self.assertEqual(ConsoleWindow._mousePosToCharPos(window, left, top + row * char_h + offset), (0, row))
                finally:
                    if child is not None:
                        child.destroy()
                    window.destroy()

    def test_editor_native_layout_keeps_text_height_and_separate_gaps(self):
        with patch.object(ckit, "dataPath", return_value=str(ROOT / "samples")):
            import clnch_cmdeditor
        ckit.registerWindowClass("ReClnchEditorLayoutTest")
        for scale in (1.0, 1.5, 2.0):
            with self.subTest(scale=scale):
                font = ckit.getStockedFont("MS Gothic", round(12 * scale), round(2 * scale))
                parent = ckit.TextWindow(width=20, height=1, show=False, font=font)
                parent.modifier_settings = clnch_configmenu.clnch_modifierconfig.DEFAULTS.copy()
                editor = None
                try:
                    with patch.object(ckit.TextWindow, "getDisplayScaling", return_value=scale), \
                         patch.object(clnch_cmdeditor.CommandEditor, "show"), \
                         patch.object(clnch_cmdeditor.CommandEditor, "activate"):
                        editor = clnch_cmdeditor.CommandEditor(parent)
                    char_w, char_h = font.getCharSize()
                    gap = round(8 * scale)
                    self.assertEqual(editor.getCharSize(), (char_w, char_h))
                    self.assertEqual(editor.getClientSize(), (66 * char_w + 2, 8 * char_h + 9 * gap + 2))
                    for previous, current in zip(editor.controls, editor.controls[1:]):
                        bottom = editor.charToClient(0, previous.y + 1)[1]
                        top = editor.charToClient(0, current.y)[1]
                        self.assertEqual(top - bottom, gap)
                        self.assertFalse(editor._on_left_button_down(15 * char_w, bottom, 0))
                    for row, plane in editor._row_planes.items():
                        self.assertEqual(plane.charToClient(0, 0), editor.charToClient(0, row))
                        self.assertEqual(plane.charToClient(0, 1), editor.charToClient(0, row + 1))
                        self.assertEqual(plane.charToScreen(0, 0), editor.charToScreen(0, row))
                    editor._on_activate(True)
                    editor.flushPaint()
                    settings = parent.modifier_settings
                    settings["CTRL_ACTION"] = "mapped_folder"
                    editor.modifier_choice.select = 1
                    editor._switch_modifier()
                    for sources in ((), ("D:/private-source",)):
                        for destination in ("", "E:/private-destination"):
                            settings["SOURCE_ROOTS"] = sources
                            settings["CTRL_DESTINATION_ROOT"] = destination
                            with patch.object(editor, "putString", wraps=editor.putString) as draws:
                                editor.paint()
                            hint = next(call.args for call in draws.call_args_list
                                        if call.args[1] == 13 and call.args[-1].strip())
                            self.assertLessEqual(editor.getStringWidth(hint[-1]), hint[2])
                finally:
                    if editor is not None:
                        for edit in editor.edits:
                            edit.destroy()
                        editor.destroy()
                    parent.destroy()

    def test_checkbox_keeps_value_and_keyboard_toggle(self):
        check = ckit.CheckBoxWidget(self.window, 0, 0, 8, 1, "Label", False)
        self.assertEqual(self.window.draws[-1][-1], "[ ]Label")
        self.assertTrue(check.onKeyDown(VK_SPACE, 0))
        self.assertTrue(check.getValue())
        self.assertEqual(self.window.draws[-1][-1], "[x]Label")

    def test_progress_values_busy_mode_and_lifecycle(self):
        bar = ckit.ProgressBarWidget(self.window, 0, 0, 10, 2)
        bar.setValue((-1, 2))
        self.assertEqual(bar.getValue(), [0, 1])
        self.assertEqual(self.window.draws[-1][2], 10)
        bar.setValue(None)
        bar._onTimer()
        self.assertEqual(len(self.window.timers), 1)
        bar.setValue(0.5)
        self.assertEqual(self.window.draws[-1][2], 5)
        bar.show(False)
        count = len(self.window.draws)
        bar._onTimer()
        self.assertEqual(len(self.window.draws), count)
        bar.show(True)
        bar.destroy()
        self.assertFalse(self.window.timers)

    def console(self, width=80, height=4):
        console = ConsoleWindow.__new__(ConsoleWindow)
        console.width = lambda: width
        console.height = lambda: height
        console.putString = self.window.putString
        console.getStringWidth = self.window.getStringWidth
        console.getCharSize = lambda: (10, 20)
        console.getClientRect = lambda: (0, 0, width*10, height*20)
        console.charToClient = self.window.charToClient
        console.setCapture = lambda: setattr(console, "captured", True)
        console.releaseCapture = lambda: setattr(console, "captured", False)
        console.captured = False
        console.mouse_click_info = None
        console._last_double_click = None
        console.debug = console.auto_show = console.auto_show_required = False
        console.log = Log()
        console._wrap_cache = None
        console.log.write("\n".join(f"line{i}" for i in range(20)))
        console.scroll_info = ckit.ScrollInfo()
        console.selection = [[0, 1], [0, 4]]
        return console

    def test_console_log_selection_and_status(self):
        console = self.console()
        with patch.object(ckit, "Attribute", lambda **kwargs: kwargs):
            console.paint()
            self.assertTrue(any(d[-1] == "ine" for d in self.window.draws))
            status = self.window.draws[-2]
            self.assertEqual(status[:4], (0, 2, 80, 1))
            self.assertIn("表示: 1–2 / 全20行｜最新まで18行", status[-1])
            self.assertEqual(status[4]["fg"], ckit.getHintColor())
            self.assertEqual(status[4]["line0"], (ckit.LINE_TOP, ckit.getColor("bar_fg")))
            guide = self.window.draws[-1]
            self.assertIn("Ctrl+A: 全選択", guide[-1])
            self.assertIn("3クリック: 全選択・コピー", guide[-1])
            self.assertEqual(guide[4], {"fg": ckit.getHintColor(), "bg": ckit.getColor("bg")})
            console._scroll(100)
            console.paint()
            self.assertEqual(console.scroll_info.pos, 18)
            self.assertIn("19–20 / 全20行｜最新のログ", self.window.draws[-2][-1])
            console._onKeyDown(ckit.VK_PRIOR, 0)
            self.assertEqual(console.scroll_info.pos, 16)
            console._onMouseWheel(0, 0, 1, 0)
            self.assertEqual(console.scroll_info.pos, 13)
            console._scroll(-100)
            self.assertEqual(console.scroll_info.pos, 0)
            console.clearLog()
            self.assertIn("1–1 / 全1行｜最新のログ", self.window.draws[-2][-1])

    def test_console_status_click_and_double_click_do_not_select_or_copy(self):
        console = self.console()
        selection = [list(point) for point in console.selection]
        with patch.object(ckit, "setClipboardText") as copy:
            for y in (40, 60):
                console._onLeftButtonDown(10, y, 0)
                console._onMouseMove(30, 80, 0)
                console._onLeftButtonUp(30, 80, 0)
                console._onLeftButtonDoubleClick(10, y, 0)
            self.assertIsNone(console.mouse_click_info)
            self.assertFalse(console.captured)
            self.assertEqual(console.selection, selection)
            self.assertEqual(console.scroll_info.pos, 0)
            copy.assert_not_called()

    def test_console_text_drag_and_copy_exclude_status(self):
        console = self.console()
        with patch.object(ckit, "setClipboardText") as copy:
            console._onLeftButtonDown(0, 0, 0)
            console._onMouseMove(50, 20, 0)
            console._onLeftButtonUp(50, 20, 0)
            copy.assert_called_once_with("line0\r\nline1")
            copy.reset_mock()
            console._onLeftButtonDown(0, 0, 0)
            console._onMouseMove(10, 60, 0)
            self.assertEqual(console.scroll_info.pos, 1)
            self.assertEqual(console.selection[1], [2, 5])
            console._onLeftButtonUp(10, 60, 0)
            self.assertNotIn("表示", copy.call_args.args[0])
            self.assertFalse(console.captured)

    def test_console_keyboard_select_all_copies_retained_original_lines(self):
        console = self.console(width=6, height=6)
        console.log = Log()
        lines = [f"日本\t🙂 long line {i}" for i in range(1002)]
        console.log.write("\n".join(lines))
        console._scroll(100)
        position = console.scroll_info.pos
        with patch.object(ckit, "setClipboardText") as copy:
            console._onKeyDown(ckit.VK_A, ckit.MODKEY_CTRL)
            self.assertEqual(console.selection, [[0, 0], [999, len(lines[-1])]])
            self.assertEqual(console.scroll_info.pos, position)
            copy.assert_not_called()
            console._onKeyDown(ckit.VK_C, ckit.MODKEY_CTRL)
            copy.assert_called_once_with("\r\n".join(lines[-1000:]))
            copy.reset_mock()
            console.selection = [[1, 3], [1, 0]]
            console._onKeyDown(ckit.VK_A, ckit.MODKEY_CTRL | ckit.MODKEY_SHIFT)
            self.assertEqual(console.selection, [[1, 3], [1, 0]])
            console._onKeyDown(ckit.VK_C, ckit.MODKEY_CTRL)
            copy.assert_called_once_with("日本\t")
            copy.reset_mock()
            console.clearLog()
            console._onKeyDown(ckit.VK_A, ckit.MODKEY_CTRL)
            console._onKeyDown(ckit.VK_C, ckit.MODKEY_CTRL)
            self.assertEqual(console.selection, [[0, 0], [0, 0]])
            copy.assert_not_called()

    def test_console_triple_click_selects_all_and_copies_on_release(self):
        console = self.console()
        with patch.object(clnch_consolewindow.time, "monotonic", side_effect=(10.0, 10.1)), \
             patch.object(clnch_consolewindow, "_GetDoubleClickTime", return_value=500), \
             patch.object(clnch_consolewindow, "_GetSystemMetrics", return_value=4), \
             patch.object(ckit, "setClipboardText") as copy:
            console._onLeftButtonDown(10, 0, 0)
            console._onLeftButtonUp(10, 0, 0)
            copy.assert_not_called()
            console._onLeftButtonDoubleClick(10, 0, 0)
            self.assertEqual(console.selection, [[0, 0], [0, 5]])
            console._onLeftButtonUp(10, 0, 0)
            copy.assert_called_once_with("line0")
            copy.reset_mock()
            console._onLeftButtonDown(12, 2, 0)
            self.assertEqual(console.selection, [[0, 0], [19, 6]])
            self.assertTrue(console.captured)
            copy.assert_not_called()
            console._onMouseMove(40, 80, 0)
            self.assertEqual(console.selection, [[0, 0], [19, 6]])
            self.assertEqual(console.scroll_info.pos, 0)
            console._onLeftButtonUp(40, 80, 0)
            copy.assert_called_once_with("\r\n".join(console.log.log))
            self.assertFalse(console.captured)

    def test_console_third_click_requires_time_and_position_without_intervening_action(self):
        for action in ("late", "distant_x", "distant_y", "key", "status", "right", "wheel", "inactive", "clear"):
            with self.subTest(action=action):
                console = self.console()
                with patch.object(clnch_consolewindow.time, "monotonic", side_effect=(10.0, 10.6 if action == "late" else 10.1)), \
                     patch.object(clnch_consolewindow, "_GetDoubleClickTime", return_value=500), \
                     patch.object(clnch_consolewindow, "_GetSystemMetrics", return_value=4), \
                     patch.object(ckit, "setClipboardText"):
                    console._onLeftButtonDoubleClick(10, 0, 0)
                    console._onLeftButtonUp(10, 0, 0)
                    if action == "key":
                        console._onKeyDown(ckit.VK_C, ckit.MODKEY_CTRL)
                    elif action == "status":
                        console._onLeftButtonDown(10, 60, 0)
                        console._onLeftButtonUp(10, 60, 0)
                    elif action == "right":
                        console._onRightButtonDown(10, 0, 0)
                    elif action == "wheel":
                        console._onMouseWheel(10, 0, 1, 0)
                    elif action == "inactive":
                        console._onActivate(False)
                    elif action == "clear":
                        console.clearLog()
                    x = 13 if action == "distant_x" else 10
                    y = 3 if action == "distant_y" else 0
                    console._onLeftButtonDown(x, y, 0)
                    self.assertEqual(console.selection[0], console.selection[1])
                    console._onLeftButtonUp(x, y, 0)
                    self.assertFalse(console.captured)

    def test_console_output_follows_tail_and_keeps_scrolled_position(self):
        console = self.console()
        with patch.object(sys, "stdout"), patch.object(sys, "stderr"):
            console._scroll(100)
            console.registerStdio()
            sys.stdout.write("\nnew line")
            self.assertEqual(console.scroll_info.pos, 19)
            console._scroll(-100)
            console.auto_show = True
            sys.stderr.write("\nerror")
            self.assertEqual(console.scroll_info.pos, 0)
            self.assertTrue(console.auto_show_required)
            self.assertEqual(console.log.getLine(21), "error")

    def test_console_wraps_without_changing_copied_text_or_wide_character_positions(self):
        console = self.console(width=6, height=6)
        console._statusHeight = lambda total=None: 1
        def width(text):
            columns = 0
            for char in text:
                columns += 4 - columns % 4 if char == "\t" else 2 if ord(char) > 127 else 1
            return columns
        console.getStringWidth = width
        console.log = Log()
        console.log.write("abcdefghi\n日本AB\tZ\nlast")
        console.selection = [[0, 0], [0, 0]]
        console.paint()
        self.assertEqual(console._mousePosToLogPos(10, 40), (1, 0))
        self.assertEqual(console._mousePosToLogPos(20, 40), (1, 1))
        self.assertEqual(console._mousePosToLogPos(40, 60), (1, 5))
        with patch.object(ckit, "setClipboardText") as clipboard:
            console._onLeftButtonDown(20, 0, 0)
            console._onMouseMove(30, 20, 0)
            console._onLeftButtonUp(30, 20, 0)
            clipboard.assert_called_once_with("cdefghi")
            clipboard.reset_mock()
            console._onLeftButtonDown(20, 0, 0)
            console._onMouseMove(20, 40, 0)
            console._onLeftButtonUp(20, 40, 0)
            clipboard.assert_called_once_with("cdefghi\r\n日")
            clipboard.reset_mock()
            console.selection = [[1, 0], [1, 6]]
            console._copySelectedRegion()
            clipboard.assert_called_once_with("日本AB\tZ")
        self.assertIn("abcdef", [draw[-1] for draw in self.window.draws])
        self.assertIn("ghi", [draw[-1] for draw in self.window.draws])
        self.assertIn("    Z", [draw[-1] for draw in self.window.draws])
        self.assertTrue(all(draw[2] >= 0 for draw in self.window.draws))
        console.clearLog()
        console.write("last", auto_show=False)
        with patch.object(ckit, "setClipboardText") as clipboard:
            console._onLeftButtonDown(0, 0, 0)
            console._onMouseMove(0, 60, 0)
            console._onLeftButtonUp(0, 60, 0)
            clipboard.assert_called_once_with("last")

    def test_console_reflow_preserves_reading_anchor_selection_and_tail(self):
        console = self.console(width=6, height=3)
        console._statusHeight = lambda total=None: 1
        console.log = Log()
        console.log.write("abcdefghijklmnopqr\ntail")
        console.paint()
        console._scroll(1)
        self.assertEqual(console._getRows()[console.scroll_info.pos], (0, 6, 12))
        console.selection = [[0, 4], [0, 13]]
        console.width = lambda: 3
        console.paint()
        self.assertEqual(console._getRows()[console.scroll_info.pos], (0, 6, 9))
        self.assertEqual(console.selection, [[0, 4], [0, 13]])
        console._scroll(100)
        self.assertEqual(console.scroll_info.pos, 6)
        console.width = lambda: 6
        console.paint()
        self.assertEqual(console.scroll_info.pos, 2)
        console.height = lambda: 2
        console.paint()
        self.assertEqual(console.scroll_info.pos, 3)
        console.height = lambda: 5
        console.paint()
        self.assertEqual(console.scroll_info.pos, 0)
        with patch.object(ckit, "setClipboardText") as clipboard:
            console._copySelectedRegion()
            clipboard.assert_called_once_with("efghijklm")

    def test_console_wrapped_output_follows_tail_and_keeps_scrolled_position(self):
        console = self.console(width=6, height=3)
        console._statusHeight = lambda total=None: 1
        console.log = Log()
        console.log.write("abcdefghij")
        console.paint()
        console.write("klmno", auto_show=False)
        self.assertEqual(console.scroll_info.pos, 1)
        console._scroll(-100)
        console.write("pqrst", auto_show=False)
        self.assertEqual(console.scroll_info.pos, 0)
        self.assertEqual(console.log.getLine(0), "abcdefghijklmnopqrst")
        self.assertEqual(len(console._getRows()), 4)
        console.clearLog()
        self.assertEqual(console._getRows(), [(0, 0, 0)])
        self.assertEqual(console.selection, [[0, 0], [0, 0]])

    def test_console_wrap_cache_reuses_history_and_handles_1000_line_limit(self):
        console = self.console(width=6, height=4)
        console._statusHeight = lambda total=None: 1
        console.log = Log()
        console.log.write("\n".join("x" * 40 for _ in range(1000)))
        console.getStringWidth = Mock(wraps=console.getStringWidth)
        console._getRows()
        console._scroll(100)
        anchor = console._getRows()[console.scroll_info.pos]
        console.selection = [[998, 1], [999, 4]]
        console.mouse_click_info = [True, 0, 0, 998, 1, 999, 4]
        console.getStringWidth.reset_mock()
        for _ in range(10):
            console._getRows()
            console._scroll(0)
        console.getStringWidth.assert_not_called()
        with patch.object(console, "paint"):
            console.write("\n" + "y" * 40, auto_show=False)
        console._getRows()
        self.assertLessEqual(console.getStringWidth.call_count, 2)
        self.assertEqual(console.log.numLines(), 1000)
        self.assertEqual(console.log.first_line, 1)
        self.assertEqual(console._getRows()[console.scroll_info.pos], anchor)
        self.assertEqual(console.selection, [[997, 1], [998, 4]])
        self.assertEqual(console.mouse_click_info[3:], [997, 1, 998, 4])

    def test_console_narrow_wrap_progress_and_original_blank_lines(self):
        console = self.console(width=1, height=4)
        console._statusHeight = lambda total=None: 1
        console.getStringWidth = lambda text: sum(2 if ord(char) > 127 else 1 for char in text)
        console.log = Log()
        console.log.write("日🙂\n\nA")
        console.paint()
        self.assertEqual(console._getRows(), [(0, 0, 1), (0, 1, 2), (1, 0, 0), (2, 0, 1)])
        self.assertTrue(all(draw[2] >= 0 for draw in self.window.draws))
        console.width = lambda: 0
        self.assertEqual(len(console._getRows()), 4)

    def test_console_copy_rebases_selection_after_direct_log_eviction(self):
        console = self.console()
        console.log = Log()
        console.log.write("\n".join(f"old{i}" for i in range(1000)))
        console._getRows()
        console.selection = [[998, 0], [999, 6]]
        console.log.write("\nnew")
        with patch.object(ckit, "setClipboardText") as copy:
            console._copySelectedRegion()
        copy.assert_called_once_with("old998\r\nold999")
        self.assertEqual(console.selection, [[997, 0], [998, 6]])

    def test_console_paint_uses_one_snapshot_during_log_eviction(self):
        console = self.console()
        console.log = Log()
        console.log.write("\n".join(f"old{i}" for i in range(1000)))
        console.selection = [[0, 0], [0, 0]]
        measure = console.getStringWidth
        written = False
        def write_during_measure(text):
            nonlocal written
            if not written:
                written = True
                console.log.write("\nnew")
            return measure(text)
        console.getStringWidth = write_during_measure
        console.paint()
        self.assertIn("old0", [draw[-1] for draw in self.window.draws])
        self.assertEqual(console._wrap_cache["layout"].first_line, 0)
        console._getRows()
        self.assertEqual(console._wrap_cache["layout"].first_line, 1)

    def test_console_clear_releases_drag_capture(self):
        console = self.console()
        console._onLeftButtonDown(0, 0, 0)
        self.assertTrue(console.captured)
        console.clearLog()
        self.assertFalse(console.captured)
        self.assertIsNone(console.mouse_click_info)
        self.assertEqual(console.selection, [[0, 0], [0, 0]])

    def test_console_layout_failure_keeps_cache_scroll_and_selection_for_retry(self):
        console = self.console(width=6, height=4)
        console._getRows()
        console._scroll(4)
        previous = console._wrap_cache
        selection = [point[:] for point in console.selection]
        pos = console.scroll_info.pos
        console.log.write("\nnew line")
        with patch.object(console, "getStringWidth", side_effect=RuntimeError("measurement")), \
             self.assertRaisesRegex(RuntimeError, "measurement"):
            console._getRows()
        self.assertIs(console._wrap_cache, previous)
        self.assertEqual(console.selection, selection)
        self.assertEqual(console.scroll_info.pos, pos)
        console.paint()
        self.assertEqual(console._wrap_cache["layout"].revision, console.log.revision)

    def test_console_double_click_uses_the_layout_that_located_the_mouse(self):
        console = self.console()
        console.log = Log()
        console.log.write("oldword")
        console._statusHeight = lambda total=None: 1
        console._getRows()
        previous = console._wrap_cache
        locate = console._mousePosToLogPos

        def locate_then_append(x, y):
            point = locate(x, y)
            console.log.write("\n" + "new\n" * 1000)
            return point

        with patch.object(console, "_mousePosToLogPos", side_effect=locate_then_append), patch.object(console, "paint"):
            console._onLeftButtonDoubleClick(0, 0, 0)
        self.assertIs(console._wrap_cache, previous)
        self.assertEqual(console.selection, [[0, 0], [0, 7]])
        console._getRows()
        self.assertEqual(console._getView()["layout"].revision, console.log.revision)

    def test_console_eviction_clips_drag_endpoints_and_full_replacement(self):
        console = self.console(width=6, height=4)
        console.log = Log()
        console.log.write("\n".join("abcdefghi" for _ in range(1000)))
        console._getRows()
        console.selection = [[0, 2], [2, 4]]
        console.mouse_click_info = [True, 0, 0, 0, 2, 2, 4]
        console.log.write("\nnew\nlast")
        console._getRows()
        self.assertEqual(console.selection, [[0, 0], [0, 4]])
        self.assertEqual(console.mouse_click_info[3:], [0, 0, 0, 4])
        console.log.write("\n" + "new\n" * 1100)
        console._getRows()
        self.assertEqual(console.selection, [[0, 0], [0, 0]])
        self.assertEqual(console.mouse_click_info[3:], [0, 0, 0, 0])
        self.assertGreaterEqual(console.scroll_info.pos, 0)
        self.assertLess(console.scroll_info.pos, len(console._getRows()))

    def test_help_success_records_log_without_requesting_console_open(self):
        import clnch_mainwindow
        for opened in (False, True):
            for pending_error in (False, True):
                with self.subTest(opened=opened, pending_error=pending_error):
                    console = self.console()
                    console.opened = opened
                    console.auto_show = True
                    items = []
                    owner = SimpleNamespace(console_window=console)
                    with patch.object(ckit.JobQueue, "defaultQueue",
                                      return_value=SimpleNamespace(enqueue=items.append)):
                        clnch_mainwindow.MainWindow.command_Help(owner, None)
                    item = items[0]
                    item.help_message = clnch_mainwindow.strings.HELP_OPENED
                    item.help_opened = True
                    with patch.object(sys, "stdout", io.StringIO()), patch.object(sys, "stderr", io.StringIO()):
                        console.registerStdio()
                        if pending_error:
                            sys.stderr.write("unrelated error\n")
                        item.finished_func_list[0](item)
                    self.assertEqual(console.opened, opened)
                    self.assertEqual(console.auto_show_required, pending_error)
                    self.assertIn(clnch_mainwindow.strings.HELP_OPENED, "\n".join(console.log.log))
                    with patch.object(console, "show") as show, patch.object(console, "syncVisibility"):
                        console.onTimerAutoShow()
                    if pending_error:
                        show.assert_called_once_with(True, False)
                    else:
                        show.assert_not_called()
        console.debug = True
        console.auto_show_required = False
        before = list(console.log.log)
        with contextlib.redirect_stdout(io.StringIO()) as output:
            item.finished_func_list[0](item)
        self.assertEqual(output.getvalue(), clnch_mainwindow.strings.HELP_OPENED + "\n\n")
        self.assertEqual(console.log.log, before)
        self.assertFalse(console.auto_show_required)
        console.debug = False
        item.help_message = clnch_mainwindow.strings.HELP_MISSING.format(path="C:/app/docs/index.html")
        item.help_opened = False
        with patch.object(sys, "stdout", io.StringIO()), patch.object(sys, "stderr", io.StringIO()):
            console.registerStdio()
            item.finished_func_list[0](item)
        self.assertTrue(console.auto_show_required)

    def test_main_and_console_help_handle_optional_files_and_launch_failures(self):
        import clnch_mainwindow

        from ckit import ckit_threadutil
        for entry in ("main", "console"):
            for state in ("missing", "success", "directory", "stat_denied",
                          "launch_denied", "vanished", "cancelled"):
                with self.subTest(entry=entry, state=state), tempfile.TemporaryDirectory(prefix="Help 日本語 ") as directory:
                    path = Path(directory) / "docs" / clnch_mainwindow.strings.get_language() / "index.html"
                    if state != "missing":
                        path.parent.mkdir(parents=True)
                        if state == "directory":
                            path.mkdir()
                        else:
                            path.write_text("<html>help</html>", encoding="utf-8")
                    output, error = io.StringIO(), io.StringIO()
                    owner = SimpleNamespace()
                    owner.command = SimpleNamespace(
                        Help=lambda: clnch_mainwindow.MainWindow.command_Help(owner, None))  # noqa: B023  # Invoked before this subTest ends.
                    console = self.console()
                    console.parent_window = owner
                    owner.console_window = console
                    launch_error = (PermissionError("browser access denied") if state == "launch_denied"
                                    else FileNotFoundError("removed after stat") if state == "vanished" else None)
                    real_stat = clnch_mainwindow.os.stat
                    def file_stat(name, *args, **kwargs):
                        if state == "stat_denied" and str(name) == str(path):  # noqa: B023  # Worker is joined in this subTest.
                            raise PermissionError("cannot inspect help")
                        return real_stat(name, *args, **kwargs)  # noqa: B023  # Worker is joined in this subTest.
                    with patch.object(ckit_threadutil.ckitcore, "setBlockDetector"):
                        queue = ckit.JobQueue()
                        try:
                            with patch.object(ckit.JobQueue, "defaultQueue", return_value=queue), \
                                 patch.object(ckit, "getAppExePath", return_value=directory), \
                                 patch.object(clnch_mainwindow.os, "stat", side_effect=file_stat), \
                                 patch.object(clnch_mainwindow.pyauto, "shellExecute", side_effect=launch_error) as launch, \
                                 contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
                                if entry == "main":
                                    owner.command.Help()
                                else:
                                    console._onKeyDown(ckit.VK_F1, 0)
                                if state == "cancelled":
                                    queue.items[0].cancel()
                                queue.join()
                            if state in ("success", "launch_denied", "vanished"):
                                launch.assert_called_once_with(None, str(path), "", "")
                            else:
                                launch.assert_not_called()
                        finally:
                            if queue.is_alive():
                                queue.join()
                            queue.destroy()
                    wording = clnch_mainwindow.strings
                    if state == "success":
                        expected = wording.HELP_OPENED
                    elif state == "missing":
                        expected = wording.HELP_MISSING.format(path=path)
                    elif state == "directory":
                        expected = wording.HELP_NOT_FILE.format(path=path)
                    elif state == "stat_denied":
                        expected = wording.HELP_OPEN_ERROR.format(path=path, error="cannot inspect help")
                    elif state in ("launch_denied", "vanished"):
                        expected = wording.HELP_OPEN_ERROR.format(path=path, error=launch_error)
                    else:
                        expected = None
                    if state == "success":
                        self.assertEqual(output.getvalue(), "")
                        self.assertTrue(console.log.last_line_terminated)
                        self.assertIn(wording.HELP_OPENED, "\n".join(console.log.log))
                    else:
                        self.assertEqual(output.getvalue(), "" if expected is None else expected + "\n\n")
                    self.assertEqual(error.getvalue(), "")

    def test_console_small_window_and_resize_keep_valid_range(self):
        console = self.console(width=12, height=4)
        console._scroll(100)
        console.height = lambda: 12
        console.paint()
        self.assertEqual(console.scroll_info.pos, console.log.numLines() - console.rectText()[3])
        self.assertTrue(all(d[1]+d[3] <= 12 for d in self.window.draws))
        self.window.draws.clear()
        console.height = lambda: 1
        console.paint()
        self.assertEqual(len(self.window.draws), 1)
        self.assertEqual(self.window.draws[-1][:4], (0, 0, 12, 1))
        console.height = lambda: 0
        self.window.draws.clear()
        console.paint()
        self.assertFalse(self.window.draws)

    def test_text_widget_has_document_before_selection_initialization(self):
        documents = []

        class Edit(ckit.TextWidget):
            def pointDocumentBegin(self):
                documents.append(self.doc)
                return super().pointDocumentBegin()

            def paint(self, *args, **kwargs):
                pass

        edit = Edit(self.window, 0, 0, 30, 5)
        try:
            self.assertTrue(documents)
            self.assertTrue(all(doc is edit.doc for doc in documents))
            self.assertIsInstance(edit.doc, ckit.Document)
            self.assertEqual([(line.s, line.end) for line in edit.doc.lines], [("", "")])
            self.assertEqual(edit.selection.cursor(), edit.point(0, 0))
            self.assertEqual(edit.doc.text_modified_handler_list, [edit.onDocumentTextModified])
            self.assertEqual(edit.doc.bookmark_handler_list, [edit.onDocumentBookmark])
        finally:
            edit.destroy()

    def test_filter_lines_whole_rows_boundaries_and_undo_redo(self):
        cases = (
            ("keep", "keep\ndrop\ntail", (0, 0), (2, 4), lambda text: True,
             ["keep", "drop", "tail"], "keep\r\ndrop\r\ntail", (0, 0), (2, 4)),
            ("nonempty", "keep\ndrop\ntail", (0, 0), (2, 4), bool,
             ["keep", "drop", "tail"], "keep\r\ndrop\r\ntail", (0, 0), (2, 4)),
            ("middle", "keep\ndrop\ntail", (0, 0), (2, 4), lambda text: text != "drop",
             ["keep", "drop", "tail"], "keep\r\ntail", (0, 0), (1, 4)),
            ("adjacent", "a\nx\nx\nz", (0, 0), (3, 1), lambda text: text != "x",
             ["a", "x", "x", "z"], "a\r\nz", (0, 0), (1, 1)),
            ("all", "a\nb\nc", (0, 0), (2, 1), lambda text: False,
             ["a", "b", "c"], "", (0, 0), (0, 0)),
            ("empty_rows", "a\n\nb\n\n", (0, 0), (4, 0), bool,
             ["a", "", "b", ""], "a\r\nb\r\n", (0, 0), (2, 0)),
            ("trailing_newline", "keep\ndrop\ntail\n", (0, 0), (3, 0), lambda text: text != "drop",
             ["keep", "drop", "tail"], "keep\r\ntail\r\n", (0, 0), (2, 0)),
            ("end_column_zero", "keep\ndrop\ntail", (0, 2), (2, 0), lambda text: text != "drop",
             ["keep", "drop"], "keep\r\ntail", (0, 0), (1, 0)),
            ("last_row", "keep\ntail", (1, 2), (1, 4), lambda text: False,
             ["tail"], "keep\r\n", (1, 0), (1, 0)),
            ("empty_document", "", (0, 0), (0, 0), bool,
             [], "", (0, 0), (0, 0)),
            ("collapsed", "a\ndrop\nz", (1, 2), (1, 2), lambda text: False,
             ["drop"], "a\r\nz", (1, 0), (1, 0)),
            ("unicode", "日本語😀\n捨てる\n終端", (0, 0), (2, 2), lambda text: text != "捨てる",
             ["日本語😀", "捨てる", "終端"], "日本語😀\r\n終端", (0, 0), (1, 2)),
        )
        for name, text, start, end, keep, expected_calls, expected, final_left, final_right in cases:
            for reverse in (False, True):
                for column in (None, 0, 7):
                    with self.subTest(case=name, reverse=reverse, column=column), patch.object(ckit.TextWidget, "paint"):
                        edit = ckit.TextWidget(self.window, 0, 0, 30, 5)
                        try:
                            edit.modifyText(text=text)
                            original = edit.getText(edit.pointDocumentBegin(), edit.pointDocumentEnd())
                            left, right = edit.point(*start), edit.point(*end)
                            edit.setSelection(right, left) if reverse else edit.setSelection(left, right)
                            if column is not None:
                                edit.ideal_column = column
                            undo_left = left.lineBegin()
                            undo_right = right.lineEnd().right() if right.index else right.copy()
                            seen = []
                            def predicate(text, info, seen=seen, keep=keep):
                                seen.append(text)
                                return keep(text)
                            undo_count = len(edit.doc.undo_list)
                            with patch.object(edit, "_notifyTextModified", wraps=edit._notifyTextModified) as notify:
                                edit.filterLines(predicate)
                                self.assertEqual(seen, expected_calls)
                                self.assertEqual(edit.getText(edit.pointDocumentBegin(), edit.pointDocumentEnd()), expected)
                                self.assertEqual(edit.selection.left(), edit.point(*final_left))
                                self.assertEqual(edit.selection.right(), edit.point(*final_right))
                                notify.assert_called_once_with(undo_left, right, edit.point(*final_right))
                            self.assertIsNone(edit.doc.atomic_undo)
                            self.assertEqual(len(edit.doc.undo_list), undo_count + 1)
                            self.assertTrue(edit.undo())
                            self.assertEqual(edit.getText(edit.pointDocumentBegin(), edit.pointDocumentEnd()), original)
                            self.assertEqual(edit.selection.left(), undo_left)
                            self.assertEqual(edit.selection.right(), undo_right)
                            self.assertTrue(edit.redo())
                            self.assertEqual(edit.getText(edit.pointDocumentBegin(), edit.pointDocumentEnd()), expected)
                            self.assertEqual(edit.selection.left(), edit.point(*final_left))
                            self.assertEqual(edit.selection.right(), edit.point(*final_right))
                        finally:
                            edit.destroy()

    def test_filter_lines_metadata_is_mutable_per_row_snapshot(self):
        import gc
        import weakref

        with patch.object(ckit.TextWidget, "paint"):
            edit = ckit.TextWidget(self.window, 0, 0, 30, 5)
            edit_ref = weakref.ref(edit)
            try:
                edit.modifyText(text="a\nb\nc")
                for index, line in enumerate(edit.doc.lines):
                    line.bookmark = index + 1
                    line.modified = bool(index % 2)
                edit.setSelection(edit.pointDocumentEnd(), edit.pointDocumentBegin())
                saved = []
                column = edit.ideal_column
                def keep(text, info):
                    current = edit_ref()
                    assert current is not None
                    self.assertEqual(current.ideal_column, column)
                    saved.append(info)
                    self.assertEqual(vars(info), {"bookmark": len(saved), "modified": bool((len(saved) - 1) % 2)})
                    info.bookmark = 7
                    return True
                edit.filterLines(keep)
                self.assertEqual(len({id(info) for info in saved}), 3)
                self.assertEqual(len({type(info) for info in saved}), 1)
                self.assertEqual([line.bookmark for line in edit.doc.lines], [1, 2, 3])
                self.assertTrue(all(info.bookmark == 7 for info in saved))
                info_class = type(saved[0])
                empty = info_class()
                for name in ("bookmark", "modified"):
                    self.assertNotIn(name, vars(info_class))
                    with self.assertRaises(AttributeError) as caught:
                        getattr(empty, name)
                    self.assertEqual(str(caught.exception), f"'LineInfo' object has no attribute '{name}'")
                    self.assertEqual(caught.exception.name, name)
                    self.assertIs(caught.exception.obj, empty)
                sentinel = object()
                vars(saved[0])["extra"] = sentinel
                self.assertIs(vars(saved[0])["extra"], sentinel)
                for line in edit.doc.lines:
                    line.bookmark = 0
                    line.modified = True
                self.assertTrue(all(info.bookmark == 7 for info in saved))
                self.assertIs(saved[0].modified, False)
                later = []
                edit.filterLines(lambda text, info: later.append(info) or True)
                self.assertEqual(len(later), 3)
                self.assertIsNot(type(later[0]), info_class)
                self.assertEqual([vars(info) for info in later], [{"bookmark": 0, "modified": True}] * 3)
            finally:
                edit.destroy()
            del edit
            gc.collect()
            self.assertIsNone(edit_ref())

    def test_filter_lines_readonly_visits_each_row_without_modifying_text(self):
        with patch.object(ckit.TextWidget, "paint"):
            edit = ckit.TextWidget(self.window, 0, 0, 30, 5)
            try:
                edit.modifyText(text="keep\ndrop\ntail")
                edit.setSelection(edit.pointDocumentBegin(), edit.pointDocumentEnd())
                edit.doc.readonly = True
                modcount = edit.doc.modcount
                seen = []
                def reject(text, info):
                    seen.append(text)
                    return False
                with patch.object(edit, "setMessage") as message:
                    edit.filterLines(reject)
                self.assertEqual(seen, ["keep", "drop", "tail"])
                self.assertEqual(message.call_count, 3)
                self.assertTrue(all(call.kwargs == {"error": True} for call in message.call_args_list))
                self.assertEqual(edit.getText(edit.pointDocumentBegin(), edit.pointDocumentEnd()), "keep\r\ndrop\r\ntail")
                self.assertEqual(edit.doc.modcount, modcount)
                self.assertIsNone(edit.doc.atomic_undo)
                self.assertEqual(edit.doc.undo_list[-1].items, [])
            finally:
                edit.destroy()

    def test_filter_lines_callback_failure_closes_undo_without_final_notification(self):
        for error_type in (RuntimeError, KeyboardInterrupt, SystemExit):
            with self.subTest(error=error_type), patch.object(ckit.TextWidget, "paint"):
                edit = ckit.TextWidget(self.window, 0, 0, 30, 5)
                try:
                    edit.modifyText(text="drop\nkeep\ntail")
                    edit.setSelection(edit.pointDocumentBegin(), edit.pointDocumentEnd())
                    failure = error_type("filter callback failed")
                    seen = []
                    def reject_then_fail(text, info, seen=seen, failure=failure):
                        seen.append(text)
                        if len(seen) == 1:
                            return False
                        raise failure
                    with patch.object(edit, "_notifyTextModified") as notify:
                        with self.assertRaises(error_type) as caught:
                            edit.filterLines(reject_then_fail)
                        self.assertIs(caught.exception, failure)
                        self.assertEqual(seen, ["drop", "keep"])
                        self.assertIsNone(edit.doc.atomic_undo)
                        notify.assert_not_called()
                    self.assertEqual(edit.getText(edit.pointDocumentBegin(), edit.pointDocumentEnd()), "keep\r\ntail")
                    self.assertTrue(edit.undo())
                    self.assertEqual(edit.getText(edit.pointDocumentBegin(), edit.pointDocumentEnd()), "drop\r\nkeep\r\ntail")
                    self.assertTrue(edit.redo())
                    self.assertEqual(edit.selection.right(), edit.pointDocumentEnd())
                finally:
                    edit.destroy()

    def test_mouse_info_preserves_conditional_attributes_and_extra_values(self):
        from ckit.ckit_textwidget import MouseInfo

        left, right, extra = object(), object(), object()
        for mode, values in (("left", {}), ("lineno", {"line": 2}),
                             ("left_double", {"left": left, "right": right})):
            with self.subTest(mode=mode):
                info = MouseInfo(mode, extra=extra, **values)
                self.assertEqual(vars(info), {"mode": mode, "extra": extra, **values})
                self.assertIs(vars(info)["extra"], extra)
                for name in ("left", "right", "line"):
                    if name in values:
                        self.assertIs(getattr(info, name), values[name])
                    else:
                        self.assertNotIn(name, vars(MouseInfo))
                        with self.assertRaises(AttributeError) as caught:
                            getattr(info, name)
                        self.assertEqual(str(caught.exception),
                                         f"'MouseInfo' object has no attribute '{name}'")
                        self.assertEqual(caught.exception.name, name)
                        self.assertIs(caught.exception.obj, info)

    def test_text_widget_mouse_drag_preserves_character_word_and_line_selection(self):
        from ckit.ckit_textwidget import MouseInfo

        with patch.object(ckit.TextWidget, "paint"):
            edit = ckit.TextWidget(self.window, 0, 0, 30, 5)
            try:
                edit.modifyText(text="one two three\nnext line\nlast")
                margin = edit.lineNoWidth()
                edit.onLeftButtonDown(margin + 4, 0, 0, 0, 0)
                self.assertEqual(vars(edit.mouse_click_info), {"mode": "left"})
                edit.onMouseMove(margin + 7, 0, 0, 0, 0)
                self.assertEqual(edit.getText(edit.selection.left(), edit.selection.right()), "two")
                edit.onLeftButtonUp(margin + 7, 0, 0, 0, 0)
                self.assertIsNone(edit.mouse_click_info)

                edit.onLeftButtonDoubleClick(margin + 5, 0, 0, 0, 0)
                info = edit.mouse_click_info
                assert isinstance(info, MouseInfo)
                self.assertEqual(info.mode, "left_double")
                self.assertEqual((info.left.index, info.right.index), (4, 7))
                for index, expected in ((1, "one two"), (10, "two three"), (5, "two")):
                    edit.onMouseMove(margin + index, 0, 0, 0, 0)
                    self.assertIs(edit.mouse_click_info, info)
                    self.assertEqual(edit.getText(edit.selection.left(), edit.selection.right()), expected)

                edit.onLeftButtonDown(0, 1, 0, 0, 0)
                info = edit.mouse_click_info
                assert isinstance(info, MouseInfo)
                self.assertEqual(vars(info), {"mode": "lineno", "line": 1})
                for row, expected in ((0, ((0, 0), (2, 0))), (2, ((1, 0), (2, 4)))):
                    edit.onMouseMove(0, row, 0, 0, 0)
                    self.assertIs(edit.mouse_click_info, info)
                    left, right = edit.selection.left(), edit.selection.right()
                    self.assertEqual(((left.line, left.index), (right.line, right.index)), expected)
                edit.onLeftButtonUp(0, 2, 0, 0, 0)
                self.assertIsNone(edit.mouse_click_info)
            finally:
                edit.destroy()

    def test_text_widget_document_replacement_rebind_and_destroy(self):
        with patch.object(ckit.TextWidget, "paint"):
            edit = ckit.TextWidget(self.window, 0, 0, 30, 5)
            original = edit.doc
            replacement = ckit.Document(None, ckit.TextMode())
            text_handler = Mock()
            bookmark_handler = Mock()
            try:
                edit.modifyText(text="old")
                edit.setDocument(replacement)
                self.assertEqual(original.text_modified_handler_list, [])
                self.assertEqual(original.bookmark_handler_list, [])
                self.assertIs(edit.doc, replacement)
                self.assertEqual(edit.selection.cursor(), edit.point(0, 0))
                replacement.text_modified_handler_list.append(text_handler)
                replacement.bookmark_handler_list.append(bookmark_handler)
                edit.setDocument(replacement)
                self.assertEqual(replacement.text_modified_handler_list,
                                 [text_handler, edit.onDocumentTextModified])
                self.assertEqual(replacement.bookmark_handler_list,
                                 [bookmark_handler, edit.onDocumentBookmark])
                edit.modifyText(text="new")
                text_handler.assert_called_once()
                edit.bookmark(0, [1, 0])
                bookmark_handler.assert_called_once_with(edit, 0, 1)
                self.assertEqual(original.lines[0].s, "old")
            finally:
                edit.destroy()
            self.assertIs(edit.doc, replacement)
            self.assertEqual(replacement.text_modified_handler_list, [text_handler])
            self.assertEqual(replacement.bookmark_handler_list, [bookmark_handler])

    def test_text_widget_shared_document_keeps_other_widget_notifications(self):
        with patch.object(ckit.TextWidget, "paint") as paint:
            first = ckit.TextWidget(self.window, 0, 0, 30, 5)
            second = ckit.TextWidget(self.window, 0, 0, 30, 5)
            shared = first.doc
            try:
                second.setDocument(shared)
                first.modifyText(text="日本語😀")
                self.assertIs(second.doc, shared)
                self.assertEqual(second.getText(second.pointDocumentBegin(), second.pointDocumentEnd()),
                                 "日本語😀")
                first.destroy()
                self.assertEqual(shared.text_modified_handler_list, [second.onDocumentTextModified])
                self.assertEqual(shared.bookmark_handler_list, [second.onDocumentBookmark])
                paint.reset_mock()
                second.bookmark(0, [1, 0])
                self.assertEqual(paint.call_count, 1)
                second.modifyText(text="続き")
            finally:
                if first.onDocumentTextModified in shared.text_modified_handler_list:
                    first.destroy()
                second.destroy()
            self.assertEqual(shared.text_modified_handler_list, [])
            self.assertEqual(shared.bookmark_handler_list, [])

    def test_shared_document_end_line_and_following_line_positions(self):
        with patch.object(ckit.TextWidget, "paint"):
            views = [ckit.TextWidget(self.window, 0, 0, 30, 5) for _ in range(3)]
            first, second, third = views
            try:
                first.modifyText(text="abcDEFghi\n後続😀abcdef\nlast")
                second.setDocument(first.doc)
                third.setDocument(first.doc)
                second.setSelection(second.point(0, 8), second.point(1, 4))
                third.setSelection(third.point(1, 4), third.point(0, 8))
                first.modifyText(first.point(0, 3), first.point(0, 6), "全")
                self.assertEqual([line.s for line in first.doc.lines], ["abc全ghi", "後続😀abcdef", "last"])
                for view, endpoints in ((second, ((0, 6), (1, 4))), (third, ((1, 4), (0, 6)))):
                    self.assertEqual((view.selection.anchor(), view.selection.cursor()),
                                     tuple(view.point(*pos) for pos in endpoints))
                self.assertEqual(first.selection.cursor(), first.point(0, 4))
            finally:
                for view in views:
                    view.destroy()

    def test_shared_document_positions_match_character_offsets(self):
        original = "A😀e\u0301全xyz\n0123456789\n後続😀abcdef\nend"
        cases = (
            ((0, 2), (0, 5), "全"),
            ((0, 2), (0, 3), "長い😀置換"),
            ((1, 3), (1, 3), "挿入😀"),
            ((0, 2), (0, 2), "\n追記\n"),
            ((0, 2), (1, 4), ""),
            ((0, 2), (2, 3), "全\n😀"),
            ((1, 1), (1, 5), "日\n本\n語😀"),
            ((0, 0), (0, 0), "先頭\n"),
            ((3, 3), (3, 3), "\n末尾😀"),
            ((0, 0), (3, 3), ""),
            ((1, 0), (2, 0), ""),
            ((1, 2), (1, 2), ""),
        )

        def offset(text, pos):
            lines = text.split("\n")
            return sum(len(line) + 1 for line in lines[:pos[0]]) + pos[1]

        def position(text, index):
            prefix = text[:index]
            return prefix.count("\n"), len(prefix.rsplit("\n", 1)[-1])

        # Use flat character offsets as an oracle independent of line/column arithmetic.
        def mapped(index, left, right, size):
            if index < left:
                return index
            if index < right:
                return left
            return index + size - (right - left)

        with patch.object(ckit.TextWidget, "paint"):
            for left, right, replacement in cases:
                start, end = offset(original, left), offset(original, right)
                changed = original[:start] + replacement + original[end:]
                for count in (2, 3):
                    for index in range(len(original) + 1):
                        with self.subTest(left=left, right=right, text=replacement, views=count, index=index):
                            views = [ckit.TextWidget(self.window, 0, 0, 30, 5) for _ in range(count)]
                            sender = views[0]
                            try:
                                sender.doc.lineend = "\n"
                                sender.modifyText(text=original)
                                pairs = []
                                for number, view in enumerate(views[1:]):
                                    view.setDocument(sender.doc)
                                    pair = (index, len(original) - index)
                                    if number:
                                        pair = pair[::-1]
                                    pairs.append(pair)
                                    view.setSelection(*(view.point(*position(original, value)) for value in pair))
                                sender.modifyText(sender.point(*left), sender.point(*right), replacement)
                                self.assertEqual(sender.getText(sender.pointDocumentBegin(), sender.pointDocumentEnd()), changed)
                                after = [tuple(mapped(value, start, end, len(replacement)) for value in pair) for pair in pairs]
                                for view, pair in zip(views[1:], after):
                                    self.assertEqual((view.selection.anchor(), view.selection.cursor()),
                                                     tuple(view.point(*position(changed, value)) for value in pair))
                                    self.assertIs(view.selection.anchor().edit, view)
                                    self.assertIs(view.selection.cursor().edit, view)
                                self.assertEqual(sender.selection.cursor(), sender.point(*position(changed, start + len(replacement))))
                                self.assertTrue(sender.undo())
                                self.assertEqual(sender.getText(sender.pointDocumentBegin(), sender.pointDocumentEnd()), original)
                                restored = [tuple(mapped(value, start, start + len(replacement), end - start) for value in pair) for pair in after]
                                for view, pair in zip(views[1:], restored):
                                    self.assertEqual((view.selection.anchor(), view.selection.cursor()),
                                                     tuple(view.point(*position(original, value)) for value in pair))
                                    self.assertIs(view.selection.anchor().edit, view)
                                    self.assertIs(view.selection.cursor().edit, view)
                                self.assertEqual(sender.selection.cursor(), sender.point(*right))
                                self.assertTrue(sender.redo())
                                for view, pair in zip(views[1:], restored):
                                    replayed = [mapped(value, start, end, len(replacement)) for value in pair]
                                    self.assertEqual((view.selection.anchor(), view.selection.cursor()),
                                                     tuple(view.point(*position(changed, value)) for value in replayed))
                                    self.assertIs(view.selection.anchor().edit, view)
                                    self.assertIs(view.selection.cursor().edit, view)
                                self.assertEqual(sender.selection.cursor(), sender.point(*position(changed, start + len(replacement))))
                            finally:
                                for view in views:
                                    view.destroy()

    def test_shared_document_selection_preserves_virtual_columns_and_normalization(self):
        with patch.object(ckit.TextWidget, "paint"):
            first = ckit.TextWidget(self.window, 0, 0, 30, 5)
            second = ckit.TextWidget(self.window, 0, 0, 30, 5)
            try:
                first.modifyText(text="abcdef\n0123456789")
                second.setDocument(first.doc)
                second.setSelection(second.point(1, 12), second.point(0, 9), block_mode=True)
                first.modifyText(first.point(0, 1), first.point(0, 4), "全")
                self.assertTrue(second.selection.block_mode)
                self.assertEqual(second.selection.anchor(), second.point(1, 12))
                self.assertEqual(second.selection.cursor(), second.point(0, 7))
                self.assertEqual(second.selection.direction, -1)
                self.assertEqual(second.selection.left(), second.point(0, 7))
                self.assertEqual(second.selection.right(), second.point(1, 12))
                # Point/setSelection retain virtual indices; only setCursor clamps to line end.
                second.setCursor(second.selection.cursor())
                self.assertEqual(second.selection.cursor(), second.point(0, 4))
                self.assertFalse(second.selection.block_mode)
                second.setCursor(second.point(0, 2))
                first.modifyText(first.point(0, 1), first.point(0, 3), "Z")
                self.assertIs(second.selection.cursor().edit, second)
                self.assertEqual(second.selection.cursor().down(), second.point(1, 1))
            finally:
                first.destroy()
                second.destroy()

    def test_text_widget_atomic_undo_and_unknown_modification_count(self):
        with patch.object(ckit.TextWidget, "paint"):
            edit = ckit.TextWidget(self.window, 0, 0, 30, 5)
            try:
                edit.modifyText(text="元")
                edit.doc.clearModified()
                edit.atomicUndoBegin()
                edit.modifyText(text="日本語")
                edit.modifyText(text="😀")
                edit.atomicUndoEnd()
                self.assertIsNone(edit.doc.atomic_undo)
                self.assertEqual(edit.doc.lines[0].s, "元日本語😀")
                self.assertTrue(edit.undo())
                self.assertEqual(edit.doc.lines[0].s, "元")
                self.assertFalse(edit.doc.isModified())
                self.assertTrue(edit.redo())
                self.assertEqual(edit.doc.lines[0].s, "元日本語😀")
                edit.setLineEnd("\n")
                self.assertIsNone(edit.doc.modcount)
                edit.modifyText(text="追記")
                self.assertIsNone(edit.doc.modcount)
                self.assertTrue(edit.doc.isModified())
            finally:
                edit.destroy()

    def test_atomic_undo_end_preserves_copy_order_replacement_and_failures(self):
        from ckit.ckit_textwidget import AtomicUndoInfo, TextWidget
        for stage in ("normal", "missing", "anchor_replace", "cursor_replace", "cursor_clear", "copy_error"):
            with self.subTest(stage=stage):
                events = []
                first, second = AtomicUndoInfo(), AtomicUndoInfo()
                with patch.object(ckit.TextWidget, "paint"):
                    edit = ckit.TextWidget(self.window, 0, 0, 30, 5)
                self.addCleanup(edit.destroy)
                doc = edit.doc
                doc.atomic_undo = None if stage == "missing" else first
                anchor_value, cursor_value = object(), object()
                failure = RuntimeError("copy failed")
                def copy_anchor(events=events, stage=stage, doc=doc, second=second, failure=failure, anchor_value=anchor_value):
                    events.append("anchor")
                    if stage == "anchor_replace":
                        doc.atomic_undo = second
                    if stage == "copy_error":
                        raise failure
                    return anchor_value
                def copy_cursor(events=events, stage=stage, doc=doc, second=second, cursor_value=cursor_value):
                    events.append("cursor")
                    if stage == "cursor_replace":
                        doc.atomic_undo = second
                    elif stage == "cursor_clear":
                        doc.atomic_undo = None
                    return cursor_value
                def end(edit=edit, copy_anchor=copy_anchor, copy_cursor=copy_cursor):
                    return TextWidget.atomicUndoEnd(edit, SimpleNamespace(copy=copy_anchor), SimpleNamespace(copy=copy_cursor))
                if stage in ("missing", "cursor_clear"):
                    name = "new_anchor" if stage == "missing" else "new_cursor"
                    with self.assertRaises(AttributeError) as raised:
                        end()
                    self.assertEqual(str(raised.exception), f"'NoneType' object has no attribute '{name}' and no __dict__ for setting new attributes")
                    self.assertEqual(raised.exception.name, name)
                    self.assertIsNone(raised.exception.obj)
                    self.assertEqual(doc.undo_list, [])
                    self.assertIsNone(doc.atomic_undo)
                elif stage == "copy_error":
                    with self.assertRaises(RuntimeError) as raised:
                        end()
                    self.assertIs(raised.exception, failure)
                    self.assertIs(doc.atomic_undo, first)
                    self.assertEqual(doc.undo_list, [])
                else:
                    self.assertIsNone(end())
                    target = second if stage.endswith("replace") else first
                    self.assertEqual(doc.undo_list, [target])
                    self.assertIs(target.new_cursor, cursor_value)
                    self.assertIsNone(doc.atomic_undo)
                self.assertEqual(events, ["anchor"] if stage in ("missing", "copy_error") else ["anchor", "cursor"])
                if stage not in ("missing", "copy_error"):
                    self.assertIs((second if stage == "anchor_replace" else first).new_anchor, anchor_value)

    def test_text_widget_document_selection_scroll_and_hide(self):
        from ckit import ckit_theme
        get_color = ckit_theme.getColor
        def color(name, section="COLOR"):
            return get_color(name, section) if ckit_theme.ini.has_option(section, name) else get_color("fg")
        with patch.object(ckit_theme, "getColor", color):
            ckit.TextWidget.updateColor()
            edit = ckit.TextWidget(self.window, 0, 0, 30, 5)
            edit.modifyText(text="hello\nworld")
            self.assertIsInstance(edit.doc.lines[0], ckit.Line)
            edit.paint()
            self.assertTrue(any("hello" in d[-1] for d in self.window.draws))
            self.assertTrue(all(d[0] == 28 and d[2] == 2 for d in self.window.draws[-5:]))
            edit.setPosSize(1, 1, 32, 6)
            edit.show(False)
            count = len(self.window.draws)
            edit.paint()
            self.assertEqual(len(self.window.draws), count)
            edit.show(True)
            edit.paint()
            edit.destroy()


    def test_text_widget_unicode_edit_selection_undo_redo_and_scroll(self):
        from ckit import ckit_theme
        get_color = ckit_theme.getColor
        def color(name, section="COLOR"):
            return get_color(name, section) if ckit_theme.ini.has_option(section, name) else get_color("fg")
        with patch.object(ckit_theme, "getColor", color):
            ckit.TextWidget.updateColor()
            edit = ckit.TextWidget(self.window, 0, 0, 30, 5)
            try:
                edit.doc.lineend = "\r\n"
                edit.modifyText(text="日本語😀\nsecond\nthird")
                original = [("日本語😀", "\r\n"), ("second", "\r\n"), ("third", "")]
                self.assertEqual([(line.s, line.end) for line in edit.doc.lines], original)
                self.window.draws.clear()
                edit.setCursor(edit.point(0, 0))
                edit.paint()
                rendered = "".join(draw[-1] for draw in self.window.draws)
                for text in ("日本語😀", "second", "third"):
                    self.assertIn(text, rendered)

                edit.setSelection(edit.point(0, 3), edit.point(1, 3))
                self.assertEqual(edit.selection.anchor(), edit.point(0, 3))
                self.assertEqual(edit.selection.cursor(), edit.point(1, 3))
                self.assertEqual(edit.getText(edit.selection.left(), edit.selection.right()), "😀\r\nsec")
                edit.modifyText(text="差替\n追記\n")
                changed = [("日本語差替", "\r\n"), ("追記", "\r\n"), ("ond", "\r\n"), ("third", "")]
                self.assertEqual([(line.s, line.end) for line in edit.doc.lines], changed)
                self.assertEqual(edit.selection.cursor(), edit.point(2, 0))
                self.assertTrue(edit.undo())
                self.assertEqual([(line.s, line.end) for line in edit.doc.lines], original)
                self.assertEqual(edit.selection.anchor(), edit.point(1, 3))
                self.assertEqual(edit.selection.cursor(), edit.point(1, 3))
                self.assertTrue(edit.redo())
                self.assertEqual([(line.s, line.end) for line in edit.doc.lines], changed)
                self.assertEqual(edit.selection.cursor(), edit.point(2, 0))
                edit.modifyText(anchor=edit.point(0, 3), cursor=edit.point(2, 0), text="")
                self.assertEqual([(line.s, line.end) for line in edit.doc.lines],
                                 [("日本語ond", "\r\n"), ("third", "")])
                edit.setCursor(edit.pointDocumentBegin())
                self.window.draws.clear()
                edit.scrollV(1)
                self.assertEqual(edit.visible_first_line, 1)
                self.assertTrue(any("third" in draw[-1] for draw in self.window.draws))
                edit.scrollV(-1)
                self.assertEqual(edit.visible_first_line, 0)
            finally:
                edit.destroy()

    def test_text_document_selects_mode_once_after_reading(self):
        from ckit import ckit_misc
        events = []
        mode = ckit.TextMode()

        class Document(ckit.Document):
            def readFile(self, fd, encoding=None):
                events.append(("read", hasattr(self, "mode"), hasattr(self, "lexer")))
                return super().readFile(fd, encoding)

            def setMode(self, selected):
                events.append(("mode", selected, [line.s for line in self.lines]))
                return super().setMode(selected)

        with tempfile.TemporaryDirectory() as directory:
            filename = Path(directory) / "input.txt"
            filename.write_bytes("日本語\ntext".encode())
            with patch.object(ckit_misc, "getFileAttribute", return_value=0):
                doc = Document(str(filename), mode)
        self.assertEqual(events, [("read", False, False), ("mode", mode, ["日本語", "text"])])
        self.assertIs(doc.mode, mode)
        self.assertIs(doc.lexer, mode.lexer)

    def test_text_document_large_file_mode_thresholds(self):
        from ckit import ckit_misc
        cases = ((100000, 10 * 1024 * 1024, False),
                 (100001, 1, True), (1, 10 * 1024 * 1024 + 1, True))
        for line_count, file_size, fallback in cases:
            with self.subTest(lines=line_count, size=file_size):
                mode = ckit.TextMode()
                selected = []

                class Document(ckit.Document):
                    def readFile(self, fd, encoding=None, line_count=line_count):
                        self.lines = [ckit.Line("x")] * line_count

                    def setMode(self, value, selected=selected):
                        selected.append(value)
                        return super().setMode(value)

                fd = io.BytesIO()
                with patch("builtins.open", return_value=fd), \
                     patch.object(fd, "tell", return_value=file_size), \
                     patch.object(ckit_misc.os.path, "exists", return_value=True), \
                     patch.object(ckit_misc, "getFileAttribute", return_value=0):
                    doc = Document("threshold.txt", mode)
                self.assertEqual(len(selected), 1)
                self.assertIs(doc.mode, selected[0])
                self.assertIs(doc.lexer, doc.mode.lexer)
                self.assertIs(doc.mode is mode, not fallback)
                self.assertIsInstance(doc.mode, ckit.TextMode)

    def test_text_document_read_failure_does_not_select_mode(self):
        failure = UnicodeError("read failed")
        selected = []

        class Document(ckit.Document):
            def readFile(self, fd, encoding=None):
                raise failure

            def setMode(self, mode):
                selected.append(mode)
                return super().setMode(mode)

        with tempfile.TemporaryDirectory() as directory:
            filename = Path(directory) / "input.txt"
            filename.write_bytes(b"text")
            with self.assertRaises(UnicodeError) as raised:
                Document(str(filename), ckit.TextMode())
        self.assertIs(raised.exception, failure)
        self.assertEqual(selected, [])

    def test_text_document_mode_change_invalidates_syntax_and_keeps_lexer(self):
        from ckit import ckit_textwidget
        doc = ckit.Document(None, ckit.TextMode())
        doc.readFile(io.BytesIO(b"first\nsecond"))
        doc.updateSyntaxContext()
        doc.updateSyntaxTokens()
        self.assertTrue(all(line.ctx is not None and line.tokens is not None for line in doc.lines))
        lexer = ckit_textwidget.RegexLexer()
        lexer.rule_map = {"root": [("first", ckit_textwidget.Token_Keyword),
                                   (None, ckit_textwidget.Token_Text)]}

        class Mode(ckit.Mode):
            def __init__(self):
                super().__init__()
                self.lexer = lexer

        mode = Mode()
        doc.setMode(mode)
        self.assertIs(doc.mode, mode)
        self.assertIs(doc.lexer, lexer)
        self.assertTrue(all(line.ctx is None and line.tokens is None for line in doc.lines))
        self.assertEqual((doc.lex_ctx_dirty_top, doc.lex_token_dirty_top), (0, 0))
        doc.updateSyntaxContext()
        doc.updateSyntaxTokens()
        self.assertEqual(ckit_textwidget.Token.unpack(doc.lines[0].tokens),
                         [(0, ckit_textwidget.Token_Keyword)])
        self.assertEqual(ckit_textwidget.Token.unpack(doc.lines[1].tokens),
                         [(0, ckit_textwidget.Token_Text)])

    def test_text_document_file_roundtrip_keeps_line_endings(self):
        cases = [("", [("", "")]),
                 ("日本語😀\r\nabc\ncr\rnul\0end",
                  [("日本語😀", "\r\n"), ("abc", "\n"), ("cr", "\r"), ("nul\0end", "")])]
        cases.extend((f"日本語😀{end}abc{end}", [("日本語😀", end), ("abc", end), ("", "")])
                     for end in ("\r", "\n", "\r\n"))
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.txt"
            target = Path(directory) / "target.txt"
            for text, expected in cases:
                with self.subTest(text=repr(text)):
                    data = text.encode("utf-8")
                    source.write_bytes(data)
                    doc = ckit.Document(None, ckit.TextMode())
                    with source.open("rb") as fd:
                        doc.readFile(fd, ckit.TextEncoding("utf-8"))
                    self.assertTrue(all(isinstance(line, ckit.Line) for line in doc.lines))
                    self.assertEqual([(line.s, line.end) for line in doc.lines], expected)
                    with target.open("wb") as fd:
                        doc.writeFile(fd)
                    self.assertEqual(target.read_bytes(), data)


class EditCandidateTests(unittest.TestCase):
    def setUp(self):
        ckit.setTheme("black", {})

        class Parent(Window):
            def __init__(self):
                super().__init__()
                self.delayed = []
                self.removed_keys = 0

            def charToScreen(self, x, y): return x * 10, y * 20
            def delayedCall(self, handler, delay): self.delayed.append((handler, delay))
            def removeKeyMessage(self): self.removed_keys += 1

        self.window = Parent()
        self.created = []

        def create():
            candidate = Mock()
            candidate.items = []
            candidate.numItems.side_effect = lambda: len(candidate.items)

            def set_items(x, y1, y2, items, selection):
                candidate.items = list(items)

            candidate.setItems.side_effect = set_items
            candidate.onKeyDown.return_value = True
            candidate.getSelection.return_value = 0
            self.created.append(candidate)
            return candidate

        self.enterContext(patch.object(ckit.EditWidget, "createCandidateWindow", side_effect=create))

    def edit(self, candidate_handler=None, candidate_remove_handler=None):
        edit = ckit.EditWidget(self.window, 0, 0, 30, 1, "a",
                              candidate_handler=candidate_handler,
                              candidate_remove_handler=candidate_remove_handler)
        self.addCleanup(edit.destroy)
        return edit

    def test_without_completion_keeps_no_candidate_window(self):
        edit = self.edit()
        self.assertIsNone(edit.list_window)
        self.assertIsNone(edit.isListOpened())
        edit.closeList()
        edit.popupList()
        self.assertFalse(self.created)
        self.assertFalse(self.window.delayed)

    def test_navigation_empty_candidates_and_disabled_handler(self):
        edit = self.edit(lambda info: (["alpha", "alpine"], 0))
        first = self.created[0]
        for key, mod in ((ckit.VK_SPACE, ckit.MODKEY_SHIFT), (ckit.VK_DOWN, 0)):
            with self.subTest(key=key, mod=mod), patch.object(edit, "insertText") as insert:
                self.assertTrue(edit.onKeyDown(key, mod))
                insert.assert_called_once_with("")
                first.onKeyDown.assert_not_called()
        first.items = ["alpha", "alpine"]
        for key, mod in ((ckit.VK_SPACE, ckit.MODKEY_SHIFT), (ckit.VK_UP, 0),
                         (ckit.VK_DOWN, 0), (ckit.VK_PRIOR, 0), (ckit.VK_NEXT, 0)):
            self.assertTrue(edit.onKeyDown(key, mod))
            first.onKeyDown.assert_called_with(key, mod)
        self.assertTrue(edit.onKeyDown(ckit.VK_ESCAPE, 0))
        self.assertEqual(first.items, [])
        first.setItems.reset_mock()
        first.onKeyDown.reset_mock()
        edit.candidate_handler = None
        edit.closeList()
        edit.popupList()
        edit.onKeyDown(ckit.VK_DOWN, 0)
        first.setItems.assert_not_called()
        first.onKeyDown.assert_not_called()

    def test_popup_reuses_same_geometry_and_delays_only_old_window(self):
        edit = self.edit(lambda info: (["alpha", "alpine"], 0))
        first = self.created[0]
        edit.popupListPrepare(complete=False)
        edit.popupList()
        second = self.created[1]
        first.enable.assert_called_once_with(False)
        first.destroy.assert_not_called()
        self.assertEqual(second.items, ["alpha", "alpine"])
        self.assertIs(edit.list_window, second)
        self.assertEqual(len(self.window.delayed), 1)
        callback, delay = self.window.delayed[0]
        self.assertEqual(delay, 50)
        edit.popupListPrepare(complete=False)
        edit.popupList()
        self.assertEqual(len(self.created), 2)
        edit.closeList()
        self.assertEqual(second.items, [])
        edit.popupListPrepare(complete=False)
        edit.popupList()
        third = self.created[2]
        callback()
        first.destroy.assert_called_once_with()
        second.destroy.assert_not_called()
        third.destroy.assert_not_called()

    def test_tab_prefix_and_candidate_removal_keep_update_contract(self):
        accepted = []
        edit = self.edit(lambda info: (["alpha", "alpine"], 0),
                         lambda text: accepted.append(text) or True)
        self.assertTrue(edit.onKeyDown(ckit.VK_TAB, 0))
        self.assertEqual(edit.getText(), "alp")
        current = self.created[-1]
        self.assertTrue(edit.removeCandidate())
        current.remove.assert_called_once_with(0)
        self.assertEqual(accepted, ["alp"])
        current.items = []
        self.assertTrue(edit.removeCandidate())
        self.assertEqual(edit.getText(), "")
        edit.candidate_remove_handler = lambda text: False
        self.assertFalse(edit.removeCandidate())


class WidgetLifecycleTests(unittest.TestCase):
    def setUp(self):
        ckit.setTheme("black", {})
        self.window = Window()

    def test_ime_preference_only_changes_focused_parent(self):
        self.window.enableIme = Mock()
        self.window.setImeRect = Mock()
        focused = ckit.Widget(self.window, 1, 2, 10, 1)
        other = ckit.Widget(self.window, 3, 4, 10, 1)
        focused.enableIme(True)
        other.enableIme(False)
        self.window.enableIme.assert_not_called()
        focused.enableCursor(True)
        self.window.enableIme.assert_called_once_with(True)
        self.window.setImeRect.assert_called_with((10, 40, 110, 60))
        focused.enableIme(False)
        self.window.enableIme.assert_called_with(False)
        count = self.window.enableIme.call_count
        other.enableIme(True)
        self.assertEqual(self.window.enableIme.call_count, count)
        focused.enableCursor(False)
        other.enableCursor(True)
        self.window.enableIme.assert_called_with(True)
        other.enableCursor(False)
        focused.enableCursor(True)
        self.window.enableIme.assert_called_with(False)

    def test_progress_transitions_timer_uniqueness_and_input_ownership(self):
        self.window.setTimer = Mock(wraps=self.window.setTimer)
        self.window.killTimer = Mock(wraps=self.window.killTimer)
        bar = ckit.ProgressBarWidget(self.window, 0, 0, 10, 2)
        original = [-1, 2]
        bar.setValue(original)
        self.assertEqual(original, [-1, 2])
        self.assertEqual(bar.getValue(), [0, 1])
        self.assertIsNot(bar.getValue(), original)
        original[:] = [0.9]
        self.assertEqual(bar.getValue(), [0, 1])
        for _ in range(3):
            bar.setValue(None)
            bar.setValue(None)
            self.assertEqual(len(self.window.timers), 1)
            count = len(self.window.draws)
            bar.setValue((0, 1))
            self.assertGreater(len(self.window.draws), count)
            self.assertFalse(self.window.timers)
            self.assertEqual(self.window.draws[-1][2], 10)
        bar.setValue(None)
        for _ in range(3):
            bar.show(False)
            bar.show(False)
            self.assertFalse(self.window.timers)
            count = len(self.window.draws)
            bar._onTimer()
            self.assertEqual(len(self.window.draws), count)
            bar.show(True)
            bar.show(True)
            self.assertEqual(len(self.window.timers), 1)
        self.assertEqual(self.window.setTimer.call_count, 7)
        bar.destroy()
        bar.destroy()
        count = len(self.window.draws)
        bar._onTimer()
        bar.show(True)
        bar.setValue(None)
        self.assertFalse(self.window.timers)
        self.assertEqual(len(self.window.draws), count)
        self.assertEqual(self.window.killTimer.call_count, 7)
        bar = ckit.ProgressBarWidget(self.window, 0, 0, 10, 1)
        bar.setValue(0.5)
        bar.setValue(None)
        bar.setValue(0.5)
        self.assertEqual(self.window.draws[-1][2], 5)
        self.assertFalse(self.window.timers)
        bar.show(False)
        bar.setValue(None)
        self.assertFalse(self.window.timers)
        bar.destroy()

    def test_color_visibility_destroy_and_partial_construction(self):
        from ckit import ckit_widget
        self.window.getCharSize = lambda: (10, 20)
        for fail_at in (None, 0, 1, "paint"):
            with self.subTest(fail_at=fail_at):
                planes = []
                def plane(*args, fail_at=fail_at, planes=planes):
                    if fail_at == len(planes):
                        raise RuntimeError("plane")
                    result = Mock()
                    planes.append(result)
                    return result
                with patch.object(ckit_widget.ckitcore, "ImagePlane", side_effect=plane):
                    if fail_at is not None:
                        with patch.object(ckit.ColorWidget, "paint", side_effect=RuntimeError("paint")), \
                             self.assertRaises(RuntimeError):
                            ckit.ColorWidget(self.window, 0, 0, 20, 1, "color", (1, 2, 3))
                    else:
                        color = ckit.ColorWidget(self.window, 0, 0, 20, 1, "color", (1, 2, 3))
                        color.show(False)
                        for resource in planes:
                            resource.show.assert_called_with(False)
                        count = len(self.window.draws)
                        color.paint()
                        self.assertEqual(len(self.window.draws), count)
                        color.show(True)
                        for resource in planes:
                            resource.show.assert_called_with(True)
                        color.destroy()
                        color.destroy()
                for resource in planes:
                    resource.destroy.assert_called_once_with()

    def test_time_calendar_boundaries_and_incomplete_edits(self):
        valid = (2024, 2, 29, 23, 59, 59)
        for timestamp in (valid, (1, 1, 1, 0, 0, 0), (9999, 12, 31, 23, 59, 59), (2000, 2, 29, 0, 0, 0)):
            widget = ckit.TimeWidget(self.window, 1, 2, timestamp)
            self.assertEqual(widget.getValue(), timestamp)
            widget.destroy()
        for timestamp in ((0, 1, 1, 0, 0, 0), (2023, 2, 29, 0, 0, 0), (1900, 2, 29, 0, 0, 0),
                          (2024, 4, 31, 0, 0, 0), (2024, 0, 1, 0, 0, 0), (2024, 1, 0, 0, 0, 0),
                          (2024, 1, 1, 24, 0, 0), (2024, 1, 1, 0, 60, 0), (2024, 1, 1, 0, 0, 60),
                          (10000, 1, 1, 0, 0, 0), (2024, 1, 1, -1, 0, 0)):
            with self.subTest(timestamp=timestamp), self.assertRaises(ValueError):
                ckit.TimeWidget(self.window, 0, 0, timestamp)
        widget = ckit.TimeWidget(self.window, 1, 2, valid)
        self.addCleanup(widget.destroy)
        widget.month_edit.setText("04")
        widget.day_edit.setText("31")
        with self.assertRaises(ValueError):
            widget.getValue()
        self.assertEqual(widget.day_edit.getText(), "31")
        widget.day_edit.setText("30")
        self.assertEqual(widget.getValue(), (2024, 4, 30, 23, 59, 59))
        for handler, limit in ((widget.onYearUpdate, 9999), (widget.onMonthUpdate, 12),
                               (widget.onDayUpdate, 31), (widget.onHourUpdate, 23),
                               (widget.onMinuteUpdate, 59), (widget.onSecondUpdate, 59)):
            for text in ("", "0", str(limit)):
                self.assertTrue(handler(ckit.EditWidget.UpdateInfo(text, [0, 0])))
            for text in ("-1", "text", str(limit + 1)):
                self.assertFalse(handler(ckit.EditWidget.UpdateInfo(text, [0, 0])))
        widget.focus = widget.FOCUS_YEAR
        widget.year_edit.selectAll()
        widget.onChar(ord("0"), 0)
        with self.assertRaises(ValueError):
            widget.getValue()
        self.assertEqual(widget.year_edit.getText(), "0000")
        widget.year_edit.selectAll()
        for char in "2024":
            widget.onChar(ord(char), 0)
        self.assertEqual(widget.getValue(), (2024, 4, 30, 23, 59, 59))

    def test_time_move_visibility_focus_and_partial_construction(self):
        from ckit import ckit_widget
        timestamp = (2024, 2, 29, 12, 34, 56)
        widget = ckit.TimeWidget(self.window, 1, 2, timestamp)
        fields = [widget.year_edit, widget.month_edit, widget.day_edit, widget.hour_edit,
                  widget.minute_edit, widget.second_edit]
        widget.enableCursor(True)
        widget.onKeyDown(ckit.VK_RIGHT, 0)
        self.assertEqual(widget.focus, widget.FOCUS_MONTH)
        self.window.setImeRect = Mock()
        fields[1].enableIme(True)
        widget.setPosSize(4, 5, 100, 10)
        self.assertEqual((widget.width, widget.height), (22, 1))
        self.assertEqual([(edit.x, edit.y, edit.width, edit.height) for edit in fields],
                         [(5, 5, 4, 1), (10, 5, 2, 1), (13, 5, 2, 1),
                          (17, 5, 2, 1), (20, 5, 2, 1), (23, 5, 2, 1)])
        self.window.setImeRect.assert_called_with((100, 100, 120, 120))
        self.assertTrue(fields[1].enable_cursor)
        self.assertEqual(widget.getValue(), timestamp)
        widget.show(False)
        self.assertTrue(all(not edit.visible for edit in fields))
        count = len(self.window.draws)
        widget.paint()
        self.assertEqual(len(self.window.draws), count)
        widget.show(True)
        widget.paint()
        self.assertEqual(self.window.draws[count][-1], "     /  /      :  :   ")
        for edit in fields:
            edit.destroy = Mock()
        widget.destroy()
        widget.destroy()
        for edit in fields:
            edit.destroy.assert_called_once_with()
        for fail_at in range(7):
            edits = []
            def create(*args, fail_at=fail_at, edits=edits, **kwargs):
                if len(edits) == fail_at:
                    raise RuntimeError("edit")
                edit = Mock()
                edits.append(edit)
                return edit
            with self.subTest(fail_at=fail_at), \
                 patch.object(ckit_widget, "EditWidget", side_effect=create), \
                 patch.object(ckit.TimeWidget, "paint", side_effect=RuntimeError("paint")), \
                 self.assertRaises(RuntimeError):
                ckit.TimeWidget(self.window, 0, 0, timestamp)
            for edit in edits:
                edit.destroy.assert_called_once_with()

    def test_owned_resources_cleanup_continues_after_failure(self):
        for cls, names in ((ckit.ColorWidget, ("frame_plane", "color_plane")),
                           (ckit.TimeWidget, ("year_edit", "month_edit", "day_edit", "hour_edit", "minute_edit", "second_edit"))):
            widget = object.__new__(cls)
            resources = [Mock() for _ in names]
            failures = [RuntimeError(name) for name in names]
            for name, resource, error in zip(names, resources, failures):
                setattr(widget, name, resource)
                resource.destroy.side_effect = error
            with self.assertRaises(RuntimeError) as caught:
                widget.destroy()
            self.assertIs(caught.exception, failures[-1])
            self.assertEqual(len(caught.exception.__notes__), len(names) - 1)
            widget.destroy()
            for resource in resources:
                resource.destroy.assert_called_once_with()


class RgbBoundaryTests(unittest.TestCase):
    def setUp(self):
        ckit.setTheme("black", {})
        self.window = Window()

    def test_color_picker_uses_native_api_and_keeps_cancel_and_error_state(self):
        import clnch_native
        initial, chosen = (17, 23, 31), (80, 90, 100)
        original_table, changed_table = ((0, 0, 0),) * 16, ((1, 2, 3),) * 16
        hwnd = 0x1234567887654321
        for key in (ckit.VK_SPACE, ckit.VK_RETURN):
            for result in (0, 1, RuntimeError("color picker failed")):
                with self.subTest(key=key, result=result):
                    widget = object.__new__(ckit.ColorWidget)
                    widget.window = SimpleNamespace(getHWND=Mock(return_value=hwnd))
                    widget.color = initial
                    widget.paint = Mock()
                    with patch.object(ckit.ColorWidget, "color_table", original_table), \
                         patch.object(clnch_native, "chooseColor",
                                      return_value=(result, chosen, changed_table)) as choose:
                        if isinstance(result, Exception):
                            choose.side_effect = result
                            with self.assertRaises(RuntimeError) as raised:
                                widget.onKeyDown(key, 0)
                            self.assertIs(raised.exception, result)
                            self.assertEqual(widget.color, initial)
                            self.assertEqual(ckit.ColorWidget.color_table, original_table)
                            widget.paint.assert_not_called()
                        else:
                            widget.onKeyDown(key, 0)
                            self.assertEqual(widget.color, chosen if result else initial)
                            self.assertEqual(ckit.ColorWidget.color_table, changed_table)
                            widget.paint.assert_called_once_with()
                        choose.assert_called_once_with(hwnd, initial, original_table)

    def test_blended_colors_keep_lookup_order_failures_and_draw_state(self):
        from ckit import ckit_theme
        edit = ckit.EditWidget(self.window, 0, 0, 20, 1, "input", [1, 3])
        self.addCleanup(edit.destroy)
        foreground, background = (17, 300, 51), (8, 11, 1000)
        for fg, bg in ((foreground, background), (None, background), (foreground, None), (None, None)):
            for operation in (ckit.getHintColor, edit.paint):
                with self.subTest(fg=fg, bg=bg, operation=operation):
                    seen = []
                    def color(name, section="COLOR", fg=fg, bg=bg, seen=seen):
                        seen.append(name)
                        return fg if name == "fg" else bg
                    self.window.draws.clear()
                    selection = edit.getSelection()
                    with patch.object(ckit_theme, "getColor", side_effect=color):
                        if fg is None or bg is None:
                            with self.assertRaisesRegex(TypeError, "^'NoneType' object is not iterable$"):
                                operation()
                            self.assertEqual(seen, ["fg", "bg"])
                            self.assertEqual(self.window.draws, [])
                        elif operation == ckit.getHintColor:
                            self.assertEqual(operation(), (14, 227, 288))
                            self.assertEqual(seen, ["fg", "bg"])
                        else:
                            operation()
                            self.assertEqual(seen, ["fg", "bg", "fg", "bg", "select_fg", "select_bg"])
                            self.assertTrue(self.window.draws)
                    self.assertEqual(edit.getText(), "input")
                    self.assertEqual(edit.getSelection(), selection)

    def test_color_sample_bytes_and_failure_resource_order(self):
        from ckit import ckit_theme, ckit_widget
        for background in ((0, 0, 0), (255, 128, 1), None):
            with self.subTest(background=background):
                widget = object.__new__(ckit.ColorWidget)
                ckit.Widget.__init__(widget, self.window, 1, 2, 20, 1)
                widget.color_plane_size = (8, 8)
                widget.frame_plane, widget.color_plane = Mock(), Mock()
                widget.color, widget.message = (17, 23, 31), "sample"
                self.window.draws.clear()
                images = Mock(return_value=object())
                def color(name, section="COLOR", background=background):
                    return background if name == "bg" else (1, 2, 3)
                with patch.object(ckit_theme, "getColor", side_effect=color), \
                     patch.object(ckit_widget.ckitcore, "Image", SimpleNamespace(fromBytes=images)):
                    if background is None:
                        with self.assertRaisesRegex(TypeError, "^'NoneType' object is not subscriptable$"):
                            widget.paint()
                        images.assert_not_called()
                        widget.frame_plane.setImage.assert_not_called()
                        widget.color_plane.setPosition.assert_not_called()
                        self.assertFalse(self.window.draws)
                    else:
                        widget.paint()
                        self.assertEqual([call.args for call in images.call_args_list],
                                         [((1, 1), bytes([value ^ 255 for value in background] + [255])),
                                          ((1, 1), bytes([17, 23, 31, 255]))])
                        self.assertEqual(self.window.draws[-1][-1], "sample")
                    widget.frame_plane.setPosition.assert_called_once_with((26, 46))

    def test_candidate_frame_colors_and_failure_before_native_initialization(self):
        from ckit import ckit_textwidget, ckit_textwindow, ckit_theme, ckit_widget
        for cls in (ckit_widget.CandidateWindow, ckit_textwidget.CandidateWindow):
            for background, foreground, expected in (
                    ((1, 2, 3), (254, 127, 0), (127, 64, 1)),
                    ((256, 1, 0), (0, 0, 0), (128, 0, 0)),
                    (None, (1, 2, 3), None), ((1, 2, 3), None, None), (None, None, None)):
                with self.subTest(widget=cls.__module__, background=background, foreground=foreground):
                    colors = {"bg": background, "fg": foreground}
                    seen = []
                    def color(name, section="COLOR", colors=colors, seen=seen):
                        seen.append(name)
                        return colors.get(name, (1, 2, 3))
                    with patch.object(ckit_theme, "getColor", side_effect=color), \
                         patch.object(ckit_textwindow.TextWindow, "__init__", return_value=None) as initialize, \
                         patch.object(cls, "setItems") as set_items:
                        if background is None or foreground is None:
                            with self.assertRaisesRegex(TypeError, "^'NoneType' object is not subscriptable$"):
                                cls(1, 2, 10, 1, 80, 16, self.window)
                            self.assertEqual(seen, ["bg", "fg"])
                            initialize.assert_not_called()
                            set_items.assert_not_called()
                        else:
                            cls(1, 2, 10, 1, 80, 16, self.window)
                            self.assertEqual(initialize.call_args.kwargs["frame_color"], expected)
                            self.assertEqual(seen, ["bg", "fg", "bg", "caret0", "caret1"])
                            set_items.assert_called_once_with(1, 2, 2, [], 0)

    def test_text_colors_preserve_absence_and_partial_first_update(self):
        from ckit import ckit_theme
        subprocess.run(
            [sys.executable, "-B", "-c",
             (f"import sys; sys.path[:0] = {sys.path!r}; import native_test_support; import ckit; "
              "assert not any(name.startswith('color_') for name in vars(ckit.TextWidget))")],
            cwd=ROOT, check=True, capture_output=True,
        )
        self.assertFalse(hasattr(ckit, "ClassVar"))
        self.assertFalse(hasattr(ckit, "_ClassVar"))
        cls = ckit.TextWidget
        saved = {name: value for name, value in vars(cls).items() if name.startswith("color_")}
        for name in saved:
            delattr(cls, name)
        try:
            with self.assertRaises(AttributeError) as raised:
                _ = cls.color_fg
            self.assertEqual(raised.exception.name, "color_fg")
            self.assertIs(raised.exception.obj, cls)
            failure = LookupError("bar color unavailable")
            foreground = (300, 6, 9)
            def color(name, section="COLOR"):
                if name == "bar_fg":
                    raise failure
                return foreground if name == "fg" else None
            with patch.object(ckit_theme, "getColor", side_effect=color), \
                 self.assertRaises(LookupError) as raised:
                cls.updateColor()
            self.assertIs(raised.exception, failure)
            self.assertIs(cls.color_fg, foreground)
            self.assertIsNone(cls.color_select_bg)
            self.assertFalse(hasattr(cls, "color_bar_fg"))
            self.assertFalse(hasattr(cls, "color_select_bg_inactive"))
        finally:
            for name in list(vars(cls)):
                if name.startswith("color_"):
                    delattr(cls, name)
            for name, value in saved.items():
                setattr(cls, name, value)

    def test_text_selection_gray_and_failure_keep_assigned_color_state(self):
        from ckit import ckit_theme
        for selected in ((9, 12, 15), None):
            with self.subTest(selected=selected):
                seen = []
                def color(name, section="COLOR", selected=selected, seen=seen):
                    seen.append((name, section))
                    return selected if name == "select_bg" else (3, 6, 9)
                marker = (91, 92, 93)
                with patch.object(ckit_theme, "getColor", side_effect=color), \
                     patch.object(ckit.TextWidget, "color_select_bg", None, create=True), \
                     patch.object(ckit.TextWidget, "color_select_bg_inactive", marker, create=True):
                    if selected is None:
                        with self.assertRaisesRegex(TypeError, "^'NoneType' object is not subscriptable$"):
                            ckit.TextWidget.updateColor()
                        self.assertIs(vars(ckit.TextWidget)["color_select_bg_inactive"], marker)
                    else:
                        ckit.TextWidget.updateColor()
                        self.assertEqual(vars(ckit.TextWidget)["color_select_bg_inactive"], (12, 12, 12))
                    self.assertIs(vars(ckit.TextWidget)["color_select_bg"], selected)
                    self.assertEqual(vars(ckit.TextWidget)["color_syntax_error"], (3, 6, 9))
                    self.assertEqual(seen[-1], ("error", "SYNTAX_COLOR"))


if __name__ == "__main__":
    unittest.main()
