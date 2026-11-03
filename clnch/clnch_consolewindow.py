import bisect
import ctypes
import sys
import time
from ctypes import wintypes
from typing import TypedDict as _TypedDict

import clnch_ini
import clnch_inisettings as ini_settings
import clnch_misc
import clnch_resource
import clnch_strings as strings
from clnch_consolelog import Log, _LogLayout

import ckit
from ckit.ckit_const import (
    LINE_TOP,
    MODKEY_CTRL,
    VK_A,
    VK_C,
    VK_DOWN,
    VK_ESCAPE,
    VK_F1,
    VK_F10,
    VK_LEFT,
    VK_NEXT,
    VK_PRIOR,
    VK_RIGHT,
    VK_UP,
)

_SetFocus = ctypes.WinDLL("user32").SetFocus
_SetFocus.argtypes = (wintypes.HWND,)
_SetFocus.restype = wintypes.HWND

_GetDoubleClickTime = ctypes.WinDLL("user32").GetDoubleClickTime
_GetDoubleClickTime.argtypes = ()
_GetDoubleClickTime.restype = wintypes.UINT
_GetSystemMetrics = ctypes.WinDLL("user32").GetSystemMetrics
_GetSystemMetrics.argtypes = (ctypes.c_int,)
_GetSystemMetrics.restype = ctypes.c_int

# --------------------------------------------------------------------
# Console window.


class _LogViewCache(_TypedDict):
    layout: _LogLayout
    width: int | None
    height: int
    text_height: int
    status_height: int


