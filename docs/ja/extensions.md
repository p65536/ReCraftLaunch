# Python拡張の実装ガイド

Pythonの基本を理解した利用者向けに、製品ソースを読まずに独自機能を作る手順を説明します。各例は独立しています。既存のconfigureを重複定義せず、必要な呼出しをその中へ追加してください。

## コードを書く場所

標準設定はconfig、アプリ・URL登録はcommands.json、独自処理はcustom.pyを使います。再利用する処理や長い処理は、選択中の設定保存先のscripts/へPythonモジュールとして置き、custom.pyからimportと関数呼出しで適用します。

| ファイル | 配置と役割 |
|---|---|
| custom.py | 設定保存先直下。必要に応じてconfigure(window)・configure_ListWindow(window)を定義 |
| scripts/my_echo.py | 同じ設定保存先の配下。自作機能を実装するモジュール |
| extensions/ | アプリ直下の共用・公式モジュール。個人用モジュールと同名にしない |

アプリ内保存ならsettings/custom.pyとsettings/scripts/my_echo.py、AppData保存なら%APPDATA%/ReCraftLaunch/custom.pyと%APPDATA%/ReCraftLaunch/scripts/my_echo.pyです。configの「設定の保存先」を確認し、使用していない側を編集しないでください。

custom.pyがなければ、同梱のsettings/_custom.pyを選択中の保存先へコピーします。既存ファイルは上書きせず、フックはどちらも未定義で構いません。定義する場合はウィンドウを1つ受け取る呼出し可能オブジェクトとし、Noneや数値を代入しないでください。呼出し可能かの検証は旧資源の終了前に行います。各フックは1つにまとめ、適用したい順に関数を呼びます。scripts/の通常のモジュールは自由な関数名を使えます。このガイドではconfigure(window)という名前に揃えます。

configureには、起動・reload時、標準キーと標準・JSONコマンドの設定後に既存のMainWindowが渡されます。configure_ListWindowには、各ListWindowの標準キー設定後にその一覧オブジェクトが渡されます。別のMainWindowを作る必要はありません。アプリのAPIはclnch、共通部品・定数はckit、外部ウィンドウ・入力の自動操作はpyautoからimportします。

## custom.pyに直接コマンドを書く

custom.pyへ次を記述します。既存のconfigureがあれば、その中へ追加してください。

<!-- example: echo_inline -->
```python
def configure(window):
    def command_Echo(info):
        if not info.args:
            print("Usage: myecho;text [more text]")
            return
        print(" | ".join(info.args))
    window.launcher.command_list.append(("myecho", command_Echo))
```

保存してreload（configの「設定をリロード」）を実行します。Ctrl+F10でコンソールを開き、myecho;hello worldを実行するとhello | worldと表示します。myechoだけなら使用方法を表示します。myecho;hello "" worldには空の引数が入り、hello |  | worldと表示します。

登録する関数はCommandInfoを1つ受け取ります。登録時にcommand_Echoを呼び出さず、関数そのものを渡してください。名前入力は最初のセミコロンだけで分けます。CommandInfo.argsは名前以降をWindows規則で解析したリスト、arg_stringは引用符・空白・後続セミコロンを保持する原文です。例えばmyecho;"a b" "" one;twoのargsは["a b", "", "one;two"]です。ShellExecuteCommandはarg_stringがNoneでなければその文字列を使い、argsから再結合しません。Pythonでargsを変更して起動する場合はarg_string=Noneにします。Pythonから直接作るCommandInfoは既定でarg_string=Noneで、argsを従来どおりjoinArgsで引用します。

## scripts/へ分離してキーを割り当てる

scripts/my_echo.pyを次の全文で作成します。

<!-- example: echo_module -->
```python
def configure(window):
    def command_Echo(info):
        if not info.args:
            print("Usage: myecho;text [more text]")
            return
        print(" | ".join(info.args))

    def command_KeyEcho(info):
        print("Input: " + " | ".join(info.args))

    window.launcher.command_list.append(("myecho", command_Echo))
    window.keymap["C-F9"] = command_KeyEcho
```

custom.pyへ次の呼出しを追加します。

<!-- example: echo_setup -->
```python
def configure(window):
    import my_echo
    my_echo.configure(window)
```

my_echo.pyの作成・変更後はreloadします。myecho;hello worldは先ほどと同様に動きます。入力欄へdraft;oneと入力してCtrl+F9を押すと、コンソールへInput: draft;oneと表示し、入力を継続できます。

名前からの実行とキーからの実行は受取値が異なるため、例では別の関数にしています。

| 呼出経路 | CommandInfo.args | CommandInfo.mod |
|---|---|---|
| myecho;a bを入力してEnter | ["a", "b"] | Enter受付時の修飾キー |
| 入力欄がmyecho;a bの状態でメイン入力のキー割当を実行 | ["myecho;a b"] | 割当キーの修飾に関係なく0 |
| ListWindowのキー割当 | [] | 0 |

一覧キーのarg_stringはNoneです。ファイル関連付けのargsは先頭にファイルパスを含み、arg_stringは引用したファイルパスと原文の引数を含みます。独自commandline_listプロトコルが自分で生成するCommandInfoや入力構文の契約は変更しません。

名前から実行したときの修飾キー判定にはckit.MODKEY_CTRL等とのビット演算を使います。関数のPython戻り値は一般的な成功フラグではありません。CommandSequenceは初期値Trueのinfo.resultで判定し、後続を試す場合はFalseを代入します。入力から実行するコマンドが文字列を返すと、残っている入力欄へ反映される場合がありますが、最上位の入力終了後に新しい欄を開く動作にはなりません。例のように明示的な処理を行うと分かりやすくなります。

