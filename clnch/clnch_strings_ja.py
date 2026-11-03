"""Japanese UI wording. Keep constant names and named {placeholders}."""

# Common buttons and access-key presentation
SETTING_VALUE = "{title}: {value}"
SETTING_CELLS = "{count}セル"
BUTTON_ADD = "追加"
BUTTON_SAVE_BACK = "保存して戻る"
BUTTON_CANCEL = "キャンセル"
ACCESS_LABEL = "{label}({key})"
BUTTON_OK = " OK "
BUTTON_YES = "はい"
BUTTON_NO = "いいえ"


# Configuration menus and storage
CONFIG_RELOADED = "設定スクリプトをリロードしました.\n"
HISTORY_RESET_NOTICE = " (設定変更後、保存済み履歴を削除)"
CONFIG_THEME = "テーマ"
CONFIG_FONT = "フォント"
CONFIG_FONT_SIZE = "フォントサイズ"
CONFIG_MIN_SIZE = "最小のウインドウサイズ"
CONFIG_MAX_SIZE = "最大のウインドウサイズ"
POSITION_CONFIRM_TITLE = "表示位置の保存の確認"
POSITION_CONFIRM = "現在の表示位置を保存しますか？"
POSITION_SAVED_TITLE = "表示位置の保存完了"
POSITION_SAVED = "現在の表示位置を保存しました。"
TOPMOST_NORMAL = "通常"
TOPMOST_ON = "最前面"
TOPMOST_ALWAYS = "最前面のなかの最前面"
CONFIG_TOPMOST_TITLE = "ウインドウの最前面表示"
SEPARATOR_SLASH = "スラッシュ       : / "
SEPARATOR_BACKSLASH = "バックスラッシュ : \\ "
CONFIG_SEPARATOR = "ファイルパス区切り文字"
SEPARATOR_SLASH_NAME = "スラッシュ"
SEPARATOR_BACKSLASH_NAME = "バックスラッシュ"
KEYMAP_101 = "英語(101)"
KEYMAP_106 = "日本語(106/109)"
CONFIG_KEYMAP = "キー配列"
AUTO_COMPLETE_OFF = "自動補完しない"
AUTO_COMPLETE_ON = "自動補完する"
CONFIG_AUTO_COMPLETE = "自動補完"
CONFIG_HOTKEY = "ホットキー"
HOTKEY_GUIDE = "割り当てるキーを押してください。\n(Deleteで解除します)"
HOTKEY_ACTIVATE = "アクティブ化"
HOTKEY_TOGGLE = "トグル"
CONFIG_HOTKEY_BEHAVIOR = "ホットキーの動作"
HOTKEY_UNASSIGNED = "未設定"
HOTKEY_MODIFIER_ONLY = '修飾キーのみではホットキーを割り当てできません。'
HOTKEY_REGISTER_ERROR = "ホットキーを適用できませんでした。\nホットキーの割り当ては変更していません。"
HOTKEY_RESTORE_ERROR = "以前のホットキーも復元できませんでした。\nConfigでホットキーを再設定してください。"
CONFIG_FONT_NAME = "フォント名: {name}"
CONFIG_MIN_WIDTH = "最小の横幅"
CONFIG_MAX_WIDTH = "最大の横幅"
CONFIG_POSITION = "現在の表示位置を保存"
CONFIG_TOPMOST = "最前面に表示"
CONFIG_APPEARANCE = "表示オプション"
CONFIG_INPUT = "入力オプション"
CONFIG_MODIFIERS = "修飾キーの既定動作"
CONFIG_HOTKEY_ASSIGN = "ホットキー割り当て"
CONFIG_HOTKEY_OPTIONS = "ホットキー設定"
INACTIVE_EMPTY = "空欄"
INACTIVE_CLOCK = "時計"
INACTIVE_HIDE = "非表示"
CONFIG_INACTIVE = "非アクティブ時の表示"
DATA_APP_FOLDER = "アプリフォルダ"
DATA_USER_FOLDER = "AppDataフォルダ"
CONFIG_LANGUAGE = '言語'
LANGUAGE_JAPANESE = 'Japanese'
LANGUAGE_ENGLISH = 'English'
LANGUAGE_RESTART = '表示言語を反映するにはReCraftLaunchを再起動してください。'
LANGUAGE_PENDING = '{current}（次回起動後: {next}）'
CONFIG_DATA = "設定の保存先"
DATA_ERROR = "保存先の設定エラー"
DATA_RESTART = "設定の保存先の変更を反映するにはReCraftLaunchを再起動してください。"
DATA_PENDING = "{current}（次回起動後: {next}）"
DATA_UNREADABLE = "読込エラー"
CONFIG_RELOAD = "設定をリロード"
CONFIG_TITLE = "設定メニュー"
DATA_VALUE_ERROR = "reclnch_exe.ini: DATA.multi_user must be 0 or 1"
CONFIG_CALLABLE_ERROR = "custom.configure must be callable"
CONFIG_LIST_CALLABLE_ERROR = "custom.configure_ListWindow must be callable"


