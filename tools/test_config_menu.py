"""Config labels, action routing and storage-mode summaries; menus are replaced."""
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from native_test_support import RUN_DIR

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "clnch"), str(RUN_DIR / "lib")]
import clnch_text

import ckit
from ckit.ckit_const import *

clnch_text.initialize()
import clnch_altenterconfig
import clnch_configmenu as menu
import clnch_execonfig
import clnch_inputconfig


class ConfigMenuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ckit.Keymap.init()

    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.values = {}
        self.stack.enter_context(patch.object(menu.clnch_ini, "get",
            side_effect=lambda section, name, default=None: self.values.get((section, name), default)))
        self.stack.enter_context(patch.object(menu.clnch_ini, "getint",
            side_effect=lambda section, name, default=None: int(self.values.get((section, name), default))))
        self.write = self.stack.enter_context(patch.object(menu.clnch_ini, "set"))
        self.main = SimpleNamespace(input_settings=clnch_inputconfig.DEFAULTS.copy(), updateFont=Mock())

    def capture(self, function):
        with patch.object(menu.clnch_listwindow, "popMenu", return_value=-1) as popup:
            function(self.main)
        self.write.assert_not_called()
        self.main.updateFont.assert_not_called()
        return popup.call_args.args[4]

    def test_history_choices_and_saved_history_notice_in_both_languages(self):
        import clnch_strings_en
        import clnch_strings_ja
        for strings, notice in ((clnch_strings_ja, " (設定変更後、保存済み履歴を削除)"),
                                (clnch_strings_en, " (deletes saved history after changing this setting)")):
            with self.subTest(language=strings.__name__), patch.object(menu, "strings", strings):
                self.main.applyInputSettings = Mock()
                with patch.object(menu.clnch_listwindow, "popMenu", return_value=-1) as popup:
                    menu._configInputSetting(self.main, "HISTORY_MODE")
                self.assertEqual(popup.call_args.args[3], menu._input_options["HISTORY_MODE"][0])
                original = menu._input_options["HISTORY_MODE"][1]
                self.assertEqual([label for label, _value in popup.call_args.args[4]],
                    [original[0][0] + notice, original[1][0] + notice, original[2][0]])
                self.assertEqual([value for _label, value in popup.call_args.args[4]],
                    ["off", "session", "persistent"])
                self.main.applyInputSettings.assert_not_called()
                self.write.assert_not_called()

    def test_modifier_tuples_preserve_choice_zero_boolean_save_and_cancel(self):
        for index in (-1, 0, 1):
            with self.subTest(index=index), patch.object(menu.clnch_listwindow, "popMenu", return_value=(index, 4)):
                value = menu._selectConfigValue(self.main, "Choice", ["zero", "one"], "zero")
                self.assertEqual(value, None if index < 0 else ["zero", "one"][index])
                self.main.altenter_settings = {"properties_first": True}
                with patch.object(menu, "_saveAltEnterSettings") as save:
                    menu._configAltEnterPriority(self.main)
                    if index < 0:
                        save.assert_not_called()
                    else:
                        save.assert_called_once_with(self.main, properties_first=bool(index))
                with patch.object(menu.clnch_execonfig, "read", return_value=True), \
                     patch.object(menu.clnch_execonfig, "write") as write, \
                     patch.object(menu.clnch_msgbox, "popMessageBox"):
                    menu._configDataPath(self.main)
                    if index == 0:
                        write.assert_called_once()
                        self.assertIs(write.call_args.args[1], False)
                    else:
                        write.assert_not_called()

    def test_simple_choices_keep_ranges_defaults_cancel_and_apply_contracts(self):
        cases = (
            (menu._configFontSize, "FONT", "size", 16, list(map(str, range(6, 33))), "updateFont"),
            (menu._configMinWidth, "GEOMETRY", "min_width", 18, list(map(str, range(12, 81))), None),
            (menu._configMaxWidth, "GEOMETRY", "max_width", 80, list(map(str, range(16, 161))), None),
            (menu._configTopMost, "GEOMETRY", "topmost", "0", ["0", "1", "2"], "updateTopMost"),
            (menu._configDirectorySeparator, "MISC", "directory_separator", "backslash",
             ["slash", "backslash"], "slash"),
            (menu._configKeyMap, "MISC", "default_keymap", "106", ["101", "106"], "configure"),
            (menu._configAutoComplete, "MISC", "auto_complete", "0", ["0", "1"], None),
            (menu._configHotKeyBehavior, "MISC", "hotkey_behavior", "toggle",
             ["activate", "toggle"], "updateHotKey"),
            (menu._configInactive, "MISC", "inactive_behavior", "clock",
             ["empty", "clock", "hide"], "updateInactiveBehavior"),
        )
        for function, section, key, default, values, effect in cases:
            with self.subTest(setting=key), ExitStack() as stack:
                self.values.clear()
                events = Mock()
                events.attach_mock(self.write, "set")
                save = stack.enter_context(patch.object(menu.clnch_ini, "write"))
                events.attach_mock(save, "write")
                for name in ("updateFont", "updateTopMost", "configure", "updateHotKey",
                             "updateInactiveBehavior"):
                    setattr(self.main, name, Mock())
                    events.attach_mock(getattr(self.main, name), name)
                slash = stack.enter_context(patch.object(ckit, "setPathSlash"))
                events.attach_mock(slash, "slash")
                popup = stack.enter_context(patch.object(menu.clnch_listwindow, "popMenu", return_value=-1))
                events.reset_mock()
                function(self.main)
                self.assertEqual(popup.call_args.args[5], values.index(str(default)))
                items = popup.call_args.args[4]
                if key in ("size", "min_width", "max_width"):
                    self.assertEqual(items, values)
                else:
                    self.assertTrue(all(isinstance(item, tuple) for item in items))
                    self.assertEqual([value for _, value in items], values)
                self.assertEqual(events.mock_calls, [])
                # Every legal current value, including same-value confirmation, keeps its effect.
                for index, value in enumerate(values):
                    self.values[section, key] = value
                    popup.return_value = index
                    events.reset_mock()
                    function(self.main)
                    self.assertEqual(popup.call_args.args[5], index)
                    expected = [call.set(section, key, value)]
                    if effect == "slash":
                        expected.append(call.slash(value == "slash"))
                    elif effect:
                        expected.append(getattr(call, effect)())
                    self.assertEqual(events.mock_calls, expected)
                self.values[section, key] = "999" if key in ("size", "min_width", "max_width") else "unknown"
                popup.return_value = -1
                events.reset_mock()
                function(self.main)
                self.assertEqual(popup.call_args.args[5], 0)
                self.assertEqual(events.mock_calls, [])

    def test_menu_iteration_refreshes_clamps_and_leaves_dispatch_to_caller(self):
        action = Mock()
        first = [("first", action), ("second", action)]
        updated = [("updated", action)]
        build = Mock(side_effect=[first, updated])
        with patch.object(menu.clnch_listwindow, "popMenu", side_effect=[1, -1]) as popup:
            selections = list(menu._iterConfigMenu(self.main, "title", build))
        self.assertEqual(selections, [(first, 1)])
        action.assert_not_called()
        self.assertEqual(build.call_count, 2)
        self.assertEqual([c.args[5] for c in popup.call_args_list], [0, 0])
        self.assertEqual(popup.call_args_list[1].args[4], updated)

    def test_theme_without_candidates_returns_without_popup_or_changes(self):
        self.main.reloadTheme = Mock()
        self.values["THEME", "name"] = "gray"
        for state in ("missing", "empty", "non-ini"):
            with self.subTest(state=state), tempfile.TemporaryDirectory() as directory:
                themes = Path(directory) / "themes"
                if state != "missing":
                    themes.mkdir()
                if state == "non-ini":
                    (themes / "notes.txt").touch()
                    (themes / "gray.ini.bak").touch()
                    (themes / "folder.ini").mkdir()
                with patch.object(ckit, "getAppExePath", return_value=directory), \
                     patch.object(menu.clnch_listwindow, "popMenu") as popup, \
                     patch.object(menu.clnch_ini, "write") as save:
                    self.assertIsNone(menu._configTheme(self.main))
                popup.assert_not_called()
                self.write.assert_not_called()
                save.assert_not_called()
                self.main.reloadTheme.assert_not_called()
                self.assertEqual(self.values["THEME", "name"], "gray")
                self.assertEqual(themes.exists(), state != "missing")

    def test_missing_themes_returns_to_appearance_menu(self):
        self.main.reloadTheme = Mock()
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(ckit, "getAppExePath", return_value=directory), \
             patch.object(menu.clnch_listwindow, "popMenu", side_effect=[0, -1]) as popup:
            self.assertIsNone(menu._configAppearance(self.main))
        self.assertEqual([c.args[3] for c in popup.call_args_list],
                         [menu.strings.CONFIG_APPEARANCE] * 2)
        self.assertEqual([c.args[5] for c in popup.call_args_list], [0, 0])
        self.write.assert_not_called()
        self.main.reloadTheme.assert_not_called()

    def test_theme_access_denied_is_not_suppressed(self):
        self.main.reloadTheme = Mock()
        with patch.object(menu.os, "listdir", side_effect=PermissionError), \
             patch.object(menu.clnch_listwindow, "popMenu") as popup, \
             self.assertRaises(PermissionError):
            menu._configTheme(self.main)
        popup.assert_not_called()
        self.write.assert_not_called()
        self.main.reloadTheme.assert_not_called()

    def test_theme_choices_initial_selection_cancel_and_confirm(self):
        self.main.reloadTheme = Mock()
        with tempfile.TemporaryDirectory() as directory:
            themes = Path(directory) / "themes"
            themes.mkdir()
            for name in ("black.ini", "gray.INI", "white.ini", "notes.txt"):
                (themes / name).touch()
            (themes / "folder.ini").mkdir()
            with patch.object(ckit, "getAppExePath", return_value=directory), \
                 patch.object(menu.clnch_listwindow, "popMenu", return_value=-1) as popup:
                for current in ("black", "gray", "white", "missing"):
                    with self.subTest(current=current):
                        self.values["THEME", "name"] = current
                        self.assertIsNone(menu._configTheme(self.main))
                        items = popup.call_args.args[4]
                        self.assertCountEqual(items, ["black", "gray", "white"])
                        self.assertEqual(popup.call_args.args[5],
                                         items.index(current) if current in items else 0)
                        self.write.assert_not_called()
                        self.main.reloadTheme.assert_not_called()
                popup.return_value = items.index("white")
                self.assertIs(menu._configTheme(self.main), False)
                self.write.assert_called_once_with("THEME", "name", "white")
                self.main.reloadTheme.assert_called_once_with()

    def test_only_appearance_propagates_false_and_root_consumes_it(self):
        for opener, action, index, propagates in (
            (menu._configAppearance, "_configTheme", 0, True),
            (menu._configInput, "_configKeyMap", 0, False),
            (menu._configHotKey, "_configHotKeyAssign", 0, False),
            (menu.doConfigMenu, "_reloadConfigFile", 8, False),
        ):
            with self.subTest(menu=opener.__name__), \
                 patch.object(menu, action, return_value=False) as selected, \
                 patch.object(menu, "_dataPathValue", return_value="app"), \
                 patch.object(menu.clnch_listwindow, "popMenu", side_effect=[index, -1]) as popup:
                result = opener(self.main)
                self.assertEqual(popup.call_count, 1 if opener in (menu._configAppearance, menu.doConfigMenu) else 2)
                selected.assert_called_once_with(self.main)
                self.assertIs(result, False if propagates else None)

    def test_altenter_shrinks_rows_and_modifier_rebuilds_status_and_selection(self):
        import clnch_modifierconfig
        self.main.getStringWidth = len
        self.main.altenter_settings = dict(clnch_altenterconfig.DEFAULTS, action="web")
        with patch.object(menu, "_configAltEnterPriority"), \
             patch.object(menu, "_configAltEnterAction", side_effect=lambda window, key:
                          window.altenter_settings.update(action="none")), \
             patch.object(menu.clnch_listwindow, "popMenu", side_effect=[2, 0, -1]) as popup:
            menu._configAltEnterKey(self.main)
        self.assertEqual([c.args[5] for c in popup.call_args_list], [0, 2, 0])
        self.assertEqual([len(c.args[4]) for c in popup.call_args_list], [3, 3, 1])
        self.main.modifier_settings = clnch_modifierconfig.DEFAULTS.copy()
        with patch.object(menu, "_configModifier", side_effect=lambda window, modifier, label:
                          window.modifier_settings.update({modifier + "_ACTION": "execute"})), \
             patch.object(menu.clnch_listwindow, "popMenu", side_effect=[1, -1]) as popup:
            menu._configModifiers(self.main)
        self.assertEqual([c.args[5] for c in popup.call_args_list], [0, 1])
        self.assertTrue(all(isinstance(item, str) for item in popup.call_args.args[4]))
        self.assertNotEqual(popup.call_args_list[0].args[4][1], popup.call_args_list[1].args[4][1])
        self.assertEqual(popup.call_args.kwargs["statusbar_handler"](80, 1), menu.strings.MODIFIER_GUIDE)

    def test_appearance_values_order_and_original_actions(self):
        self.values.update({("THEME", "name"): "gray", ("FONT", "name"): "Consolas",
            ("FONT", "size"): 18, ("GEOMETRY", "min_width"): 24, ("GEOMETRY", "max_width"): 100,
            ("MISC", "directory_separator"): "slash", ("GEOMETRY", "topmost"): "2"})
        with patch.object(ckit, "getStockedFont", side_effect=AssertionError("label created a font")):
            items = self.capture(menu._configAppearance)
        self.assertEqual([item[0] for item in items], ["テーマ: gray", "フォント名: Consolas",
            "フォントサイズ: 18", "最小の横幅: 24セル", "最大の横幅: 100セル",
            "ファイルパス区切り文字: スラッシュ", "最前面に表示: 最前面のなかの最前面",
            "現在の表示位置を保存"])
        self.assertEqual([item[1] for item in items], [menu._configTheme, menu._configFontName,
            menu._configFontSize, menu._configMinWidth, menu._configMaxWidth,
            menu._configDirectorySeparator, menu._configTopMost, menu._configPosition])
        self.values["MISC", "directory_separator"] = "backslash"
        for value, label in (("0", "通常"), ("1", "最前面")):
            self.values["GEOMETRY", "topmost"] = value
            items = self.capture(menu._configAppearance)
            self.assertEqual(items[5][0], "ファイルパス区切り文字: バックスラッシュ")
            self.assertEqual(items[6][0], "最前面に表示: " + label)

    def test_input_values_and_five_options(self):
        for keymap, label in (("101", "英語(101)"), ("106", "日本語(106/109)")):
            for enabled, description in (("0", "自動補完しない"), ("1", "自動補完する")):
                self.values.update({("MISC", "default_keymap"): keymap, ("MISC", "auto_complete"): enabled})
                items = self.capture(menu._configInput)
                self.assertEqual([item[0] for item in items], ["キー配列: " + label,
                    "自動補完: " + description, "履歴: 保持して保存", "補完候補: 登録名・ファイル名・共有",
                    "非アクティブ時の入力クリア: クリアする",
                    "Spaceの動作: 空白入力", "Tabの動作: 共通部分を補完"])
                self.assertIs(items[0][1], menu._configKeyMap)
                self.assertIs(items[1][1], menu._configAutoComplete)

    def test_hotkey_names_all_modifiers_and_unassigned(self):
        self.assertEqual(menu._hotKeyValue(), "未設定")
        self.values["HOTKEY", "activate_vk"] = VK_SPACE
        flags = ((MODKEY_CTRL, "[C]"), (MODKEY_SHIFT, "[S]"), (MODKEY_ALT, "[A]"), (MODKEY_WIN, "[W]"))
        for mask in range(16):
            enabled = [pair for i, pair in enumerate(flags) if mask & (1 << i)]
            self.values["HOTKEY", "activate_mod"] = sum(pair[0] for pair in enabled)
            self.assertEqual(menu._hotKeyValue(), "+".join([*(pair[1] for pair in enabled), "Space"]))
        self.values["HOTKEY", "activate_mod"] = MODKEY_CTRL
        items = self.capture(menu._configHotKey)
        self.assertEqual([item[0] for item in items], ["ホットキー割り当て: [C]+Space", "ホットキーの動作: トグル"])
        self.assertEqual([item[1] for item in items], [menu._configHotKeyAssign, menu._configHotKeyBehavior])
        self.values["MISC", "hotkey_behavior"] = "activate"
        self.assertEqual(self.capture(menu._configHotKey)[1][0], "ホットキーの動作: アクティブ化")

    def test_root_keeps_categories_and_actions_plain(self):
        with patch.object(menu, "_dataPathValue", return_value="アプリフォルダ"):
            items = self.capture(menu.doConfigMenu)
        self.assertEqual([item[0] for item in items], ["表示オプション", "入力オプション",
            "修飾キーの既定動作", "Alt+Enterの動作", "非アクティブ時の表示: 時計",
            "ホットキー設定", "言語: Japanese（次回起動後: English）", "設定の保存先: アプリフォルダ", "設定をリロード"])
        self.assertEqual([item[1] for item in items], [menu._configAppearance, menu._configInput,
            menu._configModifiers, menu._configAltEnter, menu._configInactive, menu._configHotKey,
            menu._configLanguage, menu._configDataPath, menu._reloadConfigFile])
        for value, label in (("empty", "空欄"), ("hide", "非表示")):
            self.values["MISC", "inactive_behavior"] = value
            with patch.object(menu, "_dataPathValue", return_value="アプリフォルダ"):
                self.assertEqual(self.capture(menu.doConfigMenu)[4][0], "非アクティブ時の表示: " + label)

    def test_labels_refresh_after_returning_from_each_submenu(self):
        for opener, action, index, setting, first, second in (
            (menu._configAppearance, "_configFontSize", 2, ("FONT", "size"), "フォントサイズ: 16", "フォントサイズ: 18"),
            (menu._configInput, "_configAutoComplete", 1, ("MISC", "auto_complete"), "自動補完: 自動補完しない", "自動補完: 自動補完する"),
            (menu._configHotKey, "_configHotKeyAssign", 0, ("HOTKEY", "activate_vk"), "ホットキー割り当て: 未設定", "ホットキー割り当て: Space"),
            (menu.doConfigMenu, "_configInactive", 4, ("MISC", "inactive_behavior"), "非アクティブ時の表示: 時計", "非アクティブ時の表示: 非表示")):
            self.values.clear()
            labels = []
            def popup(parent, width, height, title, items, selected):
                labels.append(items[index][0])  # noqa: B023  # Used within this test iteration.
                return index if len(labels) == 1 else -1  # noqa: B023  # Used within this test iteration.
            value = {"_configFontSize": 18, "_configAutoComplete": "1", "_configHotKeyAssign": VK_SPACE, "_configInactive": "hide"}[action]
            with patch.object(menu.clnch_listwindow, "popMenu", side_effect=popup), \
                 patch.object(menu, "_dataPathValue", return_value="アプリフォルダ"), \
                 patch.object(menu, action, side_effect=lambda parent: self.values.update({setting: value})):  # noqa: B023  # Used within this test iteration.
                opener(self.main)
            self.assertEqual(labels, [first, second])

    def test_destination_summaries_distinguish_missing_values_and_preserve_full_data(self):
        self.main.getStringWidth = lambda text: sum(1 if ord(c) < 128 else 2 for c in text)
        self.main.altenter_settings = clnch_altenterconfig.DEFAULTS.copy()
        for mode, title, key in (("application", "外部アプリの設定", "executable"),
                                  ("web", "URLテンプレート", "url")):
            self.main.altenter_settings["action"] = mode
            items = self.capture(menu._configAltEnterKey)
            self.assertEqual(items[1][0], title + ": 未設定")
            with patch.object(menu, "_configAltEnterTarget") as target:
                items[1][1](self.main)
                target.assert_called_once_with(self.main, "")
            value = ("C:\\辞書 tools\\EBWin4.exe" if mode == "application" else
                     "https://search.example.org/" + "日本語/" * 40 + "?q=%param%")
            self.main.altenter_settings[key] = value
            items = self.capture(menu._configAltEnterKey)
            preview = items[1][0].split(": ", 1)[1]
            if mode == "application":
                self.assertEqual(preview, "EBWin4.exe")
            else:
                self.assertLess(self.main.getStringWidth(preview), self.main.getStringWidth(value))
                self.assertTrue(preview.startswith("https://"))
                self.assertTrue(preview.endswith("?q=%param%"))
            self.assertEqual(self.main.altenter_settings[key], value)
        for value in ("短い値", "D:/" + "長いフォルダ/" * 50):
            preview = menu._configValuePreview(self.main, value)
            self.assertLessEqual(self.main.getStringWidth(preview), self.main.getStringWidth(value))
            self.assertEqual(preview == value, self.main.getStringWidth(value) <= 48)

    def test_altenter_summary_refreshes_after_editing(self):
        self.main.getStringWidth = len
        self.main.altenter_settings = dict(clnch_altenterconfig.DEFAULTS, action="web")
        labels = []
        def popup(parent, width, height, title, items, selected):
            labels.append(items[1][0])
            return 1 if len(labels) == 1 else -1
        with patch.object(menu.clnch_listwindow, "popMenu", side_effect=popup), \
             patch.object(menu, "_configAltEnterTarget", side_effect=lambda window, key:
                 window.altenter_settings.update(url="https://example.org/?q=%param%")):
            menu._configAltEnterKey(self.main)
        self.assertEqual(labels, ["URLテンプレート: 未設定", "URLテンプレート: https://example.org/?q=%param%"])

    def test_language_names_use_wording_for_choices_and_pending_summary(self):
        self.values["MISC", "language"] = "en"
        with patch.object(menu.strings, "LANGUAGE_JAPANESE", "Custom Japanese"), \
             patch.object(menu.strings, "LANGUAGE_ENGLISH", "Custom English"), \
             patch.object(menu, "_selectConfigValue", return_value=None) as select:
            menu._configLanguage(self.main)
            self.assertEqual(select.call_args.args[2],
                             [("Custom Japanese", "ja"), ("Custom English", "en")])
            self.assertEqual(menu._languageValue(), menu.strings.LANGUAGE_PENDING.format(
                current="Custom Japanese", next="Custom English"))
        self.write.assert_not_called()

    def test_language_save_failure_restores_ini_state_without_restart_notice(self):
        import configparser
        for dirty, read_failed in ((False, False), (True, False), (False, True)):
            with self.subTest(dirty=dirty, read_failed=read_failed):
                parser = configparser.RawConfigParser()
                parser["MISC"] = {"language": "ja"}
                self.values["MISC", "language"] = "ja"
                def set_value(section, name, value, parser=parser):
                    parser[section][name] = value
                    menu.clnch_ini.dirty = True
                self.write.side_effect = set_value
                with patch.object(menu.clnch_ini, "ini", parser), \
                     patch.object(menu.clnch_ini, "dirty", dirty), \
                     patch.object(menu.clnch_ini, "read_failed", read_failed), \
                     patch.object(menu.clnch_listwindow, "popMenu", return_value=(1, 4)), \
                     patch.object(menu.clnch_ini, "write") as save, \
                     patch.object(menu.clnch_msgbox, "popMessageBox") as message:
                    menu._configLanguage(self.main)
                    save.assert_called_once_with()
                    message.assert_not_called()
                    self.assertEqual(menu.clnch_ini.ini.get("MISC", "language"), "ja")
                    self.assertIs(menu.clnch_ini.dirty, dirty)
        self.write.side_effect = None
        self.write.reset_mock()

    def test_language_choice_cancel_save_and_pending_summary(self):
        original_title = menu.strings.CONFIG_TITLE
        for saved in (None, "ja", "en", "invalid"):
            for selected in (-1, 0, 1):
                with self.subTest(saved=saved, selected=selected):
                    self.values.clear()
                    if saved is not None:
                        self.values["MISC", "language"] = saved
                    self.write.reset_mock()
                    with patch.object(menu.clnch_listwindow, "popMenu", return_value=(selected, 4)) as popup, \
                         patch.object(menu.clnch_ini, "write") as save, \
                         patch.object(menu.clnch_msgbox, "popMessageBox") as message:
                        menu._configLanguage(self.main)
                    self.assertEqual(popup.call_args.args[4], [("Japanese", "ja"), ("English", "en")])
                    self.assertEqual(popup.call_args.args[5], 0 if saved == "ja" else 1)
                    value = ("ja", "en")[selected] if selected >= 0 else None
                    if value is not None and value != (saved if saved is not None else "en"):
                        self.write.assert_called_once_with("MISC", "language", value)
                        save.assert_called_once_with()
                        self.assertEqual(message.call_args.args[-1], menu.strings.LANGUAGE_RESTART)
                    else:
                        self.write.assert_not_called()
                        save.assert_not_called()
                        message.assert_not_called()
                    self.assertEqual(menu.strings.get_language(), "ja")
                    self.assertEqual(menu.strings.CONFIG_TITLE, original_title)
        self.write.reset_mock()
        for current in ("ja", "en"):
            for saved in ("ja", "en", "invalid"):
                self.values["MISC", "language"] = saved
                with patch.object(menu.strings, "get_language", return_value=current):
                    labels = {"ja": "Japanese", "en": "English"}
                    next_language = "ja" if saved == "ja" else "en"
                    expected = (labels[current] if current == next_language else
                                menu.strings.LANGUAGE_PENDING.format(current=labels[current], next=labels[next_language]))
                    self.assertEqual(menu._languageValue(), expected)
                    with patch.object(menu, "_dataPathValue", return_value="app"):
                        self.assertIs(self.capture(menu.doConfigMenu)[6][1], menu._configLanguage)

    def test_storage_summary_distinguishes_running_and_next_start_and_handles_read_error(self):
        with tempfile.TemporaryDirectory() as directory:
            app = Path(directory)
            with patch.object(menu.sys, "executable", str(app / "reclnch.exe")):
                for running in (False, True):
                    active = app / ("profile" if running else "settings")
                    with patch.object(ckit, "dataPath", return_value=str(active)):
                        for next_start in (False, True):
                            clnch_execonfig.write(app, next_start)
                            current_label = "AppDataフォルダ" if running else "アプリフォルダ"
                            next_label = "AppDataフォルダ" if next_start else "アプリフォルダ"
                            expected = current_label if running == next_start else current_label + "（次回起動後: " + next_label + "）"
                            self.assertEqual(menu._dataPathValue(), expected)
                            self.assertEqual(self.capture(menu.doConfigMenu)[7][0], "設定の保存先: " + expected)
                (app / "reclnch_exe.ini").write_text("[DATA]\nmulti_user=invalid\n", encoding="utf-8")
                with patch.object(ckit, "dataPath", return_value=str(app / "settings")):
                    self.assertEqual(menu._dataPathValue(), "アプリフォルダ（次回起動後: 読込エラー）")
                    self.capture(menu.doConfigMenu)
                    with patch.object(menu.clnch_msgbox, "popMessageBox") as error:
                        menu._configDataPath(self.main)
                    error.assert_called_once()
        self.write.assert_not_called()


if __name__ == "__main__":
    unittest.main()
