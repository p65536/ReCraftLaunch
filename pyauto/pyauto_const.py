## @cond japanese
## @addtogroup pyautoconst pyautoのWindows定数
## @endcond
## @cond english
## @addtogroup pyautoconst pyauto Windows Constants
## @endcond
## @addtogroup pyautoconst
# \~japanese
# import pyautoで取得する整数定数です。Inputの仮想キー、Windowへのメッセージ送信に使います。@ref pyauto_native の引数契約を参照してください。
# \~english
# Integer constants exported by import pyauto for virtual-key input and window messages. See @ref pyauto_native for argument contracts.
# \~
## @{

# -*- coding: utf_8 -*-

# --- window message -----------------------------
## \~japanese Window.sendMessage/postMessageへ渡すWindowsメッセージ番号。 \~english Windows message identifier for Window.sendMessage/postMessage. \~
WM_COMMAND = 0x0111
## \~japanese Window.sendMessage/postMessageへ渡すWindowsメッセージ番号。 \~english Windows message identifier for Window.sendMessage/postMessage. \~
WM_SYSCOMMAND = 0x0112

# --- system command -----------------------------
## \~japanese WM_SYSCOMMANDで使うシステムコマンド値。 \~english System-command value used with WM_SYSCOMMAND. \~
SC_SIZE = 0xF000
## \~japanese WM_SYSCOMMANDで使うシステムコマンド値。 \~english System-command value used with WM_SYSCOMMAND. \~
SC_MOVE = 0xF010
## \~japanese WM_SYSCOMMANDで使うシステムコマンド値。 \~english System-command value used with WM_SYSCOMMAND. \~
SC_MINIMIZE = 0xF020
## \~japanese WM_SYSCOMMANDで使うシステムコマンド値。 \~english System-command value used with WM_SYSCOMMAND. \~
SC_MAXIMIZE = 0xF030
## \~japanese WM_SYSCOMMANDで使うシステムコマンド値。 \~english System-command value used with WM_SYSCOMMAND. \~
SC_NEXTWINDOW = 0xF040
## \~japanese WM_SYSCOMMANDで使うシステムコマンド値。 \~english System-command value used with WM_SYSCOMMAND. \~
SC_PREVWINDOW = 0xF050
## \~japanese WM_SYSCOMMANDで使うシステムコマンド値。 \~english System-command value used with WM_SYSCOMMAND. \~
SC_CLOSE = 0xF060
## \~japanese WM_SYSCOMMANDで使うシステムコマンド値。 \~english System-command value used with WM_SYSCOMMAND. \~
SC_VSCROLL = 0xF070
## \~japanese WM_SYSCOMMANDで使うシステムコマンド値。 \~english System-command value used with WM_SYSCOMMAND. \~
SC_HSCROLL = 0xF080
## \~japanese WM_SYSCOMMANDで使うシステムコマンド値。 \~english System-command value used with WM_SYSCOMMAND. \~
SC_MOUSEMENU = 0xF090
## \~japanese WM_SYSCOMMANDで使うシステムコマンド値。 \~english System-command value used with WM_SYSCOMMAND. \~
SC_KEYMENU = 0xF100
## \~japanese WM_SYSCOMMANDで使うシステムコマンド値。 \~english System-command value used with WM_SYSCOMMAND. \~
SC_RESTORE = 0xF120
## \~japanese WM_SYSCOMMANDで使うシステムコマンド値。 \~english System-command value used with WM_SYSCOMMAND. \~
SC_TASKLIST = 0xF130
## \~japanese WM_SYSCOMMANDで使うシステムコマンド値。 \~english System-command value used with WM_SYSCOMMAND. \~
SC_SCREENSAVE = 0xF140
## \~japanese WM_SYSCOMMANDで使うシステムコマンド値。 \~english System-command value used with WM_SYSCOMMAND. \~
SC_HOTKEY = 0xF150
## \~japanese WM_SYSCOMMANDで使うシステムコマンド値。 \~english System-command value used with WM_SYSCOMMAND. \~
SC_DEFAULT = 0xF160
## \~japanese WM_SYSCOMMANDで使うシステムコマンド値。 \~english System-command value used with WM_SYSCOMMAND. \~
SC_MONITORPOWER = 0xF170
## \~japanese WM_SYSCOMMANDで使うシステムコマンド値。 \~english System-command value used with WM_SYSCOMMAND. \~
SC_CONTEXTHELP = 0xF180

