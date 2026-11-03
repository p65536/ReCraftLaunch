import mmap
import re

## @addtogroup misc
## @{

## \~japanese
#  読み取り専用mmapの所有者。HugeFile(fileno)へ開いているファイル記述子を渡します。
#  import例: from ckit.ckit_hugefile import HugeFile。ckit直下へは再公開していません。
#  ファイル自体は閉じず、使用終了時はclose()でマッピングを解放してから元のファイルを閉じます。
#  空ファイルやマッピング失敗はmmapの例外が伝播します。with用のコンテキストマネージャーではありません。
#  通常の小さいファイル処理には標準のopenも使えます。
#
# \~english
#  Owner of a read-only mmap. Pass an open file descriptor to HugeFile(fileno).
#  Import with from ckit.ckit_hugefile import HugeFile; it is not re-exported directly from ckit.
#  Do not close the file; call close() to release the mapping before closing the original file.
#  Empty-file/mapping failures propagate mmap exceptions. This is not a with context manager.
#  Ordinary small-file work may use standard open instead.
#
# \~
class HugeFile:
    def __init__(self, fileno):
        self.mm = mmap.mmap(fileno, 0, access=mmap.ACCESS_READ)

    ## \~japanese
    #  mmapを閉じる。元のファイル記述子は閉じません。解放後は読取りメソッドを使いません。
    #
    # \~english
    #  Close the mmap, without closing the original file descriptor. Do not read through it after closing.
    #
    # \~
    def close(self):
        self.mm.close()


## \~japanese
#  HugeBinaryFile(fileno)で開いたファイルを読取専用でマップします。寿命と例外はHugeFileと同じです。
#  from ckit.ckit_hugefile import HugeBinaryFileで取得します。
#  @sa HugeFile
#
# \~english
#  Map an open file read-only with HugeBinaryFile(fileno), with the same lifetime/errors as HugeFile.
#  Import with from ckit.ckit_hugefile import HugeBinaryFile.
#  @sa HugeFile
#
# \~
class HugeBinaryFile(HugeFile):
    def __init__(self, fileno):
        HugeFile.__init__(self, fileno)

    ## \~japanese
    #  @param offset 開始バイト位置。
    #  @param length 取得バイト数。
    #  @return mmap[offset:offset+length]のbytes。範囲端の切詰め・負値の扱いはPythonスライスに従います。
    #
    # \~english
    #  @param offset Starting byte position.
    #  @param length Byte count.
    #  @return bytes from mmap[offset:offset+length], using Python slice behavior for clipping/negative values.
    #
    # \~
    def getBytes(self, offset, length):
        return self.mm[offset : offset + length]


## \~japanese
#  HugeTextFile(fileno, encoding, offset)で行単位のbytes読取りを行います。
#  from ckit.ckit_hugefile import HugeTextFileで取得します。
#  encodingは行末検出に使う文字コード名で、utf-16-le/utf-16-beなら2バイト形式、それ以外は単バイトのCR/LFを探します。
#  offsetは先頭バイト位置（BOMを読み飛ばす場合等）です。文字列へのデコードはしません。
#  UTF-16のCR/LFはoffsetを基準とする2バイト境界だけで検出します。
#  行位置は要求された行まで64 KiB単位で遅延走査してキャッシュします。先読みは1区間と行末の境界分だけです。
#  mmap上を直接検索し、ファイル全体のbytes複製や全行数の事前解析は行いません。
#  寿命とマッピング例外はHugeFileを参照してください。
#  @sa HugeFile
#
# \~english
#  Read line bytes with HugeTextFile(fileno, encoding, offset).
#  Import with from ckit.ckit_hugefile import HugeTextFile.
#  encoding selects newline detection: utf-16-le/utf-16-be use two-byte forms; others look for single-byte CR/LF.
#  offset is the initial byte position, for example to skip a BOM. Do not decode to strings.
#  Detect UTF-16 CR/LF only at two-byte boundaries relative to offset.
#  Lazily scan/cache line positions in 64 KiB blocks up to the requested line, reading ahead at most one block plus newline overlap.
#  Search the mmap directly, without copying the whole file to bytes or precomputing its line count.
#  See HugeFile for lifetime/mapping errors.
#  @sa HugeFile
#
# \~
class HugeTextFile(HugeFile):
    def __init__(self, fileno, encoding, offset: int):
        HugeFile.__init__(self, fileno)

        self.encoding = encoding

        if self.encoding == "utf-16-le":
            self.line_end_re_object = re.compile(b"\x0d\x00\x0a\x00|\x0d\x00|\x0a\x00")
        elif self.encoding == "utf-16-be":
            self.line_end_re_object = re.compile(b"\x00\x0d\x00\x0a|\x00\x0d|\x00\x0a")
        else:
            self.line_end_re_object = re.compile(b"\x0d\x0a|\x0d|\x0a")

        self.line_pos = [offset]
        self._scan_pos = offset
        self._unit_size = 2 if encoding in ("utf-16-le", "utf-16-be") else 1

    ## \~japanese
    #  @param lineno 0始まりの非負の行番号。
    #  @return 行末CR/LFを含むbytes。末尾に改行がない最終行も返します。
    #  @exception IndexError その行番号までの行末がなく、行に到達できない場合。
    #  デコードが必要なら呼出し元がbytes.decodeを使います。
    #
    # \~english
    #  @param lineno Nonnegative zero-based line number.
    #  @return Line bytes including CR/LF, also returning a final line without a newline.
    #  @exception IndexError When no newline leads to the requested line.
    #  The caller uses bytes.decode when decoded text is needed.
    #
    # \~
    def getLine(self, lineno):
        size = len(self.mm)
        while len(self.line_pos) <= lineno + 1 and self._scan_pos < size:
            end = min(self._scan_pos + 64 * 1024, size)
            # Include up to three extra bytes so a UTF-16 CRLF is never split.
            for match in self.line_end_re_object.finditer(self.mm, self._scan_pos, min(end + 3, size)):
                if match.start() >= end:
                    break
                # Code units are aligned relative to the initial offset, which may be odd.
                if (match.start() - self.line_pos[0]) % self._unit_size:
                    continue
                self.line_pos.append(match.end())
            self._scan_pos = max(end, self.line_pos[-1])

        if lineno >= len(self.line_pos):
            raise IndexError
        start = self.line_pos[lineno]
        if lineno + 1 < len(self.line_pos):
            return self.mm[start : self.line_pos[lineno + 1]]
        return self.mm[start:]


## @} misc
