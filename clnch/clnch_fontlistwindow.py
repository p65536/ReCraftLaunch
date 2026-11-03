"""Font previews confined to the font-name selection window."""

import ctypes
from collections import OrderedDict
from contextlib import ExitStack
from ctypes import wintypes as W

import clnch_ini
import clnch_inisettings as ini_settings
import clnch_listwindow
import clnch_misc
import clnch_strings as strings

import ckit
from ckit import ckitcore
from ckit.ckit_misc import _cleanup_on_exit

FONT_CACHE_SIZE = 64

# Local GDI rendering avoids ckitcore.Font's full BMP character-width scan.
_gdi = ctypes.WinDLL("gdi32", use_last_error=True)
for _name, _args, _result in (
    ("CreateCompatibleDC", [W.HDC], W.HDC),
    ("CreateFontW", [ctypes.c_int] * 5 + [W.DWORD] * 8 + [W.LPCWSTR], W.HFONT),
    ("SelectObject", [W.HDC, W.HGDIOBJ], W.HGDIOBJ),
    (
        "GetTextExtentPoint32W",
        [W.HDC, W.LPCWSTR, ctypes.c_int, ctypes.POINTER(W.SIZE)],
        W.BOOL,
    ),
    (
        "CreateDIBSection",
        [W.HDC, W.LPVOID, W.UINT, ctypes.POINTER(W.LPVOID), W.HANDLE, W.DWORD],
        W.HBITMAP,
    ),
    ("SetTextColor", [W.HDC, W.COLORREF], W.COLORREF),
    ("SetBkColor", [W.HDC, W.COLORREF], W.COLORREF),
    (
        "ExtTextOutW",
        [
            W.HDC,
            ctypes.c_int,
            ctypes.c_int,
            W.UINT,
            ctypes.POINTER(W.RECT),
            W.LPCWSTR,
            W.UINT,
            W.LPVOID,
        ],
        W.BOOL,
    ),
    ("GdiFlush", [], W.BOOL),
    ("DeleteObject", [W.HGDIOBJ], W.BOOL),
    ("DeleteDC", [W.HDC], W.BOOL),
):
    _function = getattr(_gdi, _name)
    _function.argtypes = _args
    _function.restype = _result


class _BitmapHeader(ctypes.Structure):
    _fields_ = [
        ("size", W.DWORD),
        ("width", W.LONG),
        ("height", W.LONG),
        ("planes", W.WORD),
        ("bits", W.WORD),
        ("compression", W.DWORD),
        ("image_size", W.DWORD),
        ("x_pixels", W.LONG),
        ("y_pixels", W.LONG),
        ("colors", W.DWORD),
        ("important_colors", W.DWORD),
    ]


