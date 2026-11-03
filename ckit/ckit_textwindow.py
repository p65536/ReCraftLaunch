from ckit import ckitcore
from ckit.ckit_misc import _cleanup_on_exit

## @addtogroup widget
## @{

## \~japanese
#  表示セル単位の文字描画を行うWindow。ckit.TextWindowとして取得します。
#  MainWindow・ListWindow・Dialogの基底で、UIスレッドから操作します。ネイティブのHWNDと描画用TextPlaneを所有するため、
#  不要になった窓はdestroy()で破棄します。既存の本体窓を拡張から破棄しないでください。
#  x/yは画面ピクセル、width/height・描画位置は表示セルです。getWindowRect/getClientSize/getClientRectはピクセルなので混同しません。
#  キー・文字・描画・有効状態等のイベント処理は呼出し元が接続します。通常の入力・一覧・フォームには既存の高水準APIを使えます。
#  @sa MainWindow, ListWindow, Dialog
#
# \~english
#  Cell-based text drawing window exposed as ckit.TextWindow.
#  Base of MainWindow/ListWindow/Dialog. Operate on the UI thread. Own an HWND and drawing TextPlane,
#  and call destroy when an owned window is no longer needed; extensions must not destroy the application's existing windows.
#  x/y use screen pixels; width/height and text positions use display cells. getWindowRect/getClientSize/getClientRect use pixels.
#  The caller connects key/character/paint/activation events. Prefer existing high-level input/menu/form APIs for ordinary use.
#  @sa MainWindow, ListWindow, Dialog
#
# \~
class TextWindow(ckitcore.Window):
    ## \~japanese
    #  @param args キーワード引数。ネイティブWindow引数に、以下の文字窓用引数を追加します。
    #  - width/height: 初期の表示セル数。既定80/24。
    #  - font: Fontオブジェクト。指定時はfont_name/font_sizeによる新規作成をしません。
    #  - font_name/font_size: フォント名と高さ（ピクセル）。既定空文字列/12。
    #    parent_windowがありfont_nameが空なら親のフォントを共有します。
    #  - border_size: 枠のピクセル幅。既定1。
    #  - size_handler(width, height): セル単位のサイズ変更通知。
    #  - cursor/cursor0_color/cursor1_color: caret/caret0_color/caret1_colorへ変換する別名。
    #  その他の位置・タイトル・表示・親・キー等の引数はWindowへ渡します。生成途中の失敗は取得済み資源を解放して伝播します。
    #  破棄済み親はValueError、Win32生成失敗はOSErrorです。明示Noneの親は従来どおりTypeErrorです。
    #
    # \~english
    #  @param args Keyword arguments: native Window options plus the following text-window options.
    #  - width/height: Initial display-cell counts, default 80/24.
    #  - font: Font object; when supplied, do not create one from font_name/font_size.
    #  - font_name/font_size: Font name and pixel height, default empty name/12.
    #    With parent_window and an empty font_name, share the parent's font.
    #  - border_size: Border width in pixels, default 1.
    #  - size_handler(width, height): Resize notification in cells.
    #  - cursor/cursor0_color/cursor1_color: Aliases converted to caret/caret0_color/caret1_color.
    #  Forward remaining position/title/show/parent/key options to Window. Release acquired resources and propagate construction errors.
    #  A destroyed parent raises ValueError; Win32 creation failure raises OSError. An explicit None parent still raises TypeError.
    #
    # \~
    def __init__(self, **args):
        try:
            args["caret0_color"] = args["cursor0_color"]
            del args["cursor0_color"]
        except KeyError:
            pass

        try:
            args["caret1_color"] = args["cursor1_color"]
            del args["cursor1_color"]
        except KeyError:
            pass

        try:
            args["caret"] = args["cursor"]
            del args["cursor"]
        except KeyError:
            pass

        try:
            parent_window = args["parent_window"]
        except KeyError:
            parent_window = None

        try:
            width = args["width"]
        except KeyError:
            width = 80

        try:
            height = args["height"]
        except KeyError:
            height = 24

        try:
            font = args["font"]
            del args["font"]
        except KeyError:
            font = None

        try:
            font_name = args["font_name"]
            del args["font_name"]
        except KeyError:
            font_name = ""

        try:
            font_size = args["font_size"]
            del args["font_size"]
        except KeyError:
            font_size = 12

        try:
            self.__border_size = args["border_size"]
        except KeyError:
            self.__border_size = 1

        self.__horizontal_padding = 0

        try:
            self.__size_handler = args["size_handler"]
        except KeyError:
            self.__size_handler = None

        if not font:
            if parent_window and not font_name:
                font = parent_window.__text.getFont()
            else:
                font = ckitcore.Font(font_name, font_size)

        char_size = font.getCharSize()

        args["width"] = width * char_size[0] + self.__border_size * 2
        args["height"] = height * char_size[1] + self.__border_size * 2
        args["size_handler"] = self.__onSize
        args["sizing_handler"] = self.__onSizing

        ckitcore.Window.__init__(self, **args)

        with _cleanup_on_exit(ckitcore.Window.destroy, self, error_only=True):
            self.__text = ckitcore.TextPlane(self, (0, 0), (1, 1), 0.0)
            with _cleanup_on_exit(self.__text.destroy, error_only=True):
                self.__text.setFont(font)
                self.__adjustTextPlane()

    ## \~japanese
    #  描画用TextPlaneとネイティブ窓を破棄する
    #  @return None。片方の解放に失敗しても残りを試みます。破棄後の操作は行いません。
    #  ネイティブ窓の破棄失敗はOSError。先に破棄したTextPlaneは復元しません。
    #
    # \~english
    #  Destroy the drawing TextPlane and native window
    #  @return None. Attempt remaining cleanup after a failure. Do not operate on a destroyed object.
    #  Native window destruction failure raises OSError; an already destroyed TextPlane is not restored.
    #
    # \~
    def destroy(self):
        with _cleanup_on_exit(ckitcore.Window.destroy, self):
            self.__text.destroy()

    def __onSizing(self, size):
        char_size = self.__text.getCharSize()

        width = size[0]
        height = size[1]

        width -= (self.__border_size + self.__horizontal_padding) * 2
        width -= width % char_size[0]
        width += (self.__border_size + self.__horizontal_padding) * 2

        height -= self.__border_size * 2
        height -= height % char_size[1]
        height += self.__border_size * 2

        size[0] = width
        size[1] = height

    def __onSize(self, width, height):
        self.__adjustTextPlane()

        if self.__size_handler:
            char_size = self.__text.getCharSize()
            width = (
                width - (self.__border_size + self.__horizontal_padding) * 2
            ) // char_size[0]
            height = (height - self.__border_size * 2) // char_size[1]
            self.__size_handler(width, height)

    def __adjustTextPlane(self):
        client_size = self.getClientSize()
        char_size = self.__text.getCharSize()

        width = client_size[0] - (self.__border_size + self.__horizontal_padding) * 2
        height = client_size[1] - self.__border_size * 2

        width -= width % char_size[0]
        height -= height % char_size[1]

        x = (client_size[0] - width) // 2
        y = (client_size[1] - height) // 2

        self.__text.setPosition((x, y))
        self.__text.setSize((width, height))

        self.__size_in_char = (width // char_size[0], height // char_size[1])

    ## \~japanese
    #  @param x 表示開始のXセル位置。
    #  @param y Yセル位置。
    #  @param width 出力領域のセル幅。
    #  @param height 更新領域の高さ。文字列は1行に描き、自動改行しません。
    #  @param attr ckit.Attribute。
    #  @param str 描画文字列。
    #  @param offset 描画開始をxからずらすセル数。負値は左へスクロール。既定0。
    #  @return None。後続の描画処理へ更新を通知し、同期的な画面転送は保証しません。
    #
    # \~english
    #  @param x Starting X cell.
    #  @param y Y cell.
    #  @param width Output region width in cells.
    #  @param height Update-region height; text is drawn on one line without automatic wrapping.
    #  @param attr ckit.Attribute.
    #  @param str Text to draw.
    #  @param offset Cell displacement from x; negative values scroll left. Default 0.
    #  @return None. Mark drawing updates without guaranteeing synchronous screen transfer.
    #
    # \~
    def putString(self, x, y, width, height, attr, str, offset=0):
        return self.__text.putString(x, y, width, height, attr, str, offset)

    ## \~japanese
    #  @param args (text, tab_width=4, offset=0)。textは文字列、tab_widthは正のセル数。
    #  @return フォントで測定した表示セル幅の整数。ピクセル幅・Python文字数ではありません。
    #  offsetはタブ展開を始めるセル位置（負値も可）。返却幅はoffsetを含まない相対幅です。tab_width<=0はValueError。
    #  計測幅がC intの上限を超える場合はOverflowError。
    #
    # \~english
    #  @param args (text, tab_width=4, offset=0), with string text and positive cell tab_width.
    #  @return Integer font-measured display-cell width, not pixel width or Python string length.
    #  offset is the starting cell for tab expansion (negative allowed). The returned width excludes offset. tab_width<=0 raises ValueError.
    #  A measured width above the C int limit raises OverflowError.
    #
    # \~
    def getStringWidth(self, *args):
        return self.__text.getStringWidth(*args)

    ## \~japanese
    #  @param args (text, tab_width=4, offset=0)。
    #  @return 各位置までの表示セル幅のタプル。最後は全体の幅です。
    #  位置はネイティブのUTF-16コード単位であり、非BMP文字ではPython文字列インデックスと一致しません。
    #  offsetはタブ展開開始セルです。先頭値は0、末尾値はgetStringWidthと同じ相対幅。tab_width<=0はValueError。
    #  UTF-16長はINT_MAX未満、計測幅はINT_MAX以下。上限超過はOverflowError、変換・配列・tuple・要素の確保失敗はMemoryError。
    #
    # \~english
    #  @param args (text, tab_width=4, offset=0).
    #  @return Tuple of display-cell widths at positions, ending with the full width.
    #  Positions use native UTF-16 code units, differing from Python string indices for non-BMP characters.
    #  offset is the starting cell for tabs. The first value is 0; the last is the same relative width as getStringWidth. tab_width<=0 raises ValueError.
    #  UTF-16 length must be below INT_MAX and measured width at most INT_MAX; exceeding either raises OverflowError.
    #  Conversion, array, tuple or item allocation failures raise MemoryError.
    #
    # \~
    def getStringColumns(self, *args):
        return self.__text.getStringColumns(*args)

    ## \~japanese
    #  @return (0, 0, 幅, 高さ)のクライアント矩形。ここはピクセル単位で、セル数ではありません。
    #
    # \~english
    #  @return Client rectangle (0, 0, width, height) in pixels, not display cells.
    #
    # \~
    def getClientRect(self):
        return (0, 0) + self.getClientSize()

    ## \~japanese
    #  @return 通常状態のクライアント寸法から枠・余白を除いた(セル幅, 行数)。
    #
    # \~english
    #  @return (cell_width, rows) of the normal-state client area after removing border/padding.
    #
    # \~
    def getNormalSize(self):
        size = self.getNormalClientSize()
        char_size = self.__text.getCharSize()
        width = (
            size[0] - (self.__border_size + self.__horizontal_padding) * 2
        ) // char_size[0]
        height = (size[1] - self.__border_size * 2) // char_size[1]
        return (width, height)

    ## \~japanese
    #  @param args (x, y)の表示セル位置。
    #  @return クライアント内のピクセル座標(x, y)。文字面の余白を含めて変換します。
    #
    # \~english
    #  @param args Display-cell position (x, y).
    #  @return Client-pixel (x, y), including text-plane padding.
    #
    # \~
    def charToClient(self, *args):
        return self.__text.charToClient(*args)

    ## \~japanese
    #  @param args (x, y)の表示セル位置。
    #  @return 画面上のピクセル座標(x, y)。
    #
    # \~english
    #  @param args Display-cell position (x, y).
    #  @return Screen-pixel position (x, y).
    #
    # \~
    def charToScreen(self, *args):
        return self.__text.charToScreen(*args)

    ## \~japanese
    #  setCaretPositionと同じセル単位の入口です。(-1, -1)で非表示にします。
    #  @return None。
    #
    # \~english
    #  Cell-based alias for setCaretPosition; (-1, -1) hides the caret.
    #  @return None.
    #
    # \~
    def setCursorPos(self, *args):
        return self.__text.setCaretPosition(*args)

    ## \~japanese
    #  @param args (x, y)の表示セル位置。(-1, -1)はキャレットを非表示にします。
    #  TextPlaneの非表示指定へ委譲します。それ以外の負数は通常のセル座標として変換します。
    #  @return None。親窓の有効状態・IME対象管理とは別です。
    #
    # \~english
    #  @param args Display-cell position (x, y); (-1, -1) hides the caret.
    #  Delegate to the TextPlane hide sentinel. Other negative values use normal cell-coordinate conversion.
    #  @return None; distinct from parent activation/IME targeting.
    #
    # \~
    def setCaretPosition(self, *args):
        return self.__text.setCaretPosition(*args)

    ## \~japanese
    #  @param args setCaretColorへ渡す引数列。
    #  @return None。cursor名の互換入口で、ネイティブのcaret色設定へ委譲します。
    #
    # \~english
    #  @param args Argument sequence forwarded to setCaretColor.
    #  @return None. Cursor-named entry delegating to native caret color settings.
    #
    # \~
    def setCursorColor(self, *args):
        return self.setCaretColor(*args)

    ## \~japanese
    #  @param x 位置の画面Xピクセル座標。
    #  @param y 位置の画面Yピクセル座標。
    #  @param width 内容のセル幅。
    #  @param height 内容の行数。
    #  @param origin ORIGIN_X_*/ORIGIN_Y_*のビット和。x/yが指す基準点を指定。
    #  @return None。枠と横余白を加算してネイティブのピクセル寸法に変換します。
    #
    # \~english
    #  @param x Screen X position in pixels.
    #  @param y Screen Y position in pixels.
    #  @param width Content width in cells.
    #  @param height Content height in rows.
    #  @param origin Combination of ORIGIN_X_*/ORIGIN_Y_* specifying the anchor represented by x/y.
    #  @return None. Add border/horizontal padding and convert to native pixel dimensions.
    #
    # \~
    def setPosSize(self, x, y, width, height, origin):
        char_size = self.__text.getCharSize()
        width = (
            width * char_size[0] + (self.__border_size + self.__horizontal_padding) * 2
        )
        height = height * char_size[1] + self.__border_size * 2
        return self.setPositionAndSize(x, y, width, height, origin)

    ## \~japanese
    #  @return 現在の内容幅の表示セル数を表す整数。
    #
    # \~english
    #  @return Integer current content width in display cells.
    #
    # \~
    def width(self):
        return self.__size_in_char[0]

    ## \~japanese
    #  @param padding 左右それぞれのピクセル余白。
    #  @return None。文字面を再配置します。ウィンドウ外寸を指定する操作ではありません。
    #
    # \~english
    #  @param padding Pixel padding on each horizontal side.
    #  @return None. Reposition the text plane without specifying outer-window dimensions.
    #
    # \~
    def setHorizontalPadding(self, padding):
        self.__horizontal_padding = padding
        self.__adjustTextPlane()

    ## \~japanese
    #  @return 現在の内容高の文字行数を表す整数。
    #
    # \~english
    #  @return Integer current content height in character rows.
    #
    # \~
    def height(self):
        return self.__size_in_char[1]

    ## \~japanese
    #  @return 文字面の現在のFont。共有参照で、新規設定・窓寸法変更は行いません。
    #
    # \~english
    #  @return Current text-plane Font reference, without changing font or window dimensions.
    #
    # \~
    def getFont(self):
        return self.__text.getFont()

    ## \~japanese
    #  @param name フォント名。
    #  @param size 文字高のピクセル数。
    #  @return None。新しいFontを文字面に設定します。フォント作成失敗は伝播します。
    #  窓のセル数・外寸の再調整が必要ならsetPosSize等も行ってください。
    #
    # \~english
    #  @param name Font name.
    #  @param size Character height in pixels.
    #  @return None. Set a newly created Font on the text plane; propagate font creation errors.
    #  Use setPosSize or related operations if cell count/outer dimensions need adjustment.
    #
    # \~
    def setFont(self, name, size):
        font = ckitcore.Font(name, size)
        self.__text.setFont(font)

    ## \~japanese
    #  @param window フォントを共有する元のTextWindow。
    #  @return None。元の窓のFont参照を設定し、窓自体の寸法は変更しません。
    #
    # \~english
    #  @param window Source TextWindow whose font is shared.
    #  @return None. Set its Font reference without changing this window's dimensions.
    #
    # \~
    def setFontFromTextWindow(self, window):
        font = window.__text.getFont()
        self.__text.setFont(font)

    ## \~japanese
    #  @param font 設定するFontオブジェクト。
    #  @return None。参照を保持して設定し、窓自体の寸法は変更しません。
    #
    # \~english
    #  @param font Font object to use.
    #  @return None. Retain/set the font reference without changing window dimensions.
    #
    # \~
    def setFontFromFontObject(self, font):
        self.__text.setFont(font)

    ## \~japanese
    #  @return 1表示セルの(ピクセル幅, ピクセル高)。フォントと縦余白を反映します。
    #
    # \~english
    #  @return Pixel (width, height) of one display cell, including font vertical padding.
    #
    # \~
    def getCharSize(self):
        return self.__text.getCharSize()


## @} widget
