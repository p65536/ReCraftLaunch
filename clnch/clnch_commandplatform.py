"""Windows argument parsing, path helpers and unregistered executable lookup."""
import ctypes
import os
import re
import shutil
import winreg
from ctypes import wintypes
from types import SimpleNamespace

import clnch_strings as strings
from clnch_cmdstore import unquote_path

# Windows command-line parsing API.
_CommandLineToArgvW = ctypes.windll.shell32.CommandLineToArgvW
_CommandLineToArgvW.argtypes = (wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int))
_CommandLineToArgvW.restype = ctypes.POINTER(wintypes.LPWSTR)

_LocalFree = ctypes.windll.kernel32.LocalFree
_LocalFree.argtypes = (wintypes.HLOCAL,)
_LocalFree.restype = wintypes.HLOCAL

_AssocQueryStringW = ctypes.windll.shlwapi.AssocQueryStringW
_AssocQueryStringW.argtypes = (wintypes.DWORD, ctypes.c_int, wintypes.LPCWSTR,
                              wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD))
_AssocQueryStringW.restype = ctypes.c_long


def _association_string(extension, kind):
    # NOTRUNCATE | NOFIXUPS | INIT_IGNOREUNKNOWN; retain the current user's defaults.
    flags = 0x520
    size = wintypes.DWORD()
    result = _AssocQueryStringW(flags, kind, extension, None, None, ctypes.byref(size))
    if result & 0xffffffff in (0x80070483, 0x80070002):  # No association / missing value.
        return None
    if result != 1:
        raise ctypes.WinError(result)
    buffer = ctypes.create_unicode_buffer(size.value)
    result = _AssocQueryStringW(flags, kind, extension, None, buffer, ctypes.byref(size))
    if result != 0:
        raise ctypes.WinError(result)
    return buffer.value


def _association_parameters(template, document, arguments):
    """Substitute supported Shell placeholders without rebuilding the fixed arguments."""
    result = []
    quoted, backslashes, used_document, used_arguments = False, 0, False, False
    index = 0
    while index < len(template):
        char = template[index]
        if char == "%":
            code = template[index + 1:index + 2]
            if code in ("1", "l", "L"):
                if not quoted and backslashes % 2:
                    raise ValueError("unsupported quote escape before document placeholder")
                result.append(document if quoted else '"' + document + '"')
                used_document = True
            elif code == "*" and not quoted:
                if (template[index - 1:index] not in ("", " ", "\t")
                        or template[index + 2:index + 3] not in ("", " ", "\t")):
                    raise ValueError("%* must be a separate argument")
                result.append(arguments)
                used_arguments = True
            else:
                raise ValueError("unsupported placeholder: %" + code)
            index += 2
            backslashes = 0
            continue
        if char == '"' and backslashes % 2 == 0:
            quoted = not quoted
        backslashes = backslashes + 1 if char == "\\" else 0
        result.append(char)
        index += 1
    if quoted:
        raise ValueError("unbalanced association quotes")
    if not used_document:
        raise ValueError("missing document placeholder (%1 / %L)")
    parameters = "".join(result)
    if arguments and not used_arguments:
        parameters += " " + arguments
    return parameters


def resolve_elevated_document(filename, arguments):
    """Resolve only existing documents to a directly elevatable static Win32 command."""
    extension = os.path.splitext(filename)[1].lower()
    # Keep executable, script, shortcut and installer launch semantics on the existing path.
    executable_extensions = {".exe", ".com", ".bat", ".cmd", ".lnk", ".url", ".msi", ".msp", ".scr", ".cpl"}
    executable_extensions.update(os.environ.get("PATHEXT", "").lower().split(";"))
    if extension in executable_extensions or not os.path.isfile(filename):
        return filename, arguments

    try:
        for kind, label in ((7, "DDE"), (8, "DDE"), (17, "DropTarget"),
                            (18, "DelegateExecute"), (21, "packaged app (AppUserModelID)")):
            if _association_string(extension, kind) is not None:
                raise ValueError(label)
        command = _association_string(extension, 1)  # ASSOCSTR_COMMAND
        executable = _association_string(extension, 2)  # ASSOCSTR_EXECUTABLE
        if not command or not executable:
            raise ValueError("no static EXE association (ASSOCSTR_COMMAND / ASSOCSTR_EXECUTABLE)")
        command = re.sub(r"%([A-Za-z_][A-Za-z_0-9()]*)%",
                         lambda match: os.environ.get(match[1], match[0]), command)
        executable = os.path.expandvars(executable)
        # ASSOCSTR_EXECUTABLE also handles an unquoted executable path containing spaces.
        command = command.lstrip(" \t")
        prefix = '"' + executable + '"' if command.startswith('"') else executable
        if (command[:len(prefix)].lower() != prefix.lower()
                or command[len(prefix):len(prefix) + 1] not in ("", " ", "\t")):
            raise ValueError("association EXE does not match the command")
        if (not os.path.isabs(executable) or not os.path.isfile(executable)
                or os.path.splitext(executable)[1].lower() != ".exe"
                or os.path.basename(executable).lower() in {
                    "rundll32.exe", "explorer.exe", "dllhost.exe", "launchwinapp.exe",
                    "applicationframehost.exe", "cmd.exe", "powershell.exe", "pwsh.exe",
                    "wscript.exe", "cscript.exe",
                }):
            raise ValueError("unsupported EXE / Shell broker: " + executable)
        parameters = _association_parameters(command[len(prefix):], filename, arguments)
        return executable, parameters
    except ValueError as error:
        raise ValueError(strings.RUNAS_ASSOCIATION_ERROR.format(path=filename, reason=error)) from error