window.keymapは、入力を自動終了したり履歴へ追加したりせずメイン入力のキーを処理します。先に調べるwindow.cmd_keymapは、通常は入力終了と履歴追加を伴います。標準のAlt+Enterは無効時には入力・選択・フォーカスを保持し、有効時には入力を終了します。標準のF12は結果によらず入力を終了します。どちらも履歴へ追加しません。F12操作後はメインを非アクティブにします。外部起動時のフォーカス移動は起動先の通常の動作に委ねます。どちらのキーマップも入力全体を1要素のargsとarg_stringへ渡し、セミコロンや引用符を解析しません。既存コマンドを割り当てる場合はwindow.command.ConsoleToggleのように括弧を付けず渡します。キー表記はC-/Ctrl-、S-/Shift-、A-/Alt-、W-/Win-を組み合わせ、例えばC-S-F9と書けます。大文字小文字は区別しません。同じキーへの代入は既存割当を置き換えます。del window.keymap["C-F9"]は割当を削除しますが、以前の関数を復元する操作ではありません。

### コマンド名とJSONの関係

JSONの登録名には、引数区切りのセミコロン（`;`）や、前後・中間の空白文字（スペース・タブ・改行・全角空白など、`str.isspace()`が真となる文字）を使用できません。空文字列の名前は有効です。JSONの空登録（例: `{"about": {}}`）は同名の組込コマンドより優先され、名前入力・別名参照では何も実行しません。JSONの形式とGUI保存時の空欄コマンド検証は<a href="command_json.html">commands.jsonの形式</a>を参照してください。

名前は大文字小文字を区別せず、window.launcher.command_listの先頭から最初の一致を使います。重複しない小文字名を使ってください。末尾へ追加した自作項目は、同名の標準・JSON項目を上書きしません。Pythonで追加したコマンドはJSONのコマンド一覧・編集画面には表示しません。JSONの別名やF12のパス解決は、この公開リストへ追加した独自ハンドラを解決しません。GUIでJSONを保存・複製・削除しても、既存の管理項目だけをその位置で更新・削除し、独自項目の相対的な登録位置と順序を保持します。insert(0, ...)で先頭へ登録した独自コマンドの優先順位も維持します。新規名は最後の管理項目の位置（その項目を削除する場合も含む）の直後、末尾の独自項目より前へ追加します。現在の一覧に管理項目がなければ、独自項目の後ろへ追加します。設定全体のReloadでは標準・JSON登録を作り直し、custom.configure()の登録結果を新しい基準にします。

### 一覧ウィンドウのキーを変更する

custom.pyへ別のフックとして追加します。

<!-- example: list_setup -->
```python
def configure_ListWindow(window):
    window.keymap["C-P"] = window.command.CursorUp
    window.keymap["C-N"] = window.command.CursorDown
```

reload後にHistory等の一覧を開くと、Ctrl+P／Ctrl+Nで上下移動します。JSONコマンド一覧だけでなく、popMenuで作るメニュー等のListWindow系一覧にも適用します。メインウィンドウと一覧のキーマップは別のオブジェクトです。

## 文字入力と補完を使う

scripts/my_input.pyを作成します。

<!-- example: input_module -->
```python
def configure(window):
    def command_Ask(info):
        def candidates(update_info):
            left = update_info.text[:update_info.selectionLeft()]
            return [s for s in ("apple", "apricot", "banana") if s.startswith(left)], 0

        text = window.commandLine(
            "Fruit", candidate_handler=candidates, auto_complete=False
        )
        if text is None:
            print("Canceled")
            return
        print("Fruit: " + text)

    window.launcher.command_list.append(("myask", command_Ask))
```

custom.pyへ次の呼出しを追加してreloadします。

<!-- example: input_setup -->
```python
def configure(window):
    import my_input
    my_input.configure(window)
```

myaskを実行し、apと入力してTabを押すと共通部分を補完できます。補完操作でappleまたはapricotを選びEnterを押すと、コンソールへFruit:に続けて確定文字列を表示します。取消は、Escで入力を消し、コンソールが表示中ならEscで閉じ、空入力でEscを押します。Canceledと表示します。

commandLineはEnterで取得した文字列、取得前に入力終了した場合はNoneを返します。この例は既定のEnter処理を使い、空文字列も正常な確定値です。取消と空文字列をif not textでまとめないでください。Escは非空入力の消去やコンソール非表示を先に行い、常に取消になるわけではありません。

補完関数はtextとselectionを持つupdate_infoを受け取ります。selectionLeft()は選択範囲の左端です。(候補文字列のリスト, 置換開始位置)を返し、この例は先頭の0から置換します。位置はピクセルでなくPython文字列のインデックスです。ハンドラは入力中のUIスレッドで呼ばれるため短い処理にし、入力操作用オブジェクトを入力終了後まで保持しないでください。更新・キー・Enter・Esc・状態表示ハンドラはMainWindow.commandLineのAPI説明を参照してください。

## メニューと取消を扱う

scripts/my_menu.pyを作成します。

<!-- example: menu_module -->
```python
from clnch import popMenu

def configure(window):
    def command_Pick(info):
        items = [("Documents", "docs"), ("Downloads", "downloads")]
        index = popMenu(window, 40, 12, title="Choose", items=items)
        if index < 0:
            print("Canceled")
            return
        print("Choice: " + items[index][1])

    window.launcher.command_list.append(("mypick", command_Pick))
```

custom.pyへ次の呼出しを追加してreloadします。

<!-- example: menu_setup -->
```python
def configure(window):
    import my_menu
    my_menu.configure(window)
```

mypickを実行し、上下キーでDownloadsを選んでEnterを押すとChoice: downloads、Escで取り消すとCanceledと表示します。itemsへアクセスする前に負値を確認してください。Pythonで添字-1を使うと最後の項目を選んでしまいます。

max_width・max_heightは省略できます。省略した軸は作業領域の上限に従い、整数を指定した軸だけ追加で制限します。

popMenuの結果は0始まりのインデックスで、取消は-1です。return_modkey=Trueなら取消を含め(index, modifiers)のタプルを返すため、先に分解してから判定します。項目は表示名を先頭にしたタプルで、後ろのデータは呼出し元が管理します。popMenuは親の無効化・復帰と一時ウィンドウの破棄を管理します。ListWindowを直接生成する場合は、その操作と寿命を自分で管理する必要があります。

## 複数の入力項目を持つダイアログを作る

scripts/my_form.pyを作成します。

