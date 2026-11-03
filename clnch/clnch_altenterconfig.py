"""Independent main-input forwarding for Alt+Enter with Ctrl/Shift."""

import os
import subprocess
import urllib.parse

import clnch_strings as strings
from clnch_inisettings import IniSetting

ACTIONS = {
    "none": strings.ALT_ENTER_NONE,
    "application": strings.ALT_ENTER_APPLICATION,
    "web": strings.ALT_ENTER_WEB,
    "properties": strings.ALT_ENTER_PROPERTIES,
}
DEFAULTS = {
    "action": "none",
    "executable": "",
    "arguments": "%param%",
    "url": "",
    "properties_first": True,
}
SECTION = "ALT_ENTER"
KEYS = {
    "": (SECTION, "Alt+Enter", "A-Return"),
    "ctrl": ("CTRL_ALT_ENTER", "[C]+Alt+Enter", "C-A-Return"),
    "shift": ("SHIFT_ALT_ENTER", "[S]+Alt+Enter", "S-A-Return"),
    "ctrl_shift": ("CTRL_SHIFT_ALT_ENTER", "[C]+[S]+Alt+Enter", "C-S-A-Return"),
}
MODIFIED_DEFAULTS = {name: value for name, value in DEFAULTS.items() if name != "properties_first"}
SETTINGS = {
    name: IniSetting(SECTION, name, str(int(value)) if type(value) is bool else value)
    for name, value in DEFAULTS.items()
}
MODIFIED_SETTINGS = {
    key: {name: IniSetting(section, name, value) for name, value in MODIFIED_DEFAULTS.items()}
    for key, (section, _label, _binding) in KEYS.items() if key
}


def get_settings(window, key=""):
    return window.altenter_modified_settings[key] if key else window.altenter_settings


def validate(settings, key=""):
    defaults = MODIFIED_DEFAULTS if key else DEFAULTS
    if settings.keys() != defaults.keys():
        raise ValueError(strings.ALT_ENTER_ACTION_ERROR)
    if settings["action"] not in ACTIONS or (key and settings["action"] == "properties"):
        raise ValueError(strings.ALT_ENTER_ACTION_ERROR)
    if not key and type(settings["properties_first"]) is not bool:
        raise ValueError(strings.ALT_ENTER_BOOL_ERROR)
    for name in ("executable", "arguments", "url"):
        if not isinstance(settings[name], str) or any(char in settings[name] for char in "\r\n\0"):
            raise ValueError(strings.ALT_ENTER_TEXT_ERROR)
    url = settings["url"]
    if url:
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc or "%param%" not in url:
            raise ValueError(strings.ALT_ENTER_URL_ERROR)


def read(ini, key=""):
    definitions = MODIFIED_SETTINGS[key] if key else SETTINGS
    settings: dict[str, str | bool] = {
        name: setting.get(ini) for name, setting in definitions.items()
    }
    if not key:
        if settings["properties_first"] not in ("0", "1"):
            raise ValueError(strings.ALT_ENTER_BOOL_ERROR)
        settings["properties_first"] = settings["properties_first"] == "1"
    validate(settings, key)
    return settings


def write(ini, settings, key=""):
    validate(settings, key)
    definitions = MODIFIED_SETTINGS[key] if key else SETTINGS
    for name, value in settings.items():
        definitions[name].set_text(ini, str(int(value)) if type(value) is bool else value)


def build_action(settings, text, key=""):
    validate(settings, key)
    text = text.strip()
    mode = settings["action"]
    if not text or mode == "none":
        return None
    if not key and (mode == "properties" or settings["properties_first"]):
        path = text[1:-1] if text.startswith('"') and text.endswith('"') else text
        if os.path.exists(path):
            return ("properties", os.path.abspath(path), "", "")
        if mode == "properties":
            raise FileNotFoundError(strings.ALT_ENTER_PATH_ERROR.format(path=path))
    if mode == "web":
        if not settings["url"]:
            raise ValueError(strings.ALT_ENTER_URL_ERROR)
        url = settings["url"].replace("%param%", urllib.parse.quote_plus(text))
        return (None, url, "", "")
    if not settings["executable"].strip():
        raise ValueError(strings.ALT_ENTER_APP_ERROR)
    arguments = settings["arguments"]
    if "%param%" not in arguments:
        arguments = (arguments + " %param%").lstrip()
    arguments = arguments.replace("%param%", subprocess.list2cmdline([text]))
    executable = os.path.expandvars(settings["executable"])
    return (None, executable, arguments, os.path.dirname(executable))


def execute(window, text, key=""):
    import clnch_misc

    import ckit
    import pyauto

    settings = get_settings(window, key).copy()
    if not text.strip() or settings["action"] == "none":
        return

    def job_execute(job_item):
        try:
            action = build_action(settings, text, key)
            if action:
                pyauto.shellExecute(*action)
        except Exception as error:  # noqa: BLE001  # Report forwarding failures at the asynchronous launch boundary.
            print(strings.ALT_ENTER_FAILED.format(error=error))

    clnch_misc._require_job_queue(ckit.JobQueue.defaultQueue()).enqueue(ckit.JobItem(job_execute))