# Split an argument string using Windows command-line rules.
def split_commandline_args(text):
    if not text:
        return []

    # argv[0] uses executable-name rules; a dummy keeps every actual argument under normal rules.
    argc = ctypes.c_int()
    argv = _CommandLineToArgvW("dummy.exe " + text, ctypes.byref(argc))
    if not argv:
        raise ctypes.WinError()

    try:
        return [argv[i] for i in range(1, argc.value)]
    finally:
        _LocalFree(ctypes.cast(argv, wintypes.HLOCAL))


def split_commandline_target(text):
    """Decode only _ra's Windows target token; preserve the remaining text."""
    text = text.lstrip(" \t")
    quoted, backslashes = False, 0
    end = len(text)
    for index, char in enumerate(text):
        if char in " \t" and not quoted:
            end = index
            break
        if char == '"' and backslashes % 2 == 0:
            quoted = not quoted
        backslashes = backslashes + 1 if char == "\\" else 0
    target = split_commandline_args(text[:end])
    return (target[0] if target else "", text[end + 1:])


# Resolve an existing target before returning its folder; never use a missing path's parent.
def _get_target_dir(path, workdir=""):
    if not path:
        return None

    path = os.fspath(path)
    unquoted = unquote_path(path)
    if os.path.isabs(unquoted):
        path = unquoted
    candidate = os.path.join(workdir, path) if workdir else path
    if not (os.path.isfile(candidate) or os.path.isdir(candidate)):
        candidate = resolve_system_executable(path)
        if not candidate:
            return None
    abs_path = os.path.abspath(candidate)
    if os.path.isdir(abs_path):
        return abs_path
    return os.path.dirname(abs_path) if os.path.isfile(abs_path) else None


# Use the first matching source root and preserve the target directory's relative path.
def get_mapped_directory(exe_path, source_roots, destination_root, workdir=""):
    if not exe_path or not destination_root:
        return None

    target_dir = _get_target_dir(exe_path, workdir)
    if target_dir is None:
        return None
    dir_path = os.path.normpath(target_dir)
    dir_norm = os.path.normcase(dir_path)

    for base in source_roots:
        base_path = os.path.normpath(os.path.abspath(base))
        base_norm = os.path.normcase(base_path)

        # Include the directory boundary so paths such as D:\Programs2 do not match D:\Programs.
        if dir_norm == base_norm or dir_norm.startswith(
            base_norm.rstrip(os.sep) + os.sep
        ):
            rel_path = os.path.relpath(dir_path, base_path)
            if rel_path == ".":
                return destination_root
            return os.path.join(destination_root, rel_path)

    return None


_APP_PATHS_KEY = r"Software\Microsoft\Windows\CurrentVersion\App Paths"


def _resolve_app_path(command_name):
    # Append .exe when no extension is given, as App Paths entries normally use executable names.
    app_name = (
        command_name if os.path.splitext(command_name)[1] else command_name + ".exe"
    )

    # Search per-user entries before machine-wide entries.
    roots = (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE)

    # Check both registry views to find 32-bit and 64-bit registrations.
    views = []
    for view in (0, winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
        if view not in views:
            views.append(view)

    subkey = _APP_PATHS_KEY + "\\" + app_name

    for root in roots:
        for view in views:
            try:
                with winreg.OpenKey(root, subkey, 0, winreg.KEY_READ | view) as key:
                    path, _ = winreg.QueryValueEx(key, "")
            except OSError:
                continue

            if not isinstance(path, str) or not path:
                continue

            # Expand environment variables for values such as REG_EXPAND_SZ.
            path = os.path.expandvars(path).strip().strip('"')
            if os.path.isfile(path):
                return path

    return None


def resolve_system_executable(command_name):
    # Resolve a bare drive letter (e.g. "D:" or "c:") to its root, not its current directory.
    if (
        len(command_name) == 2
        and command_name[1] == ":"
        and command_name[0].isalpha()
    ):
        executable = command_name.upper() + "\\"
        if not os.path.isdir(executable):
            return None
    else:
        # Leave absolute and relative paths to commandline_ExecuteFile.
        if os.path.dirname(command_name):
            return None

        # Search PATH/PATHEXT first, then App Paths.
        executable = shutil.which(command_name)
        if not executable:
            executable = _resolve_app_path(command_name)
        if not executable:
            return None

    return executable


class SystemExecutableCommandline:
    def __init__(self, window):
        self.window = window

    def onCandidate(self, update_info):
        return []

    def onEnter(self, commandline, text, mod):
        # Only the first semicolon separates the command name from its argument string.
        parts = text.split(";", 1)
        command_name = parts[0].strip()
        param_text = parts[1] if len(parts) > 1 else ""

        if not command_name:
            return False

        executable = resolve_system_executable(command_name)
        if not executable:
            return False

        command = self.window.ShellExecuteCommand(None, executable, "", "")
        info = SimpleNamespace(mod=mod, args=split_commandline_args(param_text), arg_string=param_text)
        commandline.planCommand(command, info, text)
        commandline.quit()
        return True

    def onStatusString(self, text):
        return None
