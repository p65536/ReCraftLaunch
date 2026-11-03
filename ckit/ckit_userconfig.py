import os
import traceback

from ckit import ckit_resource

## @addtogroup userconfig
## @{


## \~japanese
# 設定スクリプトを再読み込みする
# 
#  @param filename  ファイル名
#  汎用スクリプト入口でありimport済みモジュールは再読込しません。
#  ReCraftLaunchのReloadはMainWindow.configureが対象ソースの再読込と資源終了を管理します。
# 
# \~english
# Reload a configuration script
# 
#  @param filename  Filename
#  This generic script loader does not refresh imported modules.
#  ReCraftLaunch Reload uses MainWindow.configure to manage selected sources and resource cleanup.
# 
# \~
def reloadConfigScript(filename):
    global user_namespace

    try:
        with open(filename, "rb") as fd:
            fileimage = fd.read()
        user_namespace = {}
        code = compile(fileimage, os.path.basename(filename), "exec")
        exec(code, user_namespace, user_namespace)  # noqa: S102  # Load the selected Python configuration.
    except BaseException:  # noqa: BLE001  # Keep user scripts from terminating the host application.
        print(ckit_resource.strings["error_config_file_load_failed"])
        traceback.print_exc()


## \~japanese
# 設定スクリプトの関数を呼び出す
# 
#  @param funcname  関数の名前
#  @param args      引数
#  MainWindowが公開した現在の設定名前空間から呼びます。例外は表示し、部分適用を巻き戻しません。
# 
# \~english
# Call a function from the configuration script
# 
#  @param funcname  Function name
#  @param args      Arguments
#  Use the current configuration namespace published by MainWindow. Report exceptions without rolling back partial application.
# 
# \~
def callConfigFunc(funcname, *args):

    try:
        func = user_namespace[funcname]
    except KeyError:
        return

    try:
        func(*args)
    except BaseException:  # noqa: BLE001  # Keep user scripts from terminating the host application.
        print(ckit_resource.strings["error_config_file_exec_failed"])
        traceback.print_exc()


## @} userconfig
