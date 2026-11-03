import _winapi
import configparser
import hashlib
import os
import sys
import tempfile
from contextlib import contextmanager

import clnch_debug

ini = None
ini_filename = os.path.join(os.path.dirname(sys.executable), "settings", "reclnch.ini")

dirty = False
read_failed = False

# --------------------------------------------------------------------


def _get_parser(attribute: str) -> configparser.RawConfigParser:
    parser = ini
    if parser is None:
        raise AttributeError(
            f"'NoneType' object has no attribute '{attribute}'", name=attribute, obj=None
        )
    return parser


@contextmanager
def _lock():
    # A named mutex keeps one lock identity across INI replacements without a file.
    path = os.path.normcase(os.path.realpath(ini_filename))
    name = "Local\\ReCraftLaunch.INI." + hashlib.sha256(os.fsencode(path)).hexdigest()
    handle = _winapi.CreateMutexW(0, False, name)
    if not handle:
        raise OSError(0, "Cannot create the INI settings mutex", None, _winapi.GetLastError())
    try:
        result = _winapi.WaitForSingleObject(handle, 10000)
        if result == _winapi.WAIT_TIMEOUT:
            raise TimeoutError("Timed out waiting for the INI settings mutex")
        # An abandoned mutex also grants ownership; the INI is replaced atomically.
        try:
            yield
        finally:
            _winapi.ReleaseMutex(handle)
    finally:
        _winapi.CloseHandle(handle)


def read():
    global ini
    global dirty
    global read_failed

    ini = configparser.RawConfigParser()
    read_failed = True

    try:
        with _lock():
            try:
                fd = open(ini_filename, "r", encoding="utf-8-sig")  # noqa: SIM115  # Distinguish a missing file from later read/close failures.
            except FileNotFoundError:
                pass
            else:
                with fd:
                    ini.read_file(fd)
    except Exception:  # noqa: BLE001  # Report INI read/parse failures and keep the launcher running.
        ini = configparser.RawConfigParser()
        clnch_debug.printErrorInfo()
    else:
        read_failed = False

    dirty = False


def write():
    global dirty

    # Only a successful read (including a missing file) can re-enable saving.
    if not dirty or read_failed:
        return

    try:
        with _lock():
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w", encoding="utf-8", newline="\n", delete=False,
                    dir=os.path.dirname(os.path.abspath(ini_filename)),
                    prefix=os.path.basename(ini_filename) + ".", suffix=".tmp",
                ) as fd:
                    temporary = fd.name
                    _get_parser("write").write(fd)
                    fd.flush()
                    os.fsync(fd.fileno())
                os.replace(temporary, ini_filename)
            finally:
                if temporary is not None:
                    try:
                        os.unlink(temporary)
                    except FileNotFoundError:
                        pass
        dirty = False
    except Exception:  # noqa: BLE001  # Report INI write/close failures and retain the dirty state.
        clnch_debug.printErrorInfo()


def get(section, option, default=None):
    try:
        return _get_parser("get").get(section, option)
    except Exception:
        if default is not None:
            return default
        raise


def getint(section, option, default=None):
    try:
        return _get_parser("getint").getint(section, option)
    except Exception:
        if default is not None:
            return default
        raise


def set(section, option, value):
    global dirty

    assert type(value) is str

    try:
        if _get_parser("get").get(section, option) == value:
            return
    except (configparser.NoSectionError, configparser.NoOptionError):
        pass

    try:
        _get_parser("add_section").add_section(section)
    except configparser.DuplicateSectionError:
        pass

    _get_parser("set").set(section, option, value)

    dirty = True


def setint(section, option, value):
    global dirty

    assert type(value) is int

    try:
        if _get_parser("getint").getint(section, option) == value:
            return
    except (configparser.NoSectionError, configparser.NoOptionError, ValueError):
        pass

    try:
        _get_parser("add_section").add_section(section)
    except configparser.DuplicateSectionError:
        pass

    _get_parser("set").set(section, option, str(value))

    dirty = True


def remove_section(section):
    global dirty

    if _get_parser("remove_section").remove_section(section):
        dirty = True
        return True
    else:
        return False


def remove_option(section, option):
    global dirty

    try:
        if _get_parser("remove_option").remove_option(section, option):
            dirty = True
            return True
        else:
            return False
    except configparser.NoSectionError:
        return False
