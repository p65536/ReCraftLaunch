# -*- coding: utf_8 -*-

from pyauto import pyautocore

## @cond japanese
## @addtogroup pyautoinput 外部ウィンドウと合成入力
## @endcond
## @cond english
## @addtogroup pyautoinput External Windows and Synthetic Input
## @endcond
## @addtogroup pyautoinput
# \~japanese
# pyauto.Input派生の短縮クラスです。構築と送信は別です。Window/Image/Input/Hookとモジュール関数の全契約は@ref pyauto_native を参照してください。
# \~english
# Convenience subclasses of pyauto.Input; construction is separate from submission. See @ref pyauto_native for Window/Image/Input/Hook and module contracts.
# \~
## @{


## \~japanese
# 仮想キーの合成入力を準備する短縮クラス。vkはWindows仮想キー整数または長さ1のstrです。strはordへ変換するだけで、大文字化やキー名検索はしません。たとえばAには"A"またはVK_Aを使い、"a"を同じキーとみなしません。
# 構築だけでは送信しません。Input.sendへlist/tupleで渡します。ネイティブ契約は@ref pyauto_native を参照してください。
# \~english
# Generate a synthetic key-down event.
# vk is a Windows virtual-key integer or a one-character str. Strings are converted with ord only, without case normalization or key-name lookup: use "A" or VK_A for A; "a" is not the same key.
# Construction only prepares events; pass a list/tuple to Input.send. See @ref pyauto_native for native contracts.
# \~
class KeyDown(pyautocore.Input):
    ## \~japanese
    # イベントを準備します。引数の単位と制約はクラス説明を参照。戻り値を持ちません。
    # \~english
    # Prepare events; see the class for argument units and limits. No return value.
    # \~
    def __init__(self, vk):
        pyautocore.Input.__init__(self)
        if type(vk) is str and len(vk) == 1:
            vk = ord(vk)
        self.setKeyDown(vk)


## \~japanese
# 仮想キーの合成入力を準備する短縮クラス。vkはWindows仮想キー整数または長さ1のstrです。strはordへ変換するだけで、大文字化やキー名検索はしません。たとえばAには"A"またはVK_Aを使い、"a"を同じキーとみなしません。
# 構築だけでは送信しません。Input.sendへlist/tupleで渡します。ネイティブ契約は@ref pyauto_native を参照してください。
# \~english
# Generate a synthetic key-up event.
# vk is a Windows virtual-key integer or a one-character str. Strings are converted with ord only, without case normalization or key-name lookup: use "A" or VK_A for A; "a" is not the same key.
# Construction only prepares events; pass a list/tuple to Input.send. See @ref pyauto_native for native contracts.
# \~
class KeyUp(pyautocore.Input):
    ## \~japanese
    # イベントを準備します。引数の単位と制約はクラス説明を参照。戻り値を持ちません。
    # \~english
    # Prepare events; see the class for argument units and limits. No return value.
    # \~
    def __init__(self, vk):
        pyautocore.Input.__init__(self)
        if type(vk) is str and len(vk) == 1:
            vk = ord(vk)
        self.setKeyUp(vk)


## \~japanese
# 仮想キーの合成入力を準備する短縮クラス。vkはWindows仮想キー整数または長さ1のstrです。strはordへ変換するだけで、大文字化やキー名検索はしません。たとえばAには"A"またはVK_Aを使い、"a"を同じキーとみなしません。
# 構築だけでは送信しません。Input.sendへlist/tupleで渡します。ネイティブ契約は@ref pyauto_native を参照してください。
# \~english
# Generate synthetic key-down and key-up events.
# vk is a Windows virtual-key integer or a one-character str. Strings are converted with ord only, without case normalization or key-name lookup: use "A" or VK_A for A; "a" is not the same key.
# Construction only prepares events; pass a list/tuple to Input.send. See @ref pyauto_native for native contracts.
# \~
class Key(pyautocore.Input):
    ## \~japanese
    # イベントを準備します。引数の単位と制約はクラス説明を参照。戻り値を持ちません。
    # \~english
    # Prepare events; see the class for argument units and limits. No return value.
    # \~
    def __init__(self, vk):
        pyautocore.Input.__init__(self)
        if type(vk) is str and len(vk) == 1:
            vk = ord(vk)
        self.setKey(vk)