<!-- example: dialog_module -->
```python
from contextlib import ExitStack
import ckit

def configure(window):
    def command_Form(info):
        was_enabled = window.isEnabled()
        dialog = ckit.Dialog(window, "Profile", [
            ckit.Dialog.Edit("name", 0, 32, "Name", "Alex"),
            ckit.Dialog.Choice("style", 0, "Style", ["Short", "Long"], 0),
        ])
        with ExitStack() as cleanup:
            if was_enabled:
                cleanup.callback(window.activate)
                cleanup.callback(window.enable, True)
            cleanup.callback(dialog.destroy)
            window.enable(False)
            dialog.messageLoop()
            result, values = dialog.getResult()
        if result == ckit.Dialog.RESULT_OK:
            print("Profile: " + values["name"] + ", " + str(values["style"]))
        else:
            print("Canceled")

    window.launcher.command_list.append(("myform", command_Form))
```

custom.pyへ次の呼出しを追加してreloadします。

<!-- example: dialog_setup -->
```python
def configure(window):
    import my_form
    my_form.configure(window)
```

myformを実行すると名前と形式を入力できます。名前をAlex、形式をShortのままEnterを押すとProfile: Alex, 0、Escで取り消すとCanceledと表示します。Tab／Shift+Tabで移動し、形式の左右キーで選択を変更します。Choiceの値は表示文字列でなく0始まりの番号です。

DialogのgetResult()は(RESULT_OKまたはRESULT_CANCEL, IDから値への辞書)です。取消時も辞書は返りますが、この例では適用しません。Editのwidthとindentは表示セル単位です。項目ごとのidは重複しない名前にします。ExitStackは確定・取消・例外のいずれでも破棄と親状態の復帰を実行し、元から無効な親を有効化・アクティブ化しません。

Dialog.Item系のvisibleにはvisible(dialog)を渡せます。非表示の項目も結果の辞書へ入るため、有効性を別途判断してください。表示条件の再構築で入力部品を作り直す場合があるので、内部のwidget参照を保持しません。通常はDialogを使い、Widgetを直接配置する場合は自分で描画・キー・文字・フォーカス・破棄を管理します。

## UIの更新を止めずに処理する

scripts/my_worker.pyを作成します。

<!-- example: worker_module -->
```python
import threading

def configure(window):
    def command_Count(info):
        canceled = threading.Event()

        def work():
            count = 0
            for unused in range(20):
                if canceled.wait(0.05):
                    return None
                count += 1
            return count

        result = window.subThreadCall(
            work, (), canceled.set, raise_error=True
        )
        if result is None:
            print("Canceled")
        else:
            window.setStatusMessage("Count: " + str(result), timeout=2000)

    window.launcher.command_list.append(("mycount", command_Count))
```

custom.pyへ次の呼出しを追加してreloadします。

<!-- example: worker_setup -->
```python
def configure(window):
    import my_worker
    my_worker.configure(window)
```

mycountを実行して約1秒待つと、Count: 20という状態メッセージを2秒間表示します。再度実行し、待機中にEscを押すとCanceledと表示します。ファイルやネットワークへの変更はありません。

subThreadCallはworkをワーカースレッドで実行しながらUIスレッドでメッセージを処理し、workの結果を返します。Escの関数はUIスレッドで呼ばれ、取消を要求するだけです。work側の協調が必要なので、この例ではEventを確認して終了します。workからGUIオブジェクトへアクセスせず、呼出しから戻ったUIスレッドで状態を表示します。

raise_error=Trueはワーカー例外を呼出し元で再送出します。既定ではエラーを表示してNoneを返します。UI側で例外が起きた場合は別で、フックを復元しますが実行中のワーカーを強制停止したり無期限にjoinしたりはしません。ワーカー側で資源を閉じ、処理が終了できるようにしてください。

通常のランチャー入力へすぐ戻る処理にはJobItemとアプリのJobQueue.defaultQueue()を使います。ワーカー関数も完了関数もJobItemを1つ受け取り、完了関数はキューを確認するスレッド（通常UIスレッド）で呼ばれます。結果は自分でitemの属性等へ保存します。ワーカーの戻り値は自動転送されません。取消は協調式で、実行を省略・取消したジョブでも完了関数が呼ばれる場合があります。アプリの既定キューを拡張側でjoin・destroyしないでください。

コンソールプログラムはwindow.subProcessCall([実行ファイル, 引数, ...])で出力をコンソールへ転送でき、終了コード、またはワーカー失敗の通知後にNoneを返します。shell=Falseなので自分で引用せずリストを渡します。cwd=Noneとenv=Noneは親のカレントディレクトリ・環境を継承します。enable_cancel=TrueはEscで終了を要求しますが、対応するウィンドウのないプログラム等は終了しない場合があります。文字コードと取消の制限はサブプロセスAPIを参照してください。

## ジョブを登録して通常入力へ戻る

scripts/my_job.pyを作成します。

<!-- example: job_module -->
```python
import time
import ckit

_active = None

def configure(window):
    def release():
        if _active is not None:
            _active.cancel()
            raise RuntimeError("Job is stopping; retry reload after completion")

    window.registerConfigCleanup(release)

    def command_Start(info):
        global _active
        if _active is not None:
            print("Already queued")
            return
        queue = ckit.JobQueue.defaultQueue()
        if queue is None:
            print("No default job queue")
            return

        def work(item):
            try:
                for unused in range(20):
                    if item.isCanceled():
                        return
                    item.waitPaused()
                    time.sleep(0.05)
                    item.count += 1
            except Exception as error:
                item.error = error

        def finished(item):
            global _active
            try:
                if item.error is not None:
                    print("Job failed: " + str(item.error))
                elif item.isCanceled():
                    print("Canceled")
                else:
                    window.setStatusMessage("Job: " + str(item.count), timeout=2000)
            finally:
                _active = None

        item = ckit.JobItem(work, finished)
        item.count = 0
        item.error = None
        _active = item
        queue.enqueue(item)

    def command_Cancel(info):
        if _active is not None:
            _active.cancel()

    window.launcher.command_list.append(("myjob", command_Start))
    window.launcher.command_list.append(("mycancel", command_Cancel))
```

custom.pyへ次の呼出しを追加してreloadします。

<!-- example: job_setup -->
```python
def configure(window):
    import my_job
    my_job.configure(window)
```

