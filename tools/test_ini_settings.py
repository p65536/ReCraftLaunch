"""Current INI specification and read/write behavior, using the real Windows INI API."""
import ast
import configparser
import inspect
import sys
import tempfile
import unittest
from dataclasses import FrozenInstanceError, fields, replace
from pathlib import Path
from typing import TYPE_CHECKING, assert_type
from unittest.mock import patch

from native_test_support import RUN_DIR

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "clnch"), str(RUN_DIR / "lib")]
import clnch_altenterconfig
import clnch_execonfig
import clnch_ini
import clnch_inisettings as definitions
import clnch_inputconfig
import clnch_modifierconfig

from ckit import ckit_theme

# Independent expectations for current names/defaults/types, not runtime definitions.
EXPECTED = {
    "CONSOLE": {"height": (32, int), "width": (80, int), "x": (0, int), "y": (0, int)},
    "DEBUG": {"detect_block": (0, int), "print_errorinfo": (0, int)},
    "FONT": {"name": ("MS Gothic", str), "size": (16, int)},
    "GEOMETRY": {
        "height": (None, int), "width": (None, int), "min_width": (18, int),
        "max_width": (80, int), "monitor": (0, int), "x": (0, int), "y": (0, int),
        "topmost": (0, int),
    },
    "HOTKEY": {"activate_mod": (0, int), "activate_vk": (0, int)},
    "MISC": {
        "language": ("en", str),
        "auto_complete": (0, int), "default_keymap": ("106", str),
        "directory_separator": ("backslash", str), "hotkey_behavior": ("toggle", str),
        "inactive_behavior": ("clock", str), "isearch_type": ("partial", str),
    },
    "THEME": {"name": ("gray", str)},
}
DOMAIN_DEFAULTS = {
    clnch_inputconfig: ("INPUT", {
        "HISTORY_MODE": "persistent", "COMPLETION_MODE": "standard",
        "CLEAR_ON_DEACTIVATE": True,
        "SPACE_ACTION": "insert", "TAB_ACTION": "complete",
    }),
    clnch_modifierconfig: ("MODIFIER", {
        "CTRL_ACTION": "none", "SHIFT_ACTION": "target_folder", "CTRL_SHIFT_ACTION": "none",
        "SOURCE_ROOTS": (), "CTRL_DESTINATION_ROOT": "", "SHIFT_DESTINATION_ROOT": "",
        "CTRL_SHIFT_DESTINATION_ROOT": "",
    }),
    clnch_altenterconfig: ("ALT_ENTER", {
        "action": "none", "executable": "", "arguments": "%param%", "url": "",
        "properties_first": True,
    }),
}


