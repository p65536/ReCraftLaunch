"""Compose standard registrations, command execution and GUI entry points."""
import os

import clnch_altenterconfig
import clnch_misc
import clnch_strings as strings
from clnch_cmdstore import load_commands
from clnch_commandexecutor import CommandExecutor
from clnch_commandplatform import (
    SystemExecutableCommandline,
    get_mapped_directory,  # noqa: F401  # Preserve the existing helper export.
)
from clnch_commandregistry import CommandRegistry

from ckit import dataPath, setClipboardText


class _CommandUI:
    def __init__(self, window, registry, executor):
        self.window = window
        self.registry = registry
        self.executor = executor

    def reload_commands(self, preserve_custom=True):
        data = load_commands(os.path.join(clnch_misc._require_data_path(dataPath()), "commands.json"))
        self.registry.rebuild(
            self.window.launcher, data, self.executor.make_handler,
            preserve_custom=preserve_custom,
        )

    def copy_path(self, info):
        text = (self.window.commandline_edit.getText().strip()
                if self.window.commandline_edit else "")
        name = text.split(";", 1)[0].strip().lower() if text else ""
        if not name:
            return
        real_path = self.registry.resolve_path(name)
        if real_path:
            try:
                setClipboardText(real_path)
            except Exception:  # noqa: BLE001, S110  # Preserve silent copy failure; reliable reporting needs clipboard API changes.
                pass

    def alt_enter(self, info, key=""):
        text = self.window.commandline_edit.getText() if self.window.commandline_edit else ""
        clnch_altenterconfig.execute(self.window, text, key)

    # These utility actions retain cmd_keymap's input exit without adding history.
    copy_path._append_history = False
    alt_enter._append_history = False
    alt_enter._alt_enter = True
    alt_enter._alt_enter_key = ""
    copy_path._inactivate = True

    def _open_command_editor(self, cmd_name=None, dropped_files=None, on_shown=None, parent_window=None):
        import clnch_cmdeditor

        return clnch_cmdeditor.open_editor(
            self.window,
            target_cmd=cmd_name,
            on_saved=self.reload_commands,
            dropped_files=dropped_files,
            on_shown=on_shown,
            parent_window=parent_window,
        )

    def drop_files(self, files):
        return self._open_command_editor(dropped_files=files)

    def new_command(self, info):
        if not self.window.isEnabled():
            self.window.foreground()
            return
        self._open_command_editor(None)

    def edit_or_list(self, info):
        import clnch_cmdlist

        text = (self.window.commandline_edit.getText().strip()
                if self.window.commandline_edit else "")
        name = text.split(";", 1)[0].strip() if text else ""
        if name:
            self._open_command_editor(name.lower())
        else:
            clnch_cmdlist.open_list(
                self.window,
                on_saved=self.reload_commands,
                on_edit=self._open_command_editor,
            )


def configure(window, commands):
    registry = CommandRegistry(window.launcher.command_list)
    executor = CommandExecutor(window, registry)
    ui = _CommandUI(window, registry, executor)
    for name, target in (("_ra", executor.elevate), ("new", ui.new_command)):
        registry.register(name, executor.make_handler(name, target=target), target)

    # Explicit registrations precede OS lookup and existing URL/file handlers.
    window.commandline_list.insert(1, SystemExecutableCommandline(window))
    window.cmd_keymap["F12"] = ui.copy_path
    window.cmd_keymap["A-Return"] = ui.alt_enter
    for key, (_section, _label, binding) in clnch_altenterconfig.KEYS.items():
        if not key:
            continue
        def alt_enter(info, key=key):
            ui.alt_enter(info, key)
        alt_enter._append_history = False
        alt_enter._alt_enter = True
        alt_enter._alt_enter_key = key
        window.cmd_keymap[binding] = alt_enter
    window.cmd_keymap["C-e"] = ui.edit_or_list
    window.command_drop_handler = ui.drop_files

    if not os.path.exists(os.path.join(clnch_misc._require_data_path(dataPath()), "commands.json")):
        print(strings.COMMAND_FILE_MISSING)
    registry.rebuild(window.launcher, commands, executor.make_handler, preserve_custom=False)