myjobを実行するとすぐ通常の入力に戻り、完了後にJob: 20を表示します。実行中にmycancelを実行すると取消を要求します。未完了の状態で再びmyjobを実行するとAlready queuedと表示します。開始前に取り消した場合も、本体が完了を確認したときにCanceledと表示します。

reload時は旧世代のreleaseが協調的取消を要求し、完了通知前なら例外で新設定の適用を延期します。コンソールのCanceledを待ってreloadを再実行してください。旧モジュールと登録はその間保持され、稼働中ジョブを強制終了しません。完了後に新しいモジュールの_activeをNoneから開始します。完了関数が未実行のジョブも扱えるよう、結果・エラーをenqueue前に初期化します。ワーカーはGUIを操作せず、finishedは本体のキュー確認を行うUIスレッドで動きます。本体が既に確認するので、自分でcheckAllを呼び直さないでください。このモジュールが所有するのはジョブで、本体のキューではありません。終了前はmycancelで要求し、完了を待ちます。

## 独自ウィンドウで複数行を編集する

通常の入力はcommandLine、フォームはDialogを使い、専用の複数行編集が必要なら[TextWidget](@ref textwidget)を親TextWindowへ組み込みます。次を使用中のscripts/my_text.pyへ保存します。この例はキーボード専用の一時編集窓です。

標準ランチャーテーマにはエディター用の色が揃っていないため、prepare_colorsでTextWidgetの共有color_*キャッシュを現在のfg/bg/選択色から初期化します。他のTextWidgetにもこの色設定が適用されます。構文色を使う拡張ではテーマのエディター色を用意し、代わりにTextWidget.updateColor()で読込みます。本体テーマや設定ファイルはこの例では変更しません。

<!-- example: textwidget_module -->
```python
import ckit


def prepare_colors():
    fg = ckit.getColor("fg")
    bg = ckit.getColor("bg")
    selected = ckit.getColor("select_bg")
    for name in ("fg", "bar_fg", "bar_error_fg", "bookmark1", "bookmark2", "bookmark3",
                 "syntax_text", "syntax_keyword", "syntax_name", "syntax_number", "syntax_string",
                 "syntax_preproc", "syntax_comment", "syntax_space", "syntax_error"):
        setattr(ckit.TextWidget, "color_" + name, fg)
    for name in ("diff_bg1", "diff_bg2", "diff_bg3", "line_cursor", "search_mark"):
        setattr(ckit.TextWidget, "color_" + name, bg)
    ckit.TextWidget.color_select_fg = ckit.getColor("select_fg")
    ckit.TextWidget.color_select_bg = selected
    gray = sum(selected) // 3
    ckit.TextWidget.color_select_bg_inactive = (gray, gray, gray)


class EditorWindow(ckit.TextWindow):
    def __init__(self, owner):
        self.edit = None
        self.result = None
        super().__init__(parent_window=owner, width=60, height=12,
                         title="Text: Ctrl+Enter prints, Esc cancels", title_bar=True,
                         sysmenu=True, resizable=False, show=False, caret=True,
                         bg_color=ckit.getColor("bg"),
                         activate_handler=self.onActivate, close_handler=self.quit,
                         keydown_handler=self.onKeyDown, char_handler=self.onChar,
                         move_handler=self.onMove)
        try:
            self.command = ckit.CommandMap(self)
            self.edit = ckit.TextWidget(self, 0, 0, self.width(), self.height())
            self.edit_list = [self.edit]
            self.edit.configure()
            bindings = {
                "Left": "CursorLeft", "Right": "CursorRight", "Up": "CursorUp", "Down": "CursorDown",
                "Home": "CursorLineBegin", "End": "CursorLineEnd",
                "S-Left": "SelectLeft", "S-Right": "SelectRight", "S-Up": "SelectUp", "S-Down": "SelectDown",
                "Return": "InsertReturn", "Back": "DeleteCharLeft", "Delete": "DeleteCharRight",
                "C-A": "SelectDocument", "C-Z": "Undo", "C-Y": "Redo", "C-Space": "CompleteAbbrev",
            }
            for key, name in bindings.items():
                self.edit.keymap[key] = getattr(self.edit, "command_" + name)
            self.edit.modifyText(text="apple apricot\nType here")
            self.edit.doc.clearModified()
        except BaseException:
            self.destroy()
            raise

    def onActivate(self, active):
        if self.edit is not None:
            self.edit.enableCursor(active)
            if not active:
                self.setCursorPos(-1, -1)
                self.edit.closeList()
            self.edit.paint()

    def onMove(self, x, y):
        if self.edit is not None:
            self.edit.onWindowMove()

    def onKeyDown(self, vk, mod):
        if vk == ckit.VK_ESCAPE:
            self.quit()
            return True
        if vk == ckit.VK_RETURN and mod == ckit.MODKEY_CTRL:
            self.result = self.edit.getText(self.edit.pointDocumentBegin(), self.edit.pointDocumentEnd())
            self.quit()
            return True
        return self.edit.onKeyDown(vk, mod)

    def onChar(self, ch, mod):
        self.edit.onChar(ch, mod)

    def executeCommand(self, name, info):
        return self.edit.executeCommand(name, info)

    def destroy(self):
        try:
            if self.edit is not None:
                self.edit.destroy()
                self.edit = None
        finally:
            super().destroy()


def configure(window):
    def command_Text(info):
        prepare_colors()
        enabled = window.isEnabled()
        editor = EditorWindow(window)
        try:
            window.enable(False)
            editor.show(True)
            editor.activate()
            editor.messageLoop()
            print("Canceled" if editor.result is None else editor.result)
        finally:
            try:
                editor.destroy()
            finally:
                window.enable(enabled)
                if enabled:
                    window.activate()
    window.launcher.command_list.append(("mytext", command_Text))
```

custom.pyの既存configureへ次の呼出しを統合し、reloadします。

<!-- example: textwidget_setup -->
```python
def configure(window):
    import my_text
    my_text.configure(window)
```

mytextを実行し、文字を入力します。Enterで改行、Shift+矢印で選択、Ctrl+Aで全選択、Ctrl+Z/YでUndo/Redoです。単語末尾にapと入力してCtrl+Spaceを押すとapple/apricotが候補になり、Enterで確定します。Ctrl+Enterは全文をコンソールへ出力して閉じ、Escまたは閉じるボタンはCanceledを出力します。ファイルへは保存しません。無効化はcustom.pyの適用呼出しを削除してreloadします。

