import copy
import json
import ntpath
import os
import re
import tempfile

import clnch_strings as strings

MODIFIERS = ("target", "on_ctrl", "on_shift", "on_ctrl_shift")
VIEW_MODES = ("normal", "minimized", "maximized")
ACTION_FIELDS = ("link", "args", "workdir", "view_mode")


def is_valid_command_name(name):
    return ";" not in name and not any(char.isspace() for char in name)


def unquote_path(path):
    """Remove one enclosing quote pair, without decoding Windows arguments."""
    if isinstance(path, str) and path.startswith('"') and path.endswith('"') and path.count('"') == 2:
        return path[1:-1]
    return path


def validate_link(link, name):
    """Reject explicit relative Windows paths; retain bare names and Shell URIs."""
    path = unquote_path(link.strip())
    if ntpath.isabs(path):
        return
    drive, _ = ntpath.splitdrive(path)
    if not drive and re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", path):
        return
    if drive or ntpath.dirname(path) or path in (".", ".."):
        raise ValueError(strings.COMMAND_RELATIVE_LINK.format(name=name, link=link))


def validate_commands(commands, *, editor=False):
    """Validate the shared schema, retaining the editor's diagnostic order/text."""
    if not editor and not isinstance(commands, dict):
        raise ValueError(strings.COMMAND_OBJECT_ERROR)
    for name, params in commands.items():
        if not is_valid_command_name(name):
            raise ValueError(strings.COMMAND_NAME_ERROR.format(name=name))
        if not isinstance(params, dict) or set(params) - set(MODIFIERS):
            raise ValueError(strings.COMMAND_FORMAT_ERROR.format(name=name))
        for modifier, action in params.items():
            location = f"{name}.{modifier}"
            if (
                not isinstance(action, dict) or "link" not in action
                or (editor and not isinstance(action["link"], str))
            ):
                raise ValueError(strings.ACTION_FORMAT_ERROR.format(name=name if editor else location))
            if set(action) - set(ACTION_FIELDS):
                message = (strings.EDITOR_ACTION_UNKNOWN.format(name=name) if editor
                           else strings.ACTION_UNKNOWN.format(location=location))
                raise ValueError(message)
            for field in ACTION_FIELDS:
                if field in action and not isinstance(action[field], str):
                    message = (strings.EDITOR_ACTION_VALUE.format(name=name) if editor
                               else strings.ACTION_VALUE_ERROR.format(location=location, field=field))
                    raise ValueError(message)
            if action.get("view_mode", "normal") not in VIEW_MODES:
                message = (strings.EDITOR_VIEW_ERROR.format(name=name) if editor
                           else strings.ACTION_VIEW_ERROR.format(location=location))
                raise ValueError(message)
    return commands


class _JSONObject(dict):
    def __init__(self, pairs):
        super().__init__(pairs)
        self.names = [name for name, _ in pairs]


def load_commands(path, *, validation: str | None = "runtime"):
    """Read sparse actions and lowercase names without writing or filling defaults.

    validation="editor" preserves editor diagnostics; None keeps the list's
    names-only loading, so invalid names/actions can still be displayed/deleted.
    Duplicate command names are rejected in every mode, before lowercasing.
    Only a missing file means an empty configuration; other I/O errors propagate.
    I/O, JSON and validation errors belong to the caller's notification boundary.
    """
    try:
        with open(path, "r", encoding="utf-8-sig") as source:
            commands = json.load(source, object_pairs_hook=_JSONObject)
    except FileNotFoundError:
        return {}
    if isinstance(commands, _JSONObject):
        # Only the root keys are command names; nested fields keep normal JSON semantics.
        names = {}
        for name in commands.names:
            key = name.lower()
            if key in names:
                raise ValueError(strings.COMMAND_NAME_DUPLICATE.format(first=names[key], second=name))
            names[key] = name
    if validation is not None:
        validate_commands(commands, editor=validation == "editor")
    return {name.lower(): actions for name, actions in commands.items()}


def normalize_action(action):
    return {
        "link": action["link"],
        "args": action.get("args", ""),
        "workdir": action.get("workdir", ""),
        "view_mode": action.get("view_mode", "normal"),
    }


def normalize_commands(commands):
    """Complete registered actions and order names; leave absent modifiers absent."""
    return {
        name: {modifier: normalize_action(action) for modifier, action in actions.items()}
        for name, actions in sorted(commands.items(), key=lambda item: (item[0] != "", item[0].lower()))
    }


def duplicate_command(commands, name):
    """Return a new mapping and copy name without changing the loaded snapshot."""
    if not is_valid_command_name(name):
        raise ValueError(strings.COMMAND_NAME_ERROR.format(name=name))
    base_name = re.sub(r"_copy_[1-9][0-9]*\Z", "", name) or "unnamed"
    number = 1
    while f"{base_name}_copy_{number}" in commands:
        number += 1
    copied_name = f"{base_name}_copy_{number}"
    return {**commands, copied_name: copy.deepcopy(commands[name])}, copied_name


def save_commands(path, commands, original_commands=None):
    commands = normalize_commands(commands)
    # Compare with the caller's loaded data without reading the file again.
    if commands == original_commands:
        return commands
    temporary_path = None
    try:
        # Close the temporary file before replacing the destination in the same directory on Windows.
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=os.path.dirname(os.path.abspath(path)),
            prefix=".commands-",
            suffix=".tmp",
            delete=False,
        ) as output:
            temporary_path = output.name
            json.dump(commands, output, ensure_ascii=False, indent=2)
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and os.path.exists(temporary_path):
            os.unlink(temporary_path)

    return commands
