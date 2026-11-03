import datetime
import os
import subprocess
from contextlib import ExitStack as _ExitStack
from contextlib import contextmanager as _contextmanager

import clnch_resource

import ckit as _ckit
import pyauto
from ckit.ckit_const import (
    ORIGIN_X_LEFT,
    ORIGIN_X_RIGHT,
    ORIGIN_Y_BOTTOM,
    ORIGIN_Y_TOP,
)
from ckit.ckit_misc import _cleanup_on_exit

## @cond japanese
## @addtogroup misc その他雑多な機能
## @endcond
## @cond english
## @addtogroup misc Miscellaneous
## @endcond
## @addtogroup misc
## @{

# --------------------------------------------------------------------

ignore_1second = True


def _require_data_path[PathValue](path: PathValue | None, *, for_abspath=False) -> PathValue:
    if path is None:
        message = (
            "_path_normpath: path should be string, bytes or os.PathLike, not NoneType"
            if for_abspath else "expected str, bytes or os.PathLike object, not NoneType"
        )
        raise TypeError(message)
    return path


def _require_job_queue(queue: _ckit.JobQueue | None) -> _ckit.JobQueue:
    if queue is None:
        raise AttributeError(
            "'NoneType' object has no attribute 'enqueue'", name="enqueue", obj=None
        )
    return queue


def _require_commandline_edit(edit: _ckit.EditWidget | None, attribute: str) -> _ckit.EditWidget:
    if edit is None:
        raise AttributeError(
            f"'NoneType' object has no attribute '{attribute}'", name=attribute, obj=None
        )
    return edit

# --------------------------------------------------------------------


@_contextmanager
def _modal_dialog_scope(parent, dialog, was_enabled):
    """Restore the pre-construction parent state and destroy the modal child."""
    with _ExitStack() as cleanup:
        cleanup.enter_context(_cleanup_on_exit(dialog.destroy))
        if was_enabled:
            cleanup.enter_context(_cleanup_on_exit(parent.activate))
            cleanup.enter_context(_cleanup_on_exit(parent.enable, True))
        yield


## \~japanese
#  @param size バイト数。
#  @return B/K/M/G/T表記の文字列。K以降は1024倍で換算し小数1桁、表示長により次単位へ進みます。
#
# \~english
#  @param size Byte count.
#  @return B/K/M/G/T text. Units after B use powers of 1024 and one decimal, advancing based on display length.
#
# \~
def getFileSizeString(size):
    if size < 1000:
        return "%dB" % (size,)  # noqa: UP031  # Preserve percent-d conversion for public values.

    if size < 1000 * 1024:
        s = "%.1fK" % (size / float(1024),)  # noqa: UP031  # Preserve numeric conversion and unit selection for custom numeric types.
        if len(s) <= 6:
            return s

    if size < 1000 * 1024 * 1024:
        s = "%.1fM" % (size / float(1024 * 1024),)  # noqa: UP031  # Preserve numeric conversion and unit selection for custom numeric types.
        if len(s) <= 6:
            return s

    if size < 1000 * 1024 * 1024 * 1024:
        s = "%.1fG" % (size / float(1024 * 1024 * 1024),)  # noqa: UP031  # Preserve numeric conversion and unit selection for custom numeric types.
        if len(s) <= 6:
            return s

    return "%.1fT" % (size / float(1024 * 1024 * 1024 * 1024),)  # noqa: UP031  # Preserve numeric conversion and unit selection for custom numeric types.


# --------------------------------------------------------------------

_net_connection_handler = None


## \~japanese
#  @param handler UNCサーバー名を1引数で受け取る関数。
#  @return None。アプリ共有の1つのハンドラを置換します。通常は本体が設定済みです。
#
# \~english
#  @param handler Callable accepting one UNC server name.
#  @return None. Replace a single application-shared handler, normally already installed by the application.
#
# \~
def registerNetConnectionHandler(handler):
    global _net_connection_handler
    _net_connection_handler = handler


## \~japanese
#  @param path 調べるパス文字列。
#  @return None。UNCならサーバー部分を抽出して登録ハンドラを呼び、ローカルパスは何もしません。
#  ハンドラ例外は表示して抑止します。UNC接続・認証の必要性と結果は登録ハンドラが扱います。
#
# \~english
#  @param path Path string to inspect.
#  @return None. For UNC, extract the server and call the registered handler; do nothing for local paths.
#  Print and suppress handler exceptions. The handler owns connection/authentication requirements and results.
#
# \~
def checkNetConnection(path):
    drive, _tail = os.path.splitdrive(path)
    unc = drive.startswith(("\\\\", "//"))

    if unc:
        remote_resource_name = drive.replace("/", "\\").rstrip("\\")
        try:
            handler = _net_connection_handler
            if handler is None:
                raise TypeError("'NoneType' object is not callable")
            handler(remote_resource_name)
        except Exception as e:  # noqa: BLE001  # Contain failures from the caller-provided network handler.
            print(e)


# --------------------------------------------------------------------


