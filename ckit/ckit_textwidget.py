import bisect
import math
import os
import re
import struct
import weakref as _weakref
from typing import ClassVar as _ClassVar

import pyauto
from ckit import (
    ckit_command,
    ckit_key,
    ckit_misc,
    ckit_resource,
    ckit_textwindow,
    ckit_theme,
    ckit_userconfig,
    ckit_widget,
    ckitcore,
)
from ckit.ckit_const import (
    LINE_BOTTOM,
    LINE_DOT,
    LINE_RECTANGLE,
    MODKEY_ALT,
    MODKEY_CTRL,
    MODKEY_SHIFT,
    ORIGIN_X_LEFT,
    ORIGIN_Y_TOP,
    VK_RETURN,
    VK_TAB,
)

## @cond japanese
## @addtogroup textwidget テキスト編集ウィジェット機能
## @endcond
## @cond english
## @addtogroup textwidget Text Editor Widgets
## @endcond
## @addtogroup textwidget
## @{

# --------------------------------------------------------------------

Line = ckitcore.Line

DEFAULT_LINEEND = "\r\n"  # CRLF is the default; ReCraftLaunch does not use TextWidget or need a default-line-ending setting.

# --------------------------------------------------------------------


lexer_debug = False


## \~japanese
# 構文色の境界列をbytesへ変換する補助クラス。各要素は(文字位置, Token_*番号)です。
# 位置は昇順のPython文字列インデックス。Token_Text/Keyword/Name/Number/String/Preproc/Comment/Space/Errorを使います。
# \~english
# Pack syntax-color boundaries into bytes. Each entry is (character_index, Token_* value).
# Use ascending Python string indices and Token_Text/Keyword/Name/Number/String/Preproc/Comment/Space/Error.
# \~
class Token:
    stock_SimpleTextLine = struct.pack("ii", 0, 0)

    ## \~japanese
    # 境界列をネイティブintペアのbytesへ変換します。整数範囲外等のstruct例外は伝播します。
    # \~english
    # Pack boundaries as native-int-pair bytes; struct errors such as integer overflow propagate.
    # \~
    @staticmethod
    def pack(tokens):
        if tokens == [(0, 0)]:
            return Token.stock_SimpleTextLine
        s = b""
        for token in tokens:
            s += struct.pack("ii", token[0], token[1])
        return s

    ## \~japanese
    # packのbytesを(位置, 種類)リストへ復元します。長さは8の倍数が必要です。
    # \~english
    # Unpack packed bytes into a list of (index, type); length must be a multiple of eight.
    # \~
    @staticmethod
    def unpack(s):
        tokens = []
        for i in range(0, len(s), 8):
            tokens.append(struct.unpack("ii", s[i : i + 8]))
        return tokens


## \~japanese
# 構文色を指定するトークン番号。Lexerの境界列で使います。
# \~english
# Syntax-color token identifier used in Lexer boundary lists.
# \~
Token_Text = 0
## \~japanese
# 構文色を指定するトークン番号。Lexerの境界列で使います。
# \~english
# Syntax-color token identifier used in Lexer boundary lists.
# \~
Token_Keyword = 1
## \~japanese
# 構文色を指定するトークン番号。Lexerの境界列で使います。
# \~english
# Syntax-color token identifier used in Lexer boundary lists.
# \~
Token_Name = 2
## \~japanese
# 構文色を指定するトークン番号。Lexerの境界列で使います。
# \~english
# Syntax-color token identifier used in Lexer boundary lists.
# \~
Token_Number = 3
## \~japanese
# 構文色を指定するトークン番号。Lexerの境界列で使います。
# \~english
# Syntax-color token identifier used in Lexer boundary lists.
# \~
Token_String = 4
## \~japanese
# 構文色を指定するトークン番号。Lexerの境界列で使います。
# \~english
# Syntax-color token identifier used in Lexer boundary lists.
# \~
Token_Preproc = 5
## \~japanese
# 構文色を指定するトークン番号。Lexerの境界列で使います。
# \~english
# Syntax-color token identifier used in Lexer boundary lists.
# \~
Token_Comment = 6
## \~japanese
# 構文色を指定するトークン番号。Lexerの境界列で使います。
# \~english
# Syntax-color token identifier used in Lexer boundary lists.
# \~
Token_Space = 7
## \~japanese
# 構文色を指定するトークン番号。Lexerの境界列で使います。
# \~english
# Syntax-color token identifier used in Lexer boundary lists.
# \~
Token_Error = -1


## \~japanese
# 字句分析の初期文脈名rootを返します。
# \~english
# Return the initial lexer context name root.
# \~
def rootContext():
    return "root"


## \~japanese
# シンタックス分析クラスのベースクラス
#
# Mode.lexerへ設定する派生クラスの契約です。lex(ctx, line, detail)のlineは改行なし文字列、ctxは行頭の文脈（初期値root）です。
# detail=Falseでは次行の文脈、Trueでは([(文字インデックス, Token_*), ...], 次行の文脈)を返します。
# 基底lexはNoneを返すだけなので、実用にはTextLexerか派生実装を使います。
#
# \~english
# Base class for syntax lexers
#
# Subclass contract for Mode.lexer. lex(ctx, line, detail) receives text without a line ending and the starting context (initially root).
# Return the next context for detail=False, or ([(character_index, Token_*), ...], next_context) for True.
# The base lex only returns None; use TextLexer or an implementation.
#
# \~
class Lexer:
    ## \~japanese
    # 引数なしで構築します。Lexer基底は分析を実装せず、RegexLexerは空のrule_mapで開始します。
    # \~english
    # Construct without arguments; the Lexer base has no analysis implementation and RegexLexer starts with an empty rule_map.
    # \~
    def __init__(self):
        pass

    ## \~japanese
    # 派生実装で置き換える分析入口です。基底はNoneを返します。戻り値の契約はクラス説明を参照。
    # \~english
    # Override this entry point; the base returns None. See the class for the result contract.
    # \~
    def lex(self, ctx, line, detail):
        pass


## \~japanese
# テキストファイル用のシンタックス分析クラス
#
# 常に同じ文脈を返し、detail=Trueなら共有の[(0, Token_Text)]を返します。結果リストを書き換えないでください。
#
# \~english
# Plain-text syntax lexer
#
# Return the unchanged context and, for detail=True, the shared [(0, Token_Text)] list. Do not mutate that list.
#
# \~
class TextLexer(Lexer):
    tokens = [(0, Token_Text)]  # noqa: RUF012  # Shared plain-text lexer result.

    ## \~japanese
    # 引数なしで構築します。Lexer基底は分析を実装せず、RegexLexerは空のrule_mapで開始します。
    # \~english
    # Construct without arguments; the Lexer base has no analysis implementation and RegexLexer starts with an empty rule_map.
    # \~
    def __init__(self):
        Lexer.__init__(self)

    ## \~japanese
    # detail=Trueは(共有境界列, ctx)、Falseはctxを返します。
    # \~english
    # Return (shared_boundaries, ctx) for detail=True, otherwise ctx.
    # \~
    def lex(self, ctx, line, detail):
        if detail:
            return TextLexer.tokens, ctx
        else:
            return ctx


## \~japanese
# 正規表現のテーブルを使ったシンタックス分析クラスのベースクラス
#
# 派生クラスの初期化でrule_mapとre_flagsを設定します。rule_mapは文脈名からルールのリストへの辞書です。
# ルールは(pattern, token, next_context=None, flags=0)。pattern=Noneは未一致部分の既定ルールで、リストの最後に置きます。
# tokenはToken_*整数またはキャプチャグループごとの整数リスト。グループは隙間なく一致全体を覆うようにします。
# next_contextは偽値なら文脈維持。flagsにRegexLexer.Detailを指定すると詳細分析時だけ適用します。
# 最初のlexで正規表現をコンパイルしrule_mapを置換します。以後ルールを変更しません。全参照先文脈に既定ルールを用意し、
# 消費文字のない循環を作らないでください。不正文法のre例外・未定義文脈のKeyErrorは伝播します。
# @code{.py}
# import ckit
# class NumberLexer(ckit.RegexLexer):
#     def __init__(self):
#         super().__init__()
#         self.rule_map = {"root": [(r"\d+", ckit.Token_Number), (None, ckit.Token_Text)]}
# @endcode
#
# \~english
# Base class for syntax lexers driven by regular-expression tables
#
# Initialize rule_map and re_flags in the subclass. rule_map maps context names to lists of rules.
# A rule is (pattern, token, next_context=None, flags=0). Put pattern=None last as the fallback for unmatched text.
# token is a Token_* integer or one integer per capture group; groups must cover the whole match contiguously.
# A false next_context retains context. RegexLexer.Detail restricts a rule to detailed lexing.
# The first lex compiles regexes and replaces rule_map entries; do not change rules afterwards. Provide a fallback for every referenced context
# and avoid zero-consumption cycles. Regex errors and KeyError for unknown contexts propagate.
# @code{.py}
# import ckit
# class NumberLexer(ckit.RegexLexer):
#     def __init__(self):
#         super().__init__()
#         self.rule_map = {"root": [(r"\d+", ckit.Token_Number), (None, ckit.Token_Text)]}
# @endcode
#
# \~
class RegexLexer(Lexer):
    Detail = 1 << 0  # Rules used only in detail mode.

    ## \~japanese
    # 引数なしで構築します。Lexer基底は分析を実装せず、RegexLexerは空のrule_mapで開始します。
    # \~english
    # Construct without arguments; the Lexer base has no analysis implementation and RegexLexer starts with an empty rule_map.
    # \~
    def __init__(self):
        Lexer.__init__(self)
        self.rule_map = {}
        self.rule_map_ctx = {}
        self.re_flags = 0
        self.compiled = False

    def _compile(self):
        for k in self.rule_map.keys():  # noqa: SIM118  # Support mappings exposing keys and item access without iteration.
            rule_list = self.rule_map[k]
            for i in range(len(rule_list)):
                rule = rule_list[i]
                rule = list(rule)
                if len(rule) <= 2:
                    rule.append(None)
                if len(rule) <= 3:
                    rule.append(0)
                if rule[0] is not None:
                    rule[0] = re.compile(rule[0], self.re_flags)
                rule_list[i] = rule

                assert not (isinstance(rule[2], tuple) or isinstance(rule[2], list))  # noqa: SIM101  # Retain short-circuit evaluation; excluded from cleanup for performance.

                if rule[0] is None or (rule[3] & RegexLexer.Detail) == 0:
                    if k not in self.rule_map_ctx:
                        self.rule_map_ctx[k] = []
                    self.rule_map_ctx[k].append(rule)

        self.compiled = True

    ## \~japanese
    # rule_mapで行を分析します。detail=Trueは(境界列, 次行ctx)、Falseは次行ctxです。
    # @sa RegexLexer
    # \~english
    # Lex a line with rule_map; return (boundaries, next_ctx) for detail=True, otherwise next_ctx.
    # @sa RegexLexer
    # \~
    def lex(self, ctx, line, detail):
        if not self.compiled:
            self._compile()

        if lexer_debug:
            print("line :", line)

        tokens = []
        pos = 0

        def getRuleList():
            if detail:
                return self.rule_map[ctx]
            else:
                return self.rule_map_ctx[ctx]

        rule_list = getRuleList()

        while pos <= len(line):
            if lexer_debug:
                print("  context :", ctx)

            last = pos == len(line)

            nearest_match = None
            default_rule = None

            for rule in rule_list:
                if rule[0] is not None:
                    re_result = rule[0].search(line, pos)
                    if re_result and (
                        nearest_match is None
                        or re_result.start() < nearest_match[1].start()
                    ):
                        nearest_match = rule, re_result
                        if re_result.start() == pos:
                            break
                else:
                    default_rule = rule
                    break

            else:
                if pos < len(line):
                    tokens.append((pos, Token_Error))
                break

            if lexer_debug:
                print("  nearest_rule :", nearest_match[0] if nearest_match is not None else None)
                print("  default_rule :", default_rule)

            if (
                default_rule
                and (len(tokens) == 0 or tokens[-1][1] != default_rule[1])
                and pos < len(line)
            ):
                if lexer_debug:
                    print("  %d, %d (default rule)" % (pos, default_rule[1]))  # noqa: UP031  # Preserve percent-d conversion for public values.
                tokens.append((pos, default_rule[1]))

            if nearest_match is not None:
                rule, nearest_result = nearest_match
                pos = nearest_result.start()

                if isinstance(rule[1], tuple) or isinstance(rule[1], list):  # noqa: SIM101  # Retain short-circuit evaluation; excluded from cleanup for performance.
                    action_list = rule[1]
                    for i in range(len(action_list)):
                        if (len(tokens) == 0 or tokens[-1][1] != action_list[i]) and pos < len(line):
                            if lexer_debug:
                                print(
                                    "  %d, %d (group %d)" % (pos, action_list[i], i)  # noqa: UP031  # Preserve percent-d conversion for public values.
                                )
                            tokens.append((pos, action_list[i]))
                        pos += len(nearest_result.group(i + 1))

                else:
                    if (len(tokens) == 0 or tokens[-1][1] != rule[1]) and pos < len(line):
                        if lexer_debug:
                            print("  %d, %d" % (pos, rule[1]))  # noqa: UP031  # Preserve percent-d conversion for public values.
                        tokens.append((pos, rule[1]))
                    pos += len(nearest_result.group(0))

            if rule[2]:
                ctx = rule[2]
                rule_list = getRuleList()
                if lexer_debug:
                    print("  context ->", ctx)

            if default_rule and nearest_match is None:
                break

            if last:
                break

        if detail:
            return tokens, ctx
        else:
            return ctx


# --------------------------------------------------------------------


## \~japanese
# TextWidget補完の結果。itemsは空でない候補文字列リスト、selectionは0始まりの初期選択番号、left/rightは置換するPoint範囲です。
# 候補がなければCompletion側でNoneを返せます。各属性はコピーせず保持します。
# \~english
# TextWidget completion result. items contains candidate strings; selection is the zero-based initial selection; left/right are replacement Points.
# The provider may return None for no candidates. Attributes retain supplied objects without copying.
# \~
class CompletionResult:
    ## \~japanese
    # CompletionResultを構築します。引数と前提はクラス説明を参照してください。
    # \~english
    # Construct CompletionResult; see the class description for arguments and preconditions.
    # \~
    def __init__(self, items, selection, left, right):
        self.items = items
        self.selection = selection
        self.left = left
        self.right = right


## \~japanese
# TextWidget用補完の基底クラス。Mode.completionへ設定します。
# getCandidateList(window, edit, point)はUIスレッドで呼ばれ、CompletionResultまたはNoneを返します。基底実装はNoneです。
# \~english
# Base completion provider assigned to Mode.completion.
# getCandidateList(window, edit, point) runs on the UI thread and returns CompletionResult or None; the base returns None.
# \~
class Completion:
    ## \~japanese
    # Completionを構築します。引数と前提はクラス説明を参照してください。
    # \~english
    # Construct Completion; see the class description for arguments and preconditions.
    # \~
    def __init__(self):
        pass

    ## \~japanese
    # 補完要求を処理します。基底はNoneを返します。派生実装はCompletionResultまたはNoneを返してください。
    # \~english
    # Handle a completion request; the base returns None. Implementations return CompletionResult or None.
    # \~
    def getCandidateList(self, window, edit, point):
        return None


## \~japanese
# 親window.edit_listのTextWidget群からASCIIの英数字・下線の単語を収集します。親がedit_listを用意する必要があります。
# カーソルは単語末尾に置きます。10000行超の文書と1000文字超の行は走査せず、重複除去・整列した候補を返します。
# \~english
# Collect ASCII alphanumeric/underscore words from TextWidgets in parent window.edit_list; the host must provide that attribute.
# The caret must be at a word end. Skip documents over 10000 lines and lines over 1000 characters; return sorted unique candidates.
# \~
class WordCompletion(Completion):
    ## \~japanese
    # WordCompletionを構築します。引数と前提はクラス説明を参照してください。
    # \~english
    # Construct WordCompletion; see the class description for arguments and preconditions.
    # \~
    def __init__(self):
        Completion.__init__(self)

    ## \~japanese
    # window.edit_listから候補を集めます。対象外の位置ならNone、そうでなければCompletionResult（候補が空の場合もある）を返します。
    # \~english
    # Collect candidates from window.edit_list. Return None for ineligible positions, otherwise CompletionResult (possibly with no items).
    # \~
    def getCandidateList(self, window, edit, point):
        word_left = point.wordLeft()
        word_right = point.wordRight()
        hint = edit.getText(word_left, point)
        tail = edit.getText(point, word_right)

        if not re.fullmatch("[a-zA-Z0-9_]+", hint):
            return None

        # Do not complete when the caret is inside a word.
        if re.match("[a-zA-Z0-9_]+", tail):
            return None

        items = set()

        re_patern = re.compile("\\b" + hint + "[a-zA-Z0-9_]+")

        for other_edit in window.edit_list:
            # Skip files with too many lines to limit completion work.
            if len(other_edit.doc.lines) > 10000:
                continue

            for line in other_edit.doc.lines:
                s = line.s

                # Skip overly long lines to limit completion work.
                if len(s) > 1000:
                    continue

                pos = 0
                while pos < len(s):
                    re_result = re_patern.search(s, pos)
                    if re_result:
                        items.add(re_result.group(0))
                        pos += 1
                    else:
                        break

        items = list(items)
        items.sort()

        return CompletionResult(items, 0, word_left, point)


# --------------------------------------------------------------------


## \~japanese
# TextWidget の動作モードのベースクラス
#
# 主モードはlexerとcompletionを持つ派生クラスを使います。通常はTextMode()を使い、Document.setModeで接続します。
# nameは表示名、tab_widthは正のセル数、tab_by_spaceはTabを空白にするか、wordbreakとbracketは単語・括弧移動の規則です。
# show_tab/show_space/show_wspace/show_lineend/show_fileendは表示フラグです。copy_line_if_not_selectedは無選択時のCopyとCutの両方に使われます。
# cut_line_if_not_selectedは定義だけで参照されず、cancel_selection_on_copyはCopy後の選択解除です。
# configure(edit)はedit.keymap等を設定します。TextWidget.configureで主モード→追加順の副モードに適用します。
# staticconfigure(window)は所有者が明示的に呼ぶフックで、DocumentやTextWidgetの構築では呼びません。
#
# \~english
# Base class for TextWidget editing modes
#
# A major mode subclass must supply lexer and completion; normally use TextMode() and attach it with Document.setMode.
# name is the display name; tab_width is a positive cell count; tab_by_space inserts spaces for Tab; wordbreak/bracket control word/bracket motion.
# show_tab/show_space/show_wspace/show_lineend/show_fileend control display. copy_line_if_not_selected governs both unselected Copy and Cut.
# cut_line_if_not_selected is defined but unused; cancel_selection_on_copy clears selection after Copy.
# configure(edit) sets edit.keymap and related options: TextWidget.configure applies the major mode then minor modes in insertion order.
# staticconfigure(window) is explicitly called by the host, not by Document or TextWidget construction.
#
# \~
class Mode:
    name = "-"

    tab_by_space = False
    tab_width = 4

    show_tab = True
    show_space = False
    show_wspace = True
    show_lineend = True
    show_fileend = True

    cancel_selection_on_copy = False
    copy_line_if_not_selected = True
    cut_line_if_not_selected = True

    wordbreak = ckit_misc.WordBreak(
        (
            "\"!@#$%^&*()+|~-=\\`[]{};:',./<>?",  # 0
            ckit_misc.UnicodeRange("0", "z"),  # 1
            ckit_misc.UnicodeRange("、", "〟"),  # 2
            ckit_misc.UnicodeRange("ぁ", "ゖ"),  # 3
            " \t",  # 4
        ),
        {
            -1: [0, 1, 2],
            0: [-1, 1, 2, 3],
            1: [-1, 0, 2, 3],
            2: [-1, 0, 1, 3],
            3: [-1, 0, 1, 2],
            4: [-1, 0, 1, 2, 3],
        },
    )

    bracket = (
        "{}",
        "()",
        "[]",
        "<>",
    )

    ## \~japanese
    # Modeを構築します。引数と前提はクラス説明を参照してください。
    # \~english
    # Construct Mode; see the class description for arguments and preconditions.
    # \~
    def __init__(self):
        pass

    def __str__(self):
        return self.name

    ## \~japanese
    # command_<name>(info)があれば呼びTrue、なければFalse。ハンドラの戻り値は使わず、実行例外は伝播します。
    # \~english
    # Call command_<name>(info) and return True if present, else False. Ignore its return value; execution errors propagate.
    # \~
    def executeCommand(self, name, info):
        try:
            command = getattr(self, "command_" + name)
        except AttributeError:
            return False

        command(info)
        return True

    ## \~japanese
    # command_を除いたコマンド名をyieldします。
    # \~english
    # Yield command names without the command_ prefix.
    # \~
    def enumCommand(self):
        for attr in dir(self):
            if attr.startswith("command_"):
                yield attr[len("command_") :]

    ## \~japanese
    # 所有者から明示的に呼ぶ静的設定フック。基底は何もせずNoneを返します。
    # \~english
    # Explicit host-level static configuration hook; the base does nothing and returns None.
    # \~
    @staticmethod
    def staticconfigure(window):
        pass

    ## \~japanese
    # TextWidget.configureから呼ぶインスタンス設定フック。基底は何もせずNoneを返します。
    # \~english
    # Instance hook called by TextWidget.configure; the base does nothing and returns None.
    # \~
    def configure(self, edit):
        pass


## \~japanese
# lexer=TextLexer()、completion=WordCompletion()の標準主モードです。
# staticconfigureはcustom.pyのstaticconfigure_TextMode(window)、configureはconfigure_TextMode(mode, edit)を呼びます。
# \~english
# Default major mode with lexer=TextLexer() and completion=WordCompletion().
# staticconfigure invokes custom.py staticconfigure_TextMode(window); configure invokes configure_TextMode(mode, edit).
# \~
class TextMode(Mode):
    name = "text"

    ## \~japanese
    # TextModeを構築します。引数と前提はクラス説明を参照してください。
    # \~english
    # Construct TextMode; see the class description for arguments and preconditions.
    # \~
    def __init__(self):
        Mode.__init__(self)
        self.lexer = TextLexer()
        self.completion = WordCompletion()

    ## \~japanese
    # staticconfigure_TextMode(window)設定フックを呼びます。戻り値None。
    # \~english
    # Invoke the staticconfigure_TextMode(window) configuration hook. Return None.
    # \~
    @staticmethod
    def staticconfigure(window):
        Mode.staticconfigure(window)
        ckit_userconfig.callConfigFunc("staticconfigure_TextMode", window)

    ## \~japanese
    # configure_TextMode(self, edit)設定フックを呼びます。戻り値None。
    # \~english
    # Invoke the configure_TextMode(self, edit) configuration hook. Return None.
    # \~
    def configure(self, edit):
        Mode.configure(self, edit)
        ckit_userconfig.callConfigFunc("configure_TextMode", self, edit)