# Input options
INPUT_HISTORY = "履歴"
INPUT_HISTORY_OFF = "保持しない"
INPUT_HISTORY_SESSION = "起動中のみ保持"
INPUT_HISTORY_PERSISTENT = "保持して保存"
HISTORY_LOAD_ERROR = "履歴の読み込みに失敗しました。履歴と履歴設定は変更していません。"
INPUT_COMPLETION = "補完候補"
INPUT_COMPLETION_OFF = "候補なし"
INPUT_COMPLETION_COMMANDS = "登録名"
INPUT_COMPLETION_STANDARD = "登録名・ファイル名・共有"
INPUT_CLEAR = "非アクティブ時の入力クリア"
INPUT_KEEP = "保持する"
INPUT_CLEAR_ON = "クリアする"
INPUT_SPACE = "Spaceの動作"
INPUT_SPACE_INSERT = "空白入力"
INPUT_SPACE_COMPLETE = "補完候補の操作"
INPUT_TAB = "Tabの動作"
INPUT_TAB_CLEAR = "入力クリア"
INPUT_TAB_COMPLETE = "共通部分を補完"
INPUT_VALUE_ERROR = "INPUT.{name}: expected one of {choices}"


# Command editor and command list
EDITOR_TITLE = "Edit Command - {name}"
COMMAND_FORMAT_ERROR = "{name}: 新形式のコマンド指定が必要です"
EDITOR_ACTION_UNKNOWN = "{name}: 未知の起動指定があります"
EDITOR_ACTION_VALUE = "{name}: 起動指定の各値は文字列が必要です"
EDITOR_VIEW_ERROR = "{name}: 無効な表示モードです"
COMMAND_NAME_DUPLICATE = "コマンド名が重複しています: {first!r} / {second!r}"
COMMAND_LOAD_BLOCKED = "読込失敗のため保存できません:\n{error}"
COMMAND_SAVE_ERROR = "commands.json の書き込みに失敗しました:\n{error}"
COMMAND_APPLY_ERROR = "commands.json は保存されましたが、コマンドの反映に失敗しました:\n{error}\nReload で再反映してください。"
FIELD_NAME = "Name"
FIELD_LINK = "Link"
FIELD_ARG = "Args"
FIELD_WORKDIR = "WorkDir"
EDITOR_EMPTY_TITLE = "Edit Command - (Empty)"
EDITOR_NEW_TITLE = "New Command"
VIEW_NORMAL = "通常"
VIEW_MINIMIZED = "最小化"
VIEW_MAXIMIZED = "最大化"
ERROR_LOAD_TITLE = "読込エラー"
ERROR_INPUT_TITLE = "入力エラー"
ERROR_SAVE_TITLE = "保存エラー"
ERROR_DROP_TITLE = "ドロップエラー"
COMMAND_DUPLICATE = "同じNameのコマンドが既に登録されています。"
COMMAND_NAME_ERROR = "{name}: コマンド名に空白文字（スペース・タブ・改行・全角空白など）やセミコロン (;) は使用できません。"
COMMAND_ALIAS_CYCLE = "コマンドの循環参照を検出しました: {path}"
COMMAND_RELATIVE_LINK = "Linkに相対パスは指定できません。\n  コマンド: {name}\n  Link: {link}\n  絶対パス、実行ファイル名、登録コマンド名、URLを指定してください。"
COMMAND_RELATIVE_LINK_GUI = "Linkに相対パスは指定できません。\n絶対パス、実行ファイル名、登録コマンド名、URLを指定してください。"
COMMAND_LINK_REQUIRED = "空欄コマンドには少なくとも1つのLinkが必要です。"
EDITOR_GUIDE = "Enter: OK   Esc: Cancel   Alt+key: Select/Focus"
FIELD_VIEW_MODE = "ViewMode"
FIELD_MODIFIER = "Modifier"
COMMAND_DELETE_CONFIRM = "コマンド '{name}' を削除しますか？"
COMMAND_LOAD_ERROR = "commands.json の読込に失敗しました:\n{error}"
COMMAND_EMPTY = "(空欄コマンド)"
COMMAND_EMPTY_DELETE = "空欄コマンドは削除出来ません。"
COMMAND_LIST_TITLE = "Command List"
COMMAND_DELETE_TITLE = "Command List - 削除確認"
ERROR_TITLE = "エラー"
COMMAND_OBJECT_ERROR = "commands.json: コマンド名をキーとするオブジェクトが必要です"
COMMAND_FILE_MISSING = "commands.json が見つかりません。"


