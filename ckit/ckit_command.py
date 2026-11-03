## @cond japanese
## @addtogroup command コマンド機能
## @endcond
## @cond english
## @addtogroup command Commands
## @endcond
## @addtogroup command
## @{

## \~japanese
# コマンドの引数に与えられる情報を格納するクラス
#
#  コマンド関数は info を1つ受け取ります。通常は呼出し元が生成し、独自に呼ぶ場合は
#  CommandInfo() を作り args・mod を設定します。初期値は args=[]、arg_string=None、mod=0、result=True です。
#  args は文字列リストですが、内容は呼出経路で異なります。
#  名前入力では最初のセミコロン以降をWindows規則で解析し、arg_stringにその原文を保持します。
#  メイン入力のキーはargs=[入力全体]、arg_string=入力全体で、一覧のキーはargs=[]、arg_string=Noneです。
#  ShellExecuteCommandはarg_stringがNoneでなければ原文を使い、NoneならargsをjoinArgsで整形します。
#  argsを変更して起動するPython処理はarg_string=Noneにします。独自入力プロトコルは自身の契約を使います。
#  メイン入力・一覧キー経由の mod は0です。
#  名前実行時の mod は MODKEY_CTRL 等とのビット演算で調べます。
#  result は CommandSequence の成否判定用で、Python関数の戻り値とは別です。
#  @sa CommandSequence, CommandMap
# \~english
# Information passed to a command
#
#  A command callable accepts one info argument, normally created by the caller. To invoke a command
#  yourself, create CommandInfo() and set args/mod. Defaults: args=[], arg_string=None, mod=0, result=True.
#  args is a list of strings. Named input parses text after the first semicolon using Windows rules;
#  arg_string preserves that original text. Main-input keys use args=[entire input], arg_string=entire input.
#  List-window keys pass args=[], arg_string=None. ShellExecuteCommand uses non-None arg_string unchanged;
#  otherwise it formats args with joinArgs. Python changing args before launch must set arg_string=None.
#  Custom input protocols retain their own contracts.
#  mod is 0 for main-input and list-window key bindings. For named execution, test it with masks such as MODKEY_CTRL.
#  result is used by CommandSequence, independently of a Python function's return value.
#  @sa CommandSequence, CommandMap
# \~
class CommandInfo:
    ## \~japanese
    # コンストラクタ
    # \~english
    # Constructor
    # \~
    def __init__(self):
        ## \~japanese
        # CommandSequenceが読む成否。初期値True。次のコマンドを試す場合にFalseを代入します。
        # \~english
        # Success flag read by CommandSequence. Initially True; set False to try the next command.
        # \~
        self.result = True

        ## \~japanese
        # コマンドに与えられた引数
        # \~english
        # Command arguments
        # \~
        self.args = []

        ## \~japanese
        # 起動用の生のWindows引数文字列。NoneならargsをjoinArgsで整形します。
        # \~english
        # Raw Windows argument text for launching. None formats args with joinArgs.
        # \~
        self.arg_string: str | None = None

        ## \~japanese
        # コマンド実行時に押されていたモディファイアキー
        # \~english
        # Modifier keys held when the command was invoked
        # \~
        self.mod = 0


