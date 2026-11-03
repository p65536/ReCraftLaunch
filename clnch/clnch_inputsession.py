"""Private input state and command-line session lifetimes."""
from contextlib import ExitStack, contextmanager

import clnch_ini
import clnch_inisettings as ini_settings
import clnch_misc

import ckit
from ckit.ckit_const import VK_ESCAPE, VK_RETURN


@contextmanager
def _cleanup_on_exit(callback, *args):
    """Attempt each cleanup, preserving the first failure and noting later ones."""
    try:
        yield
    except BaseException as error:
        try:
            callback(*args)
        except BaseException as cleanup_error:  # noqa: BLE001  # Preserve the primary failure while unwinding all input resources.
            error.add_note(f"Input cleanup failed: {cleanup_error!r}")
        raise
    else:
        callback(*args)


class _TemporaryInputState:
    """Restore only applied window attributes, including partial application, in LIFO order."""

    def __init__(self, window):
        self.window = window
        self.stack = ExitStack()

    def __enter__(self):
        self.stack.__enter__()
        return self

    def set(self, **changes):
        for name, value in changes.items():
            previous = getattr(self.window, name)
            # Register before assignment: a setter may change state and then raise.
            self.stack.enter_context(_cleanup_on_exit(setattr, self.window, name, previous))
            setattr(self.window, name, value)

    def __exit__(self, *exc_info):
        return self.stack.__exit__(*exc_info)