親にcommandを用意してから部品を構築し、configureでキーマップを作り、その後キーを割り当てます。WordCompletionは親のedit_listから候補を集めます。非アクティブ時のカーソル・候補窓と親移動を配送し、終了時は部品→所有ウィンドウの順に破棄します。サイズ変更可能な窓では追加でonWindowSize・setPosSize・paintの接続も必要です。マウスを扱う場合は親のclientToCharのセル座標とセル内小数をonLeftButtonDown等へ渡し、ドラッグ中のキャプチャも親が管理します。

### 文書・位置・保存の契約

- edit.docはDocument、edit.selectionはSelectionです。point(line, index)は0始まりの行とPython文字位置で、表示セル位置ではありません。範囲の右端は含みません。編集後は古いPointを使い回さず取り直します。
- setDocument(doc)で通知を付け替え、先頭へ移動します。モード変更後はconfigureを呼び、独自キーも再設定します。主モードの設定後に副モードが追加順で設定され、コマンド探索は副モードを逆順に行います。
- Document(path, TextMode(), encoding=None)は存在するファイルを読みます。Noneなら空文書、存在しないパスも空文書です。readFileはseek可能なバイナリストリーム、writeFileはバイナリ出力へ現在位置から書きます。writeFileはseek・truncate・close・保存済み判定を行いません。保存先を適切に開き、書込み成功後に必要なfilename・clearModified・clearFileModifiedの更新を呼出側で行います。
- modifyTextは選択置換、getTextは範囲取得です。複数編集をまとめる場合はatomicUndoBeginとatomicUndoEndをtry/finallyで対にします。入れ子や例外時のロールバックは提供しません。
- getColumnFromIndex/getIndexFromColumnはPython文字位置と表示セルを変換し、補助平面文字・タブ・全角文字を扱います。低レベルのgetStringColumnsはUTF-16単位のままなので、Python文字列の添字には直接使わないでください。getStringWidth/getStringColumnsのoffsetはタブ展開開始セル、返却値は先頭0の相対幅です。例えばgetStringWidth("a\tb", 4, 3)は6を返します。
- 通常のcase=False検索はupperで照合し、元のPython文字範囲を返します。ßx内のxは(1, 2)、ssやsはß全体の(0, 1)に一致します。開始/終了境界も元の文字位置です。単語一致・正規表現の一致規則は従来どおりです。

### 単独Widgetを使う場合

[Widget部品](@ref widget)は親が入力・描画・フォーカス・寿命を管理します。通常の複数項目入力にはこのガイドのDialog例を使えます。

| 部品 | 結果と後処理 |
|---|---|
| ButtonWidget | Space/Enterでhandler()を同期呼出し。戻り値は使わない |
| CheckBoxWidget / ChoiceWidget | getValueでチェック値 / 0始まり選択番号を取得 |
| HotKeyWidget | getValueは2要素の整数リスト `[vk, mod]`。OSへのホットキー登録は親の責務 |
| ColorWidget | RGB取得。showで両Planeも表示切替。終了時は部品のdestroyでまとめて解放 |
| TimeWidget | 6整数の日時。初期値とgetValueで暦・時刻を検証し、不正値はValueError。setPosSizeは固定22×1セルで内部欄も移動。終了時はdestroy |
| ProgressBarWidget | 数値または行別進捗。Noneはbusy。入力リスト/タプルはコピーして補正。可視busy中だけタイマーを1件登録し、確定値・非表示・destroyで解除 |

TimeWidgetは編集中の0や一時的に存在しない日付を許します。確定前にgetValue()を呼び、ValueErrorなら画面を閉じずに入力を修正できるようにします。日付を自動補正しません。ColorWidget/TimeWidgetの内部資源は個別に破棄せず、部品のdestroy()へ任せます。Widget.enableImeはフォーカス中だけ親へ指定値を適用し、非フォーカス時は次のフォーカス用に保持します。

## pyautoで窓の情報と入力オブジェクトを扱う

[pyautoネイティブAPI](@ref pyauto_native)は、OSの窓を参照するWindow、RGB画像のImage、入力イベントのInput、監視のHookを提供します。ckit.Windowは自分のUIを作る窓、pyauto.Windowは既存HWNDの参照で、後者を破棄してもOS窓は閉じません。

次を使用中のscripts/my_native.pyへ保存します。この例はランチャー自身の窓情報、可視窓数、生成した小画像の検索結果を表示し、入力オブジェクトを準備します。通常デスクトップへ入力を送信しません。

<!-- example: native_module -->
```python
import pyauto


def configure(window):
    def command_Inspect(info):
        target = pyauto.Window.fromHWND(window.getHWND())
        if target is None:
            print("No window")
            return
        print("Title:", target.getText())
        print("Class:", target.getClassName())
        print("Rect:", target.getRect())
        visible = []
        def collect(candidate, result):
            if candidate.isVisible():
                result.append(candidate.getHWND())
            return 1
        pyauto.Window.enum(collect, visible)
        print("Visible windows:", len(visible))
        image = pyauto.Image.fromString("RGB", (2, 1), bytes([255, 0, 0, 0, 255, 0]))
        needle = pyauto.Image.fromString("RGB", (1, 1), bytes([0, 255, 0]))
        print("Pixel match:", image.find(needle))
        events = [pyauto.Key("A"), pyauto.Char("A")]
        print("Prepared events:", len(events))
    window.launcher.command_list.append(("mynative", command_Inspect))
```

custom.pyの既存configureへ次の呼出しを統合してreloadし、mynativeを実行します。

<!-- example: native_setup -->
```python
def configure(window):
    import my_native
    my_native.configure(window)
```

Title/Class/Rectと可視窓数は実行環境に応じた値、Pixel matchは(1, 0)、Prepared eventsは2になります。無効化は適用呼出しを削除してreloadします。

### 参照・入力・監視の境界

