import subprocess
import sys
import threading
from contextlib import ExitStack

from ckit import ckit_misc

## @addtogroup subprocess
## @{

# -------------------------------------------------------------------------


## \~japanese
# コンソールプログラムをサブプロセスとして実行するためのクラス
# 
#  任意のコンソールプログラムをサブプロセスとして実行し、標準出力と標準エラーをまとめて
#  stdout_write へ渡します。省略時は sys.stdout.write を使います。
# 
#  SubProcessオブジェクトは __call__メソッドを持っており、関数のように呼び出すことができます。
# 
#  呼出しは同期的に終了まで待つため、GUIではMainWindow.subProcessCallまたはワーカーから使います。
#  標準出力と標準エラーは行単位で結合しWindowsのmbcsで復号します。UTF-8出力等は文字化け・UnicodeDecodeErrorになる場合があります。
#  起動・読取・復号・stdout_writeの例外は__call__の呼出し元へ伝播し、終了コードへの変換はしません。
#  文字コードの自動判定、シェル解釈、プロセスツリーの強制終了を行うAPIではありません。
#
# \~english
# Run console programs as subprocesses
# 
#  Run a console program as a subprocess and combine its standard output and standard error,
#  passing the result to stdout_write, which defaults to sys.stdout.write.
# 
#  SubProcess implements __call__ and can be called like a function.
# 
#  Calling blocks until termination; in GUI code use MainWindow.subProcessCall or run it in a worker.
#  Combine stdout/stderr line by line and decode using Windows mbcs. Other encodings such as UTF-8 can produce
#  incorrect text or UnicodeDecodeError. Startup/read/decode/stdout_write exceptions propagate from __call__,
#  without conversion to an exit code. This API does not autodetect encodings, interpret shell syntax, or forcibly terminate process trees.
#
# \~
class SubProcess:
    ## \~japanese
    # コンストラクタ
    # 
    #  @param self              -
    #  @param cmd               コマンドと引数のシーケンス
    #  @param cwd               サブプロセスのカレントディレクトリ
    #  @param env               サブプロセスの環境変数
    #  @param stdout_write      標準出力・標準エラーを受け取る関数。文字列を1引数で受け取ります。
    # 
    #  引数 cmd には、サブプロセスとして実行するプログラムと引数をリスト形式で渡します。\n
    #  例:  [ "subst", "R:", "//remote-machine/public/" ]
    # 
    #  cwd=Noneは親の作業ディレクトリを継承します。env=Noneは親の環境を継承し、指定した辞書は環境全体として渡します。
    #  shell=Falseで実行します。引数はリストの個々の文字列として渡し、自分で引用符を追加しないでください。
    #  stdout_writeは__call__を動かしているスレッドで呼びます。このコンストラクター自体はプロセスを作りません。
    #
    # \~english
    # Constructor
    # 
    #  @param self              -
    #  @param cmd               Sequence containing the program and its arguments
    #  @param cwd               Working directory of the subprocess
    #  @param env               Environment variables of the subprocess
    #  @param stdout_write      Function accepting standard output and standard error as one string argument
    # 
    #  Pass the program and its arguments as a list in cmd.\n
    #  Example: [ "subst", "R:", "//remote-machine/public/" ]
    # 
    #  cwd=None inherits the parent's working directory. env=None inherits its environment; a supplied mapping specifies the entire environment.
    #  Use shell=False execution: pass individual argument strings in a list without adding quoting yourself.
    #  stdout_write runs on the thread executing __call__. The constructor itself does not create a process.
    #
    # \~
    def __init__(self, cmd, cwd=None, env=None, stdout_write=None):
        if stdout_write is None:
            stdout_write = sys.stdout.write

        self.cmd = cmd
        self.cwd = cwd
        self.env = env
        self.stdout_write = stdout_write
        self.p = None
        self._lock = threading.Lock()
        self._cancel_requested = False
        self._canceling = False

    ## \~japanese
    # サブプロセス処理を実行する
    # 
    #  出力を mbcs でデコードして stdout_write へ渡し、終了コードを返します。
    #  stdoutのEOF（b''）は通知せず、子プロセスが生存していれば終了を待ちます。パイプが開いたままの無出力時は従来どおり読取りで待ちます。
    #  この呼出しで生成したstdin／stdoutは正常終了・例外・中断時に明示的に閉じます。例外時に子を強制終了・終了待ちしません。
    #  cancel()はEOF後の終了待ち中も従来の終了要求だけを行い、終了を保証しません。
    # 
    # \~english
    # Run the subprocess
    # 
    #  Decode output using mbcs, pass it to stdout_write, and return the exit code.
    #  Do not notify stdout EOF (b''); wait for the final exit code if the child is still alive. Silence with an open pipe still blocks in the read.
    #  Explicitly close the stdin/stdout created by this call on success, exception, or interruption. Exceptions do not forcibly terminate or wait for the child.
    #  During the wait after EOF, cancel() still only requests exit and does not guarantee termination.
    # 
    # \~
    def __call__(self):
        STARTF_USESHOWWINDOW = 1
        SW_HIDE = 0

        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags = STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = SW_HIDE

        p = subprocess.Popen(
            self.cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            shell=False,
            cwd=self.cwd,
            env=self.env,
            startupinfo=startupinfo,
        )
        with ExitStack() as cleanup:
            for stream in (p.stdin, p.stdout):
                if stream is not None:
                    cleanup.enter_context(ckit_misc._cleanup_on_exit(stream.close))
            with self._lock:
                self.p = p
            self._cancel_pending()

            while self.p.poll() is None:
                stdout_write = self.stdout_write
                stdout = self.p.stdout
                if stdout is None:
                    raise AttributeError(
                        "'NoneType' object has no attribute 'readline'", name="readline", obj=None
                    )
                line = stdout.readline()
                if not line:
                    self.p.wait()
                    break
                stdout_write(line.decode("mbcs"))
            stdout = self.p.stdout
            if stdout is None:
                raise TypeError("'NoneType' object is not iterable")
            for line in stdout:
                self.stdout_write(line.decode("mbcs"))

            return self.p.returncode

    ## \~japanese
    # サブプロセスのウィンドウへ終了を要求する
    # 
    #  terminateProcess() を使います。ウィンドウがない場合や要求が受け入れられない場合は終了しません。
    #  起動前・起動中の要求は生成直後に処理します。終了済みなら何もしません。
    #  強制終了・終了待ち・子孫プロセスへの終了要求は行いません。
    # 
    # \~english
    # Request exit through the window of the subprocess
    # 
    #  Use terminateProcess(). A process without a window, or one that rejects the request, may keep running.
    #  Defer requests made before or during startup until creation completes. Do nothing if already exited.
    #  Do not forcibly terminate, wait for exit, or request exit of descendant processes.
    # 
    # \~
    def cancel(self):
        with self._lock:
            if self._canceling:
                return
            self._cancel_requested = True
        self._cancel_pending()

    def _cancel_pending(self):
        with self._lock:
            if not self._cancel_requested or self.p is None:
                return
            self._cancel_requested = False
            p = self.p
            if p.poll() is not None:
                return
            self._canceling = True
        # WM_CLOSE can reenter or block; do not hold the state lock while sending it.
        try:
            ckit_misc.terminateProcess(p.pid)
        finally:
            with self._lock:
                self._canceling = False


# -------------------------------------------------------------------------

## @} subprocess