class IniDefinitionTests(unittest.TestCase):
    def setUp(self):
        self.settings = [v for v in vars(definitions).values()
                         if isinstance(v, definitions.IniSetting)]
        self.enterContext(patch.object(clnch_ini, "ini", configparser.RawConfigParser()))
        self.enterContext(patch.object(clnch_ini, "dirty", False))

    def test_complete_static_specification_and_immutable_definitions(self):
        actual = {(v.section, v.key): (v.default, v.value_type) for v in self.settings}
        expected = {(section, key): value for section, keys in EXPECTED.items()
                    for key, value in keys.items()}
        self.assertEqual(actual, expected)
        self.assertEqual(len(self.settings), len(actual))
        with self.assertRaises(FrozenInstanceError):
            definitions.FONT_SIZE.default = 99

    def test_constructor_keeps_dataclass_fields_identity_and_replacement(self):
        setting = definitions.IniSetting("TEST", "value", "fallback")
        self.assertEqual([field.name for field in fields(setting)], ["section", "key", "default", "value_type"])
        self.assertEqual(setting.__match_args__, ("section", "key", "default", "value_type"))
        self.assertEqual(repr(setting), "IniSetting(section='TEST', key='value', default='fallback', value_type=<class 'str'>)")
        self.assertIs(setting.value_type, str)
        self.assertEqual(setting, definitions.IniSetting("TEST", "value", "fallback", str))
        self.assertEqual(hash(setting), hash(definitions.IniSetting("TEST", "value", "fallback")))
        self.assertEqual(replace(setting, default="other").default, "other")
        with self.assertRaisesRegex(TypeError, "default must match value_type"):
            replace(setting, value_type=int)
        parameters = inspect.signature(definitions.IniSetting).parameters
        self.assertEqual(tuple(parameters), ("section", "key", "default", "value_type"))
        self.assertIs(parameters["value_type"].default, str)
        for name in setting.__match_args__:
            with self.assertRaises(FrozenInstanceError):
                setattr(setting, name, getattr(setting, name))

    def test_invalid_definitions_fail_before_reading_or_storing_fields(self):
        for default, kind in (("fallback", int), (23, str), (True, int), (False, str), (1.5, int), (None, bool)):
            with self.subTest(default=default, kind=kind):
                setting = object.__new__(definitions.IniSetting)
                with patch.object(clnch_ini, "get") as get, patch.object(clnch_ini, "getint") as getint:
                    self.assertRaises(TypeError, definitions.IniSetting.__init__, setting, "TEST", "value", default, kind)
                    self.assertEqual(vars(setting), {})
                    get.assert_not_called()
                    getint.assert_not_called()
                self.assertFalse(clnch_ini.dirty)

    def test_none_default_keeps_read_exception_and_valid_value_type(self):
        for kind in (str, int):
            setting = definitions.IniSetting("TEST", "value", None, kind)
            with self.assertRaises(configparser.NoSectionError):
                setting.get(clnch_ini)
            self.assertFalse(clnch_ini.dirty)
            clnch_ini.set("TEST", "value", "17")
            result = setting.get(clnch_ini)
            self.assertIs(type(result), kind)
            self.assertEqual(result, "17" if kind is str else 17)
            clnch_ini.ini.remove_section("TEST")
            clnch_ini.dirty = False

    def test_missing_present_invalid_and_text_views_keep_original_results(self):
        for setting in self.settings:
            with self.subTest(section=setting.section, key=setting.key):
                if setting.default is None:
                    with self.assertRaises(configparser.NoSectionError):
                        setting.get(clnch_ini)
                else:
                    self.assertEqual(setting.get(clnch_ini), setting.default)
                    self.assertIs(type(setting.get(clnch_ini)), setting.value_type)
                for value in ("", "日本語😀 100%", "invalid", "  +01  ", "0", "1"):
                    setting.set_text(clnch_ini, value)
                    getter = clnch_ini.getint if setting.value_type is int else clnch_ini.get
                    if setting.value_type is int and setting.default is None and value.strip() not in ("+01", "0", "1"):
                        with self.assertRaises(ValueError):
                            setting.get(clnch_ini)
                    else:
                        self.assertEqual(setting.get(clnch_ini), getter(setting.section, setting.key, setting.default))
                    self.assertEqual(setting.get_text(clnch_ini), value)
                clnch_ini.ini.remove_section(setting.section)
        self.assertEqual(definitions.FONT_NAME.get_text(clnch_ini, default=""), "")
        self.assertEqual(definitions.FONT_NAME.get(clnch_ini), "MS Gothic")
        self.assertEqual(definitions.MISC_AUTO_COMPLETE.get_text(clnch_ini), "0")
        self.assertIs(type(definitions.MISC_AUTO_COMPLETE.get(clnch_ini)), int)

    def test_raw_numeric_writes_keep_dirty_and_serialization_semantics(self):
        setting = definitions.FONT_SIZE
        setting.set_text(clnch_ini, "016")
        self.assertTrue(clnch_ini.dirty)
        clnch_ini.dirty = False
        setting.set_text(clnch_ini, "16")
        self.assertTrue(clnch_ini.dirty)
        self.assertEqual(setting.get_text(clnch_ini), "16")
        clnch_ini.dirty = False
        setting.set_text(clnch_ini, "16")
        self.assertFalse(clnch_ini.dirty)
        with patch.object(clnch_ini, "write") as save:
            setting.get(clnch_ini)
            setting.set_text(clnch_ini, "17")
            save.assert_not_called()

    def test_existing_ini_roundtrip_preserves_unknown_and_dynamic_values(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "build") as directory:
            path = Path(directory) / "設定.ini"
            old = ("[FONT]\r\nname = MS Gothic\r\nsize = 016\r\n\r\n"
                   "[COMMANDLINE]\r\nhistory_0 = 日本語;100%\r\n\r\n"
                   "[UNKNOWN]\r\ncustom = keep\r\n\r\n")
            path.write_bytes(old.encode("utf-8"))
            with patch.object(clnch_ini, "ini_filename", str(path)):
                clnch_ini.read()
                self.assertFalse(clnch_ini.dirty)
                self.assertEqual(definitions.FONT_SIZE.get(clnch_ini), 16)
                for setting in self.settings:
                    setting.set_text(clnch_ini, "23" if setting.value_type is int else "日本語 100%")
                for module in DOMAIN_DEFAULTS:
                    for setting in module.SETTINGS.values():
                        setting.set_text(clnch_ini, setting.default)
                clnch_ini.write()
                data = path.read_bytes()
                self.assertIn(b"\n", data)
                self.assertNotIn(b"\r", data)
                clnch_ini.read()
                self.assertFalse(clnch_ini.dirty)
                for setting in self.settings:
                    self.assertEqual(setting.get(clnch_ini), 23 if setting.value_type is int else "日本語 100%")
                for module, (_, defaults) in DOMAIN_DEFAULTS.items():
                    self.assertEqual(module.read(clnch_ini), defaults)
                self.assertEqual(clnch_ini.get("COMMANDLINE", "history_0"), "日本語;100%")
                self.assertEqual(clnch_ini.get("UNKNOWN", "custom"), "keep")

    def test_domain_definitions_derive_from_existing_logical_defaults(self):
        for module, (section, defaults) in DOMAIN_DEFAULTS.items():
            self.assertEqual(module.DEFAULTS, defaults)
            self.assertEqual(module.read(clnch_ini), defaults)
            self.assertEqual(set(module.SETTINGS), set(defaults))
            for name, value in defaults.items():
                setting = module.SETTINGS[name]
                self.assertEqual((setting.section, setting.key), (section, name.lower()))
                self.assertIs(setting.value_type, str)
                expected = str(int(value)) if type(value) is bool else "" if type(value) is tuple else value
                self.assertEqual(setting.default, expected)
                self.assertIs(type(module.read(clnch_ini)[name]), type(value))
        self.assertEqual((clnch_execonfig.MULTI_USER.section, clnch_execonfig.MULTI_USER.key,
                          clnch_execonfig.MULTI_USER.default), ("DATA", "multi_user", "0"))

    def test_altenter_writer_saves_current_fields_and_boolean_encoding(self):
        for properties_first in (False, True):
            settings = dict(DOMAIN_DEFAULTS[clnch_altenterconfig][1], properties_first=properties_first)
            clnch_altenterconfig.write(clnch_ini, settings)
            self.assertEqual(dict(clnch_ini.ini.items("ALT_ENTER")), {
                "action": "none", "executable": "", "arguments": "%param%", "url": "",
                "properties_first": str(int(properties_first)),
            })
            self.assertEqual(clnch_altenterconfig.read(clnch_ini), settings)

    def test_no_direct_static_launcher_accesses_remain(self):
        for path in (ROOT / "clnch").glob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                        and isinstance(node.func.value, ast.Name) and node.func.value.id == "ini"
                        and node.func.attr in ("get", "getint", "set", "setint")
                        and node.args and isinstance(node.args[0], ast.Constant)):
                    self.fail(f"Static INI access bypasses its definition: {path.name}:{node.lineno}")
                if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                        and isinstance(node.func.value, ast.Name) and node.func.value.id == "clnch_ini"
                        and node.func.attr in ("get", "getint", "set", "setint", "remove_option")):
                    continue
                if isinstance(node.args[1], ast.Name):
                    # History mode changes remove enumerated history keys, including sparse indices.
                    self.assertEqual((path.name, node.func.attr, node.args[1].id),
                                     ("clnch_mainwindow.py", "remove_option", "option"))
                else:
                    self.assertIsInstance(node.args[1], ast.JoinedStr, (path.name, node.lineno))
                    self.assertTrue(all(isinstance(v, ast.Constant) and v.value == "history_"
                                        or isinstance(v, ast.FormattedValue) for v in node.args[1].values))
                self.assertEqual(ast.unparse(node.args[0]), "ini_settings.COMMANDLINE_SECTION")

    def test_theme_precedence_choice_fallbacks_and_invalid_values(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "build") as directory:
            themes = Path(directory) / "themes"
            themes.mkdir()
            with (patch.object(ckit_theme.ckit_misc, "getAppExePath", return_value=directory),
                  patch.object(ckit_theme, "ini"), patch.object(ckit_theme, "theme_name")):
                ckit_theme.setTheme("missing", {})
                expected = {
                    "bg": (0, 0, 0), "fg": (255, 255, 255), "caret0": (255, 255, 255),
                    "caret1": (255, 0, 0), "bar_fg": (255, 255, 255),
                    "bar_error_fg": (255, 130, 130), "select_bg": (130, 130, 130),
                    "select_fg": (255, 255, 255), "choice_bg": (130, 130, 130),
                    "choice_fg": (255, 255, 255),
                }
                self.assertEqual(dict(ckit_theme.ini.items("COLOR")),
                                 {key: "(" + ",".join(map(str, value)) + ")" for key, value in expected.items()})
                for key, value in expected.items():
                    self.assertEqual(ckit_theme.getColor(key), value)
                (themes / "test.ini").write_text("[COLOR]\nselect_bg = (1,2,3)\nfg = invalid\n", encoding="utf-8")
                ckit_theme.setTheme("test", {"select_bg": (7, 8, 9), "choice_fg": (4, 5, 6)})
                self.assertEqual(ckit_theme.getColor("choice_bg"), (1, 2, 3))
                self.assertEqual(ckit_theme.getColor("choice_fg"), (4, 5, 6))
                self.assertIsNone(ckit_theme.getColor("fg"))


if TYPE_CHECKING:
    def _check_setting_types() -> None:
        assert_type(definitions.FONT_NAME.get(clnch_ini), str)
        assert_type(definitions.FONT_SIZE.get(clnch_ini), int)
        assert_type(definitions.GEOMETRY_WIDTH.get(clnch_ini), int)
        assert_type(definitions.FONT_SIZE.get_text(clnch_ini), str)
        assert_type(definitions.IniSetting("s", "k", None).get(clnch_ini), str)
        assert_type(definitions.IniSetting("s", "k", None, int).get(clnch_ini), int)
        assert_type(definitions.IniSetting("s", "k", "fallback").get(clnch_ini), str)
        assert_type(definitions.IniSetting("s", "k", 17, int).get(clnch_ini), int)


if __name__ == "__main__":
    unittest.main()