- Windowの座標はピクセルです。fromHWND(0)や未発見のfindはNone。同じHWNDのラッパーを保持しても、OSでの窓の寿命は延長しません。find/enumで得た窓も使用時には消えている場合があります。
- enumはcallback(window, arg)を同期呼出しします。C intの1で継続、0で停止し、Noneは返しません。sendMessageは対象窓の応答を待ち、引数/結果はC int幅です。64bitのポインター受渡しには使いません。
- Key("A")は仮想キー、Char("A")はUTF-16の文字単位です。Key("a")のような文字列を大文字化しません。補助平面文字1文字からCharがサロゲート対を自動生成することもありません。
- Input.send(events)を明示的に呼ぶと、OS入力列へ送信し、その時点の入力先に作用します。イベントの構築と送信は別です。マウス座標は仮想デスクトップの画面ピクセルで、左/上の画面の負座標にも対応します。範囲外は各軸の端へ丸め、ホイールに移動は含まれません。通常の本体操作は既存キー設定やコマンド呼出しを使えます。
- Hookはプロセスに1所有者だけを置き、既存の監視を重複生成しません。本体のキー追加は既存キーマップが使えます。mousemove(x, y)は画面ピクセルで通知します。終了時はdestroy()だけで全監視と参照を解放します。引数・戻り値・終了手順はネイティブAPIのHook節を参照してください。Hook生成後にwindow.registerConfigCleanup(hook.destroy)を登録すると、reload・終了時に解放します。

### 別プロセスのIME変換状態

Window.getImeStatus()はIMEの開閉だけを返します。別プロセスの編集欄はtarget.isImeConverting(1000)で照会し、True（空でない未確定の変換範囲あり）、False（対応プロバイダーが範囲なし、または空範囲と応答）、None（非対応）を区別します。TimeoutErrorや権限等のOSErrorをFalseへ変換しないでください。Windows 8.1以降のUI Automation TextEditPatternを使い、指定HWND内でフォーカスされた子孫のUIA要素を優先します。ブラウザー枠自身もフォーカスありと報告される場合に、枠を先に選ばないためです。独自HWNDを持たないブラウザー内の編集欄も選択でき、見つからない場合だけHWND自身を照会します。探索はUIAのcontrol view内で、別の窓へ広げず、選択した要素の非対応/失敗を親のFalseで隠しません。IMM/TSFへの直接照会や独自DLL注入は行いません。同一プロセスはValueErrorです。

EdgeのHTML textareaではwindowlessな編集要素の選択と、非変換時のFalseを確認しています。公開プロバイダーのない編集欄へは対応せず、任意のアプリ/IMEや実IMEの状態遷移を保証するものではありません。

次の補助関数をscripts/my_ime.pyへ保存し、独自のワーカー処理でfrom my_ime import describe_imeとして使用できます。外部アプリにフォーカスがある間にtarget = pyauto.Window.getFocus()で取得した編集欄をdescribe_ime(target)へ渡すと、文字列の状態または失敗理由が返ります。配置だけでは登録・監視を開始しません。呼出しを外すと無効になり、モジュールの変更はreloadで反映します。

<!-- example: ime_query -->
```python
def describe_ime(target):
    if target is None:
        return "No focus"
    try:
        state = target.isImeConverting(250)
    except (OSError, ValueError) as error:
        return f"{type(error).__name__}: {error}"
    if state is None:
        return "Unsupported"
    return "Composing" if state else "Idle"
```

引数は位置指定、待機上限は1～60000ミリ秒です。期限切れ後もプロバイダーの終了処理が残る場合、次の照会はOSError（winerror=170、busy）となります。完了まで待ち、応答が戻らない場合は呼出し元を再起動します。結果は瞬間の値で、フォーカス移動時に確定されるアプリもあります。UI/フック内の高頻度な同期照会は避け、管理者窓・windowlessな編集欄や全IMEへの対応を仮定しないでください。[Windowの詳細契約](@ref pyauto_Window)も参照してください。

## ネイティブ描画とファイル情報

[ckitネイティブAPI](@ref ckit_native)はWindow・Plane・Font・Image・メニュー・行データ、[clnch_native API](@ref clnch_native_api)はファイル・共有・Shell・色選択を扱います。通常のフォームはDialog、文字窓はTextWindowを先に使えます。

選択中の設定保存先のscripts/my_planes.pyへ次を保存します。ピクセル寸法の独自窓に文字とRGBA画像を描く例です。

<!-- example: planes_module -->
```python
import ckit


def configure(window):
    def command_Preview(info):
        enabled = window.isEnabled()
        left, top, _, _ = window.getWindowRect()
        preview = ckit.Window(
            x=left, y=top, width=320, height=88, parent_window=window,
            title="Native preview", show=False, resizable=False,
            bg_color=(24, 24, 24),
            close_handler=lambda: preview.quit(),
            keydown_handler=lambda vk, mod: preview.quit() if vk == ckit.VK_ESCAPE else None)
        try:
            if not preview.getHWND():
                raise RuntimeError("Could not create preview")
            text = ckit.TextPlane(preview, (8, 8), (304, 24), 0.0)
            text.setFont(ckit.getStockedFont("MS Gothic", 16))
            text.putString(0, 0, 30, 1, ckit.Attribute(fg=(240, 240, 240)), "Native planes: Esc to close")
            image = ckit.Image.fromBytes((2, 1), bytes([255, 0, 0, 255, 0, 255, 0, 255]))
            picture = ckit.ImagePlane(preview, (8, 40), (64, 32), 1.0)
            picture.setImage(image)
            window.enable(False)
            preview.show(True)
            preview.messageLoop()
        finally:
            try:
                preview.destroy()
            finally:
                window.enable(enabled)
                if enabled:
                    window.activate()
    window.launcher.command_list.append(("mypreview", command_Preview))
```

既存custom.pyのconfigureへ次の呼出しを統合してreloadします。

<!-- example: planes_setup -->
```python
def configure(window):
    import my_planes
    my_planes.configure(window)
```

mypreviewを実行すると説明文と赤/緑の帯が表示されます。Escまたは閉じるボタンで終了し、親の有効状態を復帰します。所属Planeはpreview.destroyでまとめて破棄します。親が元から無効なら有効化しません。無効化は設定呼出しを削除してreloadです。