## \~japanese
# 文字入力を準備する短縮クラス。cは整数または長さ1のstrで、strはordへ変換します。ネイティブではUTF-16の1単位へ切り詰めるため、補助平面文字を1文字渡してもサロゲート対にはなりません。
# 構築だけでは送信しません。Input.sendへlist/tupleで渡します。ネイティブ契約は@ref pyauto_native を参照してください。
# \~english
# Generate synthetic character input.
# c is an integer or a one-character str converted with ord. Native storage truncates to one UTF-16 unit; passing a supplementary character does not create a surrogate pair.
# Construction only prepares events; pass a list/tuple to Input.send. See @ref pyauto_native for native contracts.
# \~
class Char(pyautocore.Input):
    ## \~japanese
    # イベントを準備します。引数の単位と制約はクラス説明を参照。戻り値を持ちません。
    # \~english
    # Prepare events; see the class for argument units and limits. No return value.
    # \~
    def __init__(self, c):
        pyautocore.Input.__init__(self)
        if type(c) is str and len(c) == 1:
            c = ord(c)
        self.setChar(c)


## \~japanese
# マウス入力を準備する短縮クラス。x/yはC intの画面ピクセルです。仮想デスクトップ全体の負座標にも対応し、範囲外は各軸の端へ丸めます。
# 構築だけでは送信しません。Input.sendへlist/tupleで渡します。ネイティブ契約は@ref pyauto_native を参照してください。
# \~english
# Generate a synthetic mouse-move event.
# x/y are C-int screen pixels across the virtual desktop, including negative coordinates. Values outside its bounds are clamped on each axis.
# Construction only prepares events; pass a list/tuple to Input.send. See @ref pyauto_native for native contracts.
# \~
class MouseMove(pyautocore.Input):
    ## \~japanese
    # イベントを準備します。引数の単位と制約はクラス説明を参照。戻り値を持ちません。
    # \~english
    # Prepare events; see the class for argument units and limits. No return value.
    # \~
    def __init__(self, x, y):
        pyautocore.Input.__init__(self)
        self.setMouseMove(x, y)


## \~japanese
# マウス入力を準備する短縮クラス。x/yはC intの画面ピクセルです。仮想デスクトップ全体の負座標にも対応し、範囲外は各軸の端へ丸めます。
# 構築だけでは送信しません。Input.sendへlist/tupleで渡します。ネイティブ契約は@ref pyauto_native を参照してください。
# \~english
# Generate a synthetic left mouse-button-down event.
# x/y are C-int screen pixels across the virtual desktop, including negative coordinates. Values outside its bounds are clamped on each axis.
# Construction only prepares events; pass a list/tuple to Input.send. See @ref pyauto_native for native contracts.
# \~
class MouseLeftDown(pyautocore.Input):
    ## \~japanese
    # イベントを準備します。引数の単位と制約はクラス説明を参照。戻り値を持ちません。
    # \~english
    # Prepare events; see the class for argument units and limits. No return value.
    # \~
    def __init__(self, x, y):
        pyautocore.Input.__init__(self)
        self.setMouseLeftDown(x, y)


## \~japanese
# マウス入力を準備する短縮クラス。x/yはC intの画面ピクセルです。仮想デスクトップ全体の負座標にも対応し、範囲外は各軸の端へ丸めます。
# 構築だけでは送信しません。Input.sendへlist/tupleで渡します。ネイティブ契約は@ref pyauto_native を参照してください。
# \~english
# Generate a synthetic left mouse-button-up event.
# x/y are C-int screen pixels across the virtual desktop, including negative coordinates. Values outside its bounds are clamped on each axis.
# Construction only prepares events; pass a list/tuple to Input.send. See @ref pyauto_native for native contracts.
# \~
class MouseLeftUp(pyautocore.Input):
    ## \~japanese
    # イベントを準備します。引数の単位と制約はクラス説明を参照。戻り値を持ちません。
    # \~english
    # Prepare events; see the class for argument units and limits. No return value.
    # \~
    def __init__(self, x, y):
        pyautocore.Input.__init__(self)
        self.setMouseLeftUp(x, y)


