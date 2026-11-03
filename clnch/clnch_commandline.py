import fnmatch
import os

import clnch_altenterconfig
import clnch_misc
from clnch_cmdstore import unquote_path
from clnch_commandplatform import split_commandline_args

import ckit
import clnch_native
import pyauto


class _LauncherInputHandlers:
    """Route launcher input using live window state; own no input session."""

    def __init__(self, window):
        self.window = window

    def onCandidate(self, update_info):
        left = update_info.text[: update_info.selectionLeft()]
        left_lower = left.lower()
        pos_arg = clnch_misc.commandlineArgumentStart(left)
        arg = left[pos_arg:]
        pos_dir = max(arg.rfind("/") + 1, arg.rfind("\\") + 1)

        candidate_map = {}
        mode = self.window.input_settings["COMPLETION_MODE"]
        if mode == "off" or not self.window.commandline_edit.getAutoComplete():
            return [], pos_arg + pos_dir

        if mode == "commands":
            providers = [self.window.launcher]
            pos_arg = pos_dir = 0
        else:
            providers = self.window.commandline_list
            for item in self.window.commandline_history:
                item_lower = item.lower()
                if item_lower.startswith(left_lower):
                    cand = item[pos_arg + pos_dir :]
                    if cand:
                        candidate_map.setdefault(cand.lower(), cand)

        for commandline_function in providers:
            for cand in commandline_function.onCandidate(update_info):
                if cand:
                    candidate_map.setdefault(cand.lower(), cand)

        registered_names = {}
        if pos_arg + pos_dir == 0:
            # Use the first executable registration's spelling, without changing candidate order.
            for name, _command in self.window.launcher.command_list:
                registered_names.setdefault(name.lower(), name)
        return [registered_names.get(key, cand) for key, cand in candidate_map.items()], pos_arg + pos_dir

    def onCandidateRemove(self, text):
        for i, item in enumerate(self.window.commandline_history):
            if item.lower() == text.lower():
                del self.window.commandline_history[i]
                return True
        return False

    def statusString(self, update_info):
        if update_info.text:
            for commandline_function in self.window.commandline_list:
                if hasattr(commandline_function, "onStatusString"):
                    s = commandline_function.onStatusString(update_info.text)
                    if s is not None:
                        return s
        return None

    def onKeyDown(self, commandline, vk, mod):
        try:
            func = self.window.cmd_keymap.table[ckit.KeyEvent(vk, mod)]
            if (getattr(func, "_alt_enter", False) is True
                    and clnch_altenterconfig.get_settings(
                        self.window, func._alt_enter_key)["action"] == "none"):
                return True
            quit = True
            # Utility commands can end input without recording it; custom bindings keep the default.
            append_history = getattr(func, "_append_history", True)
        except KeyError:
            try:
                func = self.window.keymap.table[ckit.KeyEvent(vk, mod)]
                quit = False
                append_history = False
            except KeyError:
                return
        text = commandline.getText()
        # NamedCommand bindings can be moved between keymaps by custom.py.
        if (getattr(func, "owner", None) is self.window
                and getattr(func, "name", None) == "ContextMenu"
                and not os.path.exists(unquote_path(text.partition(";")[0]))):
            return True
        args = [text]

        if append_history:
            history_item = text
        else:
            history_item = None

        info = ckit.CommandInfo()
        info.args = args
        info.arg_string = text
        info.mod = 0

        commandline.executeCommand(func, info, history_item, quit=quit)
        if getattr(func, "_inactivate", False) is True and self.window.isForeground():
            self.window.inactivate()

        return True

    def onEnter(self, commandline, text, mod):
        for commandline_function in self.window.commandline_list:
            if commandline_function.onEnter(commandline, text, mod):
                break
        return True

    def onEscape(self, commandline):
        self.window.resetPos()
        self.window.inactivate()
        return True


## @addtogroup commandline
## @{

# --------------------------------------------------------------------


