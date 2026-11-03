import ctypes
import os
import subprocess
from contextlib import ExitStack
from ctypes import wintypes

import clnch_misc
import clnch_modifierconfig
import clnch_msgbox
import clnch_strings as strings
from clnch_cmddraft import CommandDraft, DraftValidationError
from clnch_cmdstore import (
    MODIFIERS,
    VIEW_MODES,
    load_commands,
    save_commands,
    validate_link,
)

import ckit
import clnch_native
from ckit.ckit_const import (
    MODKEY_ALT,
    MODKEY_SHIFT,
    ORIGIN_X_CENTER,
    ORIGIN_X_LEFT,
    ORIGIN_Y_CENTER,
    ORIGIN_Y_TOP,
    VK_1,
    VK_2,
    VK_3,
    VK_C,
    VK_E,
    VK_ESCAPE,
    VK_LEFT,
    VK_NEXT,
    VK_PRIOR,
    VK_RETURN,
    VK_RIGHT,
    VK_S,
    VK_SPACE,
    VK_TAB,
    VK_X,
)
from ckit.ckit_misc import _cleanup_on_exit

JSON_PATH = os.path.join(clnch_misc._require_data_path(ckit.dataPath()), "commands.json")
_SetFocus = ctypes.WinDLL("user32").SetFocus
_SetFocus.argtypes = (wintypes.HWND,)
_SetFocus.restype = wintypes.HWND

# Character-cell units.
WINDOW_WIDTH = 66
LABEL_X = 1
ROW_START = 1
ROW_STEP = 2
CONTROL_GAP = 8  # Spacing between controls and at the top/bottom at 100% scaling, in pixels.

FIELD_DEFS = [
    ("name", strings.FIELD_NAME, "n"),
    ("link", strings.FIELD_LINK, "l"),
    ("args", strings.FIELD_ARG, "a"),
    ("workdir", strings.FIELD_WORKDIR, "w"),
]
CHOICE_FIELD_DEFS = [
    ("view_mode", strings.FIELD_VIEW_MODE, "v"),
    ("modifier", strings.FIELD_MODIFIER, "m"),
]
VIEW_KEYS = (VK_1, VK_2, VK_3)
MODIFIER_KEYS = (VK_E, VK_C, VK_S, VK_X)
MODIFIER_LABELS = (
    strings.MODIFIER_NONE,
    strings.MODIFIER_CTRL,
    strings.MODIFIER_SHIFT,
    strings.MODIFIER_CTRL_SHIFT,
)


