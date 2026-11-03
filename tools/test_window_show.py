"""Native Windows checks before any paint timer is dispatched; no visual assessment."""
import ctypes
import sys
import time
import unittest
from contextlib import ExitStack
from ctypes import wintypes
from pathlib import Path

from native_test_support import RUN_DIR
from test_native_shell import replace_import

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "clnch"), str(RUN_DIR / "lib")]
sys._clnch_app_dir = str(ROOT)

import ckit


class LogFont(ctypes.Structure):
    _fields_ = [("metrics", wintypes.LONG * 5), ("flags", wintypes.BYTE * 8),
                ("face", wintypes.WCHAR * 32)]


class WindowBuffer(ctypes.Structure):
    # Mirror ckitcore.h Window through offscreen_size; validate HWND and pyobj before use.
    _fields_ = [
        ("hwnd", wintypes.HWND), ("pyobj", ctypes.c_void_p),
        ("quit_requested", ctypes.c_bool), ("active", ctypes.c_bool),
        ("ime_context", ctypes.c_void_p), ("ime_logfont", LogFont),
        ("style", wintypes.DWORD), ("exstyle", wintypes.DWORD),
        ("window_frame_size", wintypes.SIZE), ("last_valid_window_rect", wintypes.RECT),
        ("dc", wintypes.HDC), ("bitmap", wintypes.HBITMAP), ("size", wintypes.SIZE),
    ]


user32 = ctypes.WinDLL("user32")
user32.GetPropW.argtypes = (wintypes.HWND, wintypes.LPCWSTR)
user32.GetPropW.restype = ctypes.c_void_p
user32.GetActiveWindow.argtypes = ()
user32.GetActiveWindow.restype = wintypes.HWND
user32.ReleaseDC.argtypes = (wintypes.HWND, wintypes.HDC)
user32.ReleaseDC.restype = ctypes.c_int
gdi32 = ctypes.WinDLL("gdi32")
gdi32.GetPixel.argtypes = (wintypes.HDC, ctypes.c_int, ctypes.c_int)
gdi32.GetPixel.restype = wintypes.DWORD
user32.SendMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
user32.SendMessageW.restype = wintypes.LPARAM
user32.SetTimer.argtypes = (wintypes.HWND, ctypes.c_size_t, wintypes.UINT, ctypes.c_void_p)
user32.SetTimer.restype = ctypes.c_size_t


class WindowShowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ckit.registerWindowClass("ReCLWindowShowTest")

    def window(self, cls=ckit.Window, **kwargs):
        args = {"x": 100, "y": 100, "width": 160, "height": 80, "show": False,
                "bg_color": (17, 34, 51), "title": "Window show test"}
        args.update(kwargs)
        window = cls(**args)
        self.addCleanup(window.destroy)
        return window

    def buffer(self, window):
        hwnd = window.getHWND() & 0xffffffff
        address = user32.GetPropW(hwnd, "ckit_userdata")
        self.assertTrue(address)
        buffer = WindowBuffer.from_address(address)
        self.assertEqual(buffer.hwnd, hwnd)
        self.assertEqual(buffer.pyobj, id(window))
        return buffer

    def assert_ready(self, window, color=(17, 34, 51)):
        buffer = self.buffer(window)
        self.assertTrue(buffer.dc)
        self.assertTrue(buffer.bitmap)
        self.assertEqual((buffer.size.cx, buffer.size.cy), window.getClientSize())
        expected = color[0] | color[1] << 8 | color[2] << 16
        for x, y in ((0, 0), (buffer.size.cx - 1, buffer.size.cy - 1)):
            self.assertEqual(gdi32.GetPixel(buffer.dc, x, y), expected)
        return buffer

    def pixels(self, window):
        window.flushPaint()
        buffer = self.buffer(window)
        return tuple(gdi32.GetPixel(buffer.dc, x, y)
                     for y in range(buffer.size.cy) for x in range(buffer.size.cx))

    def assert_caret(self, window, baseline, x, y, mask=0xffffff):
        width, height = window.getClientSize()
        cell_height = window.getCharSize()[1]
        expected = tuple(value ^ mask if x <= i % width < x + 2 and
                         y + 2 <= i // width < y + cell_height - 2 else value
                         for i, value in enumerate(baseline))
        self.assertEqual(len(expected), width * height)
        self.assertEqual(self.pixels(window), expected)

    def test_caret_hide_with_large_border_and_horizontal_padding(self):
        font = ckit.getStockedFont("MS Gothic", 16, 2)
        cell_width, cell_height = font.getCharSize()
        for border, padding in ((1, 0), (cell_height + 3, 0), (1, cell_width * 2 + 3),
                                (cell_height + 3, cell_width * 2 + 3)):
            with self.subTest(border=border, padding=padding):
                window = self.window(ckit.TextWindow, width=10, height=3, caret=True,
                                     border_size=border, font=font)
                window.setHorizontalPadding(padding)
                window.show(True, False)
                baseline = self.pixels(window)
                for method in (window.setCursorPos, window.setCaretPosition):
                    with self.subTest(method=method.__name__):
                        self.assertIsNone(method(0, 0))
                        self.assert_caret(window, baseline, *window.charToClient(0, 0))
                        self.assertIsNone(method(-1, -1))
                        self.assertEqual(self.pixels(window), baseline)
                        for _ in range(4):
                            user32.SendMessageW(window.getHWND(), 0x113, 0x102, 0)
                            self.assertEqual(self.pixels(window), baseline)
                        window.setBGColor((17, 34, 51))
                        window.show(False)
                        window.show(True, False)
                        self.assertEqual(self.pixels(window), baseline)
                        method(1, 1)
                        self.assert_caret(window, baseline, *window.charToClient(1, 1))
                        method(-1, -1)
                        self.assertEqual(self.pixels(window), baseline)

    def test_text_plane_hide_preserves_other_negative_coordinate_conversion(self):
        window = self.window(ckit.TextWindow, width=10, height=5, caret=True,
                             font=ckit.getStockedFont("MS Gothic", 16, 2))
        plane = ckit.TextPlane(window, (30, 60), (40, 40), 1.0)
        self.addCleanup(plane.destroy)
        plane.setFont(window.getFont())
        window.show(True, False)
        baseline = self.pixels(window)
        for position in ((0, 0), (-1, 0), (0, -1), (-2, -2)):
            with self.subTest(position=position):
                plane.setCaretPosition(*position)
                self.assert_caret(window, baseline, *plane.charToClient(*position))
                plane.setCaretPosition(-1, -1)
                self.assertEqual(self.pixels(window), baseline)

    def test_caret_move_blink_redraw_and_ime_state(self):
        from ckit import ckitcore

        class Composition(ctypes.Structure):
            _fields_ = [("style", wintypes.DWORD), ("point", wintypes.POINT), ("area", wintypes.RECT)]

        window = self.window(ckit.TextWindow, width=8, height=3, caret=True,
                             font=ckit.getStockedFont("MS Gothic", 16, 2))
        window.show(True, False)
        baseline = self.pixels(window)
        opened, positions, fonts = [False], [], []
        context = ctypes.WINFUNCTYPE(ctypes.c_void_p, wintypes.HWND)(lambda hwnd: 1)
        release = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, ctypes.c_void_p)(lambda *args: True)
        status = ctypes.WINFUNCTYPE(wintypes.BOOL, ctypes.c_void_p)(lambda imc: opened[0])

        @ctypes.WINFUNCTYPE(wintypes.BOOL, ctypes.c_void_p, ctypes.POINTER(Composition))
        def composition(imc, form):
            positions.append((form.contents.style, form.contents.point.x, form.contents.point.y,
                              tuple(getattr(form.contents.area, edge) for edge in ("left", "top", "right", "bottom"))
                              if form.contents.style == 1 else None))
            return True

        @ctypes.WINFUNCTYPE(wintypes.BOOL, ctypes.c_void_p, ctypes.POINTER(LogFont))
        def font(imc, value):
            fonts.append(bytes(value.contents))
            return True

        with ExitStack() as stack:
            for name, callback in (("ImmGetContext", context), ("ImmReleaseContext", release),
                                   ("ImmGetOpenStatus", status), ("ImmSetCompositionWindow", composition),
                                   ("ImmSetCompositionFontW", font)):
                stack.enter_context(replace_import(name, callback, module=ckitcore))
            for ime_on in (False, True, False):
                opened[0] = ime_on
                user32.SendMessageW(window.getHWND(), 0x282, 0x8, 0)  # IMN_SETOPENSTATUS
                for area in (None, (4, 5, 50, 40)):
                    window.setImeRect(area)
                    for position in ((0, 0), (3, 1), (1, 2)):
                        window.setCursorPos(*position)
                        x, y = window.charToClient(*position)
                        mask = 0x0000ff if ime_on else 0xffffff
                        self.assert_caret(window, baseline, x, y, mask)
                        if ime_on:
                            self.assertEqual(positions[-1], (1 if area else 2, x, y + 2, area))
                        for visible in (True, False, True):
                            user32.SendMessageW(window.getHWND(), 0x113, 0x102, 0)
                            if visible:
                                self.assert_caret(window, baseline, x, y, mask)
                            else:
                                self.assertEqual(self.pixels(window), baseline)
                        window.setBGColor((17, 34, 51))
                        self.assert_caret(window, baseline, x, y, mask)
                        window.setCaretPosition(-1, -1)
                        self.assertEqual(self.pixels(window), baseline)
                        count = len(positions)
                        for _ in range(4):
                            user32.SendMessageW(window.getHWND(), 0x113, 0x102, 0)
                        self.assertEqual(self.pixels(window), baseline)
                        self.assertEqual(len(positions), count, "Hidden blink dirtied an empty caret")
            self.assertEqual(len(fonts), 36)
            self.assertTrue(all(value == fonts[0] for value in fonts))

    def test_dialog_scroll_hides_caret_above_and_below_viewport(self):
        from ckit import ckit_textwindow

        ckit.setTheme("black", {})
        parent = self.window(ckit.TextWindow, width=10, height=2,
                             font=ckit.getStockedFont("MS Gothic", 16, 2))
        item = ckit.Dialog.Edit("edit", 0, 8, "", "")
        dialog = ckit.Dialog(parent, "Caret scroll", [item])
        self.addCleanup(dialog.destroy)
        # Keep the actual Dialog paint/scroll path, with a border larger than a row.
        dialog._TextWindow__border_size = dialog.getCharSize()[1] + 3
        dialog.setPosSize(100, 100, 12, 3, 0)
        dialog.setBGColor((17, 34, 51))
        dialog.setCaretColor((255, 255, 255), (255, 0, 0))
        item.widget.scroll_pos = 0
        dialog.setCaretPosition(-1, -1)
        for scroll in (0, item.widget.y, item.widget.y + 1, item.widget.y + 2, 0):
            dialog.scroll_pos = scroll
            dialog.paint(ensure_visible=False)
            # Capture the same text with only the caret removed.
            ckit_textwindow.TextWindow.setCaretPosition(dialog, -1, -1)
            baseline = self.pixels(dialog)
            dialog.paint(ensure_visible=False)
            row = item.widget.y - scroll
            if 0 <= row < dialog.height():
                self.assert_caret(dialog, baseline, *dialog.charToClient(item.widget.x, item.widget.y))
            else:
                self.assertEqual(self.pixels(dialog), baseline)
            for row in (-1, dialog.height(), dialog.height() + 1):
                dialog.setCursorPos(1, row + scroll)
                self.assertEqual(self.pixels(dialog), baseline)
            dialog.setCursorPos(1, scroll)
            self.assert_caret(dialog, baseline, *ckit_textwindow.TextWindow.charToClient(dialog, 1, 0))
            dialog.setCursorPos(-1, -1)
            self.assertEqual(self.pixels(dialog), baseline)

    def test_caret_real_timer_delivery_survives_hide_and_restore(self):
        window = self.window(ckit.TextWindow, width=4, height=2, caret=True,
                             font=ckit.getStockedFont("MS Gothic", 16, 2))
        window.show(True, False)
        baseline = self.pixels(window)
        # Accelerate only this window's existing native blink timer.
        self.assertTrue(user32.SetTimer(window.getHWND(), 0x102, 30, None))
        cycles, stage, hidden_samples, errors, done = [[], []], [0], [], [], []
        deadline = time.monotonic() + 3

        def sample():
            # messageLoop checks its exit condition after draining pending messages.
            if done:
                return
            try:
                if stage[0] == 1:
                    self.assertEqual(self.pixels(window), baseline)
                    hidden_samples.append(True)
                    if len(hidden_samples) == 12:
                        stage[0] = 2
                        window.setCaretPosition(1, 0)
                else:
                    phases = cycles[stage[0] // 2]
                    visible = self.pixels(window) != baseline
                    if not phases or phases[-1] != visible:
                        phases.append(visible)
                    if len(phases) == 3:
                        if stage[0] == 0:
                            window.setCursorPos(-1, -1)
                            stage[0] = 1
                        else:
                            done.append(True)
            except BaseException as error:  # noqa: BLE001  # Surface callback assertions outside the native dispatcher.
                errors.append(error)
                done.append(True)

        # A separate native timer samples the real message-loop delivery.
        window.setCursorPos(0, 0)
        window.setTimer(sample, 10)
        try:
            window.messageLoop(lambda: int(not done and time.monotonic() < deadline))
            self.assertTrue(done, "Native blink timer did not complete both visibility cycles")
            # Late timer callbacks must not change a completed observation.
            for _ in range(2):
                user32.SendMessageW(window.getHWND(), 0x113, 0x102, 0)
                sample()
        finally:
            window.killTimer(sample)
        self.assertEqual(errors, [])
        self.assertEqual(cycles, [[True, False, True], [True, False, True]])

    def test_show_prepares_an_empty_window_without_timer_or_planes(self):
        window = self.window()
        self.assertFalse(self.buffer(window).dc)
        window.show(True, False)
        self.assert_ready(window)

    def test_unfonted_text_plane_rejects_font_operations_and_recovers(self):
        window = self.window()
        plane = ckit.TextPlane(window, (0, 0), (80, 32), 0.0)
        self.addCleanup(plane.destroy)
        attr = ckit.Attribute(fg=(255, 255, 255), bg=(9, 80, 140))
        operations = (
            (plane.putString, (0, 0, 1, 1, attr, "A")),
            (plane.scroll, (0, 0, 1, 1, 0, 0)),
            (plane.getCharSize, ()),
            (plane.charToScreen, (0, 0)),
            (plane.charToClient, (0, 0)),
            (plane.getStringWidth, ("A",)),
            (plane.getStringColumns, ("A",)),
            (plane.setCaretPosition, (0, 0)),
        )
        self.assertIsNone(plane.getFont())
        for operation, args in operations:
            with self.subTest(operation=operation.__name__), \
                 self.assertRaisesRegex(ValueError, "font is not set"):
                operation(*args)
        window.show(True, False)
        self.assert_ready(window)
        window.flushPaint()
        self.assertIsNone(plane.getFont())

        plane.setFont(ckit.Font("MS Gothic", 16))
        self.assertEqual(plane.getStringWidth("A"), 1)
        self.assertEqual(plane.getStringColumns("A"), (0, 1))
        self.assertEqual(plane.charToClient(0, 0), (0, 0))
        self.assertTrue(all(value > 0 for value in plane.getCharSize()))
        plane.charToScreen(0, 0)
        plane.setCaretPosition(0, 0)
        plane.putString(0, 0, 1, 1, attr, " ")
        window.flushPaint()
        buffer = self.buffer(window)
        self.assertEqual(gdi32.GetPixel(buffer.dc, 1, 1), 9 | 80 << 8 | 140 << 16)
        plane.scroll(0, 0, 1, 1, 0, 0)

    def test_constructor_show_uses_the_same_buffer_preparation(self):
        window = self.window(show=True)
        self.assert_ready(window)

    def test_show_prepares_pending_text_and_background(self):
        window = self.window(ckit.TextWindow, width=8, height=2,
                             font=ckit.getStockedFont("MS Gothic", 16, 2))
        color = (9, 80, 140)
        window.putString(0, 0, 8, 1, ckit.Attribute(fg=(255, 255, 255), bg=color), " " * 8)
        window.show(True, False)
        buffer = self.assert_ready(window)
        x, y = window.charToClient(0, 0)
        self.assertEqual(gdi32.GetPixel(buffer.dc, x + 1, y + 1),
                         color[0] | color[1] << 8 | color[2] << 16)

    def test_hide_does_not_allocate_a_buffer(self):
        window = self.window()
        window.show(False)
        self.assertFalse(self.buffer(window).dc)
        self.assertFalse(window.isVisible())

    def test_show_on_a_visible_window_keeps_pending_timer_updates(self):
        window = self.window(ckit.TextWindow, width=8, height=2,
                             font=ckit.getStockedFont("MS Gothic", 16, 2))
        window.show(True, False)
        buffer = self.assert_ready(window)
        x, y = window.charToClient(0, 0)
        before = gdi32.GetPixel(buffer.dc, x + 1, y + 1)
        window.putString(0, 0, 8, 1, ckit.Attribute(fg=(255, 255, 255), bg=(9, 80, 140)), " " * 8)
        from ckit import ckitcore
        visible = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND)(lambda hwnd: True)
        with replace_import("IsWindowVisible", visible, module=ckitcore):
            window.show(True, False)
        self.assertEqual(gdi32.GetPixel(buffer.dc, x + 1, y + 1), before)

    def test_presentation_distinguishes_empty_clip_errors_and_success(self):
        from ckit import ckitcore
        for clip_kind, transfer_ok, expected_calls, operation in (
            (1, True, 0, None), (0, True, 0, "GetClipBox"),
            (2, False, 1, "BitBlt"), (2, True, 1, None),
        ):
            with self.subTest(clip=clip_kind, transfer=transfer_ok):
                window = self.window()
                window.setBGColor((17, 34, 51))
                calls, messages, releases = [], [], []
                @ctypes.WINFUNCTYPE(ctypes.c_int, wintypes.HDC, ctypes.POINTER(wintypes.RECT))
                def clip(dc, rect, clip_kind=clip_kind):
                    rect.contents.right, rect.contents.bottom = 160, 80
                    ctypes.windll.kernel32.SetLastError(5)
                    return clip_kind
                @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HDC, ctypes.c_int, ctypes.c_int,
                    ctypes.c_int, ctypes.c_int, wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD)
                def transfer(*args, calls=calls, transfer_ok=transfer_ok):
                    calls.append(args)
                    ctypes.windll.kernel32.SetLastError(5)
                    return transfer_ok
                @ctypes.WINFUNCTYPE(ctypes.c_int, wintypes.HWND, wintypes.HDC)
                def release(hwnd, dc, releases=releases):
                    releases.append(dc)
                    result = user32.ReleaseDC(hwnd, dc)
                    ctypes.windll.kernel32.SetLastError(99)
                    return result
                output = ctypes.WINFUNCTYPE(None, wintypes.LPCWSTR)(messages.append)
                with (replace_import("GetClipBox", clip, module=ckitcore),
                      replace_import("BitBlt", transfer, module=ckitcore),
                      replace_import("ReleaseDC", release, module=ckitcore),
                      replace_import("OutputDebugStringW", output, module=ckitcore)):
                    window.flushPaint()
                    self.assert_ready(window)
                    self.assertEqual(len(calls), expected_calls)
                    self.assertEqual(len(releases), 1)
                    if operation:
                        self.assertEqual(messages, [f"ckit flushPaint: {operation} failed (WinError 5)\n"])
                        window.flushPaint()
                        self.assertEqual(len(messages), 2)  # Failed presentation retains dirty state.
                    else:
                        self.assertEqual(messages, [])
                        window.flushPaint()
                        self.assertEqual(len(calls), expected_calls)  # Completed buffer is clean.

    def test_getdc_failure_is_reported_and_next_flush_recovers(self):
        from ckit import ckitcore
        window = self.window()
        window.setBGColor((17, 34, 51))
        messages = []
        @ctypes.WINFUNCTYPE(wintypes.HDC, wintypes.HWND)
        def unavailable(hwnd):
            ctypes.windll.kernel32.SetLastError(5)
        output = ctypes.WINFUNCTYPE(None, wintypes.LPCWSTR)(messages.append)
        with (replace_import("GetDC", unavailable, module=ckitcore),
              replace_import("OutputDebugStringW", output, module=ckitcore)):
            window.flushPaint()
        self.assertEqual(messages, ["ckit flushPaint: GetDC failed (WinError 5)\n"])
        window.flushPaint()
        self.assert_ready(window)

    def test_reshow_rebuilds_a_resized_window_without_planes(self):
        window = self.window()
        window.show(True, False)
        self.assert_ready(window)
        window.show(False)
        window.setPositionAndSize(100, 100, 240, 120, 0)
        window.show(True, False)
        self.assert_ready(window)

    def test_show_without_activation_preserves_the_active_window(self):
        window = self.window()
        active = user32.GetActiveWindow()
        window.show(True, False)
        self.assertEqual(user32.GetActiveWindow(), active)
        self.assert_ready(window)


if __name__ == "__main__":
    unittest.main()