class _CommandLineSession:
    """Own one edit widget, its callbacks, result and deferred commands."""

    def __init__(
        self, window, paint_flag, title, text="", selection=None,
        auto_complete: int = False, autofix_list=None, update_handler=None,
        candidate_handler=None, candidate_remove_handler=None, status_handler=None,
        keydown_handler=None, char_handler=None, enter_handler=None, escape_handler=None,
        *, preserve_argument_text=False,
    ):
        self.window = window
        self.paint_flag = paint_flag
        self.title = " " + title + " " if title else title
        self.title_width = window.getStringWidth(self.title)
        self.text = text
        self.selection = [len(text), len(text)] if selection is None else selection
        self.auto_complete = auto_complete
        self.autofix_list = autofix_list
        self.update_handler = update_handler
        self.candidate_handler = candidate_handler
        self.candidate_remove_handler = candidate_remove_handler
        self.status_handler = status_handler
        self.keydown_handler = keydown_handler
        self.char_handler = char_handler
        self.enter_handler = enter_handler
        self.escape_handler = escape_handler
        self.preserve_argument_text = preserve_argument_text
        self.status_string = ""
        self.result = None
        self.planned_command_list = []
        self.edit = None

    def run(self):
        window = self.window
        if self.status_handler:
            self.status_string = self.status_handler(ckit.EditWidget.UpdateInfo(self.text, self.selection))
        window_width = self.getWindowWidthFromText(self.text)
        edit_width = self.getEditWidthFromWindowWidth(window_width)

        try:
            with ExitStack() as cleanup:
                # Unwind: destroy edit, restore input state, disable IME, hide caret, repaint.
                cleanup.enter_context(_cleanup_on_exit(window.paint, self.paint_flag))
                cleanup.enter_context(_cleanup_on_exit(window.setCursorPos, -1, -1))
                cleanup.enter_context(_cleanup_on_exit(window.enableIme, False))
                with _TemporaryInputState(window) as state:
                    self.edit = ckit.EditWidget(
                        window, self.title_width, window.height() - 1, edit_width, 1,
                        self.text, self.selection, auto_complete=self.auto_complete,
                        no_bg=False, autofix_list=self.autofix_list, update_handler=self._onUpdate,
                        candidate_handler=self.candidate_handler,
                        candidate_remove_handler=self.candidate_remove_handler,
                    )
                    with _cleanup_on_exit(self.edit.destroy):
                        state.set(commandline_edit=self.edit)
                        self.edit.setImeRect((0, 0, ini_settings.GEOMETRY_MAX_WIDTH.get(clnch_ini), 1))
                        state.set(keydown_hook=self._onKeyDown, char_hook=self._onChar,
                                  mouse_event_mask=True, status_bar_paint_hook=self._onPaint)
                        self.updateWindowWidth(self.text)
                        window.paint(self.paint_flag)
                        window.removeKeyMessage()
                        window.messageLoop(self._checkContinue)
        finally:
            self.edit = None

        # Public operations still target the restored input, as in nested commandLine calls.
        for command, info, history in self.planned_command_list:
            self.executeCommand(command, info, history, quit=False)
        return self.result

    def _checkContinue(self):
        return self.window.isLauncherActive() or len(self.window.commandline_edit.getText()) > 0

    def _onKeyDown(self, vk, mod):
        if self.keydown_handler and self.keydown_handler(self, vk, mod):
            return True

        if self.window.commandline_edit.onKeyDown(vk, mod):
            return True

        if vk == VK_RETURN:
            self.result = self.window.commandline_edit.getText()
            if self.enter_handler:
                self.window.commandline_edit.closeList()
                if self.enter_handler(self, self.result, mod):
                    self.paint()
                    return True
            self.quit()

        elif vk == VK_ESCAPE:
            if self.window.commandline_edit.getText():
                self.window.commandline_edit.clear()
            elif self.window.console_window.isVisible():
                self.window.console_window.show(False)
            else:
                if self.escape_handler and self.escape_handler(self):
                    return True
                self.quit()

        return True

    def _onChar(self, ch, mod):
        if self.char_handler and self.char_handler(self, ch, mod):
            return True

        edit = self.window.commandline_edit
        if (self.preserve_argument_text and ch == ord(";")
                and (";" in edit.getText()[:min(edit.getSelection())]
                     or edit.getText().lower().startswith(("http:", "https:")))):
            autofix = edit.autofix_list
            try:
                edit.autofix_list = [group for group in autofix or [] if ";" not in group]
                edit.onChar(ch, mod)
            finally:
                edit.autofix_list = autofix
        else:
            edit.onChar(ch, mod)

        return True

    def _normalize(self, update_info):
        raw_start = len(update_info.text)
        if self.preserve_argument_text:
            if update_info.text.lower().startswith(("http:", "https:")):
                raw_start = 0
            elif ";" in update_info.text:
                raw_start = update_info.text.index(";") + 1
        update_info.text = (clnch_misc.normalizeCommandLineText(update_info.text[:raw_start])
                            + update_info.text[raw_start:])

    def _onUpdate(self, update_info):
        self._normalize(update_info)

        if self.update_handler and not self.update_handler(update_info):
            return False

        if self.status_handler:
            self.status_string = self.status_handler(update_info)
            self.window.paint(self.paint_flag)

        self.updateWindowWidth(update_info.text)

    def _getStatusText(self):
        return "  " + self.status_string + " " if self.status_string else ""

    def _onPaint(self, x, y, width, height):
        status_string_for_paint = self._getStatusText()
        status_width = self.window.getStringWidth(status_string_for_paint)
        edit_width = width - self.title_width - status_width

        attr = ckit.Attribute(fg=ckit.getColor("bar_fg"))

        if self.window.active:
            self.window.putString(x, y, self.title_width, height, attr, self.title)
            self.window.putString(
                x + width - status_width,
                y,
                status_width,
                height,
                attr,
                status_string_for_paint,
            )
        else:
            self.window.putString(x, y, self.title_width, height, attr, " " * self.title_width)
            self.window.putString(
                x + width - status_width,
                y,
                status_width,
                height,
                attr,
                " " * status_width,
            )

        self.window.commandline_edit.setPosSize(x + self.title_width, y, edit_width, height)

        self.window.commandline_edit.enableCursor(self.window.active)
        if not self.window.active:
            self.window.setCursorPos(-1, -1)

        self.window.commandline_edit.paint()

    def paint(self):
        # Update the window size and scroll position.
        text = self.window.commandline_edit.getText()
        selection = self.window.commandline_edit.getSelection()
        self.updateWindowWidth(text)
        self.window.commandline_edit.makeVisible(selection[0])
        self.window.commandline_edit.makeVisible(selection[1])

        self.window.paint()

    def getText(self):
        return self.window.commandline_edit.getText()

    def setText(self, text):
        self.window.commandline_edit.setText(text)

    def getSelection(self):
        return self.window.commandline_edit.getSelection()

    def setSelection(self, selection):
        self.window.commandline_edit.setSelection(selection)

    def selectAll(self):
        text = self.window.commandline_edit.getText()
        self.setSelection([0, len(text)])

    def getWindowWidthFromText(self, text):
        edit_width = self.window.getStringWidth(text) + 2

        status_width = self.window.getStringWidth(self._getStatusText())

        window_width = self.title_width + edit_width + status_width

        window_width = max(
            window_width, ini_settings.GEOMETRY_MIN_WIDTH.get(clnch_ini)
        )
        window_width = min(
            window_width, ini_settings.GEOMETRY_MAX_WIDTH.get(clnch_ini)
        )

        return window_width

    def getEditWidthFromWindowWidth(self, window_width):
        status_width = self.window.getStringWidth(self._getStatusText())

        edit_width = window_width - self.title_width - status_width

        return edit_width

    def updateWindowWidth(self, text):
        window_width = self.getWindowWidthFromText(text)
        if window_width == self.window.width():
            return
        window_rect = self.window.getWindowRect()
        self.window.setPosSize(
            window_rect[0], window_rect[1], window_width, self.window.height(), 0
        )

    def planCommand(self, command, info, history):
        self.planned_command_list.append((command, info, history))

    def executeCommand(self, command, info, history_item, quit):
        try:
            result = command(info)
        except Exception as e:  # noqa: BLE001  # Report custom command failures without interrupting input.
            print(e)
            return

        if isinstance(result, str):
            # Deferred commands may have no input to restore after a top-level session.
            if self.window.commandline_edit is not None:
                self.setText(result)
                self.setSelection([0, len(result)])
                self.paint()
            return

        if history_item is not None:
            self.appendHistory(history_item)

        if quit:
            self.quit()

    def appendHistory(self, newentry):
        if newentry == "" or self.window.input_settings["HISTORY_MODE"] == "off":
            return

        # Normalize the command-line text.
        name, separator, raw = newentry.partition(";") if self.preserve_argument_text else (newentry, "", "")
        if not (self.preserve_argument_text and newentry.lower().startswith(("http:", "https:"))):
            newentry = clnch_misc.normalizeCommandLineText(name) + separator + raw

        # Remove the first case-insensitive match from the existing history.
        newentry_lower = newentry.lower()
        for i in range(len(self.window.commandline_history)):
            if self.window.commandline_history[i].lower() == newentry_lower:
                del self.window.commandline_history[i]
                break

        # Insert at the beginning.
        self.window.commandline_history.insert(0, newentry)

        # Keep at most 1,000 entries.
        if len(self.window.commandline_history) > 1000:
            self.window.commandline_history = self.window.commandline_history[:1000]

    def quit(self):
        self.updateWindowWidth("")
        self.window.quit()