class CommandEditor(ckit.TextWindow):
    def __init__(self, main_window, target_cmd=None, on_saved=None, dropped_files=None, parent_window=None):
        self.main_window = main_window
        parent_window = main_window if parent_window is None else parent_window
        self._row_gap = round(CONTROL_GAP * parent_window.getDisplayScaling())
        self._row_planes = {}
        self._scroll_y = 0
        self._window_width = WINDOW_WIDTH
        self._window_height = 17
        self._row_positions = {}
        self._viewport_height = 1
        self.result_saved = False
        self.commands_changed = False
        self.active = False
        self.load_error = None
        self.draft = CommandDraft(self._load_commands(), target_cmd)
        values = {"name": self.draft.name, **self.draft.current_action}

        if self.draft.is_edit_mode:
            if target_cmd:
                title = strings.EDITOR_TITLE.format(name=target_cmd)
            else:
                title = strings.EDITOR_EMPTY_TITLE
        else:
            title = strings.EDITOR_NEW_TITLE
        self._title = title

        rect = parent_window.getWindowRect()
        center_x = (rect[0] + rect[2]) // 2
        center_y = (rect[1] + rect[3]) // 2

        ckit.TextWindow.__init__(
            self,
            x=center_x,
            y=center_y,
            width=WINDOW_WIDTH,
            height=17,
            origin=ORIGIN_X_CENTER | ORIGIN_Y_CENTER,
            parent_window=parent_window,
            bg_color=ckit.getColor("bg"),
            cursor0_color=ckit.getColor("cursor0"),
            cursor1_color=ckit.getColor("cursor1"),
            cursor=True,  # Enable the caret.
            show=False,
            resizable=False,
            title=title,
            minimizebox=False,
            maximizebox=False,
            activate_handler=self._on_activate,
            close_handler=self._on_cancel,
            keydown_handler=self._on_keydown,
            char_handler=self._on_char,
            lbuttondown_handler=self._on_left_button_down,
            dropfiles_handler=self._on_drop_files,
            mousewheel_handler=self._on_mousewheel,
            dpi_handler=self._on_dpi,
            move_handler=self._on_move,
        )

        self.edits = []
        self.edit_by_id = {}

        with _cleanup_on_exit(self.destroy, error_only=True):
            for i, (field_id, label, _acc_key) in enumerate(FIELD_DEFS):
                row = ROW_START + i * ROW_STEP
                value = values.get(field_id, "")
                edit = ckit.EditWidget(
                    self,
                    0,
                    row,
                    47,
                    1,
                    value,
                    selection=[len(value), len(value)],
                    auto_complete=False,
                    no_bg=False,
                )
                self.edits.append(edit)
                self.edit_by_id[field_id] = edit

            self.view_choice = ckit.ChoiceWidget(
                self,
                0,
                9,
                47,
                1,
                "",
                [
                    strings.ACCESS_LABEL.format(label=label, key=chr(key))
                    for label, key in zip(
                        (
                            strings.VIEW_NORMAL,
                            strings.VIEW_MINIMIZED,
                            strings.VIEW_MAXIMIZED,
                        ),
                        VIEW_KEYS,
                    )
                ],
                VIEW_MODES.index(values.get("view_mode", "normal")),
            )
            self.modifier_choice = ckit.ChoiceWidget(
                self,
                0,
                11,
                47,
                1,
                "",
                [
                    strings.ACCESS_LABEL.format(label=label, key=chr(key))
                    for label, key in zip(MODIFIER_LABELS, MODIFIER_KEYS)
                ],
                0,
            )
            self.controls = self.edits + [self.view_choice, self.modifier_choice]
            self.focus_index = 1 if self.draft.empty_command else 0
            self.view_choice.row_step = self.modifier_choice.row_step = ROW_STEP
            self._layout()
            if parent_window is main_window:
                clnch_misc.adjustWindowPosition(parent_window, self, default_up=False)
            else:
                rect = parent_window.getWindowRect()
                self.setPosSize(rect[2], rect[1], self.width(), self.height(), ORIGIN_X_LEFT | ORIGIN_Y_TOP)
                ckit.fitWindowToWorkArea(self)
            if dropped_files:
                self._apply_drop("link", dropped_files, suggest_name=True)
            self._update_focus(select_text=True)

            self.paint()
            self.show(True)
            if dropped_files:
                self.foreground()
            self.activate()
            _SetFocus(self.getHWND())

    # ------------------------------------------------------------------
    # Store and draft connections
    # ------------------------------------------------------------------

    def _load_commands(self):
        try:
            return load_commands(JSON_PATH, validation="editor")
        except Exception as e:  # noqa: BLE001  # Keep load failures visible and prevent saving unread command data.
            self.load_error = str(e)
            return {}

    def _store_action(self):
        action = {
            field: self.edit_by_id[field].getText()
            for field in ("link", "args", "workdir")
        }
        action["view_mode"] = VIEW_MODES[self.view_choice.getValue()]
        self.draft.update_current(self.edit_by_id["name"].getText(), action)

    def _switch_modifier(self):
        index = self.modifier_choice.getValue()
        if index == self.draft.modifier_index:
            return
        self._store_action()
        values = self.draft.switch_modifier(index)
        for field in ("link", "args", "workdir"):
            text = values.get(field, "")
            self.edit_by_id[field].setText(text)
            self.edit_by_id[field].setSelection([len(text), len(text)])
        self.view_choice.select = VIEW_MODES.index(values.get("view_mode", "normal"))
        self._update_focus()
        self.paint()

    def _save(self):
        if self.load_error is not None:
            self._show_error(
                strings.ERROR_LOAD_TITLE,
                strings.COMMAND_LOAD_BLOCKED.format(error=self.load_error),
            )
            return False
        self._store_action()
        try:
            commands_data = self.draft.build_commands()
        except DraftValidationError as error:
            if error.code == "invalid_name":
                message = strings.COMMAND_NAME_ERROR.format(name=self.draft.name)
            elif error.code == "duplicate":
                message = strings.COMMAND_DUPLICATE
            elif error.code == "modifier_link_required":
                message = strings.MODIFIER_LINK_REQUIRED.format(
                    modifier=MODIFIER_LABELS[MODIFIERS.index(error.modifier)]
                )
            else:
                message = strings.COMMAND_LINK_REQUIRED
            self._show_error(strings.ERROR_INPUT_TITLE, message)
            return False

        try:
            for action in commands_data[self.draft.name].values():
                link = action["link"].strip()
                if link.lower() not in commands_data:
                    expanded = clnch_misc.replaceMacro(link, environ=True)
                    # Runtime arguments are unavailable in the editor; validate them at execution.
                    if not expanded.strip('"').startswith("%param%"):
                        validate_link(expanded, self.draft.name)
        except ValueError:
            self._show_error(strings.ERROR_INPUT_TITLE, strings.COMMAND_RELATIVE_LINK_GUI)
            return False

        try:
            saved_data = save_commands(JSON_PATH, commands_data, self.draft.original_commands)
        except Exception as e:  # noqa: BLE001  # Report save failures and keep the editor open for retry.
            self._show_error(
                strings.ERROR_SAVE_TITLE,
                strings.COMMAND_SAVE_ERROR.format(error=e),
            )
            return False

        self.commands_changed = saved_data != self.draft.original_commands
        self.result_saved = True
        self.quit()
        return True

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _row_y(self, row):
        return self._row_positions.get(row, 0)

    def width(self):
        return self._window_width

    def height(self):
        return self._window_height

    def setPosSize(self, x, y, width, height, origin):
        return self.setPositionAndSize(
            x, y, width * self.getCharSize()[0] + 2, self._viewport_height + 2, origin
        )

    def charToClient(self, x, y):
        return (1 + x * self.getCharSize()[0], 1 + self._row_y(y) - self._scroll_y)

    def charToScreen(self, x, y):
        return self.clientToScreen(*self.charToClient(x, y))

    def putString(self, x, y, width, height, attr, text, offset=0):
        if y in self._row_planes:
            return self._row_planes[y].putString(
                x, 0, width, height, attr, text, offset
            )

    def setCursorPos(self, x, y):
        if x < 0 or y < 0:
            return super().setCursorPos(x, y)
        return self._row_planes[y].setCaretPosition(x, 0)

    def destroy(self):
        with ExitStack() as cleanup:
            cleanup.enter_context(_cleanup_on_exit(super().destroy))
            for plane in reversed(list(self._row_planes.values())):
                cleanup.enter_context(_cleanup_on_exit(plane.destroy))
            for edit in reversed(self.edits):
                cleanup.enter_context(_cleanup_on_exit(edit.destroy))

    def _layout(self):
        max_width, max_height = ckit.getWindowSizeLimits(self)
        self._size_limits = (max_width, max_height)
        labels = [
            strings.ACCESS_LABEL.format(label=label, key=key.upper())
            for _, label, key in FIELD_DEFS + CHOICE_FIELD_DEFS
        ]
        if self.draft.empty_command:
            labels[0] = strings.FIELD_NAME
        label_width = max(map(self.getStringWidth, labels))
        choice_width = max(
            sum(self.getStringWidth(s) + 2 for s in choice.item_list) + 2
            for choice in (self.view_choice, self.modifier_choice)
        )
        self._window_width = min(
            max_width,
            max(
                WINDOW_WIDTH,
                self.getStringWidth(self._title) + 4,
                label_width + 3 + max(47, choice_width),
            ),
        )
        stacked = label_width + 3 + 20 > self.width()
        self.edit_x = 2 if stacked else label_width + 3
        edit_width = self.width() - self.edit_x - 2
        char_w, char_h = self.getCharSize()
        self._row_positions = {}
        self._label_draws = []
        row, pixel = ROW_START, self._row_gap

        def lines(count, gap=True):
            nonlocal row, pixel
            first = row
            for _ in range(count):
                self._row_positions[row] = pixel
                self._row_positions[row + 1] = pixel + char_h
                pixel += char_h
                row += ROW_STEP
            if gap:
                pixel += self._row_gap
            return first

        for control, label in zip(self.controls, labels):
            if stacked:
                wrapped = ckit.splitLines(self, label, self.width() - 3)
                label_row = lines(len(wrapped), gap=False)
                self._label_draws += [
                    (LABEL_X, label_row + i * ROW_STEP, line)
                    for i, line in enumerate(wrapped)
                ]
            control.setPosSize(self.edit_x, row, edit_width, 1)
            count = 1
            if control in (self.view_choice, self.modifier_choice):
                count = (
                    max(y + h for x, y, w, h, parts in control.itemRects()) - row + 1
                ) // ROW_STEP
                control.setPosSize(self.edit_x, row, edit_width, count * ROW_STEP - 1)
            if not stacked:
                self._label_draws.append((LABEL_X, row, label))
            lines(count)

        hints = [strings.MODIFIER_NONE_HINT] + [
            strings.MODIFIER_DEFAULT_HINT.format(description=value)
            for value in (
                *clnch_modifierconfig.ACTIONS.values(),
                strings.MAPPING_MISSING_BOTH,
                strings.MAPPING_MISSING_SOURCE,
                strings.MAPPING_MISSING_DESTINATION,
            )
        ]
        self._hint_row = lines(
            max(len(ckit.splitLines(self, hint, self.width() - 3)) for hint in hints)
        )
        self._guide_lines = ckit.splitLines(
            self, strings.EDITOR_GUIDE, self.width() - 3
        )
        self._guide_row = lines(len(self._guide_lines))
        self._window_height = row
        self._content_height = pixel
        self._viewport_height = min(pixel, max_height * char_h)
        self._row_positions[row] = pixel
        self._scroll_y = min(self._scroll_y, max(0, pixel - self._viewport_height))
        for plane in self._row_planes.values():
            plane.destroy()
        self._row_planes = {}
        for y in range(ROW_START, row, ROW_STEP):
            plane = ckit.TextPlane(
                self, self.charToClient(0, y), (self.width() * char_w, char_h), 0.0
            )
            self._row_planes[y] = plane
            plane.setFont(self.getFont())
        rect = self.getWindowRect()
        self.setPosSize(
            rect[0], rect[1], self.width(), self.height(), ORIGIN_X_LEFT | ORIGIN_Y_TOP
        )

    def _scroll(self, delta):
        self._scroll_y = max(
            0, min(self._scroll_y + delta, self._content_height - self._viewport_height)
        )
        for row, plane in self._row_planes.items():
            plane.setPosition(self.charToClient(0, row))
        for control in self.controls:
            control.setPosSize(control.x, control.y, control.width, control.height)

    def _ensure_visible(self):
        control = self.controls[self.focus_index]
        top = self._row_y(control.y)
        bottom = self._row_y(control.y + control.height)
        if (
            control is self.modifier_choice
            and self._content_height - top <= self._viewport_height
        ):
            bottom = self._content_height
        if top < self._scroll_y:
            self._scroll(top - self._scroll_y)
        elif bottom > self._scroll_y + self._viewport_height:
            self._scroll(
                min(
                    top - self._scroll_y,
                    bottom - self._scroll_y - self._viewport_height,
                )
            )

    def _on_mousewheel(self, x, y, wheel, mod):
        self._scroll(-round(wheel * 3 * self.getCharSize()[1]))
        self.paint()

    def _on_dpi(self, scale):
        if not self._row_planes:
            return
        self.setFontFromFontObject(clnch_misc.getDialogFont(scale))
        self._row_gap = round(CONTROL_GAP * scale)
        self._layout()
        self._ensure_visible()
        ckit.fitWindowToWorkArea(self)
        self._update_focus()
        self.paint()

    def _on_move(self, x, y):
        if self._row_planes and ckit.getWindowSizeLimits(self) != self._size_limits:
            self._on_dpi(self.getDisplayScaling())

    def _show_error(self, title, message):
        # Use ReCraftLaunch's standard message box.
        clnch_msgbox.popMessageBox(
            self,
            clnch_msgbox.MSGBOX_TYPE_OK,
            title,
            message,
        )

    def _on_activate(self, active):
        self.active = active
        self._update_focus()
        self.paint()

    def _on_cancel(self):
        self.result_saved = False
        self.quit()

    def _move_focus(self, delta):
        self.focus_index = (self.focus_index + delta) % len(self.controls)
        if self.draft.empty_command and self.focus_index == 0:
            self.focus_index = (self.focus_index + delta) % len(self.controls)
        self._update_focus(select_text=True)
        self.paint()

    def _focus_field(self, field_id):
        if self.draft.empty_command and field_id == "name":
            return
        fields = [field[0] for field in FIELD_DEFS + CHOICE_FIELD_DEFS]
        for i, fid in enumerate(fields):
            if fid == field_id:
                self.focus_index = i
                self._update_focus(select_text=True)
                self.paint()
                break

    def _update_focus(self, select_text=False):
        self._ensure_visible()
        if select_text and self.focus_index < len(self.edits):
            edit = self.edits[self.focus_index]
            edit.setSelection([0, len(edit.getText())])
        for i, edit in enumerate(self.controls):
            edit.enableCursor(self.active and i == self.focus_index)
            if not (self.draft.empty_command and i == 0):
                edit.paint()

    def _on_keydown(self, vk, mod):
        if vk in (VK_PRIOR, VK_NEXT):
            self._scroll((-1 if vk == VK_PRIOR else 1) * self._viewport_height)
            self.paint()
            return True
        # Tab / Shift+Tab: move focus.
        if vk == VK_TAB:
            if mod & MODKEY_SHIFT:
                self._move_focus(-1)
            else:
                self._move_focus(1)
            return True

        # Enter: save.
        if vk == VK_RETURN:
            self._save()
            return True

        # Esc: cancel.
        if vk == VK_ESCAPE:
            self._on_cancel()
            return True

        # Alt+access key: focus or select the corresponding control.
        if mod & MODKEY_ALT:
            modifier_keys = {key: i for i, key in enumerate(MODIFIER_KEYS)}
            if vk in modifier_keys:
                self._focus_field("modifier")
                self.modifier_choice.select = modifier_keys[vk]
                self._switch_modifier()
                return True
            view_keys = {key: i for i, key in enumerate(VIEW_KEYS)}
            if vk in view_keys:
                self._focus_field("view_mode")
                self.view_choice.select = view_keys[vk]
                self.paint()
                return True
            access_map = {
                ord(key.upper()): field
                for field, label, key in FIELD_DEFS + CHOICE_FIELD_DEFS
            }
            field_id = access_map.get(vk)
            if field_id:
                self._focus_field(field_id)
                return True

        control = self.controls[self.focus_index]
        if (
            control in (self.view_choice, self.modifier_choice)
            and vk in (VK_LEFT, VK_RIGHT, VK_SPACE)
            and mod in (0, MODKEY_SHIFT)
        ):
            delta = (
                -1 if vk == VK_LEFT or (vk == VK_SPACE and mod == MODKEY_SHIFT) else 1
            )
            control.select = (control.select + delta) % len(control.item_list)
        else:
            control.onKeyDown(vk, mod)
        if control is self.modifier_choice:
            self._switch_modifier()
        self.paint()
        return True

    def _on_char(self, ch, mod):
        if self.focus_index < len(self.edits):
            self.edits[self.focus_index].onChar(ch, mod)
        return True

    def _apply_drop(self, field, filenames, suggest_name=False):
        if not filenames or (self.draft.empty_command and field == "name"):
            return
        # Join multiple paths into one string using Windows argument quoting for every field.
        text = (
            filenames[0]
            if len(filenames) == 1 and field != "args"
            else subprocess.list2cmdline(filenames)
        )
        values = {field: text}
        mode = None
        filename = filenames[0]
        is_directory = os.path.isdir(filename)
        if field == "link" and len(filenames) == 1:
            ext = "" if is_directory else os.path.splitext(filename)[1].lower()
            try:
                if ext == ".lnk":
                    link, args, workdir, show = clnch_native.getShellLinkInfo(filename)
                    values.update(link=link, args=args, workdir=workdir)
                    mode = (
                        "maximized"
                        if show == 3
                        else "minimized"
                        if show in (2, 6, 7, 11)
                        else "normal"
                    )
                elif ext == ".url":
                    values.update(
                        link=clnch_native.getInternetShortcutInfo(filename),
                        args="",
                        workdir="",
                    )
                elif suggest_name:
                    values["workdir"] = filename if is_directory else os.path.dirname(filename)
            except Exception as error:  # noqa: BLE001  # Report drop-resolution failures without closing the editor.
                self._show_error(strings.ERROR_DROP_TITLE, str(error))
                return
        if suggest_name and not self.draft.empty_command and not self.edit_by_id["name"].getText():
            name = os.path.basename(os.path.normpath(filename))
            if not is_directory:
                name = os.path.splitext(name)[0]
            values["name"] = "".join(ch for ch in name if ch != ";" and not ch.isspace())
        for key, value in values.items():
            self.edit_by_id[key].setText(value)
            self.edit_by_id[key].setSelection([len(value), len(value)])
        if mode is not None:
            self.view_choice.select = VIEW_MODES.index(mode)
        self.paint()

    def _on_drop_files(self, x, y, filenames):
        field = "link"
        for index, (key, _, _) in enumerate(FIELD_DEFS):
            edit = self.edits[index]
            left, top = self.charToClient(edit.x, edit.y)
            right, bottom = self.charToClient(edit.x + edit.width, edit.y + edit.height)
            if left <= x < right and max(1, top) <= y < min(
                self._viewport_height + 1, bottom
            ):
                if self.draft.empty_command and key == "name":
                    return
                field = key
                self.focus_index = index
                break
        self._apply_drop(field, filenames)
        self._update_focus()
        self.paint()

    def _on_left_button_down(self, x, y, mod):
        for index, control in enumerate(self.controls):
            left, top = self.charToClient(control.x, control.y)
            right, bottom = self.charToClient(
                control.x + control.width, control.y + control.height
            )
            if left <= x < right and max(1, top) <= y < min(
                self._viewport_height + 1, bottom
            ):
                if self.draft.empty_command and index == 0:
                    return True
                self.focus_index = index
                if control in (self.view_choice, self.modifier_choice):
                    for selected, (column, row, width, height, parts) in enumerate(
                        control.itemRects()
                    ):
                        item_left, item_top = self.charToClient(column, row)
                        item_right, item_bottom = self.charToClient(
                            column + width, row + height
                        )
                        if item_left <= x < item_right and item_top <= y < item_bottom:
                            control.select = selected
                            break
                    if control is self.modifier_choice:
                        self._switch_modifier()
                self._update_focus()
                self.paint()
                return True
        return False

    def paint(self):
        attr = ckit.Attribute(fg=ckit.getColor("fg"))

        # Clear the background.
        for y in range(self.height()):
            self.putString(0, y, self.width(), 1, attr, " " * self.width())

        # Draw labels.
        for column, row, label in self._label_draws:
            self.putString(column, row, self.width() - column - 1, 1, attr, label)
        if self.active:
            self.putString(0, self.controls[self.focus_index].y, 1, 1, attr, ">")

        # Draw input controls.
        for i, edit in enumerate(self.controls):
            if self.draft.empty_command and i == 0:
                self.putString(
                    edit.x + 1, edit.y, edit.width - 1, 1,
                    ckit.Attribute(fg=ckit.getHintColor()), strings.COMMAND_EMPTY,
                )
            else:
                edit.paint()
        if self.draft.modifier_index == 0:
            hint = strings.MODIFIER_NONE_HINT
        else:
            modifier = clnch_modifierconfig.MODIFIERS[self.draft.modifier_index - 1][0]
            settings = self.main_window.modifier_settings
            action = settings[modifier + "_ACTION"]
            description = clnch_modifierconfig.ACTIONS[action]
            if action == "mapped_folder":
                sources = settings["SOURCE_ROOTS"]
                destination = settings[modifier + "_DESTINATION_ROOT"]
                if not sources and not destination:
                    description = strings.MAPPING_MISSING_BOTH
                elif not sources:
                    description = strings.MAPPING_MISSING_SOURCE
                elif not destination:
                    description = strings.MAPPING_MISSING_DESTINATION
            hint = strings.MODIFIER_DEFAULT_HINT.format(description=description)
        hint_attr = ckit.Attribute(fg=ckit.getHintColor())
        for i, line in enumerate(ckit.splitLines(self, hint, self.width() - 3)):
            self.putString(
                2, self._hint_row + i * ROW_STEP, self.width() - 3, 1, hint_attr, line
            )

        # Draw the operation guide; Enter/Esc are window-wide default actions.
        for i, line in enumerate(self._guide_lines):
            width = self.getStringWidth(line)
            self.putString(
                max(1, self.width() - width - 2),
                self._guide_row + i * ROW_STEP,
                width,
                1,
                attr,
                line,
            )


def open_editor(main_window, target_cmd=None, on_saved=None, dropped_files=None, on_shown=None, parent_window=None):
    # Keep the immediate parent visible throughout the modal interaction.
    parent_window = main_window if parent_window is None else parent_window
    was_enabled = parent_window.isEnabled()
    editor = CommandEditor(
        main_window=main_window,
        target_cmd=target_cmd,
        on_saved=on_saved,
        dropped_files=dropped_files,
        parent_window=parent_window,
    )

    # Wait modally within the ReCraftLaunch process.
    with clnch_misc._modal_dialog_scope(parent_window, editor, was_enabled):
        parent_window.enable(False)
        if on_shown:
            on_shown()
        editor.messageLoop()
        saved = editor.result_saved
        saved_key = editor.draft.name if saved else None

    if saved and editor.commands_changed and on_saved:
        on_saved()

    return saved_key