## \~japanese
# コマンドラインからのコマンド実行機能
#  本体では既存のwindow.launcherを使います。command_listへ(名前, 関数)を追加すると入力・補完の対象になります。
#  名前の比較は大文字小文字を区別せず先頭から調べます。同名の後続項目は実行しません。
#  入力名の前後空白だけを無視し、最初のセミコロン以降と履歴用の入力原文は保持します。
#  名前に引数区切りのセミコロンは使えません。JSONはGUI保存・読込時に検証し、空文字列名と操作0件の登録を許容します。
#  同名のJSON空登録は組込より優先され、名前入力・別名参照では何も実行しません。空欄名のGUI保存だけはLinkが必要です。
#  commandline_listへ独自の入力プロトコルを追加する場合は、onCandidate(update_info)で候補文字列のリスト、
#  onEnter(commandline, text, mod)で受付の真偽、必要ならonStatusString(text)で状態文字列またはNoneを返します。
#  候補は最初のセミコロン以降のWindows引数・パス末尾部分へ置換する文字列です。このプロトコルのonCandidateは、
#  MainWindow.commandLineのcandidate_handlerと異なり(リスト, 開始位置)のタプルを返しません。
#  onEnterが真なら後続プロトコルを呼びません。onStatusStringはNoneなら次へ進み、空文字列なら表示を空にして終了します。
#  いずれもUIスレッドから呼ばれ、例外や長時間処理で入力を止めないようにします。
#  @sa MainWindow, CommandInfo
#
# \~english
# Execute named commands from the command line
#  Use the application's existing window.launcher. Add (name, callable) to command_list for execution and completion.
#  Search case-insensitively in list order; later same-name items do not execute.
#  Ignore whitespace around the input name only; retain the raw tail after the first semicolon and original input for history.
#  Names cannot contain the semicolon argument separator. JSON validates names on GUI save/load, allowing empty names and zero actions.
#  An empty JSON registration overrides a same-name built-in and does nothing for input/aliases. GUI saving of an empty name requires a Link.
#  A custom entry in commandline_list implements onCandidate(update_info) returning a list of strings,
#  onEnter(commandline, text, mod) returning whether it accepted input, and optionally onStatusString(text)
#  returning status text or None. Candidates replace the current Windows argument/path suffix after the first semicolon.
#  Unlike MainWindow.commandLine's candidate_handler, this protocol returns no (list, start) tuple.
#  A true onEnter stops later protocols. None status tries the next protocol; empty text ends status lookup without displaying text.
#  Callbacks run on the UI thread; avoid blocking input with errors or long work.
#  @sa MainWindow, CommandInfo
#
# \~
class commandline_Launcher:
    def __init__(self, main_window):
        self.main_window = main_window
        self.command_list = []

    ## \~japanese
    #  @param update_info 入力文字列と選択範囲を持つUpdateInfo。
    #  @return ディレクトリ・ファイル・登録コマンド名の候補文字列リスト。
    #  commandsモードは登録名のみ、offは空リスト。履歴との統合は入力仲介側で行います。
    #  統合候補は大文字・小文字を区別せず重複を除き、名前全体の補完では登録名の表記を優先します。
    #  ファイル列挙失敗は抑止し、その種類の候補を省略して入力を継続します。
    #
    # \~english
    #  @param update_info UpdateInfo containing input text and selection.
    #  @return List of directory, file and registered-command name candidates.
    #  commands mode returns names only; off returns an empty list. The input router merges history.
    #  Merged candidates deduplicate case-insensitively; whole-name completion prefers the registered spelling.
    #  Suppress file-enumeration errors, omit affected candidates and continue input.
    #
    # \~
    def onCandidate(self, update_info):
        mode = self.main_window.input_settings["COMPLETION_MODE"]
        if mode == "off":
            return []
        if mode == "commands":
            text = update_info.text.strip().lower()
            if not text:
                return []
            return [
                item[0]
                for item in self.command_list
                if item[0] and item[0].lower().startswith(text)
            ]

        basedir = "."

        left = update_info.text[: update_info.selectionLeft()]
        left_lower = left.lower()
        pos_arg = clnch_misc.commandlineArgumentStart(left)
        arg = left[pos_arg:]
        pos_dir = max(arg.rfind("/") + 1, arg.rfind("\\") + 1)
        directory = arg[:pos_dir]
        name_prefix = arg[pos_dir:].lower()

        dirname_list = []
        filename_list = []
        candidate_list = []

        if len(directory) > 0:
            try:
                path = ckit.joinPath(basedir, directory)

                drive, tail = os.path.splitdrive(path)
                unc = drive.startswith(("\\\\", "//"))

                if unc:
                    clnch_misc.checkNetConnection(path)
                if unc and not tail:
                    servername = drive.replace("/", "\\")
                    infolist = clnch_native.enumShare(servername)
                    for info in infolist:
                        if info[1] == 0 and info[0].lower().startswith(name_prefix):
                            if ckit.pathSlash():
                                dirname_list.append(info[0] + "/")
                            else:
                                dirname_list.append(info[0] + "\\")
                else:
                    infolist = clnch_native.findFile(
                        ckit.joinPath(path, "*"), use_cache=True
                    )
                    for info in infolist:
                        if info[0].lower().startswith(name_prefix):
                            if info[3] & ckit.FILE_ATTRIBUTE_DIRECTORY:
                                if ckit.pathSlash():
                                    dirname_list.append(info[0] + "/")
                                else:
                                    dirname_list.append(info[0] + "\\")
                            else:
                                filename_list.append(info[0])
            except Exception:  # noqa: BLE001, S110  # A failed filesystem completion must not interrupt typing.
                pass

        for item in self.command_list:
            item_lower = item[0].lower()
            if item_lower.startswith(left_lower):
                candidate_list.append(item[0])

        return dirname_list + filename_list + candidate_list

    ## \~japanese
    #  @param commandline 入力中の操作オブジェクト。
    #  @param text 名前と最初のセミコロン以降のWindows引数文字列。
    #  @param mod Enter受付時の修飾キービット。
    #  @return 一致を予約して入力終了を要求した場合True、一致なしはFalse。
    #  CommandInfo.argsへWindows解析した引数列、arg_stringへ原文、modへ修飾を設定し、入力終了後の実行を予約します。
    #
    # \~english
    #  @param commandline Active input-control object.
    #  @param text Command name and raw Windows arguments separated by the first semicolon.
    #  @param mod Modifiers when Enter was accepted.
    #  @return True after scheduling a match and requesting input exit; False if no name matches.
    #  Set CommandInfo.args to Windows-parsed arguments, arg_string to the original text and mod to modifiers; schedule after input ends.
    #
    # \~
    def onEnter(self, commandline, text, mod):
        command_name, _, arg_string = text.partition(";")
        command_name = command_name.strip().lower()

        def found(command):
            info = ckit.CommandInfo()
            info.args = split_commandline_args(arg_string)
            info.arg_string = arg_string
            info.mod = mod

            commandline.planCommand(command, info, text)
            commandline.quit()

        for command in self.command_list:
            if command[0].lower() == command_name:
                found(command[1])
                return True

        return False

    def onStatusString(self, text):
        return None


