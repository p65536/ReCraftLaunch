import configparser
import datetime
import os
import stat
import threading
import traceback

import clnch_altenterconfig
import clnch_commandline
import clnch_commandplatform
import clnch_configmenu
import clnch_consolewindow
import clnch_debug
import clnch_ini
import clnch_inisettings as ini_settings
import clnch_inputconfig
import clnch_inputsession
import clnch_ipc
import clnch_listwindow
import clnch_misc
import clnch_modifierconfig
import clnch_msgbox
import clnch_resource
import clnch_standard
import clnch_statusbar
import clnch_strings as strings
from clnch_cmdstore import load_commands, unquote_path, validate_link

import ckit
import clnch_native
import pyauto
from ckit.ckit_const import (
    ORIGIN_X_CENTER,
    ORIGIN_Y_TOP,
    VK_DELETE,
    VK_ESCAPE,
)

## @cond japanese
## @addtogroup mainwindow メインウインドウ機能
## @endcond
## @cond english
## @addtogroup mainwindow Main Window
## @endcond
## @addtogroup mainwindow
## @{

# --------------------------------------------------------------------

PAINT_STATUS_BAR = 1 << 14
PAINT_ALL = PAINT_STATUS_BAR


## \~japanese
# メインウインドウ
# 
#  ReCraftLaunchのメインウインドウを表すクラスです。
# 
#  設定ファイル custom.py の configure() に渡される window 引数は、MainWindow クラスのオブジェクトです。
#  ReCraftLaunch のさまざまな機能が、MainWindowのメソッドとして提供されています。
# 
#  拡張では渡されたwindowを使い、UIスレッドから呼び出します。設定用の主な属性は次のとおりです。
#  - launcher.command_list: (名前, CommandInfoを受け取る関数)の可変リスト。名前比較は大文字小文字を区別せず先頭一致です。
#    自作項目のappendは同名の既存項目を上書きしません。JSON編集一覧・別名解決とは別の登録です。
#  - keymap: 入力を維持するキー割当。cmd_keymap: 通常は入力終了・履歴追加を伴うキー割当で、先に調べます。
#    標準Alt+Enter系4キーはそれぞれ無効時には入力を保持し、有効時には入力終了します。F12は入力終了します。どちらも履歴へ追加しません。
#    F12操作後はメインを非アクティブにします。外部起動時は起動先への自然なフォーカス遷移に委ねます。
#    どちらもCommandInfo.argsは[入力全体]、arg_stringは入力全体、modは0です。
#  - command: command_接頭辞を除いた名前で既存コマンドを取得するCommandMap。例: window.command.Reload。
#  - clock_format: 非アクティブ時計のstrftime書式文字列。
#  - synccall: UIスレッドへ処理を依頼する既存SyncCall。独自インスタンスを作る場合と違い本体がcheckします。
#  コマンド・キーはconfigureで再構築されます。独自資源の終了処理はregisterConfigCleanupへ登録します。
#  具体例は @ref extensions を参照してください。
#
# \~english
# Main window
# 
#  Represents the ReCraftLaunch main window.
# 
#  The window argument passed to configure() in custom.py is a MainWindow instance.
#  MainWindow methods provide access to various ReCraftLaunch features.
# 
#  Use the supplied window from extensions and call UI methods on the UI thread. Main configuration attributes:
#  - launcher.command_list: mutable list of (name, callable_accepting_CommandInfo). Names match case-insensitively, first match wins.
#    Appending does not override an existing same-name entry. This registration differs from the JSON editor and alias resolution.
#  - keymap: bindings retaining input. cmd_keymap: checked first, normally ending input and recording history.
#    Each of the four standard Alt+Enter combinations retains input when disabled and ends it when enabled. F12 ends input. Neither adds history.
#    F12 deactivates the main window. External launches use the target application's natural focus transition.
#    Both receive args=[entire input], arg_string=entire input and mod=0.
#  - command: CommandMap exposing command_ methods without the prefix, for example window.command.Reload.
#  - clock_format: strftime format string for the inactive clock.
#  - synccall: existing SyncCall polled by the application to run work on the UI thread.
#  configure rebuilds commands and keymaps. Register cleanup of custom resources with registerConfigCleanup.
#  See @ref extensions for complete examples.
#
# \~
class MainWindow(ckit.TextWindow):
    def __init__(self, debug=False):
        self.initialized = False
        self._launcher_active = False

        self.debug = debug

        self.loadState()

        self.loadTheme()

        self.status_bar = clnch_statusbar.StatusBar()
        self.simple_status_bar_layer = clnch_statusbar.SimpleStatusBarLayer()
        self.simple_status_bar_resistered = False
        self.custom_status_bar_map = {}
        self.status_bar_paint_hook = None
        self.commandline_edit: ckit.EditWidget | None = None

        self.cmd_keymap = ckit.Keymap()
        self.keymap = ckit.Keymap()
        self.compare_list = []
        self.sorter_list = []
        self.association_list = []
        self.clock_format = strings.CLOCK_FORMAT
        self.commandline_list = []
        self.input_settings = clnch_inputconfig.DEFAULTS.copy()
        # No history has been loaded before the first configure call.
        self.input_settings["HISTORY_MODE"] = "off"
        self.modifier_settings = clnch_modifierconfig.DEFAULTS.copy()
        self.altenter_settings = clnch_altenterconfig.DEFAULTS.copy()
        self.altenter_modified_settings = {
            key: clnch_altenterconfig.MODIFIED_DEFAULTS.copy()
            for key in clnch_altenterconfig.MODIFIED_SETTINGS
        }
        self.custom = None
        self._config_cleanup = []
        self.commandline_history = []

        # Adjust the font size for the intended monitor's DPI.
        monitor = ini_settings.GEOMETRY_MONITOR.get(clnch_ini)
        monitor_info_list = pyauto.Window.getMonitorInfo()
        if not 0 <= monitor < len(monitor_info_list):
            monitor = 0
        monitor_info = monitor_info_list[monitor]
        dpi_scale = ckit.TextWindow.getDisplayScalingFromPosition(
            monitor_info[0][0], monitor_info[0][1]
        )
        font_name = ini_settings.FONT_NAME.get(clnch_ini)
        font_size = ini_settings.FONT_SIZE.get(clnch_ini)
        font_size = round(font_size * dpi_scale)

        ckit.TextWindow.__init__(
            self,
            x=0,
            y=0,
            width=ini_settings.GEOMETRY_MIN_WIDTH.get(clnch_ini),
            height=1,
            font=ckit.getStockedFont(font_name, font_size, round(2 * dpi_scale)),
            bg_color=ckit.getColor("bg"),
            cursor0_color=ckit.getColor("cursor0"),
            cursor1_color=ckit.getColor("cursor1"),
            border_size=3,
            resizable=False,
            noframe=True,
            title_bar=False,
            title=clnch_resource.clnch_appname + " MainWindow",
            show=False,
            cursor=True,
            tool=True,
            activate_handler=self._onActivate,
            close_handler=self._onClose,
            endsession_handler=self._onEndSession,
            move_handler=self._onMove,
            size_handler=self._onSize,
            dpi_handler=self._onDpi,
            keydown_handler=self._onKeyDown,
            char_handler=self._onChar,
            lbuttondown_handler=self._onLeftButtonDown,
            rbuttondown_handler=self._onRightButtonDown,
            dropfiles_handler=self._onDropFiles,
            ipc_handler=self._onIpc,
        )

        if ini_settings.DEBUG_DETECT_BLOCK.get(clnch_ini):
            clnch_debug.enableBlockDetector()

        if ini_settings.DEBUG_PRINT_ERRORINFO.get(clnch_ini):
            clnch_debug.enablePrintErrorInfo()

        # Startup DPI correction updates both windows before the main window is shown.
        self.console_window = clnch_consolewindow.ConsoleWindow(self, debug=debug)

        self.resetPos()

        # Recheck DPI in case the window was created near a monitor boundary.
        dpi_scale2 = self.getDisplayScaling()
        if dpi_scale2 != dpi_scale:
            self.updateFont()

        self.updateTopMost()

        self.show(True)

        self.setCursorPos(-1, -1)

        self.command = ckit.CommandMap(self)

        self.launcher = clnch_commandline.commandline_Launcher(self)

        self.keydown_hook = None
        self.char_hook = None
        self.enter_hook = None
        self.mouse_event_mask = False

        self.quit_requested = False

        self.mouse_click_info = None

        self.synccall = ckit.SyncCall()

        self.child_window_lock = threading.RLock()

        self.last_monitor_info_list = pyauto.Window.getMonitorInfo()

        self.setTimer(self.onTimer, 10)
        self.setTimer(self.onTimerMonitor, 1000)

        clnch_misc.registerNetConnectionHandler(self._onCheckNetConnection)

        ckit.initTemp("clnch_")

        self.console_window.registerStdio()

        self.updateInactiveBehavior()

        self.initialized = True

        self.paint()

        self._registered_hotkey = (0, 0)
        self.updateHotKey()

    def destroy(self):
        try:
            self._releaseConfigResources()
        except BaseException:  # noqa: BLE001  # Finish native shutdown even if custom cleanup fails.
            traceback.print_exc()
        self.console_window.unregisterStdio()
        self.console_window.destroy()
        ckit.destroyTemp()
        ckit.TextWindow.destroy(self)

    def onTimer(self):
        if self.initialized:
            # WM_ACTIVATE(False) runs before the next owner window is active.
            active = self.isLauncherActive()
            was_active = self._launcher_active
            self._launcher_active = active
            if was_active and not active:
                self.saveState()
                clnch_ini.write()
        ckit.JobQueue.checkAll()
        self.synccall.check()

    ## \~japanese
    # サブスレッドで処理を実行する
    # 
    #  @param self              -
    #  @param func              サブスレッドで実行する呼び出し可能オブジェクト
    #  @param arg               引数 func に渡す引数
    #  @param cancel_func       ESCキーが押されたときのキャンセル処理
    #  @param cancel_func_arg   引数 cancel_func に渡す引数
    #  @param raise_error       引数 func のなかで例外が発生したときに、それを raise するか
    #  @param print_traceback   引数 func のなかで例外が発生したときに、エラー発生位置を詳細に出力するか
    # 
    #  メインスレッドのユーザインタフェイスの更新を止めずに、サブスレッドの中で任意の処理を行うための関数です。
    # 
    #  この関数のなかでは、引数 func をサブスレッドで呼び出しながら、メインスレッドでメッセージループを回します。
    #  返値には、引数 func の返値がそのまま返ります。
    # 
    #  ファイルのコピーや画像のデコードなどの、比較的時間のかかる処理は、メインスレッドではなくサブスレッドの中で処理するように心がけるべきです。
    #  さもないと、メインスレッドがブロックし、ウインドウの再描画などが長時間されないままになるといった弊害が発生します。
    # 
    #  argはfunc(*arg)へ展開するシーケンスです。呼出しはUIスレッドから行い、func内ではGUIを直接操作しません。
    #  cancel_funcはEsc時にUIスレッドで呼ぶ要求処理で、ワーカーを強制停止しません。cancel_func_argはその引数列です。
    #  raise_error=False時はワーカー例外を表示してNone、True時は呼出し元で同じ例外を再送出します。
    #  UI側の例外時には入力状態を復元しますが、実行中ワーカーを強制停止・無期限joinしません。
    #  @sa subProcessCall
    #  完全な協調取消の例は @ref extensions を参照してください。
    #
    # \~english
    # Run a function in a worker thread
    # 
    #  @param self              -
    #  @param func              Callable to run in the worker thread
    #  @param arg               Arguments passed to func
    #  @param cancel_func       Cancellation handler called when Esc is pressed
    #  @param cancel_func_arg   Arguments passed to cancel_func
    #  @param raise_error       Re-raise an exception raised by func
    #  @param print_traceback   Print a traceback when func raises an exception
    # 
    #  Run arbitrary work in a worker thread while continuing to update the main-thread user interface.
    # 
    #  This method calls func in a worker thread and runs a message loop on the main thread.
    #  Return the result of func unchanged.
    # 
    #  Run relatively slow work, such as copying files or decoding images, in a worker thread.
    #  Otherwise the main thread may block, preventing window repainting for an extended time.
    # 
    #  arg is the sequence expanded as func(*arg). Call from the UI thread and do not access GUI objects inside func.
    #  cancel_func runs on the UI thread on Esc and requests cancellation; it cannot forcibly stop the worker.
    #  cancel_func_arg is its argument sequence. With raise_error=False, report a worker exception and return None;
    #  with True, re-raise the same exception in the caller. On a UI-side failure restore input state, without
    #  forcibly stopping or indefinitely joining a running worker.
    #  @sa subProcessCall
    #  See @ref extensions for a complete cooperative-cancellation example.
    #
    # \~
    def subThreadCall(
        self,
        func,
        arg,
        cancel_func=None,
        cancel_func_arg=(),
        raise_error=False,
        print_traceback=False,
    ):
        class SubThread(threading.Thread):
            def __init__(self):
                threading.Thread.__init__(self)
                self.result = None
                self.error = None

            def run(self):
                try:
                    self.result = func(*arg)
                except Exception as e:  # noqa: BLE001  # Return arbitrary worker failures to the waiting caller.
                    if print_traceback:
                        traceback.print_exc()
                    self.error = e

        def onKeyDown(vk, mod):
            if vk == VK_ESCAPE and cancel_func:
                cancel_func(*cancel_func_arg)
            return True

        def onChar(ch, mod):
            return True

        sub_thread = SubThread()
        sub_thread.start()

        with clnch_inputsession._TemporaryInputState(self) as state:
            state.set(keydown_hook=onKeyDown, char_hook=onChar, mouse_event_mask=True)
            self.removeKeyMessage()
            # On UI failure, unwind hooks without blocking on a still-running worker.
            self.messageLoop(sub_thread.is_alive)
            sub_thread.join()
            result = sub_thread.result
            error = sub_thread.error

        if error:
            if raise_error:
                raise error
            else:
                print(error)

        return result

    ## \~japanese
    # コンソールプログラムをサブプロセスとして実行する
    # 
    #  @param self              -
    #  @param cmd               コマンドと引数のシーケンス
    #  @param cwd               サブプロセスのカレントディレクトリ
    #  @param env               サブプロセスの環境変数
    #  @param enable_cancel     True:ESCキーで終了を要求する  False:ESCキーで終了を要求しない
    #  @return                  サブプロセスの終了コード。サブスレッドで例外が発生した場合はエラーを表示し None。
    # 
    #  任意のコンソールプログラムを、ReCraftLaunchのサブプロセスとして実行し、そのプログラムの出力を、コンソールウインドウにリダイレクトします。
    #  ESCでの終了要求は SubProcess.cancel() に従い、終了を保証しません。処理が終わるまでUIの更新を続けて待ちます。
    # 
    #  引数 cmd には、サブプロセスとして実行するプログラムと引数をリスト形式で渡します。\n
    #  例:  [ "subst", "R:", "//remote-machine/public/" ]
    # 
    # \~english
    # Run a console program as a subprocess
    # 
    #  @param self              -
    #  @param cmd               Sequence containing the program and its arguments
    #  @param cwd               Working directory of the subprocess
    #  @param env               Environment variables of the subprocess
    #  @param enable_cancel     True: request exit on Esc; False: do not request exit on Esc
    #  @return                  Exit code, or None after reporting an exception from the worker thread.
    # 
    #  Run a console program as a ReCraftLaunch subprocess and redirect its output to the console window.
    #  Esc uses SubProcess.cancel() and does not guarantee termination. Wait for completion while continuing UI updates.
    # 
    #  Pass the program and its arguments as a list in cmd.\n
    #  Example: [ "subst", "R:", "//remote-machine/public/" ]
    # 
    # \~
    def subProcessCall(self, cmd, cwd=None, env=None, enable_cancel=False):
        p = ckit.SubProcess(cmd, cwd, env)

        if enable_cancel:
            cancel_handler = p.cancel
        else:
            cancel_handler = None

        return self.subThreadCall(p, (), cancel_handler)

    ## \~japanese
    # コマンドラインで文字列を入力する
    # 
    #  @param self                      -
    #  @param title                     コマンド入力欄の左側に表示されるタイトル文字列
    #  @param text                      コマンド入力欄の初期文字列
    #  @param selection                 初期選択範囲 [開始位置, 終了位置]。None は末尾のカーソル位置。
    #  @param auto_complete             自動補完を有効にするか
    #  @param autofix_list              選択中の補完文字列の確定位置を調整する文字グループのリスト
    #  @param update_handler            コマンド入力欄の変更があったときに通知を受けるためのハンドラ
    #  @param candidate_handler         補完候補を列挙するためのハンドラ
    #  @param candidate_remove_handler  補完候補を削除するためのハンドラ
    #  @param status_handler            コマンド入力欄の右側に表示されるステータス文字列を返すためのハンドラ
    #  @param keydown_handler           コマンド入力欄でキー入力が行われたときのハンドラ
    #  @param char_handler              コマンド入力欄で文字入力が行われたときのハンドラ
    #  @param enter_handler             コマンド入力欄でEnterキーが押されたときのハンドラ
    #  @param escape_handler            コマンド入力欄でEscapeキーが押されたときのハンドラ
    #  @param preserve_argument_text    Trueなら最初のセミコロン以降と直接URLのタブ・CR・LFを更新・履歴で置換しない。標準メイン入力で使用し、既定False。
    #  @return                          最後にEnterで取得した文字列。取得前に入力ループを終了した場合は None。
    # 
    #  コマンド入力欄で任意の文字列の入力を受け付けるための関数です。
    #  コマンドを解釈/実行するのは、このメソッドの呼び出し元の役割です。
    #  ハンドラの呼び出し形式と戻り値は以下のとおりです。未指定のハンドラは呼び出しません。
    # 
    #  - update_handler(update_info): 更新を許可する場合は真、拒否する場合は偽を返します。
    #    update_info.text と update_info.selection を書き換えられます。呼び出し前にタブ・CR・LFを半角スペースへ置換し、連続空白や前後の空白は保持します。
    #    この規則は入力設定に依存しません。preserve_argument_text=Trueなら最初のセミコロン以降と直接URL全体は置換しません。
    #  - candidate_handler(update_info): (候補文字列のリスト, 置換開始位置) を返します。
    #    置換範囲は開始位置から選択範囲の右端までです。
    #  - candidate_remove_handler(text): 候補を削除できた場合は真、削除しない場合は偽を返します。
    #  - status_handler(update_info): 右側へ表示する文字列、または表示しない場合は None／空文字列を返します。
    #  - keydown_handler(commandline, vk, mod)／char_handler(commandline, ch, mod):
    #    真を返すと標準処理を省略します。ch は文字コードの整数です。
    #  - enter_handler(commandline, text, mod): 真を返すと入力を継続し、偽なら入力ループを終了します。
    #  - escape_handler(commandline): 入力が空でコンソールも非表示の場合に呼び出し、真なら標準の終了処理を省略します。
    # 
    #  commandline は入力中だけ有効な操作用オブジェクトです。getText()／setText()、getSelection()／setSelection()、
    #  selectAll()、paint()、quit() などを提供します。Enterハンドラ自身が quit() した場合も入力ループを終了します。
    #  Enterで文字列を取得したあと、ハンドラが入力を継続してキャンセルした場合も、最後に取得した文字列を返します。
    #  autofix_list の例は ["\\/", ".", ";"] です。グループ内の文字を入力すると、選択範囲の開始を
    #  範囲内の最初の同グループ文字へ移します。該当文字がなければ選択範囲の末尾へ移し、選択中の文字列を確定します。
    # 
    #  入力操作オブジェクトの主な追加操作は以下のとおりです。保持した参照は入力終了後に使わないでください。
    #  - getText()/setText(text): 現在の文字列を取得・置換。setTextは更新ハンドラを経由します。
    #  - getSelection()/setSelection([anchor, cursor]): Python文字列の位置。選択の向きも保持します。
    #  - appendHistory(text): 履歴設定に従い正規化し、重複を除いて先頭へ追加。空文字列・offでは追加しません。
    #  - planCommand(command, info, history): 正常な入力終了・入力状態復元後にcommand(info)を予約順で実行します。
    #    異常終了時は実行しません。history=Noneなら履歴追加をしません。
    #  - executeCommand(command, info, history_item, quit): 即時実行。文字列の戻り値は入力の置換として扱い、
    #    履歴追加・追加のquitを行いません。通常の戻りではhistory_itemを追加し、quitが真なら終了します。
    #    コマンド例外はコンソールへ通知して戻ります。
    #  キー・Enter・Escハンドラにはこの操作オブジェクト、更新・補完・状態ハンドラにはUpdateInfoを渡します。
    #  更新ハンドラのない場合と、ハンドラがNoneを返した場合は異なります。このメソッドのupdate_handlerは
    #  更新を許可する場合に真を返す必要があります。
    #  @sa CommandInfo
    #
    # \~english
    # Read text from the command line
    # 
    #  @param self                      -
    #  @param title                     Title displayed to the left of the input field
    #  @param text                      Initial input text
    #  @param selection                 Initial [start, end] selection. None places the cursor at the end.
    #  @param auto_complete             Enable automatic completion
    #  @param autofix_list              Character groups that adjust how selected completion text is accepted
    #  @param update_handler            Handler notified of input changes
    #  @param candidate_handler         Handler enumerating completion candidates
    #  @param candidate_remove_handler  Handler removing a completion candidate
    #  @param status_handler            Handler returning status text displayed to the right of the input
    #  @param keydown_handler           Handler for key-down events
    #  @param char_handler              Handler for character-input events
    #  @param enter_handler             Handler for Enter
    #  @param escape_handler            Handler for Esc
    #  @param preserve_argument_text    True skips tab/CR/LF replacement in updates/history after the first semicolon and for direct URLs. Used by standard main input; default False.
    #  @return                          The text last captured on Enter, or None if the input loop ends before any capture.
    # 
    #  Accept arbitrary text in the command input field.
    #  The caller is responsible for interpreting and executing commands.
    #  Handlers use the following signatures and return values. Unspecified handlers are not called.
    # 
    #  - update_handler(update_info): Return a true value to allow the update, or a false value to reject it.
    #    You may change update_info.text and update_info.selection. Before this call, tabs/CR/LF are replaced by spaces; consecutive and leading/trailing spaces are preserved.
    #    This rule is independent of input settings. With preserve_argument_text=True, text after the first semicolon and entire direct URLs are left unchanged.
    #  - candidate_handler(update_info): Return (list_of_candidate_strings, replacement_start_index).
    #    The replacement extends from that index to the right end of the selection.
    #  - candidate_remove_handler(text): Return a true value on removal, or a false value to leave the candidate unchanged.
    #  - status_handler(update_info): Return the status text, or None / an empty string to show no status.
    #  - keydown_handler(commandline, vk, mod) / char_handler(commandline, ch, mod):
    #    Return a true value to skip standard handling. ch is an integer character code.
    #  - enter_handler(commandline, text, mod): Return a true value to continue input, or a false value to end the input loop.
    #  - escape_handler(commandline): Called when input is empty and the console is hidden. Return a true value to skip the standard exit action.
    # 
    #  commandline is an input-control object valid during input. It provides getText() / setText(), getSelection() / setSelection(),
    #  selectAll(), paint(), quit(), and other operations. Calling quit() in the Enter handler also ends the input loop.
    #  If a handler continues input after Enter and the user later cancels, the last text captured on Enter is still returned.
    #  An example autofix_list is ["\\/", ".", ";"]. Typing a character in a group moves the selection start
    #  to the first character from that group within the selection, or to the selection end if none is found, accepting the selected text.
    # 
    #  Additional input-control operations follow. Do not use a retained control object after input has ended.
    #  - getText()/setText(text): read/replace current text; setText goes through update handling.
    #  - getSelection()/setSelection([anchor, cursor]): Python string positions, retaining selection direction.
    #  - appendHistory(text): normalize, remove a duplicate and prepend according to history settings; no addition for empty text or when off.
    #  - planCommand(command, info, history): run command(info) in order after normal input termination and state restoration.
    #    Skip planned execution on abnormal exit. history=None disables history addition.
    #  - executeCommand(command, info, history_item, quit): execute now. A string result replaces input without recording
    #    history or performing the additional quit. Other results append history_item and end input if quit is true.
    #    Report command exceptions to the console and return.
    #  Key/Enter/Esc callbacks receive this control object; update/completion/status callbacks receive UpdateInfo.
    #  An absent update handler differs from one returning None: this method's update_handler must return a true value to allow updates.
    #  @sa CommandInfo
    #
    # \~
    def commandLine(
        self,
        title,
        text="",
        selection=None,
        auto_complete: int = False,
        autofix_list=None,
        update_handler=None,
        candidate_handler=None,
        candidate_remove_handler=None,
        status_handler=None,
        keydown_handler=None,
        char_handler=None,
        enter_handler=None,
        escape_handler=None,
        *, preserve_argument_text=False,
    ):
        return clnch_inputsession._CommandLineSession(
            self, PAINT_STATUS_BAR, title, text, selection, auto_complete, autofix_list,
            update_handler, candidate_handler, candidate_remove_handler, status_handler,
            keydown_handler, char_handler, enter_handler, escape_handler,
            preserve_argument_text=preserve_argument_text,
        ).run()

    def commandLineHistoryLoad(self):
        history = []
        for i in range(1000):
            try:
                entry = clnch_ini.get(ini_settings.COMMANDLINE_SECTION, f"history_{i}")
            except (configparser.NoSectionError, configparser.NoOptionError):
                break
            if entry != "":
                history.append(entry)
        return history

    def commandLineHistorySave(self):
        if self.input_settings["HISTORY_MODE"] != "persistent":
            return
        i = 0
        for entry in self.commandline_history:
            if entry == "":
                continue
            clnch_ini.set(
                ini_settings.COMMANDLINE_SECTION, f"history_{i}", entry
            )
            i += 1
        while True:
            if not clnch_ini.remove_option(ini_settings.COMMANDLINE_SECTION, f"history_{i}"):
                break
            i += 1

    def _onActivate(self, active):
        self.active = active

        self.paint()

        if self.commandline_edit:
            self.commandline_edit.onWindowActivate(active)

        if active:
            self._launcher_active = True
            if self.initialized and self.console_window.opened:
                self.console_window.onParentActivate()

    def isLauncherActive(self):
        if self.active:
            return True
        if self.initialized:
            window = pyauto.Window.getForeground()
            while window:
                if window.getHWND() == self.getHWND():
                    return True
                window = window.getOwner()
        return False

    def _onClose(self):
        if not self.isEnabled():
            self.foreground()
            return
        self.quit()

    def _onEndSession(self):
        self.saveState()
        clnch_ini.write()

    def _onMove(self, x, y):
        if not self.initialized:
            return

        if self.commandline_edit:
            self.commandline_edit.onWindowMove()

    def _onSize(self, width, height):
        self.paint()

    def updateFont(self):
        scale = self.getDisplayScaling()

        font_name = ini_settings.FONT_NAME.get(clnch_ini)
        font_size = ini_settings.FONT_SIZE.get(clnch_ini)
        font_size = round(font_size * scale)

        self.setFontFromFontObject(
            ckit.getStockedFont(font_name, font_size, round(2 * scale))
        )

        window_rect = self.getWindowRect()
        self.setPosSize(
            (window_rect[0] + window_rect[2]) // 2,
            window_rect[1],
            self.width(),
            self.height(),
            ORIGIN_X_CENTER | ORIGIN_Y_TOP,
        )

        self.console_window.updateFont()

    def _onDpi(self, scale):
        # Construction-time notifications are reconciled by the startup DPI check.
        if not self.initialized:
            return
        self.updateFont()

    def _onKeyDown(self, vk, mod):

        if self.keydown_hook and self.keydown_hook(vk, mod):
            return True

        return True

    def _onChar(self, ch, mod):

        if self.char_hook and self.char_hook(ch, mod):
            return

    def _onLeftButtonDown(self, x, y, mod):

        self.drag(x, y)

    def _onRightButtonDown(self, x, y, mod):

        pass

    def _onDropFiles(self, x, y, filename_list):
        self.hotkey_Activate()
        handler = getattr(self, "command_drop_handler", None)
        if handler and filename_list:
            handler(filename_list)

    def _onIpc(self, data):
        if not data:
            self.hotkey_Activate()
            return

        ipc_data = clnch_ipc.IpcData(data)
        ipc_data.execute(self)
        if not self.quit_requested:
            ipc_data.commandLine(self)

    def _onCheckNetConnection(self, remote_resource_name):
        def addConnection(hwnd, remote_resource_name):
            try:
                clnch_native.addConnection(hwnd, remote_resource_name)
            except Exception as e:  # noqa: BLE001  # Complete SyncCall even when connection handling fails unexpectedly.
                print(strings.CONNECT_ERROR.format(resource=remote_resource_name))
                print(e, "\n")

        self.synccall(addConnection, (self.getHWND(), remote_resource_name))

    def ratioToScreen(self, ratio):
        rect = self.getWindowRect()
        return (
            int(rect[0] * (1 - ratio[0]) + rect[2] * ratio[0]),
            int(rect[1] * (1 - ratio[1]) + rect[3] * ratio[1]),
        )

    def centerOfWindowInPixel(self):
        rect = self.getWindowRect()
        return ((rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2)

    ## \~japanese
    #  表示層を管理する既存StatusBarを取得する
    #  @return 本体が所有するStatusBar。新規オブジェクトではありません。
    #  通常の拡張はregisterStatusBar・setStatusMessageを使います。
    #  @sa registerStatusBar, setStatusMessage
    #
    # \~english
    #  Get the existing status-layer manager
    #  @return Application-owned StatusBar, not a new object.
    #  Prefer registerStatusBar and setStatusMessage for ordinary extensions.
    #  @sa registerStatusBar, setStatusMessage
    #
    # \~
    def statusBar(self):
        return self.status_bar

    ## \~japanese
    #  独自の非入力時ステータス表示を登録する
    #  @param func UIスレッドでfunc(width)として呼ぶ関数。表示セル幅を受け、文字列を返します。
    #  @param priority 数値。小さい値ほど優先。同値なら登録順。既定-1。
    #  @param interval 再描画の間隔（ミリ秒）。Noneまたは0なら定期更新しません。
    #  @return None。同じ関数の再登録は何もしません。
    #  表示領域へ収まるよう文字列を調整します。入力中は入力表示が優先されます。
    #  関数参照を保持してunregisterStatusBarで解除します。Reloadで新たな関数を作ると別登録になります。
    #  @sa unregisterStatusBar, setStatusMessage
    #
    # \~english
    #  Register a custom status display outside text input
    #  @param func UI-thread callback func(width), receiving display-cell width and returning text.
    #  @param priority Numeric priority; smaller first, registration order breaks ties. Default -1.
    #  @param interval Repaint interval in milliseconds; None or 0 disables periodic updates.
    #  @return None. Registering the same callable again does nothing.
    #  Text is fitted to the display. Input display takes precedence while entering text.
    #  Keep the callable reference and unregister it explicitly. Creating a new function on Reload creates a separate registration.
    #  @sa unregisterStatusBar, setStatusMessage
    #
    # \~
    def registerStatusBar(self, func, priority=-1, interval=None):
        if func in self.custom_status_bar_map:
            return

        custom_status_bar_layer = clnch_statusbar._CustomStatusBarLayer(
            self, func, priority, interval, PAINT_STATUS_BAR
        )
        self.status_bar.registerLayer(custom_status_bar_layer)
        self.custom_status_bar_map[func] = custom_status_bar_layer

    ## \~japanese
    #  独自ステータス表示とそのタイマーを解除する
    #  @param func registerStatusBarに渡した関数そのもの。
    #  @return None。未登録なら何もしません。関数が所有する他の資源までは解放しません。
    #  UIスレッドから呼びます。
    #  @sa registerStatusBar
    #
    # \~english
    #  Remove a custom status display and its timer
    #  @param func The exact callable passed to registerStatusBar.
    #  @return None. Do nothing if not registered; do not release other resources owned by the callback.
    #  Call on the UI thread.
    #  @sa registerStatusBar
    #
    # \~
    def unregisterStatusBar(self, func):
        if func not in self.custom_status_bar_map:
            return

        custom_status_bar_layer = self.custom_status_bar_map[func]
        self.status_bar.unregisterLayer(custom_status_bar_layer)
        custom_status_bar_layer.destroy()
        del self.custom_status_bar_map[func]

    def _onStatusMessageTimedout(self):
        self.clearStatusMessage()

    ## \~japanese
    #  一時メッセージを表示する
    #  @param message 表示文字列。
    #  @param timeout ミリ秒後に消去。Noneなら明示消去・置換まで保持します。
    #  @param error Trueならbar_error_fg、Falseならヒント色で表示します。
    #  @return None。
    #  UIスレッドから呼びます。メッセージを置換すると前の消去タイマーを解除します。
    #  他の表示層の優先順位や入力中の表示により、常に最前面になるとは限りません。
    #  例: window.setStatusMessage("Saved", timeout=2000)。
    #  @sa clearStatusMessage, registerStatusBar
    #
    # \~english
    #  Display a temporary status message
    #  @param message Text to display.
    #  @param timeout Clear after this many milliseconds; None retains it until explicit clearing or replacement.
    #  @param error True uses bar_error_fg; False uses the hint color.
    #  @return None.
    #  Call on the UI thread. Replacing a message cancels its previous expiry timer.
    #  Other layers' priority and active input can take precedence.
    #  Example: window.setStatusMessage("Saved", timeout=2000).
    #  @sa clearStatusMessage, registerStatusBar
    #
    # \~
    def setStatusMessage(self, message, timeout=None, error=False):
        self.simple_status_bar_layer.setMessage(message, error)

        if not self.simple_status_bar_resistered:
            self.status_bar.registerLayer(self.simple_status_bar_layer)
            self.simple_status_bar_resistered = True

        self.killTimer(self._onStatusMessageTimedout)
        if timeout is not None:
            self.setTimer(self._onStatusMessageTimedout, timeout)

        self.paint(PAINT_STATUS_BAR)

    ## \~japanese
    #  一時メッセージと消去タイマーを解除する
    #  @return None。独自登録したステータス層は解除しません。
    #  UIスレッドから呼びます。
    #  @sa setStatusMessage
    #
    # \~english
    #  Clear the temporary message and its expiry timer
    #  @return None. Do not remove separately registered custom status layers.
    #  Call on the UI thread.
    #  @sa setStatusMessage
    #
    # \~
    def clearStatusMessage(self):
        self.simple_status_bar_layer.setMessage("")
        if self.simple_status_bar_resistered:
            self.status_bar.unregisterLayer(self.simple_status_bar_layer)
            self.simple_status_bar_resistered = False
        self.paint(PAINT_STATUS_BAR)
        self.killTimer(self._onStatusMessageTimedout)

    # --------------------------------------------------------------------------

    def loadTheme(self):
        name = ini_settings.THEME_NAME.get(clnch_ini)
        default_color = {}
        ckit.setTheme(name, default_color)

    def reloadTheme(self):
        self.loadTheme()
        self.updateColor()

    # --------------------------------------------------------------------------

    def updateColor(self):
        self.setBGColor(ckit.getColor("bg"))
        self.setCursorColor(ckit.getColor("cursor0"), ckit.getColor("cursor1"))
        self.paint()

        self.console_window.updateColor()

    # --------------------------------------------------------------------------

    def _onTimerTopmost(self):
        wnd = pyauto.Window.fromHWND(self.getHWND())
        wnd = wnd.getPrevious()
        while wnd:
            if (
                wnd.isVisible()
                and not wnd.getClassName().startswith("#")
                and wnd.getClassName()
                not in (clnch_resource.clnch_window_class, "SysShadow")
                and not wnd.getProcessName().lower().endswith(".scr")
            ):
                self.topmost(True)
                break
            wnd = wnd.getPrevious()

    def updateTopMost(self):
        topmost = ini_settings.GEOMETRY_TOPMOST.get(clnch_ini)
        self.topmost(topmost != 0)

        if topmost == 2:
            self.setTimer(self._onTimerTopmost, 10)
        else:
            self.killTimer(self._onTimerTopmost)

    # --------------------------------------------------------------------------

    ## \~japanese
    # ウインドウ位置を初期化する
    # 
    #  @param self  -
    # 
    #  ウインドウ位置を、設定メニューの [表示オプション] → [現在の表示位置を保存] で保存されたウインドウ位置にリセットします。
    # 
    # \~english
    # Reset the window position
    # 
    #  @param self  -
    # 
    #  Restore the position saved through Config > Display options > Save current display position.
    # 
    # \~
    def resetPos(self):
        rect = self.getWindowRect()

        monitor = ini_settings.GEOMETRY_MONITOR.get(clnch_ini)
        x = ini_settings.GEOMETRY_X.get(clnch_ini)
        y = ini_settings.GEOMETRY_Y.get(clnch_ini)

        monitor_info_list = pyauto.Window.getMonitorInfo()
        if not 0 <= monitor < len(monitor_info_list):
            monitor = 0
            x = 0
            y = 0

        monitor_info = monitor_info_list[monitor]
        if x >= 0:
            x = monitor_info[0][0] + x
        else:
            x = monitor_info[0][2] + x - (rect[2] - rect[0]) + 1

        if y >= 0:
            y = monitor_info[0][1] + y
        else:
            y = monitor_info[0][3] + y - (rect[3] - rect[1]) + 1

        self.setPosSize(x, y, self.width(), self.height(), 0)

    def onTimerMonitor(self):
        monitor_info_list = pyauto.Window.getMonitorInfo()
        if monitor_info_list != self.last_monitor_info_list:
            self.resetPos()
            self.last_monitor_info_list = monitor_info_list

    # --------------------------------------------------------------------------

    def _statusbar_Clock(self, width):
        now = datetime.datetime.now()
        return now.strftime(self.clock_format)

    def updateInactiveBehavior(self):
        inactive_behavior = ini_settings.MISC_INACTIVE_BEHAVIOR.get(clnch_ini)

        if inactive_behavior == "clock":
            self.registerStatusBar(self._statusbar_Clock, priority=-1, interval=1000)
        else:
            self.unregisterStatusBar(self._statusbar_Clock)

    # --------------------------------------------------------------------------

    def paint(self, option=PAINT_ALL):
        if not self.initialized:
            return

        if option & PAINT_STATUS_BAR:
            if self.status_bar_paint_hook:
                self.status_bar_paint_hook(0, self.height() - 1, self.width(), 1)
            else:
                clock_layer = self.custom_status_bar_map.get(self._statusbar_Clock)
                if clock_layer is not None and self.status_bar.isActiveLayer(clock_layer):
                    work = ckit.getWindowWorkArea(self)
                    limit, _ = ckit.getWindowSizeLimits(self, border_size=3)
                    width = min(
                        max(self.width(), self.getStringWidth(self._statusbar_Clock(self.width())) + 2),
                        ini_settings.GEOMETRY_MAX_WIDTH.get(clnch_ini),
                        limit,
                    )
                    if width != self.width():
                        rect = self.getWindowRect()
                        char_width, _ = self.getCharSize()
                        pixel_width = rect[2] - rect[0] + (width - self.width()) * char_width
                        x = max(work[0], min(rect[0], work[2] - pixel_width))
                        y = max(work[1], min(rect[1], work[3] - (rect[3] - rect[1])))
                        self.setPosSize(x, y, width, self.height(), 0)
                self.status_bar.paint(self, 0, self.height() - 1, self.width(), 1)

    # --------------------------------------------------------------------------

    ## \~japanese
    # 設定を読み込む
    # 
    #  キーマップや command_list などをリセットした上で、標準機能と custom.py を適用します。
    # 
    #  @return None。読込失敗はコンソールへ通知します。
    #  custom.pyを新しい名前空間で読み、標準キー・内蔵コマンド、標準機能・JSON、custom.configure(self)の順に適用します。
    #  選択中のscripts/・extensions/から明示importしたPythonソースと依存先を新しい名前空間で再読込します。INIは再読込しません。
    #  読込段階の失敗は旧設定を保持します。資源終了の失敗は独自設定の適用を延期し、標準キー・組込コマンドと検証済みJSONへ退避します。
    #  退避時は旧独自登録と一覧フックを外します。独自関数内の失敗は部分適用を巻き戻しません。
    #  初回のcustom.py読込・フック検証失敗時は、独自設定なしで標準機能と検証済みJSONを適用します。
    #  独自読込・フック・終了処理のSystemExit・KeyboardInterruptも通知して継続します。
    #  JSONは資源終了・登録置換より前に検証します。初回起動の読込失敗時はJSONなしで標準・独自設定を適用します。
    #  読込・終了・適用の失敗時はReload成功を通知しません。例外の通知とNoneの戻り値は維持します。
    #  資源の寿命はregisterConfigCleanupで接続します。対象・失敗境界の詳細は @ref extensions を参照してください。
    #  フックはUIスレッドで呼ばれます。長時間処理や資源の重複登録を避けてください。
    #  @sa CommandInfo
    #
    # \~english
    # Load configuration
    # 
    #  Reset the keymaps and command_list, then apply standard features and custom.py.
    # 
    #  @return None. Report load failures to the console.
    #  Read custom.py into a fresh namespace, then apply standard keys/built-ins, standard features/JSON, and custom.configure(self).
    #  Read explicitly imported Python sources and dependencies in the active scripts/ and extensions/ into fresh namespaces. Do not reread INI.
    #  Load failures preserve the previous settings. Cleanup failures defer custom application and fall back to standard keys/built-ins and validated JSON.
    #  Fallback removes old custom registrations and list hooks. Failures inside custom hooks do not roll back partial changes.
    #  Initial custom.py loading or hook validation failure still applies standard features and validated JSON without custom settings.
    #  Report SystemExit and KeyboardInterrupt from custom loading, hooks and cleanup, and continue.
    #  Validate JSON before cleanup/replacement. On initial startup, a JSON load failure still allows standard/custom configuration without JSON.
    #  Loading, cleanup or application failures suppress Reload success notification; exceptions are reported and the return value remains None.
    #  Use registerConfigCleanup for resource lifetime. See @ref extensions for scope and failure boundaries.
    #  Hooks run on the UI thread; avoid long work and duplicate resource registrations.
    #  @sa CommandInfo
    #
    # \~
    def configure(self):
        self._config_failed = False
        try:
            commands = load_commands(os.path.join(clnch_misc._require_data_path(ckit.dataPath()), "commands.json"))
        except Exception:  # noqa: BLE001  # Preserve active registrations and custom resources on JSON load failure.
            self._config_failed = True
            traceback.print_exc()
            if self.custom is not None:
                return
            commands = {}
        try:
            settings = clnch_inputconfig.read(clnch_ini)
            modifier_settings = clnch_modifierconfig.read(clnch_ini)
            altenter_settings = clnch_altenterconfig.read(clnch_ini)
            altenter_modified_settings = {
                key: clnch_altenterconfig.read(clnch_ini, key)
                for key in clnch_altenterconfig.MODIFIED_SETTINGS
            }
            filename = os.path.join(clnch_misc._require_data_path(ckit.dataPath()), "custom.py")
        except Exception:  # noqa: BLE001  # Report invalid core settings without replacing active configuration.
            self._config_failed = True
            traceback.print_exc()
            return
        cleanup_started = False
        def release_resources():
            nonlocal cleanup_started
            cleanup_started = True
            self._releaseConfigResources()

        try:
            local = clnch_inputconfig.load(
                filename,
                (os.path.join(ckit.getAppExePath(), "extensions"),
                 os.path.join(os.path.dirname(filename), "scripts")),
                before_apply=release_resources,
            )
        except BaseException:  # noqa: BLE001  # Contain user loading/cleanup failures before replacing active settings.
            self._config_failed = True
            traceback.print_exc()
            # Cleanup can invalidate old bindings even though module staging rolls back.
            if self.custom is not None and not cleanup_started:
                return
            local = None

        self.custom = local
        self.modifier_settings = modifier_settings
        self.altenter_settings = altenter_settings
        self.altenter_modified_settings = altenter_modified_settings
        ckit.ckit_userconfig.user_namespace = vars(local) if local is not None else {}

        self.clock_format = strings.CLOCK_FORMAT

        default_keymap = ini_settings.MISC_DEFAULT_KEYMAP.get(clnch_ini)

        ckit.Keymap.init()
        self.cmd_keymap = ckit.Keymap()
        self.keymap = ckit.Keymap()
        self.keymap["C-K"] = self.command.RemoveHistory
        self.keymap["C-S"] = self.command.ConfigMenu
        self.keymap["C-F10"] = self.command.ConsoleToggle
        self.keymap["F1"] = self.command.Help
        self._input_key_commands = {}
        if (self.applyInputSettings(settings)
                and self.input_settings["HISTORY_MODE"] != "persistent" and clnch_ini.dirty):
            clnch_ini.write()
        if default_keymap == "101":
            self.cmd_keymap["C-Slash"] = self.command.ContextMenu
        elif default_keymap == "106":
            self.cmd_keymap["C-BackSlash"] = self.command.ContextMenu

        self.association_list = []

        self.commandline_list = [
            self.launcher,
            clnch_commandline.commandline_ExecuteURL(self),
            clnch_commandline.commandline_ExecuteFile(self),
        ]

        self.launcher.command_list = [
            ("history", self.command.History),
            ("config", self.command.ConfigMenu),
            ("reload", self.command.Reload),
            ("about", self.command.About),
            ("quit", self.command.Quit),
        ]

        try:
            clnch_standard.configure(self, commands)
        except Exception:  # noqa: BLE001  # Report standard-configuration failures and continue local configuration.
            self._config_failed = True
            traceback.print_exc()
        if local is not None and hasattr(local, "configure"):
            try:
                local.configure(self)
            except BaseException:  # noqa: BLE001  # Report custom configuration failures without terminating the launcher.
                self._config_failed = True
                traceback.print_exc()

    ## \~japanese
    # Reload・終了時の独自資源の終了処理を登録する
    #
    #  @param func 引数なしの呼出し可能オブジェクト。戻り値は使いません。
    #  @return None。
    #  UIスレッドで取得直後に登録します。同一オブジェクトの重複登録は無視します。
    #  次の設定読込成功後、標準/独自設定の置換前とMainWindow破棄前に、登録の逆順で呼びます。
    #  窓・タイマー・Hook・ステータス層等は所有者が解除してください。実行中ジョブを強制停止しません。
    #  例外後も残りの処理を試み、失敗した処理だけ次回へ残します。Reloadは独自設定を適用せず通知し、標準機能と検証済みJSONへ退避します。
    #  旧モジュールは再試行用に保持しますが、旧独自登録と一覧フックは外します。直接登録したタイマー等の停止は所有者の責任です。
    #  終了処理は再試行可能にし、ジョブ終了待ちは協調的取消と例外でReloadを延期してください。
    #  任意の副作用や設定適用途中の失敗は巻き戻しません。詳細は @ref extensions を参照してください。
    #
    # \~english
    # Register cleanup of custom resources on Reload and shutdown
    #
    #  @param func Callable taking no arguments. Its return value is ignored.
    #  @return None.
    #  Register on the UI thread immediately after acquisition. Repeated registration of the same object is ignored.
    #  Call in reverse order after successful loading, before replacing standard/custom settings, and before MainWindow destruction.
    #  Owners release their windows, timers, Hooks and status layers. Running jobs are never forcibly stopped.
    #  Try remaining callbacks after an exception and retain only failures for retry. On failure, report and defer custom application; fall back to standard features and validated JSON.
    #  Keep old modules for retry, but remove old custom registrations and list hooks. Owners must stop directly registered timers and similar callbacks.
    #  Make cleanup retryable; request cooperative job cancellation and raise to defer Reload until completion.
    #  Arbitrary side effects and partial application failures are not rolled back. See @ref extensions.
    #
    # \~
    def registerConfigCleanup(self, func):
        if not callable(func):
            raise TypeError("Config cleanup must be callable")
        if not any(callback is func for callback in self._config_cleanup):
            self._config_cleanup.append(func)

    def _releaseConfigResources(self):
        callbacks, self._config_cleanup = self._config_cleanup, []
        failed = []
        error = None
        for callback in reversed(callbacks):
            try:
                callback()
            except BaseException as caught:  # noqa: BLE001  # Try every owner's cleanup and retain failures for retry.
                failed.append(callback)
                if error is None:
                    error = caught
                else:
                    error.add_note(repr(caught))
        self._config_cleanup[:0] = reversed(failed)
        if error is not None:
            raise error

    def applyInputSettings(self, settings):
        previous_history_mode = self.input_settings["HISTORY_MODE"]
        applied = True
        if settings["HISTORY_MODE"] != previous_history_mode:
            if settings["HISTORY_MODE"] == "persistent":
                try:
                    history = self.commandLineHistoryLoad()
                except Exception:  # noqa: BLE001  # Preserve history and keep startup/settings usable after a failed read.
                    print(strings.HISTORY_LOAD_ERROR)
                    traceback.print_exc()
                    settings = settings.copy()
                    settings["HISTORY_MODE"] = previous_history_mode
                    history = self.commandline_history
                    applied = False
            else:
                history = []
            self.commandline_history = history
        self.input_settings = settings
        if applied and settings["HISTORY_MODE"] != "persistent":
            try:
                options = clnch_ini.ini.options(ini_settings.COMMANDLINE_SECTION)
            except configparser.NoSectionError:
                options = []
            for option in options:
                suffix = option.removeprefix("history_")
                if option.startswith("history_") and suffix.isascii() and suffix.isdecimal():
                    clnch_ini.remove_option(ini_settings.COMMANDLINE_SECTION, option)

        for name, keymap, key, enabled, command in (
            ("SPACE_ACTION", self.keymap, "Space", "insert", self.command.InsertSpace),
            ("TAB_ACTION", self.cmd_keymap, "Tab", "clear", self.command.ClearInput),
        ):
            try:
                current = keymap[key]
            except KeyError:
                current = None
            # GUI changes only replace bindings installed by the core, not user hooks.
            if current is not self._input_key_commands.get(name):
                continue
            if settings[name] == enabled:
                keymap[key] = command
                self._input_key_commands[name] = command
            else:
                if current is not None:
                    del keymap[key]
                self._input_key_commands[name] = None

        return applied

    # --------------------------------------------------------------------------

    def loadState(self):
        if ini_settings.MISC_DIRECTORY_SEPARATOR.get(clnch_ini) == "slash":
            ckit.setPathSlash(True)
        else:
            ckit.setPathSlash(False)

    def saveState(self):
        if (
            self.input_settings["CLEAR_ON_DEACTIVATE"]
            and not self.isLauncherActive()
            and self.commandline_edit
        ):
            self.commandline_edit.setText("")

        try:
            ini_settings.GEOMETRY_WIDTH.set_text(clnch_ini, str(self.width()))
            ini_settings.GEOMETRY_HEIGHT.set_text(clnch_ini, str(self.height()))

            self.commandLineHistorySave()

            self.console_window.saveState()

        except Exception as e:  # noqa: BLE001  # Report state-save failures without aborting shutdown.
            print(strings.STATE_SAVE_ERROR)
            print("  %s" % str(e))  # noqa: UP031  # Preserve percent-s conversion for public values.

    # --------------------------------------------------------------------------

    def start(self):
        print(clnch_resource.startupString())

        self.console_window.setAutoShow(True)
        if clnch_ini.read_failed:
            print(strings.INI_READ_ERROR.format(path=clnch_ini.ini_filename))

    def stop(self):
        self.console_window.setAutoShow(False)

    # --------------------------------------------------------------------------

    def activeMessageLoop(self, text="", selection=None):
        handlers = clnch_commandline._LauncherInputHandlers(self)
        auto_complete = ini_settings.MISC_AUTO_COMPLETE.get(clnch_ini)
        self.commandLine(
            "",
            text=text,
            selection=selection,
            auto_complete=auto_complete,
            autofix_list=["\\/", ".", ";"],
            candidate_handler=handlers.onCandidate,
            candidate_remove_handler=handlers.onCandidateRemove,
            status_handler=handlers.statusString,
            keydown_handler=handlers.onKeyDown,
            enter_handler=handlers.onEnter,
            escape_handler=handlers.onEscape,
            preserve_argument_text=True,
        )

    def inactiveMessageLoop(self):
        inactive_behavior = ini_settings.MISC_INACTIVE_BEHAVIOR.get(clnch_ini)

        if inactive_behavior == "hide":
            self.show(False)

        self.removeKeyMessage()

        def checkContinue():
            return not self.isLauncherActive()

        self.messageLoop(checkContinue)

    def topLevelMessageLoop(self):
        while not self.quit_requested:
            if self.isLauncherActive():
                self.activeMessageLoop()
            else:
                self.inactiveMessageLoop()

    # --------------------------------------------------------------------------

    def hotkey_Activate(self):
        hotkey_behavior = ini_settings.MISC_HOTKEY_BEHAVIOR.get(clnch_ini)

        if self.active and hotkey_behavior == "toggle":
            self.inactivate()
            return

        # Restoring a hidden modal parent would activate it before its child.
        if self.isEnabled():
            self.restore()
        self.foreground()
        if self.isEnabled():
            self.activate()

    ## \~japanese
    # ホットキーを適用し、成功時はTrue、通知済みの失敗時はFalseを返します。
    # 引数省略時はINIの値を使います。vk=0は未設定です。登録失敗時は旧キーの復元を試みます。
    # 修飾キーのみは設定や現在の登録を変更せず拒否します。
    # 設定画面はTrueのときだけ候補値を保存します。
    # \~english
    # Apply a hotkey; return True on success or False after reporting failure.
    # Omitted arguments use INI values. vk=0 disables it. Registration failure attempts to restore the old key.
    # Modifier-only keys are rejected without changing settings or the current registration.
    # The settings dialog saves candidate values only on True.
    # \~
    def updateHotKey(self, activate_vk=None, activate_mod=None):
        if activate_vk is None:
            activate_vk = ini_settings.HOTKEY_ACTIVATE_VK.get(clnch_ini)
            activate_mod = ini_settings.HOTKEY_ACTIVATE_MOD.get(clnch_ini)
        if ckit.KeyEvent.isModifierKey(activate_vk):
            clnch_msgbox.popMessageBox(self, clnch_msgbox.MSGBOX_TYPE_OK,
                                      strings.ERROR_TITLE, strings.HOTKEY_MODIFIER_ONLY)
            return False
        hotkey = (activate_vk, activate_mod) if activate_vk else (0, 0)
        previous = self._registered_hotkey
        if hotkey == previous:
            return True
        try:
            if previous[0]:
                self.killHotKey(self.hotkey_Activate)
            self._registered_hotkey = (0, 0)
            try:
                if hotkey[0]:
                    self.setHotKey(*hotkey, self.hotkey_Activate)
            except (OSError, RuntimeError, MemoryError) as error:
                if previous[0]:
                    try:
                        self.setHotKey(*previous, self.hotkey_Activate)
                        self._registered_hotkey = previous
                    except (OSError, RuntimeError, MemoryError) as restore_error:
                        raise OSError(f"{error}\n{strings.HOTKEY_RESTORE_ERROR}\n{restore_error}") from restore_error
                raise
            self._registered_hotkey = hotkey
        except (OSError, RuntimeError, MemoryError) as error:
            clnch_msgbox.popMessageBox(self, clnch_msgbox.MSGBOX_TYPE_OK,
                                      strings.ERROR_TITLE, f"{strings.HOTKEY_REGISTER_ERROR}\n{error}")
            return False
        return True

    # --------------------------------------------------------------------------

    def executeCommand(self, name, info):
        try:
            command = getattr(self, "command_" + name)
        except AttributeError:
            return False

        command(info)
        return True

    def enumCommand(self):
        for attr in dir(self):
            if attr.startswith("command_"):
                yield attr[len("command_") :]

    # --------------------------------------------------------
    # The following methods can be bound to keys.
    # --------------------------------------------------------

    ## \~japanese
    # コンテキストメニューを開く
    # 
    #  引数に与えられたファイルに関して、コンテキストメニューを開きます。
    #  パス全体を囲む引用符一組を除去します。入力キー経由では最初のセミコロンまでをパスとし、対象なしなら入力・選択・履歴を保持します。
    # 
    # \~english
    # Open a context menu
    # 
    #  Open a context menu for the file given as an argument.
    #  Remove one enclosing path quote pair. Input keys use the path before the first semicolon and preserve input, selection and history if absent.
    # 
    # \~
    def command_ContextMenu(self, info):
        if len(info.args) <= 0:
            return
        path = info.args[0]
        if getattr(info, "arg_string", None) == path:
            path = path.partition(";")[0]
        path = unquote_path(path)
        if not os.path.exists(path):
            return
        dirname, name = os.path.split(os.path.normpath(path))

        clnch_misc._require_commandline_edit(self.commandline_edit, "closeList").closeList()

        pos = self.charToScreen(
            clnch_misc._require_commandline_edit(self.commandline_edit, "x").x
            + clnch_misc._require_commandline_edit(self.commandline_edit, "width").width,
            1,
        )
        self.removeKeyMessage()
        clnch_native.popupContextMenu(self.getHWND(), pos[0], pos[1], dirname, [name])

    ## \~japanese
    # 終了する
    # 
    #  ReCraftLaunch を終了します。
    # 
    # \~english
    # Quit
    # 
    #  Exit ReCraftLaunch.
    # 
    # \~
    def command_Quit(self, info):
        if not self.isEnabled():
            self.foreground()
            return
        self.quit_requested = True
        self.quit()

    ## \~japanese
    # アプリケーションやファイルの起動を行うコマンドオブジェクトを生成する
    # 
    #  @param self          -
    #  @param verb          操作
    #  @param filename      操作対象のファイル
    #  @param param         操作のパラメータ
    #  @param directory     既定のディレクトリ
    #  @param swmode        表示状態
    #  @param _command_name 内部の登録コマンド名。Noneなら追加のLink検証・WorkDir導出を行いません。通常の拡張からは指定しません。
    # 
    #  指定されたプログラムを起動するコマンドオブジェクトを生成し、返します。
    #  返された関数は CommandInfo を1引数で受け取り、JobQueue のデフォルトキューへ起動処理を登録します。
    #  param の %param% は、info.arg_stringがNoneでなければその生のWindows引数文字列へ置換します。
    #  標準入力の引用符・空白・バックスラッシュ・後続セミコロンを再整形せず、解釈は起動先に委ねます。
    #  arg_stringがNoneのPython呼出しは、info.argsをjoinArgs（subprocess.list2cmdline）で引用します。
    #  filename と directory の %param% は、引用・エスケープせず info.args を空白で連結したパス文字列へ置換します。
    #  param が None／空文字列の場合は %param% として扱います。固定の param へ実行時の引数を自動追加はしません。
    #  これら3項目ではジョブ実行時に %% を % へ、%環境変数名% を対応する環境変数へ置換します。未定義の変数はそのまま残します。
    #  公開APIは空の directory から自動決定しません。登録コマンドの標準実行では指定・継承WorkDirがなければ、同じジョブで展開したLinkが実在するファイルの場合だけ親フォルダを使います。
    #  登録Linkの絶対パス全体を囲む引用符一組は展開後に除去し、同じパスでWorkDir判定とShell起動を行います。
    # 
    #  引数verbには、実行する操作を文字列で渡します。指定可能な文字列は対象によって異なりますが、一般的には次のような操作が指定可能です。
    # 
    #  open
    #       ファイルを開きます。またはプログラムを起動します。
    #  edit
    #       ファイルを編集します。
    #  properties
    #       ファイルのプロパティを表示します。
    # 
    #  引数swmodeには、以下のいずれかの文字列(またはNone)を渡します。
    # 
    #  "normal"または""またはNone
    #       アプリケーションを通常の状態で起動します。
    #  "maximized"
    #       アプリケーションを最大化状態で起動します。
    #  "minimized"
    #       アプリケーションを最小化状態で起動します。
    # 
    #  引数の意味の詳細については、以下の解説を参照してください。
    #  http://msdn.microsoft.com/ja-jp/library/cc422072.aspx
    # 
    #  プログラムの起動は、サブスレッドの中で行われます。
    # 
    #  このメソッドは登録用の関数を返すだけです。返された関数の実行はNoneを返し、起動完了を待ちません。
    #  起動失敗はジョブ内でコンソールへ通知し、呼出し元に終了コードを返しません。
    #  runasでのUAC取消（Windowsエラー1223）は通知せず終了します。他の起動失敗は通知します。
    #  設定時はwindow.launcher.command_list.append(("myedit", window.ShellExecuteCommand("open", "notepad.exe", "%param%", "")))のように使います。
    #  @sa subProcessCall, CommandInfo
    #
    # \~english
    # Create a command callable that launches a program or opens a file
    # 
    #  @param self          -
    #  @param verb          Operation
    #  @param filename      Target file
    #  @param param         Parameters for the operation
    #  @param directory     Working directory
    #  @param swmode        Window display state
    #  @param _command_name Internal registered-command name. None skips additional Link validation and WorkDir derivation; omit it in ordinary extensions.
    # 
    #  Return a command callable that launches the specified program.
    #  The returned function accepts one CommandInfo and queues the launch on the default JobQueue.
    #  In param, %param% uses info.arg_string unchanged when it is not None.
    #  Standard input retains quotes, spaces, backslashes and later semicolons; the target interprets them.
    #  Python calls with arg_string=None format info.args using joinArgs (subprocess.list2cmdline).
    #  In filename and directory, %param% expands to info.args joined with spaces as a path, without quoting or escaping.
    #  None or an empty param is treated as %param%. Runtime arguments are not automatically appended to a fixed param.
    #  At job execution, these three fields expand %% to % and %VARIABLE% to its environment value. Undefined variables are left unchanged.
    #  The public API leaves an empty directory unspecified. Standard registered-command execution without an explicit/inherited WorkDir use the parent only when Link expanded in that same job is an existing file.
    #  After expansion, remove one pair of quotes enclosing an absolute registered Link path; use that same path for WorkDir checks and Shell launch.
    # 
    #  Pass the verb as a string. Supported verbs depend on the target; common examples follow.
    # 
    #  open
    #       Open the file or launch the program.
    #  edit
    #       Edit the file.
    #  properties
    #       Display file properties.
    # 
    #  Pass one of the following strings, or None, as swmode.
    # 
    #  "normal", "", or None
    #       Launch the application in its normal window state.
    #  "maximized"
    #       Launch the application maximized.
    #  "minimized"
    #       Launch the application minimized.
    # 
    #  See the following reference for details of these arguments.
    #  http://msdn.microsoft.com/ja-jp/library/cc422072.aspx
    # 
    #  The program is launched in a worker thread.
    # 
    #  This method only creates the callable for registration. Invoking that callable returns None without waiting for launch completion.
    #  Launch errors are reported inside the job; no process exit code is returned to the caller.
    #  UAC cancellation for runas (Windows error 1223) ends silently; other launch failures are still reported.
    #  For example: window.launcher.command_list.append(("myedit", window.ShellExecuteCommand("open", "notepad.exe", "%param%", ""))).
    #  @sa subProcessCall, CommandInfo
    #
    # \~
    def ShellExecuteCommand(self, verb, filename, param, directory, swmode=None, *, _command_name=None):
        def jobShellExecute(job_item):
            _filename = filename
            _param = param
            _directory = directory

            if _param is None or len(_param) == 0:
                _param = "%param%"

            joint_args = (job_item.arg_string if job_item.arg_string is not None
                          else clnch_misc.joinArgs(job_item.args))
            path_args = " ".join(job_item.args)

            _filename = clnch_misc.replaceMacro(
                _filename, {"%%": "%", "%param%": path_args}, environ=True
            )
            _param = clnch_misc.replaceMacro(
                _param, {"%%": "%", "%param%": joint_args}, environ=True
            )
            _directory = clnch_misc.replaceMacro(
                _directory, {"%%": "%", "%param%": path_args}, environ=True
            )

            try:
                if _command_name is not None:
                    validate_link(_filename, _command_name)
                    unquoted = unquote_path(_filename)
                    if os.path.isabs(unquoted):
                        _filename = unquoted
                    # Derive from the exact expanded Link passed to Shell, without expanding it again.
                    if not directory and os.path.isfile(_filename):
                        _directory = os.path.dirname(_filename)
                    if verb == "runas":
                        _filename, _param = clnch_commandplatform.resolve_elevated_document(_filename, _param)
                pyauto.shellExecute(verb, _filename, _param, _directory, swmode)
            except Exception as e:  # noqa: BLE001  # Report shell-launch failures at the job boundary.
                # ERROR_CANCELLED: declining UAC is a user choice, not a launch error.
                if verb == "runas" and isinstance(e, OSError) and getattr(e, "winerror", None) == 1223:
                    return
                print(strings.EXECUTE_ERROR)
                print("  %s" % str(e))  # noqa: UP031  # Preserve percent-s conversion for public values.

        def jobShellExecuteFinished(job_item):
            pass

        def command_ShellExecute(info):
            job_item = ckit.JobItem(jobShellExecute, jobShellExecuteFinished)
            job_item.args = info.args
            job_item.arg_string = getattr(info, "arg_string", None)
            clnch_misc._require_job_queue(ckit.JobQueue.defaultQueue()).enqueue(job_item)

        return command_ShellExecute

    ## \~japanese
    # URLを開くコマンドオブジェクトを生成する
    # 
    #  @param self          -
    #  @param url           開くURL。%param% に実行時の先頭のコマンド引数を埋め込めます。
    #  @param encoding      先頭のコマンド引数をURLエンコードする際の文字コード
    #  @return              CommandInfo を1引数で受け取るコマンド関数
    # 
    #  info.args[0] を encoding でバイト列化し、quote_plus でURLエンコードして %param% へ置換します。
    #  空白は + になります。引数がない場合は空文字列、2番目以降の引数は使用しません。
    #  %% は % へ置換しますが、環境変数の展開やURL全体のエンコードは行いません。
    #  起動処理は JobQueue のデフォルトキューで実行します。
    # 
    # \~english
    # Create a command callable that opens a URL
    # 
    #  @param self          -
    #  @param url           URL to open. %param% can insert the first runtime command argument.
    #  @param encoding      Encoding used when URL-encoding the first command argument
    #  @return              Command callable accepting one CommandInfo
    # 
    #  Encode info.args[0] using encoding, apply quote_plus, and substitute the result for %param%.
    #  Spaces become +. Missing arguments produce an empty string; arguments after the first are ignored.
    #  Expand %% to %, without expanding environment variables or encoding the entire URL.
    #  The launch runs on the default JobQueue.
    # 
    # \~
    def UrlCommand(self, url, encoding="utf8"):
        def jobShellExecute(job_item):
            _url = url

            if len(job_item.args) > 0:
                import urllib.parse

                keyword = job_item.args[0].encode(encoding)
                keyword = urllib.parse.quote_plus(keyword)
            else:
                keyword = ""

            _url = clnch_misc.replaceMacro(
                _url, {"%%": "%", "%param%": keyword}, environ=False
            )

            pyauto.shellExecute(None, _url, "", "")

        def jobShellExecuteFinished(job_item):
            pass

        def command_URL(info):
            job_item = ckit.JobItem(jobShellExecute, jobShellExecuteFinished)
            job_item.args = info.args
            clnch_misc._require_job_queue(ckit.JobQueue.defaultQueue()).enqueue(job_item)

        return command_URL

    ## \~japanese
    # コマンド履歴リストを開く
    # 
    # \~english
    # Open the command-history list
    # 
    # \~
    def command_History(self, info):
        if not self.isEnabled():
            self.foreground()
            return
        items = []

        for item in self.commandline_history:
            if item:
                items.append((item,))

        max_width = ini_settings.GEOMETRY_MAX_WIDTH.get(clnch_ini)

        def onKeyDown(vk, mod):
            if vk == VK_DELETE and mod == 0:
                result = list_window.getResult()
                select, _result_mod = clnch_listwindow._split_list_result(result)
                if 0 <= select < len(items):
                    self.commandline_history.remove(items[select][0])
                    list_window.remove(select)
                return True

        def onStatusMessage(width, select):
            return ""

        was_enabled = self.isEnabled()
        pos = self.centerOfWindowInPixel()
        list_window = clnch_listwindow.ListWindow(
            pos[0],
            pos[1],
            5,
            1,
            max_width,
            16,
            self,
            False,
            strings.HISTORY_TITLE,
            items,
            initial_select=0,
            keydown_hook=onKeyDown,
            onekey_search=False,
            statusbar_handler=onStatusMessage,
        )
        with clnch_misc._modal_dialog_scope(self, list_window, was_enabled):
            clnch_misc.adjustWindowPosition(self, list_window, default_up=True)
            list_window.show(True)
            self.enable(False)
            list_window.messageLoop()
            result = list_window.getResult()

        result, _result_mod = clnch_listwindow._split_list_result(result)
        if result < 0:
            return

        text = items[result][0]

        self.activeMessageLoop(text, [0, len(text)])

    ## \~japanese
    # 入力中の文字列をコマンド履歴から削除する
    # 
    # \~english
    # Remove the current input from command history
    # 
    # \~
    def command_RemoveHistory(self, info):
        clnch_misc._require_commandline_edit(self.commandline_edit, "removeCandidate").removeCandidate()

    ## \~japanese
    # 設定メニューを開く
    # 
    # \~english
    # Open the configuration menu
    # 
    # \~
    def command_ConfigMenu(self, info):
        if not self.isEnabled():
            self.foreground()
            return
        clnch_configmenu.doConfigMenu(self)

    ## \~japanese
    # 標準機能とcustom.pyを再適用する
    # 
    #  custom.py と commands.json を読み直します。ディスク上の reclnch.ini は読み直さず、読込済みの値を使います。
    #  明示importしたscripts/・extensions/のPythonソースと依存先も再読込します。資源はregisterConfigCleanupで終了します。
    # 
    # \~english
    # Reapply standard features and custom.py
    # 
    #  Reload custom.py and commands.json. Use the already loaded reclnch.ini values without rereading that file.
    #  Also refresh explicitly imported Python sources and dependencies from scripts/ and extensions/. Release owned resources via registerConfigCleanup.
    # 
    # \~
    def command_Reload(self, info):
        if not self.isEnabled():
            self.foreground()
            return
        previous = self.custom
        self.configure()
        if self.custom is not previous and not self._config_failed:
            print(strings.CONFIG_RELOADED)

    def command_InsertSpace(self, info):
        if self.commandline_edit:
            self.removeKeyMessage()
            self.commandline_edit.insertText(" ")

    def command_ClearInput(self, info):
        if self.commandline_edit:
            self.commandline_edit.setText("")

    ## \~japanese
    # 同梱のローカルヘルプを開く
    # 
    # \~english
    # Open the bundled local help
    # 
    # \~
    def command_Help(self, info):
        help_path = os.path.join(ckit.getAppExePath(), "docs", strings.get_language(), "index.html")

        def jobHelp(job_item):
            try:
                file_stat = os.stat(help_path)
            except FileNotFoundError:
                job_item.help_message = strings.HELP_MISSING.format(path=help_path)
                return
            except OSError as error:
                job_item.help_message = strings.HELP_OPEN_ERROR.format(
                    path=help_path, error=error
                )
                return

            if not stat.S_ISREG(file_stat.st_mode):
                job_item.help_message = strings.HELP_NOT_FILE.format(path=help_path)
                return

            try:
                pyauto.shellExecute(None, help_path, "", "")
            except OSError as error:
                job_item.help_message = strings.HELP_OPEN_ERROR.format(
                    path=help_path, error=error
                )
            else:
                job_item.help_message = strings.HELP_OPENED
                job_item.help_opened = True

        def jobHelpFinished(job_item):
            if job_item.help_message is not None:
                if job_item.help_opened and not self.console_window.debug:
                    self.console_window.write(job_item.help_message + "\n\n", auto_show=False)
                else:
                    print(job_item.help_message)
                    print()

        job_item = ckit.JobItem(jobHelp, jobHelpFinished)
        job_item.help_message = None
        job_item.help_opened = False
        clnch_misc._require_job_queue(ckit.JobQueue.defaultQueue()).enqueue(job_item)

    ## \~japanese
    # コンソールウインドウを開く
    # 
    # \~english
    # Open the console window
    # 
    # \~
    def command_ConsoleOpen(self, info):
        self.console_window.show(True)

    ## \~japanese
    # コンソールウインドウを閉じる
    # 
    # \~english
    # Close the console window
    # 
    # \~
    def command_ConsoleClose(self, info):
        self.console_window.show(False)

    ## \~japanese
    # コンソールウインドウの表示状態をトグルで切り替える
    # 
    # \~english
    # Toggle console-window visibility
    # 
    # \~
    def command_ConsoleToggle(self, info):
        if self.console_window.opened:
            self.command.ConsoleClose()
        else:
            self.command.ConsoleOpen()

    ## \~japanese
    # 自動補完をOnにする
    # 
    # \~english
    # Enable automatic completion
    # 
    # \~
    def command_AutoCompleteOn(self, info):
        if self.commandline_edit:
            print(strings.COMPLETION_ENABLED)
            self.commandline_edit.setAutoComplete(True)

    ## \~japanese
    # 自動補完をOffにして表示中の候補を閉じる。入力文字列・選択・履歴は保持する。
    # 
    # \~english
    # Disable automatic completion and close candidates; retain input text, selection and history.
    # 
    # \~
    def command_AutoCompleteOff(self, info):
        if self.commandline_edit:
            print(strings.COMPLETION_DISABLED)
            self.commandline_edit.setAutoComplete(False)
            self.commandline_edit.closeList()

    ## \~japanese
    # 自動補完のOn/Offをトグルで切り替える
    # 
    # \~english
    # Toggle automatic completion
    # 
    # \~
    def command_AutoCompleteToggle(self, info):
        if self.commandline_edit:
            if self.commandline_edit.getAutoComplete():
                self.command.AutoCompleteOff()
            else:
                self.command.AutoCompleteOn()

    ## \~japanese
    # ReCraftLaunchのバージョン情報を表示する
    # 
    # \~english
    # Display ReCraftLaunch version information
    # 
    # \~
    def command_About(self, info):
        print(clnch_resource.startupString())


# --------------------------------------------------------------------

## @} mainwindow
