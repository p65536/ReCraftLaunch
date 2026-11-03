"""Check LF defaults, encoding rules, and the UTF-16LE resource exceptions."""
import unittest

from check_text_format import check_bytes, load_rules, properties


class TextFormatTests(unittest.TestCase):
    def test_text_defaults_to_lf_without_changing_encoding_rules(self):
        rules = load_rules()
        for name, prefix in (("samples/_custom.py", b""),
                             ("clnch/main.cpp", b"\xef\xbb\xbf"),
                             ("ReCraftLaunch.sln", b"\xef\xbb\xbf"),
                             ("licenses/python_LICENSE.txt", b"")):
            with self.subTest(name=name):
                settings = properties(name, rules)
                self.assertNotIn("end_of_line", settings)
                self.assertEqual(check_bytes(prefix + b"first\nsecond\n", settings), "first\nsecond\n")
                for ending in (b"\r\n", b"\r", b"\nsecond\r\n"):
                    with self.assertRaisesRegex(AssertionError, "LF required"):
                        check_bytes(prefix + b"first" + ending, settings)

    def test_utf16_resources_keep_bom_and_crlf(self):
        rules = load_rules()
        for name in ("clnch/clnch.rc", "clnch/resource.h"):
            with self.subTest(name=name):
                settings = properties(name, rules)
                data = b"\xff\xfe" + "first\r\nsecond\r\n".encode("utf-16le")
                self.assertEqual(check_bytes(data, settings), "first\r\nsecond\r\n")
                with self.assertRaisesRegex(AssertionError, "CRLF required"):
                    check_bytes(b"\xff\xfe" + "first\n".encode("utf-16le"), settings)
                with self.assertRaisesRegex(AssertionError, "BOM required"):
                    check_bytes(data[2:], settings)

    def test_bom_validation_and_binary_skip(self):
        rules = load_rules()
        with self.assertRaisesRegex(AssertionError, "BOM is not allowed"):
            check_bytes(b"\xef\xbb\xbftext\n", properties("example.py", rules))
        with self.assertRaisesRegex(AssertionError, "BOM required"):
            check_bytes(b"text\n", properties("example.cpp", rules))
        self.assertIsNone(check_bytes(b"\x89PNG\0\xff\r\n", properties("icon.png", rules)))


if __name__ == "__main__":
    unittest.main()
