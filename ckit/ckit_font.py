from ckit import ckitcore

fonts = {}

## @addtogroup theme
## @{


## \~japanese
#  共有キャッシュのフォントを取得する
#  @param name フォント名文字列。
#  @param size 文字の高さ（ピクセル）。
#  @param vertical_padding 縦方向の余白（ピクセル）。既定2。
#  @return 同じ3引数では同一のFontオブジェクト。初回はネイティブFontを作り、作成例外は伝播します。
#  本体はモニターの表示倍率を反映したsize・vertical_paddingを渡します。共有物を破棄しないでください。
#
# \~english
#  Get a shared cached font
#  @param name Font-name string.
#  @param size Character height in pixels.
#  @param vertical_padding Vertical padding in pixels, default 2.
#  @return The same Font object for the same three arguments; create a native Font on first use, propagating creation errors.
#  The application supplies size/vertical_padding adjusted for monitor scaling. Do not destroy a shared font.
#
# \~
def getStockedFont(name, size, vertical_padding=2):
    key = (name, size, vertical_padding)
    if key in fonts:
        return fonts[key]
    else:
        font = ckitcore.Font(name, size, vertical_padding)
        fonts[key] = font
        return font


## @} theme