## \~japanese
#  @param t1 比較する日時の引数列（通常は年/月/日/時/分/秒）。
#  @param t2 比較対象の同形式の日時。
#  @return 同等は0、t1が後なら1、前なら-1。
#  共有ignore_1secondが真（既定）ならdatetimeへ展開し、絶対差1秒以内を同等扱いにします。
#
# \~english
#  @param t1 Date/time argument sequence, normally year/month/day/hour/minute/second.
#  @param t2 Date/time in the same format.
#  @return 0 if equivalent, 1 if t1 is later, -1 if earlier.
#  With shared ignore_1second=True (default), construct datetime values and treat an absolute difference of at most one second as equal.
#
# \~
def compareTime(t1, t2):
    if ignore_1second:
        delta = abs(datetime.datetime(*t1) - datetime.datetime(*t2))
        if delta.days == 0 and delta.seconds <= 1:
            return 0

    return (t1 > t2) - (t1 < t2)


# --------------------------------------------------------------------


## \~japanese
#  @return ReCraftLaunchのクラス名・タイトルに一致する最初のpyauto.Window。見つからなければNone。
#  他インスタンスの列挙のみで、起動・アクティブ化・IPC送信は行いません。
#
# \~english
#  @return First pyauto.Window matching ReCraftLaunch's class/title, or None if absent.
#  Only enumerate an existing instance; do not launch, activate or send IPC.
#
# \~
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


# --------------------------------------------------------------------


## \~japanese
#  @param s 置換する文字列。
#  @param map %...%を含むトークンから置換文字列への辞書。既定は%%を%にする定義。
#  @param environ 未一致トークンを環境変数名として展開するか。既定True。
#  @return 置換結果の新しい文字列。辞書を優先し、未定義・閉じる%がない部分は保持します。
#  シェル引用・引数分割・ファイル存在確認は行いません。
#
# \~english
#  @param s Input string.
#  @param map Mapping from percent-delimited tokens to replacement strings; defaults to %% becoming %.
#  @param environ Expand unmatched tokens as environment variables, default True.
#  @return Replaced string, prioritizing map entries and retaining undefined/unclosed tokens.
#  Do not perform shell quoting, argument splitting or file-existence checks.
#
# \~
def replaceMacro(s, map={"%%": "%"}, environ=True):  # noqa: B006  # This default mapping is read-only; avoid allocating it on every call.
    search_pos = 0

    while 1:
        var_start = s.find("%", search_pos)
        if var_start < 0:
            break

        var_end = s.find("%", var_start + 1)
        if var_end < 0:
            break

        try:
            after = map[s[var_start : var_end + 1]]
            s = s[:var_start] + after + s[var_end + 1 :]
            search_pos = var_start + len(after)
            continue
        except KeyError:
            pass

        if environ:
            try:
                after = os.environ[s[var_start + 1 : var_end]]
                s = s[:var_start] + after + s[var_end + 1 :]
                search_pos = var_start + len(after)
                continue
            except KeyError:
                pass

        search_pos += 1

    return s


## \~japanese
#  @param args 引数文字列のシーケンス。
#  @return subprocess.list2cmdlineによるWindows標準規則のコマンドライン文字列。空列は空文字列。
#  空引数・空白・引用符・バックスラッシュを保持する引用を行います。cmd.exe等のシェルメタ文字を保護する関数ではありません。
#  Pythonで作る引数列の整形用です。標準入力のarg_stringは本関数で再引用しません。filename/directory内の%param%はargsの空白連結です。
#
# \~english
#  @param args Sequence of argument strings.
#  @return Windows-standard command-line string from subprocess.list2cmdline, or empty text for an empty sequence.
#  Quote to preserve empty arguments, spaces, quotes and backslashes. This does not escape shell metacharacters for cmd.exe.
#  Use for Python-created argument lists; standard input arg_string bypasses this function. Filename/directory %param% joins args with spaces.
#
# \~
def joinArgs(args):
    return subprocess.list2cmdline(args)


# --------------------------------------------------------------------

def commandlineArgumentStart(text):
    """Completion suffix after the first semicolon and unquoted Windows spaces."""
    separator = text.find(";")
    if separator < 0 or text.lower().startswith(("http:", "https:")):
        return 0
    start = separator + 1
    quoted, backslashes = False, 0
    for index in range(start, len(text)):
        char = text[index]
        if char == '"' and backslashes % 2 == 0:
            quoted = not quoted
            if quoted and index == start:
                start = index + 1
        elif char in " \t" and not quoted:
            start = index + 1
        backslashes = backslashes + 1 if char == "\\" else 0
    return start


_commandline_normalize_table = str.maketrans("\t\r\n", "   ")


## \~japanese
#  @param s 入力文字列。
#  @return タブ・CR・LFを半角空白に置換した文字列。連続空白は保持します。
#  前後空白の除去やセミコロン分割は行いません。
#
# \~english
#  @param s Input string.
#  @return Text with tabs/CR/LF replaced by spaces; consecutive spaces are preserved.
#  Do not trim leading/trailing spaces or split semicolons.
#
# \~
def normalizeCommandLineText(s):
    return s.translate(_commandline_normalize_table)