class ConsoleWindow(ckit.TextWindow):
    def __init__(self, parent_window, debug=False):
        self.initialized = False

        self.loadState()

        self.parent_window = parent_window

        self.active = False
        self.opened = False
        self.owner_active = False

        ckit.TextWindow.__init__(
            self,
            x=self.window_normal_x,
            y=self.window_normal_y,
            width=self.window_normal_width,
            height=self.window_normal_height,
            parent_window=parent_window,
            bg_color=ckit.getColor("bg"),
            cursor0_color=ckit.getColor("cursor0"),
            cursor1_color=ckit.getColor("cursor1"),
            border_size=2,
            title_bar=True,
            title=clnch_resource.clnch_appname,
            show=False,
            activate_handler=self._onActivate,
            close_handler=self._onClose,
            move_handler=self._onMove,
            size_handler=self._onSize,
            dpi_handler=self._onDpi,
            keydown_handler=self._onKeyDown,
            lbuttondown_handler=self._onLeftButtonDown,
            lbuttonup_handler=self._onLeftButtonUp,
            mbuttondown_handler=self._onMiddleButtonDown,
            mbuttonup_handler=self._onMiddleButtonUp,
            rbuttondown_handler=self._onRightButtonDown,
            rbuttonup_handler=self._onRightButtonUp,
            lbuttondoubleclick_handler=self._onLeftButtonDoubleClick,
            mousemove_handler=self._onMouseMove,
            mousewheel_handler=self._onMouseWheel,
        )

        self.debug = debug

        self.log = Log()
        self._wrap_cache: _LogViewCache | None = None
        self.scroll_info = ckit.ScrollInfo()

        self.mouse_click_info = None
        self._last_double_click = None
        self.selection = [[0, 0], [0, 0]]

        self.auto_show = False
        self.auto_show_required = False
        self.setTimer(self.onTimerAutoShow, 10)

        self.initialized = True
        self.updateFont()

    # --------------------------------------------------------------------------
    # Visibility and activation.

    def show(self, show, activate=True):
        if show:
            self.opened = True
            if activate:
                self.parent_window.show(True, False)
                clnch_misc.adjustWindowPosition(
                    self.parent_window, self, default_up=True
                )
                self._fitToWorkArea()
                ckit.TextWindow.show(self, True, False)
                self.activate()
                _SetFocus(self.getHWND())
            self.syncVisibility()
        else:
            self.auto_show_required = False
            if self.active and self.parent_window.isEnabled():
                self.parent_window.activate()
            self.opened = False
            self.owner_active = False
            ckit.TextWindow.show(self, False, False)

    def isOwnerActive(self):
        return self.parent_window.isLauncherActive()

    def onParentActivate(self):
        _SetFocus(self.parent_window.getHWND())
        self.owner_active = True

    def syncVisibility(self):
        if not self.opened:
            return
        active = self.isOwnerActive()
        self.owner_active = active
        if ini_settings.MISC_INACTIVE_BEHAVIOR.get(clnch_ini) == "hide":
            if self.parent_window.isVisible() != active:
                self.parent_window.show(active, False)
            visible = active
        else:
            visible = self.parent_window.isVisible()
        if self.isVisible() != visible:
            if visible:
                clnch_misc.adjustWindowPosition(
                    self.parent_window, self, default_up=True
                )
                self._fitToWorkArea()
            ckit.TextWindow.show(self, visible, False)

    def setAutoShow(self, auto_show):
        self.auto_show = auto_show

    def onTimerAutoShow(self):
        if self.auto_show_required:
            self.auto_show_required = False
            self.show(True, False)
        else:
            self.syncVisibility()

    # --------------------------------------------------------------------------
    # View geometry and coordinates.

    def _getRows(self):
        return self._updateView()["layout"].rows

    def _getView(self) -> _LogViewCache:
        cache = self._wrap_cache
        return self._updateView() if cache is None else cache

    def _updateView(self) -> _LogViewCache:
        width, height = max(self.width(), 1), self.height()
        cache: _LogViewCache | None = self._wrap_cache
        if (cache is not None and cache["layout"].log is self.log
                and cache["width"] == width and cache["height"] == height
                and cache["layout"].revision == self.log.revision):
            return cache

        reusable = cache if cache and cache["width"] == width else None
        previous = reusable["layout"] if reusable is not None else None
        layout = _LogLayout(self.log, width, self.getStringWidth, previous)
        if (reusable is not None and reusable["layout"].log is self.log
                and reusable["height"] == height and len(reusable["layout"].rows) == len(layout.rows)):
            status_height = reusable["status_height"]
        else:
            status_height = self._statusHeight(len(layout.rows))
        text_height = max(height - status_height, 1)
        if cache is not None and cache["layout"].log is self.log:
            self._syncLogView(cache, layout, text_height)
        cache = {
            "layout": layout, "width": width, "height": height,
            "text_height": text_height, "status_height": status_height,
        }
        self._wrap_cache = cache
        return cache

    def _syncLogView(self, cache, layout, text_height):
        previous = cache["layout"]
        pos = min(max(self.scroll_info.pos, 0), len(previous.rows) - 1)
        if pos + cache["text_height"] >= len(previous.rows):
            pos = len(layout.rows) - text_height
        else:
            line, column, _end = previous.rows[pos]
            pos = bisect.bisect_right(layout.rows, (line, column, sys.maxsize)) - 1
        self.scroll_info.pos = min(max(pos, 0), max(len(layout.rows) - text_height, 0))
        removed = layout.first_line - previous.first_line
        if removed:
            self.selection = [
                [line - removed, column] if line >= removed else [0, 0]
                for line, column in self.selection
            ]
            if self.mouse_click_info:
                for index in range(3, len(self.mouse_click_info), 2):
                    line, column = self.mouse_click_info[index : index + 2]
                    self.mouse_click_info[index : index + 2] = (
                        [line - removed, column] if line >= removed else [0, 0]
                    )

    def rectText(self):
        return [0, 0, self.width(), max(self.height() - self._statusHeight(), 0)]

    def _statusHeight(self, total=None):
        if total is None:
            self._getRows()
            return self._getView()["status_height"]
        messages = [
            template.format(first=total, last=total, total=total, count=total)
            + "\n" + strings.CONSOLE_GUIDE
            for template in (
                strings.CONSOLE_STATUS_LATEST,
                strings.CONSOLE_STATUS_REMAINING,
            )
        ]
        rows = max(
            len(ckit.splitLines(self, message, max(2, self.width())))
            for message in messages
        )
        return min(max(1, self.height() - 1), rows) if self.height() else 0

    def rectStatusBar(self):
        rows = self._statusHeight()
        return [0, self.height() - rows, self.width(), rows]

    # --------------------------------------------------------------------------
    # Event handlers.

    def _onActivate(self, active):
        self.active = active
        if active:
            self.owner_active = True
        else:
            self._last_double_click = None

    def _onClose(self):
        self.show(False)

    def _onMove(self, x, y):
        if not self.isMaximized() and not self.isMinimized():
            self.window_normal_x = x
            self.window_normal_y = y
        if (
            self.initialized
            and ckit.getWindowSizeLimits(self, border_size=2) != self._size_limits
        ):
            self._fitToWorkArea()

    def _onSize(self, width, height):
        if not self.isMaximized() and not self.isMinimized():
            self.window_normal_width = width
            self.window_normal_height = height

        self._fitToWorkArea()
        self.paint()

    def _onKeyDown(self, vk, mod):
        self._last_double_click = None
        if (vk == VK_ESCAPE and mod == 0) or (vk == VK_F10 and mod == MODKEY_CTRL):
            self.show(False)

        elif vk == VK_A and mod == MODKEY_CTRL:
            self._selectAll()

        elif vk == VK_C and mod == MODKEY_CTRL:
            self._copySelectedRegion()

        elif vk == VK_UP and mod == 0:
            self._scroll(-1)
            self.paint()

        elif vk == VK_DOWN and mod == 0:
            self._scroll(1)
            self.paint()

        elif (vk == VK_PRIOR or vk == VK_LEFT) and mod == 0:
            rect = self.rectText()
            self._scroll(-(rect[3] - rect[1]))
            self.paint()

        elif (vk == VK_NEXT or vk == VK_RIGHT) and mod == 0:
            rect = self.rectText()
            self._scroll(rect[3] - rect[1])
            self.paint()

        elif vk == VK_F1 and mod == 0:
            self.parent_window.command.Help()

    def _mousePosToCharPos(self, x, y):
        offset_x, offset_y = self.charToClient(0, 0)
        char_w, char_h = self.getCharSize()
        char_x = (x - offset_x) // char_w
        char_y = (y - offset_y) // char_h
        return char_x, char_y

    def _mousePosToLogPos(self, x, y):
        char_x, char_y = self._mousePosToCharPos(x, y)

        char_x = max(char_x, 0)
        char_x = min(char_x, self.width())

        if char_y < 0:
            char_x = 0
            char_y = 0

        text_height = self.rectText()[3]
        if char_y >= text_height:
            char_x = self.width()
            char_y = max(text_height - 1, 0)

        rows = self._getRows()
        row = self.scroll_info.pos + char_y
        layout = self._getView()["layout"]
        if row >= len(rows):
            lineno = len(layout.lines) - 1
            return lineno, len(layout.lines[lineno][0])
        lineno, start, end = rows[row]
        lineno -= layout.first_line
        text = layout.lines[lineno][0]
        columns = 0
        for index in range(start, end):
            char_width = 4 - columns % 4 if text[index] == "\t" else self.getStringWidth(text[index])
            if columns + char_width > char_x:
                return lineno, index
            columns += char_width
        return lineno, end

    def _selectAll(self):
        self._getRows()
        if self.mouse_click_info:
            self.releaseCapture()
        self.mouse_click_info = None
        self._last_double_click = None
        lines = self._getView()["layout"].lines
        last = len(lines) - 1
        self.selection = [[0, 0], [last, len(lines[last][0])]]
        self.paint()

    def _copySelectedRegion(self):
        self._getRows()
        joint_text = self._getView()["layout"].selectedText(self.selection)
        if joint_text:
            ckit.setClipboardText(joint_text)

    def _onLeftButtonDown(self, x, y, mod):
        double_click = self._last_double_click
        self._last_double_click = None
        _char_x, char_y = self._mousePosToCharPos(x, y)
        if not 0 <= char_y < self.rectText()[3]:
            return

        if double_click:
            timestamp, previous_x, previous_y = double_click
            # Use the Windows double-click time and rectangle for the third click.
            if (time.monotonic() - timestamp <= _GetDoubleClickTime() / 1000
                    and abs(x - previous_x) <= _GetSystemMetrics(36) // 2
                    and abs(y - previous_y) <= _GetSystemMetrics(37) // 2):
                self._selectAll()
                self.mouse_click_info = ["all", x, y]
                self.setCapture()
                return

        lineno, char_index = self._mousePosToLogPos(x, y)

        self.mouse_click_info = [False, x, y, lineno, char_index]
        self.setCapture()

        self.selection = [[lineno, char_index], [lineno, char_index]]
        self.paint()

    def _onLeftButtonUp(self, x, y, mod):
        if not self.mouse_click_info:
            return
        self.mouse_click_info = None
        self.releaseCapture()
        self._copySelectedRegion()

    def _onMiddleButtonDown(self, x, y, mod):
        self._last_double_click = None
        self.mouse_click_info = None

    def _onMiddleButtonUp(self, x, y, mod):
        self.mouse_click_info = None

    def _onRightButtonDown(self, x, y, mod):
        self._last_double_click = None
        self.mouse_click_info = None

    def _onRightButtonUp(self, x, y, mod):
        self.mouse_click_info = None

    def _wordbreak(self, s, pos, step):
        word_break_chars1 = "\"!@#$%^&*()+|~-=\\`[]{};:',./<>?"
        word_break_chars2 = " \t"

        while True:
            if pos <= 0:
                return 0
            if pos >= len(s):
                return len(s)

            if s[pos - 1] in word_break_chars1:
                left_char_type = 1
            elif s[pos - 1] in word_break_chars2:
                left_char_type = 2
            else:
                left_char_type = 0

            if s[pos] in word_break_chars1:
                right_char_type = 1
            elif s[pos] in word_break_chars2:
                right_char_type = 2
            else:
                right_char_type = 0

            if left_char_type != 0 and right_char_type == 0:
                return pos

            pos += step

    def _onLeftButtonDoubleClick(self, x, y, mod):
        self._last_double_click = None
        _char_x, char_y = self._mousePosToCharPos(x, y)
        if not 0 <= char_y < self.rectText()[3]:
            return

        self._last_double_click = (time.monotonic(), x, y)
        lineno, char_index = self._mousePosToLogPos(x, y)

        s = self._getView()["layout"].lines[lineno][0]

        left = max(self._wordbreak(s, char_index, -1), 0)
        right = min(self._wordbreak(s, char_index + 1, +1), len(s))

        self.mouse_click_info = [True, x, y, lineno, left, lineno, right]
        self.setCapture()

        self.selection = [[lineno, left], [lineno, right]]

        self.paint()

    def _onMouseMove(self, x, y, mod):
        if self.mouse_click_info:
            if self.mouse_click_info[0] == "all":
                return
            _char_x, char_y = self._mousePosToCharPos(x, y)

            if char_y < 0:
                self._scroll(-1)
            elif char_y >= self.rectText()[3]:
                self._scroll(1)

            lineno, char_index = self._mousePosToLogPos(x, y)

            double_click = self.mouse_click_info[0]
            if double_click:
                s = self._getView()["layout"].lines[lineno][0]

                if [lineno, char_index] > self.selection[0]:
                    right = min(self._wordbreak(s, char_index + 1, +1), len(s))
                    self.selection[0] = self.mouse_click_info[3:5]
                    self.selection[1] = [lineno, right]
                else:
                    left = max(self._wordbreak(s, char_index, -1), 0)
                    self.selection[0] = self.mouse_click_info[5:7]
                    self.selection[1] = [lineno, left]

            else:
                self.selection[1] = [lineno, char_index]

            self.paint()

    def _scroll(self, delta):
        rows = self._getRows()
        self.scroll_info.pos += delta
        self.scroll_info.pos = min(
            self.scroll_info.pos, len(rows) - max(self.rectText()[3], 1)
        )
        self.scroll_info.pos = max(self.scroll_info.pos, 0)

    def _onMouseWheel(self, x, y, wheel, mod):
        self._last_double_click = None
        wheel_per_line = 0.34

        if wheel > 0:
            while wheel > 0:
                self._scroll(-1)
                wheel -= wheel_per_line
        else:
            while wheel < 0:
                self._scroll(+1)
                wheel += wheel_per_line

        self.paint()

    # --------------------------------------------------------------------------
    # Standard-output stream interface.

    def write(self, text, auto_show=True):
        self._getRows()
        self.log.write(text)
        self.paint()
        if auto_show and self.auto_show:
            self.auto_show_required = True

    def registerStdio(self):
        console = self
        class Stdout:
            def write(self, text):
                console.write(text)

        class Stderr:
            def write(self, text):
                console.write(text)

        if not self.debug:
            sys.stdout = Stdout()
            sys.stderr = Stderr()

    def unregisterStdio(self):
        sys.stdout = sys.__stdout__
        sys.stderr = sys.__stderr__

    # --------------------------------------------------------------------------

    def _fitToWorkArea(self):
        if (
            not self.initialized
            or getattr(self, "_fitting", False)
            or self.isMaximized()
            or self.isMinimized()
        ):
            return
        self._fitting = True
        try:
            self._size_limits = ckit.getWindowSizeLimits(self, border_size=2)
            width, height = self._size_limits
            rect = self.getWindowRect()
            self.setPosSize(
                rect[0],
                rect[1],
                min(self.width(), width),
                min(self.height(), height),
                0,
            )
            ckit.fitWindowToWorkArea(self)
        finally:
            self._fitting = False

    def _onDpi(self, scale):
        if not self.initialized:
            return
        width, height = self.width(), self.height()
        if self._wrap_cache is not None:
            self._wrap_cache["width"] = None
        self.setFontFromFontObject(clnch_misc.getDialogFont(scale))
        rect = self.getWindowRect()
        self.setPosSize(rect[0], rect[1], width, height, 0)
        self._fitToWorkArea()
        self.paint()

    def updateFont(self):
        self._onDpi(self.getDisplayScaling())

    def updateColor(self):
        self.setBGColor(ckit.getColor("bg"))
        self.setCursorColor(ckit.getColor("cursor0"), ckit.getColor("cursor1"))
        self.paint()

    # --------------------------------------------------------------------------
    # Drawing.

    def paint(self):
        rows = self._getRows()
        cache = self._getView()
        layout = cache["layout"]
        status_height = cache["status_height"]
        x, y, width, height = 0, 0, self.width(), self.height() - status_height
        self.scroll_info.pos = min(
            max(self.scroll_info.pos, 0), max(len(rows) - max(height, 1), 0)
        )
        attr = ckit.Attribute(fg=ckit.getColor("fg"))
        attr_selected = ckit.Attribute(
            fg=ckit.getColor("select_fg"), bg=ckit.getColor("select_bg")
        )
        selection_left, selection_right = sorted(self.selection)
        for row in range(height):
            self.putString(x, y + row, width, 1, attr, " " * width)
            index = self.scroll_info.pos + row
            if index >= len(rows):
                continue
            lineno, start, end = rows[index]
            lineno -= layout.first_line
            text = layout.lines[lineno][0][start:end]
            if selection_left[0] <= lineno <= selection_right[0]:
                left = selection_left[1] - start if lineno == selection_left[0] else 0
                right = selection_right[1] - start if lineno == selection_right[0] else len(text)
                left = min(max(left, 0), len(text))
                right = min(max(right, 0), len(text))
                parts = ((text[:left], attr), (text[left:right], attr_selected), (text[right:], attr))
            else:
                parts = ((text, attr),)
            column = 0
            for part, part_attr in parts:
                if "\t" in part:
                    part = ckit.expandTab(self, part, offset=column)
                self.putString(x + column, y + row, max(width - column, 0), 1, part_attr, part)
                column += self.getStringWidth(part)

        # Position and operation guides are excluded from text selection.
        x, y = 0, height
        if status_height:
            total = len(rows)
            first = self.scroll_info.pos + 1 if height else 0
            last = min(self.scroll_info.pos + height, total) if height else 0
            remaining = total - last
            if remaining:
                message = strings.CONSOLE_STATUS_REMAINING.format(
                    first=first, last=last, total=total, count=remaining
                )
            else:
                message = strings.CONSOLE_STATUS_LATEST.format(
                    first=first, last=last, total=total
                )
            attr = ckit.Attribute(
                fg=ckit.getHintColor(),
                bg=ckit.getColor("bg"),
                line0=(LINE_TOP, ckit.getColor("bar_fg")),
            )
            lines = ckit.splitLines(self, message + "\n" + strings.CONSOLE_GUIDE, max(2, width))
            guide_attr = ckit.Attribute(fg=ckit.getHintColor(), bg=ckit.getColor("bg"))
            for row in range(status_height):
                line = lines[row] if row < len(lines) else ""
                self.putString(
                    x,
                    y + row,
                    width,
                    1,
                    attr if row == 0 else guide_attr,
                    ckit.adjustStringWidth(self, line, width),
                )

    # --------------------------------------------------------------------------
    # Save and restore state.

    def loadState(self):
        self.window_normal_x = ini_settings.CONSOLE_X.get(clnch_ini)
        self.window_normal_y = ini_settings.CONSOLE_Y.get(clnch_ini)
        self.window_normal_width = ini_settings.CONSOLE_WIDTH.get(clnch_ini)
        self.window_normal_height = ini_settings.CONSOLE_HEIGHT.get(clnch_ini)

    def saveState(self):
        ini_settings.CONSOLE_X.set_text(clnch_ini, str(self.window_normal_x))
        ini_settings.CONSOLE_Y.set_text(clnch_ini, str(self.window_normal_y))
        ini_settings.CONSOLE_WIDTH.set_text(clnch_ini, str(self.window_normal_width))
        ini_settings.CONSOLE_HEIGHT.set_text(clnch_ini, str(self.window_normal_height))

    # --------------------------------------------------------------------------
    # Clear the log.

    def clearLog(self):
        if self.mouse_click_info:
            self.releaseCapture()
        self.log = Log()
        self._wrap_cache = None
        self.scroll_info = ckit.ScrollInfo()
        self.mouse_click_info = None
        self._last_double_click = None
        self.selection = [[0, 0], [0, 0]]
        self.paint()
