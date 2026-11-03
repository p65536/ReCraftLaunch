"""Default actions used when a command has no operation for a modifier."""

import os

import clnch_strings as strings
from clnch_inisettings import IniSetting

MODIFIERS = (
    ("CTRL", strings.MODIFIER_CTRL),
    ("SHIFT", strings.MODIFIER_SHIFT),
    ("CTRL_SHIFT", strings.MODIFIER_CTRL_SHIFT),
)
ACTIONS = {
    "none": strings.ACTION_NONE,
    "execute": strings.ACTION_EXECUTE,
    "target_folder": strings.ACTION_FOLDER,
    "mapped_folder": strings.ACTION_MAPPED,
}
DEFAULTS = {
    "CTRL_ACTION": "none",
    "SHIFT_ACTION": "target_folder",
    "CTRL_SHIFT_ACTION": "none",
    "SOURCE_ROOTS": (),
    "CTRL_DESTINATION_ROOT": "",
    "SHIFT_DESTINATION_ROOT": "",
    "CTRL_SHIFT_DESTINATION_ROOT": "",
}
SETTINGS = {
    name: IniSetting("MODIFIER", name.lower(), "" if name == "SOURCE_ROOTS" else value)
    for name, value in DEFAULTS.items()
}


def validate_root(value):
    if not value or any(ch in value for ch in "\r\n\0") or not os.path.isabs(value):
        raise ValueError(strings.FOLDER_ABSOLUTE_ERROR)


def validate(settings):
    for modifier, label in MODIFIERS:
        if settings[modifier + "_ACTION"] not in ACTIONS:
            raise ValueError(
                strings.MODIFIER_ACTION_ERROR.format(modifier=modifier.lower())
            )
        destination = settings[modifier + "_DESTINATION_ROOT"]
        if destination:
            validate_root(destination)
    for root in settings["SOURCE_ROOTS"]:
        validate_root(root)


def read(ini):
    settings = DEFAULTS.copy()
    for name, setting in SETTINGS.items():
        value = setting.get(ini)
        settings[name] = (
            tuple(line.strip() for line in value.splitlines() if line.strip())
            if name == "SOURCE_ROOTS"
            else value
        )
    validate(settings)
    return settings


def write(ini, settings):
    validate(settings)
    for name in DEFAULTS:
        value = "\n".join(settings[name]) if name == "SOURCE_ROOTS" else settings[name]
        SETTINGS[name].set_text(ini, value)