# Modifier settings and folder explanations
MODIFIER_ACTION = "動作: {action}"
SOURCE_COUNT = "{count}件"
SOURCE_SUMMARY = "置換元フォルダ一覧: {count}（共通設定）"
DESTINATION_SUMMARY = "置換先フォルダ: {path}"
MODIFIER_DEFAULT_TITLE = "{modifier}の既定動作"
MODIFIER_ACTION_TITLE = "{modifier}の動作"
MODIFIER_DESTINATION_TITLE = "{modifier}の置換先フォルダ"
FOLDER_LABEL = "フォルダ"
FOLDER_GUIDE = "絶対パスを指定してください。"
FOLDER_TITLE = "フォルダの設定"
SOURCE_GUIDE = "Ins: 追加 / Enter: 編集 / Del: 削除 / Ctrl+↑↓: 順序"
SOURCE_LIST_TITLE = "置換元フォルダ一覧（共通設定・先頭優先）"
SOURCE_TITLE = "置換元フォルダ"
SOURCE_EXPLANATION = "この一覧は基点置換を使う全修飾キーで共有します。"
SOURCE_EXAMPLE = "例: C:\\Programs\\Tool\\bin\\tool.exe"
SOURCE_MAPPING_EXAMPLE = "置換元 C:\\Programs → 置換先 D:\\Archives"
SOURCE_RESULT_EXAMPLE = "開く先 D:\\Archives\\Tool\\bin"
MODIFIER_GUIDE = "個別の修飾操作が未登録の場合に適用"
SOURCE_EMPTY = "未登録"
DESTINATION_EMPTY = "未設定"
SOURCE_MISSING = "置換元が未登録のため実行されません。"
DESTINATION_MISSING = "置換先が未設定のため実行されません。"
DESTINATION_EXPLANATION = "空欄にすると未設定になります。"
ACTION_FORMAT_ERROR = "{name}: 新形式の起動指定が必要です"
MODIFIER_LINK_REQUIRED = "{modifier}: Link が必要です。"
MODIFIER_DEFAULT_HINT = "未登録時: {description}"
MODIFIER_NONE_HINT = "修飾キーなしEnter時の動作"
MAPPING_MISSING_BOTH = "基点置換（置換元・置換先が未設定）"
MAPPING_MISSING_SOURCE = "基点置換（置換元が未登録）"
MAPPING_MISSING_DESTINATION = "基点置換（置換先が未設定）"
MODIFIER_NONE = "None"
MODIFIER_CTRL = "Ctrl"
MODIFIER_SHIFT = "Shift"
MODIFIER_CTRL_SHIFT = "Ctrl+Shift"
ACTION_UNKNOWN = "{location}: 未知の項目があります"
ACTION_VALUE_ERROR = "{location}.{field}: 文字列が必要です"
ACTION_VIEW_ERROR = "{location}.view_mode: 無効な表示モードです"
MODIFIER_ACTION_ERROR = "MODIFIER.{modifier}_action: 無効な動作です。"
ACTION_NONE = "何もしない"
ACTION_EXECUTE = "Enterと同じ動作で実行"
ACTION_FOLDER = "所在フォルダを開く"
ACTION_MAPPED = "基点を置換してフォルダを開く"
FOLDER_ABSOLUTE_ERROR = "フォルダには絶対パスを指定してください。"


