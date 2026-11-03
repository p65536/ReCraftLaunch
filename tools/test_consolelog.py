"""Console storage and layout contracts without native or GUI imports."""
import random
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "clnch"))

from clnch_consolelog import Log, _LogLayout


def measure(text):
    columns = 0
    for char in text:
        columns += 4 - columns % 4 if char == "\t" else 2 if ord(char) > 127 else 1
    return columns


class ConsoleLogTests(unittest.TestCase):
    def test_crlf_and_lf_copy_identically_for_every_write_split(self):
        for ending in ("\n", "\r\n"):
            text = ending.join(("abcdefghi", "日本\t🙂", "tail"))
            for split in range(len(text) + 1):
                with self.subTest(ending=ending, split=split):
                    log = Log()
                    log.write(text[:split])
                    previous = _LogLayout(log, 3, measure)
                    log.write("")
                    log.write(text[split:])
                    layout = _LogLayout(log, 3, measure, previous)
                    self.assertEqual(log.log, ["abcdefghi", "日本\t🙂", "tail"])
                    self.assertEqual(layout.lines, _LogLayout(log, 3, measure).lines)
                    self.assertEqual(layout.rows, _LogLayout(log, 3, measure).rows)
                    self.assertEqual(layout.selectedText([[0, 0], [2, 4]]), "abcdefghi\r\n日本\t🙂\r\ntail")
                    self.assertEqual(layout.selectedText([[1, 3], [0, 2]]), "cdefghi\r\n日本\t")
                    self.assertEqual(layout.selectedText([[0, 2], [0, 8]]), "cdefgh")
                    self.assertEqual(layout.selectedText([[0, 9], [1, 0]]), "\r\n")

    def test_only_the_cr_paired_with_lf_is_removed(self):
        log = Log()
        for text in ("a\rb\r\r", "", "\n", "\r", "\n", "tail\r"):
            log.write(text)
        self.assertEqual(log.log, ["a\rb\r", "", "tail\r"])
        layout = _LogLayout(log, 2, measure)
        self.assertEqual(layout.selectedText([[0, 0], [2, 5]]), "a\rb\r\r\n\r\ntail\r")
        self.assertEqual(layout.selectedText([[0, 3], [0, 4]]), "\r")
        self.assertFalse(log.last_line_terminated)

    def test_empty_and_chunked_newlines_preserve_original_text(self):
        log = Log()
        self.assertEqual(log.snapshot(), (0, 0, [""]))
        self.assertEqual(_LogLayout(log, 5, measure).rows, [(0, 0, 0)])
        for text in ("", "日\t", "本\r\n", "\n", "last", "\n"):
            log.write(text)
        self.assertEqual(log.snapshot(), (5, 0, ["日\t本", "", "last"]))
        self.assertTrue(log.last_line_terminated)
        self.assertEqual(log.getLine(3), "")

    def test_limit_retains_1000_logical_lines_and_snapshot_is_stable(self):
        log = Log()
        log.write("\n".join(str(i) for i in range(1000)))
        revision, first, lines = log.snapshot()
        log.write("\n1000\n1001")
        self.assertEqual((revision, first, len(lines), lines[0]), (1, 0, 1000, "0"))
        self.assertEqual((log.first_line, log.numLines(), log.getLine(0)), (2, 1000, "2"))
        log.write("\n" + "\n".join(str(i) for i in range(3000)))
        self.assertEqual((log.first_line, log.numLines(), log.getLine(0)), (3002, 1000, "2000"))

    def test_wrap_wide_characters_tabs_blank_lines_and_narrow_width(self):
        log = Log()
        log.write("日本AB\tZ\n\n日🙂")
        layout = _LogLayout(log, 6, measure)
        self.assertEqual(layout.rows, [(0, 0, 4), (0, 4, 6), (1, 0, 0), (2, 0, 2)])
        self.assertEqual(_LogLayout(log, 1, measure).rows[-2:], [(2, 0, 1), (2, 1, 2)])
        self.assertEqual(_LogLayout(log, 0, measure).rows, _LogLayout(log, 1, measure).rows)

    def test_copy_uses_logical_breaks_and_preserves_tabs_and_reverse_selection(self):
        log = Log()
        log.write("abcdefgh\n日本\tZ\nlast")
        layout = _LogLayout(log, 3, measure)
        self.assertEqual(layout.selectedText([[1, 3], [0, 2]]), "cdefgh\r\n日本\t")
        self.assertEqual(layout.selectedText([[0, 2], [0, 7]]), "cdefg")
        self.assertEqual(layout.selectedText([[0, 0], [0, 0]]), "")
        self.assertEqual(layout.selectedText([[0, 0], [2, 4]]), "abcdefgh\r\n日本\tZ\r\nlast")

    def test_incremental_cache_retains_prefix_and_does_not_remeasure_history(self):
        log = Log()
        log.write("\n".join("x" * 40 for _ in range(1000)))
        width = Mock(side_effect=measure)
        old = _LogLayout(log, 6, width)
        saved = list(old.rows)
        width.reset_mock()
        unchanged = _LogLayout(log, 6, width, old)
        width.assert_not_called()
        self.assertIs(unchanged.rows, old.rows)
        log.write("\n" + "y" * 40)
        new = _LogLayout(log, 6, width, old)
        self.assertLessEqual(width.call_count, 2)
        self.assertIs(new.lines[0], old.lines[1])
        self.assertEqual(new.rows, _LogLayout(log, 6, measure).rows)
        self.assertEqual(old.rows, saved)

    def test_incremental_layout_matches_full_rebuild_after_updates_and_resizes(self):
        rng = random.Random(812)
        log = Log()
        log.write("x\n" * 998)
        layout = None
        for _ in range(120):
            log.write("".join(rng.choice("a日🙂\t\r\n") for _ in range(rng.randrange(20))))
            width = rng.choice((1, 3, 6, 20))
            layout = _LogLayout(log, width, measure, layout)
            fresh = _LogLayout(log, width, measure)
            self.assertEqual(layout.lines, fresh.lines)
            self.assertEqual(layout.rows, fresh.rows)

    def test_replacing_log_does_not_reuse_same_revision(self):
        first, second = Log(), Log()
        first.write("old")
        second.write("new")
        old = _LogLayout(first, 6, measure)
        self.assertEqual(_LogLayout(second, 6, measure, old).lines, [("new", [(0, 3)])])

    def test_long_line_keeps_all_characters_and_reuses_unmodified_spans(self):
        log = Log()
        text = "日a\t🙂" * 10000
        log.write(text)
        layout = _LogLayout(log, 6, measure)
        self.assertEqual("".join(text[start:end] for _, start, end in layout.rows), text)
        self.assertTrue(all(end > start for _, start, end in layout.rows))
        log.write("\nnext")
        new = _LogLayout(log, 6, measure, layout)
        self.assertIs(new.lines[0][1], layout.lines[0][1])
        self.assertEqual(new.selectedText([[0, 0], [1, 4]]), text + "\r\nnext")

    def test_measure_failure_preserves_previous_layout_and_can_retry(self):
        log = Log()
        log.write("old")
        old = _LogLayout(log, 3, measure)
        log.write("\nnew")
        with self.assertRaisesRegex(RuntimeError, "measurement"):
            _LogLayout(log, 3, Mock(side_effect=RuntimeError("measurement")), old)
        self.assertEqual(old.lines, [("old", [(0, 3)])])
        self.assertEqual(old.rows, [(0, 0, 3)])
        self.assertEqual(_LogLayout(log, 3, measure, old).rows, [(0, 0, 3), (1, 0, 3)])

    def test_log_lock_is_released_after_invalid_write(self):
        log = Log()
        with self.assertRaises(AttributeError):
            log.write(1)
        self.assertTrue(log.lock.acquire(blocking=False))
        log.lock.release()
        log.write("valid")
        self.assertEqual(log.getLine(0), "valid")


if __name__ == "__main__":
    unittest.main()