# --------------------------------------------------------------------


class UndoInfo:
    def __init__(self):
        self.old_text: str | None = None
        self.old_text_left = None
        self.old_text_right: Point | None = None
        self.old_anchor = None
        self.old_cursor = None

        self.new_text: str | None = None
        self.new_text_left = None
        self.new_text_right: Point | None = None
        self.new_anchor = None
        self.new_cursor = None

    def __str__(self):
        return "UndoInfo( %s,%s,  %s,%s )" % (  # noqa: UP031  # Preserve percent-s conversion for public values.
            self.old_text_left,
            self.old_text_right,
            self.new_text_left,
            self.new_text_right,
        )


class AtomicUndoInfo:
    def __init__(self):
        self.old_anchor = None
        self.old_cursor = None
        self.new_anchor = None
        self.new_cursor = None
        self.items = []

    def __str__(self):
        return "AtomicUndoInfo( %s,%s,  %s,%s )" % (  # noqa: UP031  # Preserve percent-s conversion for public values.
            self.old_anchor,
            self.old_cursor,
            self.new_anchor,
            self.new_cursor,
        )


## \~japanese
# TextWidget の文書中の位置を示すクラス
#
# editは所属TextWidget、lineは0始まり行番号、indexは改行を除くPython文字列の0始まり位置です。表示セル数ではありません。
# copy・移動メソッドは元を変えず新しいPointを返します。比較は行・文字位置だけを使い、所属文書を検証しません。
# 構築時の範囲補正はありません。同じ文書の有効な位置を使い、編集前のPointを編集後にそのまま再利用しないでください。
# 上下移動はedit.ideal_columnを目標セル位置として使います。block_mode=Trueなら行末を越える位置を許します。
#
# \~english
# A position in a TextWidget document
#
# edit is the owning TextWidget; line is a zero-based line number; index is a zero-based Python string position excluding the line ending, not a display column.
# copy and movement methods return new Points without changing the source. Comparisons use line/index only and do not validate document ownership.
# Construction does not clamp positions. Use valid positions in the same document and reacquire them after editing.
# Vertical movement targets edit.ideal_column in display cells. block_mode=True allows positions beyond line ends.
#
# \~
class Point:
    ## \~japanese
    # Pointを構築します。引数と前提はクラス説明を参照してください。
    # \~english
    # Construct Point; see the class description for arguments and preconditions.
    # \~
    def __init__(self, edit, line=0, index=0):
        self.edit = edit
        self.line = line
        self.index = index

    ## \~japanese
    # 同じedit・line・indexを持つ新しいPointを返します。
    # \~english
    # Return a new Point with the same edit, line and index.
    # \~
    def copy(self):
        return Point(self.edit, self.line, self.index)

    def __eq__(self, other):
        return (
            isinstance(other, Point)
            and self.line == other.line
            and self.index == other.index
        )

    def __ne__(self, other):
        return (
            not isinstance(other, Point)
            or self.line != other.line
            or self.index != other.index
        )

    def __gt__(self, other):
        if self.line > other.line:
            return True
        if self.line < other.line:
            return False
        return self.index > other.index

    def __ge__(self, other):
        if self.line > other.line:
            return True
        if self.line < other.line:
            return False
        return self.index >= other.index

    def __lt__(self, other):
        if self.line < other.line:
            return True
        if self.line > other.line:
            return False
        return self.index < other.index

    def __le__(self, other):
        if self.line < other.line:
            return True
        if self.line > other.line:
            return False
        return self.index <= other.index

    def __str__(self):
        return "Point(%d,%d)" % (self.line, self.index)  # noqa: UP031  # Preserve percent-d conversion for public values.

    def __repr__(self):
        return "Point(%d,%d)" % (self.line, self.index)  # noqa: UP031  # Preserve percent-d conversion for public values.

    ## \~japanese
    # 1文字左のPoint。通常は行をまたぎ、block_mode=Trueなら行をまたぎません。
    # \~english
    # Return a Point one character left; cross line boundaries unless block_mode=True.
    # \~
    def left(self, block_mode=False):
        point = self.copy()
        if point.index > 0:
            point.index -= 1
        else:
            if not block_mode and point.line > 0:
                point.line -= 1
                point.index = len(self.edit.doc.lines[point.line].s)
        return point

    ## \~japanese
    # 1文字右のPoint。通常は行をまたぎ、block_mode=Trueなら同じ行の末尾を越えられます。
    # \~english
    # Return a Point one character right; normally cross lines, but block_mode=True permits virtual positions on the same line.
    # \~
    def right(self, block_mode=False):
        point = self.copy()
        if block_mode or point.index < len(self.edit.doc.lines[point.line].s):
            point.index += 1
        else:
            if point.line < len(self.edit.doc.lines) - 1:
                point.line += 1
                point.index = 0
        return point

    ## \~japanese
    # wordbreakを使った左の単語境界のPointを返します。use_type_boundsは文字種境界を使うかです。
    # \~english
    # Return a Point at the left word boundary using wordbreak; use_type_bounds controls character-type boundaries.
    # \~
    def wordLeft(self, use_type_bounds=True):
        point = self.copy()
        if point.index > 0:
            line = self.edit.doc.lines[point.line]
            point.index = self.edit.doc.mode.wordbreak(
                line.s, point.index, -1, use_type_bounds=use_type_bounds
            )
        else:
            if point.line > 0:
                point.line -= 1
                line = self.edit.doc.lines[point.line]
                point.index = self.edit.doc.mode.wordbreak(
                    line.s, len(line.s), -1, use_type_bounds=use_type_bounds
                )
        return point

    ## \~japanese
    # wordbreakを使った右の単語境界のPointを返します。use_type_boundsは文字種境界を使うかです。
    # \~english
    # Return a Point at the right word boundary using wordbreak; use_type_bounds controls character-type boundaries.
    # \~
    def wordRight(self, use_type_bounds=True):
        point = self.copy()
        if point.index < len(self.edit.doc.lines[point.line].s):
            line = self.edit.doc.lines[point.line]
            point.index = self.edit.doc.mode.wordbreak(
                line.s, point.index, +1, use_type_bounds=use_type_bounds
            )
        else:
            if point.line < len(self.edit.doc.lines) - 1:
                point.line += 1
                line = self.edit.doc.lines[point.line]
                point.index = self.edit.doc.mode.wordbreak(
                    line.s, 0, +1, use_type_bounds=use_type_bounds
                )
        return point

    ## \~japanese
    # 前のtab_widthセル境界に対応するPointを返します。行は変えません。
    # \~english
    # Return a Point at the previous tab_width cell boundary on this line.
    # \~
    def tabLeft(self):
        point = self.copy()
        tab_width = self.edit.doc.mode.tab_width
        column = self.edit.getColumnFromIndex(point.line, point.index)
        column = max((column - 1) // tab_width * tab_width, 0)
        point.index = self.edit.getIndexFromColumn(point.line, column)
        return point

    ## \~japanese
    # step行上へ移動したPoint。理想カラムを使い、文書先頭を越えると(0,0)です。
    # \~english
    # Return a Point step lines up using the ideal column; past the beginning return (0,0).
    # \~
    def up(self, step=1, block_mode=False):
        point = self.copy()
        if point.line - step >= 0:
            point.line -= step
            point.index = self.edit.getIndexFromColumn(
                point.line, self.edit.ideal_column, block_mode=block_mode
            )
        else:
            point.line = 0
            point.index = 0
        return point

    ## \~japanese
    # step行下へ移動したPoint。理想カラムを使い、文書末尾を越えると末尾です。
    # \~english
    # Return a Point step lines down using the ideal column; past the end return the document end.
    # \~
    def down(self, step=1, block_mode=False):
        point = self.copy()
        if point.line + step <= len(self.edit.doc.lines) - 1:
            point.line += step
            point.index = self.edit.getIndexFromColumn(
                point.line, self.edit.ideal_column, block_mode=block_mode
            )
        else:
            point.line = len(self.edit.doc.lines) - 1
            point.index = len(self.edit.doc.lines[point.line].s)
        return point

    ## \~japanese
    # 現在行の文字位置0のPointを返します。
    # \~english
    # Return a Point at index zero of this line.
    # \~
    def lineBegin(self):
        point = self.copy()
        point.index = 0
        return point

    ## \~japanese
    # 現在行の改行直前のPointを返します。
    # \~english
    # Return a Point immediately before this line's ending.
    # \~
    def lineEnd(self):
        point = self.copy()
        point.index = len(self.edit.doc.lines[point.line].s)
        return point

    ## \~japanese
    # 先頭の空白・タブを除いた最初の位置を返します。空白のみなら行末です。
    # \~english
    # Return a Point after leading spaces/tabs, or the line end for whitespace-only text.
    # \~
    def lineFirstGraph(self):
        point = self.copy()
        s = self.edit.doc.lines[point.line].s
        s2 = s.lstrip(" \t")
        point.index = len(s) - len(s2)
        return point

    ## \~japanese
    # 2文字の括弧対シーケンスを使い対応位置を返します。字句種別は無視し、1000行を超える走査や未発見では元のコピーです。
    # \~english
    # Return a corresponding position using a sequence of two-character bracket pairs; ignore syntax types. Return a source copy if not found or scanning exceeds 1000 lines.
    # \~
    def correspondingBracket(self, bracket_pair_list):
        point = self.copy()

        s = self.edit.doc.lines[point.line].s

        for bracket_pair in bracket_pair_list:
            if point.index < len(s) and bracket_pair[0] == s[point.index]:
                step = 1
                depth = 1
                inside = False
                point = point.right()
                break
            elif point.index < len(s) and bracket_pair[1] == s[point.index]:
                step = -1
                depth = 1
                inside = True
                break
            elif point.index > 0 and bracket_pair[0] == s[point.index - 1]:
                step = 1
                depth = 1
                inside = True
                break
            elif point.index > 0 and bracket_pair[1] == s[point.index - 1]:
                step = -1
                depth = 1
                inside = False
                point = point.left()
                break
        else:
            return point

        num_checked_lines = 0

        while True:
            s = self.edit.doc.lines[point.line].s

            if step > 0:
                pos1 = s.find(bracket_pair[0], point.index)
                pos2 = s.find(bracket_pair[1], point.index)
            else:
                pos1 = s.rfind(bracket_pair[0], 0, point.index)
                pos2 = s.rfind(bracket_pair[1], 0, point.index)

            if pos1 >= 0 and (pos2 < 0 or int(math.copysign(1, pos2 - pos1)) == step):
                depth += step
                point.index = pos1
            elif pos2 >= 0 and (pos1 < 0 or int(math.copysign(1, pos1 - pos2)) == step):
                depth -= step
                point.index = pos2
            else:
                if step > 0:
                    point = point.lineEnd()
                else:
                    point = point.lineBegin()

                # Give up after checking more than 1,000 lines.
                num_checked_lines += 1
                if num_checked_lines > 1000:
                    # No limit notification: ReCraftLaunch does not use TextWidget.
                    return self.copy()

            if depth <= 0:
                break

            if step > 0:
                new_point = point.right()
            else:
                new_point = point.left()

            # Reached the end of the document in the search direction.
            if new_point == point:
                return self.copy()

            point = new_point

        if (step > 0 and not inside) or (step < 0 and inside):
            point = point.right()

        return point


## \~japanese
# TextWidget の選択範囲を示すクラス
#
# 通常はedit.selectionを使います。コンストラクターのdoc引数はDocumentではなくpointDocumentBegin()を持つTextWidgetです。
# left/rightは昇順の両端、anchorは固定端、cursorは移動端のPointコピーを返します。directionは同位置0、順方向1、逆方向-1です。
# block_modeは矩形選択。直接のsetSelection/setBlockModeは描画・通知を行わないため、通常はTextWidget.setSelectionを使います。
#
# \~english
# A selection in a TextWidget document
#
# Normally use edit.selection. The constructor argument named doc is a TextWidget exposing pointDocumentBegin(), not a Document.
# left/right return ordered endpoint copies; anchor is the fixed endpoint and cursor the moving endpoint. direction is 0 for equal, 1 forward, -1 backward.
# block_mode selects a rectangle. Direct setters do not paint/notify; normally call TextWidget.setSelection.
#
# \~
class Selection:
    ## \~japanese
    # Selectionを構築します。引数と前提はクラス説明を参照してください。
    # \~english
    # Construct Selection; see the class description for arguments and preconditions.
    # \~
    def __init__(self, doc):
        self.pos = [doc.pointDocumentBegin(), doc.pointDocumentBegin()]
        self.direction = 0
        self.block_mode = False

    ## \~japanese
    # 昇順左端のPointコピーを返します。
    # \~english
    # Return a copy of the ordered left endpoint.
    # \~
    def left(self):
        return self.pos[0].copy()

    ## \~japanese
    # 昇順右端のPointコピーを返します。
    # \~english
    # Return a copy of the ordered right endpoint.
    # \~
    def right(self):
        return self.pos[1].copy()

    ## \~japanese
    # 移動端のPointコピーを返します。
    # \~english
    # Return a copy of the moving endpoint.
    # \~
    def cursor(self):
        if self.direction == 1:
            return self.pos[1].copy()
        else:
            return self.pos[0].copy()

    ## \~japanese
    # 固定端のPointコピーを返します。
    # \~english
    # Return a copy of the fixed endpoint.
    # \~
    def anchor(self):
        if self.direction == 1:
            return self.pos[0].copy()
        else:
            return self.pos[1].copy()

    ## \~japanese
    # anchor/cursorをコピーして順序とdirectionを更新します。通知・描画はしません。
    # \~english
    # Copy anchor/cursor and update ordering/direction without notifying or painting.
    # \~
    def setSelection(self, anchor, cursor):
        anchor = anchor.copy()
        cursor = cursor.copy()

        if anchor == cursor:
            self.direction = 0
            self.pos = [anchor, cursor]
        elif anchor < cursor:
            self.direction = 1
            self.pos = [anchor, cursor]
        else:
            self.direction = -1
            self.pos = [cursor, anchor]

    ## \~japanese
    # 矩形選択フラグだけを設定します。
    # \~english
    # Set only the rectangular-selection flag.
    # \~
    def setBlockMode(self, block_mode):
        self.block_mode = block_mode


## \~japanese
# TextWidget の文書を示すクラス
#
# filenameはパスまたはNone。存在するファイルはバイナリで読込み、存在しないパスは空文書の名前として保持します。
# modeはlexerを持つ主モード、encodingはTextEncodingまたはNone（自動検出）です。新規文書はUTF-8・CRLF・空行1行です。
# 既存ファイルが100000行超または10MiB超なら主モードをTextModeへ切り替えます。I/O・復号方式の例外は伝播します。
# linesはネイティブLineのリスト（sは本文、endは改行）、encoding/lineend/filename/readonlyは文書状態です。
# modcountは保存状態からの編集回数、Noneは回数で復元を判定できない状態。undo_list/redo_list/atomic_undoは内部編集履歴です。
# text_modified_handler_listは(sender, left, old_right, new_right)、bookmark_handler_listは(sender, line, bookmark)を
# 変更を起こしたUIスレッドで呼びます。戻り値は使わず、例外は伝播します。独自登録は所有者が解除してください。
# readFile/writeFileは通知・画面再設定・保存済みフラグ更新を自動実行しません。複数TextWidgetで文書を共有できます。
#
# \~english
# A TextWidget document
#
# filename is a path or None. Existing files are read in binary mode; a nonexistent path is retained as the empty document name.
# mode is a major mode with a lexer; encoding is TextEncoding or None for detection. New documents contain one empty line, UTF-8 and CRLF.
# Existing files over 100000 lines or 10 MiB switch to TextMode. I/O and encoding errors propagate.
# lines is a list of native Lines (s is body, end is line ending); encoding/lineend/filename/readonly hold document state.
# modcount counts edits relative to the saved state; None means the count cannot determine restoration. undo_list/redo_list/atomic_undo are internal history.
# text_modified_handler_list callbacks take (sender, left, old_right, new_right); bookmark_handler_list takes (sender, line, bookmark).
# They run on the modifying UI thread; return values are ignored and exceptions propagate. Remove callbacks you register.
# readFile/writeFile do not automatically notify, reconfigure views or mark the document saved. Multiple TextWidgets can share a document.
#
# \~
class Document:
    ## \~japanese
    # Documentを構築します。引数と前提はクラス説明を参照してください。
    # \~english
    # Construct Document; see the class description for arguments and preconditions.
    # \~
    def __init__(self, filename, mode, encoding=None):
        if filename:
            filename = ckit_misc.normPath(filename)

        self.lines = [Line("")]
        self.encoding = ckit_misc.TextEncoding("utf-8")
        self.lineend = DEFAULT_LINEEND
        self.filename = filename
        self.timestamp = None
        self.readonly = False
        self.bg_color_name = None
        self.diff_mode = False

        self.undo_list = []
        self.redo_list = []
        self.atomic_undo: AtomicUndoInfo | None = None
        self.modcount: int | None = 0

        # Handlers that notify all attached TextWidgets of document changes.
        self.text_modified_handler_list = []
        self.bookmark_handler_list = []

        self.lex_ctx_dirty_top = 0
        self.lex_token_dirty_top = 0
        self.minor_mode_list = []

        if filename and os.path.exists(filename):
            with open(filename, "rb") as fd:
                self.readFile(fd, encoding)

                if (
                    ckit_misc.getFileAttribute(filename)
                    & ckit_misc.FILE_ATTRIBUTE_READONLY
                ):
                    self.setReadOnly(True)

                # Use TextMode for files exceeding 100,000 lines or 10 MiB.
                fd.seek(0, os.SEEK_END)
                file_size = fd.tell()
                if len(self.lines) > 100000 or file_size > 10 * 1024 * 1024:
                    # No mode-switch notification: ReCraftLaunch does not use TextWidget.
                    mode = TextMode()

        self.setMode(mode)

        self.clearFileModified()

    ## \~japanese
    # ファイルの末尾名、無名ならuntitledを返します。
    # \~english
    # Return the basename, or untitled for an unnamed document.
    # \~
    def getName(self):
        if self.filename:
            return os.path.basename(self.filename)
        else:
            return "untitled"

    ## \~japanese
    # 保持するパスまたはNoneを返します。
    # \~english
    # Return the retained path or None.
    # \~
    def getFullpath(self):
        return self.filename

    ## \~japanese
    # modcountが0でないかNoneならTrueです。
    # \~english
    # Return True when modcount is nonzero or None.
    # \~
    def isModified(self):
        return self.modcount is None or self.modcount != 0

    ## \~japanese
    # 全行のmodifiedをFalse、modcountを0にします。Undoは消しません。
    # \~english
    # Clear each line's modified flag and reset modcount to zero without deleting undo.
    # \~
    def clearModified(self):
        for line in self.lines:
            line.modified = False
        self.modcount = 0

    ## \~japanese
    # 保存したmtimeとの違いを返します。無名・stat失敗時はFalseです。
    # \~english
    # Compare mtime with the recorded value; return False for unnamed files or stat failures.
    # \~
    def isFileModified(self):
        if not self.filename:
            return False
        try:
            timestamp = os.stat(self.filename).st_mtime
        except OSError:
            return False
        return self.timestamp != timestamp

    ## \~japanese
    # 現在のmtimeを記録します。stat失敗時はNone、無名なら何もしません。
    # \~english
    # Record current mtime, or None on stat failure; do nothing for unnamed documents.
    # \~
    def clearFileModified(self):
        if self.filename:
            try:
                self.timestamp = os.stat(self.filename).st_mtime
            except OSError:
                self.timestamp = None

    ## \~japanese
    # mode/lexerを置換し全行の構文キャッシュを無効化します。TextWidget.configureは別途必要です。
    # \~english
    # Replace mode/lexer and invalidate syntax caches on every line; call TextWidget.configure separately.
    # \~
    def setMode(self, mode):
        self.mode = mode
        self.lexer = mode.lexer

        for line in self.lines:
            line.ctx = None
            line.tokens = None
        self.lex_ctx_dirty_top = 0
        self.lex_token_dirty_top = 0

    ## \~japanese
    # 副モードを末尾へ追加します。キーの再設定は別途configureで行います。
    # \~english
    # Append a minor mode; call configure separately to reapply key settings.
    # \~
    def appendMinorMode(self, mode):
        self.minor_mode_list.append(mode)

    ## \~japanese
    # nameが一致する最初の副モードを削除します。なければValueError(name)。
    # \~english
    # Remove the first minor mode with this name; raise ValueError(name) when absent.
    # \~
    def removeMinorMode(self, name):
        for mode in self.minor_mode_list:
            if mode.name == name:
                self.minor_mode_list.remove(mode)
                return
        raise ValueError(name)

    ## \~japanese
    # 全副モードを解除します。キーの再設定は行いません。
    # \~english
    # Remove all minor modes without reconfiguring keys.
    # \~
    def clearMinorMode(self):
        self.minor_mode_list.clear()

    ## \~japanese
    # nameに一致する副モードがあればTrue。
    # \~english
    # Return True if a minor mode has this name.
    # \~
    def hasMinorMode(self, name):
        for mode in self.minor_mode_list:
            if mode.name == name:
                return True
        return False

    ## \~japanese
    # 読取専用フラグを設定します。真なら背景名readonly_bgを設定しますが、偽へ戻す際は背景を復元しません。
    # \~english
    # Set the read-only flag; true sets background name readonly_bg, but false does not restore the previous background.
    # \~
    def setReadOnly(self, readonly):
        self.readonly = readonly
        if self.readonly:
            self.setBGColor("readonly_bg")

    ## \~japanese
    # 背景色名またはNoneを保存します。再描画はしません。
    # \~english
    # Store a background color name or None without repainting.
    # \~
    def setBGColor(self, bg_color_name):
        self.bg_color_name = bg_color_name

    ## \~japanese
    # seek/read可能なバイナリfdを先頭から全読込みし、行・Undo/Redo・変更回数を置換します。
    # encoding=Noneは自動検出。BOMを除き、復号不能文字は置換し、検出不能ならUnicodeErrorです。
    # 最初の行の改行を既定に使い、なければCRLFです。fdは閉じず、失敗時の状態復元・通知も行いません。
    # \~english
    # Read a seekable binary fd from the beginning and replace lines, undo/redo and modification count.
    # encoding=None detects encoding. Strip detected BOM, replace undecodable characters; raise UnicodeError for undetected encoding.
    # Use the first line's ending or CRLF by default. Do not close fd, roll back on failure or notify views.
    # \~
    def readFile(self, fd, encoding=None):
        self.lines = []

        self.undo_list = []
        self.redo_list = []
        self.modcount = 0

        fd.seek(0, os.SEEK_SET)
        data = fd.read()

        detected_encoding = ckit_misc.detectTextEncoding(data, ascii_as="utf-8")

        if detected_encoding.bom:
            data = data[len(detected_encoding.bom) :]

        if not encoding:
            encoding = detected_encoding

        if encoding.encoding:
            data = data.decode(encoding=encoding.encoding, errors="replace")

            # Convert wave dash to fullwidth tilde.
            if encoding.encoding == "cp932":
                data = data.replace("\u301c", "\uff5e")

            self.encoding = encoding
        else:
            raise UnicodeError

        lines = data.splitlines(True)
        self.lines = [Line(line) for line in lines]

        # Append an empty final line if the document is empty or ends with a line break.
        if len(self.lines) == 0 or self.lines[-1].end:
            self.lines.append(Line(""))

        if len(self.lines) > 0 and self.lines[0].end:
            self.lineend = self.lines[0].end
        else:
            self.lineend = DEFAULT_LINEEND

        self.lex_ctx_dirty_top = 0
        self.lex_token_dirty_top = 0

    ## \~japanese
    # バイナリfdへ現在の位置からBOMと全行を現在のencodingで書きます。符号化不能文字は置換します。
    # seek/truncate/close、mtime更新、clearModifiedは行いません。ファイル名やreadonlyも参照しません。
    # \~english
    # Write BOM and all lines at the current binary fd position using encoding and replacement for unencodable characters.
    # Do not seek, truncate, close, update mtime or clearModified; filename and readonly are not consulted.
    # \~
    def writeFile(self, fd):
        if self.encoding.bom:
            fd.write(self.encoding.bom)

        for line in self.lines:
            s = line.s

            # Convert fullwidth tilde to wave dash.
            if self.encoding.encoding == "cp932":
                s = s.replace("\uff5e", "\u301c")

            s = s.encode(self.encoding.encoding, "replace")
            fd.write(s)
            end = line.end.encode(self.encoding.encoding)
            fd.write(end)

    ## \~japanese
    # dirty位置からstop（0始まり・除外）まで行頭文脈を更新します。Noneは文書末尾。max_lexは今回の分析行数上限です。
    # \~english
    # Update starting contexts from the dirty position up to exclusive zero-based stop (None means end); max_lex limits analyzed lines.
    # \~
    def updateSyntaxContext(self, stop=None, max_lex=None):

        if stop is None:
            stop = len(self.lines)
        else:
            stop = min(stop, len(self.lines))

        if max_lex is None:
            max_lex = len(self.lines)

        if self.lex_ctx_dirty_top is None or self.lex_ctx_dirty_top >= stop:
            return

        start = self.lex_ctx_dirty_top
        line = start
        num_lex = 0
        prev_line_dirty = self.lines[line].ctx is None

        while True:
            if self.lines[line].ctx is None or prev_line_dirty:
                if line == 0:
                    ctx = rootContext()
                else:
                    prev_line = self.lines[line - 1]
                    ctx = self.lexer.lex(prev_line.ctx, prev_line.s, False)

                if self.lines[line].ctx != ctx:
                    self.lines[line].ctx = ctx
                    self.lines[line].tokens = None
                    prev_line_dirty = True
                else:
                    prev_line_dirty = False

                num_lex += 1

            line += 1

            if line >= stop or num_lex >= max_lex:
                break

        if line < len(self.lines):
            if prev_line_dirty:
                self.lines[line].ctx = None
            self.lex_ctx_dirty_top = line
        else:
            self.lex_ctx_dirty_top = None

    ## \~japanese
    # start〜stop（除外）の未計算トークンを更新します。Noneは0/末尾。先に文脈を更新してください。max_lexは分析行数上限です。
    # stopを文書末尾へ制限した後にstart >= stopとなる空範囲では、トークンとdirty位置を変更しません。
    # \~english
    # Update missing tokens in start..stop (exclusive); None means zero/end. Update contexts first. max_lex limits analyzed lines.
    # An empty range (start >= stop after clamping stop to the document end) leaves tokens and the dirty position unchanged.
    # \~
    def updateSyntaxTokens(self, start=None, stop=None, max_lex=None):

        if start is None:
            start = 0

        if stop is None:
            stop = len(self.lines)
        else:
            stop = min(stop, len(self.lines))

        if start >= stop:
            return

        if max_lex is None:
            max_lex = len(self.lines)

        if self.lex_token_dirty_top is None or self.lex_token_dirty_top >= stop:
            return

        num_lex = 0

        for line in range(start, stop):
            if self.lines[line].tokens is None:
                ctx = self.lines[line].ctx
                assert ctx is not None
                tokens, _tmp = self.lexer.lex(ctx, self.lines[line].s, True)
                self.lines[line].tokens = Token.pack(tokens)

                num_lex += 1
                if num_lex >= max_lex:
                    break

        if start <= self.lex_token_dirty_top and line == len(self.lines) - 1:
            self.lex_token_dirty_top = None

    ## \~japanese
    # start〜stop（除外）へctxと境界列tokensを設定します。Noneは0/末尾。dirtyフラグは解除しません。
    # \~english
    # Set ctx and token boundaries over start..stop (exclusive); None means zero/end. Do not clear dirty flags.
    # \~
    def fillSyntaxContextAndTokens(self, start, stop, ctx, tokens):
        if start is None:
            start = 0

        if stop is None:
            stop = len(self.lines)
        else:
            stop = min(stop, len(self.lines))

        for line in range(start, stop):
            self.lines[line].ctx = ctx
            self.lines[line].tokens = Token.pack(tokens)

    ## \~japanese
    # TextLexer以外では文脈1000行・トークン100行を上限に更新します。タイマー自体の登録はしません。
    # \~english
    # For non-TextLexer lexers, update at most 1000 context lines and 100 token lines; do not register a timer.
    # \~
    def updateSyntaxTimer(self):
        if not isinstance(self.lexer, TextLexer):
            self.updateSyntaxContext(max_lex=1000)
            self.updateSyntaxTokens(start=self.lex_token_dirty_top, max_lex=100)

    ## \~japanese
    # 文脈またはトークンのdirty位置がNone以外ならTrue。TextLexerでも初期値はdirtyです。
    # \~english
    # Return True if either context/token dirty position is not None; even TextLexer starts dirty.
    # \~
    def isSyntaxDirty(self):
        return (
            self.lex_ctx_dirty_top is not None or self.lex_token_dirty_top is not None
        )


# --------------------------------------------------------------------


## \~japanese
# TextWidget の検索条件を保存し実行するクラス
#
# textは検索文字列、wordは単語一致、caseは大文字小文字を区別、regexは正規表現を使うかの真偽値です。
# 単語一致は検索文字列の両端がASCII英数字・下線の場合だけ有効です。不正な正規表現の例外は構築時に伝播します。
# re_resultはregex=Trueで直前に検索したre.MatchまたはNone。それ以外はNoneです。
#
# \~english
# Store and execute TextWidget search conditions
#
# text is the query; word enables whole-word matching; case enables case sensitivity; regex enables regular expressions.
# Whole-word matching is enabled only when the query endpoints are ASCII alphanumeric/underscore. Invalid regex errors propagate during construction.
# re_result is the last re.Match or None when regex=True, otherwise None.
#
# \~
class Search:
    ## \~japanese
    # Searchを構築します。引数と前提はクラス説明を参照してください。
    # \~english
    # Construct Search; see the class description for arguments and preconditions.
    # \~
    def __init__(self, text, word, case, regex):
        self.text = text
        self.word = word
        self.case = case
        self.regex = regex
        self.text_upper = self.text.upper()

        # Check whether the search text can begin and end at word boundaries;
        # otherwise disable whole-word matching.
        if (
            (len(self.text) >= 2 and re.match('[a-zA-Z0-9_].*[a-zA-Z0-9_]', self.text) is None)
            or (re.match('[a-zA-Z0-9_]', self.text) is None)
        ):
            self.word = False

        if self.regex or self.word:
            if self.regex:
                if self.word:
                    re_pattern = r"\b" + self.text + r"\b"
                else:
                    re_pattern = self.text
            else:
                re_pattern = ""
                for c in self.text:
                    if c in "\\[]^":
                        c = "\\" + c
                    re_pattern += "[" + c + "]"

                if self.word:
                    re_pattern = r"\b" + re_pattern + r"\b"

            re_option = re.UNICODE
            if not self.case:
                re_option |= re.IGNORECASE

            self.re_object = re.compile(re_pattern, re_option)
            self.re_result = None

        else:
            self.re_object = None
            self.re_result = None

    def __str__(self):
        return self.text

    ## \~japanese
    # 1行の文字列をposからend（除外）まで検索し、(開始, 終了)の文字位置タプルまたはNoneを返します。
    # Noneは先頭/末尾。正規表現のときだけre_resultも更新します。
    # 通常のcase=False検索はupperで照合し、境界・結果は元のPython文字位置です。展開文字の一部への一致も元文字全体を含みます。
    # \~english
    # Search one line between pos and exclusive end; return (start, end) string positions or None.
    # None bounds mean beginning/end; only regex searches update re_result.
    # Plain case=False searches compare uppercased strings but use original Python bounds/spans; partial expansion matches include the whole original character.
    # \~
    def search(self, line, pos=None, end=None):
        if self.re_object:
            if pos is None:
                re_result = self.re_object.search(line)
            elif end is None:
                re_result = self.re_object.search(line, pos)
            else:
                re_result = self.re_object.search(line, pos, end)

            if self.regex:
                self.re_result = re_result
            else:
                self.re_result = None

            if re_result:
                return (re_result.start(), re_result.end())
            else:
                return None

        else:
            if self.case:
                text = self.text
            else:
                text = self.text_upper
                upper = line.upper()
                if len(upper) != len(line):
                    # Keep bounds and returned spans in original Python characters.
                    start = 0 if pos is None else pos
                    stop = len(line) if end is None else end
                    if start < 0:
                        start = max(0, len(line) + start)
                    if stop < 0:
                        stop = max(0, len(line) + stop)
                    stop = min(len(line), stop)
                    if start > stop:
                        return None
                    offsets = [0]
                    for char in line:
                        offsets.append(offsets[-1] + len(char.upper()))
                    found = upper.find(text, offsets[start], offsets[stop])
                    if found < 0:
                        return None
                    return (
                        bisect.bisect_right(offsets, found) - 1,
                        bisect.bisect_left(offsets, found + len(text)),
                    )
                line = upper

            if pos is None:
                pos = line.find(text)
            elif end is None:
                pos = line.find(text, pos)
            else:
                pos = line.find(text, pos, end)

            if pos >= 0:
                return (pos, pos + len(text))
            else:
                return None


# --------------------------------------------------------------------


class MouseInfo:
    left: Point
    right: Point
    line: int

    def __init__(self, mode, **args):
        self.mode = mode
        self.__dict__.update(args)


# --------------------------------------------------------------------


## \~japanese
# テキスト編集ウィジェット
# 
#
# 親TextWindow上の複数行エディターです。通常のランチャー入力にはEditWidget/commandLineを使います。
# 位置・寸法は親の表示セル単位。親にcommand（CommandMap等）が必要です。構築前にテーマを準備しupdateColor()を呼ぶか、共有color_*キャッシュを明示設定します。
# 構築で空のDocument(TextMode)を作り描画しますが、keymapは作りません。configure()後にキーを割り当てます。
# 親はキー・文字・活性化・移動・サイズ変更を配送し、enableCursorとpaintを管理します。WordCompletionを使うなら親にedit_listも必要です。
# message_handler(message, timeout, error)はUIスレッドで呼ぶ通知先で、省略時は通知を捨てます。timeoutはミリ秒またはNoneです。
# color_*はクラス共有のRGB描画色です。syntax_*は構文色、diff_bg1/2/3は差分背景、select_bg_inactiveは非活性選択背景です。
# doc/selectionは現在の文書と選択、ideal_columnは上下移動先のセル、visible_first_line/columnは0始まりスクロール位置です。
# show_lineno、scroll_margin_v/h（行/セル）、scroll_bottom_adjustで表示を調整します。keymapはconfigureで置換されます。
# selection_changed_handler_listの関数は(self, anchor, cursor)で同期呼出しし、戻り値を無視します。例外は伝播します。
# UIスレッドで操作し、親の破棄前にdestroy()で文書通知と候補窓を解除します。ファイル保存やDocumentの破棄は行いません。
# command_*はCommandInfoを受け戻り値None。特定の不成立時にはinfo.result=Falseを設定します。executeCommandのboolとは別です。
# UndoInfo/AtomicUndoInfo、MouseInfo、CandidateWindowは編集・配送の内部補助です。通常は直接構築せず公開操作を使います。
# @sa Document, Point, Selection, Mode, Completion, Search
#
# \~english
# Text editor widget
# 
#
# Multiline editor on a parent TextWindow; use EditWidget/commandLine for ordinary launcher input.
# Geometry uses parent display cells. The host must provide command (such as CommandMap). Initialize the theme and call updateColor(), or explicitly fill the shared color_* cache, before construction.
# Construction creates/paints an empty Document(TextMode), but does not create a keymap. Call configure(), then assign keys.
# The host routes keys, characters, activation, movement and resizing, and manages enableCursor/paint. WordCompletion also requires host.edit_list.
# message_handler(message, timeout, error) runs on the UI thread; omit it to discard messages. timeout is milliseconds or None.
# color_* are shared class RGB drawing colors: syntax_* for syntax, diff_bg1/2/3 for diff backgrounds, select_bg_inactive for inactive selection.
# doc/selection hold current document/selection; ideal_column is the target display column; visible_first_line/column are zero-based scroll offsets.
# show_lineno, scroll_margin_v/h (lines/cells), and scroll_bottom_adjust control display. configure replaces keymap.
# selection_changed_handler_list callbacks run synchronously as (self, anchor, cursor); returns are ignored and exceptions propagate.
# Operate on the UI thread and call destroy() before destroying the parent to detach document callbacks and release candidates. It does not save/destroy the Document.
# command_* methods take CommandInfo and return None; some failed actions set info.result=False, separately from executeCommand's bool.
# UndoInfo/AtomicUndoInfo, MouseInfo and CandidateWindow are internal editing/dispatch helpers; normally use public operations instead.
# @sa Document, Point, Selection, Mode, Completion, Search
#
# \~
class TextWidget(ckit_widget.Widget):
    color_fg: _ClassVar[tuple[int, int, int] | None]
    color_select_fg: _ClassVar[tuple[int, int, int] | None]
    color_select_bg: _ClassVar[tuple[int, int, int] | None]
    color_bar_fg: _ClassVar[tuple[int, int, int] | None]
    color_bar_error_fg: _ClassVar[tuple[int, int, int] | None]
    color_bookmark1: _ClassVar[tuple[int, int, int] | None]
    color_bookmark2: _ClassVar[tuple[int, int, int] | None]
    color_bookmark3: _ClassVar[tuple[int, int, int] | None]
    color_diff_bg1: _ClassVar[tuple[int, int, int] | None]
    color_diff_bg2: _ClassVar[tuple[int, int, int] | None]
    color_diff_bg3: _ClassVar[tuple[int, int, int] | None]
    color_line_cursor: _ClassVar[tuple[int, int, int] | None]
    color_search_mark: _ClassVar[tuple[int, int, int] | None]
    color_syntax_text: _ClassVar[tuple[int, int, int] | None]
    color_syntax_keyword: _ClassVar[tuple[int, int, int] | None]
    color_syntax_name: _ClassVar[tuple[int, int, int] | None]
    color_syntax_number: _ClassVar[tuple[int, int, int] | None]
    color_syntax_string: _ClassVar[tuple[int, int, int] | None]
    color_syntax_preproc: _ClassVar[tuple[int, int, int] | None]
    color_syntax_comment: _ClassVar[tuple[int, int, int] | None]
    color_syntax_space: _ClassVar[tuple[int, int, int] | None]
    color_syntax_error: _ClassVar[tuple[int, int, int] | None]
    color_select_bg_inactive: _ClassVar[tuple[int, int, int]]

    BLOCK_SELECTION_COLUMN_OFFSET = 0.5

    rect_mode_clipboard_number = (
        None  # Clipboard sequence number recorded when copying a rectangular selection.
    )

    ## \~japanese
    # TextWidgetを構築します。引数と前提はクラス説明を参照してください。
    # \~english
    # Construct TextWidget; see the class description for arguments and preconditions.
    # \~
    def __init__(self, window, x, y, width, height, message_handler=None):
        ckit_widget.Widget.__init__(self, window, x, y, width, height)

        self.enableIme(True)

        self.command = window.command
        self.doc = Document(filename=None, mode=TextMode())
        self.selection = Selection(self)
        self.ideal_column = 0
        self.visible_first_line = 0
        self.visible_first_column = 0
        self.scroll_margin_v = 3
        self.scroll_margin_h = 0
        self.scroll_bottom_adjust = False
        self.show_lineno = True
        self.search_object = None
        self.search_re_result = None
        self.mouse_click_info = None
        self.message_handler = message_handler

        self.selection_changed_handler_list = []

        self.candidate_window = None

        self.doc.text_modified_handler_list.append(self.onDocumentTextModified)
        self.doc.bookmark_handler_list.append(self.onDocumentBookmark)
        self.setCursor(self.pointDocumentBegin())

    ## \~japanese
    # 文書に登録した通知ハンドラと候補窓を解放します。1回だけ呼び、以後この部品を使用しません。
    # \~english
    # Detach registered document callbacks and destroy the candidate window; call once and do not use this control afterwards.
    # \~
    def destroy(self):
        if self.candidate_window:
            self.candidate_window.destroy()

        self.doc.text_modified_handler_list.remove(self.onDocumentTextModified)
        self.doc.bookmark_handler_list.remove(self.onDocumentBookmark)

    ## \~japanese
    # 設定を読み込む
    # 
    #  キーマップなどをリセットした上で、モードの設定を反映しなおします。
    # 
    # \~english
    # Load configuration
    # 
    #  Reset the keymap and reapply the mode configuration.
    # 
    # \~
    def configure(self):
        self.keymap = ckit_key.Keymap()

        # Apply settings for each mode.
        self.doc.mode.configure(self)

        for mode in self.doc.minor_mode_list:
            mode.configure(self)

    ## \~japanese
    # Documentを共有して接続し、以前の文書から通知登録を外してカーソルを先頭へ戻します。
    # Noneは使えません。新しいモードのconfigureは別途必要です。旧文書・新文書の内容とUndo履歴は保持します。
    # 他ビューの編集では選択端点のうち変更範囲前を保持し、範囲内（終端を除く）を通知先ビューのPointで始点へ戻します。
    # 旧終端以降は終了行上なら行・文字位置を補正し、後続行なら行番号だけを補正します。
    # \~english
    # Attach/share a Document, detach callbacks from the previous one and move the caret to the beginning.
    # Do not pass None. Configure the new mode separately; preserve both documents' content and undo history.
    # Edits in another view preserve endpoints before the changed range and collapse those inside it (excluding its end) to its start using this view's Points.
    # At/after the old end, adjust line and character index on that end line; on following lines, adjust only the line number.
    # \~
    def setDocument(self, doc: Document):
        if self.doc:
            self.doc.text_modified_handler_list.remove(self.onDocumentTextModified)
            self.doc.bookmark_handler_list.remove(self.onDocumentBookmark)
        self.doc = doc
        if self.doc:
            self.doc.text_modified_handler_list.append(self.onDocumentTextModified)
            self.doc.bookmark_handler_list.append(self.onDocumentBookmark)

        self.setCursor(self.pointDocumentBegin())

    ## \~japanese
    # TextEncodingをdocへ設定しmodcount=Noneにして文書変更を通知します。文字列の再復号やファイル保存はしません。
    # \~english
    # Assign a TextEncoding to doc, set modcount=None and notify document change; do not redecode text or save a file.
    # \~
    def setEncoding(self, encoding):
        self.doc.encoding = encoding
        self.doc.modcount = None
        self._notifyTextModified(
            self.selection.cursor(), self.selection.cursor(), self.selection.cursor()
        )

    ## \~japanese
    # 既定と既存の非空の改行をlineend（CR/LF/CRLF）へ置換し、modcount=Noneにして通知します。Undo記録・保存はしません。
    # \~english
    # Replace default/existing nonempty line endings with lineend (CR/LF/CRLF), set modcount=None and notify; do not record undo or save.
    # \~
    def setLineEnd(self, lineend):
        self.doc.lineend = lineend
        for line in self.doc.lines:
            if line.end:
                line.end = lineend
        self.doc.modcount = None
        self._notifyTextModified(
            self.selection.cursor(), self.selection.cursor(), self.selection.cursor()
        )

    ## \~japanese
    # 親セル単位で位置・寸法とIME矩形を更新します。再描画は別途行います。
    # \~english
    # Update geometry in parent cells and the IME rectangle; repaint separately.
    # \~
    def setPosSize(self, x, y, width, height):
        ckit_widget.Widget.setPosSize(self, x, y, width, height)

    ## \~japanese
    # 指定した行に関してカラムから文字インデックスを取得する
    # line/columnは0始まりの行/表示セル、sub_xはセル内横小数位置です。block_modeは行末超の仮想位置を許します。
    # 戻り値はPython文字位置です。親APIのUTF-16列一覧を対応付け、補助平面文字の途中を返しません。
    # \~english
    # Get a character index from a display column on the specified line
    # line/column are zero-based line/display cells; sub_x is the horizontal cell fraction; block_mode permits virtual positions.
    # Return a Python character index by mapping the parent UTF-16 column list; never return a position inside a supplementary character.
    # \~
    def getIndexFromColumn(self, line, column, sub_x=0.0, block_mode=False):
        if len(self.doc.lines) <= line:
            return 0
        s = self.doc.lines[line].s
        column_list = self.window.getStringColumns(s, self.doc.mode.tab_width)
        if len(column_list) != len(s) + 1:
            python_columns = []
            utf16_index = 0
            for char in s:
                python_columns.append(column_list[utf16_index])
                utf16_index += 2 if ord(char) > 0xFFFF else 1
            python_columns.append(column_list[utf16_index])
            column_list = python_columns
        pos = bisect.bisect_right(column_list, column) - 1
        if pos + 1 > len(column_list) - 1:
            if block_mode:
                return len(s) + column - column_list[-1] + int(sub_x + 0.25)
            else:
                return len(s)
        elif column + sub_x < (column_list[pos] + column_list[pos + 1]) * 0.5 + 0.25:
            return pos
        else:
            return pos + 1

    ## \~japanese
    # 0始まりの行・Python文字位置を表示セル位置へ変換します。タブ幅はmode.tab_width。行末を越えたindexは1位置1セルを加算します。
    # \~english
    # Convert zero-based line/Python character index to display cells using mode.tab_width; add one cell per virtual position past the end.
    # \~
    def getColumnFromIndex(self, line, index):
        if len(self.doc.lines) <= line:
            return 0
        line = self.doc.lines[line].s
        s = line[:index]
        width = self.window.getStringWidth(s, self.doc.mode.tab_width)
        if index > len(line):
            width += index - len(line)
        return width

    ## \~japanese
    # 現在カーソルの(x,y)を親TextWindowのセル座標で返します。スクロール・行番号幅を含みます。
    # \~english
    # Return current caret (x,y) in parent TextWindow cells, accounting for scrolling and the line-number margin.
    # \~
    def getCursorPos(self):
        cursor = self.selection.cursor()
        line = self.doc.lines[cursor.line].s
        left_string = line[: cursor.index]
        x = (
            self.x
            + self.lineNoWidth()
            + self.window.getStringWidth(left_string, self.doc.mode.tab_width)
            - self.visible_first_column
        )
        if cursor.index > len(line):
            x += cursor.index - len(line)
        y = self.y + cursor.line - self.visible_first_line
        return (x, y)

    ## \~japanese
    # 親のキーイベントを配送します。vkは仮想キー、modはMODKEY_*。候補窓またはkeymapで扱えばTrue、未割当ならNoneです。
    # \~english
    # Route parent key input: vk is a virtual key, mod uses MODKEY_*. Return True when candidates/keymap handle it, otherwise None.
    # \~
    def onKeyDown(self, vk, mod):

        if self.candidate_window and self.candidate_window.onKeyDown(vk, mod):
            return True

        try:
            func = self.keymap.table[ckit_key.KeyEvent(vk, mod)]
        except KeyError:
            return

        func(ckit_command.CommandInfo())

        return True

    ## \~japanese
    # 親の文字コードchと修飾modを配送します。Ctrl入力と制御文字は無視し、通常文字を挿入します。戻り値で挿入成功は判定できません。
    # \~english
    # Route parent character code ch and modifiers mod; ignore Ctrl/control characters and insert ordinary characters. The return value does not indicate insertion success.
    # \~
    def onChar(self, ch, mod):

        if mod & MODKEY_CTRL:
            return

        if self.candidate_window and self.candidate_window.onChar(ch, mod):
            return True

        if ch <= 0xFF and (ch < 0x20 or ch == 0x7F):
            return

        self.modifyText(text=chr(ch))

        # Typing while the completion list is open filters its candidates.
        if self.candidate_window:
            self.popupList(auto_fix=False)

    ## \~japanese
    # 左押下でカーソル/選択を更新します。Shiftは選択伸縮、Altは矩形選択、行番号欄は行選択です。 char_x/yは親セル座標、sub_x/yはセル内小数、modは修飾ビット。
    # \~english
    # Update caret/selection on left press: Shift extends, Alt selects a rectangle, and the margin selects lines. char_x/y are parent cells, sub_x/y cell fractions, and mod modifier bits.
    # \~
    def onLeftButtonDown(self, char_x, char_y, sub_x, sub_y, mod):
        self.mouse_click_info = None
        point = self.pointMouse(char_x, char_y, sub_x)
        if char_x < self.x + self.lineNoWidth():
            if mod == MODKEY_SHIFT:
                anchor = self.selection.anchor()
                if self.selection.direction < 0 and anchor.index == 0:
                    anchor_line = max(anchor.line - 1, 0)
                else:
                    anchor_line = anchor.line
                if point.line < anchor.line:
                    anchor = self.point(anchor_line, 0).lineEnd().right()
                    cursor = point.lineBegin()
                else:
                    anchor = self.point(anchor_line, 0)
                    cursor = point.lineEnd().right()
                self.setSelection(anchor, cursor, block_mode=False)
                self.mouse_click_info = MouseInfo("lineno", line=anchor_line)
            else:
                left = point.lineBegin()
                right = point.lineEnd().right()
                self.setSelection(left, right, block_mode=False)
                self.mouse_click_info = MouseInfo("lineno", line=point.line)
        else:
            if mod == MODKEY_SHIFT:
                anchor = self.selection.anchor()
                self.setSelection(anchor, point)
            elif mod == MODKEY_ALT:
                point = self.pointMouse(char_x, char_y, sub_x, block_mode=True)
                self.setSelection(point, point, block_mode=True)
            else:
                self.setCursor(point)
            self.mouse_click_info = MouseInfo("left")

    ## \~japanese
    # 左ボタンのドラッグ状態を解除します。 char_x/yは親セル座標、sub_x/yはセル内小数、modは修飾ビット。
    # \~english
    # Clear left-button drag state. char_x/y are parent cells, sub_x/y cell fractions, and mod modifier bits.
    # \~
    def onLeftButtonUp(self, char_x, char_y, sub_x, sub_y, mod):
        self.mouse_click_info = None

    ## \~japanese
    # 本文は単語、行番号欄は行を選択し、ドラッグ開始状態を保持します。 char_x/yは親セル座標、sub_x/yはセル内小数、modは修飾ビット。
    # \~english
    # Select a word in text or a line in the margin and retain drag state. char_x/y are parent cells, sub_x/y cell fractions, and mod modifier bits.
    # \~
    def onLeftButtonDoubleClick(self, char_x, char_y, sub_x, sub_y, mod):
        self.mouse_click_info = None
        point = self.pointMouse(char_x, char_y, sub_x)
        if char_x < self.x + self.lineNoWidth():
            left = point.lineBegin()
            right = point.lineEnd().right()
            self.setSelection(left, right, block_mode=False)
            self.mouse_click_info = MouseInfo("lineno", line=point.line)
        else:
            line = self.doc.lines[point.line]
            left = self.point(
                point.line,
                self.doc.mode.wordbreak(
                    line.s, min(point.index + 1, len(line.s)), -1, use_type_bounds=False
                ),
            )
            right = self.point(
                point.line,
                self.doc.mode.wordbreak(line.s, point.index, +1, use_type_bounds=False),
            )
            self.setSelection(
                left,
                right,
                block_mode=False,
                make_visible=True,
                make_anchor_visible=True,
            )
            self.mouse_click_info = MouseInfo("left_double", left=left, right=right)

    ## \~japanese
    # 現在は何もしません。コンテキストメニューは親で実装します。 char_x/yは親セル座標、sub_x/yはセル内小数、modは修飾ビット。
    # \~english
    # Currently do nothing; implement context menus in the host. char_x/y are parent cells, sub_x/y cell fractions, and mod modifier bits.
    # \~
    def onRightButtonDown(self, char_x, char_y, sub_x, sub_y, mod):
        pass

    ## \~japanese
    # 現在は何もしません。 char_x/yは親セル座標、sub_x/yはセル内小数、modは修飾ビット。
    # \~english
    # Currently do nothing. char_x/y are parent cells, sub_x/y cell fractions, and mod modifier bits.
    # \~
    def onRightButtonUp(self, char_x, char_y, sub_x, sub_y, mod):
        pass

    ## \~japanese
    # 押下状態に従って文字/単語/行の選択を伸縮します。 char_x/yは親セル座標、sub_x/yはセル内小数、modは修飾ビット。
    # \~english
    # Extend character/word/line selection according to retained button state. char_x/y are parent cells, sub_x/y cell fractions, and mod modifier bits.
    # \~
    def onMouseMove(self, char_x, char_y, sub_x, sub_y, mod):

        if self.mouse_click_info is None:
            return

        if self.mouse_click_info.mode == "left":
            anchor = self.selection.anchor()
            cursor = self.pointMouse(
                char_x, char_y, sub_x, block_mode=self.selection.block_mode
            )
            self.setSelection(anchor, cursor)

        elif self.mouse_click_info.mode == "left_double":
            point = self.pointMouse(char_x, char_y, sub_x)
            line = self.doc.lines[point.line]
            if point < self.mouse_click_info.left:
                anchor = self.mouse_click_info.right
                cursor = self.point(
                    point.line,
                    self.doc.mode.wordbreak(
                        line.s,
                        min(point.index + 1, len(line.s)),
                        -1,
                        use_type_bounds=False,
                    ),
                )
            elif self.mouse_click_info.right <= point:
                anchor = self.mouse_click_info.left
                cursor = self.point(
                    point.line,
                    self.doc.mode.wordbreak(
                        line.s, point.index, +1, use_type_bounds=False
                    ),
                )
            else:
                anchor = self.mouse_click_info.left
                cursor = self.mouse_click_info.right
            self.setSelection(anchor, cursor)

        elif self.mouse_click_info.mode == "lineno":
            point = self.pointMouse(char_x, char_y, sub_x)
            if point.line < self.mouse_click_info.line:
                anchor = self.point(self.mouse_click_info.line, 0).lineEnd().right()
                cursor = self.point(point.line, 0)
            else:
                anchor = self.point(self.mouse_click_info.line, 0)
                cursor = self.point(point.line).lineEnd().right()
            self.setSelection(anchor, cursor)

    ## \~japanese
    # wheelの符号と量で縦スクロールします（正は上）。0.34単位ごとに1行です。 char_x/yは親セル座標、sub_x/yはセル内小数、modは修飾ビット。
    # \~english
    # Scroll vertically by wheel sign/magnitude (positive up), one line per 0.34 unit. char_x/y are parent cells, sub_x/y cell fractions, and mod modifier bits.
    # \~
    def onMouseWheel(self, char_x, char_y, sub_x, sub_y, wheel, mod):

        wheel_per_line = 0.34

        if wheel > 0:
            while wheel > 0:
                self.scrollV(-1)
                wheel -= wheel_per_line
        else:
            while wheel < 0:
                self.scrollV(1)
                wheel += wheel_per_line

    def _notifyTextModified(self, left, old_right, new_right):
        for text_modified_handler in self.doc.text_modified_handler_list:
            text_modified_handler(self, left, old_right, new_right)

    def onDocumentTextModified(self, sender, left, old_right, new_right):
        if self != sender:

            def adjustPoint(point, left, old_right, new_right):
                if point < left:
                    return point
                elif point < old_right:
                    return self.point(left.line, left.index)
                elif point.line == old_right.line:
                    return self.point(
                        new_right.line,
                        point.index - old_right.index + new_right.index,
                    )
                else:
                    return self.point(
                        point.line - old_right.line + new_right.line,
                        point.index,
                    )

            anchor = adjustPoint(self.selection.anchor(), left, old_right, new_right)
            cursor = adjustPoint(self.selection.cursor(), left, old_right, new_right)

            self.setSelection(anchor, cursor, paint=False)

            self.paint()

    def onDocumentBookmark(self, sender, line, bookmark):
        if self != sender:
            self.paint()

    ## \~japanese
    # この部品のPoint(line, index)を返します。範囲補正はしません。
    # \~english
    # Return Point(line, index) belonging to this control without clamping.
    # \~
    def point(self, line, index=0):
        return Point(self, line, index)

    ## \~japanese
    # 文書先頭(0,0)のPointを返します。
    # \~english
    # Return a Point at document beginning (0,0).
    # \~
    def pointDocumentBegin(self):
        point = self.point(0, 0)
        return point

    ## \~japanese
    # 文書最終行の改行直前のPointを返します。
    # \~english
    # Return a Point before the final line's ending.
    # \~
    def pointDocumentEnd(self):
        point = self.point(len(self.doc.lines) - 1, 0)
        point.index = len(self.doc.lines[point.line].s)
        return point

    ## \~japanese
    # 親セル座標をPointへ変換します。sub_xはセル内の横小数位置。上下の範囲外は文書先頭/末尾へ補正します。
    # \~english
    # Convert parent cell coordinates to a Point; sub_x is the horizontal cell fraction. Clamp positions above/below the document to its beginning/end.
    # \~
    def pointMouse(self, char_x, char_y, sub_x=0.0, block_mode=False):
        line = char_y - self.y + self.visible_first_line
        if line < 0:
            line = 0
            index = 0
        elif line > len(self.doc.lines) - 1:
            line = len(self.doc.lines) - 1
            index = len(self.doc.lines[line].s)
        else:
            x = char_x - self.x
            if x < self.lineNoWidth():
                index = 0
            else:
                column = x - self.lineNoWidth() + self.visible_first_column
                index = self.getIndexFromColumn(
                    line, column, sub_x, block_mode=block_mode
                )
        return self.point(line, index)

    ## \~japanese
    # 昇順のPoint left〜right（右端除外）の文字列を返します。通常範囲は元の改行を保持します。
    # block_mode=Trueの複数行は表示カラムで切り出し、各行の改行を含みます。Pointは同じ文書の有効な位置を渡します。
    # \~english
    # Return text between ordered Points left and right (exclusive). Normal ranges preserve stored line endings.
    # Multiline block_mode=True extracts display-column slices with each line ending. Supply valid Points in this document.
    # \~
    def getText(self, left, right, block_mode=False):
        if left.line == right.line:
            line = self.doc.lines[left.line]
            text = line.s[left.index : right.index]
        else:
            lines = []
            if not block_mode:
                line = self.doc.lines[left.line]
                lines.append(line.s[left.index :])
                lines.append(line.end)
                for i in range(left.line + 1, right.line):
                    line = self.doc.lines[i]
                    lines.append(line.s)
                    lines.append(line.end)
                line = self.doc.lines[right.line]
                lines.append(line.s[: right.index])
            else:
                column1 = self.getColumnFromIndex(left.line, left.index)
                column2 = self.getColumnFromIndex(right.line, right.index)
                rect_column_left = min(column1, column2)
                rect_column_right = max(column1, column2)

                for i in range(left.line, right.line + 1):
                    sel_left = self.getIndexFromColumn(
                        i, rect_column_left, TextWidget.BLOCK_SELECTION_COLUMN_OFFSET
                    )
                    sel_right = self.getIndexFromColumn(
                        i, rect_column_right, TextWidget.BLOCK_SELECTION_COLUMN_OFFSET
                    )

                    line = self.doc.lines[i]
                    lines.append(line.s[sel_left:sel_right])
                    lines.append(line.end)

            text = "".join(lines)
        return text

    ## \~japanese
    # anchor/cursor（Noneは現在選択）間をtextで置換します。戻り値None。新規改行はdoc.lineendを使います。
    # 通常の空文字列/Noneは削除。矩形操作のNoneはAttributeErrorです。text_block_modeは貼付け文字列が矩形かを示し、
    # 通常選択と矩形テキスト等の組合せを拒否してビープする場合があります。読取専用では通知だけで変更せず、ignore_readonlyで回避できます。
    # move_cursor/notify_modified/paintはカーソル・文書通知・再描画、append_undoはUndo記録を制御します。
    # modstepは変更回数への加算値、undo_selectはUndo/Redoで範囲選択を復元するかです。
    # 座標・型の誤りやコールバック例外は伝播し、変更のロールバックは保証しません。
    # \~english
    # Replace between anchor/cursor (None uses current selection) with text; return None. New line breaks use doc.lineend.
    # Normal empty text/None deletes; rectangular None raises AttributeError. text_block_mode marks rectangular input;
    # incompatible selection/input combinations may beep and return. Read-only documents report without changing unless ignore_readonly is true.
    # move_cursor/notify_modified/paint control caret movement, document notification and repaint; append_undo controls undo recording.
    # modstep increments modification count; undo_select restores the selected range during undo/redo.
    # Invalid positions/types and callback errors propagate; rollback is not guaranteed.
    # \~
    def modifyText(
        self,
        anchor=None,
        cursor=None,
        text: str | None = "",
        text_block_mode=False,
        move_cursor=True,
        notify_modified=True,
        paint=True,
        modstep=1,
        append_undo=True,
        undo_select=False,
        ignore_readonly=False,
    ):

        if self.doc.readonly and not ignore_readonly:
            self.setMessage(ckit_resource.strings["readonly"], 1000, error=True)
            return

        if anchor is None:
            anchor = self.selection.anchor()
        if cursor is None:
            cursor = self.selection.cursor()

        if anchor <= cursor:
            left = anchor.copy()
            right = cursor.copy()
        else:
            left = cursor.copy()
            right = anchor.copy()

        # Reject block text when a nonempty normal selection is active.
        if (
            not self.selection.block_mode
            and self.selection.direction != 0
            and text_block_mode
        ):
            ckit_misc.messageBeep()
            return

        # Reject nonempty normal text while a block selection is active.
        if self.selection.block_mode and not text_block_mode and text:
            ckit_misc.messageBeep()
            return

        block_mode = self.selection.block_mode or text_block_mode

        if not block_mode:
            if append_undo:
                undo_info = UndoInfo()
                undo_info.old_text = self.getText(left, right)
                undo_info.old_text_left = left.copy()
                undo_info.old_text_right = right.copy()
                if undo_select:
                    undo_info.old_anchor = anchor.copy()
                    undo_info.old_cursor = cursor.copy()
                else:
                    undo_info.old_anchor = cursor.copy()
                    undo_info.old_cursor = cursor.copy()

            # Delete the selected text.
            if left != right:
                line1 = self.doc.lines[left.line]
                line2 = self.doc.lines[right.line]

                s1 = line1.s[: left.index]
                s2 = line2.s[right.index :]

                if s1.strip() and line1.bg:
                    bg = line1.bg
                else:
                    bg = line2.bg

                if left.index > 0 or left.line == right.line:
                    bookmark = line1.bookmark
                elif right.index == 0:
                    bookmark = line2.bookmark
                else:
                    bookmark = 0

                line1.s = s1 + s2
                line1.end = line2.end
                line1.bg = bg
                line1.bookmark = bookmark
                if left.index or right.index:
                    line1.modified = True
                else:
                    line1.modified = line2.modified

                if left.line != right.line:
                    del self.doc.lines[left.line + 1 : right.line + 1]

            anchor = left
            cursor = left.copy()

            # Insert text.
            if text:
                insert_lines = text.splitlines(True)
                for insert_line in insert_lines:
                    if insert_line.endswith("\r\n"):
                        insert_return = True
                        insert_line = insert_line[:-2]
                    elif insert_line.endswith(("\n", "\r")):
                        insert_return = True
                        insert_line = insert_line[:-1]
                    else:
                        insert_return = False

                    line = self.doc.lines[cursor.line]
                    line.s = (
                        line.s[: cursor.index] + insert_line + line.s[cursor.index :]
                    )
                    cursor.index += len(insert_line)

                    if insert_return:
                        s1 = line.s[: cursor.index]
                        s2 = line.s[cursor.index :]

                        lineend1 = self.doc.lineend
                        lineend2 = line.end
                        if s1.strip():
                            bg1 = line.bg
                        else:
                            bg1 = 0
                        bg2 = line.bg

                        line.s = s1
                        line.end = lineend1
                        line.bg = bg1
                        line.tokens = None

                        line2 = Line(s2 + lineend2)
                        line2.bg = bg2
                        if line.modified or cursor.index:
                            line2.modified = True
                        self.doc.lines.insert(cursor.line + 1, line2)

                        cursor.line += 1
                        cursor.index = 0

                    line.modified = True

                if anchor.line != cursor.line and anchor.index == 0:
                    self.doc.lines[cursor.line].bookmark = self.doc.lines[
                        anchor.line
                    ].bookmark
                    self.doc.lines[anchor.line].bookmark = 0

            # Record undo information.
            if append_undo:
                undo_info.new_text = text
                undo_info.new_text_left = anchor.copy()
                undo_info.new_text_right = cursor.copy()
                if undo_select:
                    undo_info.new_anchor = anchor.copy()
                    undo_info.new_cursor = cursor.copy()
                else:
                    undo_info.new_anchor = cursor.copy()
                    undo_info.new_cursor = cursor.copy()
                self.appendUndo(undo_info)

        else:  # block_mode
            if text is None:
                raise AttributeError("'NoneType' object has no attribute 'splitlines'", name="splitlines", obj=None)
            insert_lines = text.splitlines(False)
            num_modify_line = max(len(insert_lines), right.line - left.line + 1)

            column1 = self.getColumnFromIndex(left.line, left.index)
            column2 = self.getColumnFromIndex(right.line, right.index)
            rect_column_left = min(column1, column2)
            rect_column_right = max(column1, column2)

            cursor = left.copy()
            cursor.index = self.getIndexFromColumn(
                cursor.line, rect_column_left, TextWidget.BLOCK_SELECTION_COLUMN_OFFSET
            )
            anchor = right.copy()
            anchor.index = self.getIndexFromColumn(
                anchor.line, rect_column_right, TextWidget.BLOCK_SELECTION_COLUMN_OFFSET
            )

            if append_undo:
                undo_left = left.lineBegin()
                undo_right = undo_left.copy()
                undo_right.line += num_modify_line
                undo_right = min(undo_right, self.pointDocumentEnd())

                undo_info = UndoInfo()
                undo_info.old_text = self.getText(undo_left, undo_right)
                undo_info.old_text_left = undo_left
                undo_info.old_text_right = undo_right
                undo_info.old_anchor = cursor.copy()
                undo_info.old_cursor = cursor.copy()

            for i in range(num_modify_line):
                lineno = left.line + i

                if i < len(insert_lines):
                    insert_line = insert_lines[i]
                else:
                    insert_line = ""

                if lineno <= right.line:
                    sel_left = self.getIndexFromColumn(
                        lineno,
                        rect_column_left,
                        TextWidget.BLOCK_SELECTION_COLUMN_OFFSET,
                    )
                    sel_right = self.getIndexFromColumn(
                        lineno,
                        rect_column_right,
                        TextWidget.BLOCK_SELECTION_COLUMN_OFFSET,
                    )

                    line = self.doc.lines[lineno]
                    line.s = line.s[:sel_left] + insert_line + line.s[sel_right:]
                    line.tokens = None
                    line.modified = True

                elif lineno < len(self.doc.lines):
                    index = self.getIndexFromColumn(lineno, rect_column_left)

                    line = self.doc.lines[lineno]
                    line.s = line.s[:index] + insert_line + line.s[index:]
                    line.tokens = None
                    line.modified = True

                else:
                    line = Line(insert_line + self.doc.lineend)
                    self.doc.lines.append(line)

            # Record undo information.
            if append_undo:
                undo_left = left.lineBegin()
                undo_right = undo_left.copy()
                undo_right.line += num_modify_line
                undo_right = min(undo_right, self.pointDocumentEnd())

                undo_info.new_text = self.getText(undo_left, undo_right)
                undo_info.new_text_left = undo_left
                undo_info.new_text_right = undo_right
                undo_info.new_anchor = cursor.copy()
                undo_info.new_cursor = cursor.copy()

                self.appendUndo(undo_info)

        # Update the modification count.
        if self.doc.modcount is not None:
            self.doc.modcount += modstep
            if self.doc.modcount == 0:
                for line in self.doc.lines:
                    line.modified = False

        if move_cursor:
            self.setCursor(cursor, paint=False)

        # Invalidate syntax highlighting after the modified lines.
        if left.line + 1 < len(self.doc.lines):
            self.doc.lines[left.line + 1].ctx = None
            if self.doc.lex_ctx_dirty_top is None:
                self.doc.lex_ctx_dirty_top = left.line + 1
            else:
                self.doc.lex_ctx_dirty_top = min(
                    self.doc.lex_ctx_dirty_top, left.line + 1
                )

        self.doc.lines[left.line].tokens = None
        if self.doc.lex_token_dirty_top is None:
            self.doc.lex_token_dirty_top = left.line
        else:
            self.doc.lex_token_dirty_top = min(self.doc.lex_token_dirty_top, left.line)

        if notify_modified:
            self._notifyTextModified(left, right, cursor)

        if paint:
            self.paint()

    ## \~japanese
    # 選択にかかる行の改行を除く文字列へfunc(text)を適用します。1行の文字列を返してください。
    # 終端が次行のindex=0ならその行を含みません。まとめたUndoに記録し、選択・通知・描画を更新します。例外は伝播し部分変更を戻しません。
    # \~english
    # Apply func(text) to selected lines without their endings; return one line of text.
    # An endpoint at index zero excludes that final line. Group undo and update selection/notifications/paint. Errors propagate without rolling back partial edits.
    # \~
    def replaceLines(self, func):
        left = self.selection.left()
        right = self.selection.right()

        left = left.lineBegin()
        if right.index > 0:
            right = right.lineEnd().right()

        self.atomicUndoBegin(True, left, right)
        try:
            point1 = left.copy()
            while point1 < right:
                point2 = point1.lineEnd()

                old_text = self.getText(point1, point2)
                new_text = func(old_text)
                if new_text != old_text:
                    self.modifyText(
                        point1,
                        point2,
                        new_text,
                        move_cursor=False,
                        notify_modified=False,
                        paint=False,
                    )

                point1.line += 1

        finally:
            self.atomicUndoEnd(left, right)

        self._notifyTextModified(left, right, right)

        self.setSelection(left, right, block_mode=False)
        self.paint()

    ## \~japanese
    # 選択行ごとにfunc(text, info)を呼び、偽値の行を削除します。info.bookmark/modifiedは読取り用の行情報です。
    # まとめたUndo・選択・通知・描画を更新します。例外は伝播し部分変更を戻しません。
    # \~english
    # Call func(text, info) for selected lines and delete those returning false; info.bookmark/modified are line metadata for reading.
    # Group undo and update selection/notifications/paint; errors propagate without undoing partial edits.
    # \~
    def filterLines(self, func):
        class LineInfo:
            bookmark: int
            modified: bool

        left = self.selection.left()
        right = self.selection.right()
        old_right = right.copy()

        left = left.lineBegin()
        if right.index > 0:
            right = right.lineEnd().right()

        self.atomicUndoBegin(True, left, right)
        try:
            point1 = left.copy()
            while point1 < right:
                line = self.doc.lines[point1.line]
                info = LineInfo()
                info.bookmark = line.bookmark
                info.modified = line.modified

                point2 = point1.lineEnd()

                text = self.getText(point1, point2)
                if func(text, info):
                    point1.line += 1
                else:
                    num_lines = len(self.doc.lines)
                    self.modifyText(
                        point1,
                        point2.right(),
                        "",
                        move_cursor=False,
                        notify_modified=False,
                        paint=False,
                    )
                    removed_lines = num_lines - len(self.doc.lines)
                    right.line -= removed_lines
                    right = min(right, self.pointDocumentEnd())
                    if not removed_lines:
                        point1.line += 1

        finally:
            self.atomicUndoEnd(left, right)

        self._notifyTextModified(left, old_right, right)

        self.setSelection(left, right, block_mode=False)
        self.paint()

    ## \~japanese
    # 内部UndoInfoを記録しRedoを消します。通常はmodifyTextが呼ぶため直接編集履歴を構築しません。
    # \~english
    # Record an internal UndoInfo and clear redo; normally use modifyText rather than constructing history manually.
    # \~
    def appendUndo(self, info):
        # Clearing the redo list makes the saved state unreachable when modcount is negative.
        if self.doc.modcount is not None and self.doc.modcount < 0:
            self.doc.modcount = None

        self.doc.redo_list = []

        if self.doc.atomic_undo is None:
            self.doc.undo_list.append(info)
        else:
            self.doc.atomic_undo.items.append(info)

    ## \~japanese
    # 後続の編集を1回のUndoへまとめ始めます。Noneの端点は現在選択。入れ子不可で、finallyでatomicUndoEndと対にします。
    # undo_select引数は現在使われません。各modifyTextのundo_selectは別です。
    # \~english
    # Start grouping edits as one undo; None endpoints use current selection. No nesting; pair with atomicUndoEnd in finally.
    # This method's undo_select is currently unused, independently of modifyText.undo_select.
    # \~
    def atomicUndoBegin(self, undo_select=False, anchor=None, cursor=None):
        if anchor is None:
            anchor = self.selection.anchor()
        if cursor is None:
            cursor = self.selection.cursor()

        self.doc.atomic_undo = AtomicUndoInfo()
        self.doc.atomic_undo.old_anchor = anchor.copy()
        self.doc.atomic_undo.old_cursor = cursor.copy()

    ## \~japanese
    # グループを確定します。Noneの端点は現在選択。BeginなしならAttributeErrorです。空のグループも履歴に追加します。
    # \~english
    # Commit the group using current selection for None endpoints; raise AttributeError without Begin. Even empty groups enter history.
    # \~
    def atomicUndoEnd(self, anchor=None, cursor=None):
        if anchor is None:
            anchor = self.selection.anchor()
        if cursor is None:
            cursor = self.selection.cursor()

        new_anchor = anchor.copy()
        atomic_undo = self.doc.atomic_undo
        if atomic_undo is None:
            raise AttributeError(
                "'NoneType' object has no attribute 'new_anchor' and no __dict__ for setting new attributes",
                name="new_anchor", obj=None,
            )
        atomic_undo.new_anchor = new_anchor
        new_cursor = cursor.copy()
        atomic_undo = self.doc.atomic_undo
        if atomic_undo is None:
            raise AttributeError(
                "'NoneType' object has no attribute 'new_cursor' and no __dict__ for setting new attributes",
                name="new_cursor", obj=None,
            )
        atomic_undo.new_cursor = new_cursor
        self.doc.undo_list.append(self.doc.atomic_undo)
        self.doc.atomic_undo = None

    ## \~japanese
    # 履歴がなければFalse、あれば履歴を移し復元を試みTrueを返します。read-onlyでもTrueになり得るため、変更成功の保証ではありません。
    # \~english
    # Return False without history; otherwise move history, attempt restoration and return True. True may occur for read-only documents and does not guarantee a text change.
    # \~
    def undo(self):
        if len(self.doc.undo_list) == 0:
            return False

        info = self.doc.undo_list.pop()
        self.doc.redo_list.append(info)

        if isinstance(info, UndoInfo):
            self.modifyText(
                info.new_text_left,
                info.new_text_right,
                info.old_text,
                move_cursor=False,
                paint=False,
                modstep=-1,
                append_undo=False,
            )
        elif isinstance(info, AtomicUndoInfo):
            for i, item in enumerate(reversed(info.items)):
                self.modifyText(
                    item.new_text_left,
                    item.new_text_right,
                    item.old_text,
                    move_cursor=False,
                    notify_modified=False,
                    paint=False,
                    modstep=-1,
                    append_undo=False,
                )
            self._notifyTextModified(info.new_anchor, info.new_cursor, info.old_cursor)

        self.setSelection(info.old_anchor, info.old_cursor, paint=False)

        self.paint()

        return True

    ## \~japanese
    # Redo履歴がなければFalse、あれば履歴を移し再適用を試みTrue。read-only等の編集制約はmodifyTextと同じです。
    # \~english
    # Return False without redo history; otherwise move history, attempt replay and return True. Editing constraints such as read-only follow modifyText.
    # \~
    def redo(self):
        if len(self.doc.redo_list) == 0:
            return False

        info = self.doc.redo_list.pop()
        self.doc.undo_list.append(info)

        if isinstance(info, UndoInfo):
            self.modifyText(
                info.old_text_left,
                info.old_text_right,
                info.new_text,
                move_cursor=False,
                paint=False,
                append_undo=False,
            )
        elif isinstance(info, AtomicUndoInfo):
            for i, item in enumerate(info.items):
                self.modifyText(
                    item.old_text_left,
                    item.old_text_right,
                    item.new_text,
                    move_cursor=False,
                    notify_modified=False,
                    paint=False,
                    append_undo=False,
                )
            self._notifyTextModified(info.old_anchor, info.old_cursor, info.new_cursor)

        self.setSelection(info.new_anchor, info.new_cursor, paint=False)

        self.paint()

        return True

    ## \~japanese
    # Pointへ移動し選択・矩形モードを解除します。行末超は行末へ補正。残るフラグはsetSelectionと同じです。
    # \~english
    # Move to a Point and clear selection/block mode, clamping past-end indices to line end. Other flags follow setSelection.
    # \~
    def setCursor(
        self,
        cursor,
        update_ideal_column=True,
        make_visible=True,
        make_anchor_visible=False,
        paint=True,
    ):
        cursor = min(cursor, cursor.lineEnd())
        self.setSelection(
            cursor,
            cursor,
            block_mode=False,
            update_ideal_column=update_ideal_column,
            make_visible=make_visible,
            make_anchor_visible=make_anchor_visible,
            paint=paint,
        )

    ## \~japanese
    # Point anchor（固定端）とcursor（移動端）で選択します。block_mode=Noneは現在値維持です。
    # update_ideal_columnは上下移動用セル位置更新、make_visibleはスクロール、make_anchor_visibleは固定端も対象にします。
    # paint=Falseでも選択通知は呼びます。両Pointはコピーして保持しますが通知へは引数のPointを渡します。
    # 端点の順序と方向を正規化しますが、行・文字位置の範囲クランプは行いません。
    # \~english
    # Select from fixed anchor Point to moving cursor Point; block_mode=None preserves the current mode.
    # update_ideal_column updates the vertical target column; make_visible scrolls, with make_anchor_visible also revealing anchor.
    # Selection callbacks run even with paint=False. Retain copies, but pass the supplied Points to callbacks.
    # Normalize endpoint ordering/direction without clamping line numbers or character indices.
    # \~
    def setSelection(
        self,
        anchor,
        cursor,
        block_mode=None,
        update_ideal_column=True,
        make_visible=True,
        make_anchor_visible=False,
        paint=True,
    ):
        left_old, right_old = self.selection.left(), self.selection.right()

        if block_mode is not None:
            self.selection.setBlockMode(block_mode)

        self.selection.setSelection(anchor, cursor)

        left_new, right_new = self.selection.left(), self.selection.right()

        if update_ideal_column:
            self.ideal_column = self.getColumnFromIndex(cursor.line, cursor.index)

        line_range = (min(left_old, left_new).line, max(right_old, right_new).line + 1)

        if make_visible:
            if make_anchor_visible:
                if self.makeVisible([anchor, cursor], paint=False):
                    line_range = None
            else:
                if self.makeVisible(cursor, paint=False):
                    line_range = None

        for selection_changed_handler in self.selection_changed_handler_list:
            selection_changed_handler(self, anchor, cursor)

        if paint:
            self.paint(line_range=line_range)

    ## \~japanese
    # 0始まりlineの印を非空bookmark_listの次の値へ巡回し通知します。通常は0（なし）と1/2/3。paintは再描画を制御します。
    # \~english
    # Cycle the zero-based line's marker through nonempty bookmark_list and notify; normally use 0 (none) and 1/2/3. paint controls repaint.
    # \~
    def bookmark(self, line, bookmark_list, paint=True):
        for i in range(len(bookmark_list)):
            if self.doc.lines[line].bookmark == bookmark_list[i]:
                i += 1
                if i >= len(bookmark_list):
                    i = 0
                break
        else:
            i = 0

        self.doc.lines[line].bookmark = bookmark_list[i]

        for bookmark_handler in self.doc.bookmark_handler_list:
            bookmark_handler(self, line, bookmark_list[i])

        if paint:
            self.paint()

    ## \~japanese
    # 全印を消し、(0始まり行番号, 印, ...)の列を適用します。通知・描画はしません。有効な非負行番号を使います。
    # \~english
    # Clear markers and apply entries (zero-based line, marker, ...); do not notify or paint. Use valid nonnegative line numbers.
    # \~
    def setBookmarkList(self, bookmark_list):
        for line in self.doc.lines:
            line.bookmark = 0

        for bookmark in bookmark_list:
            if bookmark[0] < len(self.doc.lines):
                self.doc.lines[bookmark[0]].bookmark = bookmark[1]

    ## \~japanese
    # 印が0でない行の(0始まり行番号, 印, 本文)リストを返します。
    # \~english
    # Return (zero-based line, marker, body) entries for nonzero markers.
    # \~
    def getBookmarkList(self):
        bookmark_list = []

        for i, line in enumerate(self.doc.lines):
            if line.bookmark:
                bookmark_list.append((i, line.bookmark, line.s))

        return bookmark_list

    ## \~japanese
    # 差分色モードのboolを返します。
    # \~english
    # Return the diff-color mode bool.
    # \~
    def isDiffColorMode(self):
        return self.doc.diff_mode

    ## \~japanese
    # 差分色モードを有効にします。色はdoc.linesの各bg（1/2/3）へ設定します。再描画しません。
    # \~english
    # Enable diff-color mode; assign colors through each doc.lines entry's bg (1/2/3). Do not repaint.
    # \~
    def setDiffColorMode(self):
        self.doc.diff_mode = True

    ## \~japanese
    # 差分色モードなら全行bgを0にしてモードを解除します。再描画しません。
    # \~english
    # When in diff mode, clear all line bg values to zero and disable it without repainting.
    # \~
    def clearDiffColor(self):
        if self.doc.diff_mode:
            for line in self.doc.lines:
                line.bg = 0
            self.doc.diff_mode = False

    ## \~japanese
    # 現在行を除いてdirection>0なら下、そうでなければ上へ走査し、func(Line)が真の行の先頭Pointを返します。
    # 未発見はNone。move_cursor=Trueなら移動・スクロール・描画します。
    # \~english
    # Scan below the current line for direction>0, otherwise above; return a line-start Point where func(Line) is true, or None.
    # move_cursor=True moves, scrolls and paints.
    # \~
    def seek(self, direction, func, move_cursor=True):
        cursor = self.selection.cursor()

        if direction > 0:
            line_range = range(cursor.line + 1, len(self.doc.lines))
        else:
            line_range = range(cursor.line - 1, -1, -1)

        for line in line_range:
            if func(self.doc.lines[line]):
                cursor = self.point(line, 0)
                break
        else:
            return None

        if move_cursor:
            self.setCursor(cursor, make_visible=False, paint=False)
            self.makeVisible(cursor, jump_mode=True)

        return cursor

    ## \~japanese
    # Search条件で行内検索します。search_object=Noneは前の条件、point=Noneは選択の右端（順方向）/左端（逆方向）です。
    # direction>0は順方向、その他は逆方向。折返しなし、oneline=Trueは開始行だけ。結果は一致先頭PointまたはNone。
    # move_cursor/selectは移動と一致選択、hitmarkは条件保持、paintは移動後描画、messageは結果通知です。
    # 正規表現の結果はsearch_re_resultに保持します。通常のcase=False検索はupperで照合し、
    # 大文字化で長さが変わっても元のPython文字範囲を選択します。展開文字の一部への一致は元文字全体を含みます。
    # \~english
    # Search within lines using a Search object. search_object=None reuses the prior condition; point=None starts at the right/left selection edge for forward/backward.
    # direction>0 is forward, otherwise backward. No wrap; oneline=True restricts to the starting line. Return a match-start Point or None.
    # move_cursor/select control movement/match selection; hitmark retains the condition; paint repaints after movement; message reports the result.
    # search_re_result retains the regex match. Plain case=False searches compare uppercased strings and select original Python spans,
    # even when uppercasing changes length; partial expansion matches include the whole original character.
    # \~
    def search(
        self,
        search_object=None,
        point=None,
        direction=1,
        oneline=False,
        move_cursor=True,
        select=True,
        hitmark=True,
        paint=True,
        message=True,
    ):
        if search_object is None:
            search_object = self.search_object
        else:
            if hitmark:
                self.search_object = search_object

        if not search_object:
            return None

        if point:
            point = point.copy()
        else:
            if direction > 0:
                point = self.selection.right()
            else:
                point = self.selection.left()

        def foundMessage():
            if message:
                self.setMessage(
                    ckit_resource.strings["search_found"].format(query=search_object),
                    1000,
                )

        def notFoundMessage():
            if message:
                self.setMessage(
                    ckit_resource.strings["search_not_found"].format(
                        query=search_object
                    ),
                    3000,
                    error=True,
                )

        while True:
            if direction > 0:
                if point.line >= len(self.doc.lines):
                    notFoundMessage()
                    return None
            else:
                if point.line < 0:
                    notFoundMessage()
                    return None

            line = self.doc.lines[point.line].s

            if direction > 0:
                result = search_object.search(line, point.index)
                self.search_re_result = search_object.re_result
            else:

                def rsearch(end):
                    pos = 0
                    last_found = None
                    while pos < len(line):  # noqa: B023  # Called before the next loop iteration.
                        search_result = search_object.search(line, pos, end)  # noqa: B023  # Called before the next loop iteration.
                        if not search_result:
                            break
                        if last_found is None or last_found[0] < search_result[0]:
                            self.search_re_result = search_object.re_result
                            last_found = search_result
                        pos = search_result[0] + 1
                    return last_found

                result = rsearch(point.index)

            if result:
                cursor = self.point(point.line, result[0])
                anchor = self.point(point.line, result[1])
                break

            if oneline:
                notFoundMessage()
                return None

            if direction > 0:
                point.line += 1
                point.index = 0
            else:
                point.line -= 1
                point.index = len(self.doc.lines[point.line].s)

        foundMessage()

        if move_cursor:
            if select:
                self.setSelection(
                    anchor, cursor, block_mode=False, make_visible=False, paint=False
                )
            else:
                self.setCursor(cursor, make_visible=False, paint=False)

            self.makeVisible([anchor, cursor], jump_mode=True, paint=paint)

        return cursor.copy()

    ## \~japanese
    # 0始まり行番号を文書内へ補正して先頭へ移動し、横スクロールをリセットします。表示行番号は1始まりです。
    # \~english
    # Clamp a zero-based line number, move to its start and reset horizontal scrolling; displayed line numbers are one-based.
    # \~
    def jumpLineNo(self, lineno):
        lineno = max(lineno, 0)
        lineno = min(lineno, len(self.doc.lines) - 1)
        point = self.point(lineno, 0)
        self.visible_first_line = max(point.line - self.height // 2, 0)
        self.visible_first_column = 0
        self.setCursor(point, make_visible=False, paint=False)
        self.makeVisible(point, jump_mode=True)

    ## \~japanese
    # step行（正は下）スクロールします。無選択ならカーソルも移動します。再描画します。
    # \~english
    # Scroll by step lines (positive downward); also move the caret when there is no selection, then repaint.
    # \~
    def scrollV(self, step):
        step = max(-self.visible_first_line, step)
        step = min(len(self.doc.lines) - 1 - self.visible_first_line, step)

        if step == 0:
            return

        self.visible_first_line = self.visible_first_line + step
        if step < 0:
            cursor = self.selection.cursor().up(-step)
        else:
            cursor = self.selection.cursor().down(step)

        if self.selection.direction == 0:
            self.setCursor(
                cursor, update_ideal_column=False, make_visible=False, paint=False
            )

        self.paint()

    ## \~japanese
    # 単一PointまたはPoint列が見えるようスクロールし、スクロールしたかのboolを返します。
    # 余白Noneは部品設定、jump_modeは範囲外の行を上寄りに表示、paintは再描画です。
    # \~english
    # Scroll to reveal a Point or sequence of Points and return whether scrolling occurred.
    # None margins use control settings; jump_mode places offscreen lines near the top; paint controls repaint.
    # \~
    def makeVisible(
        self,
        points,
        scroll_margin_v=None,
        scroll_margin_h=None,
        jump_mode=False,
        paint=True,
    ):
        scrolled = False

        if isinstance(points, Point):
            points = [points]
        if scroll_margin_v is None:
            scroll_margin_v = self.scroll_margin_v
        if scroll_margin_h is None:
            scroll_margin_h = self.scroll_margin_h
        scroll_margin_v = min(scroll_margin_v, self.height // 2)
        scroll_margin_h = min(scroll_margin_h, self.width // 2)

        for point in points:
            if jump_mode and (
                point.line < self.visible_first_line
                or point.line > self.visible_first_line + (self.height - 1)
            ):
                self.visible_first_line = point.line - self.height // 3
                scrolled = True

            if (
                point.line
                > self.visible_first_line + (self.height - 1) - scroll_margin_v
            ):
                self.visible_first_line = max(
                    point.line - (self.height - 1) + scroll_margin_v, 0
                )
                scrolled = True

            if point.line < self.visible_first_line + scroll_margin_v:
                self.visible_first_line = max(point.line - scroll_margin_v, 0)
                scrolled = True

            if self.scroll_bottom_adjust and (
                self.visible_first_line
                > len(self.doc.lines) - self.height + scroll_margin_v
            ):
                self.visible_first_line = (
                    len(self.doc.lines) - self.height + scroll_margin_v
                )
                scrolled = True

            if self.visible_first_line < 0:
                self.visible_first_line = 0
                scrolled = True

            text_rect = self.rectText()
            text_width = text_rect[2] - text_rect[0]

            column = self.getColumnFromIndex(point.line, point.index)

            if column > self.visible_first_column + (text_width - 1) - scroll_margin_h:
                self.visible_first_column = max(
                    column - (text_width - 1) + scroll_margin_h, 0
                )
                scrolled = True

            if column < self.visible_first_column + scroll_margin_h:
                self.visible_first_column = max(column - scroll_margin_h, 0)
                scrolled = True

        if paint:
            self.paint()

        return scrolled

    ## \~japanese
    # 行番号欄幅をセル数で返します。show_lineno=Falseでも最大2セルの余白を残します。
    # \~english
    # Return line-number margin width in cells; show_lineno=False still leaves up to two margin cells.
    # \~
    def lineNoWidth(self):
        if self.show_lineno:
            str_max_lineno = str(len(self.doc.lines))
            keta = len(str_max_lineno)
            return min(keta + 2, self.width)
        else:
            return min(2, self.width)

    ## \~japanese
    # 行番号欄の[left, top, right, bottom]を親セル座標で返します。右・下は除外。
    # \~english
    # Return line-number [left, top, right, bottom] in parent cells, right/bottom exclusive.
    # \~
    def rectLineNo(self):
        lineno_width = self.lineNoWidth()
        return [self.x, self.y, self.x + lineno_width, self.y + self.height]

    ## \~japanese
    # 本文欄の[left, top, right, bottom]を親セル座標で返します。右のスクロール欄2セルを除きます。
    # \~english
    # Return text-area [left, top, right, bottom] in parent cells, excluding the two-cell scrollbar margin.
    # \~
    def rectText(self):
        lineno_width = self.lineNoWidth()
        return [
            self.x + lineno_width,
            self.y,
            self.x + self.width - 2,
            self.y + self.height,
        ]

    ## \~japanese
    # 右端の最大2セルのスクロール欄を親セル座標[left, top, right, bottom]で返します。
    # \~english
    # Return the rightmost up-to-two-cell scrollbar area as parent-cell [left, top, right, bottom].
    # \~
    def rectScrollbar(self):
        scrollbar_width = min(2, self.width)
        return [
            self.x + self.width - scrollbar_width,
            self.y,
            self.x + self.width,
            self.y + self.height,
        ]

    ## \~japanese
    # 共有テーマからクラスの描画色を更新します。構築前とテーマ変更後に呼び、既存部品は別途paintします。
    # エディター固有のbookmark/diff/syntax等の色も必要です。不足色はgetColorの通知・黒へのフォールバックに従います。
    # \~english
    # Update class drawing colors from the shared theme before construction and after theme changes; repaint existing controls separately.
    # Editor-specific bookmark/diff/syntax colors are also required; missing colors follow getColor's reported black fallback.
    # \~
    @staticmethod
    def updateColor():
        TextWidget.color_fg = ckit_theme.getColor("fg")
        TextWidget.color_select_fg = ckit_theme.getColor("select_fg")
        TextWidget.color_select_bg = ckit_theme.getColor("select_bg")
        TextWidget.color_bar_fg = ckit_theme.getColor("bar_fg")
        TextWidget.color_bar_error_fg = ckit_theme.getColor("bar_error_fg")
        TextWidget.color_bookmark1 = ckit_theme.getColor("bookmark1")
        TextWidget.color_bookmark2 = ckit_theme.getColor("bookmark2")
        TextWidget.color_bookmark3 = ckit_theme.getColor("bookmark3")
        TextWidget.color_diff_bg1 = ckit_theme.getColor("diff_bg1")
        TextWidget.color_diff_bg2 = ckit_theme.getColor("diff_bg2")
        TextWidget.color_diff_bg3 = ckit_theme.getColor("diff_bg3")
        TextWidget.color_line_cursor = ckit_theme.getColor("line_cursor")
        TextWidget.color_search_mark = ckit_theme.getColor("search_mark")
        TextWidget.color_syntax_text = ckit_theme.getColor("text", "SYNTAX_COLOR")
        TextWidget.color_syntax_keyword = ckit_theme.getColor("keyword", "SYNTAX_COLOR")
        TextWidget.color_syntax_name = ckit_theme.getColor("name", "SYNTAX_COLOR")
        TextWidget.color_syntax_number = ckit_theme.getColor("number", "SYNTAX_COLOR")
        TextWidget.color_syntax_string = ckit_theme.getColor("string", "SYNTAX_COLOR")
        TextWidget.color_syntax_preproc = ckit_theme.getColor("preproc", "SYNTAX_COLOR")
        TextWidget.color_syntax_comment = ckit_theme.getColor("comment", "SYNTAX_COLOR")
        TextWidget.color_syntax_space = ckit_theme.getColor("space", "SYNTAX_COLOR")
        TextWidget.color_syntax_error = ckit_theme.getColor("error", "SYNTAX_COLOR")
        select_bg = ckit_theme._require_rgb(TextWidget.color_select_bg)
        gray_select_bg = (
            select_bg[0]
            + select_bg[1]
            + select_bg[2]
        ) // 3
        TextWidget.color_select_bg_inactive = (
            gray_select_bg,
            gray_select_bg,
            gray_select_bg,
        )

    ## \~japanese
    # line_range=Noneは全可視行、(start, stop)は0始まり文書行の半開区間を描画します。paint_cursorは親キャレット更新を制御します。
    # 必要な構文情報も更新します。visible=Falseなら何もしません。
    # \~english
    # Paint all visible lines for line_range=None, or the half-open zero-based document-line range (start, stop). paint_cursor controls the parent caret.
    # Update needed syntax data; do nothing when visible=False.
    # \~
    def paint(self, line_range=None, paint_cursor=True):
        if not self.visible:
            return

        x = self.x
        y = self.y
        width = self.width
        height = self.height

        selection_left = self.selection.left()
        selection_right = self.selection.right()
        cursor = self.selection.cursor()
        block_mode = self.selection.block_mode
        if block_mode:
            column1 = self.getColumnFromIndex(selection_left.line, selection_left.index)
            column2 = self.getColumnFromIndex(
                selection_right.line, selection_right.index
            )
            selection_rect_column_left = min(column1, column2)
            selection_rect_column_right = max(column1, column2)

        active = self.enable_cursor and self.window.isForeground()

        tab_width = self.doc.mode.tab_width
        show_tab = self.doc.mode.show_tab
        show_space = self.doc.mode.show_space
        show_wspace = self.doc.mode.show_wspace
        show_lineend = self.doc.mode.show_lineend
        show_fileend = self.doc.mode.show_fileend

        if show_tab:
            altchar_tab = "►"
        else:
            altchar_tab = " "
        if show_space:
            altchar_space = "˽"
        else:
            altchar_space = " "
        if show_wspace:
            altchar_wspace = "□"
        else:
            altchar_wspace = "　"
        if show_lineend:
            altchar_lineend = "↵"
        else:
            altchar_lineend = " "
        if show_fileend:
            altchar_fileend = "[EOF]"
        else:
            altchar_fileend = ""

        lineno_width = self.lineNoWidth()
        keta = lineno_width - 2

        # Update syntax highlighting for the visible text.
        visible_bottom = self.visible_first_line + self.height
        if isinstance(self.doc.lexer, TextLexer):
            self.doc.fillSyntaxContextAndTokens(
                start=self.visible_first_line,
                stop=visible_bottom,
                ctx=rootContext(),
                tokens=TextLexer.tokens,
            )
        else:
            self.doc.updateSyntaxContext(stop=visible_bottom)
            self.doc.updateSyntaxTokens(
                start=self.visible_first_line, stop=visible_bottom
            )

        # Draw the text.
        x2 = x + lineno_width
        width2 = width - lineno_width

        attribute_whitespace = ckitcore.Attribute(fg=TextWidget.color_fg)

        bookmark_line = (LINE_RECTANGLE, TextWidget.color_bar_fg)
        attribute_lineno_table = {}
        attribute_lineno_table[(False, 0)] = ckitcore.Attribute(
            fg=TextWidget.color_bar_fg, bg=None, line1=None
        )
        attribute_lineno_table[(False, 1)] = ckitcore.Attribute(
            fg=TextWidget.color_bar_fg,
            bg=TextWidget.color_bookmark1,
            line1=bookmark_line,
        )
        attribute_lineno_table[(False, 2)] = ckitcore.Attribute(
            fg=TextWidget.color_bar_fg,
            bg=TextWidget.color_bookmark2,
            line1=bookmark_line,
        )
        attribute_lineno_table[(False, 3)] = ckitcore.Attribute(
            fg=TextWidget.color_bar_fg,
            bg=TextWidget.color_bookmark3,
            line1=bookmark_line,
        )
        attribute_lineno_table[(True, 0)] = ckitcore.Attribute(
            fg=TextWidget.color_bar_error_fg, bg=None, line1=None
        )
        attribute_lineno_table[(True, 1)] = ckitcore.Attribute(
            fg=TextWidget.color_bar_error_fg,
            bg=TextWidget.color_bookmark1,
            line1=bookmark_line,
        )
        attribute_lineno_table[(True, 2)] = ckitcore.Attribute(
            fg=TextWidget.color_bar_error_fg,
            bg=TextWidget.color_bookmark2,
            line1=bookmark_line,
        )
        attribute_lineno_table[(True, 3)] = ckitcore.Attribute(
            fg=TextWidget.color_bar_error_fg,
            bg=TextWidget.color_bookmark3,
            line1=bookmark_line,
        )

        default_bg_color = None
        if self.doc.bg_color_name:
            default_bg_color = ckit_theme.getColor(self.doc.bg_color_name)

        attribute_table = {}
        bg_color_list = (
            default_bg_color,
            TextWidget.color_diff_bg1,
            TextWidget.color_diff_bg2,
            TextWidget.color_diff_bg3,
        )
        line0_list = (None, (LINE_DOT | LINE_BOTTOM, TextWidget.color_line_cursor))
        line1_list = (None, (LINE_BOTTOM, TextWidget.color_search_mark))
        for bg in range(4):
            bg_color = bg_color_list[bg]
            for line_cursor in (False, True):
                line0 = line0_list[line_cursor]
                for search_mark in (False, True):
                    line1 = line1_list[search_mark]
                    attribute_table[(Token_Text, bg, line_cursor, search_mark)] = (
                        ckitcore.Attribute(
                            fg=TextWidget.color_syntax_text,
                            bg=bg_color,
                            line0=line0,
                            line1=line1,
                        )
                    )
                    attribute_table[(Token_Keyword, bg, line_cursor, search_mark)] = (
                        ckitcore.Attribute(
                            fg=TextWidget.color_syntax_keyword,
                            bg=bg_color,
                            line0=line0,
                            line1=line1,
                        )
                    )
                    attribute_table[(Token_Name, bg, line_cursor, search_mark)] = (
                        ckitcore.Attribute(
                            fg=TextWidget.color_syntax_name,
                            bg=bg_color,
                            line0=line0,
                            line1=line1,
                        )
                    )
                    attribute_table[(Token_Number, bg, line_cursor, search_mark)] = (
                        ckitcore.Attribute(
                            fg=TextWidget.color_syntax_number,
                            bg=bg_color,
                            line0=line0,
                            line1=line1,
                        )
                    )
                    attribute_table[(Token_String, bg, line_cursor, search_mark)] = (
                        ckitcore.Attribute(
                            fg=TextWidget.color_syntax_string,
                            bg=bg_color,
                            line0=line0,
                            line1=line1,
                        )
                    )
                    attribute_table[(Token_Preproc, bg, line_cursor, search_mark)] = (
                        ckitcore.Attribute(
                            fg=TextWidget.color_syntax_preproc,
                            bg=bg_color,
                            line0=line0,
                            line1=line1,
                        )
                    )
                    attribute_table[(Token_Comment, bg, line_cursor, search_mark)] = (
                        ckitcore.Attribute(
                            fg=TextWidget.color_syntax_comment,
                            bg=bg_color,
                            line0=line0,
                            line1=line1,
                        )
                    )
                    attribute_table[(Token_Space, bg, line_cursor, search_mark)] = (
                        ckitcore.Attribute(
                            fg=TextWidget.color_syntax_space,
                            bg=bg_color,
                            line0=line0,
                            line1=line1,
                        )
                    )
                    attribute_table[(Token_Error, bg, line_cursor, search_mark)] = (
                        ckitcore.Attribute(
                            fg=TextWidget.color_syntax_error,
                            bg=bg_color,
                            line0=line0,
                            line1=line1,
                        )
                    )

        if active:
            attribute_select = ckitcore.Attribute(
                fg=TextWidget.color_select_fg, bg=TextWidget.color_select_bg
            )
            attribute_select_search_mark = ckitcore.Attribute(
                fg=TextWidget.color_select_fg,
                bg=TextWidget.color_select_bg,
                line1=line1_list[1],
            )
        else:
            attribute_select = ckitcore.Attribute(
                fg=TextWidget.color_select_fg, bg=TextWidget.color_select_bg_inactive
            )
            attribute_select_search_mark = ckitcore.Attribute(
                fg=TextWidget.color_select_fg,
                bg=TextWidget.color_select_bg_inactive,
                line1=line1_list[1],
            )

        white_space = " " * width

        for i in range(height):
            line = i + self.visible_first_line

            if line_range and not (line_range[0] <= line < line_range[1]):
                continue

            if line < len(self.doc.lines):
                bg = self.doc.lines[line].bg

                line_cursor = 0
                if paint_cursor and active and line == cursor.line:
                    line_cursor = 1

                search_hit = []
                if self.search_object:
                    search_pos = 0
                    while True:
                        search_result = self.search_object.search(
                            self.doc.lines[line].s, search_pos
                        )
                        if search_result and search_result[1] != search_pos:
                            search_hit.append(search_result)
                            search_pos = search_result[1]
                        else:
                            break

                # Draw line numbers.
                if self.show_lineno:
                    str_lineno = str(line + 1)
                    self.window.putString(
                        x,
                        y + i,
                        width,
                        1,
                        attribute_lineno_table[
                            (
                                self.doc.lines[line].modified,
                                self.doc.lines[line].bookmark,
                            )
                        ],
                        " " * (keta - len(str_lineno) + 1) + str_lineno,
                    )
                    self.window.putString(
                        x + lineno_width - 1,
                        y + i,
                        width - lineno_width + 1,
                        1,
                        attribute_whitespace,
                        " ",
                    )
                else:
                    self.window.putString(
                        x, y + i, width, 1, attribute_whitespace, "  "
                    )

                paint_offset = [0]

                def paintToken(s, begin, end, attr_normal, attr_gray):
                    if 0:
                        s2 = ckit_misc.expandTab(
                            self.window, s[begin:end], tab_width, offset=paint_offset[0]  # noqa: B023  # Called before the next loop iteration.
                        )
                        self.window.putString(
                            x2,
                            y + i,  # noqa: B023  # Called before the next loop iteration.
                            width2,
                            1,
                            attr_normal,
                            s2,
                            offset=paint_offset[0] - self.visible_first_column,  # noqa: B023  # Called before the next loop iteration.
                        )
                        paint_offset[0] += self.window.getStringWidth(s2)  # noqa: B023  # Called before the next loop iteration.

                    if 1:
                        pos = begin

                        while True:
                            tab_pos = s.find("\t", pos, end)
                            if show_space:
                                space_pos = s.find(" ", pos, end)
                            else:
                                space_pos = -1
                            if show_wspace:
                                wspace_pos = s.find("　", pos, end)
                            else:
                                wspace_pos = -1

                            if (
                                tab_pos >= 0
                                and (space_pos < 0 or tab_pos < space_pos)
                                and (wspace_pos < 0 or tab_pos < wspace_pos)
                            ):
                                new_pos = tab_pos
                            elif (
                                space_pos >= 0
                                and (tab_pos < 0 or space_pos < tab_pos)
                                and (wspace_pos < 0 or space_pos < wspace_pos)
                            ):
                                new_pos = space_pos
                            elif (
                                wspace_pos >= 0
                                and (tab_pos < 0 or wspace_pos < tab_pos)
                                and (space_pos < 0 or wspace_pos < space_pos)
                            ):
                                new_pos = wspace_pos
                            else:
                                s2 = s[pos:end]
                                self.window.putString(
                                    x2,
                                    y + i,  # noqa: B023  # Called before the next loop iteration.
                                    width2,
                                    1,
                                    attr_normal,
                                    s2,
                                    offset=paint_offset[0] - self.visible_first_column,  # noqa: B023  # Called before the next loop iteration.
                                )
                                paint_offset[0] += self.window.getStringWidth(s2)  # noqa: B023  # Called before the next loop iteration.
                                break

                            if pos < new_pos:
                                s2 = s[pos:new_pos]
                                self.window.putString(
                                    x2,
                                    y + i,  # noqa: B023  # Called before the next loop iteration.
                                    width2,
                                    1,
                                    attr_normal,
                                    s2,
                                    offset=paint_offset[0] - self.visible_first_column,  # noqa: B023  # Called before the next loop iteration.
                                )
                                paint_offset[0] += self.window.getStringWidth(s2)  # noqa: B023  # Called before the next loop iteration.

                            if new_pos == tab_pos:
                                if show_tab:
                                    attr = attr_gray
                                else:
                                    attr = attr_normal
                                s2 = altchar_tab
                                s2_width = 1
                                while (paint_offset[0] + s2_width) % tab_width:  # noqa: B023  # Called before the next loop iteration.
                                    s2 += " "
                                    s2_width += 1

                            elif new_pos == space_pos:
                                if show_space:
                                    attr = attr_gray
                                else:
                                    attr = attr_normal
                                s2 = altchar_space
                                s2_width = 1

                            elif new_pos == wspace_pos:
                                if show_wspace:
                                    attr = attr_gray
                                else:
                                    attr = attr_normal
                                s2 = altchar_wspace
                                s2_width = 2

                            self.window.putString(
                                x2,
                                y + i,  # noqa: B023  # Called before the next loop iteration.
                                width2,
                                1,
                                attr,
                                s2,
                                offset=paint_offset[0] - self.visible_first_column,  # noqa: B023  # Called before the next loop iteration.
                            )
                            paint_offset[0] += s2_width  # noqa: B023  # Called before the next loop iteration.

                            pos = new_pos + 1

                def paintNormal(s, begin, end, tokens):
                    for t in range(len(tokens)):
                        pos1 = tokens[t][0]
                        if t + 1 < len(tokens):
                            pos2 = tokens[t + 1][0]
                        else:
                            pos2 = end

                        if pos2 <= begin:
                            continue
                        if pos1 >= end:
                            break

                        pos1 = max(pos1, begin)
                        pos2 = min(pos2, end)

                        for h in range(len(search_hit)):  # noqa: B023  # Called before the next loop iteration.
                            if search_hit[h][1] <= pos1:  # noqa: B023  # Called before the next loop iteration.
                                continue
                            if search_hit[h][0] >= pos2:  # noqa: B023  # Called before the next loop iteration.
                                break

                            hit1 = max(search_hit[h][0], pos1)  # noqa: B023  # Called before the next loop iteration.
                            hit2 = min(search_hit[h][1], pos2)  # noqa: B023  # Called before the next loop iteration.

                            if pos1 < hit1:
                                paintToken(
                                    s,
                                    pos1,
                                    hit1,
                                    attribute_table[
                                        (tokens[t][1], bg, line_cursor, False)  # noqa: B023  # Called before the next loop iteration.
                                    ],
                                    attribute_table[
                                        (Token_Space, bg, line_cursor, False)  # noqa: B023  # Called before the next loop iteration.
                                    ],
                                )

                            if hit1 < hit2:
                                paintToken(
                                    s,
                                    hit1,
                                    hit2,
                                    attribute_table[
                                        (tokens[t][1], bg, line_cursor, True)  # noqa: B023  # Called before the next loop iteration.
                                    ],
                                    attribute_table[
                                        (Token_Space, bg, line_cursor, True)  # noqa: B023  # Called before the next loop iteration.
                                    ],
                                )

                            pos1 = hit2

                        paintToken(
                            s,
                            pos1,
                            pos2,
                            attribute_table[(tokens[t][1], bg, line_cursor, False)],  # noqa: B023  # Called before the next loop iteration.
                            attribute_table[(Token_Space, bg, line_cursor, False)],  # noqa: B023  # Called before the next loop iteration.
                        )

                def paintSelected(s, begin, end):
                    pos1 = begin
                    pos2 = end

                    for h in range(len(search_hit)):  # noqa: B023  # Called before the next loop iteration.
                        if search_hit[h][1] <= pos1:  # noqa: B023  # Called before the next loop iteration.
                            continue
                        if search_hit[h][0] >= pos2:  # noqa: B023  # Called before the next loop iteration.
                            break

                        hit1 = max(search_hit[h][0], pos1)  # noqa: B023  # Called before the next loop iteration.
                        hit2 = min(search_hit[h][1], pos2)  # noqa: B023  # Called before the next loop iteration.

                        if pos1 < hit1:
                            paintToken(
                                s, pos1, hit1, attribute_select, attribute_select
                            )

                        if hit1 < hit2:
                            paintToken(
                                s,
                                hit1,
                                hit2,
                                attribute_select_search_mark,
                                attribute_select_search_mark,
                            )

                        pos1 = hit2

                    paintToken(s, pos1, pos2, attribute_select, attribute_select)

                def paintEnd(selected):
                    if line == len(self.doc.lines) - 1:  # noqa: B023  # Called before the next loop iteration.
                        s = altchar_fileend
                        if show_fileend:
                            attr = attribute_table[
                                (Token_Space, bg, line_cursor, False)  # noqa: B023  # Called before the next loop iteration.
                            ]
                        else:
                            s = " "
                            attr = attribute_table[(Token_Text, bg, line_cursor, False)]  # noqa: B023  # Called before the next loop iteration.
                    else:
                        s = altchar_lineend
                        if show_lineend:
                            attr = attribute_table[
                                (Token_Space, bg, line_cursor, False)  # noqa: B023  # Called before the next loop iteration.
                            ]
                        else:
                            attr = attribute_table[(Token_Text, bg, line_cursor, False)]  # noqa: B023  # Called before the next loop iteration.

                    if selected:
                        attr = attribute_select

                    self.window.putString(
                        x2,
                        y + i,  # noqa: B023  # Called before the next loop iteration.
                        width2,
                        1,
                        attr,
                        s,
                        offset=paint_offset[0] - self.visible_first_column,  # noqa: B023  # Called before the next loop iteration.
                    )
                    paint_offset[0] += self.window.getStringWidth(s)  # noqa: B023  # Called before the next loop iteration.

                def paintSpace(space_width, selected):
                    offset2 = max(paint_offset[0] - self.visible_first_column, 0)  # noqa: B023  # Called before the next loop iteration.
                    if selected:
                        attr = attribute_select
                    else:
                        attr = attribute_table[(Token_Text, bg, line_cursor, False)]  # noqa: B023  # Called before the next loop iteration.
                    self.window.putString(
                        x2,
                        y + i,  # noqa: B023  # Called before the next loop iteration.
                        min(offset2 + space_width, width2),
                        1,
                        attr,
                        white_space,
                        offset=offset2,
                    )
                    paint_offset[0] += space_width  # noqa: B023  # Called before the next loop iteration.

                tokens = self.doc.lines[line].tokens

                if tokens is None:
                    print("no syntax info", line)
                    continue

                tokens = Token.unpack(tokens)

                # Lines entirely outside the selection.
                if (
                    self.selection.direction == 0
                    or line < selection_left.line
                    or line > selection_right.line
                ):
                    paintNormal(
                        self.doc.lines[line].s, 0, len(self.doc.lines[line].s), tokens
                    )
                    paintEnd(selected=False)
                    paintSpace(space_width=width2, selected=False)

                # Lines within the rectangular selection.
                elif block_mode:
                    sel_left = self.getIndexFromColumn(
                        line,
                        selection_rect_column_left,
                        TextWidget.BLOCK_SELECTION_COLUMN_OFFSET,
                    )
                    sel_right = self.getIndexFromColumn(
                        line,
                        selection_rect_column_right,
                        TextWidget.BLOCK_SELECTION_COLUMN_OFFSET,
                    )

                    paintNormal(self.doc.lines[line].s, 0, sel_left, tokens)
                    paintSelected(self.doc.lines[line].s, sel_left, sel_right)
                    paintNormal(
                        self.doc.lines[line].s,
                        sel_right,
                        len(self.doc.lines[line].s),
                        tokens,
                    )
                    paintEnd(
                        selected=(
                            selection_rect_column_left
                            <= paint_offset[0]
                            < selection_rect_column_right
                        )
                    )
                    if paint_offset[0] < selection_rect_column_left:
                        paintSpace(
                            selection_rect_column_left - paint_offset[0], selected=False
                        )
                    if paint_offset[0] < selection_rect_column_right:
                        paintSpace(
                            selection_rect_column_right - paint_offset[0], selected=True
                        )
                    paintSpace(space_width=width2, selected=False)

                else:
                    # Lines entirely within the selection.
                    if selection_left.line < line < selection_right.line:
                        paintSelected(
                            self.doc.lines[line].s, 0, len(self.doc.lines[line].s)
                        )
                        paintSelected(altchar_lineend, 0, 1)
                        paintSpace(space_width=width2, selected=False)

                    # Partially selected lines.
                    else:
                        sel_left = 0
                        sel_right = len(self.doc.lines[line].s)

                        if line == selection_left.line:
                            sel_left = selection_left.index
                        if line == selection_right.line:
                            sel_right = selection_right.index

                        paintNormal(self.doc.lines[line].s, 0, sel_left, tokens)
                        paintSelected(self.doc.lines[line].s, sel_left, sel_right)
                        paintNormal(
                            self.doc.lines[line].s,
                            sel_right,
                            len(self.doc.lines[line].s),
                            tokens,
                        )
                        paintEnd(selected=(line < selection_right.line))
                        paintSpace(space_width=width2, selected=False)

            else:
                self.window.putString(
                    x, y + i, width, 1, attribute_whitespace, " " * lineno_width
                )
                self.window.putString(
                    x2, y + i, width2, 1, attribute_whitespace, white_space
                )

        # Show the scroll position using character-cell background colors.
        left, top, right, bottom = self.rectScrollbar()
        track_height = bottom - top
        thumb_height = min(
            track_height,
            max(
                1,
                track_height
                * self.height
                // max(len(self.doc.lines) + self.height - 1, 1),
            ),
        )
        thumb_pos = (
            (track_height - thumb_height)
            * self.visible_first_line
            // len(self.doc.lines)
        )
        track_attr = ckitcore.Attribute(bg=ckit_theme.getColor("bg"))
        thumb_attr = ckitcore.Attribute(bg=ckit_theme.getColor("select_bg"))
        for row in range(track_height):
            attr = (
                thumb_attr
                if thumb_pos <= row < thumb_pos + thumb_height
                else track_attr
            )
            self.window.putString(
                left, top + row, right - left, 1, attr, " " * (right - left)
            )

        if self.enable_cursor and self.window.isActive():
            x, y = self.getCursorPos()
            if (
                paint_cursor
                and self.x <= x < self.x + self.width
                and self.y <= y < self.y + self.height
            ):
                self.window.setCursorPos(x, y)
            else:
                self.window.setCursorPos(-1, -1)

        # Let the normal paint timer flush the buffer to avoid flicker.

    ## \~japanese
    # message_handler(message, timeout, error)へそのまま委譲します。未設定なら何もしません。戻り値None。
    # \~english
    # Forward message, timeout and error unchanged to message_handler, or do nothing if absent. Return None.
    # \~
    def setMessage(self, message, timeout=None, error=None):
        if self.message_handler:
            self.message_handler(message, timeout, error)

    ## \~japanese
    # 親の移動時に呼び、候補窓を閉じます。
    # \~english
    # Call when the parent moves to close completion candidates.
    # \~
    def onWindowMove(self):
        self.closeList()

    ## \~japanese
    # 親のサイズ変更時に呼び、候補窓を閉じます。部品のsetPosSize/paintは別途必要です。
    # \~english
    # Call when the parent resizes to close completion candidates; setPosSize/paint are separate.
    # \~
    def onWindowSize(self):
        self.closeList()

    ## \~japanese
    # mode.completionへ要求します。候補なしなら終了、auto_fix=Trueで1件なら即置換、それ以外は候補窓を表示します。
    # Enterで確定、Tabで共通部分を挿入。既存窓の破棄は親のdelayedCallで50ms遅延します。
    # \~english
    # Request mode.completion. No candidates returns; auto_fix=True with one candidate replaces immediately; otherwise show a candidate window.
    # Enter commits; Tab inserts the common prefix. Existing-window destruction uses the parent delayedCall with a 50 ms delay.
    # \~
    def popupList(self, auto_fix=True):
        self.closeList(delay=True)

        cursor = self.selection.cursor()
        completion_result = self.doc.mode.completion.getCandidateList(
            self.window, self, cursor
        )
        if completion_result is None or not completion_result.items:
            return

        if auto_fix and len(completion_result.items) == 1:
            self.modifyText(
                completion_result.left,
                completion_result.right,
                completion_result.items[0],
            )
            return

        candidate_ref: _weakref.ReferenceType[CandidateWindow] | None = None

        def onKeyDown(vk, mod):
            if mod == 0 and vk in (VK_RETURN, VK_TAB):
                candidate_window = candidate_ref() if candidate_ref is not None else None
                if candidate_window is None or self.candidate_window is not candidate_window:
                    return True
                if vk == VK_RETURN:
                    selection = candidate_window.getSelection()
                    text = completion_result.items[selection]
                    self.closeList()
                    self.modifyText(
                        completion_result.left, completion_result.right, text
                    )
                    return True

                elif vk == VK_TAB:
                    common_prefix = completion_result.items[0]
                    for item in completion_result.items:
                        while common_prefix:
                            if item.startswith(common_prefix):
                                break
                            common_prefix = common_prefix[:-1]
                        if not common_prefix:
                            break
                    if common_prefix and (
                        self.getText(
                            completion_result.left, completion_result.right
                        )
                        != common_prefix
                    ):
                        self.modifyText(
                            completion_result.left,
                            completion_result.right,
                            common_prefix,
                        )
                        self.popupList(auto_fix=auto_fix)
                    return True

        self.candidate_window = CandidateWindow(
            0,
            0,
            10,
            1,
            80,
            16,
            self.window,
            keydown_hook=onKeyDown,
        )
        candidate_ref = _weakref.ref(self.candidate_window)

        left_string = self.doc.lines[completion_result.left.line].s[
            : completion_result.left.index
        ]
        x = (
            self.x
            + self.lineNoWidth()
            + self.window.getStringWidth(left_string, self.doc.mode.tab_width)
            - self.visible_first_column
        )
        y = self.y + completion_result.left.line - self.visible_first_line

        screen_x, screen_y1 = self.window.charToScreen(x, y)
        screen_x, screen_y2 = self.window.charToScreen(x, y + 1)

        self.candidate_window.setItems(
            screen_x,
            screen_y1,
            screen_y2,
            completion_result.items,
            completion_result.selection,
        )

    ## \~japanese
    # 候補窓を切離して破棄します。delay=Trueなら親delayedCallで50ms後に破棄します。戻り値None。
    # \~english
    # Detach/destroy the completion window; delay=True schedules destruction after 50 ms through the parent delayedCall. Return None.
    # \~
    def closeList(self, delay=False):
        if self.candidate_window:
            if delay:
                # Delay destruction to avoid flicker.
                class DelayedCall:
                    candidate_window: CandidateWindow

                    def __call__(self):
                        self.candidate_window.destroy()

                delay = DelayedCall()
                delay.candidate_window = self.candidate_window
                self.window.delayedCall(delay, 50)
            else:
                self.candidate_window.destroy()
            self.candidate_window = None

    ## \~japanese
    # 現在保持する候補窓があればTrue。遅延破棄待ちの旧窓は含めません。
    # \~english
    # Return True when a current candidate window is retained; exclude old windows waiting for delayed destruction.
    # \~
    def isListOpened(self):
        return self.candidate_window is not None

    ## \~japanese
    # 候補窓→副モード逆順→主モード→自身のcommand_<name>の順で探索し、扱えばTrue、不在ならFalse。
    # 候補窓で扱えなければ閉じます。ハンドラの戻り値は使わず、例外は伝播します。
    # \~english
    # Dispatch through candidates, reverse minor modes, major mode, then command_<name> on this control; return True if handled, else False.
    # Close candidates when they cannot handle the command. Ignore handler return values; errors propagate.
    # \~
    def executeCommand(self, name, info):
        if self.candidate_window:
            if self.candidate_window.executeCommand(name, info):
                return True
            else:
                self.closeList()

        for mode in reversed(self.doc.minor_mode_list):
            if mode.executeCommand(name, info):
                return True

        if self.doc.mode.executeCommand(name, info):
            return True

        try:
            command = getattr(self, "command_" + name)
        except AttributeError:
            return False

        command(info)
        return True

    ## \~japanese
    # 候補窓→副モード逆順→主モード→自身の順でコマンド名をyieldします。重複を除きません。
    # \~english
    # Yield command names from candidates, reverse minor modes, major mode, then this control, without deduplication.
    # \~
    def enumCommand(self):
        if self.candidate_window:
            for item in self.candidate_window.enumCommand():
                yield item

        for mode in reversed(self.doc.minor_mode_list):
            for item in mode.enumCommand():
                yield item

        for item in self.doc.mode.enumCommand():
            yield item

        for attr in dir(self):
            if attr.startswith("command_"):
                yield attr[len("command_") :]

    # --------------------------------------------------------
    # The following methods can be bound to keys.
    # --------------------------------------------------------

    ## \~japanese
    # カーソルを左1文字へ移動します。
    # \~english
    # Move the caret to one character left.
    # \~
    def command_CursorLeft(self, info):
        if self.selection.direction == 0:
            cursor = self.selection.cursor().left()
        else:
            cursor = self.selection.left()

        self.setCursor(cursor)

    ## \~japanese
    # カーソルを右1文字へ移動します。
    # \~english
    # Move the caret to one character right.
    # \~
    def command_CursorRight(self, info):
        if self.selection.direction == 0:
            cursor = self.selection.cursor().right()
        else:
            cursor = self.selection.right()

        self.setCursor(cursor)

    ## \~japanese
    # カーソルを左の単語境界へ移動します。
    # \~english
    # Move the caret to the left word boundary.
    # \~
    def command_CursorWordLeft(self, info):
        cursor = self.selection.cursor().wordLeft()

        self.setCursor(cursor)

    ## \~japanese
    # カーソルを右の単語境界へ移動します。
    # \~english
    # Move the caret to the right word boundary.
    # \~
    def command_CursorWordRight(self, info):
        cursor = self.selection.cursor().wordRight()

        self.setCursor(cursor)

    ## \~japanese
    # 前のタブ桁位置へ移動します。
    # \~english
    # Move to the previous tab column.
    # \~
    def command_CursorTabLeft(self, info):
        cursor = self.selection.cursor().tabLeft()

        self.setCursor(cursor)

    ## \~japanese
    # カーソルを行頭へ移動します。
    # \~english
    # Move the caret to line start.
    # \~
    def command_CursorLineBegin(self, info):
        cursor = self.selection.cursor().lineBegin()

        self.setCursor(cursor)

    ## \~japanese
    # カーソルを行末へ移動します。
    # \~english
    # Move the caret to line end.
    # \~
    def command_CursorLineEnd(self, info):
        cursor = self.selection.cursor().lineEnd()

        self.setCursor(cursor)

    ## \~japanese
    # 行頭の空白を除く最初の位置へ移動します。同位置ならinfo.result=False。
    # \~english
    # Move after leading whitespace; set info.result=False if already there.
    # \~
    def command_CursorLineFirstGraph(self, info):
        cursor = self.selection.cursor()
        cursor2 = cursor.lineFirstGraph()

        if cursor == cursor2:
            info.result = False
            return

        self.setCursor(cursor2)

    ## \~japanese
    # カーソルを上1行へ移動します。
    # \~english
    # Move the caret to one line up.
    # \~
    def command_CursorUp(self, info):
        cursor = self.selection.cursor().up()

        self.setCursor(cursor, update_ideal_column=False)

    ## \~japanese
    # カーソルを下1行へ移動します。
    # \~english
    # Move the caret to one line down.
    # \~
    def command_CursorDown(self, info):
        cursor = self.selection.cursor().down()

        self.setCursor(cursor, update_ideal_column=False)

    ## \~japanese
    # カーソルを上1ページへ移動します。
    # \~english
    # Move the caret to one page up.
    # \~
    def command_CursorPageUp(self, info):
        step = self.height

        self.visible_first_line = max(self.visible_first_line - step, 0)
        cursor = self.selection.cursor().up(step)

        self.setCursor(cursor, update_ideal_column=False, paint=False)

        self.paint()

    ## \~japanese
    # カーソルを下1ページへ移動します。
    # \~english
    # Move the caret to one page down.
    # \~
    def command_CursorPageDown(self, info):
        step = self.height

        self.visible_first_line = min(
            self.visible_first_line + step, len(self.doc.lines) - 1
        )
        cursor = self.selection.cursor().down(step)

        self.setCursor(cursor, update_ideal_column=False, paint=False)

        self.paint()

    ## \~japanese
    # カーソルを対応括弧へ移動します。
    # \~english
    # Move the caret to the corresponding bracket.
    # \~
    def command_CursorCorrespondingBracket(self, info):
        cursor = self.selection.cursor().correspondingBracket(self.doc.mode.bracket)
        self.setCursor(cursor)

    ## \~japanese
    # 前の変更行を検索し、移動します。未発見は通知します。
    # \~english
    # Move to the previous match for a modified line; report when absent.
    # \~
    def command_CursorModifiedLinePrev(self, info):
        def func(line):
            return line.modified

        if not self.seek(-1, func):
            self.setMessage(
                ckit_resource.strings["modified_line_not_found"], 1000, error=True
            )

    ## \~japanese
    # 次の変更行を検索し、移動します。未発見は通知します。
    # \~english
    # Move to the next match for a modified line; report when absent.
    # \~
    def command_CursorModifiedLineNext(self, info):
        def func(line):
            return line.modified

        if not self.seek(+1, func):
            self.setMessage(
                ckit_resource.strings["modified_line_not_found"], 1000, error=True
            )

    ## \~japanese
    # 前の印のある行を検索し、移動します。未発見は通知します。
    # \~english
    # Move to the previous match for a bookmarked line; report when absent.
    # \~
    def command_CursorBookmarkPrev(self, info):
        def func(line):
            return line.bookmark

        if not self.seek(-1, func):
            self.setMessage(
                ckit_resource.strings["bookmark_not_found"], 1000, error=True
            )

    ## \~japanese
    # 次の印のある行を検索し、移動します。未発見は通知します。
    # \~english
    # Move to the next match for a bookmarked line; report when absent.
    # \~
    def command_CursorBookmarkNext(self, info):
        def func(line):
            return line.bookmark

        if not self.seek(+1, func):
            self.setMessage(
                ckit_resource.strings["bookmark_not_found"], 1000, error=True
            )

    ## \~japanese
    # 前の変更または印のある行を検索し、移動します。未発見は通知します。
    # \~english
    # Move to the previous match for a modified or bookmarked line; report when absent.
    # \~
    def command_CursorModifiedOrBookmarkPrev(self, info):
        def func(line):
            return line.modified or line.bookmark

        if not self.seek(-1, func):
            self.setMessage(
                ckit_resource.strings["modified_line_or_bookmark_not_found"],
                1000,
                error=True,
            )

    ## \~japanese
    # 次の変更または印のある行を検索し、移動します。未発見は通知します。
    # \~english
    # Move to the next match for a modified or bookmarked line; report when absent.
    # \~
    def command_CursorModifiedOrBookmarkNext(self, info):
        def func(line):
            return line.modified or line.bookmark

        if not self.seek(+1, func):
            self.setMessage(
                ckit_resource.strings["modified_line_or_bookmark_not_found"],
                1000,
                error=True,
            )

    ## \~japanese
    # カーソルを文書先頭へ移動します。
    # \~english
    # Move the caret to document beginning.
    # \~
    def command_CursorDocumentBegin(self, info):
        cursor = self.pointDocumentBegin()

        self.setCursor(cursor)

    ## \~japanese
    # カーソルを文書末尾へ移動します。
    # \~english
    # Move the caret to document end.
    # \~
    def command_CursorDocumentEnd(self, info):
        cursor = self.pointDocumentEnd()

        self.setCursor(cursor)

    ## \~japanese
    # 3行上へスクロールします。
    # \~english
    # Scroll three lines up.
    # \~
    def command_ScrollUp(self, info):
        self.scrollV(-3)

    ## \~japanese
    # 3行下へスクロールします。
    # \~english
    # Scroll three lines down.
    # \~
    def command_ScrollDown(self, info):
        self.scrollV(3)

    ## \~japanese
    # カーソル行を中央へスクロールします。
    # \~english
    # Scroll the caret line to the center.
    # \~
    def command_ScrollCursorCenter(self, info):
        cursor = self.selection.cursor()

        self.visible_first_line = cursor.line - self.height // 2
        self.visible_first_line = max(self.visible_first_line, 0)

        self.makeVisible(cursor)

    ## \~japanese
    # 固定端を保持して選択を左1文字へ伸縮します。
    # \~english
    # Extend selection to one character left while retaining anchor.
    # \~
    def command_SelectLeft(self, info):
        cursor = self.selection.cursor().left(block_mode=self.selection.block_mode)
        anchor = self.selection.anchor()

        self.setSelection(anchor, cursor)

    ## \~japanese
    # 固定端を保持して選択を右1文字へ伸縮します。
    # \~english
    # Extend selection to one character right while retaining anchor.
    # \~
    def command_SelectRight(self, info):
        cursor = self.selection.cursor().right(block_mode=self.selection.block_mode)
        anchor = self.selection.anchor()

        self.setSelection(anchor, cursor)

    ## \~japanese
    # 固定端を保持して選択を左の単語境界へ伸縮します。
    # \~english
    # Extend selection to the left word boundary while retaining anchor.
    # \~
    def command_SelectWordLeft(self, info):
        cursor = self.selection.cursor().wordLeft()
        anchor = self.selection.anchor()

        self.setSelection(anchor, cursor)

    ## \~japanese
    # 固定端を保持して選択を右の単語境界へ伸縮します。
    # \~english
    # Extend selection to the right word boundary while retaining anchor.
    # \~
    def command_SelectWordRight(self, info):
        cursor = self.selection.cursor().wordRight()
        anchor = self.selection.anchor()

        self.setSelection(anchor, cursor)

    ## \~japanese
    # 固定端を保持して選択を行頭へ伸縮します。
    # \~english
    # Extend selection to line start while retaining anchor.
    # \~
    def command_SelectLineBegin(self, info):
        cursor = self.selection.cursor().lineBegin()
        anchor = self.selection.anchor()

        self.setSelection(anchor, cursor)

    ## \~japanese
    # 固定端を保持して選択を行末へ伸縮します。
    # \~english
    # Extend selection to line end while retaining anchor.
    # \~
    def command_SelectLineEnd(self, info):
        cursor = self.selection.cursor().lineEnd()
        anchor = self.selection.anchor()

        self.setSelection(anchor, cursor)

    ## \~japanese
    # 固定端を保持して選択を上1行へ伸縮します。
    # \~english
    # Extend selection to one line up while retaining anchor.
    # \~
    def command_SelectUp(self, info):
        cursor = self.selection.cursor().up(block_mode=self.selection.block_mode)
        anchor = self.selection.anchor()

        self.setSelection(anchor, cursor, update_ideal_column=False)

    ## \~japanese
    # 固定端を保持して選択を下1行へ伸縮します。
    # \~english
    # Extend selection to one line down while retaining anchor.
    # \~
    def command_SelectDown(self, info):
        cursor = self.selection.cursor().down(block_mode=self.selection.block_mode)
        anchor = self.selection.anchor()

        self.setSelection(anchor, cursor, update_ideal_column=False)

    ## \~japanese
    # 固定端を保持して選択を上1ページへ伸縮します。
    # \~english
    # Extend selection to one page up while retaining anchor.
    # \~
    def command_SelectPageUp(self, info):
        step = self.height

        cursor = self.selection.cursor().up(step, block_mode=self.selection.block_mode)
        anchor = self.selection.anchor()

        self.setSelection(anchor, cursor, update_ideal_column=False)

    ## \~japanese
    # 固定端を保持して選択を下1ページへ伸縮します。
    # \~english
    # Extend selection to one page down while retaining anchor.
    # \~
    def command_SelectPageDown(self, info):
        step = self.height

        cursor = self.selection.cursor().down(
            step, block_mode=self.selection.block_mode
        )
        anchor = self.selection.anchor()

        self.setSelection(anchor, cursor, update_ideal_column=False)

    ## \~japanese
    # 固定端を保持して選択を対応括弧へ伸縮します。
    # \~english
    # Extend selection to the corresponding bracket while retaining anchor.
    # \~
    def command_SelectCorrespondingBracket(self, info):
        cursor = self.selection.cursor().correspondingBracket(self.doc.mode.bracket)
        anchor = self.selection.anchor()

        self.setSelection(anchor, cursor)

    ## \~japanese
    # 前の変更行を検索し、選択を伸縮します。未発見は通知します。
    # \~english
    # Extend selection to the previous match for a modified line; report when absent.
    # \~
    def command_SelectModifiedLinePrev(self, info):
        def func(line):
            return line.modified

        cursor = self.seek(-1, func, move_cursor=False)
        anchor = self.selection.anchor()

        if cursor:
            self.setSelection(anchor, cursor)
        else:
            self.setMessage(
                ckit_resource.strings["modified_line_not_found"], 1000, error=True
            )

    ## \~japanese
    # 次の変更行を検索し、選択を伸縮します。未発見は通知します。
    # \~english
    # Extend selection to the next match for a modified line; report when absent.
    # \~
    def command_SelectModifiedLineNext(self, info):
        def func(line):
            return line.modified

        cursor = self.seek(+1, func, move_cursor=False)
        anchor = self.selection.anchor()

        if cursor:
            self.setSelection(anchor, cursor)
        else:
            self.setMessage(
                ckit_resource.strings["modified_line_not_found"], 1000, error=True
            )

    ## \~japanese
    # 前の印のある行を検索し、選択を伸縮します。未発見は通知します。
    # \~english
    # Extend selection to the previous match for a bookmarked line; report when absent.
    # \~
    def command_SelectBookmarkPrev(self, info):
        def func(line):
            return line.bookmark

        cursor = self.seek(-1, func, move_cursor=False)
        anchor = self.selection.anchor()

        if cursor:
            self.setSelection(anchor, cursor)
        else:
            self.setMessage(
                ckit_resource.strings["bookmark_not_found"], 1000, error=True
            )

    ## \~japanese
    # 次の印のある行を検索し、選択を伸縮します。未発見は通知します。
    # \~english
    # Extend selection to the next match for a bookmarked line; report when absent.
    # \~
    def command_SelectBookmarkNext(self, info):
        def func(line):
            return line.bookmark

        cursor = self.seek(+1, func, move_cursor=False)
        anchor = self.selection.anchor()

        if cursor:
            self.setSelection(anchor, cursor)
        else:
            self.setMessage(
                ckit_resource.strings["bookmark_not_found"], 1000, error=True
            )

    ## \~japanese
    # 前の変更または印のある行を検索し、選択を伸縮します。未発見は通知します。
    # \~english
    # Extend selection to the previous match for a modified or bookmarked line; report when absent.
    # \~
    def command_SelectModifiedOrBookmarkPrev(self, info):
        def func(line):
            return line.modified or line.bookmark

        cursor = self.seek(-1, func, move_cursor=False)
        anchor = self.selection.anchor()

        if cursor:
            self.setSelection(anchor, cursor)
        else:
            self.setMessage(
                ckit_resource.strings["modified_line_or_bookmark_not_found"],
                1000,
                error=True,
            )

    ## \~japanese
    # 次の変更または印のある行を検索し、選択を伸縮します。未発見は通知します。
    # \~english
    # Extend selection to the next match for a modified or bookmarked line; report when absent.
    # \~
    def command_SelectModifiedOrBookmarkNext(self, info):
        def func(line):
            return line.modified or line.bookmark

        cursor = self.seek(+1, func, move_cursor=False)
        anchor = self.selection.anchor()

        if cursor:
            self.setSelection(anchor, cursor)
        else:
            self.setMessage(
                ckit_resource.strings["modified_line_or_bookmark_not_found"],
                1000,
                error=True,
            )

    ## \~japanese
    # 固定端を保持して選択を文書先頭へ伸縮します。
    # \~english
    # Extend selection to document beginning while retaining anchor.
    # \~
    def command_SelectDocumentBegin(self, info):
        cursor = self.pointDocumentBegin()
        anchor = self.selection.anchor()

        self.setSelection(anchor, cursor)

    ## \~japanese
    # 固定端を保持して選択を文書末尾へ伸縮します。
    # \~english
    # Extend selection to document end while retaining anchor.
    # \~
    def command_SelectDocumentEnd(self, info):
        cursor = self.pointDocumentEnd()
        anchor = self.selection.anchor()

        self.setSelection(anchor, cursor)

    ## \~japanese
    # 全体を通常選択します。
    # \~english
    # Select the entire document in normal mode.
    # \~
    def command_SelectDocument(self, info):
        anchor = self.pointDocumentBegin()
        cursor = self.pointDocumentEnd()

        self.setSelection(anchor, cursor, block_mode=False)
        self.paint()

    ## \~japanese
    # 現在カーソルを残して選択と矩形モードを解除します。
    # \~english
    # Clear selection/block mode while retaining the caret.
    # \~
    def command_SelectCancel(self, info):
        cursor = self.selection.cursor()

        self.setCursor(cursor)

    ## \~japanese
    # 選択を3行上へ伸縮してスクロールします。
    # \~english
    # Extend selection three lines up and scroll.
    # \~
    def command_SelectScrollUp(self, info):
        old_cursor = self.selection.cursor()
        cursor = self.selection.cursor()
        for i in range(3):
            cursor = cursor.up(block_mode=self.selection.block_mode)
        anchor = self.selection.anchor()

        self.setSelection(anchor, cursor, update_ideal_column=False)

        self.scrollV(cursor.line - old_cursor.line)

    ## \~japanese
    # 選択を3行下へ伸縮してスクロールします。
    # \~english
    # Extend selection three lines down and scroll.
    # \~
    def command_SelectScrollDown(self, info):
        old_cursor = self.selection.cursor()
        cursor = self.selection.cursor()
        for i in range(3):
            cursor = cursor.down(block_mode=self.selection.block_mode)

        anchor = self.selection.anchor()

        self.setSelection(anchor, cursor, update_ideal_column=False)

        self.scrollV(cursor.line - old_cursor.line)

    ## \~japanese
    # 現在の端点で矩形選択へ切り替えます。
    # \~english
    # Switch to rectangular selection with current endpoints.
    # \~
    def command_SelectBlock(self, info):
        cursor = self.selection.cursor()
        anchor = self.selection.anchor()

        self.setSelection(anchor, cursor, block_mode=True)

    ## \~japanese
    # 選択を既定改行へ置換します。
    # \~english
    # Replace the selection with the default line ending.
    # \~
    def command_InsertReturn(self, info):
        self.modifyText(text="\n")

    ## \~japanese
    # 選択を改行と元行先頭の空白・タブへ置換します。
    # \~english
    # Replace the selection with a line ending and the original line's leading spaces/tabs.
    # \~
    def command_InsertReturnAutoIndent(self, info):
        left = self.selection.left()

        s = self.doc.lines[left.line].s[: left.index]
        s2 = s.lstrip(" \t")
        indent = s[: len(s) - len(s2)]

        self.modifyText(text="\n" + indent)

    ## \~japanese
    # mode.tab_by_space/tab_widthに従いタブまたは次桁までの空白を挿入します。
    # \~english
    # Insert a tab or spaces to the next tab column according to mode.tab_by_space/tab_width.
    # \~
    def command_InsertTab(self, info):
        left = self.selection.left()

        if self.doc.mode.tab_by_space:
            tab_width = self.doc.mode.tab_width
            column1 = self.getColumnFromIndex(left.line, left.index)
            column2 = (column1 + tab_width) // tab_width * tab_width
            self.modifyText(text=" " * (column2 - column1))
        else:
            self.modifyText(text="\t")

    ## \~japanese
    # DeleteCharRightと同じ操作です。
    # \~english
    # Perform DeleteCharRight.
    # \~
    def command_Delete(self, info):
        self.command_DeleteCharRight(info)

    ## \~japanese
    # 選択または右1文字を削除します。
    # \~english
    # Delete selection or one character to the right.
    # \~
    def command_DeleteCharRight(self, info):
        if self.selection.direction == 0:
            left = self.selection.cursor()
            right = left.right()
            if left != right:
                self.modifyText(right, left, "")
        else:
            self.modifyText(text="")

    ## \~japanese
    # 選択または左1文字を削除します。
    # \~english
    # Delete selection or one character to the left.
    # \~
    def command_DeleteCharLeft(self, info):
        if self.selection.direction == 0:
            right = self.selection.cursor()
            left = right.left()
            if left != right:
                self.modifyText(left, right, "")
        else:
            self.modifyText(text="")

    ## \~japanese
    # 選択またはカーソル位置の単語を削除します。
    # \~english
    # Delete selection or the word at the caret.
    # \~
    def command_DeleteWord(self, info):
        if self.selection.direction == 0:
            cursor = self.selection.cursor()
            right = cursor.wordRight(False)
            left = right.wordLeft(False)
            if left != right:
                self.modifyText(right, left, "")
        else:
            self.modifyText(text="")

    ## \~japanese
    # 選択または右の単語境界まで削除します。
    # \~english
    # Delete selection or text to the right word boundary.
    # \~
    def command_DeleteWordRight(self, info):
        if self.selection.direction == 0:
            left = self.selection.cursor()
            right = left.wordRight(False)
            if left != right:
                self.modifyText(right, left, "")
        else:
            self.modifyText(text="")

    ## \~japanese
    # 選択または左の単語境界まで削除します。
    # \~english
    # Delete selection or text to the left word boundary.
    # \~
    def command_DeleteWordLeft(self, info):
        if self.selection.direction == 0:
            right = self.selection.cursor()
            left = right.wordLeft(False)
            if left != right:
                self.modifyText(left, right, "")
        else:
            self.modifyText(text="")

    ## \~japanese
    # 選択または現在行の本文を削除します。空行なら次行との改行も削除します。
    # \~english
    # Delete selection or current line body; on an empty line also delete its ending.
    # \~
    def command_DeleteLine(self, info):
        if self.selection.direction == 0:
            cursor = self.selection.cursor()
            left = cursor.lineBegin()
            right = cursor.lineEnd()
            if left == right:
                right = right.right()
            if left != right:
                self.modifyText(right, left, "")
        else:
            self.modifyText(text="")

    ## \~japanese
    # 選択または行末までを削除します。行末なら次行との改行を削除します。
    # \~english
    # Delete selection or to line end; at line end delete the ending.
    # \~
    def command_DeleteLineRight(self, info):
        if self.selection.direction == 0:
            left = self.selection.cursor()
            right = left.lineEnd()
            if left == right:
                right = right.right()
            if left != right:
                self.modifyText(right, left, "")
        else:
            self.modifyText(text="")

    ## \~japanese
    # 選択または行頭までを削除します。行頭なら前行との改行を削除します。
    # \~english
    # Delete selection or to line start; at line start delete the preceding ending.
    # \~
    def command_DeleteLineLeft(self, info):
        if self.selection.direction == 0:
            right = self.selection.cursor()
            left = right.lineBegin()
            if left == right:
                left = left.left()
            if left != right:
                self.modifyText(left, right, "")
        else:
            self.modifyText(text="")

    ## \~japanese
    # 選択をクリップボードへコピーします。無選択ならcopy_line_if_not_selectedに従い現在行をコピーします。
    # \~english
    # Copy selection to clipboard, or the current line when unselected and copy_line_if_not_selected is true.
    # \~
    def command_Copy(self, info):
        if self.selection.direction == 0:
            if self.doc.mode.copy_line_if_not_selected:
                left = self.selection.cursor().lineBegin()
                right = left.lineEnd().right()
                text = self.getText(left, right)
                ckit_misc.setClipboardText(text)
        else:
            text = self.getText(
                self.selection.left(), self.selection.right(), self.selection.block_mode
            )
            ckit_misc.setClipboardText(text)
            if self.selection.block_mode:
                TextWidget.rect_mode_clipboard_number = (
                    ckit_misc.getClipboardSequenceNumber()
                )

            if self.doc.mode.cancel_selection_on_copy:
                cursor = self.selection.cursor()
                self.setCursor(cursor)

    ## \~japanese
    # Copyと同じ対象をコピー後に削除します。readonlyでもクリップボードは更新し得ます。
    # \~english
    # Copy then delete the same range as Copy; the clipboard can change even when read-only.
    # \~
    def command_Cut(self, info):
        if self.selection.direction == 0:
            if self.doc.mode.copy_line_if_not_selected:
                left = self.selection.cursor().lineBegin()
                right = left.lineEnd().right()
                text = self.getText(left, right)
                ckit_misc.setClipboardText(text)
                self.modifyText(right, left, text="")
        else:
            text = self.getText(
                self.selection.left(), self.selection.right(), self.selection.block_mode
            )
            ckit_misc.setClipboardText(text)
            if self.selection.block_mode:
                TextWidget.rect_mode_clipboard_number = (
                    ckit_misc.getClipboardSequenceNumber()
                )

            self.modifyText(text="")

    ## \~japanese
    # クリップボード文字列を挿入します。矩形選択または直前の矩形コピーの連番一致時は矩形挿入です。
    # \~english
    # Insert clipboard text; use rectangular mode for a block selection or a matching last rectangular-copy sequence number.
    # \~
    def command_Paste(self, info):
        text = ckit_misc.getClipboardText()
        if text:
            text_block_mode = self.selection.block_mode or (
                TextWidget.rect_mode_clipboard_number
                == ckit_misc.getClipboardSequenceNumber()
            )
            self.modifyText(text=text, text_block_mode=text_block_mode)

    ## \~japanese
    # Undoを実行し、履歴がなければビープします。
    # \~english
    # Undo, beeping when there is no history.
    # \~
    def command_Undo(self, info):
        if not self.undo():
            ckit_misc.messageBeep()

    ## \~japanese
    # Redoを実行し、履歴がなければビープします。
    # \~english
    # Redo, beeping when there is no history.
    # \~
    def command_Redo(self, info):
        if not self.redo():
            ckit_misc.messageBeep()

    ## \~japanese
    # 複数行選択の非空白行へ1段の字下げを追加します。1行ならinfo.result=False。
    # \~english
    # Indent nonblank selected lines by one level; set info.result=False for a single-line selection.
    # \~
    def command_IndentSelection(self, info):
        left = self.selection.left()
        right = self.selection.right()
        if left.line == right.line:
            info.result = False
            return

        def func(s):
            if s.lstrip(" \t"):
                if self.doc.mode.tab_by_space:
                    return " " * self.doc.mode.tab_width + s
                else:
                    return "\t" + s
            return s

        self.replaceLines(func)

    ## \~japanese
    # 複数行選択の先頭空白/タブを除きます。1行ならinfo.result=False。
    # \~english
    # Remove leading spaces/tabs from multiple selected lines; set info.result=False for a single-line selection.
    # \~
    def command_UnindentSelection(self, info):
        left = self.selection.left()
        right = self.selection.right()
        if left.line == right.line:
            info.result = False
            return

        def func(s):
            for i in range(self.doc.mode.tab_width + 1):
                if i >= len(s):
                    break
                if s[i] == "\t":
                    i += 1
                    break
                if s[i] != " ":
                    break
            return s[i:]

        self.replaceLines(func)

    ## \~japanese
    # 補完候補を要求します。
    # \~english
    # Request completion candidates.
    # \~
    def command_CompleteAbbrev(self, info):
        self.popupList()

    ## \~japanese
    # 候補を閉じます。候補がなければinfo.result=False。
    # \~english
    # Close candidates, or set info.result=False when absent.
    # \~
    def command_CloseList(self, info):
        if self.isListOpened():
            self.closeList()
        else:
            info.result = False

    ## \~japanese
    # 現在行の印を1/0で巡回します。
    # \~english
    # Cycle the current line marker through 1/0.
    # \~
    def command_Bookmark1(self, info):
        cursor = self.selection.cursor()
        self.bookmark(cursor.line, [1, 0])

    ## \~japanese
    # 現在行の印を2/0で巡回します。
    # \~english
    # Cycle the current line marker through 2/0.
    # \~
    def command_Bookmark2(self, info):
        cursor = self.selection.cursor()
        self.bookmark(cursor.line, [2, 0])

    ## \~japanese
    # 現在行の印を3/0で巡回します。
    # \~english
    # Cycle the current line marker through 3/0.
    # \~
    def command_Bookmark3(self, info):
        cursor = self.selection.cursor()
        self.bookmark(cursor.line, [3, 0])

    ## \~japanese
    # 現在行の印を1/2/3/0で巡回します。
    # \~english
    # Cycle the current line marker through 1/2/3/0.
    # \~
    def command_Bookmark123(self, info):
        cursor = self.selection.cursor()
        self.bookmark(cursor.line, [1, 2, 3, 0])

    ## \~japanese
    # 診断用。現在行の本文・改行・背景番号と展開した構文トークンを標準出力へ出します。tokens未計算なら例外になります。
    # \~english
    # Diagnostic: print current line body, ending, background number and unpacked syntax tokens to stdout; uncomputed tokens cause an exception.
    # \~
    def command_DebugEdit(self, info):
        cursor = self.selection.cursor()
        print(
            [
                self.doc.lines[cursor.line].s,
                self.doc.lines[cursor.line].end,
                self.doc.lines[cursor.line].bg,
            ]
        )
        print(Token.unpack(self.doc.lines[cursor.line].tokens))


# --------------------------------------------------------------------


class CandidateWindow(ckit_textwindow.TextWindow):
    def __init__(
        self,
        x,
        y,
        min_width,
        min_height,
        max_width,
        max_height,
        parent_window,
        keydown_hook=None,
        selchange_handler=None,
    ):
        bg = ckit_theme.getColor("bg")
        fg = ckit_theme.getColor("fg")
        bg = ckit_theme._require_rgb(bg)
        fg = ckit_theme._require_rgb(fg)

        frame_color = (
            (bg[0] + fg[0]) // 2,
            (bg[1] + fg[1]) // 2,
            (bg[2] + fg[2]) // 2,
        )

        ckit_textwindow.TextWindow.__init__(
            self,
            x=x,
            y=y,
            width=5,
            height=5,
            origin=ORIGIN_X_LEFT | ORIGIN_Y_TOP,
            parent_window=parent_window,
            bg_color=ckit_theme.getColor("bg"),
            caret0_color=ckit_theme.getColor("caret0"),
            caret1_color=ckit_theme.getColor("caret1"),
            frame_color=frame_color,
            border_size=0,
            transparency=255,  # Use WS_EX_LAYERED to avoid flicker.
            show=False,
            resizable=False,
            title_bar=False,
            minimizebox=False,
            maximizebox=False,
            activate_handler=self.onActivate,
            keydown_handler=self.onKeyDown,
            char_handler=self.onChar,
            ncpaint=True,
        )

        with ckit_misc._cleanup_on_exit(ckit_textwindow.TextWindow.destroy, self, error_only=True):
            self.parent_window = parent_window

            self.min_width = min_width
            self.min_height = min_height
            self.max_width = max_width
            self.max_height = max_height

            self.keydown_hook = keydown_hook
            self.selchange_handler = selchange_handler

            self.setItems(x, y, y, [], 0)

    def setItems(self, x, y1, y2, items, select=0):
        # Adjust x to account for the window frame.
        char_x, _char_y = self.charToScreen(0, 0)
        window_rect = self.getWindowRect()
        x -= char_x - window_rect[0]

        max_item_width = 0
        for item in items:
            if isinstance(item, list) or isinstance(item, tuple):  # noqa: SIM101  # Retain short-circuit evaluation; excluded from cleanup for performance.
                item = item[0]
            item_width = self.getStringWidth(item)
            if item_width > max_item_width:  # noqa: PLR1730  # Keep conditional updates; min/max calls were slower in the reviewed paths.
                max_item_width = item_width

        window_width = max_item_width
        window_height = len(items)

        window_width = max(window_width, self.min_width)
        window_height = max(window_height, self.min_height)

        window_width = min(window_width, self.max_width)
        window_height = min(window_height, self.max_height)

        # Place the window above if it does not fit below in the work area.
        y = y2
        monitor_info_list = pyauto.Window.getMonitorInfo()
        for monitor_info in monitor_info_list:
            if (
                monitor_info[0][0] <= x < monitor_info[0][2]
                and monitor_info[0][1] <= y1 < monitor_info[0][3]
            ):
                window_rect = self.getWindowRect()
                _char_w, char_h = self.getCharSize()
                if (
                    y2
                    + (window_rect[3] - window_rect[1])
                    + (self.max_height - self.height()) * char_h
                    >= monitor_info[1][3]
                ):
                    y = y1 - (
                        (window_rect[3] - window_rect[1])
                        + (window_height - self.height()) * char_h
                    )
                break

        if not len(items):
            self.show(False, False)

        self.setPosSize(
            x=x,
            y=y,
            width=window_width,
            height=window_height,
            origin=ORIGIN_X_LEFT | ORIGIN_Y_TOP,
        )

        self.items = items
        self.scroll_info = ckit_misc.ScrollInfo()
        self.select = select
        self.scroll_info.makeVisible(self.select, self.height())

        self.paint()

        if len(items):
            self.show(True, False)

    def onActivate(self, active):
        if active:
            self.parent_window.activate()

    def onKeyDown(self, vk, mod):
        if self.keydown_hook and self.keydown_hook(vk, mod):
            return True

    def onChar(self, ch, mod):
        pass

    def paint(self):
        x = 0
        y = 0
        width = self.width()
        height = self.height()

        attribute_normal = ckitcore.Attribute(fg=ckit_theme.getColor("fg"))
        attribute_candidate = ckitcore.Attribute(
            fg=ckit_theme.getColor("fg"), bg=ckit_theme.getColor("bg")
        )
        attribute_candidate_selected = ckitcore.Attribute(
            fg=ckit_theme.getColor("select_fg"), bg=ckit_theme.getColor("select_bg")
        )

        active = self.parent_window.isActive()

        for i in range(height):
            index = self.scroll_info.pos + i
            if index < len(self.items):
                item = self.items[index]
                if isinstance(item, list) or isinstance(item, tuple):  # noqa: SIM101  # Retain short-circuit evaluation; excluded from cleanup for performance.
                    item = item[0]

                if active and self.select == index:
                    attr = attribute_candidate_selected
                else:
                    attr = attribute_candidate
                self.putString(x, y + i, width, 1, attr, " " * width)
                self.putString(x, y + i, width, 1, attr, item)
            else:
                self.putString(x, y + i, width, 1, attribute_normal, " " * width)

    def getSelection(self):
        return self.select

    def numItems(self):
        return len(self.items)

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

    def command_CursorUp(self, info):
        if not len(self.items):
            return
        if self.select >= 0:
            self.select -= 1
            if self.select < 0:  # noqa: PLR1730  # Keep conditional updates; min/max calls were slower in the reviewed paths.
                self.select = 0
        else:
            self.select = len(self.items) - 1
        self.scroll_info.makeVisible(self.select, self.height())

        if self.selchange_handler:
            self.selchange_handler(self.select, self.items[self.select])

        self.paint()

    def command_CursorDown(self, info):
        if not len(self.items):
            return
        self.select += 1
        if self.select > len(self.items) - 1:  # noqa: PLR1730  # Keep conditional updates; min/max calls were slower in the reviewed paths.
            self.select = len(self.items) - 1
        self.scroll_info.makeVisible(self.select, self.height())

        if self.selchange_handler:
            self.selchange_handler(self.select, self.items[self.select])

        self.paint()

    def command_CursorPageUp(self, info):
        if not len(self.items):
            return
        if self.select >= 0:
            if self.select > self.scroll_info.pos:
                self.select = self.scroll_info.pos
            else:
                self.select -= self.height()
                if self.select < 0:  # noqa: PLR1730  # Keep conditional updates; min/max calls were slower in the reviewed paths.
                    self.select = 0
        else:
            self.select = len(self.items) - 1

        self.scroll_info.makeVisible(self.select, self.height())

        if self.selchange_handler:
            self.selchange_handler(self.select, self.items[self.select])

        self.paint()

    def command_CursorPageDown(self, info):
        if not len(self.items):
            return
        if self.select < self.scroll_info.pos + self.height() - 1:
            self.select = self.scroll_info.pos + self.height() - 1
        else:
            self.select += self.height()
        if self.select > len(self.items) - 1:  # noqa: PLR1730  # Keep conditional updates; min/max calls were slower in the reviewed paths.
            self.select = len(self.items) - 1
        self.scroll_info.makeVisible(self.select, self.height())

        if self.selchange_handler:
            self.selchange_handler(self.select, self.items[self.select])

        self.paint()


## @} textwidget
