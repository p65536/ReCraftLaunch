"""Python-index contracts with a synthetic UTF-16 column provider; no GUI."""
import unittest
from unittest.mock import patch

from test_gui_drawing import Window, ckit


class SearchPositionTests(unittest.TestCase):
    def test_uppercase_expansion_spans(self):
        cases = (
            ("ßx", "x", (1, 2)), ("aßx", "x", (2, 3)),
            ("ßx", "s", (0, 1)), ("ßx", "ss", (0, 1)),
            ("ßx", "sx", (0, 2)), ("aßx", "ass", (0, 2)),
            ("ﬃx", "fi", (0, 1)), ("ﬃx", "ix", (0, 2)),
            ("😀ß全x", "x", (3, 4)), ("ss", "ß", (0, 2)),
            ("ß", "sss", None), ("İıſ", "i", (1, 2)),
        )
        for line, query, expected in cases:
            with self.subTest(line=line, query=query):
                search = ckit.Search(query, False, False, False)
                self.assertEqual(search.search(line), expected)
                self.assertIsNone(search.re_result)

    def test_bounds_use_original_characters(self):
        search = ckit.Search("x", False, False, False)
        for start, end, expected in (
            (None, None, (1, 2)), (1, 2, (1, 2)), (2, None, (3, 4)),
            (0, 1, None), (1, 1, None), (2, 3, None),
            (-3, -2, (1, 2)), (-2, None, (3, 4)),
            (9, None, None), (0, -9, None), (0, 99, (1, 2)),
        ):
            with self.subTest(start=start, end=end):
                self.assertEqual(search.search("ßxßx", start, end), expected)
        partial = ckit.Search("s", False, False, False)
        self.assertEqual(partial.search("ßx", 0, 1), (0, 1))
        self.assertIsNone(partial.search("ßx", 1))
        crossing = ckit.Search("sx", False, False, False)
        self.assertIsNone(crossing.search("ßx", 0, 1))
        self.assertIsNone(crossing.search("ßx", 1))

    def test_empty_query_and_unchanged_search_modes(self):
        for line in ("", "abc", "ßx", "ﬃx"):
            search = ckit.Search("", False, False, False)
            for start in range(-len(line) - 2, len(line) + 3):
                for end in range(-len(line) - 2, len(line) + 3):
                    found = line.find("", start, end)
                    expected = None if found < 0 else (found, found)
                    self.assertEqual(search.search(line, start, end), expected)
        self.assertEqual(ckit.Search("x", False, True, False).search("ßx"), (1, 2))
        self.assertIsNone(ckit.Search("X", False, True, False).search("ßx"))
        for word, regex in ((True, False), (False, True)):
            search = ckit.Search("ss", word, False, regex)
            self.assertIsNone(search.search("ß"))
        regex = ckit.Search("x", False, False, True)
        self.assertEqual(regex.search("ßx"), (1, 2))
        self.assertEqual(regex.re_result.span(), (1, 2))


class TextColumnTests(unittest.TestCase):
    def test_utf16_columns_to_python_positions(self):
        window = Window()
        # One cell per surrogate unit and two cells for the CJK character.
        window.getStringColumns = lambda *args: (0, 1, 2, 3, 4, 6, 7, 8, 9)
        with patch.object(ckit.TextWidget, "paint"):
            edit = ckit.TextWidget(window, 0, 0, 30, 5)
            try:
                edit.modifyText(text="a😀\t全😀z")
                columns = (0, 1, 3, 4, 6, 8, 9)
                for index, column in enumerate(columns):
                    self.assertEqual(edit.getIndexFromColumn(0, column), index)
                for column, fraction, expected in (
                    (1, 0.0, 1), (2, 0.24, 1), (2, 0.25, 2),
                    (4, 0.0, 3), (5, 0.24, 3), (5, 0.25, 4),
                    (9, 0.0, 6), (12, 0.74, 9), (12, 0.75, 10),
                ):
                    self.assertEqual(edit.getIndexFromColumn(0, column, fraction, True), expected)
                self.assertEqual(edit.getIndexFromColumn(0, 20), len("a😀\t全😀z"))
                self.assertEqual(edit.getIndexFromColumn(1, 20), 0)
            finally:
                edit.destroy()


if __name__ == "__main__":
    unittest.main()
