"""Command data checks without native modules, widgets or program launches; run with -B."""
import copy
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "clnch"))
import clnch_cmdstore as store
import clnch_strings as strings


class CommandDataTests(unittest.TestCase):
    def test_path_quotes_are_removed_only_as_one_complete_pair(self):
        for path in (r"C:\two words\file.exe", "C:\\日本語 folder\\", "relative file.txt"):
            self.assertEqual(store.unquote_path('"' + path + '"'), path)
            for unchanged in (path, '"' + path, path + '"', '""' + path + '""',
                              '"' + path + '";arguments', '"' + path + '"tail"'):
                self.assertEqual(store.unquote_path(unchanged), unchanged)

    def test_link_policy_keeps_absolute_names_uris_and_rejects_relative_windows_paths(self):
        for link in (r"C:\Tools\tool.exe", "C:/Tools/tool.exe", r"\\server\share\folder",
                     '"C:\\two words\\tool.exe"', "notepad.exe", "np", "missing.exe",
                     "https://example.org/a/b", "ms-settings:display", "shell:Personal"):
            with self.subTest(link=link):
                store.validate_link(link, "tool")
        for link in (r"tools\tool.exe", "tools/tool.exe", r".\tool.exe", "../folder",
                     r"\tools\tool.exe", "/tools/tool.exe", "C:tools/tool.exe", "C:",
                     ".", "..", '"tools\\two words.exe"'):
            with self.subTest(link=link), self.assertRaises(ValueError) as raised:
                store.validate_link(link, "alias")
            self.assertEqual(str(raised.exception), strings.COMMAND_RELATIVE_LINK.format(name="alias", link=link))

    def test_relative_links_load_and_roundtrip_without_global_rejection(self):
        data = {"bad": {"target": {"link": "tools/tool.exe"}}, "good": {"target": {"link": "notepad.exe"}}}
        self.path.write_text(json.dumps(data), encoding="utf-8")
        original = self.path.read_bytes()
        for validation in ("runtime", "editor", None):
            with self.subTest(validation=validation):
                self.assertEqual(store.load_commands(self.path, validation=validation), data)
                self.assertEqual(self.path.read_bytes(), original)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "commands.json"

    def test_utf8_bom_is_accepted_on_load(self):
        self.path.write_bytes(b"\xef\xbb\xbf" + json.dumps({"Tool": {}}).encode("utf-8"))
        self.assertEqual(store.load_commands(self.path), {"tool": {}})

    def test_crlf_file_is_read_and_saved_as_lf_preserving_argument_newlines(self):
        data = {"tool": {"target": {"link": "notepad.exe", "args": "日本語\r\nnext\nlast"}}}
        self.path.write_bytes(json.dumps(data, ensure_ascii=False, indent=2).replace("\n", "\r\n").encode("utf-8"))
        loaded = store.load_commands(self.path)
        self.assertEqual(loaded, data)
        saved = store.save_commands(self.path, loaded)
        output = self.path.read_bytes()
        self.assertIn(b"\n", output)
        self.assertNotIn(b"\r", output)
        self.assertFalse(output.startswith(b"\xef\xbb\xbf"))
        self.assertEqual(json.loads(output), saved)
        self.assertEqual(saved["tool"]["target"]["args"], data["tool"]["target"]["args"])

    def test_load_is_sparse_case_insensitive_and_never_writes(self):
        data = {"Tool": {"target": {"link": "first.exe"}},
                "Other": {"on_shift": {"link": "last.exe"}}, "": {}}
        self.path.write_text(json.dumps(data), encoding="utf-8")
        original = self.path.read_bytes()
        with patch.object(store.tempfile, "NamedTemporaryFile", side_effect=AssertionError("unexpected write")):
            for validation in ("runtime", "editor", None):
                with self.subTest(validation=validation):
                    loaded = store.load_commands(self.path, validation=validation)
                    self.assertEqual(loaded, {"tool": data["Tool"], "other": data["Other"], "": {}})
                    self.assertEqual(list(loaded), ["tool", "other", ""])
                    self.assertEqual(self.path.read_bytes(), original)

    def test_duplicate_root_names_are_rejected_in_every_mode_and_language(self):
        import clnch_strings_en
        import clnch_strings_ja
        for first, second in (("tool", "tool"), ("Tool", "tool"), ("tool", "TOOL"),
                              ("", ""), ("İ", "i\u0307")):
            # Keep the repeated keys in raw JSON; a Python dict would erase them.
            contents = ('{' + json.dumps(first) + ': {"target": {"link": "first.exe"}}, '
                        '"other": {}, ' + json.dumps(second) + ': {"target": {"link": "last.exe"}}}')
            self.path.write_text(contents, encoding="utf-8")
            original = self.path.read_bytes()
            for language in (clnch_strings_ja, clnch_strings_en):
                with patch.object(store, "strings", language):
                    for validation in ("runtime", "editor", None):
                        with self.subTest(first=first, second=second, language=language.__name__, validation=validation):
                            with self.assertRaises(ValueError) as raised:
                                store.load_commands(self.path, validation=validation)
                            self.assertEqual(str(raised.exception),
                                             language.COMMAND_NAME_DUPLICATE.format(first=first, second=second))
                            self.assertEqual(self.path.read_bytes(), original)

    def test_distinct_lower_names_are_not_compared_with_casefold(self):
        data = {"Straße": {"target": {"link": "first.exe"}},
                "STRASSE": {"target": {"link": "second.exe"}}}
        self.path.write_text(json.dumps(data), encoding="utf-8")
        for validation in ("runtime", "editor", None):
            with self.subTest(validation=validation):
                self.assertEqual(store.load_commands(self.path, validation=validation),
                                 {"straße": data["Straße"], "strasse": data["STRASSE"]})

    def test_nested_keys_are_not_command_names_and_keep_normal_json_semantics(self):
        contents = ('{"target": {"target": {"link": "first.exe"}, '
                    '"target": {"link": "old.exe", "link": "last.exe"}, '
                    '"on_ctrl": {"link": "ctrl.exe"}}, "link": {"target": {"link": "other.exe"}}}')
        self.path.write_text(contents, encoding="utf-8")
        expected = json.loads(contents)
        for validation in ("runtime", "editor", None):
            with self.subTest(validation=validation):
                self.assertEqual(store.load_commands(self.path, validation=validation), expected)
                self.assertEqual(self.path.read_text(encoding="utf-8"), contents)

    def test_args_roundtrip_and_duplicate_preserve_strings_for_all_modifiers(self):
        arguments = ('', '"固定 文書.txt" --flag', '--before %param% --after', '"C:\\tail\\"')
        data = {"tool": {modifier: {"link": "tool.exe", "args": value}
                         for modifier, value in zip(store.MODIFIERS, arguments)}}
        saved = store.save_commands(self.path, data)
        for validation in ("runtime", "editor"):
            with self.subTest(validation=validation):
                self.assertEqual(store.load_commands(self.path, validation=validation), saved)
        copied, name = store.duplicate_command(saved, "tool")
        saved_copy = store.save_commands(self.path, copied, saved)
        self.assertEqual(store.load_commands(self.path), saved_copy)
        for modifier, value in zip(store.MODIFIERS, arguments):
            self.assertEqual(saved_copy[name][modifier]["args"], value)
            self.assertNotIn("arg", saved_copy[name][modifier])

    def test_names_and_zero_actions_in_both_languages(self):
        import clnch_strings_en
        import clnch_strings_ja
        valid_names = ("", "foo", "foo_bar", "foo-bar", "disabled", "日本語", "tool-name_1.!")
        for language in (clnch_strings_ja, clnch_strings_en):
            with patch.object(store, "strings", language):
                for name in valid_names + (";", "a;b", "a;", ";b", '"a;b"') + (" foo", "foo ", " foo ", "foo bar", "foo \u00a0bar",
                        "foo\tbar", "foo\nbar", "foo\u3000bar", " \u00a0 "):
                    for actions in ({}, {"target": {"link": "tool.exe", "args": "a;b"}}):
                        data = {name: actions}
                        self.path.write_text(json.dumps(data), encoding="utf-8")
                        original = self.path.read_bytes()
                        for validation in ("runtime", "editor", None):
                            with self.subTest(language=language.__name__, name=name, actions=actions, validation=validation):
                                if name not in valid_names and validation is not None:
                                    with self.assertRaises(ValueError) as raised:
                                        store.load_commands(self.path, validation=validation)
                                    self.assertEqual(str(raised.exception), language.COMMAND_NAME_ERROR.format(name=name))
                                else:
                                    self.assertEqual(store.load_commands(self.path, validation=validation), data)
                                self.assertEqual(self.path.read_bytes(), original)

    def test_duplicate_rejects_invalid_name_without_mutating_snapshot(self):
        for name in ("bad;name",) + (" foo", "foo ", " foo ", "foo bar", "foo \u00a0bar",
                "foo\tbar", "foo\nbar", "foo\u3000bar", " \u00a0 "):
            with self.subTest(name=name):
                data = {name: {}, "good": {}}
                with self.assertRaises(ValueError) as raised:
                    store.duplicate_command(data, name)
                self.assertEqual(str(raised.exception), strings.COMMAND_NAME_ERROR.format(name=name))
                self.assertEqual(data, {name: {}, "good": {}})

    def test_old_arg_is_rejected_as_unknown_even_alongside_args(self):
        for modifier in store.MODIFIERS:
            for extra in ({}, {"args": "new"}):
                data = {"tool": {modifier: {"link": "tool.exe", "arg": "old", **extra}}}
                self.path.write_text(json.dumps(data), encoding="utf-8")
                original = self.path.read_bytes()
                for validation in ("runtime", "editor"):
                    expected = (strings.EDITOR_ACTION_UNKNOWN.format(name="tool") if validation == "editor"
                                else strings.ACTION_UNKNOWN.format(location="tool." + modifier))
                    with self.subTest(modifier=modifier, extra=extra, validation=validation):
                        with self.assertRaises(ValueError) as raised:
                            store.load_commands(self.path, validation=validation)
                        self.assertEqual(str(raised.exception), expected)
                        self.assertEqual(self.path.read_bytes(), original)

    def test_missing_empty_and_invalid_json_remain_distinct(self):
        for validation in ("runtime", "editor", None):
            with self.subTest(validation=validation):
                self.assertEqual(store.load_commands(self.path, validation=validation), {})
        self.assertFalse(self.path.exists())
        for contents, failure in (("", json.JSONDecodeError), ("{broken", json.JSONDecodeError)):
            self.path.write_text(contents, encoding="utf-8")
            for validation in ("runtime", "editor", None):
                with self.subTest(contents=contents, validation=validation), self.assertRaises(failure):
                    store.load_commands(self.path, validation=validation)
            self.assertEqual(self.path.read_text(encoding="utf-8"), contents)
        self.path.write_text("{}", encoding="utf-8")
        self.assertEqual(store.load_commands(self.path), {})

    def test_read_failure_is_propagated_for_each_caller(self):
        self.path.write_text("{}", encoding="utf-8")
        for validation in ("runtime", "editor", None):
            with self.subTest(validation=validation), \
                    patch("builtins.open", side_effect=PermissionError("locked")), \
                    self.assertRaisesRegex(PermissionError, "locked"):
                store.load_commands(self.path, validation=validation)
        self.assertEqual(self.path.read_bytes(), b"{}")

    def test_failed_metadata_lookup_is_not_treated_as_missing_json(self):
        for validation in ("runtime", "editor", None):
            with self.subTest(validation=validation), \
                    patch.object(store.os.path, "exists", return_value=False), \
                    patch("builtins.open", side_effect=PermissionError("access denied")), \
                    self.assertRaisesRegex(PermissionError, "access denied"):
                store.load_commands(self.path, validation=validation)

    def test_list_can_display_names_with_invalid_actions(self):
        data = {"Bad": {"target": "legacy.exe"}, "Other": {"unknown": {}}}
        self.path.write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(store.load_commands(self.path, validation=None),
                         {name.lower(): actions for name, actions in data.items()})
        for validation in ("runtime", "editor"):
            with self.subTest(validation=validation), self.assertRaises(ValueError):
                store.load_commands(self.path, validation=validation)

    def test_root_error_contract_is_preserved(self):
        for data in ([], None, "legacy", 1):
            with self.subTest(data=data):
                self.path.write_text(json.dumps(data), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, strings.COMMAND_OBJECT_ERROR):
                    store.load_commands(self.path)
                for validation in ("editor", None):
                    with self.subTest(validation=validation), self.assertRaises(AttributeError):
                        store.load_commands(self.path, validation=validation)

    def test_schema_and_diagnostic_order_in_both_languages(self):
        spec = importlib.util.spec_from_file_location("store_strings_en", ROOT / "clnch/clnch_strings_en.py")
        assert spec is not None and spec.loader is not None
        english = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(english)
        for language in (strings, english):
            cases = (
                ("legacy", language.COMMAND_FORMAT_ERROR.format(name="Tool"),
                 language.COMMAND_FORMAT_ERROR.format(name="Tool")),
                ({"unknown": {}}, language.COMMAND_FORMAT_ERROR.format(name="Tool"),
                 language.COMMAND_FORMAT_ERROR.format(name="Tool")),
                ({"target": "legacy"}, language.ACTION_FORMAT_ERROR.format(name="Tool.target"),
                 language.ACTION_FORMAT_ERROR.format(name="Tool")),
                ({"target": {}}, language.ACTION_FORMAT_ERROR.format(name="Tool.target"),
                 language.ACTION_FORMAT_ERROR.format(name="Tool")),
                ({"target": {"link": 1}}, language.ACTION_VALUE_ERROR.format(location="Tool.target", field="link"),
                 language.ACTION_FORMAT_ERROR.format(name="Tool")),
                ({"target": {"link": 1, "unknown": ""}}, language.ACTION_UNKNOWN.format(location="Tool.target"),
                 language.ACTION_FORMAT_ERROR.format(name="Tool")),
                ({"target": {"link": "", "unknown": ""}}, language.ACTION_UNKNOWN.format(location="Tool.target"),
                 language.EDITOR_ACTION_UNKNOWN.format(name="Tool")),
                ({"target": {"link": "", "view_mode": "invalid"}}, language.ACTION_VIEW_ERROR.format(location="Tool.target"),
                 language.EDITOR_VIEW_ERROR.format(name="Tool")),
            )
            cases += tuple(
                ({"on_shift": {"link": "", field: None}},
                 language.ACTION_VALUE_ERROR.format(location="Tool.on_shift", field=field),
                 language.EDITOR_ACTION_VALUE.format(name="Tool"))
                for field in ("args", "workdir", "view_mode")
            )
            with patch.object(store, "strings", language):
                for actions, runtime_error, editor_error in cases:
                    for editor, expected in ((False, runtime_error), (True, editor_error)):
                        with self.subTest(language=language.__name__, actions=actions, editor=editor):
                            with self.assertRaises(ValueError) as raised:
                                store.validate_commands({"Tool": actions}, editor=editor)
                            self.assertEqual(str(raised.exception), expected)

    def test_valid_actions_are_not_mutated_or_completed_by_validation(self):
        data = {"": {}, "Tool": {modifier: {"link": "", "view_mode": mode}
                for modifier, mode in zip(store.MODIFIERS, (*store.VIEW_MODES, "normal"))}}
        original = copy.deepcopy(data)
        for editor in (False, True):
            self.assertIs(store.validate_commands(data, editor=editor), data)
            self.assertEqual(data, original)

    def test_normalization_sorts_names_and_only_completes_registered_actions(self):
        data = {"z": {}, "A": {"on_ctrl": {"link": "tool.exe", "args": " spaced "}}, "": {}}
        original = copy.deepcopy(data)
        result = store.normalize_commands(data)
        self.assertEqual(list(result), ["", "A", "z"])
        self.assertEqual(result["A"], {"on_ctrl": {"link": "tool.exe", "args": " spaced ",
                                                "workdir": "", "view_mode": "normal"}})
        self.assertEqual(data, original)
        self.assertIsNot(result["A"]["on_ctrl"], data["A"]["on_ctrl"])

    def test_duplicate_returns_independent_actions_and_keeps_original_snapshot(self):
        data = {"tool": {"target": {"link": "original.exe"}}, "tool_copy_1": {}}
        original = copy.deepcopy(data)
        result, name = store.duplicate_command(data, "tool")
        self.assertEqual(name, "tool_copy_2")
        self.assertEqual(result[name], data["tool"])
        result[name]["target"]["link"] = "changed.exe"
        self.assertEqual(data, original)
        self.assertEqual(set(data), {"tool", "tool_copy_1"})


if __name__ == "__main__":
    unittest.main()
