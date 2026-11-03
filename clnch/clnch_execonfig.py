"""Executable-local choice of portable or per-user settings."""

import configparser
import os
import tempfile

import clnch_strings as strings
from clnch_inisettings import IniSetting

MULTI_USER = IniSetting("DATA", "multi_user", "0")


def read(app_dir):
    ini = configparser.RawConfigParser()
    try:
        with open(os.path.join(app_dir, "reclnch_exe.ini"), encoding="utf-8-sig") as source:
            ini.read_file(source)
    except FileNotFoundError:
        return False
    value = ini.get(MULTI_USER.section, MULTI_USER.key, fallback=MULTI_USER.default)
    if value not in ("0", "1"):
        raise ValueError(strings.DATA_VALUE_ERROR)
    return value == "1"


def write(app_dir, multi_user):
    path = os.path.join(app_dir, "reclnch_exe.ini")
    ini = configparser.RawConfigParser()
    try:
        with open(path, encoding="utf-8-sig") as source:
            ini.read_file(source)
    except FileNotFoundError:
        pass
    if not ini.has_section(MULTI_USER.section):
        ini.add_section(MULTI_USER.section)
    MULTI_USER.set_text(ini, str(int(multi_user)))
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=app_dir,
            prefix=".reclnch-exe-",
            suffix=".tmp",
            delete=False,
        ) as output:
            temporary_path = output.name
            ini.write(output)
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and os.path.exists(temporary_path):
            os.unlink(temporary_path)
