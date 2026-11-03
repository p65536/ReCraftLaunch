"""Hidden Windows-native font previews; no visible GUI or real INI writes."""
import ctypes
import statistics
import sys
import time
import unittest
from contextlib import ExitStack
from ctypes import wintypes
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from native_test_support import RUN_DIR

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "clnch"), str(RUN_DIR / "lib")]
sys._clnch_app_dir = str(ROOT)
import clnch_text

import ckit
from ckit import ckit_font, ckit_misc, ckitcore
from ckit.ckit_const import *

clnch_text.initialize()
import clnch_configmenu
import clnch_ini
import clnch_listwindow

LAZY_IMPORT = "clnch_fontlistwindow" not in sys.modules
import clnch_fontlistwindow as previews


class FontListTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ckit.registerWindowClass("ReClnchFontPreviewTest")
        ckit.Keymap.init()
        cls.font_names = ckit.TextWindow.enumFonts()

    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        ckit.setTheme("black", {})
        self.stack.enter_context(patch.object(ckit, "callConfigFunc"))
        self.stack.enter_context(patch.object(clnch_ini, "getint", return_value=12))
        self.stack.enter_context(patch.object(clnch_ini, "get", return_value="MS Gothic"))
        self.stack.enter_context(patch.object(ckit_misc.pyauto, "Window", SimpleNamespace(
            getMonitorInfo=lambda: [((0, 0, 1024, 768), (0, 0, 1024, 768), True)])))
        for method in ("show", "activate", "foreground"):
            self.stack.enter_context(patch.object(ckit.TextWindow, method))
        self.parent = ckit.TextWindow(x=200, y=200, width=20, height=1, show=False,
                                     font=ckit.getStockedFont("MS Gothic", 12, 2))
        self.addCleanup(self.parent.destroy)

    def window(self, items=None, rows=16, max_width=None, **kwargs):
        window = previews.FontListWindow(300, 250, 5, 1, max_width, rows, self.parent,
            False, "Fonts", self.font_names if items is None else items, **kwargs)
        self.addCleanup(window.destroy)
        return window

    def test_lazy_import_and_no_preview_generation_in_ordinary_list(self):
        self.assertTrue(LAZY_IMPORT)
        with patch.object(previews.FontListWindow, "_previewFont", side_effect=AssertionError):
            window = clnch_listwindow.ListWindow(300, 250, 5, 1, 40, 16,
                                                self.parent, False, "Config", ["Font", "History"])
            try:
                window.command_CursorDown(None)
                window.paint()
                self.assertIs(type(window), clnch_listwindow.ListWindow)
            finally:
                window.destroy()


    def test_list_defaults_are_private_and_explicit_items_keep_identity(self):
        first = clnch_listwindow.ListWindow(300, 250, 5, 1, 40, 16, self.parent, False)
        self.addCleanup(first.destroy)
        second = clnch_listwindow.ListWindow(300, 250, 5, 1, 40, 16, self.parent, False)
        self.addCleanup(second.destroy)
        self.assertIsNot(first.items, second.items)
        first.items.append("private")
        self.assertEqual(second.items, [])
        supplied = ["first", "second"]
        explicit = clnch_listwindow.ListWindow(300, 250, 5, 1, 40, 16,
                                              self.parent, False, items=supplied)
        self.addCleanup(explicit.destroy)
        self.assertIs(explicit.items, supplied)
        explicit.remove(0)
        self.assertEqual(supplied, ["second"])

    def test_popup_defaults_do_not_retain_callback_mutations(self):
        seen = []
        def loop(window):
            seen.append(window.items)
            window.items.append("callback")
        with (
            patch.object(self.parent, "centerOfWindowInPixel", return_value=(300, 250), create=True),
            patch.object(clnch_listwindow.ListWindow, "messageLoop", loop),
            patch.object(clnch_listwindow.clnch_misc, "adjustWindowPosition"),
        ):
            clnch_listwindow.popMenu(self.parent, 40, 16)
            clnch_listwindow.popMenu(self.parent, 40, 16)
            supplied = ["explicit"]
            clnch_listwindow.popMenu(self.parent, 40, 16, items=supplied)
        self.assertIsNot(seen[0], seen[1])
        self.assertEqual(seen[0], ["callback"])
        self.assertEqual(seen[1], ["callback"])
        self.assertIs(seen[2], supplied)
        self.assertEqual(supplied, ["explicit", "callback"])

    def test_only_visible_fonts_created_and_cursor_reuses_fonts_and_planes(self):
        stocked = ckit_font.fonts.copy()
        with patch.object(previews._gdi, "CreateFontW", wraps=previews._gdi.CreateFontW) as create:
            window = self.window(rows=4)
            self.assertEqual(set(window._preview_fonts), set(window.items[:window.itemsHeight()]))
            self.assertEqual(create.call_count, len(window.items) + len(window._preview_fonts))
            count = create.call_count
            planes = window._preview_planes.copy()
            window.onActivate(True)
            window.onKeyDown(VK_DOWN, 0)
            window.onKeyDown(VK_UP, 0)
            self.assertEqual(create.call_count, count)
            self.assertEqual(window._preview_planes, planes)
            window.onKeyDown(VK_END, 0)
            self.assertLessEqual(len(window._preview_fonts), previews.FONT_CACHE_SIZE)
            self.assertLessEqual(len(window._preview_planes), window.height())
            self.assertEqual(ckit_font.fonts, stocked)

    def test_preview_never_constructs_ckit_fonts_and_only_changed_rows_are_rendered(self):
        with patch.object(ckitcore, "Font", side_effect=AssertionError("full BMP scan")):
            window = self.window(rows=4)
            window.onActivate(True)
            with patch.object(window, "_renderPixels", wraps=window._renderPixels) as render:
                window.paint()
                render.assert_not_called()
                window.command_CursorDown(None)
                self.assertEqual(render.call_count, 2)

    def test_native_font_face_and_raster_background_clipping_and_replacement(self):
        window = self.window(["Consolas", "Cascadia Mono"])
        face_name = previews._gdi.GetTextFaceW
        face_name.argtypes = (wintypes.HDC, ctypes.c_int, wintypes.LPWSTR)
        face_name.restype = ctypes.c_int
        pictures = []
        for name in window.items:
            font, height = window._previewFont(name)
            previous = previews._gdi.SelectObject(window._preview_dc, font)
            try:
                face = ctypes.create_unicode_buffer(32)
                self.assertTrue(face_name(window._preview_dc, len(face), face))
                self.assertEqual(face.value, name)
            finally:
                previews._gdi.SelectObject(window._preview_dc, previous)
            pictures.append(window._renderPixels(font, height, "Sample", 90, 24,
                                                 (255, 255, 255), (0, 0, 0)))
        self.assertNotEqual(*pictures)
        self.assertTrue(any(pictures[0][0::4]))
        font, height = window._previewFont("Consolas")
        color = (23, 45, 67)
        for text in ("", " " * 20):
            pixels = window._renderPixels(font, height, text, 90, 24, (255, 255, 255), color)
            self.assertEqual(pixels, bytes((*color, 255)) * (90 * 24))
        clipped = window._renderPixels(font, height, "Sample" * 100, 8, 24,
                                       (255, 255, 255), color)
        self.assertEqual(len(clipped), 8 * 24 * 4)

    def test_bounded_cache_eviction_and_reuse(self):
        with patch.object(previews, "FONT_CACHE_SIZE", 6):
            window = self.window(rows=4)
            for _ in range(len(window.items)):
                window.onKeyDown(VK_DOWN, 0)
                self.assertLessEqual(len(window._preview_fonts), 6)
            self.assertNotIn(window.items[0], window._preview_fonts)
            last = window._preview_fonts[window.items[-1]]
            window.paint()
            self.assertIs(window._preview_fonts[window.items[-1]], last)

    def test_row_planes_fit_original_layout_across_fonts_and_dpi(self):
        window = self.window(initial_select=12)
        for scale in (1.0, 1.25, 1.5, 1.75, 2.0):
            with patch.object(previews.FontListWindow, "getDisplayScaling", return_value=scale):
                previous = list(window._preview_planes.values())
                window.onDpi(scale)
                self.assertEqual(window.select, 12)
                for plane in previous:
                    with self.assertRaises(ValueError):
                        plane.getPosition()
                for _ in range(3):
                    window.paint()
                    window.flushPaint()
                    cw, ch = window.getCharSize()
                    for row, plane in window._preview_planes.items():
                        x, y = plane.getPosition()
                        width, height = plane.getSize()
                        left, top = window.charToClient(0, row)
                        self.assertEqual(x, left)
                        self.assertGreaterEqual(y, top)
                        self.assertLessEqual(y + height, top + ch)
                        self.assertLessEqual(width, window.width() * cw)
                        name = window.items[window.scroll_info.pos + row // window.item_height]
                        self.assertEqual(window._preview_images[row][0], name)
                        self.assertEqual(height, ch)
                    window.command_CursorPageDown(None)
                    window.select = 12
                    window.scroll_info.makeVisible(12, window.itemsHeight())

    def test_long_names_wrap_at_their_own_width_and_stale_planes_are_destroyed(self):
        items = ["ＭＳ ゴシック" * 4, "MS Gothic", "Cascadia Mono"]
        window = self.window(items, max_width=20)
        self.assertGreater(window.item_height, 1)
        available = window.width() * window.getCharSize()[0] - 2
        for name, lines in zip(items, window.item_lines):
            self.assertEqual("".join(lines), name)
            font, font_height = window._previewFont(name)
            for line in lines:
                extent = window._fontExtent(font, line)
                self.assertLessEqual(extent.cx * window.getCharSize()[1],
                                     available * max(font_height, window.getCharSize()[1]))
        old = list(window._preview_planes.values())
        window.items = []
        window.item_lines = []
        window.paint()
        self.assertEqual(window._preview_planes, {})
        for plane in old:
            with self.assertRaises(ValueError):
                plane.getPosition()

    def test_maximum_width_includes_offscreen_font_and_exceeds_old_40_column_cap(self):
        items = self.font_names[:16] + ["Ｗ" * 31]
        window = self.window(items, rows=4)
        self.assertNotIn(items[-1], window._preview_fonts)
        self.assertGreater(window.width(), 40)
        self.assertEqual(window.item_height, 1)
        cw, ch = window.getCharSize()
        largest = 0
        for name in items:
            font, extent = window._createPreviewFont(name)
            try:
                height = max(ch, extent.cy)
                largest = max(largest, (extent.cx * ch + height - 1) // height)
            finally:
                previews._gdi.DeleteObject(font)
        expected = max(window.getStringWidth(window.title) * cw, largest + 2)
        self.assertEqual(window.width(), (expected + cw - 1) // cw)
        self.assertEqual(window.item_lines, [[name] for name in items])

    def test_real_font_names_fit_across_dpi_and_width_tracks_work_area(self):
        window = self.window(initial_select=12)
        for scale in (1.0, 1.25, 1.5, 1.75, 2.0):
            with patch.object(previews.FontListWindow, "getDisplayScaling", return_value=scale):
                window.onDpi(scale)
                self.assertEqual(window.select, 12)
                self.assertEqual(window.item_height, 1)
                cw, ch = window.getCharSize()
                for name in window.items:
                    font, extent = window._createPreviewFont(name)
                    try:
                        self.assertLessEqual(extent.cx * ch,
                            (window.width() * cw - round(2 * scale)) * max(ch, extent.cy))
                    finally:
                        previews._gdi.DeleteObject(font)
                with patch.object(ckit_misc.pyauto, "Window", SimpleNamespace(
                        getMonitorInfo=lambda: [((0, 0, 1024, 768), (0, 0, 190, 768), True)])):
                    window.onDpi(scale)
                    self.assertEqual(window.select, 12)
                    self.assertTrue(all("".join(lines) == name
                        for name, lines in zip(window.items, window.item_lines)))
                    left, _top, right, _bottom = window.getWindowRect()
                    self.assertGreaterEqual(left, 0)
                    self.assertLessEqual(right, 190)

    def test_tall_font_raster_shrinks_to_unchanged_row_height(self):
        window = self.window(["Consolas"])
        cell_width, cell_height = window.getCharSize()
        window._font_size = 36
        window._clearPreviews()
        with patch.object(window, "_renderPixels", wraps=window._renderPixels) as render:
            window.paint()
            window.flushPaint()
            font_height = window._preview_fonts["Consolas"][1]
            self.assertGreater(font_height, cell_height)
            expected_width = (window.width() * cell_width * font_height + cell_height - 1) // cell_height
            self.assertEqual(render.call_args.args[3:5], (expected_width, font_height))
            self.assertEqual(window._preview_planes[0].getSize(),
                             (window.width() * cell_width, cell_height))
            self.assertEqual(window.getCharSize(), (cell_width, cell_height))

    def test_navigation_search_enter_and_escape(self):
        window = self.window(["Consolas", "Courier New", "MS Gothic", "Cascadia Mono"], rows=2)
        for key, selected in ((VK_DOWN, 1), (VK_UP, 0), (VK_NEXT, 1), (VK_NEXT, 3),
                              (VK_PRIOR, 2), (VK_HOME, 0), (VK_END, 3)):
            window.onKeyDown(key, 0)
            self.assertEqual(window.select, selected)
        window.onChar(ord("M"), 0)
        self.assertEqual(window.select, 2)
        with patch.object(previews.FontListWindow, "quit") as quit_window:
            window.onKeyDown(VK_RETURN, 0)
            self.assertEqual(window.getResult(), 2)
            quit_window.assert_called_once()
            window.onKeyDown(VK_ESCAPE, 0)
            self.assertEqual(window.getResult(), -1)
            window.select = 2
            window.onClose()
            self.assertEqual(window.getResult(), -1)

    def test_incremental_search_reuses_base_handlers(self):
        window = self.window(["Consolas", "Courier New", "MS Gothic", "Cascadia Mono"],
                             onekey_search=False)
        window.onKeyDown(ord("F"), 0)
        window.onChar(ord("C"), 0)
        window.onKeyDown(VK_END, 0)
        self.assertEqual(window.select, 3)
        window.onKeyDown(VK_HOME, 0)
        self.assertEqual(window.select, 0)
        window.onKeyDown(VK_ESCAPE, 0)
        self.assertIsNone(window.isearch)
        self.assertEqual(window.select, 0)

    def test_config_changes_only_after_confirmation_and_preserves_initial_selection(self):
        main = SimpleNamespace(enumFonts=lambda: ["Consolas", "MS Gothic", "Cascadia Mono"],
                               updateFont=Mock())
        with patch.object(clnch_ini, "set") as save:
            def choose(parent, items, initial_select):
                self.assertEqual(initial_select, 1)
                save.assert_not_called()
                main.updateFont.assert_not_called()
                return result
            with patch.object(previews, "popFontMenu", side_effect=choose):
                result = -1
                clnch_configmenu._configFontName(main)
                save.assert_not_called()
                result = 2
                clnch_configmenu._configFontName(main)
                save.assert_called_once_with("FONT", "name", "Cascadia Mono")
                main.updateFont.assert_called_once_with()

    def test_popup_exception_restores_parent_and_releases_resources(self):
        self.parent.centerOfWindowInPixel = lambda: (300, 250)
        created = []
        original = previews.FontListWindow
        def make(*args, **kwargs):
            window = original(*args, **kwargs)
            created.append(window)
            return window
        with patch.object(previews, "FontListWindow", side_effect=make), \
             patch.object(original, "messageLoop", side_effect=RuntimeError("test")), \
             patch.object(ckit.TextWindow, "enable") as enable:
            with self.assertRaisesRegex(RuntimeError, "test"):
                previews.popFontMenu(self.parent, self.font_names, 0)
            self.assertEqual([call.args[0] for call in enable.call_args_list], [False, True])
            self.assertEqual(created[0]._preview_fonts, {})
            self.assertEqual(created[0]._preview_planes, {})

    def test_repeated_open_close_does_not_accumulate_gdi_resources(self):
        process = ctypes.WinDLL("kernel32").GetCurrentProcess
        process.restype = wintypes.HANDLE
        resources = ctypes.WinDLL("user32").GetGuiResources
        resources.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        resources.restype = wintypes.DWORD
        counts = []
        for _ in range(6):
            window = previews.FontListWindow(300, 250, 5, 1, 40, 16, self.parent,
                                             False, "Fonts", self.font_names)
            window.onActivate(True)
            window.command_CursorLast(None)
            window.flushPaint()
            window.destroy()
            self.assertEqual(window._preview_fonts, {})
            self.assertEqual(window._preview_planes, {})
            counts.append(resources(process(), 0))
        self.assertEqual(len(set(counts)), 1, counts)
        print("GDI resources after close:", counts)

    def test_scroll_cost_and_font_creation_count(self):
        with patch.object(previews._gdi, "CreateFontW", wraps=previews._gdi.CreateFontW) as create:
            start = time.perf_counter()
            window = self.window()
            opening = (time.perf_counter() - start) * 1000
            counts, costs = [], []
            for _ in range(2):
                start_count = create.call_count
                times = []
                for _ in window.items:
                    start = time.perf_counter()
                    window.command_CursorDown(None)
                    window.flushPaint()
                    times.append((time.perf_counter() - start) * 1000)
                counts.append(create.call_count - start_count)
                costs.append((round(statistics.median(times), 3), round(max(times), 3)))
                window.command_CursorFirst(None)
            self.assertEqual(counts[1], 0)
            self.assertLessEqual(len(window._preview_fonts), previews.FONT_CACHE_SIZE)
            print("Preview benchmark: opening_ms=", round(opening, 3), "scroll_fonts=", counts,
                  "scroll_median_max_ms=", costs, "cache=", len(window._preview_fonts))


if __name__ == "__main__":
    unittest.main()