# --------------------------------------------------------------------


## \~japanese
#  @param base_window 基準となる親窓。
#  @param new_window 配置するTextWindow。
#  @param default_up Trueなら上、Falseなら下を先に選びます。
#  @param monitor_adjust_vertical 縦方向で作業領域に収まるよう調整するか。
#  @param monitor_adjust_horizontal 横方向で調整するか。
#  @return None。位置は画面ピクセル、寸法はnew_window.width()/height()のセル値を使います。
#  基準窓の左上、中心、矩形間の最短距離の順にモニターを選びます。同距離なら矩形座標順です。
#  UIスレッドで呼びます。表示・親状態・破棄は行いません。
#
# \~english
#  @param base_window Reference parent window.
#  @param new_window TextWindow to position.
#  @param default_up Prefer above if True, below if False.
#  @param monitor_adjust_vertical Adjust vertically to fit the work area.
#  @param monitor_adjust_horizontal Adjust horizontally.
#  @return None. Use screen-pixel positions and new_window.width()/height() cell dimensions.
#  Select by parent top-left, then center, then shortest rectangle distance; break distance ties by rectangle coordinates.
#  Call on the UI thread; do not show, manage parent state or destroy windows.
#
# \~
def adjustWindowPosition(
    base_window,
    new_window,
    default_up,
    monitor_adjust_vertical=True,
    monitor_adjust_horizontal=True,
):
    base_window_rect = base_window.getWindowRect()

    x1 = base_window_rect[0]
    x2 = base_window_rect[2]
    y1 = base_window_rect[1]
    y2 = base_window_rect[3]

    if default_up:
        y = y1
        origin_y = ORIGIN_Y_BOTTOM
    else:
        y = y2
        origin_y = ORIGIN_Y_TOP

    x = x1
    origin_x = ORIGIN_X_LEFT

    monitor_info_list = pyauto.Window.getMonitorInfo()
    for px, py in ((x1, y1), ((x1 + x2) // 2, (y1 + y2) // 2)):
        monitor_info = next(
            (info for info in monitor_info_list
             if info[0][0] <= px < info[0][2] and info[0][1] <= py < info[0][3]),
            None,
        )
        if monitor_info is not None:
            break
    else:
        # Rectangle distance, then coordinates: never depend on enumeration order.
        monitor_info = min(
            monitor_info_list,
            key=lambda info: (
                max(info[0][0] - x2, x1 - info[0][2], 0) ** 2
                + max(info[0][1] - y2, y1 - info[0][3], 0) ** 2,
                info[0], info[1],
            ),
        )

    new_window_rect = new_window.getWindowRect()
    _char_w, _char_h = new_window.getCharSize()

    if monitor_adjust_vertical:
        if default_up:
            if (
                y1 - (new_window_rect[3] - new_window_rect[1])
                < monitor_info[1][1]
            ):
                y = y2
                origin_y = ORIGIN_Y_TOP
        else:
            if (
                y2 + (new_window_rect[3] - new_window_rect[1])
                >= monitor_info[1][3]
            ):
                y = y1
                origin_y = ORIGIN_Y_BOTTOM

    if (
        monitor_adjust_horizontal
        and x1 + (new_window_rect[2] - new_window_rect[0]) >= monitor_info[1][2]
    ):
        x = x2
        origin_x = ORIGIN_X_RIGHT

    new_window.setPosSize(
        x, y, new_window.width(), new_window.height(), origin_x | origin_y
    )
    rect = new_window.getWindowRect()
    work = monitor_info[1]
    x = (
        max(work[0], min(rect[0], work[2] - (rect[2] - rect[0])))
        if monitor_adjust_horizontal
        else rect[0]
    )
    y = (
        max(work[1], min(rect[1], work[3] - (rect[3] - rect[1])))
        if monitor_adjust_vertical
        else rect[1]
    )
    new_window.setPosSize(
        x, y, new_window.width(), new_window.height(), ORIGIN_X_LEFT | ORIGIN_Y_TOP
    )


## \~japanese
#  @param scale モニターの表示倍率（1.0等）。
#  @return 本体のフォント名・サイズに倍率を反映した共有Font。縦余白も倍率で丸めます。
#  拡張から共有フォントを破棄しません。
#
# \~english
#  @param scale Monitor display scale, such as 1.0.
#  @return Shared Font using the application's font name/size scaled and rounded, with scaled vertical padding.
#  Extensions must not destroy the shared font.
#
# \~
def getDialogFont(scale):
    import clnch_ini
    import clnch_inisettings as ini_settings

    import ckit

    return ckit.getStockedFont(
        ini_settings.FONT_NAME.get(clnch_ini),
        round(ini_settings.FONT_SIZE.get(clnch_ini) * scale),
        round(2 * scale),
    )


## @} misc