## \~japanese
# コマンドラインでファイルパスを起動する機能
#  onEnter(commandline, text, mod)は先頭のセミコロン区切りをパスとして実在を調べ、不在ならFalseを返します。
#  パス全体を囲むダブルクォートは一組だけ除去し、履歴には元の入力を保持します。
#  association_listの(空白区切りのパターン群, 関数)が一致すれば、パスを含むWindows解析済みargsとmodで関数を予約します。arg_stringは引用したパスと原文の引数です。
#  未一致なら最初のセミコロン以降を再引用せず、原文のまま既定JobQueueからShellへ渡します。
#  受付時は履歴・入力終了を処理してTrueを返します。onCandidateは空リスト、onStatusStringはNoneです。
#  通常は本体のcommandline_listに組み込まれ、独自に追加する必要はありません。
#
# \~english
# Open file paths from the command line
#  onEnter(commandline, text, mod) treats the first semicolon-separated field as a path and returns False if absent.
#  Remove only one pair of double quotes enclosing the entire path; keep the original input in history.
#  A matching association_list entry (space-separated patterns, callable) schedules it with Windows-parsed args including the path and mod; arg_string contains the quoted path and original argument text.
#  Otherwise pass the original text after the first semicolon to the Shell on the default JobQueue, without re-quoting.
#  Handle history/input exit on acceptance and return True. onCandidate returns [], onStatusString returns None.
#  Normally installed in the application's commandline_list; no need to add another instance.
#
# \~
class commandline_ExecuteFile:
    def __init__(self, main_window):
        self.main_window = main_window

    def onCandidate(self, update_info):
        return []

    def onEnter(self, commandline, text, mod):
        file, separator, arg_string = text.partition(";")
        file = unquote_path(file)

        if not os.path.exists(file):
            return False

        for association in self.main_window.association_list:
            for pattern in association[0].split():
                if fnmatch.fnmatch(file, pattern):
                    info = ckit.CommandInfo()
                    info.args = [file, *split_commandline_args(arg_string)]
                    info.arg_string = clnch_misc.joinArgs([file]) + (" " + arg_string if separator else "")
                    info.mod = mod

                    commandline.planCommand(association[1], info, text)
                    commandline.quit()

                    return True

        joint_args = arg_string

        directory, _tmp = ckit.splitPath(file)

        if not os.path.isabs(file):
            file = os.path.abspath(file)


        def jobShellExecute(job_item):
            pyauto.shellExecute(None, file, joint_args, directory)

        def jobShellExecuteFinished(job_item):
            pass

        job_item = ckit.JobItem(jobShellExecute, jobShellExecuteFinished)
        clnch_misc._require_job_queue(ckit.JobQueue.defaultQueue()).enqueue(job_item)

        commandline.appendHistory(text)

        commandline.quit()

        return True

    def onStatusString(self, text):
        return None


