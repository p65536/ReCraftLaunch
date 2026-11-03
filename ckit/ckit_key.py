import ctypes

from ckit import ckit_resource
from ckit.ckit_const import (
    MODKEY_ALT,
    MODKEY_CTRL,
    MODKEY_SHIFT,
    MODKEY_WIN,
    VK_0,
    VK_1,
    VK_2,
    VK_3,
    VK_4,
    VK_5,
    VK_6,
    VK_7,
    VK_8,
    VK_9,
    VK_A,
    VK_ADD,
    VK_APPS,
    VK_B,
    VK_BACK,
    VK_C,
    VK_CAPITAL,
    VK_CONTROL,
    VK_D,
    VK_DECIMAL,
    VK_DELETE,
    VK_DIVIDE,
    VK_DOWN,
    VK_E,
    VK_END,
    VK_ESCAPE,
    VK_F,
    VK_F1,
    VK_F2,
    VK_F3,
    VK_F4,
    VK_F5,
    VK_F6,
    VK_F7,
    VK_F8,
    VK_F9,
    VK_F10,
    VK_F11,
    VK_F12,
    VK_G,
    VK_H,
    VK_HOME,
    VK_I,
    VK_INSERT,
    VK_J,
    VK_K,
    VK_L,
    VK_LCONTROL,
    VK_LEFT,
    VK_LMENU,
    VK_LSHIFT,
    VK_LWIN,
    VK_M,
    VK_MENU,
    VK_MULTIPLY,
    VK_N,
    VK_NEXT,
    VK_NUMLOCK,
    VK_NUMPAD0,
    VK_NUMPAD1,
    VK_NUMPAD2,
    VK_NUMPAD3,
    VK_NUMPAD4,
    VK_NUMPAD5,
    VK_NUMPAD6,
    VK_NUMPAD7,
    VK_NUMPAD8,
    VK_NUMPAD9,
    VK_O,
    VK_OEM_1,
    VK_OEM_2,
    VK_OEM_3,
    VK_OEM_4,
    VK_OEM_5,
    VK_OEM_6,
    VK_OEM_7,
    VK_OEM_102,
    VK_OEM_COMMA,
    VK_OEM_MINUS,
    VK_OEM_PERIOD,
    VK_OEM_PLUS,
    VK_P,
    VK_PAUSE,
    VK_PRIOR,
    VK_Q,
    VK_R,
    VK_RCONTROL,
    VK_RETURN,
    VK_RIGHT,
    VK_RMENU,
    VK_RSHIFT,
    VK_RWIN,
    VK_S,
    VK_SCROLL,
    VK_SHIFT,
    VK_SNAPSHOT,
    VK_SPACE,
    VK_SUBTRACT,
    VK_T,
    VK_TAB,
    VK_U,
    VK_UP,
    VK_V,
    VK_W,
    VK_X,
    VK_Y,
    VK_Z,
)

## @addtogroup command
## @{

