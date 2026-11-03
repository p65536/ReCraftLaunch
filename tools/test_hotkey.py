"""Hotkey replacement, disabled state and recovery with native calls replaced."""
import ctypes
import itertools
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from native_test_support import ROOT, RUN_DIR

sys.path[:0] = [str(ROOT), str(ROOT / "clnch"), str(RUN_DIR / "lib")]
import clnch_text

clnch_text.initialize()
import clnch_configmenu as menu
import clnch_mainwindow as main

import ckit


class HotKeyDisplayTests(unittest.TestCase):
    def setUp(self):
        ckit.Keymap.init()
        ckit.setDataPath(str(ROOT / "samples"))
        ckit.setTheme("black", {})
        self.addCleanup(ckit.Keymap.init)

    def test_modifiers_order_sides_and_key_names(self):
        flags = ((ckit.MODKEY_CTRL, "[C]"), (ckit.MODKEY_SHIFT, "[S]"),
                 (ckit.MODKEY_ALT, "[A]"), (ckit.MODKEY_WIN, "[W]"))
        modifier_keys = ((ckit.VK_CONTROL, ckit.VK_LCONTROL, ckit.VK_RCONTROL),
                         (ckit.VK_SHIFT, ckit.VK_LSHIFT, ckit.VK_RSHIFT),
                         (ckit.VK_MENU, ckit.VK_LMENU, ckit.VK_RMENU),
                         (ckit.VK_LWIN, ckit.VK_RWIN))
        for selected in itertools.product((False, True), repeat=4):
            mod = sum(mask for (mask, _), enabled in zip(flags, selected) if enabled)
            prefix = [label for (_, label), enabled in zip(flags, selected) if enabled]
            for vk, name in ((ckit.VK_A, "A"), (ckit.VK_C, "C"), (ckit.VK_F1, "F1"),
                             (ckit.VK_SPACE, "Space"), (ckit.VK_SNAPSHOT, "PrintScreen"),
                             (ckit.VK_ADD, "Add"), (ckit.VK_SUBTRACT, "Subtract"),
                             (ckit.VK_DIVIDE, "Divide"), (ckit.VK_MULTIPLY, "Multiply"), (255, "(255)")):
                with self.subTest(vk=vk, mod=mod):
                    self.assertEqual(ckit.KeyEvent.formatHotKey(vk, mod), "+".join([*prefix, name]))
                    self.assertFalse(ckit.KeyEvent.isModifierKey(vk))
            for (mask, _), keys in zip(flags, modifier_keys):
                expected = "+".join(label for bit, label in flags if (mod | mask) & bit)
                for vk in keys:
                    self.assertEqual(ckit.KeyEvent.formatHotKey(vk, mod), expected)
                    self.assertTrue(ckit.KeyEvent.isModifierKey(vk))
            self.assertEqual(ckit.KeyEvent.formatHotKey(0, mod), "")

    def test_layout_symbols_shift_and_existing_key_syntax(self):
        keys = (ckit.VK_OEM_1, ckit.VK_OEM_PLUS, ckit.VK_OEM_COMMA, ckit.VK_OEM_MINUS,
                ckit.VK_OEM_PERIOD, ckit.VK_OEM_2, ckit.VK_OEM_3, ckit.VK_OEM_4,
                ckit.VK_OEM_5, ckit.VK_OEM_6, ckit.VK_OEM_7, ckit.VK_OEM_102)
        for keyboard_type, symbols in ((7, (":", ";", ",", "-", ".", "/", "@", "[", "¥", "]", "^", "\\")),
                                       (4, (";", "=", ",", "-", ".", "/", "`", "[", "\\", "]", "'", "(226)"))):
            with patch.object(ctypes.windll.user32, "GetKeyboardType", return_value=keyboard_type):
                ckit.KeyEvent.initTables()
            for vk, symbol in zip(keys, symbols):
                with self.subTest(keyboard_type=keyboard_type, vk=vk):
                    self.assertEqual(ckit.KeyEvent.formatHotKey(vk, ckit.MODKEY_CTRL), "[C]+" + symbol)
                    self.assertEqual(ckit.KeyEvent.formatHotKey(vk, ckit.MODKEY_CTRL | ckit.MODKEY_SHIFT),
                                     "[C]+[S]+" + symbol)
                    name = ckit.KeyEvent.vkToStr(vk)
                    self.assertEqual(str(ckit.KeyEvent(vk, 7)), "A-C-S-" + name)
                    self.assertEqual(ckit.KeyEvent.fromString("A-C-S-" + name), ckit.KeyEvent(vk, 7))
        with patch.dict(ckit.KeyEvent.vk_str_table, {255: "+"}):
            self.assertEqual(ckit.KeyEvent.formatHotKey(255, 2), "[C]+[+]")

    def test_widget_narrow_widths_show_ellipsis_and_keep_value(self):
        window = Mock()
        window.getStringWidth.side_effect = len
        for width in (0, 1, 2, 3, 12, 26, 27, 31):
            with self.subTest(width=width):
                widget = ckit.HotKeyWidget(window, 2, 0, width, 1, ckit.VK_SNAPSHOT, 15)
                value = window.putString.call_args.args[-1]
                self.assertLessEqual(len(value), width)
                if 0 < width < len(ckit.KeyEvent.formatHotKey(ckit.VK_SNAPSHOT, 15)):
                    self.assertIn("⋯", value)
                self.assertEqual(widget.getValue(), [ckit.VK_SNAPSHOT, 15])

    def test_widget_and_menu_share_display_and_modifier_preview(self):
        window = Mock()
        window.getStringWidth.side_effect = len
        widget = ckit.HotKeyWidget(window, 2, 0, 31, 1, 0, 0)
        for order in itertools.permutations(((ckit.VK_CONTROL, 2), (ckit.VK_SHIFT, 4),
                                             (ckit.VK_MENU, 1), (ckit.VK_LWIN, 8))):
            mod = 0
            for vk, bit in order:
                mod |= bit
                widget.onKeyDown(vk, mod)
                value = widget.getValue()
                with patch.object(menu.clnch_ini, "getint", side_effect=value):
                    self.assertEqual(window.putString.call_args.args[-1].strip(), menu._hotKeyValue())
            self.assertEqual(window.putString.call_args.args[-1].strip(), "[C]+[S]+[A]+[W]")
        for vk, mod in ((ckit.VK_SNAPSHOT, 15), (ckit.VK_C, 2), (ckit.VK_OEM_3, 2), (255, 0)):
            widget.onKeyDown(vk, mod)
            with patch.object(menu.clnch_ini, "getint", side_effect=widget.getValue()):
                self.assertEqual(window.putString.call_args.args[-1].strip(), menu._hotKeyValue())
        widget.onKeyDown(0, 0)
        self.assertEqual(window.putString.call_args.args[-1].strip(), "")
        with patch.object(menu.clnch_ini, "getint", return_value=0):
            self.assertEqual(menu._hotKeyValue(), menu.strings.HOTKEY_UNASSIGNED)