class FontListWindow(clnch_listwindow.ListWindow):
    def __init__(self, *args, **kwargs):
        self._preview_fonts = OrderedDict()
        self._preview_planes = {}
        self._preview_images = {}
        self._preview_dc = None
        self._preview_paint = False
        self._font_size = ini_settings.FONT_SIZE.get(clnch_ini)
        with _cleanup_on_exit(self._clearPreviews, error_only=True):
            super().__init__(*args, **kwargs)

    def _createPreviewFont(self, name, scale=None):
        if self._preview_dc is None:
            self._preview_dc = _gdi.CreateCompatibleDC(None)
            if not self._preview_dc:
                raise ctypes.WinError(ctypes.get_last_error())
        size = max(
            1,
            round(
                self._font_size * (self.getDisplayScaling() if scale is None else scale)
            ),
        )
        font = _gdi.CreateFontW(-size, 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 0, 1, name)
        if not font:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return font, self._fontExtent(font, name)
        except BaseException:
            _gdi.DeleteObject(font)
            raise

    def _fontExtent(self, font, text):
        previous = _gdi.SelectObject(self._preview_dc, font)
        try:
            extent = W.SIZE()
            if not _gdi.GetTextExtentPoint32W(
                self._preview_dc,
                text,
                len(text.encode("utf-16-le")) // 2,
                ctypes.byref(extent),
            ):
                raise ctypes.WinError(ctypes.get_last_error())
            return extent
        finally:
            _gdi.SelectObject(self._preview_dc, previous)

    def _previewFont(self, name):
        if name in self._preview_fonts:
            self._preview_fonts.move_to_end(name)
            return self._preview_fonts[name]
        font, extent = self._createPreviewFont(name)
        self._preview_fonts[name] = (font, extent.cy)
        if len(self._preview_fonts) > FONT_CACHE_SIZE:
            _gdi.DeleteObject(self._preview_fonts.popitem(last=False)[1][0])
        return font, extent.cy

    def _layout(self, x, y, scale=None):
        scale = self.getDisplayScaling() if scale is None else scale
        padding = round(clnch_listwindow.HORIZONTAL_PADDING * scale)
        self.setHorizontalPadding(padding)
        min_width, min_height, max_width, max_height = self._size_request
        limit_width, limit_height = ckit.getWindowSizeLimits(self)
        self._size_limits = (limit_width, limit_height)
        char_width, row_height = self.getCharSize()
        padding_columns = (padding * 2 + char_width - 1) // char_width
        limit_width -= padding_columns
        if max_width is not None:
            limit_width = min(limit_width, max_width - padding_columns)
        widths = []
        # Measure one temporary font at a time; retain only the visible preview fonts.
        for name in self.items:
            font, extent = self._createPreviewFont(name, scale)
            try:
                height = max(row_height, extent.cy)
                widths.append((extent.cx * row_height + height - 1) // height)
            finally:
                _gdi.DeleteObject(font)
        margin = max(1, round(2 * scale))
        content_width = max(
            self.getStringWidth(self.title) * char_width,
            max(widths, default=0) + margin,
        )
        width = max(
            2,
            min(
                limit_width,
                max(
                    min_width - padding_columns,
                    (content_width + char_width - 1) // char_width,
                ),
            ),
        )
        available = width * char_width - margin
        self.item_lines = []
        for name, measured in zip(self.items, widths):
            lines = [name]
            if measured > available:
                font, extent = self._createPreviewFont(name, scale)
                try:
                    height = max(row_height, extent.cy)
                    lines = []
                    start = 0
                    while start < len(name):
                        end = start + 1
                        while (
                            end < len(name)
                            and self._fontExtent(font, name[start : end + 1]).cx
                            * row_height
                            <= available * height
                        ):
                            end += 1
                        lines.append(name[start:end])
                        start = end
                finally:
                    _gdi.DeleteObject(font)
            self.item_lines.append(lines)
        self.item_height = max((len(lines) for lines in self.item_lines), default=1)
        self.status_rows = 0
        height = min(
            limit_height,
            max(max_height, self.item_height),
            max(min_height, len(self.items) * self.item_height),
        )
        self.setPosSize(
            x, y, width, height, ckit.ORIGIN_X_CENTER | ckit.ORIGIN_Y_CENTER
        )

    def _renderPixels(self, font, font_height, text, width, height, fg, bg):
        header = _BitmapHeader(
            size=ctypes.sizeof(_BitmapHeader),
            width=width,
            height=-height,
            planes=1,
            bits=32,
        )
        bits = W.LPVOID()
        bitmap = _gdi.CreateDIBSection(
            self._preview_dc, ctypes.byref(header), 0, ctypes.byref(bits), None, 0
        )
        if not bitmap:
            raise ctypes.WinError(ctypes.get_last_error())
        old_bitmap = _gdi.SelectObject(self._preview_dc, bitmap)
        old_font = _gdi.SelectObject(self._preview_dc, font)
        try:
            _gdi.SetTextColor(self._preview_dc, fg[0] | fg[1] << 8 | fg[2] << 16)
            _gdi.SetBkColor(self._preview_dc, bg[0] | bg[1] << 8 | bg[2] << 16)
            rect = W.RECT(0, 0, width, height)
            # ETO_OPAQUE | ETO_CLIPPED: fill the row and clip all glyphs to it.
            if not _gdi.ExtTextOutW(
                self._preview_dc,
                0,
                (height - font_height) // 2,
                6,
                ctypes.byref(rect),
                text,
                len(text.encode("utf-16-le")) // 2,
                None,
            ):
                raise ctypes.WinError(ctypes.get_last_error())
            _gdi.GdiFlush()
            pixels = bytearray(ctypes.string_at(bits, width * height * 4))
            pixels[0::4], pixels[2::4] = pixels[2::4], pixels[0::4]
            pixels[3::4] = b"\xff" * (width * height)
            return bytes(pixels)
        finally:
            _gdi.SelectObject(self._preview_dc, old_font)
            _gdi.SelectObject(self._preview_dc, old_bitmap)
            _gdi.DeleteObject(bitmap)

    def putString(self, x, y, width, height, attr, text, offset=0):
        if (
            not self._preview_paint
            or not text.strip()
            or y >= self.height() - self.status_rows
        ):
            return super().putString(x, y, width, height, attr, text, offset)
        index = self.scroll_info.pos + y // self.item_height
        name = self.items[index]
        cell_width, cell_height = self.getCharSize()
        pixels_width = width * cell_width
        selected = self.active and self.select == index
        fg = ckit.getColor("select_fg" if selected else "fg")
        bg = ckit.getColor("select_bg" if selected else "bg")
        key = (name, text, pixels_width, cell_height, fg, bg)
        super().putString(x, y, width, height, attr, " " * width)
        self._preview_rows.add(y)
        plane = self._preview_planes.get(y)
        if plane is None:
            # Lower priorities are drawn after the base TextWindow plane (0.0).
            plane = ckitcore.ImagePlane(self, (0, 0), (1, 1), -1.0)
            self._preview_planes[y] = plane
        plane.setPosition(self.charToClient(x, y))
        plane.setSize((pixels_width, cell_height))
        if self._preview_images.get(y) != key:
            font, font_height = self._previewFont(name)
            # Bitmap faces may have a fixed minimum height: shrink the whole raster to fit.
            render_height = max(cell_height, font_height)
            render_width = (
                pixels_width * render_height + cell_height - 1
            ) // cell_height
            pixels = self._renderPixels(
                font, font_height, text, render_width, render_height, fg, bg
            )
            plane.setImage(
                ckitcore.Image.fromBytes(
                    (render_width, render_height), pixels, None, True
                )
            )
            self._preview_images[y] = key

    def paint(self):
        self._preview_rows = set()
        self._preview_paint = True
        try:
            super().paint()
        finally:
            self._preview_paint = False
            for row in list(self._preview_planes):
                if row not in self._preview_rows:
                    self._preview_planes.pop(row).destroy()
                    self._preview_images.pop(row, None)

    def _clearPreviews(self):
        with ExitStack() as cleanup:
            if self._preview_dc:
                cleanup.enter_context(_cleanup_on_exit(_gdi.DeleteDC, self._preview_dc))
                self._preview_dc = None
            for font, height in reversed(self._preview_fonts.values()):
                cleanup.enter_context(_cleanup_on_exit(_gdi.DeleteObject, font))
            self._preview_fonts.clear()
            for plane in reversed(self._preview_planes.values()):
                cleanup.enter_context(_cleanup_on_exit(plane.destroy))
            self._preview_planes.clear()
            self._preview_images.clear()

    def onDpi(self, scale):
        self._clearPreviews()
        super().onDpi(scale)

    def onClose(self):
        self.cancel()

    def destroy(self):
        with _cleanup_on_exit(super().destroy):
            self._clearPreviews()


def popFontMenu(main_window, items, initial_select):
    was_enabled = main_window.isEnabled()
    pos = main_window.centerOfWindowInPixel()
    window = FontListWindow(
        pos[0],
        pos[1],
        5,
        1,
        None,
        16,
        main_window,
        False,
        strings.CONFIG_FONT,
        items,
        initial_select=initial_select,
    )
    with clnch_misc._modal_dialog_scope(main_window, window, was_enabled):
        clnch_misc.adjustWindowPosition(main_window, window, default_up=False)
        window.show(True)
        main_window.enable(False)
        window.messageLoop()
        return window.getResult()