# --- virtual keycode ----------------------------
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_LBUTTON = 0x01
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_RBUTTON = 0x02
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_CANCEL = 0x03
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_MBUTTON = 0x04
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_BACK = 0x08
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_TAB = 0x09
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_CLEAR = 0x0C
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_RETURN = 0x0D
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_SHIFT = 0x10
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_CONTROL = 0x11
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_MENU = 0x12
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_PAUSE = 0x13
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_CAPITAL = 0x14
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_KANA = 0x15
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_HANGUL = 0x15
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_JUNJA = 0x17
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_FINAL = 0x18
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_HANJA = 0x19
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_KANJI = 0x19
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_ESCAPE = 0x1B
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_CONVERT = 0x1C
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_NONCONVERT = 0x1D
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_ACCEPT = 0x1E
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_MODECHANGE = 0x1F
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_SPACE = 0x20
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_PRIOR = 0x21
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_NEXT = 0x22
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_END = 0x23
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_HOME = 0x24
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_LEFT = 0x25
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_UP = 0x26
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_RIGHT = 0x27
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_DOWN = 0x28
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_SELECT = 0x29
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_PRINT = 0x2A
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_EXECUTE = 0x2B
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_SNAPSHOT = 0x2C
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_INSERT = 0x2D
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_DELETE = 0x2E
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_HELP = 0x2F
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_0 = 0x30
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_1 = 0x31
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_2 = 0x32
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_3 = 0x33
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_4 = 0x34
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_5 = 0x35
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_6 = 0x36
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_7 = 0x37
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_8 = 0x38
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_9 = 0x39
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_A = 0x41
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_B = 0x42
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_C = 0x43
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_D = 0x44
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_E = 0x45
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_F = 0x46
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_G = 0x47
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_H = 0x48
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_I = 0x49
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_J = 0x4A
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_K = 0x4B
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_L = 0x4C
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_M = 0x4D
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_N = 0x4E
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_O = 0x4F
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_P = 0x50
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_Q = 0x51
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_R = 0x52
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_S = 0x53
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_T = 0x54
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_U = 0x55
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_V = 0x56
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_W = 0x57
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_X = 0x58
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_Y = 0x59
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_Z = 0x5A
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_LWIN = 0x5B
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_RWIN = 0x5C
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_APPS = 0x5D
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_NUMPAD0 = 0x60
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_NUMPAD1 = 0x61
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_NUMPAD2 = 0x62
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_NUMPAD3 = 0x63
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_NUMPAD4 = 0x64
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_NUMPAD5 = 0x65
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_NUMPAD6 = 0x66
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_NUMPAD7 = 0x67
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_NUMPAD8 = 0x68
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_NUMPAD9 = 0x69
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_MULTIPLY = 0x6A
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_ADD = 0x6B
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_SEPARATOR = 0x6C
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_SUBTRACT = 0x6D
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_DECIMAL = 0x6E
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_DIVIDE = 0x6F
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_F1 = 0x70
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_F2 = 0x71
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_F3 = 0x72
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_F4 = 0x73
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_F5 = 0x74
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_F6 = 0x75
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_F7 = 0x76
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_F8 = 0x77
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_F9 = 0x78
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_F10 = 0x79
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_F11 = 0x7A
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_F12 = 0x7B
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_F13 = 0x7C
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_F14 = 0x7D
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_F15 = 0x7E
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_F16 = 0x7F
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_F17 = 0x80
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_F18 = 0x81
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_F19 = 0x82
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_F20 = 0x83
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_F21 = 0x84
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_F22 = 0x85
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_F23 = 0x86
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_F24 = 0x87
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_NUMLOCK = 0x90
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_SCROLL = 0x91
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_LSHIFT = 0xA0
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_RSHIFT = 0xA1
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_LCONTROL = 0xA2
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_RCONTROL = 0xA3
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_LMENU = 0xA4
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_RMENU = 0xA5
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_BROWSER_BACK = 0xA6
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_BROWSER_FORWARD = 0xA7
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_BROWSER_REFRESH = 0xA8
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_BROWSER_STOP = 0xA9
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_BROWSER_SEARCH = 0xAA
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_BROWSER_FAVORITES = 0xAB
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_BROWSER_HOME = 0xAC
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_VOLUME_MUTE = 0xAD
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_VOLUME_DOWN = 0xAE
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_VOLUME_UP = 0xAF
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_MEDIA_NEXT_TRACK = 0xB0
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_MEDIA_PREV_TRACK = 0xB1
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_MEDIA_STOP = 0xB2
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_MEDIA_PLAY_PAUSE = 0xB3
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_LAUNCH_MAIL = 0xB4
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_LAUNCH_MEDIA_SELECT = 0xB5
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_LAUNCH_APP1 = 0xB6
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_LAUNCH_APP2 = 0xB7
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_OEM_1 = 0xBA
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_OEM_PLUS = 0xBB
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_OEM_COMMA = 0xBC
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_OEM_MINUS = 0xBD
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_OEM_PERIOD = 0xBE
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_OEM_2 = 0xBF
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_OEM_3 = 0xC0
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_OEM_4 = 0xDB
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_OEM_5 = 0xDC
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_OEM_6 = 0xDD
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_OEM_7 = 0xDE
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_OEM_8 = 0xDF
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_OEM_102 = 0xE2
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_PROCESSKEY = 0xE5
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_PACKET = 0xE7
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_ATTN = 0xF6
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_CRSEL = 0xF7
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_EXSEL = 0xF8
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_EREOF = 0xF9
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_PLAY = 0xFA
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_ZOOM = 0xFB
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_NONAME = 0xFC
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_PA1 = 0xFD
## \~japanese Windows仮想キー番号。Unicode文字コードとは異なります。OEMキーはキーボード配列に依存します。 \~english Windows virtual-key value, not a Unicode character code. OEM keys depend on the keyboard layout. \~
VK_OEM_CLEAR = 0xFE

## @} pyautoconst