# Startup, console, IPC and diagnostics
IPC_EXISTING = "another {app} instance already exists."
IPC_SENDING = "sending Ipc data."
IPC_DONE = "done."
CONNECT_ERROR = "ERROR : 接続失敗 : {resource}"
STATE_SAVE_ERROR = "Save State Failed"
INI_READ_ERROR = "ERROR : 設定を読み込めませんでした: {path}\n既定値で起動します。設定と履歴は保存されません。\nReCraftLaunchを終了し、ファイルまたは読取り権限を修復してから再起動してください。"
EXECUTE_ERROR = "Error : 実行に失敗"
RUNAS_ASSOCIATION_ERROR = "この関連付けは管理者権限で起動できません ({reason}): {path}"
HISTORY_TITLE = "履歴リスト"
COMPLETION_ENABLED = "自動補完 ON\n"
COMPLETION_DISABLED = "自動補完 OFF\n"
IPC_POSITION_ERROR = 'ERROR : invalid position description "{position}".'
IPC_SELECTION_ERROR = 'ERROR : unknown selection description "{selection}".'
EXIT_THREAD_ID = "ThreadID: {thread_id}\n"
EXIT_FRAME = '  File: "{filename}", line {line}, in {name}\n'
EXIT_THREADS = "Remaining threads:\n"
BLOCK_DETECTED = "Block detected:"
DEBUG_PREFIX = "Debug: "
CLOCK_FORMAT = "%m/%d(%a) %H:%M"
CONSOLE_STATUS_REMAINING = " 表示: {first}–{last} / 全{total}行｜最新まで{count}行"
HELP_OPENED = "Helpを開きました"
HELP_MISSING = (
    "ヘルプファイルが存在しないため起動できません。\n"
    "配布ZIPに含まれるdocsフォルダーを、関連ファイル一式とともに"
    "アプリのフォルダーへ復元してください。\n"
    "公開先: https://github.com/p65536/ReCraftLaunch/releases\n"
    "必要なファイル: {path}\n"
    "ヘルプ本文は日本語です。"
)
HELP_OPEN_ERROR = "ヘルプを起動できませんでした。\nファイル: {path}\n理由: {error}"
HELP_NOT_FILE = "ヘルプ起動先が通常のファイルではありません: {path}"
CONSOLE_STATUS_LATEST = " 表示: {first}–{last} / 全{total}行｜最新のログ"
CONSOLE_GUIDE = " Ctrl+A: 全選択 / Ctrl+C: コピー / 3クリック: 全選択・コピー"
LIST_SEARCH = " Search : {query}_"
MESSAGE_SCROLL = "続きあり {first}-{last}/{total}  ↑↓ PgUp/PgDn Home/End"
STARTUP = (
    "{app} version {version}:\n"
    "  リポジトリ: {project_url}\n"
    "  配布先: {releases_url}\n"
    "\n"
    "移植元: {origin}\n"
    "  作者: {author}\n"
    "  リポジトリ: {source_url}\n"
    "  サイト: {url}\n"
)


# Shared ckit components (supplied by clnch_text.initialize)
CKIT_READONLY = "編集禁止です."
CKIT_SEARCH_FOUND = "[{query}]が見つかりました."
CKIT_SEARCH_NOT_FOUND = "[{query}]が見つかりません."
CKIT_MODIFIED_LINE_NOT_FOUND = "変更行が見つかりません."
CKIT_BOOKMARK_NOT_FOUND = "ブックマークが見つかりません."
CKIT_MODIFIED_OR_BOOKMARK_NOT_FOUND = "変更行またはブックマークが見つかりません."
CKIT_CONFIG_LOAD_ERROR = "ERROR : 設定ファイルの読み込み中にエラーが発生しました."
CKIT_CONFIG_EXEC_ERROR = "ERROR : 設定ファイルの実行中にエラーが発生しました."
CKIT_INVALID_KEY = "ERROR : Key expression is not valid :"
CKIT_COLOR_NOT_FOUND = "color not found :"
CKIT_JOB_SUSPENDED = "Suspended …\n"
CKIT_JOB_RESUMED = "… Resumed"


# Alt+Enter forwarding
CONFIG_ALT_ENTER = 'Alt+Enterの動作'
ALT_ENTER_NONE = '無効'
ALT_ENTER_APPLICATION = '外部アプリへ渡す'
ALT_ENTER_WEB = 'Web検索へ渡す'
ALT_ENTER_PROPERTIES = 'プロパティを表示'
ALT_ENTER_ACTION = '動作'
ALT_ENTER_TARGET = '外部アプリの設定'
ALT_ENTER_EXECUTABLE = '実行ファイル'
ALT_ENTER_ARGUMENTS = '引数'
ALT_ENTER_URL = 'URLテンプレート'
ALT_ENTER_PRIORITY = '実在するパスならプロパティを優先'
ALT_ENTER_ON = '有効'
ALT_ENTER_APP_GUIDE = '実行ファイルと引数を分けて指定します。\n%param%は入力全体です。引用符で囲まず指定してください。'
ALT_ENTER_WEB_GUIDE = '任意の検索URLを指定します。例： https://www.google.com/search?q=%param%\n%param% は入力全体をURLエンコードした文字列に置き換わります。'
ALT_ENTER_ACTION_ERROR = 'ALT_ENTER.action: 無効な動作です。'
ALT_ENTER_BOOL_ERROR = 'ALT_ENTER.properties_first: 0または1を指定してください。'
ALT_ENTER_TEXT_ERROR = '改行やNUL文字は使用できません。'
ALT_ENTER_URL_ERROR = '%param%を含むhttpまたはhttpsのURLを指定してください。'
ALT_ENTER_APP_ERROR = 'Alt+Enterの実行ファイルを設定してください。'
ALT_ENTER_PATH_ERROR = 'ファイルまたはフォルダが見つかりません: {path}'
ALT_ENTER_FAILED = 'Alt+Enterの実行に失敗しました: {error}'


# Config input controls
CONFIG_EDIT_GUIDE = "Enter: 決定 / Esc: キャンセル"
CONFIG_EDIT_FIELDS_GUIDE = "Tab / Shift+Tab: 項目移動 / Enter: 決定 / Esc: キャンセル"