Planeの配置/寸法はクライアントピクセル、putStringは文字セルです。setFontを先に呼び、priorityが小さいPlaneを前面に置きます。setPriorityで構築後の重なり順を変更でき、同値間の既存順は保持します。getFont/getImageは同じネイティブ資源を参照する新ラッパーを返し、Pythonのis一致は保証しません。clearは全Planeを無効化するためTextWindowには使いません。直接Windowを使うこの例にはTextWidgetの編集・IME機能はありません。

Image.fromBytesは短いバッファ・寸法積の超過・確保/GDI失敗を例外で通知します。Windowの破棄はヒットテスト関数とメニュー木も解放します。TaskTrayIconも明示destroyが必要で、以後の操作はValueErrorです。

scripts/my_files.pyへ次を保存すると、指定したワイルドカードの情報をワーカーで列挙できます。

<!-- example: files_module -->
```python
import clnch_native


def configure(window):
    def command_Stat(info):
        if len(info.args) != 1 or not info.args[0]:
            print(r"Usage: mystat;C:\folder\*")
            return
        pattern = info.args[0]
        items = window.subThreadCall(lambda: clnch_native.findFile(pattern, use_cache=False), (), raise_error=True)
        print("Entries:", len(items))
        for name, size, stamp, attributes in sorted(items):
            print(name, size, stamp, hex(attributes))
    window.launcher.command_list.append(("mystat", command_Stat))
```

既存custom.pyのconfigureへ次の呼出しを統合してreloadします。

<!-- example: files_setup -->
```python
def configure(window):
    import my_files
    my_files.configure(window)
```

`mystat;C:\folder\*`のように既存フォルダーを指定して実行します。件数と各項目の名前・バイト数・ローカル更新日時・属性ビットがコンソールへ出ます。該当なしはEntries: 0、存在しない親などのOSエラーはコンソールへ通知されます。ファイルを変更しません。use_cache=Falseで時刻/内容が古いキャッシュを避けます。接続や認証はこの例では行いません。無効化は設定呼出しを削除してreloadです。

setFileTime(path, (2024, 2, 29, 12, 34, 56))はローカル日時で最終更新時刻を設定します。無効な日時はファイル変更前にValueError、OS失敗はOSErrorです。読取専用属性は一時解除して復元します。更新後に後始末だけが失敗する場合もあるため、例外のnotesを確認してください。時刻のロールバックはしません。Shellメニュー/ドラッグはNoneから成功と取消を区別できません。chooseColorは戻り値のresultが非ゼロのときだけ色を適用します。これらの制約・後始末・引数は上記APIページを参照してください。

大きなファイルの行をbytesで取得するには、from ckit.ckit_hugefile import HugeTextFileで取得し、HugeTextFile(fd.fileno(), encoding, offset)へ開いたバイナリファイルを渡します。offsetはBOM等を飛ばす開始バイト位置、getLineの行番号は0始まりです。UTF-16LE/BEのCR・LF・CRLFはoffsetを基準とする2バイト境界だけで検出し、文字内の紛らわしいバイト列は改行として扱いません。行末込みのbytesを返し、末尾改行の後は空の最終行があります。要求された行まで64 KiB単位で走査・位置をキャッシュし、ファイル全体をbytesへ複製しません。使用後はreader.close()でmmapを解放してから呼出し元でfdを閉じます。詳細は[HugeTextFileのAPI](@ref misc)を参照してください。

## 状態表示と資源の管理

UIスレッドからwindow.setStatusMessage("Saved", timeout=2000)を呼ぶと、2000ミリ秒表示します。error=Trueならエラー色、timeout=Noneなら置換またはclearStatusMessage()まで表示します。置換すると以前の期限タイマーを解除します。

入力していないときの独自表示にはregisterStatusBar(func, priority=-1, interval=None)を使います。func(width)は表示文字列を返し、widthは表示セル数、intervalはミリ秒です。priorityは小さい値ほど優先します。短い処理にしてください。unregisterStatusBar(func)は登録したその関数とタイマーを解除します。資源の終了処理をregisterConfigCleanup(func)へ登録すると、次の設定読込成功後の置換前とアプリ終了時にUIスレッドで呼ばれます。引数なし、戻り値は未使用、登録の逆順です。同一オブジェクトの重複登録は無視します。

次はcustom.pyへ追加できる独立した例です。既存configureへ処理を統合し、reloadします。入力を終了するとReload safeと表示し、呼出しを削除してreloadすると表示とタイマーが解除されます。

<!-- example: reload_cleanup -->
```python
def configure(window):
    def status(width):
        return "Reload safe"

    window.registerConfigCleanup(lambda: window.unregisterStatusBar(status))
    window.registerStatusBar(status, interval=1000)
```

取得した窓にはwindow.registerConfigCleanup(child.destroy)、Hookにはwindow.registerConfigCleanup(hook.destroy)、独自タイマーにはwindow.registerConfigCleanup(lambda: window.killTimer(tick))を登録します。解除対象の旧オブジェクトをクロージャーや束縛メソッドで保持し、モジュールの新定義から検索し直さないでください。終了処理は再試行可能にし、例外後も他の処理を試みます。成功分は除去し、失敗分だけ再試行します。reload時の終了失敗は新しい独自設定を適用せず、旧独自キー・コマンド・関連付け・入力処理・一覧フックを外し、標準機能と検証済みJSONへ退避します。既に解放した資源は復元しません。旧モジュールと失敗した終了処理は再試行用に保持し、修正・ジョブ完了後のreloadで終了を再試行して独自設定を適用します。アプリ終了時は失敗を通知して本体の破棄を続けます。

本体が設定として再構築する登録以外の、直接登録したタイマー・Hook・実行中ジョブ・外部の旧関数参照は、この退避で停止・更新されません。終了処理が停止前に失敗したタイマーは、別の終了処理が破棄した窓を引き続き参照できます。依存するコールバックを先に停止し、ジョブが使う資源は完了まで破棄しないよう、所有者側で終了順序を管理してください。一つの終了処理が途中まで成功してから失敗する場合も、再試行で二重解放しないようにしてください。停止や参照の回収ができない場合は再起動します。

