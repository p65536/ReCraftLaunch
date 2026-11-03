"""mmap newline boundaries without importing the GUI toolkit or native modules."""
import contextlib
import importlib.util
import itertools
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

spec = importlib.util.spec_from_file_location("hugefile", Path(__file__).resolve().parent.parent / "ckit/ckit_hugefile.py")
assert spec is not None and spec.loader is not None
hugefile = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hugefile)
HugeTextFile = hugefile.HugeTextFile


class HugeTextFileTests(unittest.TestCase):
    def check_lines(self, encoding, prefix, lines):
        with tempfile.TemporaryFile() as fd:
            content = prefix + "".join(lines).encode(encoding)
            fd.write(content)
            fd.flush()
            with contextlib.closing(HugeTextFile(fd.fileno(), encoding, len(prefix))) as reader:
                self.assertEqual(reader.line_pos, [len(prefix)])
                scanner = Mock(wraps=reader.line_end_re_object)
                reader.line_end_re_object = scanner
                for index in reversed(range(len(lines))):
                    self.assertEqual(reader.getLine(index), lines[index].encode(encoding))
                count = scanner.finditer.call_count
                for index, line in enumerate(lines):
                    self.assertEqual(reader.getLine(index), line.encode(encoding))
                for index in (len(lines), len(lines) + 10):
                    with self.assertRaises(IndexError):
                        reader.getLine(index)
                self.assertEqual(scanner.finditer.call_count, count)
                for args, _ in scanner.finditer.call_args_list:
                    self.assertIs(args[0], reader.mm)
                    self.assertLessEqual(args[2] - args[1], 65536 + 3)
            self.assertTrue(reader.mm.closed)
            self.assertFalse(fd.closed)
            fd.seek(0)
            self.assertEqual(fd.read(), content)

    def test_utf16_unaligned_newline_patterns_and_real_endings(self):
        for encoding, confusing, bom in (
            ("utf-16-le", "\u0a00\u0100\u0d00\u0100\u0d00\u0a00\u0100", b"\xff\xfe"),
            ("utf-16-be", "\u0100\u0a01\u0100\u0d01\u0100\u0d00\u0a01", b"\xfe\xff"),
        ):
            for prefix in (b"", bom, b"odd"):
                for ending in ("", "\r", "\n", "\r\n"):
                    lines = [confusing + ending, ""] if ending else [confusing]
                    with self.subTest(encoding=encoding, prefix=prefix, ending=ending):
                        self.check_lines(encoding, prefix, lines)
                with self.subTest(encoding=encoding, prefix=prefix, mixed=True):
                    self.check_lines(encoding, prefix, [confusing + "\r\n", "\n", "🙂\r", confusing])

    def test_utf16_false_and_real_newlines_near_block_boundaries(self):
        for encoding, confusing in (("utf-16-le", "\u0d00\u0a00\u0100"),
                                    ("utf-16-be", "\u0100\u0d00\u0a01")):
            for prefix in (b"", b"\xff\xfe" if encoding.endswith("le") else b"\xfe\xff", b"odd"):
                for delta in range(-6, 7, 2):
                    for ending in ("\r", "\n", "\r\n"):
                        with self.subTest(encoding=encoding, prefix=prefix, delta=delta, ending=ending):
                            first = "x" * ((65536 + delta) // 2) + confusing + ending
                            self.check_lines(encoding, prefix, [first, "y" * 70000 + ending, "tail"])
                            first = "x" * ((65536 + delta) // 2) + ending
                            self.check_lines(encoding, prefix, [first, confusing + ending, ""])

    def test_utf16_adjacent_code_units_do_not_hide_real_newlines(self):
        characters = "\x00\u0001\u0100\u0a00\u0d00\u0a01\u0d01🙂"
        lines = [a + b + ending for a, b in itertools.product(characters, repeat=2)
                 for ending in ("\r", "\n", "\r\n")]
        lines.append("tail")
        for encoding in ("utf-16-le", "utf-16-be"):
            with self.subTest(encoding=encoding):
                self.check_lines(encoding, b"odd", lines)

    def test_single_byte_newlines_and_final_lines(self):
        for encoding in ("utf-8", "cp932"):
            for prefix in (b"", b"prefix"):
                for lines in (["日本\r\n", "\r", "x\n", "tail"], ["one\n", ""], ["tail"], [""]):
                    if lines == [""] and not prefix:
                        continue  # An empty file cannot be memory mapped.
                    with self.subTest(encoding=encoding, prefix=prefix, lines=lines):
                        self.check_lines(encoding, prefix, lines)

    def test_utf16_lookahead_is_bounded_and_cached(self):
        for encoding in ("utf-16-le", "utf-16-be"):
            with self.subTest(encoding=encoding), tempfile.TemporaryFile() as fd:
                fd.write(("line\r\n" * 100000).encode(encoding))
                fd.flush()
                with contextlib.closing(HugeTextFile(fd.fileno(), encoding, 0)) as reader:
                    scanner = Mock(wraps=reader.line_end_re_object)
                    reader.line_end_re_object = scanner
                    self.assertEqual(reader.getLine(0), "line\r\n".encode(encoding))
                    self.assertEqual(scanner.finditer.call_count, 1)
                    self.assertLessEqual(reader.line_pos[-1], 65536 + 3)
                    for index in (0, 2, 1):
                        self.assertEqual(reader.getLine(index), "line\r\n".encode(encoding))
                    self.assertEqual(scanner.finditer.call_count, 1)


if __name__ == "__main__":
    unittest.main()
