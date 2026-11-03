"""Local command, syntax-token and key-binding boundary regressions."""
import contextlib
import ctypes
import io
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from native_test_support import RUN_DIR

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "clnch"), str(RUN_DIR / "lib")]

import clnch_text

import ckit
from ckit import ckit_textwidget

clnch_text.initialize()


class CommandSequenceTests(unittest.TestCase):
    def test_decline_then_implicit_success_stops_and_preserves_shared_info(self):
        info = ckit.CommandInfo()
        info.args = ["日本語", "two words"]
        info.arg_string = '日本語  "two words"'
        info.mod = ckit.MODKEY_CTRL | ckit.MODKEY_SHIFT
        info.custom = object()
        arguments, custom = info.args, info.custom
        calls = []

        def decline(received):
            self.assertIs(received, info)
            self.assertIs(received.result, True)
            received.args.append("from first")
            received.extra = "retained"
            received.result = False
            calls.append("decline")
            return True

        def succeed(received):
            self.assertIs(received, info)
            self.assertIs(received.result, True)
            self.assertIs(received.args, arguments)
            self.assertEqual(received.args, ["日本語", "two words", "from first"])
            self.assertEqual(received.arg_string, '日本語  "two words"')
            self.assertEqual(received.mod, ckit.MODKEY_CTRL | ckit.MODKEY_SHIFT)
            self.assertIs(received.custom, custom)
            self.assertEqual(received.extra, "retained")
            calls.append("success")
            return False

        later = Mock()
        self.assertIsNone(ckit.CommandSequence(decline, succeed, later)(info))
        self.assertEqual(calls, ["decline", "success"])
        self.assertIs(info.result, True)
        later.assert_not_called()

    def test_supplied_false_is_reset_before_first_attempt(self):
        info = ckit.CommandInfo()
        info.result = False
        states = []
        ckit.CommandSequence(lambda received: states.append(received.result))(info)
        self.assertEqual(states, [True])
        self.assertIs(info.result, True)

    def test_all_decline_and_empty_sequence(self):
        info = ckit.CommandInfo()
        states = []

        def decline(received):
            states.append(received.result)
            received.result = False

        self.assertIsNone(ckit.CommandSequence(decline, decline)(info))
        self.assertEqual(states, [True, True])
        self.assertIs(info.result, False)
        before = vars(info).copy()
        self.assertIsNone(ckit.CommandSequence()(info))
        self.assertEqual(vars(info), before)
        self.assertIsNone(ckit.CommandSequence()())

    def test_default_info_and_exception_propagation(self):
        failure = RuntimeError("command failed")
        received = []

        def fail(info):
            self.assertEqual((info.args, info.arg_string, info.mod, info.result), ([], None, 0, True))
            received.append(info)
            info.result = False
            raise failure

        later = Mock()
        with self.assertRaises(RuntimeError) as raised:
            ckit.CommandSequence(fail, later)()
        self.assertIs(raised.exception, failure)
        self.assertIs(received[0].result, False)
        later.assert_not_called()


class SyntaxTokenTests(unittest.TestCase):
    def document(self):
        doc = ckit.Document(None, ckit.TextMode())
        doc.readFile(io.BytesIO(b"first\nsecond\nthird"))
        doc.updateSyntaxContext()
        doc.lexer.lex = Mock(wraps=doc.lexer.lex)
        return doc

    def test_empty_and_reversed_ranges_leave_tokens_and_dirty_position(self):
        for start, stop in ((1, 1), (2, 1), (3, None), (4, 9), (0, 0)):
            with self.subTest(start=start, stop=stop):
                doc = self.document()
                before = [(line.ctx, line.tokens) for line in doc.lines]
                self.assertIsNone(doc.updateSyntaxTokens(start, stop))
                self.assertEqual([(line.ctx, line.tokens) for line in doc.lines], before)
                self.assertEqual(doc.lex_token_dirty_top, 0)
                doc.lexer.lex.assert_not_called()

    def test_final_line_and_dirty_coverage(self):
        for start, dirty, expected in ((0, 0, None), (2, 2, None), (2, 0, 0)):
            with self.subTest(start=start, dirty=dirty):
                doc = self.document()
                doc.lex_token_dirty_top = dirty
                doc.updateSyntaxTokens(start, 99)
                self.assertEqual(doc.lex_token_dirty_top, expected)
                self.assertEqual(doc.lexer.lex.call_count, 3 - start)
                for line in doc.lines[start:]:
                    self.assertEqual(ckit_textwidget.Token.unpack(line.tokens),
                                     [(0, ckit_textwidget.Token_Text)])

    def test_dirty_short_circuit_and_partial_range(self):
        for dirty, stop in ((None, 3), (2, 2), (0, 2)):
            with self.subTest(dirty=dirty, stop=stop):
                doc = self.document()
                doc.lex_token_dirty_top = dirty
                doc.updateSyntaxTokens(stop=stop)
                self.assertEqual(doc.lex_token_dirty_top, dirty)
                self.assertEqual(doc.lexer.lex.call_count, 2 if dirty == 0 else 0)
                self.assertIsNone(doc.lines[-1].tokens)

    def test_max_lex_counts_only_missing_tokens_and_resumes(self):
        for limit, analyzed in ((0, 1), (1, 1), (2, 2), (None, 2)):
            with self.subTest(limit=limit):
                doc = self.document()
                cached = ckit_textwidget.Token.pack([(0, ckit_textwidget.Token_Keyword)])
                doc.lines[0].tokens = cached
                doc.updateSyntaxTokens(max_lex=limit)
                self.assertIs(doc.lines[0].tokens, cached)
                self.assertEqual(doc.lexer.lex.call_count, analyzed)
                self.assertEqual(doc.lex_token_dirty_top, None if analyzed == 2 else 0)
                doc.updateSyntaxTokens()
                self.assertEqual(doc.lexer.lex.call_count, 2)
                self.assertIsNone(doc.lex_token_dirty_top)