## \~japanese
# マウス入力を準備する短縮クラス。x/yはC intの画面ピクセルです。仮想デスクトップ全体の負座標にも対応し、範囲外は各軸の端へ丸めます。
# 構築だけでは送信しません。Input.sendへlist/tupleで渡します。ネイティブ契約は@ref pyauto_native を参照してください。
# \~english
# Generate synthetic left mouse-button-down and button-up events.
# x/y are C-int screen pixels across the virtual desktop, including negative coordinates. Values outside its bounds are clamped on each axis.
# Construction only prepares events; pass a list/tuple to Input.send. See @ref pyauto_native for native contracts.
# \~
class MouseLeftClick(pyautocore.Input):
    ## \~japanese
    # イベントを準備します。引数の単位と制約はクラス説明を参照。戻り値を持ちません。
    # \~english
    # Prepare events; see the class for argument units and limits. No return value.
    # \~
    def __init__(self, x, y):
        pyautocore.Input.__init__(self)
        self.setMouseLeftClick(x, y)


## \~japanese
# マウス入力を準備する短縮クラス。x/yはC intの画面ピクセルです。仮想デスクトップ全体の負座標にも対応し、範囲外は各軸の端へ丸めます。
# 構築だけでは送信しません。Input.sendへlist/tupleで渡します。ネイティブ契約は@ref pyauto_native を参照してください。
# \~english
# Generate a synthetic right mouse-button-down event.
# x/y are C-int screen pixels across the virtual desktop, including negative coordinates. Values outside its bounds are clamped on each axis.
# Construction only prepares events; pass a list/tuple to Input.send. See @ref pyauto_native for native contracts.
# \~
class MouseRightDown(pyautocore.Input):
    ## \~japanese
    # イベントを準備します。引数の単位と制約はクラス説明を参照。戻り値を持ちません。
    # \~english
    # Prepare events; see the class for argument units and limits. No return value.
    # \~
    def __init__(self, x, y):
        pyautocore.Input.__init__(self)
        self.setMouseRightDown(x, y)


## \~japanese
# マウス入力を準備する短縮クラス。x/yはC intの画面ピクセルです。仮想デスクトップ全体の負座標にも対応し、範囲外は各軸の端へ丸めます。
# 構築だけでは送信しません。Input.sendへlist/tupleで渡します。ネイティブ契約は@ref pyauto_native を参照してください。
# \~english
# Generate a synthetic right mouse-button-up event.
# x/y are C-int screen pixels across the virtual desktop, including negative coordinates. Values outside its bounds are clamped on each axis.
# Construction only prepares events; pass a list/tuple to Input.send. See @ref pyauto_native for native contracts.
# \~
class MouseRightUp(pyautocore.Input):
    ## \~japanese
    # イベントを準備します。引数の単位と制約はクラス説明を参照。戻り値を持ちません。
    # \~english
    # Prepare events; see the class for argument units and limits. No return value.
    # \~
    def __init__(self, x, y):
        pyautocore.Input.__init__(self)
        self.setMouseRightUp(x, y)


## \~japanese
# マウス入力を準備する短縮クラス。x/yはC intの画面ピクセルです。仮想デスクトップ全体の負座標にも対応し、範囲外は各軸の端へ丸めます。
# 構築だけでは送信しません。Input.sendへlist/tupleで渡します。ネイティブ契約は@ref pyauto_native を参照してください。
# \~english
# Generate synthetic right mouse-button-down and button-up events.
# x/y are C-int screen pixels across the virtual desktop, including negative coordinates. Values outside its bounds are clamped on each axis.
# Construction only prepares events; pass a list/tuple to Input.send. See @ref pyauto_native for native contracts.
# \~
class MouseRightClick(pyautocore.Input):
    ## \~japanese
    # イベントを準備します。引数の単位と制約はクラス説明を参照。戻り値を持ちません。
    # \~english
    # Prepare events; see the class for argument units and limits. No return value.
    # \~
    def __init__(self, x, y):
        pyautocore.Input.__init__(self)
        self.setMouseRightClick(x, y)


## \~japanese
# マウス入力を準備する短縮クラス。x/yはC intの画面ピクセルです。仮想デスクトップ全体の負座標にも対応し、範囲外は各軸の端へ丸めます。
# 構築だけでは送信しません。Input.sendへlist/tupleで渡します。ネイティブ契約は@ref pyauto_native を参照してください。
# \~english
# Generate a synthetic middle mouse-button-down event.
# x/y are C-int screen pixels across the virtual desktop, including negative coordinates. Values outside its bounds are clamped on each axis.
# Construction only prepares events; pass a list/tuple to Input.send. See @ref pyauto_native for native contracts.
# \~
class MouseMiddleDown(pyautocore.Input):
    ## \~japanese
    # イベントを準備します。引数の単位と制約はクラス説明を参照。戻り値を持ちません。
    # \~english
    # Prepare events; see the class for argument units and limits. No return value.
    # \~
    def __init__(self, x, y):
        pyautocore.Input.__init__(self)
        self.setMouseMiddleDown(x, y)


