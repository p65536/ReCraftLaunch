# Keep initial imports minimal for fast IPC forwarding.
import ctypes
import getopt
import importlib.abc
import importlib.util
import os
import sys

import clnch_strings as strings


class CustomPydFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        exe_path = os.path.split(sys.argv[0])[0]
        pyd_filename_body = fullname.split(".")[-1]
        pyd_fullpath = os.path.join(exe_path, "lib", pyd_filename_body + ".pyd")
        if os.path.exists(pyd_fullpath):
            return importlib.util.spec_from_file_location(fullname, pyd_fullpath)


sys.meta_path.append(CustomPydFinder())

# Import IPC support after configuring native-extension lookup.
import clnch_debug
import clnch_ipc
import clnch_resource
import clnch_text

import ckit
import pyauto

# --------------------------------------------------------------------

debug = False

ipc_data = clnch_ipc.IpcData()

option_list, args = getopt.getopt(sys.argv[1:], "d", [] + clnch_ipc.IpcData.options)
for option in option_list:
    if option[0] == "-d":
        debug = True
    elif ipc_data.trySetOption(option[0], option[1]):
        pass

# --------------------------------------------------------------------


def findExistingClnchWindow():
    found = [None]

    def callback(wnd, arg):
        if (
            wnd.getClassName() == clnch_resource.clnch_window_class
            and wnd.getText() == clnch_resource.clnch_appname + " MainWindow"
        ):
            found[0] = wnd
            return False
        return True

    pyauto.Window.enum(callback, None)
    return found[0]


def sendIpc(wnd):
    print(strings.IPC_EXISTING.format(app=clnch_resource.clnch_appname))
    print(strings.IPC_SENDING)

    # Grant foreground permission before the receiver handles synchronous IPC.
    process_id = ctypes.c_ulong()
    ctypes.windll.user32.GetWindowThreadProcessId(
        ctypes.c_void_p(wnd.getHWND()), ctypes.byref(process_id)
    )
    ctypes.windll.user32.AllowSetForegroundWindow(process_id)
    ckit.TextWindow.sendIpc(wnd.getHWND(), ipc_data.getValue())

    print(strings.IPC_DONE)


existing_clnch_wnd = findExistingClnchWindow()
if existing_clnch_wnd:
    sendIpc(existing_clnch_wnd)
    sys.exit(0)

# --------------------------------------------------------------------

# Load application modules only when this process is not just forwarding IPC.

import clnch_execonfig
import clnch_ini
import clnch_inisettings as ini_settings
import clnch_misc

ckit.registerWindowClass(clnch_resource.clnch_window_class_prefix)
ckit.registerCommandInfoConstructor(ckit.CommandInfo)

# The executable directory owns the storage-mode selection, including development runs.
app_dir = os.path.dirname(sys.executable)
try:
    if not os.path.exists(os.path.join(app_dir, "reclnch_exe.ini")):
        clnch_execonfig.write(app_dir, False)
    multi_user = clnch_execonfig.read(app_dir)
    ckit.setDataPath(
        os.path.join(ckit.getAppDataPath(), clnch_resource.clnch_dirname)
        if multi_user
        else os.path.join(app_dir, "settings")
    )
    os.makedirs(os.path.join(clnch_misc._require_data_path(ckit.dataPath()), "scripts"), exist_ok=True)
    # Keep core and standard-library paths ahead of explicitly imported extensions.
    for path in (os.path.join(ckit.getAppExePath(), "extensions"),
                 os.path.join(clnch_misc._require_data_path(ckit.dataPath()), "scripts")):
        if path not in sys.path:
            sys.path.append(path)
    clnch_ini.ini_filename = os.path.join(clnch_misc._require_data_path(ckit.dataPath()), "reclnch.ini")
except Exception as error:
    # The Release build has no console for the traceback printed by main.cpp; exit code 1 is kept.
    ctypes.windll.user32.MessageBoxW(None, str(error), clnch_resource.clnch_appname, 0x10)  # MB_ICONERROR
    raise

clnch_ini.read()

strings.initialize(ini_settings.MISC_LANGUAGE.get(clnch_ini))
clnch_text.initialize()

# Import GUI modules after selecting the startup language for their cached strings.
import clnch_mainwindow

ckit.JobQueue.createDefaultQueue()

_main_window = clnch_mainwindow.MainWindow(debug=debug)

_main_window.configure()

_main_window.start()

_main_window.topLevelMessageLoop()

_main_window.stop()

_main_window.saveState()

clnch_debug.enableExitTimeout()

ckit.JobQueue.cancelAll()

_main_window.destroy()

ckit.JobQueue.joinAll()

clnch_ini.write()

clnch_debug.disableExitTimeout()