## \~japanese
# コマンドラインで URL を起動する機能
#  onEnter(commandline, text, mod)はhttp:またはhttps:で始まる文字列を大文字小文字を区別せず受付し、
#  既定JobQueueから文字列全体を開き、履歴追加・入力終了を処理してTrueを返します。その他はFalseです。
#  セミコロンで引数分割せず、URL全体を渡します。onCandidateは空リスト、onStatusStringはNoneです。
#  通常は本体のcommandline_listに組み込まれます。
#  @sa commandline_ExecuteFile
#
# \~english
# Open URLs from the command line
#  onEnter(commandline, text, mod) accepts strings starting with http: or https: case-insensitively,
#  opens the entire string on the default JobQueue, records history, requests input exit, and returns True; otherwise False.
#  Do not split URL arguments at semicolons. onCandidate returns [], onStatusString returns None.
#  Normally installed in the application's commandline_list.
#  @sa commandline_ExecuteFile
#
# \~
class commandline_ExecuteURL:
    def __init__(self, main_window):
        self.main_window = main_window

    def onCandidate(self, update_info):
        return []

    def onEnter(self, commandline, text, mod):
        if not (text.lower().startswith("http:") or text.lower().startswith("https:")):
            return False


        def jobShellExecute(job_item):
            pyauto.shellExecute(None, text, "", "")

        def jobShellExecuteFinished(job_item):
            pass

        job_item = ckit.JobItem(jobShellExecute, jobShellExecuteFinished)
        clnch_misc._require_job_queue(ckit.JobQueue.defaultQueue()).enqueue(job_item)

        commandline.appendHistory(text)

        commandline.quit()

        return True

    def onStatusString(self, text):
        return None


## @}
