import ctypes
import ctypes.wintypes
import msvcrt
import os
import shutil
import sys
import tempfile
import winsound
from contextlib import contextmanager as _contextmanager
from threading import RLock as _RLock
from typing import Protocol as _Protocol
from typing import TypeGuard as _TypeGuard

import pyauto
from ckit.ckit_const import ORIGIN_X_LEFT, ORIGIN_Y_TOP

## @addtogroup misc
## @{

# --------------------------------------------------------------------

_use_slash = False
_drive_case_upper = None


class _AppResourceSys(_Protocol):
    _clnch_app_dir: str


def _has_app_resource_dir(module: object) -> _TypeGuard[_AppResourceSys]:
    return hasattr(module, "_clnch_app_dir")


# --------------------------------------------------------------------


@_contextmanager
def _cleanup_on_exit(callback, *args, error_only=False):
    """Run every registered cleanup without replacing the first exception."""
    try:
        yield
    except BaseException as error:
        try:
            callback(*args)
        except BaseException as cleanup_error:  # noqa: BLE001  # Continue unwinding GUI resources and retain the primary failure.
            error.add_note(f"GUI cleanup failed: {cleanup_error!r}")
        raise
    else:
        if not error_only:
            callback(*args)


class ScrollInfo:
    def __init__(self):
        self.pos = 0

    def makeVisible(self, index, visible_height, margin=0):
        if margin > visible_height // 2:  # noqa: PLR1730  # Keep conditional updates; min/max calls were slower in the reviewed paths.
            margin = visible_height // 2
        if index < self.pos + margin:
            self.pos = index - margin
        elif index > self.pos + visible_height - 1 - margin:
            self.pos = index - visible_height + 1 + margin
        if self.pos < 0:  # noqa: PLR1730  # Keep conditional updates; min/max calls were slower in the reviewed paths.
            self.pos = 0


# --------------------------------------------------------------------


## \~japanese
# テキストのエンコーディングを表すクラス
#  TextEncoding(encoding="utf-8", bom=None)のencodingはPythonの文字コード名またはバイナリ判定を表すNone、bomはBOMのbytesまたはNoneです。
#  str変換はutf-8/BOMなしをutf-8n、cp932をshift-jis、それ以外をencodingのまま返します。encoding=Noneのstr変換はTypeErrorになります。
#  @sa detectTextEncoding
#
# \~english
# Represents a text encoding
#  TextEncoding(encoding="utf-8", bom=None) stores a Python encoding name or None for binary detection; bom is BOM bytes or None.
#  String conversion returns utf-8n for UTF-8 without BOM, shift-jis for cp932, otherwise encoding unchanged. Converting encoding=None to str raises TypeError.
#  @sa detectTextEncoding
#
# \~
class TextEncoding:
    def __init__(self, encoding="utf-8", bom=None):
        self.encoding: str | None = encoding
        self.bom = bom

    def __str__(self):
        if self.encoding == "utf-8" and self.bom is None:
            return "utf-8n"
        if self.encoding == "cp932":
            return "shift-jis"
        return self.encoding


