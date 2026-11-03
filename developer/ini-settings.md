# INI設定の定義と参照

## 定義の置き場所

静的な通常設定は[clnch_inisettings.py](../clnch/clnch_inisettings.py)の不変な`IniSetting(section, key, default, value_type)`で定義します。`value_type`は`str`または`int`です。定義はGUI・通常INIモジュールへ依存せず、呼出し元から既存INI APIを受け取ります。

- `setting.get(clnch_ini)`は型に応じて既存の`get`／`getint`を呼び、欠損・不正値のフォールバックと例外を維持します。
- `setting.get_text(clnch_ini)`は保存文字列を取得します。整数の既定値も文字列化し、Configの文字列による択一照合を維持します。
- `setting.set_text(clnch_ini, value)`は既存の`set`へ文字列を渡します。整数設定でも先頭の0等を勝手に正規化せず、旧処理と同じdirty判定にします。
- `write()`、`configure()`、フォント・ホットキー等の即時反映は従来の呼出し元に残します。定義の参照や読書きによって適用・ファイル保存を追加しません。

[入力](../clnch/clnch_inputconfig.py)・[修飾キー](../clnch/clnch_modifierconfig.py)・[Alt+Enter](../clnch/clnch_altenterconfig.py)は各モジュールの`DEFAULTS`を論理値と型の正本にし、`SETTINGS`をそこから生成します。INI文字列とbool・パス列の変換、値域・パス・URLの検証は各モジュールに保持します。ConfigのINPUT書込みも同じ`SETTINGS`を使います。

`reclnch_exe.ini`は[clnch_execonfig.py](../clnch/clnch_execonfig.py)の`MULTI_USER`を正本にします。通常INIと違いRawConfigParserの`fallback=`を使う読み取りと、独立した保存・起動時の保存先選択を維持します。

## 通常INIの読込み失敗と保存保護

`clnch_ini.read()`は通常INIをUTF-8で読みます。ファイル未作成だけは正常な初回起動として扱い、空の設定から初回保存できます。構文・文字コード・読取り権限・I/O・ロック等の失敗では、解析途中の設定を破棄して既定値で起動し、`read_failed`を保持します。`write()`はこの状態で一時ファイル作成・置換を行わず、設定変更や自動保存でdirtyになっても元INIを保ちます。起動時の既存コンソールに対象パス、保存停止、修復・再起動の案内を表示します。JSON登録の保存は独立です。

復旧はアプリを終了し、対象INIまたは読取り権限を手動修復して再起動します。通常のReloadはINIを再読込みしません。ファイルの修復だけでは実行中の保存抑止を解除せず、`read()`が成功した場合（未作成を含む）だけ解除します。抑止中の変更・履歴を修復済みINIへ自動でマージしません。通常の書込み失敗は別扱いで、従来どおり原本とdirtyを保持し、次の保存で再試行します。一時ファイル・fsync・原子的置換・パス単位のミューテックスは維持します。

通常GUIはパーサーの直列化と原子的置換で保存するため、手動編集や外部ツールによる構文破損とは発生条件が異なります。外部変更が構文上有効な空ファイル・途中までのINIであれば、この保護では欠落を検出できません。起動後の外部編集との競合、設定マージ、バックアップ世代管理、電源断等からの復旧は対象外です。

## 通常設定の一覧

`IniSetting[str]`／`IniSetting[int]`は取得型と既定値を結び付け、`get()`の戻り値をそれぞれstr／intに固定します。`value_type`は組込みのstr／intのみとし、既定値は同じ型の値かNoneに限ります。不一致・bool既定値・未対応の取得型は、フィールド保存やINI読取りより前にTypeErrorで拒否します。Noneは「既定値なし」であり、読取り失敗時の既存例外を維持してNoneは返しません。定義が正しい場合の欠損・整数変換失敗は、従来どおり同型の既定値へ戻ります。凍結dataclassの4フィールド・引数順・比較／ハッシュ・同型の置換と、取得・適用・保存の分担は維持します。`tools/test_ini_settings.py`で構築時拒否と現行44定義の動作を検査し、`TYPE_CHECKING`内の`assert_type`で取得型を確認します。

表の参照元／書込み元は`clnch/`内のモジュール名（`clnch_`と`.py`を省略）です。数値設定の不正値は従来の`getint`と同じく既定値へ戻り、文字列設定は生の値を返して利用側で判断します。`width`／`height`は保存専用で、読み込み既定値を新設しません。

