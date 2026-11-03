import os
import sys
import types

import clnch_strings as strings
from clnch_configmodules import ConfigModules, _import_lock
from clnch_inisettings import IniSetting

DEFAULTS = {
    "HISTORY_MODE": "persistent",
    "COMPLETION_MODE": "standard",
    "CLEAR_ON_DEACTIVATE": True,
    "SPACE_ACTION": "insert",
    "TAB_ACTION": "complete",
}
SETTINGS = {
    name: IniSetting("INPUT", name.lower(), str(int(value)) if type(value) is bool else value)
    for name, value in DEFAULTS.items()
}

CHOICES = {
    "HISTORY_MODE": ("off", "session", "persistent"),
    "COMPLETION_MODE": ("off", "commands", "standard"),
    "SPACE_ACTION": ("insert", "complete"),
    "TAB_ACTION": ("clear", "complete"),
}


def load(filename, module_roots=None, before_apply=None):
    # Serialize staging/cleanup with imports made by the active generation.
    with _import_lock:
        local = types.ModuleType("custom")
        local.__file__ = filename
        previous = sys.modules.get("custom")
        previous_modules = getattr(previous, "_config_modules", None)
        if module_roots is None:
            module_roots = (os.path.join(os.path.dirname(filename), "scripts"),)
        modules = ConfigModules(module_roots, previous_modules)
        local.__dict__["_config_modules"] = modules
        local.__dict__["__builtins__"] = modules.builtins
        sys.modules["custom"] = local
        try:
            if os.path.exists(filename):
                with open(filename, "rb") as source:
                    code = compile(source.read(), filename, "exec")
                with modules.importing():
                    exec(code, local.__dict__)  # noqa: S102  # Load the selected Python configuration.

            if hasattr(local, "configure") and not callable(local.configure):
                raise ValueError(strings.CONFIG_CALLABLE_ERROR)
            if hasattr(local, "configure_ListWindow") and not callable(local.configure_ListWindow):
                raise ValueError(strings.CONFIG_LIST_CALLABLE_ERROR)
            if before_apply is not None:
                before_apply()
        except BaseException:
            modules.rollback()
            if previous is None:
                sys.modules.pop("custom", None)
            else:
                sys.modules["custom"] = previous
            raise
        modules.commit(previous_modules)
        return local


def read(ini):
    settings = DEFAULTS.copy()
    for name, default in DEFAULTS.items():
        value = SETTINGS[name].get(ini)
        choices = ("0", "1") if type(default) is bool else CHOICES[name]
        if value not in choices:
            raise ValueError(
                strings.INPUT_VALUE_ERROR.format(name=name.lower(), choices=choices)
            )
        settings[name] = value == "1" if type(default) is bool else value
    return settings