class KeyBoundaryTests(unittest.TestCase):
    def setUp(self):
        for name in ("str_vk_table", "vk_str_table", "str_vk_table_common", "vk_str_table_common"):
            change = patch.object(ckit.KeyEvent, name, getattr(ckit.KeyEvent, name).copy())
            change.start()
            self.addCleanup(change.stop)

    def test_invalid_key_strings_do_not_register_or_replace_bindings(self):
        ckit.Keymap.init()
        keymap = ckit.Keymap()
        original, replacement = Mock(), Mock()
        keymap["C-F9"] = original
        before = keymap.table.copy()
        for invalid in ("", "NoSuchKey", "NoModifier-F9", "C-", "C-(bad)"):
            with self.subTest(invalid=invalid), contextlib.redirect_stdout(io.StringIO()) as output:
                keymap[invalid] = replacement
                self.assertEqual(keymap.table, before)
                self.assertNotIn(None, keymap.table)
                self.assertTrue(output.getvalue())
                with self.assertRaises(KeyError):
                    _ = keymap[invalid]
                del keymap[invalid]
                self.assertIs(keymap["C-F9"], original)
        for invalid_type in (None, 1, object()):
            with self.subTest(invalid_type=invalid_type), self.assertRaises(TypeError):
                keymap[invalid_type] = replacement

    def test_key_event_equality_handles_unrelated_types_and_subclasses(self):
        event = ckit.KeyEvent(65, 0)
        for other in (None, 65, "A", object(), Mock(vk=65, mod=0, extra=None)):
            with self.subTest(other=other):
                self.assertIs(event == other, False)
                self.assertIs(event != other, True)

        class DerivedEvent(ckit.KeyEvent):
            pass

        self.assertIs(event == DerivedEvent(65, 0), True)
        self.assertIs(DerivedEvent(65, 1) == event, False)

    def test_keyboard_reinitialization_keeps_common_tables_clean(self):
        event = ckit.KeyEvent
        common_names, common_codes = event.str_vk_table_common.copy(), event.vk_str_table_common.copy()
        for keyboard_type in (7, 4, 7, 4):
            with self.subTest(keyboard_type=keyboard_type):
                names = event.str_vk_table_jpn if keyboard_type == 7 else event.str_vk_table_std
                codes = event.vk_str_table_jpn if keyboard_type == 7 else event.vk_str_table_std
                with patch.object(ctypes.windll.user32, "GetKeyboardType", return_value=keyboard_type):
                    event.initTables()
                self.assertEqual(event.str_vk_table_common, common_names)
                self.assertEqual(event.vk_str_table_common, common_codes)
                self.assertIsNot(event.str_vk_table, event.str_vk_table_common)
                self.assertIsNot(event.vk_str_table, event.vk_str_table_common)
                self.assertEqual(event.str_vk_table, common_names | names)
                self.assertEqual(event.vk_str_table, common_codes | codes)
                keymap, handler = ckit.Keymap(), Mock()
                for name, vk in (common_names | names).items():
                    self.assertEqual(event.fromString("C-S-" + name),
                                     event(vk, ckit.MODKEY_CTRL | ckit.MODKEY_SHIFT))
                    keymap["C-S-" + name] = handler
                    self.assertIs(keymap[event(vk, ckit.MODKEY_CTRL | ckit.MODKEY_SHIFT)], handler)
                for vk, name in (common_codes | codes).items():
                    self.assertEqual(event.vkToStr(vk), name)
                if keyboard_type != 7:
                    self.assertEqual(event.vkToStr(ckit.VK_OEM_102), "(226)")

    def test_valid_binding_aliases_numeric_keys_and_extra_replacement(self):
        ckit.Keymap.init()
        keymap = ckit.Keymap()
        first, second = Mock(), Mock()
        keymap[" ctrl - s - f9 "] = first
        self.assertIs(keymap[ckit.KeyEvent(ckit.VK_F9, ckit.MODKEY_CTRL | ckit.MODKEY_SHIFT)], first)
        keymap["C-S-(120)"] = second
        self.assertIs(keymap["C-S-F9"], second)
        keymap[ckit.KeyEvent(ckit.VK_A, 0, "one")] = first
        keymap[ckit.KeyEvent(ckit.VK_A, 0, "two")] = second
        self.assertEqual(len(keymap.table), 3)
        keymap["A"] = second
        self.assertEqual(len(keymap.table), 2)
        self.assertIs(keymap[ckit.KeyEvent(ckit.VK_A, 0, "any")], second)
        del keymap["A"]
        del keymap["A"]
        with self.assertRaises(KeyError):
            _ = keymap["A"]
        self.assertIs(keymap["C-S-F9"], second)


if __name__ == "__main__":
    unittest.main()