## \~japanese
# 名前を使って所有オブジェクトのコマンドを呼び出す関数オブジェクト
#
#  通常は直接生成せず window.command.Name を取得します。呼ぶと owner.executeCommand(name, info)へ委譲し、
#  info省略時は新しいCommandInfoを作ります。コマンドが見つからない場合はinfo.result=Falseにします。
#  この呼出しの戻り値はNoneで、対象コマンドの戻り値は転送しません。実行中の例外は伝播します。
#  @sa CommandMap, CommandInfo
# \~english
# Callable dispatching a named command to its owner
#
#  Normally obtain window.command.Name instead of constructing this directly. Calling it delegates to
#  owner.executeCommand(name, info), creating a new CommandInfo when omitted. If no command is found,
#  set info.result=False. Return None without forwarding the target's result; execution exceptions propagate.
#  @sa CommandMap, CommandInfo
# \~
class NamedCommand:
    ## \~japanese
    #  @param owner executeCommand(name, info)を持つ所有オブジェクト。
    #  @param name command_接頭辞を除いたコマンド名。
    #
    # \~english
    #  @param owner Owner exposing executeCommand(name, info).
    #  @param name Command name without the command_ prefix.
    #
    # \~
    def __init__(self, owner, name):
        self.owner = owner
        self.name = name

    ## \~japanese
    #  @param info 渡すCommandInfo。Noneなら初期値の新規オブジェクト。
    #  @return None。未解決時はinfo.resultをFalseにします。
    #
    # \~english
    #  @param info CommandInfo to pass; None creates one with default values.
    #  @return None. Set info.result=False if not resolved.
    #
    # \~
    def __call__(self, info=None):
        if info is None:
            info = CommandInfo()
        if not self.owner.executeCommand(self.name, info):
            info.result = False


## \~japanese
# 成功扱いになるまでコマンドを順に試すためのクラス
# 
#  各コマンドへ同じ CommandInfo を渡し、呼び出し後の info.result が真なら後続を実行せず終了します。
#  戻り値では判定しません。各試行の直前に info.result だけを True に戻し、他の属性は保持します。後続へ進める場合は
#  コマンド側で info.result = False としてください。すべてを必ず実行するためのクラスではありません。
# \~english
# Try commands in order until one reports success
# 
#  Pass the same CommandInfo to each command and stop when info.result is true after a call.
#  The return value is not used. Reset only info.result to True before each attempt, preserving other attributes; to try the next command,
#  set info.result = False in the command. This class does not unconditionally execute every command.
# \~
class CommandSequence:
    ## \~japanese
    #  @param commands 試す順番に並べた、CommandInfoを受け取る可変個の関数。
    #
    # \~english
    #  @param commands Variable number of callables accepting CommandInfo, in trial order.
    #
    # \~
    def __init__(self, *commands):
        self.commands = commands

    ## \~japanese
    #  @param info 各関数で共有するCommandInfo。Noneなら新規作成。
    #  @return None。関数の戻り値は使わずinfo.resultが真になると停止します。
    #  実行中の例外は伝播し、それ以降の関数を呼びません。
    #
    # \~english
    #  @param info CommandInfo shared by all callables; None creates a new instance.
    #  @return None. Ignore callable return values and stop when info.result is true.
    #  An execution exception propagates and prevents later calls.
    #
    # \~
    def __call__(self, info=None):
        if info is None:
            info = CommandInfo()
        for command in self.commands:
            info.result = True
            command(info)
            if info.result:
                return


## \~japanese
# window.command.Name形式で既存コマンドを取得する窓口
#
#  ownerはexecuteCommand(name, info)を持つオブジェクトです。属性を読むたびにNamedCommandを返します。
#  属性取得時はコマンドの存在を検査せず、呼出時に解決します。キー割当には括弧を付けず関数を渡します。
#  例: window.keymap["C-F10"] = window.command.ConsoleToggle。
#  コマンド名はcommand_接頭辞を除いた名前で、大文字小文字を保持します。JSON登録名の解決とは別です。
#  @sa NamedCommand, CommandInfo
# \~english
# Access existing commands through window.command.Name
#
#  owner must provide executeCommand(name, info). Each attribute lookup returns a NamedCommand without
#  checking whether the command exists; resolution occurs when called. Bind the callable without parentheses,
#  for example window.keymap["C-F10"] = window.command.ConsoleToggle.
#  Use the command_ method name without its prefix, preserving case. This differs from JSON name resolution.
#  @sa NamedCommand, CommandInfo
# \~
class CommandMap:
    ## \~japanese
    #  @param owner executeCommand(name, info)でコマンドを解決するオブジェクト。
    #
    # \~english
    #  @param owner Object resolving commands through executeCommand(name, info).
    #
    # \~
    def __init__(self, owner):
        self.owner = owner

    def __getattr__(self, name):
        return NamedCommand(self.owner, name)


## @} command
