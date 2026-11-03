"""Exercise the native Line with the bundled Python; no GUI is opened."""
import ctypes
import gc
import sys
import unittest
import weakref
from pathlib import Path

import native_test_support  # noqa: F401  # Select and pin the native build before importing ckit.

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ckit import ckitcore


class NativeLineTests(unittest.TestCase):
    def assert_defaults(self, line):
        self.assertIsNone(line.ctx)
        self.assertIsNone(line.tokens)
        self.assertEqual(line.bg, 0)
        self.assertEqual(line.bookmark, 0)
        self.assertIs(line.modified, False)

    def test_body_and_one_trailing_line_end(self):
        for body in ("", "ascii", "日本語", "a\0b", "\U0001f680", "\ud800", "\udfff", "a\nb"):
            for end in ("", "\r", "\n", "\r\n"):
                text = body + end
                with self.subTest(text=repr(text)):
                    line = ckitcore.Line(text)
                    self.assertEqual(line.s, body)
                    self.assertEqual(line.end, end)
                    self.assert_defaults(line)
        for text, body, end in (("a\r\n\r\n", "a\r\n", "\r\n"),
                                ("a\n\n", "a\n", "\n"), ("a\r\r", "a\r", "\r"),
                                ("a\r\n\0", "a\r\n\0", "")):
            with self.subTest(text=repr(text)):
                line = ckitcore.Line(text)
                self.assertEqual((line.s, line.end), (body, end))

    def test_keyword_and_string_subclass(self):
        class Text(str):
            def __str__(self):
                raise AssertionError("Line must use the Unicode value")

        line = ckitcore.Line(s=Text("日本語\U0001f680\0\r\n"))
        self.assertEqual(line.s, "日本語\U0001f680\0")
        self.assertEqual(line.end, "\r\n")

    def test_invalid_constructor_arguments(self):
        cases = [
            ((), {}), (("a", "b"), {}), ((), {"unknown": "a"}),
            (("a",), {"s": "b"}),
        ]
        cases.extend(((value,), {}) for value in (None, b"text", 1, [], object()))
        for args, kwargs in cases:
            with self.subTest(args=args, kwargs=kwargs), self.assertRaises(TypeError):
                ckitcore.Line(*args, **kwargs)

    def test_attributes_and_independent_flags(self):
        line = ckitcore.Line("body\r\n")
        ctx, tokens = object(), [1, 2]
        line.s = "replacement\n"
        line.ctx = ctx
        line.tokens = tokens
        line.bg = 3
        line.bookmark = 7
        line.modified = True
        for end, expected in (("\r", "\r"), ("\n", "\n"), ("\r\n", "\r\n"),
                              ("", ""), ("prefix\r\n", "\r\n"), ("\n\0", "")):
            with self.subTest(end=repr(end)):
                line.end = end
                self.assertEqual(line.end, expected)
                self.assertEqual(line.s, "replacement\n")
                self.assertIs(line.ctx, ctx)
                self.assertIs(line.tokens, tokens)
                self.assertEqual(line.bg, 3)
                self.assertEqual(line.bookmark, 7)
                self.assertIs(line.modified, True)
        line.bg = 0
        line.bookmark = 0
        line.modified = False
        line.ctx = None
        line.tokens = None
        self.assert_defaults(line)

    def test_integer_attributes_round_trip_and_independent_flags(self):
        line = ckitcore.Line("body\r\n")
        ctx, tokens = object(), [1, 2]
        line.ctx, line.tokens = ctx, tokens
        for end in ("", "\r", "\n", "\r\n"):
            line.end = end
            for modified in (False, True, False):
                line.modified = modified
                for bg in (0, 1, 2, 3, 0):
                    line.bg = bg
                    for bookmark in (*range(8), 0):
                        with self.subTest(end=end, modified=modified, bg=bg, bookmark=bookmark):
                            line.bookmark = bookmark
                            self.assertEqual((line.bg, line.bookmark, line.modified),
                                             (bg, bookmark, modified))
                            self.assertEqual((line.s, line.end), ("body", end))
                            self.assertIs(line.ctx, ctx)
                            self.assertIs(line.tokens, tokens)

    def test_integer_attributes_accept_bool_and_int_subclasses(self):
        class Integer(int):
            def __int__(self):
                raise AssertionError("must use the stored integer")

            def __index__(self):
                raise AssertionError("must use the stored integer")

        line = ckitcore.Line("body")
        for name, maximum in (("bg", 3), ("bookmark", 7)):
            for value in (False, True, Integer(0), Integer(maximum)):
                with self.subTest(name=name, value=value):
                    setattr(line, name, value)
                    self.assertEqual(getattr(line, name), value)
                    self.assertIs(type(getattr(line, name)), int)

    def test_invalid_integer_attributes_preserve_state_and_allow_recovery(self):
        class IndexOnly:
            def __index__(self):
                raise AssertionError("must reject non-int without conversion")

        class IntOnly:
            def __int__(self):
                raise AssertionError("must reject non-int without conversion")

        class Integer(int):
            pass

        long_max = (1 << (ctypes.sizeof(ctypes.c_long) * 8 - 1)) - 1
        line = ckitcore.Line("body\r\n")
        ctx, tokens = object(), [1, 2]
        line.ctx, line.tokens = ctx, tokens
        for name, maximum in (("bg", 3), ("bookmark", 7)):
            cases = [(ValueError, value) for value in
                     (-1, maximum + 1, maximum + 2, 16, 1 << 20,
                      -long_max - 1, long_max, Integer(-1), Integer(maximum + 1))]
            cases.extend((OverflowError, value) for value in
                         (-long_max - 2, long_max + 1, -(1 << 1000), 1 << 1000,
                          Integer(1 << 1000)))
            cases.extend((TypeError, value) for value in
                         (None, 1.0, "1", b"1", [], object(), IndexOnly(), IntOnly()))
            for end in ("", "\r", "\n", "\r\n"):
                line.end = end
                for modified in (False, True):
                    for error, value in cases:
                        with self.subTest(name=name, value=value, end=end, modified=modified):
                            line.bg, line.bookmark, line.modified = 2, 5, modified
                            with self.assertRaises(error) as caught:
                                setattr(line, name, value)
                            self.assertIs(type(caught.exception), error)
                            self.assertEqual((line.bg, line.bookmark, line.modified), (2, 5, modified))
                            self.assertEqual((line.s, line.end), ("body", end))
                            self.assertIs(line.ctx, ctx)
                            self.assertIs(line.tokens, tokens)
                            setattr(line, name, maximum)
                            self.assertEqual((line.bg, line.bookmark, line.modified),
                                             (maximum, 5, modified) if name == "bg"
                                             else (2, maximum, modified))

    def test_invalid_attributes_leave_values_unchanged(self):
        line = ckitcore.Line("body\r\n")
        for name, value in (("end", None), ("end", b"\n"), ("bg", "1"),
                            ("bookmark", None), ("modified", 1)):
            with self.subTest(name=name, value=value), self.assertRaises(TypeError):
                setattr(line, name, value)
        with self.assertRaises(AttributeError):
            _ = line.unknown
        with self.assertRaises(AttributeError):
            line.unknown = 1
        self.assertEqual(line.s, "body")
        self.assertEqual(line.end, "\r\n")
        self.assert_defaults(line)

    def test_reinitialization_resets_and_releases_attributes(self):
        class Value:
            pass

        line = ckitcore.Line("old\r")
        values = [Value(), Value(), Value()]
        refs = [weakref.ref(value) for value in values]
        line.s, line.ctx, line.tokens = values
        del values
        line.bg, line.bookmark, line.modified = 3, 7, True
        ckitcore.Line.__init__(line, s="new\U0001f680\r\n")
        gc.collect()
        self.assertTrue(all(ref() is None for ref in refs))
        self.assertEqual(line.s, "new\U0001f680")
        self.assertEqual(line.end, "\r\n")
        self.assert_defaults(line)

    def test_failed_reinitialization_preserves_state(self):
        line = ckitcore.Line("body\r\n")
        ctx, tokens = object(), [1]
        line.ctx, line.tokens = ctx, tokens
        line.bg, line.bookmark, line.modified = 2, 5, True
        with self.assertRaises(TypeError):
            ckitcore.Line.__init__(line, None)
        self.assertEqual(line.s, "body")
        self.assertEqual(line.end, "\r\n")
        self.assertIs(line.ctx, ctx)
        self.assertIs(line.tokens, tokens)
        self.assertEqual((line.bg, line.bookmark, line.modified), (2, 5, True))

    def test_input_reference_count_and_destruction(self):
        class Value:
            pass

        text = "日本語\U0001f680\0" + str(id(self)) + "\n"
        count = sys.getrefcount(text)
        for _ in range(100):
            line = ckitcore.Line(text)
            value = Value()
            ref = weakref.ref(value)
            line.ctx = line.tokens = value
            del value, line
            self.assertIsNone(ref())
        self.assertEqual(sys.getrefcount(text), count)


if __name__ == "__main__":
    unittest.main()
