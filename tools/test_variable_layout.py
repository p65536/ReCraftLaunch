"""Hidden native layout checks; activation/IME enable replaced, IME rectangles measured."""
import ctypes
import json
import runpy
import sys
import tempfile
import unittest
from contextlib import ExitStack, nullcontext
from ctypes import wintypes
from pathlib import Path
from types import MethodType, SimpleNamespace
from unittest.mock import patch

from native_test_support import RUN_DIR

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "clnch"), str(RUN_DIR / "lib")]
sys._clnch_app_dir = str(ROOT)
import clnch_text

import ckit
from ckit import ckit_misc

clnch_text.initialize()
ckit.setDataPath(str(ROOT / "samples"))
import clnch_cmdeditor
import clnch_cmdlist
import clnch_configmenu
import clnch_consolewindow
import clnch_inputconfig
import clnch_listwindow
import clnch_mainwindow
import clnch_misc
import clnch_msgbox
import clnch_statusbar
import clnch_strings as strings
from clnch_consolewindow import ConsoleWindow


class VariableLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ckit.registerWindowClass("ReClnchVariableLayoutTest")
        ckit.Keymap.init()

    def setUp(self):
        ckit.setTheme("black", {})
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.work_area = (0, 0, 1024, 768)
        self.stack.enter_context(patch.object(ckit_misc.pyauto, "Window", SimpleNamespace(
            getMonitorInfo=lambda: [((0, 0, 1024, 768), self.work_area, True)])))
        for method in ("show", "activate", "foreground", "enableIme"):
            self.stack.enter_context(patch.object(ckit.TextWindow, method))
        self.temp = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.stack.enter_context(patch.object(clnch_cmdeditor, "JSON_PATH", str(Path(self.temp) / "commands.json")))
        self.stack.enter_context(patch.object(ckit, "callConfigFunc"))

    def parent(self, scale):
        parent = ckit.TextWindow(x=100, y=100, width=20, height=1, show=False,
            font=ckit.getStockedFont("MS Gothic", round(12 * scale), round(2 * scale)))
        parent.modifier_settings = clnch_configmenu.clnch_modifierconfig.DEFAULTS.copy()
        parent.centerOfWindowInPixel = lambda: (300, 250)
        return parent

    def assert_inside(self, window):
        ckit.fitWindowToWorkArea(window)
        left, top, right, bottom = window.getWindowRect()
        self.assertTrue(0 <= left < right <= 1024, (left, right))
        self.assertTrue(0 <= top < bottom <= 768, (top, bottom))

    def assert_draws_fit(self, window, calls):
        for call in calls:
            x, _y, width, _height, _attr, value = call.args[:6]
            if value.strip():
                self.assertGreaterEqual(x, 0, value)
                self.assertLessEqual(x + width, window.width(), value)
                self.assertLessEqual(window.getStringWidth(value), width, value)

    def clock_window(self, scale):
        window = None
        window = ckit.TextWindow(x=100, y=100, width=12, height=1, show=False,
            border_size=3, noframe=True, title_bar=False, resizable=False,
            size_handler=lambda width, height: window.paint() if window is not None else None,
            font=ckit.getStockedFont("MS Gothic", round(12 * scale), round(2 * scale)))
        window.initialized = True
        window.active = False
        window.clock_format = "%Y/%m/%d(%a) %H:%M:%S"
        window.status_bar = clnch_statusbar.StatusBar()
        window.custom_status_bar_map = {}
        window.status_bar_paint_hook = None
        window.commandline_edit = None
        for name in ("paint", "registerStatusBar", "_statusbar_Clock", "commandLine"):
            setattr(window, name, MethodType(getattr(clnch_mainwindow.MainWindow, name), window))
        window.registerStatusBar(window._statusbar_Clock)
        return window

    def test_editor_list_position_aligns_right_and_top_with_work_area_clamping(self):
        for scale in (1.0, 1.5, 2.0):
            for work in ((0, 0, 2400, 1600), (-2400, -200, 0, 1400), (0, 0, 1024, 768)):
                for corner in ("left", "right_bottom"):
                    with self.subTest(scale=scale, work=work, corner=corner):
                        self.work_area = work
                        main = self.parent(scale)
                        listing = self.parent(scale)
                        editor = None
                        try:
                            x = work[0] + 20 if corner == "left" else work[2] - 50
                            y = work[1] + 20 if corner == "left" else work[3] - 50
                            listing.setPosSize(x, y, 10, 2, ckit.ORIGIN_X_LEFT | ckit.ORIGIN_Y_TOP)
                            # Match the chosen monitor in the controlled monitor inventory.
                            with patch.object(ckit_misc.pyauto, "Window", SimpleNamespace(
                                    getMonitorInfo=lambda work=work: [(work, work, True)])):
                                editor = clnch_cmdeditor.CommandEditor(main, parent_window=listing)
                                base = listing.getWindowRect()
                                rect = editor.getWindowRect()
                                expected_x = max(work[0], min(base[2], work[2] - (rect[2] - rect[0])))
                                expected_y = max(work[1], min(base[1], work[3] - (rect[3] - rect[1])))
                                self.assertEqual(rect[:2], (expected_x, expected_y))
                                self.assertLessEqual(rect[2], work[2])
                                self.assertLessEqual(rect[3], work[3])
                                if corner == "left" and work[2] - work[0] == 2400:
                                    self.assertEqual(rect[:2], (base[2], base[1]))
                        finally:
                            if editor is not None:
                                editor.destroy()
                            listing.destroy()
                            main.destroy()

    def test_adjust_window_position_selects_monitor_and_preserves_placement(self):
        main = ((0, 0, 1000, 800), (20, 30, 980, 760), True)
        right = ((1200, 0, 2200, 800), (1220, 30, 2180, 760), False)
        left = ((-1200, 0, -200, 800), (-1180, 30, -220, 760), False)
        upper = ((0, -1000, 1000, -200), (20, -970, 980, -240), False)
        monitors = [main, right, left, upper]
        child = self.parent(1.0)
        self.addCleanup(child.destroy)
        child.setPosSize(0, 0, 20, 5, ckit.ORIGIN_X_LEFT | ckit.ORIGIN_Y_TOP)
        rect = child.getWindowRect()
        w, h = rect[2] - rect[0], rect[3] - rect[1]
        cases = [
            # name, base rectangle, prefer up, vertical, horizontal, final pixel position
            ("below", (100, 200, 200, 240), False, True, True, (100, 240)),
            ("above", (100, 200, 200, 240), True, True, True, (100, 200 - h)),
            ("top left wins over center", (950, 200, 1550, 240), False, True, True, (980 - w, 240)),
            ("right monitor", (1300, 200, 1400, 240), False, True, True, (1300, 240)),
            ("left monitor", (-1100, 200, -1000, 240), False, True, True, (-1100, 240)),
            ("upper monitor", (100, -800, 200, -760), False, True, True, (100, -760)),
            ("taskbar is inside monitor", (5, 5, 105, 45), False, True, True, (20, 45)),
            ("center main", (-100, 200, 300, 240), False, True, True, (20, 240)),
            ("center right", (1100, 200, 1500, 240), False, True, True, (1220, 240)),
            ("center left", (-1300, 200, -900, 240), False, True, True, (-1180, 240)),
            ("center upper", (100, -1100, 300, -700), False, True, True, (100, -700)),
            ("outside right", (2400, 200, 2500, 240), False, True, True, (2180 - w, 240)),
            ("outside left", (-1500, 200, -1400, 240), False, True, True, (-1180, 240)),
            ("outside upper", (100, -1400, 200, -1300), False, True, True, (100, -970)),
            ("outside lower", (100, 1000, 200, 1040), False, True, True, (100, 760 - h)),
            ("gap nearest", (1110, 200, 1150, 240), False, True, True, (1220, 240)),
            ("gap equal distance", (1050, 200, 1150, 240), False, True, True, (980 - w, 240)),
            ("overlap with center in gap", (900, -100, 1400, 100), False, True, True, (980 - w, 100)),
            ("center wins over overlap tie", (900, -100, 1700, 100), False, True, True, (1220, 100)),
            ("diagonal nearest", (2300, 900, 2400, 940), False, True, True, (2180 - w, 760 - h)),
            ("fallback flips below", (2400, 20, 2500, 60), True, True, True, (2180 - w, 60)),
            ("exclusive right edge", (1000, 200, 1100, 240), False, True, True, (980 - w, 240)),
            ("flip below", (100, 35, 200, 75), True, True, True, (100, 75)),
            ("flip above and left", (950, 700, 990, 730), False, True, True, (980 - w, 700 - h)),
            ("exact lower edge flips", (100, 720 - h, 200, 760 - h), False, True, True, (100, 720 - 2 * h)),
            ("vertical disabled", (950, 700, 990, 730), False, False, True, (980 - w, 730)),
            ("horizontal disabled", (950, 700, 990, 730), False, True, False, (950, 700 - h)),
            ("both disabled", (950, 700, 990, 730), False, False, False, (950, 730)),
            ("up vertical disabled", (100, 35, 200, 75), True, False, True, (100, 35 - h)),
            ("fallback vertical disabled", (2400, 900, 2500, 940), False, False, True, (2180 - w, 940)),
            ("fallback horizontal disabled", (2400, 900, 2500, 940), False, True, False, (2400, 760 - h)),
            ("fallback both disabled", (2400, 900, 2500, 940), False, False, False, (2400, 940)),
        ]
        for name, base, up, vertical, horizontal, expected in cases:
            inventories = [monitors, monitors[::-1], monitors[1:] + monitors[:1]]
            if name in ("below", "above", "center main", "outside lower"):
                inventories.append([main])
            for inventory in inventories:
                with self.subTest(case=name, monitors=inventory):
                    parent = SimpleNamespace(getWindowRect=lambda base=base: base)
                    with patch.object(ckit_misc.pyauto, "Window", SimpleNamespace(
                            getMonitorInfo=lambda inventory=inventory: inventory)), \
                         patch.object(child, "setPosSize", wraps=child.setPosSize) as position:
                        clnch_misc.adjustWindowPosition(parent, child, up, vertical, horizontal)
                    self.assertEqual(child.getWindowRect(), (*expected, expected[0] + w, expected[1] + h))
                    self.assertEqual(position.call_count, 2)
                    self.assertTrue(all(call.args[2:4] == (20, 5) for call in position.call_args_list))
                    self.assertEqual(position.call_args.args[-1], ckit.ORIGIN_X_LEFT | ckit.ORIGIN_Y_TOP)

    def test_dialog_tab_traverses_fields_skipping_labels_and_hidden_items(self):
        parent = self.parent(1.0)
        dialog = None
        try:
            dialog = ckit.Dialog(parent, "Tab navigation", [
                ckit.Dialog.StaticText(0, "Explanation"),
                ckit.Dialog.Edit("first", 0, 40, "First", "keep first"),
                ckit.Dialog.StaticText(0, "Instructions"),
                ckit.Dialog.Edit("hidden", 0, 40, "Hidden", "hidden", visible=lambda window: False),
                ckit.Dialog.CheckBox("flag", 0, "Flag", False),
                ckit.Dialog.Choice("choice", 0, "Choice", ["A", "B"], 0),
                ckit.Dialog.Edit("second", 0, 40, "Second", "keep second"),
            ])
            first = dialog.items[1].widget
            first.setSelection([2, 5])
            with patch.object(first, "onKeyDown", return_value=True) as child_key, \
                 patch.object(first, "closeList", wraps=first.closeList) as close_candidates:
                dialog.onKeyDown(ckit.VK_TAB, 0)
                self.assertEqual(dialog.items[dialog.focus].id, "flag")
                child_key.assert_not_called()
                close_candidates.assert_called_once()
            for expected in ("choice", "second", "first"):
                dialog.onKeyDown(ckit.VK_TAB, 0)
                self.assertEqual(dialog.items[dialog.focus].id, expected)
            for expected in ("second", "choice", "flag", "first"):
                dialog.onKeyDown(ckit.VK_TAB, ckit.MODKEY_SHIFT)
                self.assertEqual(dialog.items[dialog.focus].id, expected)
            self.assertEqual(first.getSelection(), [2, 5])
            self.assertEqual(dialog.getValueById("first"), "keep first")
            self.assertEqual(dialog.getValueById("second"), "keep second")
            self.assertFalse(dialog.getValueById("flag"))
            self.assertEqual(dialog.getValueById("choice"), 0)
            with patch.object(first, "onKeyDown", return_value=True) as child_key:
                dialog.onKeyDown(ckit.VK_TAB, ckit.MODKEY_CTRL)
                child_key.assert_called_once_with(ckit.VK_TAB, ckit.MODKEY_CTRL)
                self.assertEqual(dialog.items[dialog.focus].id, "first")
        finally:
            if dialog is not None:
                dialog.destroy()
            parent.destroy()

    def test_dialog_checkbox_repositions_after_preceding_height_changes(self):
        parent = self.parent(1.0)
        dialog = None
        visible = [True]
        try:
            heading = ckit.Dialog.StaticText(0, "First\nSecond\nThird",
                visible=lambda window: visible[0])
            check = ckit.Dialog.CheckBox("check", 2, "Check", False)
            dialog = ckit.Dialog(parent, "Rebuild", [heading, check])
            dialog.onKeyDown(ckit.VK_SPACE, 0)
            widget = check.widget
            for shown in (False, True, True, False, True):
                visible[0] = shown
                dialog.rebuildItems()
                self.assertIs(check.widget, widget)
                self.assertEqual((widget.x, widget.y, widget.width, widget.height),
                    (4, 4 if shown else 1, dialog.getStringWidth("Check") + 3, 1))
                self.assertEqual(dialog.content_height, widget.y + 2)
                self.assertTrue(check.getValue())
                self.assertEqual(dialog.focus, 1)
        finally:
            if dialog is not None:
                dialog.destroy()
            parent.destroy()

    def test_dialog_choice_reflows_reused_widgets_and_scroll_range(self):
        parent = self.parent(1.0)
        dialog = None
        limits = [80, 6]
        try:
            with patch.object(ckit_misc, "getWindowSizeLimits", side_effect=lambda window: tuple(limits)):
                choice = ckit.Dialog.Choice("choice", 2, "Choice", ["Alpha", "BBBBBBBBBBBB", "Omega"], 0)
                check = ckit.Dialog.CheckBox("check", 0, "Check", False)
                dialog = ckit.Dialog(parent, "Reflow", [choice, check])
                dialog.onKeyDown(ckit.VK_RIGHT, 0)
                check.onKeyDown(ckit.VK_SPACE, 0)
                widgets = (choice.widget, check.widget)
                for width, height in ((80, 1), (26, 3), (18, 7), (18, 7), (26, 3), (80, 1)):
                    with self.subTest(width=width):
                        limits[0] = width
                        dialog.rebuildItems()
                        self.assertIs(choice.widget, widgets[0])
                        self.assertIs(check.widget, widgets[1])
                        self.assertEqual(choice.size(), (min(36, width - 6) + 2, height))
                        self.assertEqual(choice.widget.width, min(36, width - 6))
                        self.assertEqual(check.widget.y, 1 + height)
                        self.assertEqual(dialog.content_height, height + 3)
                        self.assertEqual(dialog.window_height, min(6, height + 3))
                        self.assertLessEqual(dialog.scroll_pos, max(0, height - 3))
                        self.assertEqual(dialog.focus, 0)
                        self.assertEqual((choice.getValue(), check.getValue()), (1, True))
                        for x, y, w, h, _parts in choice.widget.itemRects():
                            self.assertLessEqual(x + w, choice.widget.x + choice.widget.width)
                            self.assertLessEqual(y + h, check.widget.y)
                        dialog.onMouseWheel(0, 0, -100, 0)
                        self.assertEqual(dialog.scroll_pos, max(0, height - 3))
            self.work_area = (0, 0, 400, 300)
            dialog.font_handler = lambda scale: ckit.getStockedFont("MS Gothic", round(12 * scale), round(2 * scale))
            for scale, height in ((1.0, 1), (2.0, 3), (1.0, 1)):
                with self.subTest(scale=scale):
                    dialog.onDpi(scale)
                    self.assertIs(choice.widget, widgets[0])
                    self.assertIs(check.widget, widgets[1])
                    self.assertEqual(choice.widget.width, min(36, dialog.max_width - 6))
                    self.assertEqual(choice.widget.height, height)
                    self.assertEqual(check.widget.y, height + 1)
                    self.assertEqual(dialog.content_height, height + 3)
                    self.assertEqual((choice.getValue(), check.getValue()), (1, True))
                    self.assertEqual(dialog.focus, 0)
        finally:
            if dialog is not None:
                dialog.destroy()
            parent.destroy()

    def test_dialog_choice_visibility_preserves_selection(self):
        parent = self.parent(1.0)
        dialog = None
        try:
            choice = ckit.Dialog.Choice("choice", 0, "Choice", ["A", "B", "C"], 1,
                visible=lambda window: window.getValueById("show_choice"))
            dialog = ckit.Dialog(parent, "Choice visibility", [
                ckit.Dialog.CheckBox("show_choice", 0, "Show choice", False),
                choice,
            ])
            self.assertIsNone(choice.widget)
            self.assertEqual(choice.size(), (0, 0))
            self.assertEqual(dialog.getValueById("choice"), 1)
            hidden_height = dialog.content_height
            dialog.onKeyDown(ckit.VK_SPACE, 0)
            for key, expected in ((ckit.VK_RIGHT, 2), (ckit.VK_LEFT, 1)):
                dialog.onKeyDown(ckit.VK_TAB, 0)
                self.assertEqual(dialog.items[dialog.focus].id, "choice")
                dialog.onKeyDown(key, 0)
                self.assertEqual(dialog.getValueById("choice"), expected)
                widget = choice.widget
                dialog.onKeyDown(ckit.VK_TAB, ckit.MODKEY_SHIFT)
                dialog.onKeyDown(ckit.VK_SPACE, 0)
                self.assertIsNone(choice.widget)
                self.assertEqual(choice.size(), (0, 0))
                self.assertEqual(dialog.content_height, hidden_height)
                self.assertEqual(dialog.getValueById("choice"), expected)
                dialog.rebuildItems()
                dialog.onKeyDown(ckit.VK_TAB, 0)
                self.assertEqual(dialog.items[dialog.focus].id, "show_choice")
                dialog.onKeyDown(ckit.VK_SPACE, 0)
                self.assertIsNot(choice.widget, widget)
                self.assertEqual(choice.widget.getValue(), expected)
                self.assertGreater(dialog.content_height, hidden_height)
                self.assertEqual(dialog.getResult()[1]["choice"], expected)
        finally:
            if dialog is not None:
                dialog.destroy()
            parent.destroy()

    def test_dialog_unbuilt_and_hidden_controls_ignore_input_and_keep_values(self):
        items = [ckit.Dialog.Edit("edit", 0, 30, "Edit", "keep", visible=lambda dialog: False),
                 ckit.Dialog.CheckBox("check", 0, "Check", True, visible=lambda dialog: False),
                 ckit.Dialog.Choice("choice", 0, "Choice", ["A", "B"], 1,
                                    visible=lambda dialog: False)]
        for item, expected in zip(items, ("keep", True, 1)):
            with self.subTest(stage="unbuilt", item=item.id):
                self.assertIsNone(item.widget)
                self.assertFalse(item.onKeyDown(ckit.VK_RIGHT, 0))
                item.onChar(ord("日"), 0)
                self.assertEqual(item.getValue(), expected)
        parent = self.parent(1.0)
        dialog = None
        try:
            dialog = ckit.Dialog(parent, "Hidden controls", items)
            self.assertIsNone(dialog.focus)
            for item, expected in zip(items, ("keep", True, 1)):
                with self.subTest(stage="hidden", item=item.id):
                    self.assertIsNone(item.widget)
                    self.assertFalse(item.onKeyDown(ckit.VK_RIGHT, 0))
                    item.onChar(ord("日"), 0)
                    self.assertEqual(item.getValue(), expected)
        finally:
            if dialog is not None:
                dialog.destroy()
            parent.destroy()

    def test_dialog_hidden_focused_controls_keep_values_and_allow_tab(self):
        visible = [True]
        items = [ckit.Dialog.Edit("head", 0, 30, "Head", "head"),
                 ckit.Dialog.Edit("edit", 0, 30, "Edit", "keep", visible=lambda dialog: visible[0]),
                 ckit.Dialog.CheckBox("check", 0, "Check", True, visible=lambda dialog: visible[0]),
                 ckit.Dialog.Choice("choice", 0, "Choice", ["A", "B"], 1,
                                    visible=lambda dialog: visible[0]),
                 ckit.Dialog.Edit("tail", 0, 30, "Tail", "tail")]
        parent = self.parent(1.0)
        dialog = None
        try:
            dialog = ckit.Dialog(parent, "Dynamic controls", items)
            for focus in (1, 2, 3):
                with self.subTest(focus=focus):
                    visible[0] = True
                    dialog.rebuildItems()
                    dialog.focus = focus
                    previous = [item.widget for item in items[1:4]]
                    visible[0] = False
                    dialog.rebuildItems()
                    dialog.onChar(ord("日"), 0)
                    dialog.onKeyDown(ckit.VK_SPACE, 0)
                    self.assertEqual([item.getValue() for item in items[1:4]], ["keep", True, 1])
                    self.assertTrue(all(item.widget is None for item in items[1:4]))
                    dialog.onKeyDown(ckit.VK_TAB, 0)
                    self.assertEqual(dialog.focus, 4)
                    dialog.onKeyDown(ckit.VK_TAB, ckit.MODKEY_SHIFT)
                    self.assertEqual(dialog.focus, 0)
                    visible[0] = True
                    dialog.rebuildItems()
                    self.assertEqual([item.getValue() for item in items[1:4]], ["keep", True, 1])
                    self.assertTrue(all(item.widget is not old for item, old in zip(items[1:4], previous)))
        finally:
            if dialog is not None:
                dialog.destroy()
            parent.destroy()

    def test_dialog_arrows_enter_escape_and_completion_keep_existing_behavior(self):
        parent = self.parent(1.0)
        dialog = None
        try:
            dialog = ckit.Dialog(parent, "Dialog controls", [
                ckit.Dialog.Edit("first", 0, 40, "First", "first"),
                ckit.Dialog.StaticText(0, "Guide"),
                ckit.Dialog.Edit("second", 0, 40, "Second", "second"),
            ])
            dialog.onKeyDown(ckit.VK_UP, 0)
            self.assertEqual(dialog.focus, 0)
            dialog.onKeyDown(ckit.VK_DOWN, 0)
            self.assertEqual(dialog.focus, 2)
            dialog.onKeyDown(ckit.VK_DOWN, 0)
            self.assertEqual(dialog.focus, 2)
            dialog.onKeyDown(ckit.VK_UP, 0)
            self.assertEqual(dialog.focus, 0)
            widget = dialog.items[0].widget
            with patch.object(widget, "isListOpened", return_value=True), \
                 patch.object(widget, "closeList") as close_candidates:
                dialog.onKeyDown(ckit.VK_RETURN, 0)
                self.assertEqual(dialog.result, ckit.Dialog.RESULT_CANCEL)
                close_candidates.assert_called_once()
            dialog.onKeyDown(ckit.VK_RETURN, 0)
            self.assertEqual(dialog.getResult(), (ckit.Dialog.RESULT_OK, {"first": "first", "second": "second"}))
            dialog.onKeyDown(ckit.VK_ESCAPE, 0)
            self.assertEqual(dialog.result, ckit.Dialog.RESULT_CANCEL)
        finally:
            if dialog is not None:
                dialog.destroy()
            parent.destroy()

    def test_alt_enter_target_dialogs_keep_fields_and_fit_native_layout(self):
        for scale in (1.0, 1.5, 2.0):
            for mode, fields in (("application", ["executable", "arguments"]), ("web", ["url"])):
                with self.subTest(scale=scale, mode=mode), patch.object(ckit.TextWindow, "getDisplayScaling", return_value=scale):
                    self.work_area = (0, 0, 360, 600)
                    parent = self.parent(scale)
                    parent.altenter_settings = dict(clnch_configmenu.clnch_altenterconfig.DEFAULTS,
                        action=mode, executable="C:/" + "long folder/" * 10 + "EBWin4.exe",
                        arguments="/G=0 /C=1 /M=p /S=%param%", url="https://search.example.org/?q=%param%")
                    try:
                        def inspect(dialog):
                            edits = [item for item in dialog.items if isinstance(item, ckit.Dialog.Edit)]
                            self.assertEqual([item.id for item in edits], fields)  # noqa: B023  # Invoked within this test iteration.
                            controls = strings.CONFIG_EDIT_FIELDS_GUIDE if len(edits) > 1 else strings.CONFIG_EDIT_GUIDE
                            self.assertEqual(dialog.items[-1].text, controls)
                            helper = dialog.items[-1]
                            self.assertEqual(helper.align, ckit.ALIGN_RIGHT)
                            description = dialog.items[-2]
                            if fields == ["url"]:  # noqa: B023  # Invoked within this test iteration.
                                self.assertIn("https://www.google.com/search?q=%param%", description.text)
                                self.assertEqual(len(description.text.splitlines()), 2)
                            self.assertEqual(helper.y, description.y + len(description.lines))
                            self.assertLessEqual(helper.y + len(helper.lines) - dialog.scroll_pos, dialog.height())
                            initial_focus = dialog.focus
                            dialog.onKeyDown(ckit.VK_TAB, 0)
                            if len(edits) > 1:
                                self.assertNotEqual(dialog.focus, initial_focus)
                            dialog.onKeyDown(ckit.VK_TAB, ckit.MODKEY_SHIFT)
                            self.assertEqual(dialog.focus, initial_focus)
                            dialog.onChar(9, 0)
                            for item in edits:
                                self.assertEqual(item.widget.getText(), parent.altenter_settings[item.id])  # noqa: B023  # Invoked within this test iteration.
                            self.assert_inside(dialog)
                            with patch.object(dialog, "putString", wraps=dialog.putString) as draws:
                                dialog.paint()
                            self.assert_draws_fit(dialog, draws.call_args_list)
                            for row, line in enumerate(helper.lines):
                                draw = next(call.args for call in draws.call_args_list
                                    if call.args[1] == helper.y + row - dialog.scroll_pos and call.args[-1] == line)
                                self.assertEqual(draw[0] + dialog.getStringWidth(line), dialog.width() - 2)
                            dialog.onClose()
                        with patch.object(ckit.TextWindow, "messageLoop", inspect):
                            clnch_configmenu._configAltEnterTarget(parent)
                    finally:
                        parent.destroy()

    def test_clock_expands_and_input_returns_to_its_own_width(self):
        with patch.object(clnch_mainwindow.clnch_ini, "getint", side_effect=lambda section, key, default: {
                "min_width": 12, "max_width": 80}.get(key, default)):
            for scale in (1.0, 1.5, 2.0):
                with self.subTest(scale=scale):
                    window = self.clock_window(scale)
                    try:
                        expected = window.getStringWidth(window._statusbar_Clock(12)) + 2
                        with patch.object(window, "putString", wraps=window.putString) as draws:
                            window.paint()
                        self.assertEqual(window.width(), expected)
                        self.assertIn(":", draws.call_args.args[-1])
                        self.assert_draws_fit(window, draws.call_args_list)
                        with patch.object(window, "setPosSize", wraps=window.setPosSize) as resize:
                            window.paint()
                        resize.assert_not_called()
                        window.keydown_hook = window.char_hook = None
                        window.mouse_event_mask = False
                        window.input_settings = clnch_inputconfig.DEFAULTS.copy()
                        window.removeKeyMessage = lambda: None
                        input_widths = []
                        window.messageLoop = lambda check, target=window, widths=input_widths: widths.append(target.width())
                        window.commandLine("")
                        self.assertEqual(input_widths, [12])
                        self.assertEqual(window.width(), expected)
                        self.assertIsNone(window.commandline_edit)
                    finally:
                        window.destroy()

    def test_clock_respects_maximum_and_work_area_and_other_status_layers(self):
        window = self.clock_window(1.0)
        try:
            with patch.object(clnch_mainwindow.clnch_ini, "getint", return_value=16):
                window.paint()
            self.assertEqual(window.width(), 16)
            self.work_area = (0, 0, 180, 100)
            window.setPosSize(150, 70, 12, 1, 0)
            with patch.object(clnch_mainwindow.clnch_ini, "getint", return_value=80):
                window.paint()
            self.assertLessEqual(window.width(), ckit.getWindowSizeLimits(window, border_size=3)[0])
            left, top, right, bottom = window.getWindowRect()
            self.assertTrue(0 <= left < right <= 180)
            self.assertTrue(0 <= top < bottom <= 100)
            self.work_area = (0, 0, 1024, 768)
            window.status_bar_paint_hook = lambda *args: None
            window.setPosSize(100, 100, 12, 1, 0)
            window.paint()
            self.assertEqual(window.width(), 12)
            window.status_bar_paint_hook = None
            layer = clnch_statusbar.SimpleStatusBarLayer(priority=-2, message="status")
            window.status_bar.registerLayer(layer)
            window.paint()
            self.assertEqual(window.width(), 12)
            window.status_bar.unregisterLayer(layer)
            window.custom_status_bar_map.clear()
            window.paint()
            self.assertEqual(window.width(), 12)
        finally:
            window.destroy()

    def test_editor_long_translation_wraps_and_uses_same_input_and_choice_coordinates(self):
        variants = ({}, {
            "FIELD_VIEW_MODE": "Window display mode 全角",
            "FIELD_MODIFIER": "Modifier operation 全角",
            "VIEW_NORMAL": "Normal window display 全角 display",
            "VIEW_MINIMIZED": "Minimized window display 全角 display",
            "VIEW_MAXIMIZED": "Maximized window display 全角 display",
            "MODIFIER_NONE": "Without modifier 全角 Enter",
            "MODIFIER_CTRL": "Control modifier 全角 Enter",
            "MODIFIER_SHIFT": "Shift modifier 全角 Enter",
            "MODIFIER_CTRL_SHIFT": "Control and Shift modifiers 全角 Enter",
            "MODIFIER_NONE_HINT": "Action when pressing Enter without a modifier 全角\nAdditional explanation",
            "MODIFIER_DEFAULT_HINT": "Default action when no operation is registered: {description} 全角",
            "MAPPING_MISSING_BOTH": "Mapped folder: source and destination folders have not been set 全角",
            "EDITOR_GUIDE": "Enter: Save command   Esc: Cancel editing   Alt+key: Select or focus 全角\n" + "LongWord" * 14},
            {"FIELD_VIEW_MODE": "Window display properties 全角 " * 4})
        for scale in (1.0, 1.5, 2.0):
            for values in variants:
                with self.subTest(scale=scale, translated=bool(values)), (patch.multiple(strings, **values) if values else nullcontext()), \
                     patch.object(ckit.TextWindow, "getDisplayScaling", return_value=scale):
                    fields = [(key, label + (" field 全角" if values else ""), access)
                              for key, label, access in clnch_cmdeditor.FIELD_DEFS]
                    choices = [("view_mode", strings.FIELD_VIEW_MODE, "v"), ("modifier", strings.FIELD_MODIFIER, "m")]
                    modifiers = (strings.MODIFIER_NONE, strings.MODIFIER_CTRL, strings.MODIFIER_SHIFT, strings.MODIFIER_CTRL_SHIFT)
                    with patch.multiple(clnch_cmdeditor, FIELD_DEFS=fields, CHOICE_FIELD_DEFS=choices, MODIFIER_LABELS=modifiers):
                        parent = self.parent(scale)
                        editor = None
                        try:
                            editor = clnch_cmdeditor.CommandEditor(parent)
                            self.assert_inside(editor)
                            self.assertGreaterEqual(editor.edits[0].width, 20)
                            with patch.object(editor, "putString", wraps=editor.putString) as draws:
                                editor.paint()
                            self.assert_draws_fit(editor, draws.call_args_list)
                            for index, edit in enumerate(editor.edits):
                                editor.focus_index = index
                                editor._update_focus()
                                x, y = editor.charToClient(edit.x, edit.y)
                                self.assertGreaterEqual(y, 1)
                                editor._on_left_button_down(x, y, 0)
                                self.assertEqual(editor.focus_index, index)
                                editor._on_drop_files(x, y, ["D:/sample.exe"])
                                self.assertEqual(edit.getText(), "D:/sample.exe")
                                editor.active = True
                                with patch.object(editor, "setImeRect", wraps=editor.setImeRect) as ime:
                                    editor._update_focus()
                                self.assertEqual(ime.call_args.args[0], (*editor.charToClient(edit.x, edit.y),
                                    *editor.charToClient(edit.x + edit.width, edit.y + 1)))
                                plane = editor._row_planes[edit.y]
                                self.assertEqual(plane.charToClient(edit.x, 0), editor.charToClient(edit.x, edit.y))
                                self.assertEqual(plane.charToScreen(edit.x, 0), editor.charToScreen(edit.x, edit.y))
                            for control in (editor.view_choice, editor.modifier_choice):
                                for selected, (x, y, width, height, parts) in enumerate(control.itemRects()):
                                    self.assertTrue(all(editor.getStringWidth(line) <= width for line in parts))
                                    editor._scroll(editor._row_y(y) - editor._scroll_y)
                                    px, py = editor.charToClient(x, y)
                                    editor._on_left_button_down(px, py, 0)
                                    self.assertEqual(control.getValue(), selected)
                            before = (editor._content_height, editor._hint_row, editor._guide_row)
                            for key in (69, 67, 83, 88):
                                editor._on_keydown(key, ckit.MODKEY_ALT)
                                self.assertEqual(before, (editor._content_height, editor._hint_row, editor._guide_row))
                            editor._on_keydown(ckit.VK_END, 0)
                            editor._on_keydown(ckit.VK_NEXT, 0)
                            self.assertLessEqual(editor._scroll_y, editor._content_height - editor._viewport_height)
                            editor._on_dpi(scale)
                            self.assert_inside(editor)
                        finally:
                            if editor:
                                for edit in editor.edits:
                                    edit.destroy()
                                editor.destroy()
                            parent.destroy()

    def test_updated_config_wording_fits_in_both_languages(self):
        for language in ("ja", "en"):
            wording = runpy.run_path(str(ROOT / f"clnch/clnch_strings_{language}.py"))
            labels = [wording[name] for name in
                      ("CONFIG_INACTIVE", "DATA_USER_FOLDER", "ACTION_NONE", "ACTION_EXECUTE")]
            title = wording["INPUT_HISTORY"]
            labels += [wording[name] + wording["HISTORY_RESET_NOTICE"]
                       for name in ("INPUT_HISTORY_OFF", "INPUT_HISTORY_SESSION")]
            for scale in (1.0, 1.5, 2.0):
                with self.subTest(language=language, scale=scale), \
                     patch.object(ckit.TextWindow, "getDisplayScaling", return_value=scale):
                    parent = self.parent(scale)
                    box = None
                    try:
                        for work in ((0, 0, 1024, 768), (0, 0, 360, 600)):
                            self.work_area = work
                            def inspect(window, title=title, labels=labels):
                                self.assertEqual(window.title, title)
                                self.assertEqual(["".join(parts) for parts in window.item_lines], labels)
                                rect = window.getWindowRect()
                                self.assertLessEqual(rect[2] - rect[0], self.work_area[2])
                                self.assertLessEqual(rect[3] - rect[1], self.work_area[3])
                                with patch.object(window, "putString", wraps=window.putString) as draws:
                                    window.paint()
                                self.assert_draws_fit(window, draws.call_args_list)
                                window.cancel()
                            with patch.object(ckit.TextWindow, "messageLoop", inspect):
                                clnch_listwindow.popMenu(parent, title=title, items=labels)
                            box = clnch_msgbox.MessageBox(180, 250, parent, False, 0,
                                wording["CONFIG_DATA"], wording["DATA_RESTART"])
                            self.assertEqual("".join(box.message_lines), wording["DATA_RESTART"])
                            with patch.object(box, "putString", wraps=box.putString) as draws:
                                box.paint()
                            self.assert_draws_fit(box, draws.call_args_list)
                            box.destroy()
                            box = None
                    finally:
                        if box:
                            box.destroy()
                        parent.destroy()

    def test_command_apply_failure_message_fits_in_both_languages(self):
        english = runpy.run_path(str(ROOT / "clnch/clnch_strings_en.py"))
        for template in (strings.COMMAND_APPLY_ERROR, english["COMMAND_APPLY_ERROR"]):
            for scale in (1.0, 1.5, 2.0):
                with self.subTest(template=template, scale=scale):
                    parent = self.parent(scale)
                    message = template.format(error="日本語 path / long error " * 30)
                    box = None
                    try:
                        box = clnch_msgbox.MessageBox(300, 250, parent, False, 0, strings.ERROR_TITLE, message)
                        self.assert_inside(box)
                        self.assertEqual("".join(box.message_lines), message.replace("\n", ""))
                        box._scroll(10000)
                        self.assertEqual(box.scroll_pos + box.visible_rows, len(box.message_lines))
                        with patch.object(box, "putString", wraps=box.putString) as draws:
                            box.paint()
                        self.assert_draws_fit(box, draws.call_args_list)
                    finally:
                        if box:
                            box.destroy()
                        parent.destroy()

    def test_message_buttons_determine_width_and_wrap_vertically_with_matching_hits(self):
        for scale in (1.0, 1.5, 2.0):
            with self.subTest(scale=scale), patch.multiple(strings,
                BUTTON_YES="Affirmative answer 全角 " * 4, BUTTON_NO="Negative answer 全角 " * 4,
                MESSAGE_SCROLL="More text {first}-{last}/{total}; use arrow keys, PageUp or PageDown 全角"):
                parent = self.parent(scale)
                box = clnch_msgbox.MessageBox(300, 250, parent, False, 1, "Title", "Short")
                try:
                    self.assert_inside(box)
                    self.assertGreater(box.button_rows[box.BUTTON_NO], box.button_rows[box.BUTTON_YES])
                    with patch.object(box, "putString", wraps=box.putString) as draws:
                        box.paint()
                    self.assert_draws_fit(box, draws.call_args_list)
                    for button, label, column, width in box.buttons:
                        for offset in range(len(box.button_lines[button])):
                            x, y = box.charToClient(column + 1, box.button_rows[button] + offset)
                            self.assertEqual(box._button_at(x, y), button)
                        box.onLeftButtonDown(x, y, 0)
                        box.onLeftButtonUp(x, y, 0)
                        self.assertEqual(box.getResult(), 2 if button == box.BUTTON_YES else 3)
                    box.message = "\n".join("LongWord" * 16 for _ in range(50))
                    box._layout(300, 250)
                    box._scroll(10000)
                    self.assertEqual(box.scroll_pos + box.visible_rows, len(box.message_lines))
                    self.assert_inside(box)
                    with patch.object(box, "putString", wraps=box.putString) as draws:
                        box.paint()
                    self.assert_draws_fit(box, draws.call_args_list)
                    self.assertTrue(all(0 <= call.args[1] < box.height() for call in draws.call_args_list))
                    box.onDpi(scale)
                finally:
                    box.destroy()
                    parent.destroy()

    def test_config_menus_and_command_list_use_content_width_instead_of_maximum(self):
        for scale in (1.0, 1.5, 2.0):
            with self.subTest(scale=scale), patch.object(ckit.TextWindow, "getDisplayScaling", return_value=scale):
                parent = self.parent(scale)
                parent.input_settings = clnch_inputconfig.DEFAULTS.copy()
                def check(expected):
                    def cancel(window):
                        self.assertEqual(window.width(), expected, window.title)
                        padding = round(4 * scale)  # noqa: B023  # Used within this test iteration.
                        self.assertEqual(window.charToClient(0, 0), (1 + padding, 1))
                        self.assertEqual(window.getClientSize()[0], expected * window.getCharSize()[0] + 2 + padding * 2)
                        self.assert_inside(window)
                        window.cancel()
                    return cancel
                try:
                    for open_menu, expected in ((clnch_configmenu.doConfigMenu, 37),
                            (clnch_configmenu._configAppearance, 40),
                            (clnch_configmenu._configInput, 38),
                            (clnch_configmenu._configModifiers, 36),
                            (clnch_configmenu._configHotKey, 26)):
                        with patch.object(clnch_configmenu, "_dataPathValue", return_value=strings.DATA_APP_FOLDER), \
                             patch.object(ckit.TextWindow, "messageLoop", check(expected)):
                            open_menu(parent)
                    Path(self.temp, "commands.json").write_text(json.dumps({"": {}, "memo": {}, "notepad": {}}), encoding="utf-8")
                    with patch.object(ckit, "dataPath", return_value=self.temp), \
                         patch.object(ckit.TextWindow, "messageLoop", check(14)):
                        clnch_cmdlist.open_list(parent)
                finally:
                    parent.destroy()

    def test_command_list_uses_configured_width_when_reopened_and_wraps_only_at_limits(self):
        name = "long_command_name_" * 3
        Path(self.temp, "commands.json").write_text(json.dumps({name: {}}), encoding="utf-8")
        for scale in (1.0, 1.5, 2.0):
            with self.subTest(scale=scale), patch.object(ckit.TextWindow, "getDisplayScaling", return_value=scale):
                parent = self.parent(scale)
                try:
                    for configured, work_width, wraps in ((80, 1024, False), (32, 1024, True),
                                                           (160, 1024, False), (160, 240, True)):
                        self.work_area = (0, 0, work_width, 768)
                        def inspect(window, configured=configured, wraps=wraps):
                            self.assertEqual(window._size_request[2], configured)
                            self.assert_inside(window)
                            padding = round(4 * window.getDisplayScaling())
                            columns = (padding * 2 + window.getCharSize()[0] - 1) // window.getCharSize()[0]
                            self.assertLessEqual(window.width() + columns, configured)
                            index = next(i for i, item in enumerate(window.items) if item[1] == name)
                            self.assertEqual(len(window.item_lines[index]) > 1, wraps)
                            self.assertEqual("".join(window.item_lines[index]), name)
                            if not wraps:
                                self.assertEqual(window.width(), window.getStringWidth(name))
                                self.assertGreater(window.width(), 20)
                            window.cancel()
                        with self.subTest(configured=configured, work_width=work_width), \
                             patch.object(ckit, "dataPath", return_value=self.temp), \
                             patch.object(clnch_cmdlist.clnch_ini, "getint", return_value=configured), \
                             patch.object(ckit.TextWindow, "messageLoop", inspect):
                            clnch_cmdlist.open_list(parent)
                finally:
                    parent.destroy()

    def test_config_values_use_available_width_and_reflow_on_dpi_and_work_area_changes(self):
        values = {("FONT", "name"): "Cascadia Mono ExtraLight", ("THEME", "name"): "Theme 全角 " * 8,
                  ("GEOMETRY", "topmost"): "2"}
        for scale in (1.0, 1.25, 1.5, 1.75, 2.0):
            with self.subTest(scale=scale), patch.object(ckit.TextWindow, "getDisplayScaling", return_value=scale):
                self.work_area = (0, 0, 1024, 768)
                parent = self.parent(scale)
                try:
                    def check(window, current_scale):
                        labels = [item[0] for item in window.items]
                        content_width = max(map(window.getStringWidth, [window.title, *labels]))
                        char_width = window.getCharSize()[0]
                        padding_columns = (2 * round(4 * current_scale) + char_width - 1) // char_width
                        limit = ckit.getWindowSizeLimits(window)[0] - padding_columns
                        self.assertEqual(window.width(), min(content_width, limit))
                        self.assertEqual(["".join(parts) for parts in window.item_lines], labels)
                        self.assertEqual(window.item_height == 1, content_width <= limit)
                        self.assertTrue(all(window.getStringWidth(line) <= window.width()
                            for parts in window.item_lines for line in parts))
                        self.assert_inside(window)
                        with patch.object(window, "putString", wraps=window.putString) as draws:
                            window.paint()
                        self.assert_draws_fit(window, draws.call_args_list)
                    def inspect(window):
                        check(window, scale)  # noqa: B023  # Used within this test iteration.
                        if window.title == strings.CONFIG_APPEARANCE:
                            self.assertEqual(window.item_lines[5], ["ファイルパス区切り文字: バックスラッシュ"])
                        window.command_CursorLast(None)
                        selected = window.select
                        with patch.object(ckit.TextWindow, "getDisplayScaling", return_value=2.0):
                            window.onDpi(2.0)
                            check(window, 2.0)
                            for work in ((0, 0, 360, 600), (0, 0, 1024, 768)):
                                self.work_area = work
                                window.onMove(0, 0)
                                check(window, 2.0)
                                rect = window.getWindowRect()
                                self.assertLessEqual(rect[2], work[2])
                                self.assertLessEqual(rect[3], work[3])
                                self.assertEqual(window.select, selected)
                        window.cancel()
                    with patch.object(clnch_configmenu.clnch_ini, "get",
                            side_effect=lambda section, name, default=None: values.get((section, name), default)), \
                         patch.object(clnch_configmenu, "_dataPathValue",
                            return_value="アプリフォルダ（次回起動後: AppDataフォルダ）"), \
                         patch.object(ckit.TextWindow, "messageLoop", inspect):
                        clnch_configmenu.doConfigMenu(parent)
                        clnch_configmenu._configAppearance(parent)
                finally:
                    parent.destroy()

    def test_config_submenus_and_source_list_expand_beyond_old_caps(self):
        parent = self.parent(1.0)
        parent.input_settings = clnch_inputconfig.DEFAULTS.copy()
        path = "D:/" + "folder/" * 14
        parent.modifier_settings.update(CTRL_ACTION="mapped_folder", SOURCE_ROOTS=(path,),
                                        CTRL_DESTINATION_ROOT=path)
        title = "Long menu title " * 6
        seen = []
        def inspect(window):
            if window.title == strings.MODIFIER_DEFAULT_TITLE.format(modifier="Ctrl"):
                preview = window.items[-1]
                self.assertLessEqual(window.getStringWidth(preview.split(": ", 1)[1]), 48)
                self.assertEqual(parent.modifier_settings["CTRL_DESTINATION_ROOT"], path)
            else:
                self.assertGreater(window.width(), 76, window.title)
            self.assertEqual(window.item_height, 1)
            if window.title == strings.SOURCE_LIST_TITLE:
                with patch.object(window, "putString", wraps=window.putString) as draws:
                    window.paint()
                self.assertEqual(window.status_bar_layer.align, ckit.ALIGN_RIGHT)
                self.assertEqual(len(draws.call_args_list[-1].args[-1]) - len(draws.call_args_list[-1].args[-1].rstrip()), 2)
                window.command_IncrementalSearch(None)
                self.assertEqual(window.status_bar_layer.align, ckit.ALIGN_LEFT)
            self.assert_inside(window)
            seen.append(window.title)
            window.cancel()
        try:
            with patch.object(ckit.TextWindow, "getDisplayScaling", return_value=1.0), \
                 patch.multiple(strings, CONFIG_INPUT=title, CONFIG_HOTKEY_OPTIONS=title,
                     CONFIG_DATA=title, CONFIG_FONT_SIZE=title), \
                 patch.object(clnch_configmenu.clnch_execonfig, "read", return_value=False), \
                 patch.object(ckit.TextWindow, "messageLoop", inspect):
                clnch_configmenu._configInput(parent)
                clnch_configmenu._configHotKey(parent)
                clnch_configmenu._configDataPath(parent)
                clnch_configmenu._configFontSize(parent)
                clnch_configmenu._configModifierSources(parent)
                clnch_configmenu._configModifier(parent, "CTRL", "Ctrl")
            self.assertEqual(len(seen), 6)
        finally:
            parent.destroy()

    def test_editor_key_guide_is_right_aligned_with_measured_width(self):
        parent = self.parent(1.0)
        try:
            for guide in (strings.EDITOR_GUIDE, "Enter: 保存 全角   Esc: Cancel " * 8):
                with patch.object(strings, "EDITOR_GUIDE", guide):
                    editor = clnch_cmdeditor.CommandEditor(parent)
                try:
                    with patch.object(editor, "putString", wraps=editor.putString) as draws:
                        editor.paint()
                    for i, line in enumerate(editor._guide_lines):
                        call = next(call for call in draws.call_args_list
                                    if call.args[1] == editor._guide_row + i * clnch_cmdeditor.ROW_STEP
                                    and call.args[5] == line)
                        x, _y, width = call.args[:3]
                        self.assertEqual(x + width, editor.width() - 2)
                        self.assertEqual(width, editor.getStringWidth(line))
                finally:
                    for edit in editor.edits:
                        edit.destroy()
                    editor.destroy()
        finally:
            parent.destroy()

    def test_console_keeps_default_or_saved_cells_and_caps_outer_frame_to_work_area(self):
        for scale in (1.0, 1.5, 2.0):
            for saved in ({}, {"width": 70, "height": 20}, {"x": 4000, "y": -4000, "width": 1000, "height": 1000}):
                with self.subTest(scale=scale, saved=saved):
                    self.work_area = (0, 0, 1920, 1080)
                    parent = self.parent(scale)
                    with patch.object(clnch_consolewindow.clnch_ini, "getint",
                                      side_effect=lambda section, key, default: saved.get(key, default)):  # noqa: B023  # Used within this test iteration.
                        console = ConsoleWindow(parent)
                    try:
                        if not saved or saved.get("width") == 70:
                            self.assertEqual((console.width(), console.height()),
                                             (saved.get("width", 80), saved.get("height", 32)))
                        for new_scale in (scale, 2.0, 1.0):
                            console._onDpi(new_scale)
                            rect = console.getWindowRect()
                            self.assertTrue(0 <= rect[0] < rect[2] <= 1920, rect)
                            self.assertTrue(0 <= rect[1] < rect[3] <= 1080, rect)
                        self.work_area = (0, 0, 800, 600)
                        console._onDpi(scale)
                        rect = console.getWindowRect()
                        self.assertTrue(0 <= rect[0] < rect[2] <= 800, rect)
                        self.assertTrue(0 <= rect[1] < rect[3] <= 600, rect)
                        self.assertEqual((console.window_normal_width, console.window_normal_height),
                                         (console.width(), console.height()))
                        before = (console.width(), console.height())
                        console._fitToWorkArea()
                        self.assertEqual((console.width(), console.height()), before)
                        self.work_area = (0, 0, 640, 480)
                        console._onMove(0, 0)
                        rect = console.getWindowRect()
                        self.assertTrue(0 <= rect[0] < rect[2] <= 640, rect)
                        self.assertTrue(0 <= rect[1] < rect[3] <= 480, rect)
                        self.work_area = (0, 0, 500, 400)
                        send = ctypes.WinDLL("user32").SendMessageW
                        send.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
                        send.restype = wintypes.LPARAM
                        send(console.getHWND(), 0x001A, 0x002F, 0)
                        rect = console.getWindowRect()
                        self.assertTrue(0 <= rect[0] < rect[2] <= 500, rect)
                        self.assertTrue(0 <= rect[1] < rect[3] <= 400, rect)
                    finally:
                        console.destroy()
                        parent.destroy()

    def test_console_wrap_uses_native_widths_across_resize_and_dpi(self):
        parent = self.parent(1.0)
        console = ConsoleWindow(parent)
        source = "C:/日本語/with space/" * 10 + "\n" + "ABC\t日本語🙂" * 10 + "\nend"
        try:
            console.clearLog()
            console.log.write(source)
            console.selection = [[0, 3], [1, 5]]
            for scale in (1.0, 1.5, 2.0):
                console._onDpi(scale)
                for width in (12, 32, 80):
                    with self.subTest(scale=scale, width=width):
                        console.setPosSize(0, 0, width, 12, 0)
                        console.paint()
                        rows = console._getRows()
                        for lineno, original in enumerate(source.split("\n")):
                            parts = [original[start:end] for line, start, end in rows if line == lineno]
                            self.assertEqual("".join(parts), original)
                            self.assertTrue(all(console.getStringWidth(ckit.expandTab(console, part)) <= console.width()
                                                for part in parts))
                        with patch.object(ckit, "setClipboardText") as clipboard:
                            console._copySelectedRegion()
                        clipboard.assert_called_once_with(source.split("\n")[0][3:] + "\r\n"
                                                          + source.split("\n")[1][:5])
        finally:
            console.destroy()
            parent.destroy()

    def test_list_wraps_items_and_reserves_status_rows_and_keeps_navigation(self):
        for scale in (1.0, 1.5, 2.0):
            with self.subTest(scale=scale), patch.object(ckit.TextWindow, "getDisplayScaling", return_value=scale):
                parent = self.parent(scale)
                items = ["Setting 全角 " * 12 + str(i) for i in range(12)]
                status = "Insert: add; Enter: edit; Delete: delete; Control+arrows: reorder 全角 " * 2
                window = clnch_listwindow.ListWindow(300, 250, 5, 1, 40, 16, parent, False,
                    strings.CONFIG_TITLE, items, statusbar_handler=lambda width, index: status)  # noqa: B023  # Used within this test iteration.
                try:
                    self.assert_inside(window)
                    char_width = window.getCharSize()[0]
                    self.assertEqual(window.width(), 40 - (2 * round(4 * scale) + char_width - 1) // char_width)
                    self.assertLessEqual(window.getClientSize()[0], 40 * char_width + 2)
                    self.assertEqual(window.item_height, max(map(len, window.item_lines)))
                    self.assertEqual(["".join(parts) for parts in window.item_lines], items)
                    self.assertEqual(window.status_rows, len(ckit.splitLines(window, status, window.width() - 2)))
                    self.assertGreaterEqual(window.itemsHeight(), 1)
                    with patch.object(window, "putString", wraps=window.putString) as draws:
                        window.paint()
                    self.assert_draws_fit(window, draws.call_args_list)
                    window.command_CursorLast(None)
                    self.assertEqual(window.select, len(items) - 1)
                    window.command_CursorFirst(None)
                    self.assertEqual(window.select, 0)
                    window.onDpi(scale)
                    self.assert_inside(window)
                finally:
                    window.destroy()
                    parent.destroy()

    def test_list_pixel_padding_tracks_dpi_with_matching_text_coordinates_and_selection(self):
        parent = self.parent(1.0)
        with patch.object(ckit.TextWindow, "getDisplayScaling", return_value=1.0):
            window = clnch_listwindow.ListWindow(300, 250, 5, 1, 40, 16, parent, False,
                "List", ["Short", "Long item 全角 " * 10], initial_select=1)
        try:
            self.assertEqual(parent.charToClient(0, 0), (1, 1))
            for scale in (1.0, 1.25, 1.5, 1.75, 2.0, 1.0):
                with self.subTest(scale=scale):
                    window.onDpi(scale)
                    padding = round(4 * scale)
                    char_w, char_h = window.getCharSize()
                    self.assertEqual(window.select, 1)
                    self.assertEqual(window.charToClient(0, 0), (padding + 1, 1))
                    self.assertEqual(window.getClientSize(),
                        (window.width() * char_w + padding * 2 + 2, window.height() * char_h + 2))
                    self.assertEqual(window.getNormalSize(), (window.width(), window.height()))
                    self.assertEqual(window.getClientSize()[0] - window.charToClient(window.width(), 0)[0], padding + 1)
                    for row in range(window.height()):
                        x, y = window.charToClient(0, row)
                        self.assertEqual((x, y), (padding + 1, 1 + row * char_h))
                        self.assertEqual(window.charToScreen(0, row), window.clientToScreen(x, y))
                        for column in (0, window.width() - 1):
                            px, py = window.charToClient(column, row)
                            self.assertEqual(((px - x) // char_w, (py - 1) // char_h), (column, row))
                    normal = ckit.Attribute(fg=ckit.getColor("fg"))
                    selected = ckit.Attribute(fg=ckit.getColor("select_fg"), bg=ckit.getColor("select_bg"))
                    window.active = True
                    with patch.object(ckit, "Attribute", side_effect=[normal, selected]), \
                         patch.object(window, "putString", wraps=window.putString) as draws:
                        window.paint()
                    highlights = [call for call in draws.call_args_list if call.args[4] is selected]
                    self.assertEqual(len(highlights), len(window.item_lines[1]))
                    for offset, call in enumerate(highlights):
                        self.assertEqual(call.args[:4], (0, window.item_height + offset, window.width(), 1))
                    self.assert_draws_fit(window, draws.call_args_list)
                    self.assert_inside(window)
        finally:
            window.destroy()
            parent.destroy()

    def test_list_padding_preserves_width_cap_and_reflows_on_work_area_changes(self):
        for scale in (1.0, 1.25, 1.5, 2.0):
            with self.subTest(scale=scale), patch.object(ckit.TextWindow, "getDisplayScaling", return_value=scale):
                parent = self.parent(scale)
                window = clnch_listwindow.ListWindow(300, 250, 5, 1, 76, 16, parent, False,
                    "List", ["WholeWord" * 20, "全角" * 60], initial_select=1)
                try:
                    for work in ((0, 0, 1024, 768), (0, 0, 360, 600), (0, 0, 800, 600)):
                        self.work_area = work
                        window.onMove(0, 0)
                        rect = window.getWindowRect()
                        char_w = window.getCharSize()[0]
                        self.assertLessEqual(window.getClientSize()[0], 76 * char_w + 2)
                        self.assertTrue(work[0] <= rect[0] < rect[2] <= work[2], rect)
                        self.assertEqual(["".join(parts) for parts in window.item_lines], window.items)
                        self.assertTrue(all(window.getStringWidth(line) <= window.width()
                            for parts in window.item_lines for line in parts))
                        self.assertEqual(window.select, 1)
                        self.assertEqual(window.charToClient(0, 0), (round(4 * scale) + 1, 1))
                finally:
                    window.destroy()
                    parent.destroy()

    def test_text_window_padding_keeps_sizing_callbacks_in_cells(self):
        sizes = []
        window = ckit.TextWindow(x=100, y=100, width=10, height=3, show=False,
            size_handler=lambda width, height: sizes.append((width, height)))
        try:
            for padding in (4, 6, 8, 0):
                window.setHorizontalPadding(padding)
                window.setPosSize(100, 100, 20, 4, 0)
                self.assertEqual(sizes[-1], (20, 4))
                self.assertEqual((window.width(), window.height()), (20, 4))
                char_w, char_h = window.getCharSize()
                self.assertEqual(window.getNormalSize(), (20, 4))
                size = [20 * char_w + padding * 2 + 2 + char_w - 1, 4 * char_h + 2 + char_h - 1]
                window._TextWindow__onSizing(size)
                self.assertEqual(size, [20 * char_w + padding * 2 + 2, 4 * char_h + 2])
                self.assertEqual(window.charToClient(0, 0), (padding + 1, 1))
        finally:
            window.destroy()

    def test_folder_dialog_wraps_labels_and_explanation_and_preserves_edit_on_reflow(self):
        for scale in (1.0, 1.5, 2.0):
            with self.subTest(scale=scale):
                parent = self.parent(scale)
                value = "D:/Long folder/" * 30
                with patch.object(ckit.Dialog, "show"):
                    dialog = ckit.Dialog(parent, "Translated folder settings", [
                        ckit.Dialog.StaticText(0, "Explanation 全角\n" + "LongWord" * 40),
                        ckit.Dialog.Edit("path", 0, 72, "Translated folder field 全角 " * 3, value),
                        ckit.Dialog.StaticText(0, "Enter: accept / Escape: cancel 全角 " * 3 + "\nShort", align=ckit.ALIGN_RIGHT)])
                try:
                    self.assert_inside(dialog)
                    edit = dialog.items[1]
                    self.assertGreater(len(edit.label_lines), 0)
                    self.assertGreaterEqual(edit.widget.width, 12)
                    self.assertEqual(edit.widget.getText(), value)
                    with patch.object(dialog, "putString", wraps=dialog.putString) as draws:
                        dialog.paint()
                    self.assert_draws_fit(dialog, draws.call_args_list)
                    self.assertTrue(all(call.args[0] == 2 for call in draws.call_args_list
                        if call.args[-1] in dialog.items[0].lines))
                    helper = dialog.items[-1]
                    for row, line in enumerate(helper.lines):
                        draw = next(call.args for call in draws.call_args_list
                            if call.args[1] == helper.y + row - dialog.scroll_pos and call.args[-1] == line)
                        self.assertEqual(draw[0] + dialog.getStringWidth(line), dialog.width() - 2)
                    edit.widget.setText(value + "changed")
                    edit.widget.setSelection([3, 6])
                    dialog.font_handler = lambda scale: ckit.getStockedFont("MS Gothic", round(12 * scale), round(2 * scale))
                    dialog.onDpi(scale)
                    self.assertEqual(edit.widget.getText(), value + "changed")
                    self.assertEqual(edit.widget.getSelection(), [3, 6])
                    with patch.object(dialog, "setImeRect", wraps=dialog.setImeRect) as ime:
                        dialog.paint()
                    widget = edit.widget
                    self.assertEqual(ime.call_args.args[0], (*dialog.charToClient(widget.x, widget.y),
                        *dialog.charToClient(widget.x + widget.width, widget.y + 1)))
                    self.assert_inside(dialog)
                finally:
                    edit.widget.destroy()
                    dialog.destroy()
                    parent.destroy()

    def test_hotkey_clear_guide_is_two_lines_with_fixed_width(self):
        import clnch_strings_en
        import clnch_strings_ja
        for language in (clnch_strings_ja, clnch_strings_en):
            for scale in (1.0, 1.5, 2.0):
                with self.subTest(language=language.__name__, scale=scale), \
                     patch.object(clnch_configmenu, "strings", language):
                    parent = self.parent(scale)
                    def check(window, language=language):
                        first, second = language.HOTKEY_GUIDE.splitlines()
                        self.assertTrue(second.startswith("(") and second.endswith(")"))
                        self.assertEqual(window.guide_lines, [first, second])
                        expected = max(35, window.getStringWidth(first) + 4,
                                       window.getStringWidth(language.CONFIG_EDIT_GUIDE) + 4,
                                       window.getStringWidth(language.CONFIG_HOTKEY) + 4)
                        self.assertEqual(window.width(), expected)
                        self.assert_inside(window)
                        with patch.object(window, "putString", wraps=window.putString) as draws:
                            window.paint()
                        self.assert_draws_fit(window, draws.call_args_list)
                        window.onKeyDown(ckit.VK_ESCAPE, 0)
                    try:
                        with patch.object(ckit.TextWindow, "messageLoop", check):
                            clnch_configmenu._configHotKeyAssign(parent)
                    finally:
                        parent.destroy()

    def test_hotkey_long_value_fixed_width_and_work_area_ellipsis(self):
        import clnch_strings_en
        import clnch_strings_ja
        expected = "[C]+[S]+[A]+[W]+PrintScreen"
        for language in (clnch_strings_ja, clnch_strings_en):
            for scale in (1.0, 1.5, 2.0):
                for work_width in (1024, 320):
                    self.work_area = (0, 0, work_width, 768)
                    with self.subTest(language=language.__name__, scale=scale, work_width=work_width), \
                         patch.object(clnch_configmenu, "strings", language):
                        parent = self.parent(scale)
                        def check(window):
                            size = window.width(), window.height()
                            for vk, mod in ((ckit.VK_CONTROL, 2), (ckit.VK_SNAPSHOT, 15)):
                                window.onKeyDown(vk, mod)
                                self.assertEqual((window.width(), window.height()), size)
                            with patch.object(window, "putString", wraps=window.putString) as draws:
                                window.paint()
                            self.assert_draws_fit(window, draws.call_args_list)
                            value = [call.args[-1] for call in draws.call_args_list if call.args[1] == 0][-1]
                            if window.getStringWidth(expected) <= window.activate_hotkey.width:
                                self.assertEqual(value.strip(), expected)
                            else:
                                self.assertIn("⋯", value)
                            self.assertEqual(window.activate_hotkey.getValue(), [ckit.VK_SNAPSHOT, 15])
                            window.onDpi(scale)  # noqa: B023  # Driven synchronously within this iteration.
                            self.assertEqual(window.activate_hotkey.getValue(), [ckit.VK_SNAPSHOT, 15])
                            self.assertLessEqual(window.width(), ckit.getWindowSizeLimits(window)[0])
                            window.onKeyDown(ckit.VK_ESCAPE, 0)
                        try:
                            with patch.object(ckit.TextWindow, "messageLoop", check):
                                clnch_configmenu._configHotKeyAssign(parent)
                        finally:
                            parent.destroy()

    def test_hotkey_modifier_warning_localized_layout(self):
        import clnch_strings_en
        import clnch_strings_ja
        for language in (clnch_strings_ja, clnch_strings_en):
            for scale in (1.0, 1.5, 2.0):
                with self.subTest(language=language.__name__, scale=scale):
                    parent = self.parent(scale)
                    box = clnch_msgbox.MessageBox(300, 250, parent, show=False,
                        title=language.ERROR_TITLE, message=language.HOTKEY_MODIFIER_ONLY)
                    try:
                        self.assertEqual("".join(box.message_lines), language.HOTKEY_MODIFIER_ONLY)
                        with patch.object(box, "putString", wraps=box.putString) as draws:
                            box.paint()
                        self.assert_draws_fit(box, draws.call_args_list)
                        self.assert_inside(box)
                    finally:
                        box.destroy()
                        parent.destroy()

    def test_hotkey_guide_grows_and_wraps_without_changing_binding(self):
        for scale in (1.0, 1.5, 2.0):
            with self.subTest(scale=scale), patch.multiple(strings,
                    HOTKEY_GUIDE="Press the keys 全角 " * 4,
                    CONFIG_EDIT_GUIDE="Enter: accept / Esc: cancel 全角 " * 4):
                parent = self.parent(scale)
                def check(window):
                    self.assert_inside(window)
                    self.assertGreaterEqual(len(window.guide_lines), 1)
                    self.assertEqual("".join(window.guide_lines), strings.HOTKEY_GUIDE)
                    self.assertEqual("".join(window.control_lines), strings.CONFIG_EDIT_GUIDE)
                    with patch.object(window, "putString", wraps=window.putString) as draws:
                        window.paint()
                    self.assert_draws_fit(window, draws.call_args_list)
                    for row, line in enumerate(window.guide_lines, 1):
                        draw = next(call.args for call in draws.call_args_list
                            if call.args[1] == row and call.args[-1] == line)
                        self.assertEqual(draw[0], 2)
                    for row, line in enumerate(window.control_lines, len(window.guide_lines) + 1):
                        draw = next(call.args for call in draws.call_args_list
                            if call.args[1] == row and call.args[-1] == line)
                        self.assertEqual(draw[0] + window.getStringWidth(line), window.width() - 2)
                    window.onDpi(scale)  # noqa: B023  # Used within this test iteration.
                    self.assert_inside(window)
                    window.onKeyDown(ckit.VK_TAB, ckit.MODKEY_CTRL)
                    self.assertEqual(window.activate_hotkey.getValue(), [ckit.VK_TAB, ckit.MODKEY_CTRL])
                    window.onKeyDown(ckit.VK_ESCAPE, 0)
                try:
                    with patch.object(ckit.TextWindow, "messageLoop", check):
                        clnch_configmenu._configHotKeyAssign(parent)
                finally:
                    parent.destroy()

    def test_existing_editor_reflows_for_dpi_changes_without_losing_input_or_selection(self):
        parent = self.parent(1.0)
        editor = clnch_cmdeditor.CommandEditor(parent)
        try:
            editor._focus_field("args")
            edit = editor.edit_by_id["args"]
            edit.setText("--argument with spaces 全角")
            edit.setSelection([3, 9])
            for scale in (1.5, 2.0, 1.0):
                editor._on_dpi(scale)
                self.assertEqual(editor._row_gap, round(8 * scale))
                self.assertEqual(edit.getText(), "--argument with spaces 全角")
                self.assertEqual(edit.getSelection(), [3, 9])
                self.assert_inside(editor)
        finally:
            for edit in editor.edits:
                edit.destroy()
            editor.destroy()
            parent.destroy()

    def test_empty_editor_keeps_name_disabled_with_native_widgets_and_both_labels(self):
        for scale in (1.0, 1.5, 2.0):
            for label in ("(空欄コマンド)", "(Empty Command)"):
                with self.subTest(scale=scale, label=label), \
                     patch.object(strings, "COMMAND_EMPTY", label), \
                     patch.object(ckit.TextWindow, "getDisplayScaling", return_value=scale):
                    parent = self.parent(scale)
                    editor = None
                    try:
                        editor = clnch_cmdeditor.CommandEditor(parent, "")
                        editor.active = True
                        self.assertEqual(editor.focus_index, 1)
                        with patch.object(editor, "putString", wraps=editor.putString) as draws:
                            editor.paint()
                        self.assert_draws_fit(editor, draws.call_args_list)
                        self.assertTrue(any(call.args[-1] == label for call in draws.call_args_list))
                        editor._on_keydown(ckit.VK_TAB, ckit.MODKEY_SHIFT)
                        self.assertEqual(editor.focus_index, 5)
                        editor._on_keydown(ckit.VK_TAB, 0)
                        self.assertEqual(editor.focus_index, 1)
                        name = editor.edit_by_id["name"]
                        x, y = editor.charToClient(name.x + 1, name.y)
                        editor._on_left_button_down(x, y, 0)
                        editor._on_drop_files(x, y, ["D:/renamed.exe"])
                        editor._on_keydown(ckit.VK_N, ckit.MODKEY_ALT)
                        self.assertEqual(editor.focus_index, 1)
                        self.assertEqual(name.getText(), "")
                        self.assertFalse(name.enable_cursor)
                    finally:
                        if editor is not None:
                            for edit in editor.edits:
                                edit.destroy()
                            editor.destroy()
                        parent.destroy()

    def test_console_reserves_all_translated_status_lines_outside_log_selection(self):
        for scale in (1.0, 1.5, 2.0):
            parent = self.parent(scale)
            try:
                console = ConsoleWindow.__new__(ConsoleWindow)
                console.width, console.height = lambda: 50, lambda: 20
                console.getStringWidth = parent.getStringWidth
                console.log = clnch_consolewindow.Log()
                console.log.write("\n".join(["line"] * 1000))
                console._wrap_cache = None
                console.scroll_info = ckit.ScrollInfo()
                console.selection = [[0, 0], [0, 0]]
                console.mouse_click_info = None
                with patch.multiple(strings,
                    CONSOLE_STATUS_LATEST="Visible log lines {first}-{last}; {total} lines in total; latest log message 全角",
                    CONSOLE_STATUS_REMAINING="Visible log lines {first}-{last}; {total} lines in total; {count} lines until latest 全角"):
                    status = console.rectStatusBar()
                    self.assertGreater(status[3], 1)
                    self.assertEqual(console.rectText()[3] + status[3], 20)
                    for template in (strings.CONSOLE_STATUS_LATEST, strings.CONSOLE_STATUS_REMAINING):
                        value = template.format(first=1000, last=1000, total=1000, count=1000) + "\n" + strings.CONSOLE_GUIDE
                        self.assertLessEqual(len(ckit.splitLines(console, value, 50)), status[3])
            finally:
                parent.destroy()

    def test_editor_reflows_when_moved_to_a_smaller_work_area(self):
        parent = self.parent(1.0)
        editor = clnch_cmdeditor.CommandEditor(parent)
        try:
            self.work_area = (0, 0, 800, 600)
            editor._on_move(100, 100)
            rect = editor.getWindowRect()
            self.assertLessEqual(rect[2], 800)
            self.assertLessEqual(rect[3], 600)
            self.assertEqual(editor._size_limits, ckit.getWindowSizeLimits(editor))
        finally:
            for edit in editor.edits:
                edit.destroy()
            editor.destroy()
            parent.destroy()

    def test_native_work_area_and_display_notifications_request_relayout(self):
        events = []
        window = ckit.TextWindow(x=100, y=100, width=20, height=1, show=False,
                                 dpi_handler=lambda scale: events.append(scale))
        send = ctypes.WinDLL("user32").SendMessageW
        send.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
        send.restype = wintypes.LPARAM
        try:
            send(window.getHWND(), 0x001A, 0, 0)
            self.assertEqual(events, [])
            send(window.getHWND(), 0x001A, 0x002F, 0)  # WM_SETTINGCHANGE / SPI_SETWORKAREA
            send(window.getHWND(), 0x007E, 0, 0)  # WM_DISPLAYCHANGE
            self.assertEqual(len(events), 2)
            self.assertTrue(all(scale > 0 for scale in events))
        finally:
            window.destroy()


if __name__ == "__main__":
    unittest.main()