## \~japanese
# テキストのエンコードを検出する
# 
#  @param data 検出するバイト列 (bytes)。str は渡せません。
#  @param maxlen デコードによる推測で調査する最大バイト数
#  @param maxline デコードによる推測で調査する最大行数
#  @param ascii_as asciiだと検出された場合の代替のエンコーディング
#  @return 検出結果を格納した TextEncoding オブジェクト
# 
#  渡されたデータのエンコーディングを推測します。
#  以下のエンコーディングの可能性を調査します。
# 
#  - ascii
#  - cp932
#  - euc-jp
#  - iso-2022-jp
#  - utf-8
#  - utf-16-le
#  - utf-16-be
# 
#  またバイナリデータであると推測された場合は、TextEncoding の encoding には None が入ります。
#  BOMの判定を最初に行い、UTF-16はBOMがある場合だけ判定します。
#  BOMがない場合は、maxlen による切り詰めより前に入力全体のNULを検査し、含まれていればバイナリと判定します。
# 
# \~english
# Detect a text encoding
# 
#  @param data Byte sequence (bytes) to inspect. str is not accepted.
#  @param maxlen Maximum number of bytes used for decoding-based detection
#  @param maxline Maximum number of lines used for decoding-based detection
#  @param ascii_as Replacement encoding when ASCII is detected
#  @return TextEncoding containing the detection result
# 
#  Guess the encoding of the supplied data.
#  The following encodings are considered.
# 
#  - ascii
#  - cp932
#  - euc-jp
#  - iso-2022-jp
#  - utf-8
#  - utf-16-le
#  - utf-16-be
# 
#  If the input appears binary, the returned TextEncoding has encoding=None.
#  Check the BOM first. UTF-16 is detected only when a BOM is present.
#  Without a BOM, check the entire input for NUL before applying maxlen; any NUL marks the input as binary.
# 
# \~
def detectTextEncoding(data, maxlen=1024 * 1024, maxline=1000, ascii_as=None):
    result = TextEncoding()

    if data[:3] == b"\xef\xbb\xbf":
        result.encoding = "utf-8"
        result.bom = b"\xef\xbb\xbf"
        return result
    elif data[:2] == b"\xff\xfe":
        result.encoding = "utf-16-le"
        result.bom = b"\xff\xfe"
        return result
    elif data[:2] == b"\xfe\xff":
        result.encoding = "utf-16-be"
        result.bom = b"\xfe\xff"
        return result

    if data.find(b"\0") >= 0:
        result.encoding = None
        return result

    if len(data) > maxlen:
        data = data[:maxlen]

    lines = data.splitlines()

    encoding_list = [
        ["ascii", 0],
        ["cp932", 0],
        ["euc-jp", 0],
        ["iso-2022-jp", 0],
        ["utf-8", 0],
    ]

    numline_read = 0

    for line in lines:
        for encoding in encoding_list:
            try:
                uniode_line = line.decode(encoding=encoding[0])
            except UnicodeDecodeError:
                encoding[1] -= 1
            else:
                if len(uniode_line) < len(line):
                    encoding[1] += 1

        numline_read += 1
        if numline_read >= maxline:
            break

    best_encoding = [None, -1 - numline_read // 100]

    for encoding in encoding_list:
        if encoding[1] > best_encoding[1]:
            best_encoding = encoding

    result.encoding = best_encoding[0]

    if result.encoding == "ascii" and ascii_as:
        result.encoding = ascii_as

    return result


## \~japanese
# 文字列の先頭に連続するBOM文字 (U+FEFF、U+FFFE) を除去して返す
# 
#  文字列の途中にあるBOM文字は除去しません。
# \~english
# Remove all consecutive leading BOM characters (U+FEFF and U+FFFE)
# 
#  BOM characters inside the string are preserved.
# \~
def removeBom(s):
    return s.lstrip("\ufeff\ufffe")


# --------------------------------------------------------------------

_argv = None


## \~japanese
# Unicode 形式で sys.argv 相当の情報を取得する
#  @return Unicode文字列の引数リスト。最初の取得結果をキャッシュし、同じ可変リストを返します。
#  本体の引数を変更する目的でこのリストを書き換えないでください。
#  @exception OSError Win32引数取得失敗。失敗した結果はキャッシュしません。
#
# \~english
# Get sys.argv-equivalent information as Unicode strings
#  @return List of Unicode argument strings. Cache the first result and return the same mutable list.
#  Do not mutate it to change application arguments.
#  @exception OSError Win32 argument retrieval failure. Failed results are not cached.
#
# \~
def getArgv():
    global _argv

    if _argv is None:
        from ctypes import POINTER, byref, c_int, cdll, windll
        from ctypes.wintypes import HLOCAL, LPCWSTR, LPWSTR

        GetCommandLineW = cdll.kernel32.GetCommandLineW
        GetCommandLineW.argtypes = []
        GetCommandLineW.restype = LPCWSTR

        CommandLineToArgvW = windll.shell32.CommandLineToArgvW
        CommandLineToArgvW.argtypes = [LPCWSTR, POINTER(c_int)]
        CommandLineToArgvW.restype = POINTER(LPWSTR)

        LocalFree = windll.kernel32.LocalFree
        LocalFree.argtypes = [HLOCAL]
        LocalFree.restype = HLOCAL

        cmd = GetCommandLineW()
        argc = c_int(0)
        argv = CommandLineToArgvW(cmd, byref(argc))
        if not argv:
            raise ctypes.WinError()

        try:
            result = []
            if argc.value > 0:
                # Remove Python executable and commands if present
                start = argc.value - len(sys.argv)
                for i in range(start, argc.value):
                    result.append(argv[i])
        finally:
            LocalFree(ctypes.cast(argv, HLOCAL))
        _argv = result

    return _argv


## \~japanese
# デスクトップディレクトリを取得する
#  @return 現在のユーザーのデスクトップのパス文字列。作成はしません。
#  Win32の取得結果を返し、失敗をOSErrorへ変換しません。
#
# \~english
# Get the desktop directory
#  @return Current user's desktop path string without creating it.
#  Return the Win32 result without converting failure to OSError.
#
# \~
def getDesktopPath():
    MAX_PATH = 260
    CSIDL_DESKTOPDIRECTORY = 0x10

    buf = ctypes.create_unicode_buffer(MAX_PATH)
    ctypes.windll.shell32.SHGetSpecialFolderPathW(None, buf, CSIDL_DESKTOPDIRECTORY, 0)

    return buf.value


## \~japanese
# アプリケーションの資源を参照するディレクトリを取得する
# 
#  通常実行では実行ファイルの格納ディレクトリ、開発実行では sys._clnch_app_dir を返します。
#  実行ファイル名を含むパスではありません。
# \~english
# Get the directory containing application resources
# 
#  Normally return the executable directory; in development return sys._clnch_app_dir.
#  The result is a directory, not a path including the executable filename.
# \~
def getAppExePath():
    # Keep development resources beside the repository sources.
    if _has_app_resource_dir(sys):
        return sys._clnch_app_dir
    return os.path.split(getArgv()[0])[0]


## \~japanese
# ユーザーのRoaming AppDataディレクトリ (%APPDATA%) を取得する
# 
#  アプリ固有の設定保存先ではありません。選択中の設定保存先は dataPath() で取得します。
# \~english
# Get the user's Roaming AppData directory (%APPDATA%)
# 
#  This is not the application-specific settings directory. Use dataPath() for the selected settings location.
# \~
def getAppDataPath():
    MAX_PATH = 260
    CSIDL_APPDATA = 26

    buf = ctypes.create_unicode_buffer(MAX_PATH)
    ctypes.windll.shell32.SHGetSpecialFolderPathW(None, buf, CSIDL_APPDATA, 0)

    return buf.value


## \~japanese
# ドキュメントディレクトリのパスを取得する
#  @return 現在のユーザーのDocumentsパス文字列。フォルダーを作成しません。
#
# \~english
# Get the Documents directory
#  @return Current user's Documents path string without creating a directory.
#
# \~
def getDocumentsPath():
    MAX_PATH = 260
    CSIDL_PERSONAL = 5

    buf = ctypes.create_unicode_buffer(MAX_PATH)
    ctypes.windll.shell32.SHGetSpecialFolderPathW(None, buf, CSIDL_PERSONAL, 0)

    return buf.value


## \~japanese
# ユーザプロファイルディレクトリのパスを取得する
#  @return 現在のユーザープロファイルのパス文字列。ReCraftLaunchの設定先ではありません。
#
# \~english
# Get the user-profile directory
#  @return Current user-profile path string; this is not the ReCraftLaunch settings directory.
#
# \~
def getProfilePath():
    MAX_PATH = 260
    CSIDL_PROFILE = 40

    buf = ctypes.create_unicode_buffer(MAX_PATH)
    ctypes.windll.shell32.SHGetSpecialFolderPathW(None, buf, CSIDL_PROFILE, 0)

    return buf.value


## \~japanese
# テンポラリファイル用ディレクトリのパスを取得する
#  @return Windowsが返す一時ディレクトリのパス文字列。独自の一時ファイルはmakeTempFile等で作成します。
#
# \~english
# Get the temporary-file directory
#  @return Temporary-directory path string from Windows. Use makeTempFile or related functions to create a file.
#
# \~
def getTempPath():
    MAX_PATH = 260

    buf = ctypes.create_unicode_buffer(MAX_PATH)
    ctypes.windll.kernel32.GetTempPathW(MAX_PATH, buf)

    return buf.value


_data_path = None


## \~japanese
# アプリケーションのデータ格納用のパスを取得する
# @sa setDataPath
#  @return 本体が選んだ設定保存先のパス。設定前はNone。通常custom.py実行時には設定済みです。
#  アプリ内settings/かAppDataかを自分で決め打ちせず、この値を使います。
#
# \~english
# Get the application's data directory
# @sa setDataPath
#  @return Settings directory selected by the application, or None before initialization; normally set by custom.py execution.
#  Use this value instead of assuming application-local settings/ or AppData.
#
# \~
def dataPath():
    return _data_path


## \~japanese
# アプリケーションのデータ格納用のパスを設定する
# @sa dataPath
#  @param data_path 本体が確定した設定保存先。値をそのまま保持します。
#  @return None。ディレクトリ作成・設定移動はしません。拡張は通常dataPathで読み取るだけにします。
#
# \~english
# Set the application's data directory
# @sa dataPath
#  @param data_path Selected settings directory; store the value unchanged.
#  @return None. Do not create directories or move settings. Extensions normally only read dataPath.
#
# \~
def setDataPath(data_path):
    global _data_path
    _data_path = data_path


## \~japanese
# 利用可能なドライブ文字を連結した文字列を取得する
#  @return 利用可能なドライブ文字を大文字で連結した文字列。例: CDE。コロン・区切りは含みません。
#
# \~english
# Get a string containing all available drive letters
#  @return Available uppercase drive letters concatenated, for example CDE, without colons or separators.
#
# \~
def getDrives():
    drives = ""
    drive_bits = ctypes.windll.kernel32.GetLogicalDrives()
    for i in range(26):
        if drive_bits & (1 << i):
            drives += chr(ord("A") + i)
    return drives


## \~japanese
# ドライブの種別を取得する
#  @param drive C:\\等のルートパス文字列。
#  @return Removable/HDD/Network/CD/DVD/Ramdiskの文字列。未判別・不在は空文字列。
#
# \~english
# Get the drive type
#  @param drive Root path string such as C:\\.
#  @return Removable/HDD/Network/CD/DVD/Ramdisk string, or empty text if unknown/absent.
#
# \~
def getDriveType(drive):
    DRIVE_TYPE_UNDTERMINED = 0
    DRIVE_ROOT_NOT_EXIST = 1
    DRIVE_REMOVABLE = 2
    DRIVE_FIXED = 3
    DRIVE_REMOTE = 4
    DRIVE_CDROM = 5
    DRIVE_RAMDISK = 6

    drive_type = ctypes.windll.kernel32.GetDriveTypeW(drive)

    if drive_type == DRIVE_TYPE_UNDTERMINED or drive_type == DRIVE_ROOT_NOT_EXIST:
        return ""
    elif drive_type == DRIVE_REMOVABLE:
        return "Removable"
    elif drive_type == DRIVE_FIXED:
        return "HDD"
    elif drive_type == DRIVE_REMOTE:
        return "Network"
    elif drive_type == DRIVE_CDROM:
        return "CD/DVD"
    elif drive_type == DRIVE_RAMDISK:
        return "Ramdisk"
    return ""


## \~japanese
# ドライブの表示用の文字列を取得する
# 
#  "C:\" の形式で渡す必要があります
# 
#  @param drive ドライブのルートパス文字列。
#  @return Shellが返す表示名文字列。ファイルシステム上のパスとは区別してください。
#
# \~english
# Get the drive's display name
# 
#  Pass the drive in the form "C:\\".
# 
#  @param drive Drive-root path string.
#  @return Shell display-name string, distinct from a filesystem path.
#
# \~
def getDriveDisplayName(drive):
    MAX_PATH = 260

    class SHFILEINFO(ctypes.Structure):
        _fields_ = [
            ("hIcon", ctypes.wintypes.HICON),
            ("iIcon", ctypes.c_int),
            ("dwAttributes", ctypes.wintypes.DWORD),
            ("szDisplayName", ctypes.c_wchar * MAX_PATH),
            ("szTypeName", ctypes.c_wchar * 80),
        ]

    SHGFI_DISPLAYNAME = 0x000000200

    shfileinfo = SHFILEINFO()

    flags = SHGFI_DISPLAYNAME
    ctypes.windll.shell32.SHGetFileInfoW(
        drive, 0, ctypes.byref(shfileinfo), ctypes.sizeof(shfileinfo), flags
    )

    return shfileinfo.szDisplayName


FILE_ATTRIBUTE_READONLY = 0x00000001
FILE_ATTRIBUTE_HIDDEN = 0x00000002
FILE_ATTRIBUTE_SYSTEM = 0x00000004
FILE_ATTRIBUTE_DIRECTORY = 0x00000010
FILE_ATTRIBUTE_ARCHIVE = 0x00000020
FILE_ATTRIBUTE_DEVICE = 0x00000040
FILE_ATTRIBUTE_NORMAL = 0x00000080
FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400


## \~japanese
# ファイルの属性を取得する
#  @param filename 対象パス文字列。
#  @return Win32属性ビットの整数。FILE_ATTRIBUTE_DIRECTORY等とビット演算します。
#  取得失敗時の-1をディレクトリ等と誤判定しないでください。OSErrorへの自動変換はしません。
#
# \~english
# Get file attributes
#  @param filename Target path string.
#  @return Integer Win32 attribute bits; test with FILE_ATTRIBUTE_DIRECTORY and related masks.
#  Do not interpret failure value -1 as valid attributes. Do not automatically raise OSError.
#
# \~
def getFileAttribute(filename):
    return ctypes.windll.kernel32.GetFileAttributesW(filename)


## \~japanese
# ファイルの属性を設定する
#  @param filename 対象パス文字列。
#  @param attribute 置換するWin32属性ビット。変更したいビットだけの差分ではありません。
#  @return Win32の結果整数。成功は非0、失敗は0。ファイルの属性を実際に変更します。
#
# \~english
# Set file attributes
#  @param filename Target path string.
#  @param attribute Replacement Win32 attribute mask, not a delta of changed bits.
#  @return Win32 integer result, nonzero on success, 0 on failure. Actually change file attributes.
#
# \~
def setFileAttribute(filename, attribute):
    return ctypes.windll.kernel32.SetFileAttributesW(filename, attribute)


## \~japanese
# ゴミ箱を使ってファイルを削除する
#  @param hwnd 確認・エラー画面の親となるHWND整数。
#  @param filename_list 削除するパス文字列のリスト。
#  @return SHFileOperationWの結果整数。0は成功、非0はエラーコードです。
#  FOF_ALLOWUNDOとFOF_NOCONFIRMATIONを指定して実際に削除を要求します。一般の削除確認を自動表示するAPIではありません。
#  ゴミ箱の利用可否は対象・Windowsの条件に従います。結果値だけで一部取消の詳細を取得することはできません。
#
# \~english
# Delete files using the Recycle Bin
#  @param hwnd Integer owner HWND for confirmation/error windows.
#  @param filename_list List of path strings to delete.
#  @return SHFileOperationW integer result: 0 for success, nonzero for an error code.
#  Actually request deletion with FOF_ALLOWUNDO and FOF_NOCONFIRMATION; this API does not automatically ask ordinary deletion confirmation.
#  Recycle Bin availability depends on the target and Windows. The result alone does not expose partial-abort details.
#
# \~
def deleteFilesUsingRecycleBin(hwnd, filename_list):
    class SHFILEOPSTRUCT(ctypes.Structure):
        _fields_ = [
            ("hwnd", ctypes.wintypes.HWND),
            ("wFunc", ctypes.wintypes.UINT),
            ("pFrom", ctypes.c_wchar_p),
            ("pTo", ctypes.c_wchar_p),
            ("fFlags", ctypes.wintypes.WORD),
            ("fAnyOperationsAborted", ctypes.wintypes.BOOL),
            ("hNameMappings", ctypes.c_void_p),
            ("lpszProgressTitle", ctypes.c_wchar_p),
        ]

    joint_filenames = ""
    for filename in filename_list:
        filename = filename.replace("/", "\\")
        joint_filenames += filename
        joint_filenames += "\0"
    joint_filenames += "\0"
    c_joint_filenames = ctypes.create_unicode_buffer(joint_filenames)

    fileopdata = SHFILEOPSTRUCT()

    FO_DELETE = 3

    FOF_NOCONFIRMATION = 16
    FOF_ALLOWUNDO = 64

    fileopdata.hwnd = hwnd
    fileopdata.wFunc = FO_DELETE
    fileopdata.pFrom = ctypes.cast(ctypes.byref(c_joint_filenames), ctypes.c_wchar_p)
    fileopdata.pTo = 0
    fileopdata.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION
    fileopdata.fAnyOperationsAborted = 0
    fileopdata.hNameMappings = 0
    fileopdata.lpszProgressTitle = 0
    return ctypes.windll.shell32.SHFileOperationW(ctypes.byref(fileopdata))


## \~japanese
# ディスクの空き容量と全体の容量を取得する
#  @param drive 対象ドライブまたはディレクトリのパス文字列。
#  @return (空きバイト数, 総バイト数)。呼出しユーザー固有の利用可能量でなくfree_sizeを返します。
#  Win32失敗を例外へ変換しません。
#
# \~english
# Get free space and total disk capacity
#  @param drive Drive or directory path string.
#  @return (free_bytes, total_bytes). Return free_size, not the caller-specific free_size_for_user.
#  Do not convert Win32 failures to exceptions.
#
# \~
def getDiskSize(drive):
    free_size_for_user = ctypes.c_longlong()
    total_size = ctypes.c_longlong()
    free_size = ctypes.c_longlong()
    ctypes.windll.kernel32.GetDiskFreeSpaceExW(
        drive,
        ctypes.byref(free_size_for_user),
        ctypes.byref(total_size),
        ctypes.byref(free_size),
    )

    return (free_size.value, total_size.value)


# --------------------------------------------------------------------

CF_UNICODETEXT = 13
GHND = 66

# Private function objects keep clipboard signatures independent of ctypes.windll users.
_clipboard_kernel32 = ctypes.WinDLL("kernel32")
_clipboard_user32 = ctypes.WinDLL("user32")
# Windows clipboard client data is process-wide; serialize complete transactions.
_clipboard_lock = _RLock()
for _dll, _name, _restype, _argtypes in (
    (_clipboard_kernel32, "GlobalAlloc", ctypes.c_void_p, (ctypes.c_uint, ctypes.c_size_t)),
    (_clipboard_kernel32, "GlobalLock", ctypes.c_void_p, (ctypes.c_void_p,)),
    (_clipboard_kernel32, "GlobalUnlock", ctypes.c_int, (ctypes.c_void_p,)),
    (_clipboard_kernel32, "GlobalFree", ctypes.c_void_p, (ctypes.c_void_p,)),
    (_clipboard_user32, "OpenClipboard", ctypes.c_int, (ctypes.c_void_p,)),
    (_clipboard_user32, "CloseClipboard", ctypes.c_int, ()),
    (_clipboard_user32, "EmptyClipboard", ctypes.c_int, ()),
    (_clipboard_user32, "GetClipboardData", ctypes.c_void_p, (ctypes.c_uint,)),
    (_clipboard_user32, "SetClipboardData", ctypes.c_void_p, (ctypes.c_uint, ctypes.c_void_p)),
):
    _function = getattr(_dll, _name)
    _function.restype = _restype
    _function.argtypes = _argtypes


## \~japanese
# クリップボードのテキストを取得する
# 
#  @return クリップボードから取得した文字列
# 
#  CF_UNICODETEXTとして取得します。取得不能・テキストなしは空文字列を返します。
#  クリップボードはOSの共有状態です。戻り値は新しいPython文字列として使えます。
#  同じプロセスの取得・設定は直列化します。文字列のコピー後にUnlockし、成功したOpenは例外時もCloseします。
#  取得したメモリはOSが所有し、この関数では解放しません。絵文字等のUTF-16補助平面文字も保持します。
#
# \~english
# Get text from the clipboard
# 
#  @return Clipboard text
# 
#  Read CF_UNICODETEXT; unavailable/non-text content returns an empty string.
#  The clipboard is shared OS state. Use the returned value as a Python string.
#  Serialize reads/writes within the process. Unlock after copying the string and close every successful open, including on exceptions.
#  The OS owns the retrieved memory; this function does not free it. Preserve UTF-16 supplementary characters such as emoji.
#
# \~
def getClipboardText():
    with _clipboard_lock:
        if not _clipboard_user32.OpenClipboard(0):
            return ""
        with _cleanup_on_exit(_clipboard_user32.CloseClipboard):
            hClipMem = _clipboard_user32.GetClipboardData(CF_UNICODETEXT)
            if not hClipMem:
                return ""
            pointer = _clipboard_kernel32.GlobalLock(hClipMem)
            if not pointer:
                return ""
            with _cleanup_on_exit(_clipboard_kernel32.GlobalUnlock, hClipMem):
                return ctypes.wstring_at(pointer)


## \~japanese
# クリップボードにテキストを設定する
# 
#  @param text  クリップボードに設定する文字列
# 
#  @return None。共有クリップボードの現在内容を置換します。成功可否の戻り値はありません。
#  例: setClipboardText("hello")。通常はユーザーが実行したコマンドの中で使います。
#  CF_UNICODETEXTのNUL終端UTF-16を設定し、絵文字等の補助平面文字を保持します。取得・設定はプロセス内で直列化します。
#  確保・Lock・Open・Empty・SetのOS失敗は戻り値で通知しません。Set成功後だけメモリをOSへ渡し、それまでは失敗・例外時に解放します。
#  成功したLock／OpenはUnlock／Closeします。Empty後にSetが失敗した場合、以前の内容は復元しません。Python例外は伝播します。
#
# \~english
# Set clipboard text
# 
#  @param text  Text to place on the clipboard
# 
#  @return None. Replace current shared clipboard content without returning success status.
#  Example: setClipboardText("hello"). Normally use inside a user-invoked command.
#  Write NUL-terminated UTF-16 as CF_UNICODETEXT, preserving supplementary characters such as emoji. Serialize reads/writes within the process.
#  OS allocation/lock/open/empty/set failures have no return status. Transfer memory to the OS only after Set succeeds; free it on earlier failure or exception.
#  Unlock/close successful locks/opens. A failed Set after Empty does not restore previous content. Python exceptions propagate.
#
# \~
def setClipboardText(text):
    with _clipboard_lock:
        buffer = ctypes.create_unicode_buffer(text)
        bufferSize = ctypes.sizeof(buffer)
        hGlobalMem = _clipboard_kernel32.GlobalAlloc(GHND, bufferSize)
        if not hGlobalMem:
            return
        try:
            pointer = _clipboard_kernel32.GlobalLock(hGlobalMem)
            if not pointer:
                return
            with _cleanup_on_exit(_clipboard_kernel32.GlobalUnlock, hGlobalMem):
                ctypes.memmove(pointer, buffer, bufferSize)
            if not _clipboard_user32.OpenClipboard(0):
                return
            with _cleanup_on_exit(_clipboard_user32.CloseClipboard):
                if (_clipboard_user32.EmptyClipboard() and
                        _clipboard_user32.SetClipboardData(CF_UNICODETEXT, hGlobalMem)):
                    hGlobalMem = None
        finally:
            if hGlobalMem:
                _clipboard_kernel32.GlobalFree(hGlobalMem)


## \~japanese
# クリップボードのシーケンスナンバーを取得する
# 
#  @return Windowsのクリップボード更新番号の整数。変更検出用で、内容やコピー件数ではありません。
#
# \~english
# Get the clipboard sequence number
# 
#  @return Integer Windows clipboard sequence number, for change detection rather than content or copy count.
#
# \~
def getClipboardSequenceNumber():
    return ctypes.windll.user32.GetClipboardSequenceNumber()


# --------------------------------------------------------------------


## \~japanese
# ファイルが他のプロセスから変更されないように共有ロックするためのクラス
# 
#  開いているファイル記述子から共有読取ロックを取得するクラスです。コンストラクターは待たずに取得を試み、失敗はOSErrorを送出します。
#  使用後は明示的にunlock()し、その後ファイルを閉じます。このクラス自体はファイルをcloseせず、with用のコンテキストマネージャーでもありません。
#
# \~english
# Acquire a shared file lock to prevent other processes from changing the file
# 
#  Acquire a shared read lock from an open file descriptor. Construction tries immediately without waiting, raising OSError on failure.
#  Explicitly unlock() before closing the file. This object neither closes the file nor implements a with context manager.
#
# \~
class FileReaderLock:
    class OVERLAPPED(ctypes.Structure):
        _fields_ = [
            ("Internal", ctypes.wintypes.LPVOID),
            ("InternalHigh", ctypes.wintypes.LPVOID),
            ("Offset", ctypes.wintypes.DWORD),
            ("OffsetHigh", ctypes.wintypes.DWORD),
            # ('Pointer', ctypes.wintypes.LPVOID),
            ("hEvent", ctypes.wintypes.HANDLE),
        ]

    ## \~japanese
    # コンストラクタ
    # 
    #  @param fileno  ロックしたいファイルのfileno
    # 
    # \~english
    # Constructor
    # 
    #  @param fileno  File descriptor of the file to lock
    # 
    # \~
    def __init__(self, fileno):
        self.handle = msvcrt.get_osfhandle(fileno)

        LOCKFILE_FAIL_IMMEDIATELY = 0x00000001

        overlapped = FileReaderLock.OVERLAPPED()

        result = ctypes.windll.kernel32.LockFileEx(
            self.handle,
            LOCKFILE_FAIL_IMMEDIATELY,
            0,
            0xFFFFFFFF,
            0xFFFFFFFF,
            ctypes.byref(overlapped),
        )

        if result == 0:
            raise ctypes.WinError()

        self.locked = True

    ## \~japanese
    # ロック解除
    # 
    #  @return None。未ロックなら何もしません。
    #  @exception OSError Win32ロック解除失敗。失敗時はlocked状態を保持します。
    #
    # \~english
    # Release the lock
    # 
    #  @return None; do nothing if already unlocked.
    #  @exception OSError Win32 unlock failure; retain locked state on failure.
    #
    # \~
    def unlock(self):
        if not self.locked:
            return

        overlapped = FileReaderLock.OVERLAPPED()

        result = ctypes.windll.kernel32.UnlockFileEx(
            self.handle,
            0,
            0xFFFFFFFF,
            0xFFFFFFFF,
            ctypes.byref(overlapped),
        )

        if result == 0:
            raise ctypes.WinError()

        self.locked = False


# --------------------------------------------------------------------

WM_CLOSE = 16


## \~japanese
# 指定したプロセスIDの最初のウィンドウへ終了を要求する
# 
#  該当ウィンドウへ WM_CLOSE を送ります。ウィンドウがない場合は何もせず、強制終了や終了待ちは行いません。
#  対象が要求を受け入れて終了することは保証しません。
# \~english
# Request exit through the first window belonging to the specified process ID
# 
#  Send WM_CLOSE to the matching window. If none exists, do nothing. Do not forcibly terminate the process or wait for exit.
#  The target is not guaranteed to accept the request or exit.
# \~
def terminateProcess(pid):
    def callback(wnd, arg):
        wnd_pid = ctypes.c_int(0)
        ctypes.windll.user32.GetWindowThreadProcessId(
            wnd.getHWND(), ctypes.byref(wnd_pid)
        )
        if wnd_pid.value == pid:
            wnd.sendMessage(WM_CLOSE, 0, 0)
            return False
        return True

    pyauto.Window.enum(callback, None)


# --------------------------------------------------------------------

ELLIPSIS_NONE = 0
ELLIPSIS_RIGHT = 1
ELLIPSIS_MID = 2

ALIGN_LEFT = 0
ALIGN_CENTER = 1
ALIGN_RIGHT = 2


## \~japanese
# 文字列を指定した長さに調節する
#  @param window getStringWidthを提供するTextWindow等。
#  @param s 調整する文字列。
#  @param width 表示セル幅。通常は非負整数。
#  @param align ALIGN_LEFT/ALIGN_CENTER/ALIGN_RIGHT。短い文字列の空白の配置。
#  @param ellipsis ELLIPSIS_NONEで切詰め、ELLIPSIS_RIGHTで末尾、ELLIPSIS_MIDで中間を省略。
#  @return 調整した文字列。入力を変更しません。文字数でなくフォントの表示幅を使います。
#  不正なalign/ellipsisはAssertionErrorです。省略記号を使う場合は十分な幅を確保してください。
#
# \~english
# Adjust a string to the specified display width
#  @param window TextWindow or object exposing getStringWidth.
#  @param s Input string.
#  @param width Display-cell width, normally a nonnegative integer.
#  @param align ALIGN_LEFT/ALIGN_CENTER/ALIGN_RIGHT for padding short text.
#  @param ellipsis ELLIPSIS_NONE truncates, ELLIPSIS_RIGHT elides the end, ELLIPSIS_MID the middle.
#  @return Adjusted string without modifying input; use font display width rather than character count.
#  Invalid align/ellipsis raises AssertionError. Provide sufficient width for ellipsis modes.
#
# \~
def adjustStringWidth(window, s, width, align=ALIGN_LEFT, ellipsis=ELLIPSIS_NONE):
    if ellipsis == ELLIPSIS_RIGHT:
        original_width = window.getStringWidth(s)
        if original_width > width:
            str_width = 0
            pos = 0
            while True:
                char_width = window.getStringWidth(s[pos])
                if str_width + char_width >= width - 1:
                    if str_width + char_width == width - 1:
                        return "%s\u22ef" % (s[: pos + 1])  # noqa: UP031  # Preserve percent-s conversion for public values.
                    else:
                        return "%s\u22ef " % (s[:pos])  # noqa: UP031  # Preserve percent-s conversion for public values.
                str_width += char_width
                pos += 1

    elif ellipsis == ELLIPSIS_MID:
        original_width = window.getStringWidth(s)
        if original_width > width:
            left_width = (width - 1) // 2
            str_width = 0
            pos = 0
            while True:
                char_width = window.getStringWidth(s[pos])
                if str_width + char_width >= left_width:
                    if str_width + char_width == left_width:
                        str_width += char_width
                    break
                str_width += char_width
                pos += 1
            left_string = s[:pos]

            right_width = width - str_width - 1
            str_width = 0
            pos = len(s)
            while True:
                pos -= 1
                char_width = window.getStringWidth(s[pos])
                if str_width + char_width >= right_width:
                    if str_width + char_width == right_width:
                        str_width += char_width
                    break
                str_width += char_width
            right_string = s[pos:]
            return "%s\u22ef%s" % (left_string, right_string)  # noqa: UP031  # Preserve percent-s conversion for public values.

    elif ellipsis == ELLIPSIS_NONE:
        original_width = window.getStringWidth(s)
        if original_width > width:
            left_width = width
            pos = 0
            while True:
                left_width -= window.getStringWidth(s[pos])
                if left_width < 0:
                    break
                pos += 1
            return s[:pos]

    else:
        assert 0

    if align == ALIGN_LEFT:
        return s + " " * (width - original_width)

    elif align == ALIGN_RIGHT:
        return " " * (width - original_width) + s

    elif align == ALIGN_CENTER:
        delta = width - original_width
        left_space = delta // 2
        right_space = delta - left_space
        return " " * left_space + s + " " * right_space

    else:
        assert 0


## \~japanese
#  @param window 既存の窓。
#  @return 窓中心のモニターの作業領域(left, top, right, bottom)。画面ピクセル単位。
#  該当モニターがなければ先頭モニターの作業領域を返します。
#
# \~english
#  @param window Existing window.
#  @return (left, top, right, bottom) work area of the monitor containing the window center, in screen pixels.
#  If none matches, return the first monitor's work area.
#
# \~
def getWindowWorkArea(window):
    rect = window.getWindowRect()
    x, y = (rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2
    monitors = pyauto.Window.getMonitorInfo()
    return next(
        (
            info[1]
            for info in monitors
            if info[0][0] <= x < info[0][2] and info[0][1] <= y < info[0][3]
        ),
        monitors[0][1],
    )


## \~japanese
#  @param window getWindowRect/getClientSize/getCharSizeを持つ文字窓。
#  @param border_size 内容周囲の枠ピクセル幅。既定1。
#  @return 作業領域に収められる(最大セル幅, 最大行数)。それぞれ最低2です。
#
# \~english
#  @param window Text window exposing getWindowRect/getClientSize/getCharSize.
#  @param border_size Border width around content in pixels, default 1.
#  @return (maximum_cell_width, maximum_rows) fitting the work area, each at least 2.
#
# \~
def getWindowSizeLimits(window, border_size=1):
    work = getWindowWorkArea(window)
    rect = window.getWindowRect()
    client_w, client_h = window.getClientSize()
    char_w, char_h = window.getCharSize()
    return (
        max(
            2,
            (work[2] - work[0] - (rect[2] - rect[0] - client_w) - border_size * 2)
            // char_w,
        ),
        max(
            2,
            (work[3] - work[1] - (rect[3] - rect[1] - client_h) - border_size * 2)
            // char_h,
        ),
    )


## \~japanese
#  @param window 配置を修正するTextWindow。
#  @return None。現在のセル寸法を保ち、作業領域へ位置を補正します。UIスレッドで呼びます。
#
# \~english
#  @param window TextWindow to reposition.
#  @return None. Preserve current cell dimensions and adjust position into the work area. Call on the UI thread.
#
# \~
def fitWindowToWorkArea(window):
    work = getWindowWorkArea(window)
    rect = window.getWindowRect()
    x = max(work[0], min(rect[0], work[2] - (rect[2] - rect[0])))
    y = max(work[1], min(rect[1], work[3] - (rect[3] - rect[1])))
    window.setPosSize(
        x, y, window.width(), window.height(), ORIGIN_X_LEFT | ORIGIN_Y_TOP
    )


## \~japanese
# 文字列を改行コードの位置と、決まった幅の位置で分割する
#  @param window getStringWidthを提供するウィンドウ。
#  @param src 分割する文字列。
#  @param width 折返す表示セル幅。正整数を使います。
#  @param keepends Trueなら元の改行文字を保持。
#  @return 分割した文字列リスト。空入力は空リスト。幅より広い単一文字はその1文字を1行にします。
#
# \~english
# Split text at line endings and the specified display width
#  @param window Window exposing getStringWidth.
#  @param src Input text.
#  @param width Positive integer display-cell wrapping width.
#  @param keepends Keep original line endings when true.
#  @return List of strings; empty input produces an empty list. A single character wider than width occupies a line by itself.
#
# \~
def splitLines(window, src, width, keepends=False):
    lines = []
    for line in src.splitlines(keepends):
        while window.getStringWidth(line) > width:
            w = 0
            i = 0
            while True:
                char_width = window.getStringWidth(line[i])
                if w + char_width > width:
                    if i == 0:
                        i = 1
                    lines.append(line[:i])
                    line = line[i:]
                    break
                w += char_width
                i += 1
        lines.append(line)
    return lines


## \~japanese
# TAB文字をスペース文字に置き換える
#  @param window getStringWidthを提供するウィンドウ。
#  @param src 入力文字列。
#  @param tab_width タブ位置の間隔（正の表示セル数）。既定4。
#  @param offset 先頭の表示セル位置。既定0。
#  @return タブを次のタブ位置まで空白へ展開した文字列。改行単位の列リセットは行いません。
#
# \~english
# Expand tab characters to spaces
#  @param window Window exposing getStringWidth.
#  @param src Input text.
#  @param tab_width Positive tab-stop interval in display cells, default 4.
#  @param offset Starting display-cell position, default 0.
#  @return Text with tabs expanded to the next tab stop. Do not reset the column automatically at newlines.
#
# \~
def expandTab(window, src, tab_width=4, offset=0):
    dst = ""
    dst_len = offset
    pos = 0
    while 1:
        new_pos = src.find("\t", pos)
        if new_pos < 0:
            dst += src[pos:]
            break
        src_part = src[pos:new_pos]
        dst += src_part
        dst_len += window.getStringWidth(src_part)
        dst += " "
        dst_len += 1
        while dst_len % tab_width:
            dst += " "
            dst_len += 1
        pos = new_pos + 1
    return dst


# --------------------------------------------------------------------


## \~japanese
# 単語区切り位置を検索するためのクラス
#  WordBreak(char_types, type_bounds)で文字種の境界を定義します。char_typesはin演算を提供する文字列・UnicodeRange等の順序列です。
#  先に一致した文字種の番号を使い、未分類は-1です。type_boundsは左文字種から右文字種の許可番号列への辞書です。
#  呼出しはwordbreak(s, pos, step, use_type_bounds=True)。sは文字列、posは文字位置、stepは+1または-1です。
#  @return 移動先の文字位置。use_type_bounds=Falseでは文字種の変化ならすべて境界とします。
#  通常はwordbreak_Filename/wordbreak_TextFileを使います。
#
# \~english
# Locate word boundaries
#  Construct WordBreak(char_types, type_bounds). char_types is an ordered sequence of membership containers such as strings or UnicodeRange.
#  Use the first matching type index, or -1 when unclassified. type_bounds maps a left type to permitted right-type indices.
#  Call wordbreak(s, pos, step, use_type_bounds=True), with string s, character position pos, and step +1/-1.
#  @return Destination character position. False use_type_bounds treats any type change as a boundary.
#  Prefer the supplied wordbreak_Filename/wordbreak_TextFile for ordinary use.
#
# \~
class WordBreak:
    def __init__(self, char_types, type_bounds):
        self.char_types = char_types
        self.type_bounds = type_bounds

    def _charType(self, c):
        for i in range(len(self.char_types)):
            if c in self.char_types[i]:
                return i
        return -1

    def __call__(self, s, pos, step, use_type_bounds=True):
        if step > 0:
            pos += 1
            if pos >= len(s):
                return len(s)
        else:
            pos -= 1
            if pos <= 0:
                return 0

        left_char_type = self._charType(s[pos - 1])
        right_char_type = self._charType(s[pos])

        while True:
            if left_char_type != right_char_type and (
                not use_type_bounds
                or right_char_type in self.type_bounds[left_char_type]
            ):
                return pos

            if step > 0:
                pos += 1
                if pos >= len(s):
                    return len(s)
                left_char_type = right_char_type
                right_char_type = self._charType(s[pos])
            else:
                pos -= 1
                if pos <= 0:
                    return 0
                right_char_type = left_char_type
                left_char_type = self._charType(s[pos - 1])


## \~japanese
# Unicode の範囲を定義するためのクラス
#  UnicodeRange(start, end)は1文字文字列の両端を含む範囲です。例: "a" in UnicodeRange("a", "z")。
#  大小関係による判定で、Unicodeの正規化や大文字小文字の同一視は行いません。
#
# \~english
# Define a range of Unicode characters
#  UnicodeRange(start, end) includes both single-character string endpoints, for example "a" in UnicodeRange("a", "z").
#  Use ordering comparisons without Unicode normalization or case folding.
#
# \~
class UnicodeRange:
    def __init__(self, start, end):
        self.start = start
        self.end = end

    def __contains__(self, item):
        return self.start <= item <= self.end


## \~japanese
# テキストファイル用の単語区切り
# \~english
# Word boundaries for text files
# \~
wordbreak_TextFile = WordBreak(
    (
        "\"!@#$%^&*()+|~-=\\`[]{};:',./<>?",
        " \t",
    ),
    {
        -1: [0],
        0: [-1],
        1: [-1, 0],
    },
)

## \~japanese
# ファイル名用の単語区切り
# \~english
# Word boundaries for filenames
# \~
wordbreak_Filename = WordBreak(
    (
        "\"!@#$%^&*()+|~-=\\`[]{};:',./<>?",
        " \t",
    ),
    {
        -1: [],
        0: [-1, 1],
        1: [-1, 0],
    },
)

# --------------------------------------------------------------------


## \~japanese
# ファイルパスのディレクトリ区切り文字を ￥と / で切り替える
# 
#  @param use_slash     True:/を使用する False:￥を使用する
# 
#  normPath や joinPath で使用されるディレクトリ区切り文字を設定します。
# 
# \~english
# Choose backslash or slash as the path separator
# 
#  @param use_slash     True: use slash; False: use backslash
# 
#  Set the separator used by normPath and joinPath.
# 
# \~
def setPathSlash(use_slash):
    global _use_slash
    _use_slash = use_slash


## \~japanese
# ファイルパスのディレクトリ区切り文字を取得する
# 
#  @return True:/ False:￥
# 
#  normPath や joinPath で使用されるディレクトリ区切り文字を取得します。
# 
#  @sa setPathSlash
# 
# \~english
# Get the configured path separator
# 
#  @return True:/ False:backslash
# 
#  Get the separator used by normPath and joinPath.
# 
#  @sa setPathSlash
# 
# \~
def pathSlash():
    return _use_slash


## \~japanese
#  @param drive_case_upper Trueならドライブ文字を大文字、Falseなら小文字、Noneなら変換なし。
#  @return None。共有設定を変更し、以後のreplacePath/joinPath/normPathに適用します。
#
# \~english
#  @param drive_case_upper True for uppercase drive letters, False for lowercase, None to preserve case.
#  @return None. Change shared settings for subsequent replacePath/joinPath/normPath calls.
#
# \~
def setPathDriveUpper(drive_case_upper):
    global _drive_case_upper
    _drive_case_upper = drive_case_upper


## \~japanese
#  @return ドライブ文字の大小設定。True/False/Noneを区別します。
#
# \~english
#  @return Drive-letter case setting; distinguish True/False/None.
#
# \~
def pathDriveUpper():
    return _drive_case_upper


## \~japanese
# ファイルパスを連結する
# 
#  @param *args     連結される任意の個数のパス
#  @return          連結結果のパス
# 
#  ファイルパスの連結処理に加えて、ディレクトリ区切り文字の \\ と / の置き換え処理も行います。
# 
# \~english
# Join file paths
# 
#  @param *args     Any number of path components to join
#  @return          Joined path
# 
#  Join the paths and replace backslash / slash according to the separator setting.
# 
# \~
def joinPath(*args):
    path = os.path.join(*args)
    path = replacePath(path)
    return path


## \~japanese
# ファイルパスをディレクトリ名とファイル名に分離する
# 
#  @param path     分離されるパス
#  @return         ( ディレクトリ名, ファイル名 )
# 
#  動作は os.path.split と同じです。
# 
# \~english
# Split a path into directory and filename
# 
#  @param path     Path to split
#  @return         (directory, filename)
# 
#  Behaves like os.path.split.
# 
# \~
def splitPath(path):
    return os.path.split(path)


## \~japanese
# 拡張子の長さと文字コードの条件を満たすときだけ分離する
# 
#  @param path     分離されるパス
#  @param maxlen   拡張子とみなす最大の長さ (ピリオドを含む)
#  @return         分離時は (ファイル名本体, ピリオドを含む拡張子)、非分離時は (元のパス, None)
# 
#  この関数の動きは os.path.splitext() に似せてありますが、
#  os.path.splitext() とは違い、長い拡張子を分離しないことが出来ます。
#  拡張子の各文字がU+0100未満の場合に分離します。ASCII以外のU+0080〜U+00FFも対象です。
# 
# \~english
# Split an extension only when its length and character-code conditions are met
# 
#  @param path     Path to split
#  @param maxlen   Maximum extension length, including the dot
#  @return         (stem, extension_including_dot), or (original_path, None) if not split
# 
#  This function resembles os.path.splitext(),
#  but can leave long extensions unsplit.
#  Every extension character must be below U+0100. Non-ASCII characters U+0080 through U+00FF are included.
# 
# \~
def splitExt(path, maxlen=5):
    last_period_pos = path.rfind(".")
    if last_period_pos > 0 and last_period_pos >= len(path) - maxlen:
        for i in range(last_period_pos + 1, len(path)):
            if path[i] >= "\u0100":
                return path, None
        return path[:last_period_pos], path[last_period_pos:]
    return path, None


## \~japanese
# ファイルパスのルートディレクトリ部分を取得する
# 
#  @param path     元になるパス
#  @return         ルートディレクトリのパス
# 
# \~english
# Get the root-directory part of a path
# 
#  @param path     Input path
#  @return         Root-directory path
# 
# \~
def rootPath(path):
    while True:
        new_path, _name = os.path.split(path)
        if new_path == path:
            return path
        path = new_path


## \~japanese
# ファイルパスを標準化する
# 
#  @param path     元になるパス
#  @return         標準化されたのパス
# 
#  os.path.normpath() 相当の処理に加え、ディレクトリ区切り文字の \\ と / の置き換え処理を行います。
# 
# \~english
# Normalize a file path
# 
#  @param path     Input path
#  @return         Normalized path
# 
#  Apply os.path.normpath() and replace backslash / slash according to the separator setting.
# 
# \~
def normPath(path):
    path = os.path.normpath(path)
    path = replacePath(path)
    return path


## \~japanese
# ディレクトリ区切り文字とドライブ名の設定にしたがってパスを整形する
# 
#  @param path     元になるパス
#  @return         置換されたパス
# 
#  ディレクトリ区切り文字の \\ と / の置き換え処理を行います。
#  ドライブ名の大文字/小文字の変換処理を行います。
# 
# \~english
# Format a path using the separator and drive-letter case settings
# 
#  @param path     Input path
#  @return         Formatted path
# 
#  Replace backslash / slash according to the separator setting.
#  Apply the configured uppercase / lowercase conversion to drive letters.
# 
# \~
def replacePath(path):
    if _use_slash:
        path = path.replace("\\", "/")
    else:
        path = path.replace("/", "\\")

    # Keep None distinct from False, including numeric flag values.
    if _drive_case_upper == True:
        drive, tail = os.path.splitdrive(path)
        if drive.endswith(":"):
            drive = drive.upper()
            path = os.path.join(drive, tail)

    elif _drive_case_upper == False:
        drive, tail = os.path.splitdrive(path)
        if drive.endswith(":"):
            drive = drive.lower()
            path = os.path.join(drive, tail)

    return path


# --------------------------------------------------------------------


beep_enabled = True


## \~japanese
# 警告音を有効/無効にする
#  @param enable 警告音を有効にする真偽値。
#  @return None。共有フラグを変更し、音はまだ鳴らしません。
#
# \~english
# Enable or disable the alert sound
#  @param enable Whether to enable the alert sound.
#  @return None. Change a shared flag without playing a sound yet.
#
# \~
def enableBeep(enable):
    global beep_enabled
    beep_enabled = enable


## \~japanese
# 警告音を再生する
#  @return None。有効な場合だけWindowsのMessageBeepを呼びます。
#
# \~english
# Play the alert sound
#  @return None. Call Windows MessageBeep only when enabled.
#
# \~
def messageBeep():
    if beep_enabled:
        winsound.MessageBeep()


# --------------------------------------------------------------------


_temp_num = 1
_temp_dir = ""


## \~japanese
#  アプリ共用の一時領域を初期化する
#  @param prefix tempfile.mkdtempへ渡す接頭辞。
#  @return None。通常は本体が起動時に呼び、拡張はmakeTempFile/makeTempDirを使います。
#
# \~english
#  Initialize the application's shared temporary area
#  @param prefix Prefix passed to tempfile.mkdtemp.
#  @return None. Normally called by the application at startup; extensions use makeTempFile/makeTempDir.
#
# \~
def initTemp(prefix):
    global _temp_dir
    _temp_dir = tempfile.mkdtemp(prefix=prefix)


## \~japanese
#  アプリ共用の一時領域を再帰削除する
#  @return None。削除エラーは無視します。通常は本体が終了時に呼び、拡張が独自に呼ぶ操作ではありません。
#
# \~english
#  Recursively remove the application's shared temporary area
#  @return None. Ignore deletion errors. Normally called at application shutdown, not by individual extensions.
#
# \~
def destroyTemp():
    shutil.rmtree(_temp_dir, ignore_errors=True)


## \~japanese
# テンポラリディレクトリを作成する
#  @param prefix 作成名の接頭辞。
#  @return 作成済みディレクトリのパス文字列。既存のアプリ用一時領域配下で連番を使います。
#  通常は本体がinitTempを実行済みです。不要になった資源は呼出し元が片付けます。ファイル操作の例外は伝播します。
#
# \~english
# Create a temporary directory
#  @param prefix Name prefix.
#  @return Path string of a created directory, numbered under the initialized application temporary area.
#  Normally the application has called initTemp. The caller releases resources when no longer needed; filesystem errors propagate.
#
# \~
def makeTempDir(prefix):
    global _temp_num
    while 1:
        path = os.path.join(_temp_dir, prefix + f"{_temp_num:08x}")
        _temp_num += 1
        if not os.path.exists(path):
            break
    os.mkdir(path)
    return path


## \~japanese
# テンポラリファイルを作成する
#  @param prefix ファイル名の接頭辞。
#  @param suffix ファイル名の末尾（例: .txt）。
#  @return 作成・close済みの空ファイルのパス文字列。ファイルオブジェクトではありません。
#  通常は本体がinitTempを実行済みです。必要なモードで開き直し、終了後は呼出し元が片付けます。
#
# \~english
# Create a temporary file
#  @param prefix Filename prefix.
#  @param suffix Filename suffix, such as .txt.
#  @return Path string of a created and closed empty file, not a file object.
#  Normally initTemp has been called by the application. Reopen in the required mode and clean up when done.
#
# \~
def makeTempFile(prefix, suffix=""):
    global _temp_num
    while 1:
        path = os.path.join(_temp_dir, prefix + f"{_temp_num:08x}" + suffix)
        _temp_num += 1
        if not os.path.exists(path):
            break
    fd = open(path, "wb")  # noqa: SIM115  # Closed immediately on the next line with no intervening operation.
    fd.close()
    return path


# --------------------------------------------------------------------

## @} misc
