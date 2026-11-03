import os
from contextlib import ExitStack, contextmanager

import clnch_ini
import clnch_inisettings as ini_settings
import clnch_isearch
import clnch_listwindow
import clnch_misc
import clnch_msgbox
import clnch_strings as strings
from clnch_cmdstore import duplicate_command, load_commands, save_commands

import ckit
from ckit import MODKEY_CTRL, VK_DELETE, VK_E, VK_INSERT
from ckit.ckit_misc import _cleanup_on_exit

EMPTY_LABEL = strings.COMMAND_EMPTY


class CommandListWindow(clnch_listwindow.ListWindow):
    def configure(self):
        super().configure()
        if ckit.KeyEvent(ckit.VK_F, MODKEY_CTRL) not in self.keymap.table:
            self.keymap["C-F"] = self.command.IncrementalSearch

    def command_IncrementalSearch(self, info):
        if self.isearch:
            return
        self.removeKeyMessage()
        self._search_items = self.items
        self._search_key = self.items[self.select][1] if 0 <= self.select < len(self.items) else None
        self.isearch = clnch_isearch.IncrementalSearch()
        self.keydown_hook_old = self.keydown_hook
        self.keydown_hook = self._onSearchKeyDown
        self.paint()

    def _setSearchItems(self, query):
        if 0 <= self.select < len(self.items):
            self._search_key = self.items[self.select][1]
        query = query.casefold()
        self.items = (
            [item for item in self._search_items if item[1] and query in item[1].casefold()]
            if query else self._search_items
        )
        self.select = next(
            (i for i, item in enumerate(self.items) if item[1] == self._search_key),
            0 if self.items else -1,
        )
        # Rebuild wrapped rows as well as the window size when candidates change.
        rect = self.getWindowRect()
        self._layout((rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2)
        self.scroll_info.pos = 0
        if self.select >= 0:
            self.scroll_info.makeVisible(self.select, self.itemsHeight())
        ckit.fitWindowToWorkArea(self)
        self.paint()

    def onChar(self, ch, mod):
        if not self.isearch:
            return super().onChar(ch, mod)
        if ch == ord("\b"):
            self.isearch.isearch_value = self.isearch.isearch_value[:-1]
        elif ch >= 0x20 and ch != 0x7f:
            self.isearch.isearch_value += chr(ch)
        else:
            return
        self._setSearchItems(self.isearch.isearch_value)

    def _onSearchKeyDown(self, vk, mod):
        if vk in (ckit.VK_RETURN, ckit.VK_ESCAPE):
            self.isearch = None
            self.keydown_hook = self.keydown_hook_old
            self._setSearchItems("")
        elif self.items:
            commands = {
                ckit.VK_UP: self.command.CursorUp,
                ckit.VK_DOWN: self.command.CursorDown,
                ckit.VK_HOME: self.command.CursorFirst,
                ckit.VK_END: self.command.CursorLast,
            }
            if vk in commands:
                commands[vk](ckit.CommandInfo())
            elif vk in (ckit.VK_PRIOR, ckit.VK_NEXT):
                # The shared page commands pause during incremental search.
                if vk == ckit.VK_PRIOR:
                    self.select = max(
                        0, self.scroll_info.pos if self.select > self.scroll_info.pos
                        else self.select - self.itemsHeight(),
                    )
                else:
                    page_end = self.scroll_info.pos + self.itemsHeight() - 1
                    self.select = min(
                        len(self.items) - 1,
                        page_end if self.select < page_end else self.select + self.itemsHeight(),
                    )
                self.scroll_info.makeVisible(self.select, self.itemsHeight())
                self.paint()
        return True

    def getResult(self):
        result = super().getResult()
        if self.isearch:
            index, _result_mod = clnch_listwindow._split_list_result(result)
            if index >= 0:
                # open_list actions use indices in the original, unfiltered items.
                index = self._search_items.index(self.items[index])
                return (index, result[1]) if isinstance(result, tuple) else index
        return result

    def destroy(self):
        if self.isearch:
            self.keydown_hook = self.keydown_hook_old
            self.isearch = None
        super().destroy()


def _confirm_delete(window, cmd_name):
    display_name = EMPTY_LABEL if cmd_name == "" else cmd_name
    ret = clnch_msgbox.popMessageBox(
        window,
        clnch_msgbox.MSGBOX_TYPE_YESNO,
        strings.COMMAND_DELETE_TITLE,
        strings.COMMAND_DELETE_CONFIRM.format(name=display_name),
    )
    return ret == clnch_msgbox.MSGBOX_RESULT_YES


def _command_items(commands):
    """Build display rows in the same order for opening and post-delete selection."""
    keys = sorted(commands.keys() | {""}, key=lambda name: (name != "", name.lower()))
    return [(EMPTY_LABEL if name == "" else name, name) for name in keys]


@contextmanager
def _show_list(window, items, selected_key, parent_cleanup, previous_cleanup):
    """Own one list and its callbacks until an optional editor handoff completes."""
    action: dict[str, str | bool | list[str]] = {"type": "edit"}

    def keydown_hook(vk, mod):
        operation = {
            (VK_E, MODKEY_CTRL): "edit",
            (VK_INSERT, 0): "new",
            (VK_INSERT, MODKEY_CTRL): "duplicate",
            (VK_DELETE, 0): "kill",
        }.get((vk, mod))
        if operation is None:
            return False
        action["type"] = operation
        list_window.quit()
        return True

    def dropfiles_handler(x, y, filenames):
        if filenames and not list_window.isearch:
            action.update(type="drop", files=filenames)
            list_window.quit()

    was_enabled = window.isEnabled()
    pos = window.centerOfWindowInPixel()
    initial_select = next((i for i, item in enumerate(items) if item[1] == selected_key), 0)
    list_window = CommandListWindow(
        pos[0], pos[1], 5, 1,
        ini_settings.GEOMETRY_MAX_WIDTH.get(clnch_ini), 16,
        window, False, strings.COMMAND_LIST_TITLE, items,
        initial_select=initial_select,
        onekey_search=True,
        onekey_decide=False,
        return_modkey=False,
        keydown_hook=keydown_hook,
        statusbar_handler=None,
        dropfiles_handler=dropfiles_handler,
        opaque_normal=True,
    )
    with ExitStack() as cleanup:
        cleanup.enter_context(_cleanup_on_exit(list_window.destroy))
        if was_enabled:
            parent_cleanup.enter_context(_cleanup_on_exit(window.activate))
            parent_cleanup.enter_context(_cleanup_on_exit(window.enable, True))
        clnch_misc.adjustWindowPosition(window, list_window, default_up=False)
        list_window.show(True)
        previous_cleanup.close()
        window.enable(False)
        list_window.messageLoop()
        yield list_window, action
        if action.get("reopen"):
            # Keep the old list behind the editor until its replacement is visible.
            previous_cleanup.enter_context(cleanup.pop_all())


def _save_list_commands(window, json_path, commands, on_saved):
    """Distinguish a failed write from a failed callback after a committed save."""
    try:
        save_commands(json_path, commands)
    except Exception as e:  # noqa: BLE001  # Report store failures at the GUI boundary.
        clnch_msgbox.popMessageBox(
            window, clnch_msgbox.MSGBOX_TYPE_OK, strings.ERROR_SAVE_TITLE,
            strings.COMMAND_SAVE_ERROR.format(error=e),
        )
        return False

    if on_saved:
        try:
            on_saved()
        except Exception as e:  # noqa: BLE001  # The file is already saved; preserve its successful selection.
            clnch_msgbox.popMessageBox(
                window, clnch_msgbox.MSGBOX_TYPE_OK, strings.ERROR_TITLE,
                strings.COMMAND_APPLY_ERROR.format(error=e),
            )
    return True


# Display and operate the command list using ckit (clnch_listwindow).
#   window: ReCraftLaunch MainWindow instance.
#   on_saved: callback invoked after saving changes.
#   on_edit: callback that opens the command editor.
#     It receives the list as parent_window for edit, new and drop actions.
def open_list(window, on_saved=None, on_edit=None):
    # Rebuilding the list must not reactivate MainWindow between modal children.
    with ExitStack() as cleanup, ExitStack() as previous_cleanup:
        return _open_list(window, on_saved, on_edit, cleanup, previous_cleanup)


def _open_list(window, on_saved, on_edit, parent_cleanup, previous_cleanup):
    json_path = os.path.join(clnch_misc._require_data_path(ckit.dataPath()), "commands.json")
    current_select_key = None

    while True:
        try:
            commands_data = load_commands(json_path, validation=None)
        except Exception as e:  # noqa: BLE001  # Report unreadable command data and leave the file unchanged.
            clnch_msgbox.popMessageBox(
                window, clnch_msgbox.MSGBOX_TYPE_OK, strings.ERROR_TITLE,
                strings.COMMAND_LOAD_ERROR.format(error=e),
            )
            return

        items = _command_items(commands_data)
        with _show_list(window, items, current_select_key, parent_cleanup, previous_cleanup) as (list_window, action):
            result = list_window.getResult()
            result_idx = None if result is None else clnch_listwindow._split_list_result(result)[0]
            selected_idx = result_idx if result_idx is not None and 0 <= result_idx < len(items) else None
            if selected_idx is not None:
                current_select_key = items[selected_idx][1]
            operation = action["type"]
            if on_edit and (selected_idx is not None or operation == "drop") and operation in ("edit", "new", "drop"):
                options = {"dropped_files": action["files"]} if operation == "drop" else {}
                saved_key = on_edit(
                    current_select_key if operation == "edit" else None,
                    parent_window=list_window, **options,
                )
                if saved_key is not None:
                    current_select_key = saved_key
                action["reopen"] = True
                continue

        if selected_idx is None:
            return

        elif action["type"] == "kill":
            if current_select_key == "":
                clnch_msgbox.popMessageBox(
                    window, clnch_msgbox.MSGBOX_TYPE_OK,
                    strings.COMMAND_LIST_TITLE, strings.COMMAND_EMPTY_DELETE,
                )
            elif current_select_key in commands_data and _confirm_delete(window, current_select_key):
                candidate = commands_data.copy()
                del candidate[current_select_key]
                if _save_list_commands(window, json_path, candidate, on_saved):
                    new_items = _command_items(candidate)
                    current_select_key = new_items[min(selected_idx, len(new_items) - 1)][1]

        elif action["type"] == "duplicate" and current_select_key in commands_data:
            try:
                candidate, copied_key = duplicate_command(commands_data, current_select_key)
            except ValueError as error:
                clnch_msgbox.popMessageBox(
                    window, clnch_msgbox.MSGBOX_TYPE_OK, strings.ERROR_INPUT_TITLE, str(error),
                )
                continue
            if _save_list_commands(window, json_path, candidate, on_saved):
                current_select_key = copied_key