管理外のキューやタイマーを増やす前に、アプリの既存JobQueue・SyncCallを使います。独自タイマー、スレッド、ネイティブウィンドウ、フックにはそれぞれ解除・停止手順が必要です。configure途中の失敗は、それまでのすべての変更を巻き戻す動作にはなりません。

独自設定の読込・フック・登録済み終了処理からのSystemExit・KeyboardInterruptもエラーとして通知し、本体を継続します。未定義のフックは正常です。初回のcustom.py読込・フック検証に失敗した場合は、独自設定を適用せず標準キー・組込コマンドと検証済みJSONで起動します。Ctrl+F10でコンソールのトレースバックを確認し、選択中の保存先のcustom.pyやimport先を修正して、入力欄でreloadを実行できます。configure()の実行が始まってから失敗した場合は、初回起動でも部分適用が残ります。失敗時はReload成功を通知しません。

## 変更反映・無効化・問題の調べ方

reloadはcommands.jsonを先に読み込み、構文・形式・登録名を検証してからcustom.pyの読込と旧資源の終了へ進みます。JSON読込・検証に失敗すると、旧コマンド・別名・キー・独自設定・登録済み資源を保持してエラーを通知し、成功通知は出しません。修正後にreloadすると、検証済みの読込結果へ切り替わります。ファイルが存在しない場合は空登録として扱い、JSONの既存登録を外して標準・独自設定を再適用します。アクセス拒否等のI/Oエラーは欠損として扱いません。標準・独自設定の適用途中で失敗した場合も成功通知は出しませんが、部分適用は巻き戻しません。

| 変更 | 反映方法 |
|---|---|
| custom.py自体 | reload。新しい名前空間で評価 |
| 通常import・対応する動的importで選択したscripts/・extensions/のPythonソースと依存先 | reload。新しい名前空間で再読込 |
| このガイドのコマンド・キー設定の呼出しをcustom.pyから削除 | reload。標準コマンド一覧とキーマップを作り直す |
| 資源を作る呼出しを削除 | registerConfigCleanupへ終了処理を登録してreload。未登録資源は明示解放 |
| reclnch.iniを直接編集 | 終了して編集後に再起動。reloadはこのファイルを再読込しない |

適用関数の呼出しはフック内へ置き、呼出順が適用順になります。公式拡張は配置だけでは有効になりません。本体・標準ライブラリの検索先、extensions/、使用中のscripts/の順で検索するため、ckit・clnchや公式拡張と同名のモジュールは避けてください。

対象は、選択中の保存先のscripts/とアプリ側のextensions/にあるPythonソース（.py）、通常・namespaceパッケージとその対象内の依存先です。custom.pyと対象ソース内の通常のimport/from-importに加え、トップレベル・configure・configure_ListWindowとそれらから呼ぶ対象ソース内のimportlib.import_moduleも追跡します。対象ソース内のfrom importlib import import_module（別名を含む）や、パッケージ名を指定する相対importにも対応します。

次のreloadで旧世代のキャッシュを外し、importされた順に読みます。循環はPythonの通常規則に従い、未初期化の定義をfrom-importする循環は失敗します。削除した定義とfrom-importの参照は新世代で置き換わり、同じ時刻・サイズの編集でもソースを読みます。標準ライブラリ・本体・選択外のモジュールは再読込せず、配置の自動探索・監視もしません。C拡張、対象外の場所、対象外のライブラリから渡された元のimport_moduleや独自ローダーによる読込は対象外です。任意のバックグラウンド処理やフック終了後の遅延import全般は保証しません。

旧登録を保ってモジュールの構文・読込を確認したい場合は、import my_module等をcustom.pyのトップレベルへ置き、configure内ではmy_module.configure(window)を呼びます。正常設定からのReloadでは、トップレベルの構文・読込・configure／configure_ListWindowのcallable検査が失敗すれば旧名前空間・対象モジュール・登録・資源を保持します。フック内のimportはフック実行時に読み込むため、その失敗は適用途中の失敗です。configure_ListWindowで初めてimportするものは次に一覧を開く時に読みます。

設定適用開始後の失敗では部分適用と登録済みの終了処理が残ります。修正してreloadすると、その処理を終了して再適用します。保持した旧関数・実行中ジョブ・既に開いた一覧等の外部参照は書き換えません。ジョブは上の例のように取消・完了後に再試行し、一覧は閉じて開き直します。import時に窓・スレッド等を作らず、configure内で取得と終了登録を行ってください。任意Python副作用の完全ロールバックは保証しません。未登録資源を回収できない場合や対象外のモジュール変更は再起動が必要です。

Ctrl+F10でコンソールを開くと、printの出力やトレースバックを読めます。動かない場合は設定保存先、登録名の綴り、同名の標準・JSON登録、reload時の読込・終了・適用のどの段階で失敗したかを確認し、修正してreloadしてください。同名のJSON優先、JSON編集後の独自登録保持、ディスクINI非再読込の契約は変わりません。

例の表示メッセージは、日英ヘルプで同じコードを使えるようASCIIにしています。動作確認後に好みの文言へ変更できます。既存フックを別のdef configureで置き換えず、必要な呼出しを統合してください。

## APIリファレンス

- [メインウィンドウと入力](@ref mainwindow): MainWindow、commandLine、ShellExecuteCommand、UrlCommand、状態表示とワーカー呼出し。
- [コマンド](@ref command): CommandInfo、CommandMap、CommandSequence。
- [一覧ウィンドウ](@ref listwindow): ListWindow、popMenu。
- [スレッド支援](@ref threadutil): JobItem、JobQueue、SyncCall。
- [サブプロセス](@ref subprocess): SubProcess。
- [Widgetとフォーム](@ref widget): TextWindow、Widget派生部品、EditWidget、Dialog。
- [複数行編集](@ref textwidget): TextWidget、Document、Point、Selection、Mode、Lexer、Completion、Search。
- [pyautoの入力部品](@ref pyautoinput)と[ネイティブ契約](@ref pyauto_native): Window、Image、Input、Hook、Shell。
- [ckitネイティブAPI](@ref ckit_native)と[clnch_native API](@ref clnch_native_api): 低水準描画・メニュー・行・ファイル・Shell。
- <a href="topics.html">APIの全グループ</a>。