class HotKeyTests(unittest.TestCase):
    def setUp(self):
        self.window = SimpleNamespace(_registered_hotkey=(0, 0),
                                      hotkey_Activate=Mock(), setHotKey=Mock(), killHotKey=Mock())
        self.notice = patch.object(main.clnch_msgbox, "popMessageBox").start()
        self.addCleanup(patch.stopall)

    def update(self, vk, mod):
        return main.MainWindow.updateHotKey(self.window, vk, mod)

    def test_disabled_default_same_value_change_and_disable(self):
        self.assertTrue(self.update(0, 0))
        self.window.setHotKey.assert_not_called()
        self.window.killHotKey.assert_not_called()
        self.assertTrue(self.update(120, 2))
        self.assertTrue(self.update(120, 2))
        self.window.setHotKey.assert_called_once_with(120, 2, self.window.hotkey_Activate)
        self.window.killHotKey.assert_not_called()
        self.assertTrue(self.update(121, 4))
        self.assertEqual(self.window._registered_hotkey, (121, 4))
        self.assertTrue(self.update(0, 0))
        self.assertEqual(self.window._registered_hotkey, (0, 0))
        self.assertEqual(self.window.killHotKey.call_count, 2)
        self.notice.assert_not_called()

    def test_initial_failure_is_not_registered_and_can_retry(self):
        self.window.setHotKey.side_effect = OSError("registration failed")
        self.assertFalse(self.update(120, 2))
        self.assertEqual(self.window._registered_hotkey, (0, 0))
        self.notice.assert_called_once()
        self.assertIn("registration failed", self.notice.call_args.args[-1])
        self.window.setHotKey.side_effect = None
        self.assertTrue(self.update(120, 2))

    def test_failed_replacement_restores_previous_hotkey(self):
        self.window._registered_hotkey = (120, 2)
        for error in (OSError("conflict"), MemoryError("allocation"), RuntimeError("no IDs")):
            with self.subTest(error=error):
                self.window.setHotKey.side_effect = [error, None]
                self.assertFalse(self.update(121, 4))
                self.assertEqual(self.window._registered_hotkey, (120, 2))
                self.assertEqual(self.window.setHotKey.call_args.args[:2], (120, 2))

    def test_unregister_failure_keeps_previous_registration(self):
        self.window._registered_hotkey = (120, 2)
        self.window.killHotKey.side_effect = OSError("unregister failed")
        self.assertFalse(self.update(121, 4))
        self.assertEqual(self.window._registered_hotkey, (120, 2))
        self.window.setHotKey.assert_not_called()

    def test_restore_failure_reports_both_errors_and_allows_retry(self):
        self.window._registered_hotkey = (120, 2)
        self.window.setHotKey.side_effect = [OSError("new failed"), OSError("old failed")]
        self.assertFalse(self.update(121, 4))
        self.assertEqual(self.window._registered_hotkey, (0, 0))
        message = self.notice.call_args.args[-1]
        self.assertIn("new failed", message)
        self.assertIn("old failed", message)
        self.assertIn(main.strings.HOTKEY_RESTORE_ERROR, message)
        self.window.setHotKey.side_effect = None
        self.assertTrue(self.update(120, 2))

    def test_reload_reads_current_settings(self):
        with patch.object(main.clnch_ini, "getint", side_effect=[120, 2]):
            self.assertTrue(main.MainWindow.updateHotKey(self.window))
        self.assertEqual(self.window._registered_hotkey, (120, 2))

    def test_modifier_only_rejected_before_registration_or_settings_change(self):
        self.window._registered_hotkey = (120, 2)
        for vk in (ckit.VK_CONTROL, ckit.VK_LCONTROL, ckit.VK_RCONTROL,
                   ckit.VK_SHIFT, ckit.VK_LSHIFT, ckit.VK_RSHIFT,
                   ckit.VK_MENU, ckit.VK_LMENU, ckit.VK_RMENU, ckit.VK_LWIN, ckit.VK_RWIN):
            for mod in range(16):
                with self.subTest(vk=vk, mod=mod), patch.object(main.clnch_ini, "set") as save:
                    self.assertFalse(self.update(vk, mod))
                    self.assertEqual(self.window._registered_hotkey, (120, 2))
                    self.assertEqual(self.notice.call_args.args[-1], main.strings.HOTKEY_MODIFIER_ONLY)
                    save.assert_not_called()
        self.window.setHotKey.assert_not_called()
        self.window.killHotKey.assert_not_called()

    def test_saved_modifier_only_rejected_without_rewriting_ini(self):
        with patch.object(main.clnch_ini, "getint", side_effect=[ckit.VK_RCONTROL, 4]), \
             patch.object(main.clnch_ini, "set") as save:
            self.assertFalse(main.MainWindow.updateHotKey(self.window))
        self.assertEqual(self.window._registered_hotkey, (0, 0))
        self.window.setHotKey.assert_not_called()
        self.window.killHotKey.assert_not_called()
        save.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