## \~japanese
# 仮想キーコードvkと修飾キービットmodを組み合わせたキー条件
#
#  KeyEvent(vk, mod, extra=None)で生成するか、fromString("C-S-F9")で文字列表記から生成します。
#  modはMODKEY_CTRL等のビット和です。extraは追加条件で、比較の両側がNone以外のときだけ一致を要求します。
#  等値比較はKeyEventとその派生型を対象とし、別型にはNotImplementedを返します。
#  通常のキー割当にはKeymapの文字列表記を使います。キー名の表は本体が起動時に初期化します。
#  @sa Keymap
# \~english
# Key condition combining a virtual-key code vk and modifier bits mod
#
#  Construct KeyEvent(vk, mod, extra=None), or parse fromString("C-S-F9"). mod is a bitwise combination
#  of MODKEY_CTRL and related constants. extra only restricts equality when both operands specify it.
#  Equality compares KeyEvent instances and subclasses; it returns NotImplemented for unrelated types.
#  Prefer Keymap's string notation for ordinary bindings. The application initializes key-name tables at startup.
#  @sa Keymap
# \~
class KeyEvent:
    vk_str_table = {}  # noqa: RUF012  # Shared keyboard lookup table.
    str_vk_table = {}  # noqa: RUF012  # Shared keyboard lookup table.
    _keyboard_type = 0
    _modifier_vk_mod = {  # noqa: RUF012  # Shared modifier lookup table.
        VK_CONTROL: MODKEY_CTRL, VK_LCONTROL: MODKEY_CTRL, VK_RCONTROL: MODKEY_CTRL,
        VK_SHIFT: MODKEY_SHIFT, VK_LSHIFT: MODKEY_SHIFT, VK_RSHIFT: MODKEY_SHIFT,
        VK_MENU: MODKEY_ALT, VK_LMENU: MODKEY_ALT, VK_RMENU: MODKEY_ALT,
        VK_LWIN: MODKEY_WIN, VK_RWIN: MODKEY_WIN,
    }

    vk_str_table_common = {  # noqa: RUF012  # Shared keyboard lookup table.
        VK_A: "A",
        VK_B: "B",
        VK_C: "C",
        VK_D: "D",
        VK_E: "E",
        VK_F: "F",
        VK_G: "G",
        VK_H: "H",
        VK_I: "I",
        VK_J: "J",
        VK_K: "K",
        VK_L: "L",
        VK_M: "M",
        VK_N: "N",
        VK_O: "O",
        VK_P: "P",
        VK_Q: "Q",
        VK_R: "R",
        VK_S: "S",
        VK_T: "T",
        VK_U: "U",
        VK_V: "V",
        VK_W: "W",
        VK_X: "X",
        VK_Y: "Y",
        VK_Z: "Z",
        VK_0: "0",
        VK_1: "1",
        VK_2: "2",
        VK_3: "3",
        VK_4: "4",
        VK_5: "5",
        VK_6: "6",
        VK_7: "7",
        VK_8: "8",
        VK_9: "9",
        VK_OEM_MINUS: "Minus",
        VK_OEM_PLUS: "Plus",
        VK_OEM_COMMA: "Comma",
        VK_OEM_PERIOD: "Period",
        VK_NUMLOCK: "NumLock",
        VK_DIVIDE: "Divide",
        VK_MULTIPLY: "Multiply",
        VK_SUBTRACT: "Subtract",
        VK_ADD: "Add",
        VK_DECIMAL: "Decimal",
        VK_NUMPAD0: "Num0",
        VK_NUMPAD1: "Num1",
        VK_NUMPAD2: "Num2",
        VK_NUMPAD3: "Num3",
        VK_NUMPAD4: "Num4",
        VK_NUMPAD5: "Num5",
        VK_NUMPAD6: "Num6",
        VK_NUMPAD7: "Num7",
        VK_NUMPAD8: "Num8",
        VK_NUMPAD9: "Num9",
        VK_F1: "F1",
        VK_F2: "F2",
        VK_F3: "F3",
        VK_F4: "F4",
        VK_F5: "F5",
        VK_F6: "F6",
        VK_F7: "F7",
        VK_F8: "F8",
        VK_F9: "F9",
        VK_F10: "F10",
        VK_F11: "F11",
        VK_F12: "F12",
        VK_LEFT: "Left",
        VK_RIGHT: "Right",
        VK_UP: "Up",
        VK_DOWN: "Down",
        VK_SPACE: "Space",
        VK_TAB: "Tab",
        VK_BACK: "Back",
        VK_RETURN: "Return",
        VK_ESCAPE: "Escape",
        VK_CAPITAL: "CapsLock",
        VK_APPS: "Apps",
        VK_INSERT: "Insert",
        VK_DELETE: "Delete",
        VK_HOME: "Home",
        VK_END: "End",
        VK_NEXT: "PageDown",
        VK_PRIOR: "PageUp",
        VK_MENU: "Alt",
        VK_LMENU: "LAlt",
        VK_RMENU: "RAlt",
        VK_CONTROL: "Ctrl",
        VK_LCONTROL: "LCtrl",
        VK_RCONTROL: "RCtrl",
        VK_SHIFT: "Shift",
        VK_LSHIFT: "LShift",
        VK_RSHIFT: "RShift",
        VK_LWIN: "LWin",
        VK_RWIN: "RWin",
        VK_SNAPSHOT: "PrintScreen",
        VK_SCROLL: "ScrollLock",
        VK_PAUSE: "Pause",
    }

    vk_str_table_std = {  # noqa: RUF012  # Shared keyboard lookup table.
        VK_OEM_1: "Semicolon",
        VK_OEM_2: "Slash",
        VK_OEM_3: "BackQuote",
        VK_OEM_4: "OpenBracket",
        VK_OEM_5: "BackSlash",
        VK_OEM_6: "CloseBracket",
        VK_OEM_7: "Quote",
    }

    vk_str_table_jpn = {  # noqa: RUF012  # Shared keyboard lookup table.
        VK_OEM_1: "Colon",
        VK_OEM_2: "Slash",
        VK_OEM_3: "Atmark",
        VK_OEM_4: "OpenBracket",
        VK_OEM_5: "Yen",
        VK_OEM_6: "CloseBracket",
        VK_OEM_7: "Caret",
        VK_OEM_102: "BackSlash",
    }

    str_vk_table_common = {  # noqa: RUF012  # Shared keyboard lookup table.
        "A": VK_A,
        "B": VK_B,
        "C": VK_C,
        "D": VK_D,
        "E": VK_E,
        "F": VK_F,
        "G": VK_G,
        "H": VK_H,
        "I": VK_I,
        "J": VK_J,
        "K": VK_K,
        "L": VK_L,
        "M": VK_M,
        "N": VK_N,
        "O": VK_O,
        "P": VK_P,
        "Q": VK_Q,
        "R": VK_R,
        "S": VK_S,
        "T": VK_T,
        "U": VK_U,
        "V": VK_V,
        "W": VK_W,
        "X": VK_X,
        "Y": VK_Y,
        "Z": VK_Z,
        "0": VK_0,
        "1": VK_1,
        "2": VK_2,
        "3": VK_3,
        "4": VK_4,
        "5": VK_5,
        "6": VK_6,
        "7": VK_7,
        "8": VK_8,
        "9": VK_9,
        "MINUS": VK_OEM_MINUS,
        "PLUS": VK_OEM_PLUS,
        "COMMA": VK_OEM_COMMA,
        "PERIOD": VK_OEM_PERIOD,
        "NUMLOCK": VK_NUMLOCK,
        "DIVIDE": VK_DIVIDE,
        "MULTIPLY": VK_MULTIPLY,
        "SUBTRACT": VK_SUBTRACT,
        "ADD": VK_ADD,
        "DECIMAL": VK_DECIMAL,
        "NUM0": VK_NUMPAD0,
        "NUM1": VK_NUMPAD1,
        "NUM2": VK_NUMPAD2,
        "NUM3": VK_NUMPAD3,
        "NUM4": VK_NUMPAD4,
        "NUM5": VK_NUMPAD5,
        "NUM6": VK_NUMPAD6,
        "NUM7": VK_NUMPAD7,
        "NUM8": VK_NUMPAD8,
        "NUM9": VK_NUMPAD9,
        "F1": VK_F1,
        "F2": VK_F2,
        "F3": VK_F3,
        "F4": VK_F4,
        "F5": VK_F5,
        "F6": VK_F6,
        "F7": VK_F7,
        "F8": VK_F8,
        "F9": VK_F9,
        "F10": VK_F10,
        "F11": VK_F11,
        "F12": VK_F12,
        "LEFT": VK_LEFT,
        "RIGHT": VK_RIGHT,
        "UP": VK_UP,
        "DOWN": VK_DOWN,
        "SPACE": VK_SPACE,
        "TAB": VK_TAB,
        "BACK": VK_BACK,
        "RETURN": VK_RETURN,
        "ENTER": VK_RETURN,
        "ESCAPE": VK_ESCAPE,
        "ESC": VK_ESCAPE,
        "CAPSLOCK": VK_CAPITAL,
        "CAPS": VK_CAPITAL,
        "CAPITAL": VK_CAPITAL,
        "APPS": VK_APPS,
        "INSERT": VK_INSERT,
        "DELETE": VK_DELETE,
        "HOME": VK_HOME,
        "END": VK_END,
        "PAGEDOWN": VK_NEXT,
        "PAGEUP": VK_PRIOR,
        "ALT": VK_MENU,
        "LALT": VK_LMENU,
        "RALT": VK_RMENU,
        "CTRL": VK_CONTROL,
        "LCTRL": VK_LCONTROL,
        "RCTRL": VK_RCONTROL,
        "SHIFT": VK_SHIFT,
        "LSHIFT": VK_LSHIFT,
        "RSHIFT": VK_RSHIFT,
        "LWIN": VK_LWIN,
        "RWIN": VK_RWIN,
        "PRINTSCREEN": VK_SNAPSHOT,
        "SCROLLLOCK": VK_SCROLL,
        "PAUSE": VK_PAUSE,
    }

    str_vk_table_std = {  # noqa: RUF012  # Shared keyboard lookup table.
        "SEMICOLON": VK_OEM_1,
        "COLON": VK_OEM_1,
        "SLASH": VK_OEM_2,
        "BACKQUOTE": VK_OEM_3,
        "TILDE": VK_OEM_3,
        "OPENBRACKET": VK_OEM_4,
        "BACKSLASH": VK_OEM_5,
        "YEN": VK_OEM_5,
        "CLOSEBRACKET": VK_OEM_6,
        "QUOTE": VK_OEM_7,
        "DOUBLEQUOTE": VK_OEM_7,
        "UNDERSCORE": VK_OEM_MINUS,
        "ASTERISK": VK_8,
        "ATMARK": VK_2,
        "CARET": VK_6,
    }

    str_vk_table_jpn = {  # noqa: RUF012  # Shared keyboard lookup table.
        "SEMICOLON": VK_OEM_PLUS,
        "COLON": VK_OEM_1,
        "SLASH": VK_OEM_2,
        "BACKQUOTE": VK_OEM_3,
        "TILDE": VK_OEM_7,
        "OPENBRACKET": VK_OEM_4,
        "BACKSLASH": VK_OEM_102,
        "YEN": VK_OEM_5,
        "CLOSEBRACKET": VK_OEM_6,
        "QUOTE": VK_7,
        "DOUBLEQUOTE": VK_2,
        "UNDERSCORE": VK_OEM_102,
        "ASTERISK": VK_OEM_1,
        "ATMARK": VK_OEM_3,
        "CARET": VK_OEM_7,
    }

    str_mod_table = {  # noqa: RUF012  # Shared keyboard lookup table.
        "ALT": MODKEY_ALT,
        "CTRL": MODKEY_CTRL,
        "SHIFT": MODKEY_SHIFT,
        "WIN": MODKEY_WIN,
        "A": MODKEY_ALT,
        "C": MODKEY_CTRL,
        "S": MODKEY_SHIFT,
        "W": MODKEY_WIN,
    }

    ## \~japanese
    #  @param vk 仮想キーコードの整数（VK_F9等）。
    #  @param mod MODKEY_*ビットの組合せ。修飾なしは0。
    #  @param extra 追加の一致条件。Noneは制限なし。
    #
    # \~english
    #  @param vk Integer virtual-key code, such as VK_F9.
    #  @param mod Combination of MODKEY_* bits; 0 for no modifiers.
    #  @param extra Additional equality condition; None imposes no restriction.
    #
    # \~
    def __init__(self, vk, mod, extra=None):
        self.vk = vk
        self.mod = mod
        self.extra = extra

    def __str__(self):
        s = ""
        if self.mod & MODKEY_ALT:
            s += "A-"
        if self.mod & MODKEY_CTRL:
            s += "C-"
        if self.mod & MODKEY_SHIFT:
            s += "S-"
        if self.mod & MODKEY_WIN:
            s += "W-"
        s += KeyEvent.vkToStr(self.vk)
        return s

    def __hash__(self):
        return self.vk

    def __eq__(self, rhs):
        if not isinstance(rhs, KeyEvent):
            return NotImplemented
        if self.vk != rhs.vk:
            return False
        if self.mod != rhs.mod:
            return False
        if self.extra is not None and rhs.extra is not None and self.extra != rhs.extra:  # noqa: SIM103  # Retain short-circuit evaluation; excluded from cleanup for performance.
            return False
        return True

    ## \~japanese
    #  @param s キー表記文字列。例: C-S-F9。
    #  @return 新しいKeyEvent。大文字小文字と各トークン前後の空白は無視します。
    #  @exception ValueError 未知の修飾名・キー名。
    #  キー名はReturn・Escape・Space・F1～F12等。数値の仮想キーコードは(120)のようにも書けます。
    #
    # \~english
    #  @param s Key expression, for example C-S-F9.
    #  @return New KeyEvent, ignoring case and surrounding whitespace of each token.
    #  @exception ValueError Unknown modifier/key name.
    #  Key names include Return, Escape, Space and F1 through F12. A numeric virtual-key code may be written as (120).
    #
    # \~
    @staticmethod
    def fromString(s):
        s = s.upper()

        vk = None
        mod = 0

        token_list = s.split("-")

        for token in token_list[:-1]:
            mod |= KeyEvent.strToMod(token.strip())

        token = token_list[-1].strip()

        vk = KeyEvent.strToVk(token)

        return KeyEvent(vk, mod)

    ## \~japanese
    #  OSのキーボード種別からキー名と仮想キーコードの表を初期化する
    #  @return None。本体が起動・設定時に呼びます。通常の拡張で呼び直す必要はありません。
    #  共通表をコピーして現在の配列を適用し、共通表と以前の配列を混在させません。
    #
    # \~english
    #  Initialize key-name/virtual-key tables using the OS keyboard type
    #  @return None. Called by the application at startup/configuration; ordinary extensions need not call it again.
    #  Copy the common tables and apply the current layout without modifying the common tables or retaining the previous layout.
    #
    # \~
    @staticmethod
    def initTables():
        keyboard_type = ctypes.windll.user32.GetKeyboardType(0)
        KeyEvent._keyboard_type = keyboard_type

        KeyEvent.str_vk_table = KeyEvent.str_vk_table_common.copy()
        KeyEvent.vk_str_table = KeyEvent.vk_str_table_common.copy()

        if keyboard_type == 7:
            KeyEvent.str_vk_table.update(KeyEvent.str_vk_table_jpn)
            KeyEvent.vk_str_table.update(KeyEvent.vk_str_table_jpn)
        else:
            KeyEvent.str_vk_table.update(KeyEvent.str_vk_table_std)
            KeyEvent.vk_str_table.update(KeyEvent.vk_str_table_std)

    ## \~japanese
    #  @param name キー名または仮想キーコードの数値文字列。
    #  @return 仮想キーコードの整数。
    #  @exception ValueError 未知のキー名で数値にも変換できない場合。
    #
    # \~english
    #  @param name Key name or numeric virtual-key string.
    #  @return Integer virtual-key code.
    #  @exception ValueError If the name is unknown and cannot be converted to an integer.
    #
    # \~
    @staticmethod
    def strToVk(name):
        try:
            vk = KeyEvent.str_vk_table[name.upper()]
        except KeyError:
            try:
                vk = int(name.strip("()"))
            except ValueError:
                raise ValueError
        return vk

    ## \~japanese
    #  @param vk 仮想キーコード。
    #  @return 既知のキー名、未知なら(数値)の文字列。
    #
    # \~english
    #  @param vk Virtual-key code.
    #  @return Known key name, or (number) for an unknown code.
    #
    # \~
    @staticmethod
    def vkToStr(vk) -> str:
        try:
            name = KeyEvent.vk_str_table[vk]
        except KeyError:
            name = "(%d)" % vk  # noqa: UP031  # Preserve percent-d conversion for public values.
        return name

    ## \~japanese
    #  @param vk 仮想キーコード。
    #  @return Ctrl・Shift・Alt・Win（左右別を含む）ならTrue。
    # \~english
    #  @param vk Virtual-key code.
    #  @return True for Ctrl, Shift, Alt or Win, including left/right variants.
    # \~
    @staticmethod
    def isModifierKey(vk):
        return vk in KeyEvent._modifier_vk_mod

    ## \~japanese
    #  @param vk 仮想キーコード。0は未設定。
    #  @param mod MODKEY_*ビットの組合せ。
    #  @return GUI用の表示文字列。未設定は空文字列で、文言と幅調整は呼出し側が扱います。
    #  修飾キーは[C]+[S]+[A]+[W]の固定順。OEM記号はinitTablesの配列判定を使い、Shiftで変化しません。
    #  修飾キーのみの入力途中も表示します。Keymapの構文やOS登録の可否とは別です。
    # \~english
    #  @param vk Virtual-key code; 0 means unassigned.
    #  @param mod Combination of MODKEY_* bits.
    #  @return GUI display text, or an empty string when unassigned. The caller handles labels and width.
    #  Modifiers use the fixed order [C]+[S]+[A]+[W]. OEM symbols use the initTables layout, unaffected by Shift.
    #  Modifier-only previews are supported independently of Keymap syntax or OS registration validity.
    # \~
    @staticmethod
    def formatHotKey(vk, mod):
        if not vk:
            return ""
        modifier = KeyEvent._modifier_vk_mod.get(vk, 0)
        mod |= modifier
        parts = [label for mask, label in (
            (MODKEY_CTRL, "[C]"), (MODKEY_SHIFT, "[S]"),
            (MODKEY_ALT, "[A]"), (MODKEY_WIN, "[W]"),
        ) if mod & mask]
        if not modifier:
            japanese = KeyEvent._keyboard_type == 7
            symbols = {
                VK_OEM_1: ":" if japanese else ";",
                VK_OEM_PLUS: ";" if japanese else "=",
                VK_OEM_COMMA: ",", VK_OEM_MINUS: "-", VK_OEM_PERIOD: ".",
                VK_OEM_2: "/", VK_OEM_3: "@" if japanese else "`",
                VK_OEM_4: "[", VK_OEM_5: "¥" if japanese else "\\",
                VK_OEM_6: "]", VK_OEM_7: "^" if japanese else "'",
            }
            if japanese:
                symbols[VK_OEM_102] = "\\"
            name = symbols.get(vk, KeyEvent.vkToStr(vk))
            parts.append("[+]" if name == "+" else name)
        return "+".join(parts)

    ## \~japanese
    #  @param name C/CTRL等の修飾名。大文字小文字を区別しません。
    #  @param force_LR Trueなら低位8ビットの修飾を8ビット左へ移します。既定False。
    #  @return 対応する修飾ビット。
    #  @exception ValueError 未知の修飾名。
    #
    # \~english
    #  @param name Modifier name such as C/CTRL; case-insensitive.
    #  @param force_LR If True, shift low-byte modifiers left by 8 bits. Default False.
    #  @return Corresponding modifier bits.
    #  @exception ValueError Unknown modifier name.
    #
    # \~
    @staticmethod
    def strToMod(name, force_LR=False):
        try:
            mod = KeyEvent.str_mod_table[name.upper()]
        except KeyError:
            raise ValueError
        if force_LR and (mod & 0xFF):
            mod <<= 8
        return mod