| セクション | キー | 既定値 | 取得型 | 参照元 | 書込み元 |
|---|---|---|---|---|---|
| CONSOLE | `height` | `32` | int | `consolewindow` | `consolewindow` |
| CONSOLE | `width` | `80` | int | `consolewindow` | `consolewindow` |
| CONSOLE | `x` | `0` | int | `consolewindow` | `consolewindow` |
| CONSOLE | `y` | `0` | int | `consolewindow` | `consolewindow` |
| DEBUG | `detect_block` | `0` | int | `mainwindow` | なし |
| DEBUG | `print_errorinfo` | `0` | int | `mainwindow` | なし |
| FONT | `name` | `'MS Gothic'` | str | `configmenu`, `mainwindow`, `misc` | `configmenu` |
| FONT | `size` | `16` | int | `configmenu`, `fontlistwindow`, `mainwindow`, `misc` | `configmenu` |
| GEOMETRY | `height` | なし（保存専用） | int | なし | `mainwindow` |
| GEOMETRY | `max_width` | `80` | int | `cmdlist`, `configmenu`, `inputsession`, `mainwindow` | `configmenu` |
| GEOMETRY | `min_width` | `18` | int | `configmenu`, `inputsession`, `mainwindow` | `configmenu` |
| GEOMETRY | `monitor` | `0` | int | `mainwindow` | `configmenu` |
| GEOMETRY | `topmost` | `0` | int | `configmenu`, `mainwindow` | `configmenu` |
| GEOMETRY | `width` | なし（保存専用） | int | なし | `mainwindow` |
| GEOMETRY | `x` | `0` | int | `mainwindow` | `configmenu` |
| GEOMETRY | `y` | `0` | int | `mainwindow` | `configmenu` |
| HOTKEY | `activate_mod` | `0` | int | `configmenu`, `mainwindow` | `configmenu` |
| HOTKEY | `activate_vk` | `0` | int | `configmenu`, `mainwindow` | `configmenu` |
| MISC | `auto_complete` | `0` | int | `configmenu`, `mainwindow` | `configmenu` |
| MISC | `default_keymap` | `'106'` | str | `configmenu`, `mainwindow` | `configmenu` |
| MISC | `directory_separator` | `'backslash'` | str | `configmenu`, `mainwindow` | `configmenu` |
| MISC | `hotkey_behavior` | `'toggle'` | str | `configmenu`, `mainwindow` | `configmenu` |
| MISC | `inactive_behavior` | `'clock'` | str | `configmenu`, `consolewindow`, `mainwindow` | `configmenu` |
| MISC | `language` | `'en'` | str | `main`, `configmenu` | `configmenu` |
| MISC | `isearch_type` | `'partial'` | str | `isearch` | なし |
| THEME | `name` | `'gray'` | str | `configmenu`, `mainwindow` | `configmenu` |

MISC.languageはja／enを次回起動時に反映します。未設定・不正値は英語で起動し、保存済みの不正値は自動修正しません。Configは変更時にset_textと既存のclnch_ini.writeを呼び、適用中の言語を保持したまま再起動を案内します。

## 専用モジュールの設定

全項目を起動／Reload時に`MainWindow.configure`が専用モジュールの`read`経由で取得します。変更時はConfigがINPUTを個別に、MODIFIER・Alt+Enter系4セクションを専用モジュールの`write`経由で書き込みます。不正値は従来どおり検証エラーにします。

| セクション | キー | 論理値の既定値 | 論理型 | INIの既定文字列 |
|---|---|---|---|---|
| INPUT | `history_mode` | `'persistent'` | str | `'persistent'` |
| INPUT | `completion_mode` | `'standard'` | str | `'standard'` |
| INPUT | `clear_on_deactivate` | `True` | bool | `'1'` |
| INPUT | `space_action` | `'insert'` | str | `'insert'` |
| INPUT | `tab_action` | `'complete'` | str | `'complete'` |
| MODIFIER | `ctrl_action` | `'none'` | str | `'none'` |
| MODIFIER | `shift_action` | `'target_folder'` | str | `'target_folder'` |
| MODIFIER | `ctrl_shift_action` | `'none'` | str | `'none'` |
| MODIFIER | `source_roots` | `()` | tuple | `''` |
| MODIFIER | `ctrl_destination_root` | `''` | str | `''` |
| MODIFIER | `shift_destination_root` | `''` | str | `''` |
| MODIFIER | `ctrl_shift_destination_root` | `''` | str | `''` |
| ALT_ENTER | `action` | `'none'` | str | `'none'` |
| ALT_ENTER | `executable` | `''` | str | `''` |
| ALT_ENTER | `arguments` | `'%param%'` | str | `'%param%'` |
| ALT_ENTER | `url` | `''` | str | `''` |
| ALT_ENTER | `properties_first` | `True` | bool | `'1'` |

`CTRL_ALT_ENTER`・`SHIFT_ALT_ENTER`・`CTRL_SHIFT_ALT_ENTER`は各キー専用の独立セクションです。それぞれ`action='none'`・`executable=''`・`arguments='%param%'`・`url=''`（すべてstr）を既定値とし、`properties_first`は持ちません。追加3キーは`none/application/web`だけを許し、通常の`ALT_ENTER`だけが`properties`を許します。未定義欄はそのセクションの既定値を使い、他のキーへフォールバックしません。