## \~japanese
# マウス入力を準備する短縮クラス。x/yはC intの画面ピクセルです。仮想デスクトップ全体の負座標にも対応し、範囲外は各軸の端へ丸めます。
# 構築だけでは送信しません。Input.sendへlist/tupleで渡します。ネイティブ契約は@ref pyauto_native を参照してください。
# \~english
# Generate a synthetic middle mouse-button-up event.
# x/y are C-int screen pixels across the virtual desktop, including negative coordinates. Values outside its bounds are clamped on each axis.
# Construction only prepares events; pass a list/tuple to Input.send. See @ref pyauto_native for native contracts.
# \~
class MouseMiddleUp(pyautocore.Input):
    ## \~japanese
    # イベントを準備します。引数の単位と制約はクラス説明を参照。戻り値を持ちません。
    # \~english
    # Prepare events; see the class for argument units and limits. No return value.
    # \~
    def __init__(self, x, y):
        pyautocore.Input.__init__(self)
        self.setMouseMiddleUp(x, y)


## \~japanese
# マウス入力を準備する短縮クラス。x/yはC intの画面ピクセルです。仮想デスクトップ全体の負座標にも対応し、範囲外は各軸の端へ丸めます。
# 構築だけでは送信しません。Input.sendへlist/tupleで渡します。ネイティブ契約は@ref pyauto_native を参照してください。
# \~english
# Generate synthetic middle mouse-button-down and button-up events.
# x/y are C-int screen pixels across the virtual desktop, including negative coordinates. Values outside its bounds are clamped on each axis.
# Construction only prepares events; pass a list/tuple to Input.send. See @ref pyauto_native for native contracts.
# \~
class MouseMiddleClick(pyautocore.Input):
    ## \~japanese
    # イベントを準備します。引数の単位と制約はクラス説明を参照。戻り値を持ちません。
    # \~english
    # Prepare events; see the class for argument units and limits. No return value.
    # \~
    def __init__(self, x, y):
        pyautocore.Input.__init__(self)
        self.setMouseMiddleClick(x, y)


## \~japanese
# ホイール入力を準備する短縮クラス。x/yは仮想デスクトップの画面ピクセル、wheelはfloatで1.0が120単位です。ホイール操作にMOVEフラグはなく、ポインターの移動は行いません。
# 構築だけでは送信しません。Input.sendへlist/tupleで渡します。ネイティブ契約は@ref pyauto_native を参照してください。
# \~english
# Generate a synthetic vertical mouse-wheel event.
# x/y are virtual-desktop screen pixels; float wheel=1.0 is 120 units. Wheel events omit the MOVE flag and do not move the pointer.
# Construction only prepares events; pass a list/tuple to Input.send. See @ref pyauto_native for native contracts.
# \~
class MouseWheel(pyautocore.Input):
    ## \~japanese
    # イベントを準備します。引数の単位と制約はクラス説明を参照。戻り値を持ちません。
    # \~english
    # Prepare events; see the class for argument units and limits. No return value.
    # \~
    def __init__(self, x, y, wheel):
        pyautocore.Input.__init__(self)
        self.setMouseWheel(x, y, wheel)


## \~japanese
# ホイール入力を準備する短縮クラス。x/yは仮想デスクトップの画面ピクセル、wheelはfloatで1.0が120単位です。ホイール操作にMOVEフラグはなく、ポインターの移動は行いません。
# 構築だけでは送信しません。Input.sendへlist/tupleで渡します。ネイティブ契約は@ref pyauto_native を参照してください。
# \~english
# Generate a synthetic horizontal mouse-wheel event.
# x/y are virtual-desktop screen pixels; float wheel=1.0 is 120 units. Wheel events omit the MOVE flag and do not move the pointer.
# Construction only prepares events; pass a list/tuple to Input.send. See @ref pyauto_native for native contracts.
# \~
class MouseHorizontalWheel(pyautocore.Input):
    ## \~japanese
    # イベントを準備します。引数の単位と制約はクラス説明を参照。戻り値を持ちません。
    # \~english
    # Prepare events; see the class for argument units and limits. No return value.
    # \~
    def __init__(self, x, y, wheel):
        pyautocore.Input.__init__(self)
        self.setMouseHorizontalWheel(x, y, wheel)


## @} pyautoinput