## \~japanese
# キー条件からコマンド関数への対応表
#
#  本体から渡されるwindow.keymapまたはwindow.cmd_keymapへ、keymap["C-F9"] = handlerの形で設定します。
#  値はCommandInfoを1つ受け取る関数です。取得はkeymap[key]、削除はdel keymap[key]で行います。
#  キーは文字列またはKeyEventです。C/CTRL、S/SHIFT、A/ALT、W/WINをハイフンで組み合わせ、
#  末尾へキー名を置きます。大文字小文字は区別しません。例: C-S-F9、Ctrl-Return、A-Space。
#  同じ条件の代入は置換、取得に該当がなければKeyError、削除に該当がなければ何もしません。
#  削除で以前の割当は復元しません。不正な文字列表記の代入はエラーを表示し、割当表を変更しません。
#  メイン入力はcmd_keymapを先に調べます。渡されるargs/modと入力終了の違いは拡張実装ガイドを参照してください。
#  @sa KeyEvent, CommandInfo
# \~english
# Map key conditions to command callables
#
#  Set window.keymap or window.cmd_keymap with keymap["C-F9"] = handler. Values accept one CommandInfo.
#  Read with keymap[key], delete with del keymap[key]. A key is a string or KeyEvent. Combine C/CTRL,
#  S/SHIFT, A/ALT and W/WIN with hyphens, ending with a key name; case is ignored. Examples: C-S-F9,
#  Ctrl-Return, A-Space. Assignment replaces a matching binding. Missing lookup raises KeyError;
#  missing deletion does nothing. Deletion does not restore an older binding. Assigning an invalid key string prints
#  an error and leaves the binding table unchanged. Main input checks cmd_keymap first. See the extension guide for
#  differences in args/mod and whether input ends.
#  @sa KeyEvent, CommandInfo
# \~
class Keymap:
    ## \~japanese
    #  KeyEvent.initTables()へ委譲する。本体が設定時に呼びます。
    #
    # \~english
    #  Delegate to KeyEvent.initTables(); called during application configuration.
    #
    # \~
    @staticmethod
    def init():
        KeyEvent.initTables()

    ## \~japanese
    #  空のキー割当表を作る。通常は渡されたwindowの既存表を編集します。
    #
    # \~english
    #  Create an empty binding table. Normally edit the supplied window's existing table.
    #
    # \~
    def __init__(self):
        self.table = {}

    def _toKeyEvent(self, expression):
        if isinstance(expression, KeyEvent):
            key_cond = expression
        elif isinstance(expression, str):
            try:
                key_cond = KeyEvent.fromString(expression)
            except ValueError:
                print(ckit_resource.strings["invalid_key"], expression)
                return
        else:
            raise TypeError

        return key_cond

    def __setitem__(self, expression, value):
        key_cond = self._toKeyEvent(expression)
        if key_cond is None:
            return

        # Remove existing bindings while ignoring differences in extra.
        while key_cond in self.table:
            del self.table[key_cond]

        self.table[key_cond] = value

    def __getitem__(self, expression):
        key_cond = self._toKeyEvent(expression)
        return self.table[key_cond]

    def __delitem__(self, expression):
        key_cond = self._toKeyEvent(expression)

        # Remove existing bindings while ignoring differences in extra.
        while key_cond in self.table:
            del self.table[key_cond]


## @} command
