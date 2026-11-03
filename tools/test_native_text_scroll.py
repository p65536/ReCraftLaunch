"""TextPlane drawing/scroll bounds and rendered contents in a disposable Windows child.

--package DIR selects the distributed modules/PYD. No visible desktop is used.
"""
import ctypes as c
import faulthandler
import subprocess
import sys
import unittest
from pathlib import Path

if __name__ == "__main__" and "--child" not in sys.argv:
    result = subprocess.run([sys.executable, "-B", __file__, "--child", *sys.argv[1:]],
                            check=False, timeout=90)
    if result.returncode:
        print(f"Native scroll child exited with {result.returncode:#x}", file=sys.stderr)
    sys.exit(result.returncode)
if "--child" in sys.argv:
    sys.argv.remove("--child")

import test_native_callbacks as fixture
from test_native_gdi import plane_pixels

import ckit
from ckit import ckitcore

c.windll.kernel32.SetErrorMode(0x8003)
LIMIT = 2**31 - 1


class NativeTextScrollTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        expected = (fixture.PACKAGE or fixture.RUN_DIR) / "lib/ckitcore.pyd"
        assert Path(ckitcore.__file__).resolve() == expected.resolve()
        if fixture.PACKAGE:
            assert ckit.__file__.startswith(str(fixture.PACKAGE / "library.zip"))
        ckit.registerWindowClass("ReCLTextScrollTest")
        print("ckitcore:", ckitcore.__file__, flush=True)

    def setUp(self):
        self.font = ckit.Font("ＭＳ ゴシック", 16)
        self.cw, self.ch = self.font.getCharSize()
        self.size = (self.cw * 10, self.ch * 7)
        self.attrs = [ckit.Attribute()]
        for i in range(1, 50):
            self.attrs.append(ckit.Attribute(fg=(255, 255 - i, 210),
                                            bg=(20 + i, 40 + i * 2, 50 + i * 3),
                                            line0=(ckit.LINE_BOTTOM, (90, i, 120))))

    def plane(self, rows=()):
        window = ckit.Window(x=0, y=0, width=self.size[0] + 8, height=self.size[1] + 10,
                             show=False, bg_color=(9, 19, 29))
        self.addCleanup(window.destroy)
        plane = ckit.TextPlane(window, (3, 5), self.size, 0)
        plane.setFont(self.font)
        for y, row in enumerate(rows):
            for x, token in enumerate(row):
                if token:
                    plane.putString(x, y, 1, 1, self.attrs[token], chr(64 + token))
        return window, plane

    def snapshot(self, window):
        with plane_pixels() as snapshots:
            window.flushPaint()
        self.assertEqual(len(snapshots), 1)
        return snapshots[0]

    def rebuild(self, window, plane):
        # Recreate the DIB so this checks the character buffer, not just ScrollDC's cache.
        plane.setSize((self.size[0] + self.cw, self.size[1]))
        plane.setFont(ckit.Font("Consolas", 16))
        plane.setFont(self.font)
        window.flushPaint()
        plane.setSize(self.size)
        plane.setFont(ckit.Font("Consolas", 16))
        plane.setFont(self.font)
        return self.snapshot(window)

    def assert_scroll(self, rows, args):
        window, plane = self.plane(rows)
        expected = [list(row) for row in rows]
        x, y, width, height, dx, dy = args
        while len(expected) < y + height + max(0, dy):
            expected.append([])
        before = [row[:] for row in expected]
        if dy:
            # Preserve the existing vertical operation's whole-line buffer copy.
            for row in range(y, y + height):
                expected[row + dy] = before[row][:]
        else:
            for row in range(y, y + height):
                expected[row].extend([0] * max(0, x + width + max(0, dx) - len(expected[row])))
                source = before[row] + [0] * max(0, x + width - len(before[row]))
                expected[row][x + dx:x + dx + width] = source[x:x + width]
        reference, _ = self.plane(expected)
        desired = self.snapshot(reference)
        self.assertIsNone(plane.scroll(*args))
        actual = self.snapshot(window)
        # The overlapping destination must already be correct in the ScrollDC cache.
        left, top = max(x, x + dx), max(y, y + dy)
        right, bottom = min(x + width, x + width + dx, 10), min(y + height, y + height + dy, 7)
        for py in range(top * self.ch, bottom * self.ch):
            offset = ((self.size[1] - py - 1) * self.size[0] + left * self.cw) * 4
            end = offset + max(0, right - left) * self.cw * 4
            self.assertEqual(actual[2][offset:end], desired[2][offset:end])
        # All cells, glyphs, attributes and retained source cells must survive rebuilding.
        self.assertEqual(self.rebuild(window, plane), desired)

    def test_put_string_empty_areas_and_offscreen_inputs_do_not_allocate(self):
        from test_native_window_lifetime import native_allocations

        window, plane = self.plane([[1, 2]])
        baseline = self.snapshot(window)
        cases = ((0, 0, 0, 1, -1), (0, 0, -1, 1, -1),
                 (0, 0, -2**31, 1, -1), (0, 0, 1, 0, -1),
                 (0, 0, 1, -1, -1), (LIMIT, 0, LIMIT, 1, LIMIT),
                 (0, LIMIT, 1, LIMIT, 0), (0, 0, 1, 1, LIMIT),
                 (-1, 0, 1, 1, 0), (0, -1, 1, 1, 0),
                 (0, 0, LIMIT, LIMIT, -2**31))
        for x, y, width, height, offset in cases:
            with self.subTest(args=(x, y, width, height, offset)):
                with native_allocations() as (allocated, _):
                    self.assertIsNone(plane.putString(x, y, width, height, self.attrs[2], "日", offset))
                self.assertEqual(allocated.value, 0)
        with native_allocations() as (allocated, _):
            self.assertIsNone(plane.putString(5, 2, 3, 1, self.attrs[2], ""))
            self.assertIsNone(plane.putString(LIMIT, LIMIT, LIMIT, LIMIT, self.attrs[2], ""))
        self.assertEqual(allocated.value, 0)
        self.assertEqual(self.rebuild(window, plane), baseline)

    def test_put_string_double_cell_clipping_mixed_text_and_scroll_offsets(self):
        # Expected cells are explicit, including attributed spaces at both edges.
        cases = ((0, 1, "日", 0, [(0, " ")]),
                 (3, 1, "日", -1, [(3, " ")]),
                 (3, 4, "日Ab本", -1, [(3, " Ab ")]),
                 (2, 3, "A日B", 0, [(2, "A日")]),
                 (2, 2, "A日B", 0, [(2, "A ")]),
                 (1, 5, "A日B本C", -2, [(1, " B本C")]),
                 (1, 5, "A日B", 1, [(2, "A日B")]),
                 (1, 5, "Ab日C", 0, [(1, "Ab日C")]),
                 (8, LIMIT, "日B", 0, [(8, "日")]),
                 (9, LIMIT, "日", 0, [(9, " ")]))
        for x, width, text, offset, expected in cases:
            with self.subTest(x=x, width=width, text=text, offset=offset):
                window, plane = self.plane([[1] * 10])
                reference, target = self.plane([[1] * 10])
                self.assertEqual(plane.getStringWidth("日"), 2)
                self.assertIsNone(plane.putString(x, 0, width, 1, self.attrs[2], text, offset))
                for start, value in expected:
                    target.putString(start, 0, plane.getStringWidth(value), 1, self.attrs[2], value)
                self.assertEqual(self.rebuild(window, plane), self.snapshot(reference))

    def test_put_string_positive_offset_pads_to_actual_position(self):
        window, plane = self.plane()
        reference, target = self.plane()
        plane.putString(x=2, y=1, width=6, height=1, attr=self.attrs[2], str="A日B", offset=2)
        target.putString(0, 1, 4, 1, self.attrs[0], "    ")
        target.putString(4, 1, 4, 1, self.attrs[2], "A日B")
        self.assertEqual(self.rebuild(window, plane), self.snapshot(reference))

    def test_put_string_integer_extremes_clip_without_large_storage(self):
        window, plane = self.plane()
        reference, target = self.plane()
        # x+width and y+height overflow int before clipping in the old code.
        plane.putString(1, 1, LIMIT, LIMIT, self.attrs[2], "A日B")
        target.putString(1, 1, 4, 1, self.attrs[2], "A日B")
        self.assertEqual(self.rebuild(window, plane), self.snapshot(reference))
        # Exercise x+offset overflow/underflow without allocating or moving a GUI.
        for x, offset in ((1, LIMIT), (LIMIT, LIMIT), (LIMIT, -2**31), (0, -2**31)):
            self.assertIsNone(plane.putString(x, 0, LIMIT, 1, self.attrs[2], "日", offset))
        self.assertEqual(self.rebuild(window, plane), self.rebuild(reference, target))

    def test_put_string_allocation_failure_releases_text_and_recovers(self):
        from test_native_strings import column_allocations, conversion_error

        window, plane = self.plane()
        with conversion_error(ckitcore), self.assertRaises(MemoryError):
            plane.putString(0, 0, 1, 1, self.attrs[2], "日")
        malloc = fixture.CALL(c.c_void_p, c.c_size_t)
        slot = fixture.support.imports(ckitcore)["malloc"]
        real = malloc(c.c_void_p.from_address(slot).value)
        failed = []
        def allocate(size):
            if size == c.sizeof(c.c_void_p):
                failed.append(size)
                return None
            return real(size)
        with (column_allocations() as (_, _, wide_freed, _),
              fixture.support.replace_import("malloc", malloc(allocate), ckitcore),
              self.assertRaises(MemoryError)):
            plane.putString(0, 0, 1, 1, self.attrs[2], "日")
        self.assertEqual(failed, [c.sizeof(c.c_void_p)])
        self.assertEqual(wide_freed.value, 1)
        reference, target = self.plane()
        plane.putString(0, 0, 4, 1, self.attrs[2], "A日B")
        target.putString(0, 0, 4, 1, self.attrs[2], "A日B")
        self.assertEqual(self.rebuild(window, plane), self.snapshot(reference))

    def test_put_string_argument_and_lifetime_guards(self):
        window, plane = self.plane([[1, 2]])
        baseline = self.snapshot(window)
        for index in (0, 1, 2, 3, 6):
            for value, error in ((LIMIT + 1, OverflowError), (-2**31 - 1, OverflowError),
                                 (None, TypeError), (1.5, TypeError)):
                args = [0, 0, 1, 1, self.attrs[2], "日", 0]
                args[index] = value
                with self.subTest(index=index, value=value), self.assertRaises(error):
                    plane.putString(*args)
        self.assertEqual(self.rebuild(window, plane), baseline)
        fontless = ckit.TextPlane(window, (0, 0), self.size, 0)
        with self.assertRaisesRegex(ValueError, "font is not set"):
            fontless.putString(0, 0, 0, 1, self.attrs[2], "日", -1)
        fontless.destroy()
        with self.assertRaisesRegex(ValueError, "already destroyed"):
            fontless.putString(0, 0, 1, 1, self.attrs[2], "日")

    def test_normal_up_down_left_right_and_overlap(self):
        rows = [list(range(y * 8 + 1, y * 8 + 9)) for y in range(5)]
        for args in ((0, 1, 8, 4, 0, -1), (0, 0, 8, 4, 0, 1),
                     (1, 0, 7, 5, -1, 0), (0, 0, 7, 5, 1, 0),
                     (2, 1, 3, 3, -2, 0), (2, 1, 3, 3, 2, 0),
                     (2, 2, 3, 2, 0, -2), (2, 0, 3, 2, 0, 2)):
            with self.subTest(args=args):
                self.assert_scroll(rows, args)

    def test_empty_and_short_source_buffers(self):
        for rows, args in (([], (0, 2, 1, 3, 0, -2)),
                           ([], (1, 0, 3, 1, -1, 0)),
                           ([[1]], (1, 0, 5, 2, -1, 0)),
                           ([[1], [], [2, 3]], (0, 2, 5, 4, 0, -2)),
                           ([], (0, 0, 3, 2, 2, 0)),
                           ([], (0, 0, 3, 2, 0, 2))):
            with self.subTest(rows=rows, args=args):
                self.assert_scroll(rows, args)

    def test_moves_equal_to_and_larger_than_source(self):
        rows = [[1, 2], [3, 4]]
        for args in ((0, 0, 2, 2, 2, 0), (0, 0, 2, 2, 7, 0),
                     (0, 0, 2, 2, 0, 2), (0, 0, 2, 2, 0, 5),
                     (7, 0, 2, 2, -7, 0), (0, 5, 2, 2, 0, -5)):
            with self.subTest(args=args):
                self.assert_scroll(rows, args)

    def test_double_cell_glyphs_and_attributes_survive_rebuild(self):
        for args, text, expected in (((0, 0, 4, 1, 2, 0), "日本Ab", "日日本"),
                                     ((2, 0, 4, 1, -2, 0), "Ab日本", "日本本"),
                                     ((0, 0, 6, 1, 0, 1), "Ab日本", "Ab日本")):
            with self.subTest(args=args):
                window, plane = self.plane()
                plane.putString(0, 0, 6, 1, self.attrs[1], text)
                self.assertIsNone(plane.scroll(*args))
                reference, target = self.plane()
                target.putString(0, 0, 6, 1, self.attrs[1], expected)
                if args[-1]:
                    target.putString(0, 1, 6, 1, self.attrs[1], expected)
                self.assertEqual(self.rebuild(window, plane), self.snapshot(reference))

    def test_invalid_arguments_preserve_contents_and_recover(self):
        window, plane = self.plane([[1, 2], [3, 4]])
        baseline = self.snapshot(window)
        bad = [(-1, 0, 1, 1, 1, 0), (0, -1, 1, 1, 0, 1),
               (0, 0, -1, 1, 0, 0), (0, 0, 1, -1, 0, 0),
               (-2**31, 0, 1, 1, 0, 0), (0, -2**31, 1, 1, 0, 0),
               (0, 0, -2**31, 1, 0, 0), (0, 0, 1, -2**31, 0, 0),
               (0, 0, 3, 1, -1, 0), (0, 0, 1, 3, 0, -1),
               (0, 0, 1, 1, -2**31, 0), (0, 0, 1, 1, 0, -2**31)]
        overflow = [(LIMIT, 0, 1, 1, 0, 0), (0, LIMIT, 1, 1, 0, 0),
                    (0, 0, LIMIT, 1, LIMIT, 0), (0, 0, 1, LIMIT, 0, LIMIT),
                    (0, 0, 1, 1, LIMIT, 0), (0, 0, 1, 1, 0, LIMIT),
                    (0, 0, LIMIT, 1, 0, 0), (0, 0, 1, LIMIT, 0, 0)]
        for args, error in [(a, ValueError) for a in bad] + [(a, OverflowError) for a in overflow]:
            with self.subTest(args=args), self.assertRaises(error):
                plane.scroll(*args)
        for index in range(6):
            for value, error in ((2**31, OverflowError), (-2**31 - 1, OverflowError),
                                 (1.5, TypeError), (None, TypeError)):
                args = [0, 0, 1, 1, 0, 0]
                args[index] = value
                with self.subTest(index=index, value=value), self.assertRaises(error):
                    plane.scroll(*args)
        self.assertEqual(self.rebuild(window, plane), baseline)
        self.assertIsNone(plane.scroll(0, 0, 2, 1, 0, 1))
        reference, _ = self.plane([[1, 2], [1, 2]])
        self.assertEqual(self.rebuild(window, plane), self.snapshot(reference))

    def test_pixel_boundary_and_plane_translation_overflow(self):
        window, plane = self.plane([[1]])
        for args in ((LIMIT // self.cw, 0, 1, 1, 0, 0),
                     (0, LIMIT // self.ch, 1, 1, 0, 0)):
            with self.subTest(args=args), self.assertRaises(OverflowError):
                plane.scroll(*args)
        # Exact last representable cell endpoints, with no giant buffer allocation.
        plane.setPosition((0, 0))
        self.assertIsNone(plane.scroll(LIMIT // self.cw - 1, LIMIT // self.ch - 1,
                                       1, 1, 0, 0))
        plane.setPosition((-2**31, -2**31))
        self.assertIsNone(plane.scroll(0, 0, 1, 1, 0, 0))
        # Translation alone can overflow even when the cell products fit.
        plane.setPosition((LIMIT - self.size[0], LIMIT - self.size[1]))
        with self.assertRaises(OverflowError):
            plane.scroll(10, 7, 1, 1, 0, 0)
        plane.setPosition((3, 5))
        self.assertIsNone(plane.scroll(0, 0, 1, 1, 1, 0))
        self.assertTrue(self.rebuild(window, plane))

    def test_zero_area_zero_move_and_lifetime_guards(self):
        window, plane = self.plane([[1, 2], [3, 4]])
        baseline = self.snapshot(window)
        for args in ((0, 0, 0, 1, LIMIT, -2**31), (0, 0, 1, 0, -2**31, LIMIT),
                     (0, 0, 2, 2, 0, 0)):
            self.assertIsNone(plane.scroll(*args))
        self.assertEqual(self.rebuild(window, plane), baseline)
        fontless = ckit.TextPlane(window, (0, 0), self.size, 0)
        with self.assertRaisesRegex(ValueError, "font is not set"):
            fontless.scroll(0, 0, 1, 1, 0, 0)
        fontless.destroy()
        with self.assertRaisesRegex(ValueError, "already destroyed"):
            fontless.scroll(0, 0, 1, 1, 0, 0)

    def test_row_reserve_failure_becomes_memory_error_and_recovers(self):
        window, plane = self.plane([[1, 2], [3, 4]])
        baseline = self.snapshot(window)
        malloc = fixture.CALL(c.c_void_p, c.c_size_t)
        slot = fixture.support.imports(ckitcore)["malloc"]
        real = malloc(c.c_void_p.from_address(slot).value)
        failed = []

        def allocate(size):
            # Only fail the row-pointer reserve, never Debug STL's noexcept proxies.
            if size == 100 * c.sizeof(c.c_void_p):
                failed.append(size)
                return None
            return real(size)

        with (fixture.support.replace_import("malloc", malloc(allocate), ckitcore),
              self.assertRaises(MemoryError)):
            plane.scroll(0, 0, 1, 1, 0, 99)
        self.assertTrue(failed)
        self.assertEqual(self.rebuild(window, plane), baseline)
        self.assertIsNone(plane.scroll(0, 0, 2, 1, 0, 1))
        reference, _ = self.plane([[1, 2], [1, 2]])
        self.assertEqual(self.rebuild(window, plane), self.snapshot(reference))


if __name__ == "__main__":
    faulthandler.dump_traceback_later(60, exit=True)
    unittest.main(verbosity=2)