`MODIFIER.source_roots`は順序を持つパス列です。空文字列を空tupleへ、非空文字列を改行分割・各行strip・空行除去してtupleへ変換します。保存は改行連結し、ConfigParserの継続行形式を維持します。修飾キー名から組み立てるaction／destination_rootは有限の既知キーで、動的INIキーとして除外せず同じ`SETTINGS`へ対応させます。

`DATA.multi_user`はINIでは文字列`'0'`／`'1'`、論理値はbool、既定はFalseです。`clnch_main`とConfigが`clnch_execonfig.read`を使い、初回とConfig確定時に`write`を使います。欠損ファイル／キーはFalse、不正値は従来のValueErrorです。保存先の実変更は次回起動時です。

Configは選択した設定だけを更新し、同値確定は書込みを省略し、取消では変更しません。Alt+Enter系4キーはINIの保存成功後だけ該当キーの実行時設定を更新し、保存失敗・読込失敗による保存抑止では変更前のINI状態と実行時設定を保持します。Modifierは専用モジュールで検証・INI変更を行い、実行時設定を更新してからINIを書き込みます。保存失敗時は変更済みの設定とdirtyを保持し、後続の保存で再試行します。変更にJSON・custom.py・キーマップの全体再構築は不要です。
実行中の通常設定は`window.altenter_settings`、追加3キーは`window.altenter_modified_settings[key]`で保持します。Reloadは従来どおりメモリ上のINIから全4キーを検証し、不正値があれば置換前に中止します。ディスクINIの再読込や移行処理は追加しません。

## テーマ資材

`themes/*.ini`の`COLOR`は[ckit_theme.py](../ckit/ckit_theme.py)が所有します。`COLOR_SECTION`・`DEFAULT_COLORS`・`COLOR_FALLBACKS`が正本です。全値はINIではRGBタプル形式の文字列、`getColor`の正常な戻り値は整数3要素のtupleです。

| キー | ckitの欠損時の値 |
|---|---|
| `bg` | `(0,0,0)` |
| `fg` | `(255,255,255)` |
| `caret0` | `(255,255,255)` |
| `caret1` | `(255,0,0)` |
| `bar_fg` | `(255,255,255)` |
| `bar_error_fg` | `(255,130,130)` |
| `select_bg` | `(130,130,130)` |
| `select_fg` | `(255,255,255)` |
| `choice_bg` | 読込後の`select_bg` |
| `choice_fg` | 読込後の`select_fg` |

`setTheme`は呼出し側のdefault_color→テーマファイル→欠損値の補完の順で組み立て、ディスクへ保存しません。`getColor`をckit各GUIと本体が参照します。テーマファイル固有の配色は利用者が選ぶ資材であり、ckitの最終フォールバックとは異なります。任意の色名・セクションを扱う公開APIは維持します。色名を指定するGUI描画側はINIアクセスではないため定義方式を強制しません。

## 意図的な例外と現行API

- `COMMANDLINE.history_{i}`は動的な履歴列です。セクション名だけを共有し、最大1000件の読込み・欠損での終端・古い末尾の削除・persistent時だけの保存を維持します。
- フォント選択の初期選択だけは`FONT_NAME.get_text(clnch_ini, default="")`を使います。実フォントとメニューの現在値の既定`MS Gothic`へ統一しません。
- `GEOMETRY.topmost`と`MISC.auto_complete`は実行時には整数、Configでは生の文字列として取得します。例えば不正な`auto_complete`は実行時に整数0へ戻り、Configでは元文字列を維持します。メイン入力の候補生成はINI初期値ではなく入力中のEditWidgetの自動補完状態を参照し、OFFを`INPUT.completion_mode`より優先します。
- `clnch_altenterconfig.read/write`は省略時に`ALT_ENTER`の5項目、keyが`ctrl/shift/ctrl_shift`なら対応セクションの4項目を扱います。`DEFAULTS/SETTINGS`は通常キー、`MODIFIED_DEFAULTS/MODIFIED_SETTINGS`は追加キーの定義です。呼出し元は読込済み設定の既知項目だけを更新し、未定義キー向けの互換分岐は設けません。
- `clnch_ipc.IpcData`の`EXECUTE.itemN`・`COMMANDLINE.text/selection/position`は一時的なIPC通信形式です。同名の通常INIセクションとは寿命・意味が異なるため対象外です。
- `clnch_ini`自身は任意の利用者設定を扱う汎用公開APIなので、定義への依存を追加しません。外部拡張の`get/getint/set/setint/remove_*`は現行APIとして利用できます。テスト内のリテラルは現行仕様の名前・型・既定値を確認する独立した期待値です。旧形式の読替え・移行処理は持ちません。

自動検証の選択は[検証手順](release-verification.md)を参照してください。
