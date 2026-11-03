import _thread
import queue
import threading
import time
import traceback

from ckit import ckit_resource, ckitcore

## @addtogroup threadutil
## @{

# -------------------------------------------------------------------------


class _SyncCallRequest:
    def __init__(self, func, args):
        self.func = func
        self.args = args
        self.result = None
        self.error = None
        self.done = threading.Event()


## \~japanese
# 同期呼び出しクラス
# 
#  ほかのスレッドの中で同期して関数を呼び出すためのクラスです。
# 
#  __call__() に渡された関数が、ほかのスレッドが呼び出した check() のなかで実行され、
#  返値が __call__() の返値として返ります。
# 
#  ReCraftLaunchのwindow.synccallを使えばUIタイマーがcheckを行います。
#  ワーカーからwindow.synccall(func, args)と呼ぶと同期的に結果・例外を受け取れます。
#  checkされない間は待機が続きます。UIがワーカーのjoinで停止した状態から呼ぶと相互待機になるため、
#  UIのメッセージ処理を止めないでください。呼出可能オブジェクトや引数のスレッド安全性は呼出し元が管理します。
#  @sa JobQueue
#
# \~english
# Synchronous cross-thread calls
# 
#  Call a function synchronously in another thread.
# 
#  A function passed to __call__() runs inside check() called by another thread,
#  and its result is returned by __call__().
# 
#  Use ReCraftLaunch's window.synccall to have its UI timer poll check. A worker can call
#  window.synccall(func, args) to receive the result or exception synchronously.
#  Waiting continues until check runs. Do not block UI message processing by joining a worker that is waiting for this call;
#  that creates a deadlock. The caller owns thread safety of the callable and arguments.
#  @sa JobQueue
#
# \~
class SyncCall:
    ## \~japanese
    # SyncCallのコンストラクタ
    # 
    #  SyncCallのコンストラクタを呼び出したスレッドは内部に記録され、
    #  単純な関数呼び出しで済むのか、マルチスレッドによる同期処理が必要なのかを
    #  判断するために利用されます。
    # 
    # \~english
    # SyncCall constructor
    # 
    #  The thread that constructs SyncCall is recorded internally
    #  to decide whether a direct function call suffices
    #  or cross-thread synchronization is required.
    # 
    # \~
    def __init__(self):
        self._requests = queue.Queue()
        self.main_thread_id = _thread.get_ident()

    ## \~japanese
    # 関数を同期呼び出しする
    # 
    #  @param self  -
    #  @param func  関数
    #  @param args  引数リスト
    #  @return      func(*args)の返値
    # 
    #  SyncCallのコンストラクタを呼び出したスレッドのなかで __call__() を呼び出した場合は、
    #  単純に func(*args) を呼び出します。
    # 
    #  SyncCallのコンストラクタを呼び出したスレッドとは別のスレッドで __call__() を呼び出した場合は、
    #  SyncCallのコンストラクタを呼び出したスレッドのなかで check() が呼ばれるまで待って、
    #  check() のなかで同期的に func(*args) が呼び出されます。
    #  実行時の例外は呼び出し元へ送出されます。
    # 
    # \~english
    # Call a function synchronously
    # 
    #  @param self  -
    #  @param func  Function
    #  @param args  Argument sequence
    #  @return      Result of func(*args)
    # 
    #  Calling __call__() from the thread that constructed SyncCall
    #  directly invokes func(*args).
    # 
    #  Calling __call__() from a different thread
    #  waits for the constructing thread to call check(),
    #  which synchronously invokes func(*args).
    #  Exceptions from func are raised in the caller.
    # 
    # \~
    def __call__(self, func, args=()):
        if _thread.get_ident() == self.main_thread_id:
            return func(*args)
        request = _SyncCallRequest(func, args)
        self._requests.put(request)
        request.done.wait()
        if request.error is not None:
            raise request.error.with_traceback(request.error.__traceback__)
        return request.result

    ## \~japanese
    # 関数を同期呼び出しが要求されているかをチェックし、必要に応じて呼び出しを行う
    # 
    #  check() は、SyncCallのコンストラクタを呼び出したスレッドから呼び出す必要があります。
    # 
    #  別のスレッドの __call__() 呼び出しに渡された func, args を、
    #  check() のなかで同期的に呼び出します。
    #  受付順に1要求だけ処理し、要求がなければ直ちに戻ります。
    # 
    # \~english
    # Check for and execute a requested synchronous call
    # 
    #  Call check() from the thread that constructed SyncCall.
    # 
    #  The func and args passed to __call__() in another thread
    #  are invoked synchronously inside check().
    #  Process one request in FIFO order, returning immediately if none is pending.
    # 
    # \~
    def check(self):
        assert _thread.get_ident() == self.main_thread_id
        try:
            request = self._requests.get_nowait()
        except queue.Empty:
            return
        try:
            request.result = request.func(*request.args)
        except BaseException as error:  # noqa: BLE001  # Transfer every callback failure to its waiting caller.
            request.error = error
        finally:
            request.done.set()


# -------------------------------------------------------------------------

JOB_STATUS_WAITING = 0
JOB_STATUS_RUNNING = 1
JOB_STATUS_FINISHED = 2


## \~japanese
# ジョブのアイテム
# 
#  ジョブの命令１つを意味するクラスです。
#  JobItemオブジェクトを、JobQueue.enqueue() に渡すことで実行することが出来ます。
# 
#  @sa JobQueue
# 
#  subthread_func(item)はワーカー、finished_func(item)はcheck()/join()の呼出し元で実行します。
#  各関数の戻り値は使いません。結果・エラーは独自属性へ保存し完了側で読みます。未開始取消でも完了関数は呼ばれます。
#  ワーカー例外はキューが表示し、正常完了と同じく完了通知へ進みます。例外オブジェクトの自動保存はしません。
#  cancel()/pause()は要求だけで、実行関数がisCanceled()/waitPaused()を確認する協調処理です。
#  args等の属性はすべてのジョブに存在するわけではなく、必要な呼出し元が設定します。
#  @sa JobQueue
#
# \~english
# Job item
# 
#  Represents one unit of background work.
#  Pass a JobItem to JobQueue.enqueue() to queue its execution.
# 
#  @sa JobQueue
# 
#  subthread_func(item) runs in the worker; finished_func(item) runs in the caller of check()/join().
#  Callback return values are ignored. Store results/errors in your own attributes and read them at completion.
#  Completion also runs for work canceled before starting. The queue prints worker exceptions and proceeds to completion,
#  without automatically storing the exception. cancel()/pause() only request action; running work must cooperate
#  using isCanceled()/waitPaused(). Attributes such as args are not present on every item; callers set them when needed.
#  @sa JobQueue
#
# \~
class JobItem:
    # Set by command jobs; other jobs may leave this absent.
    args: list[str]
    # Set only by ShellExecuteCommand; None uses the args list.
    arg_string: str | None

    # Set by the application's help command; other jobs may leave these absent.
    help_message: str | None
    help_opened: bool

    ## \~japanese
    # コンストラクタ
    #  @param self              -
    #  @param subthread_func    サブスレッドの中で実行される関数
    #  @param finished_func     サブスレッド処理終了後、JobQueue.check()／join()の呼出し元（通常はメインスレッド）で呼ばれる関数
    #  各コールバックはNoneなら呼びません。subthread_func(item)とfinished_func(item)の戻り値は使いません。
    #  完了前に必要な独自属性を初期化し、ワーカーで設定した結果を完了関数で読みます。
    #
    # \~english
    # Constructor
    #  @param self              -
    #  @param subthread_func    Function executed in the worker thread
    #  @param finished_func     Function called after worker processing ends, on the thread calling JobQueue.check() / join() (normally the main thread)
    #  A None callback is not called. Return values from subthread_func(item) and finished_func(item) are ignored.
    #  Initialize needed custom attributes before enqueue, then read worker results from the completion callback.
    #
    # \~
    def __init__(self, subthread_func=None, finished_func=None):
        self.status = JOB_STATUS_WAITING
        self.cancel_requested = False
        self.pause_requested = False
        self.pause_waiting = False
        self.subthread_func = subthread_func
        self.finished_func_list = [finished_func]

    ## \~japanese
    # ジョブのキャンセルを要求する
    # \~english
    # Request job cancellation
    # \~
    def cancel(self):
        self.cancel_requested = True

    ## \~japanese
    # ジョブのキャンセルが要求されているかをチェックする
    # 
    #  @return True:キャンセルが要求されている  False:キャンセルが要求されていない
    # 
    # \~english
    # Check whether job cancellation was requested
    # 
    #  @return True if cancellation was requested; False otherwise
    # 
    # \~
    def isCanceled(self):
        return self.cancel_requested

    ## \~japanese
    # ジョブの一時停止を要求する
    # \~english
    # Request that the job pause
    # \~
    def pause(self):
        self.pause_requested = True

    ## \~japanese
    # ジョブの再開を要求する
    # \~english
    # Request that the job resume
    # \~
    def restart(self):
        self.pause_requested = False

    ## \~japanese
    # ジョブの一時停止が要求されているかをチェックする
    # 
    #  @return True:一時停止が要求されている  False:一時停止が要求されていない
    # 
    # \~english
    # Check whether a pause was requested
    # 
    #  @return True if a pause was requested; False otherwise
    # 
    # \~
    def isPaused(self):
        return self.pause_requested

    ## \~japanese
    # ジョブの一時停止が要求されている間、処理をブロックする
    # 
    #  @return True:一時停止が発生した  False:一時停止しなかった
    # 
    # \~english
    # Block while a pause is requested
    # 
    #  @return True if the job paused; False otherwise
    # 
    # \~
    def waitPaused(self):
        if self.pause_requested:
            print(ckit_resource.strings["job_suspended"])
            while self.pause_requested and not self.cancel_requested:
                self.pause_waiting = True
                time.sleep(0.1)
            self.pause_waiting = False
            print(ckit_resource.strings["job_resumed"])
            return True
        return False


_job_queue_list = []
_job_queue = None


## \~japanese
# ジョブのキュー
# 
#  ジョブのアイテムを順番に処理する機能を持つクラスです。
# 
#  @sa JobItem
# 
#  キュー作成でスレッドを開始しますが、enqueueだけでは実行を始めません。checkが先頭を開始し、
#  完了関数を実行してから次へ進む逐次キューです。未処理件数は実行中・完了通知待ちも含みます。
#  ReCraftLaunchは起動時に既定キューを作り、UIタイマーでcheckAllを呼び、終了時にjoinします。
#  拡張は既定キューを再作成・join・destroyせず利用します。独自キューは自分でcheck・cancel・join・destroyを管理します。
#  キュー操作と完了処理は同じ管理スレッドから行い、ワーカーでGUIや管理側の待機操作を呼ばないでください。
#  @sa JobItem, SyncCall
#
# \~english
# Job queue
# 
#  Process job items sequentially.
# 
#  @sa JobItem
# 
#  Construction starts a thread, but enqueue alone does not start work. check starts the head item and
#  runs its completion callback before advancing: execution is sequential. Item count includes running work and pending completion.
#  ReCraftLaunch creates the default queue at startup, polls checkAll on the UI timer, and joins at shutdown.
#  Extensions should use it without recreating, joining or destroying it. Own check/cancel/join/destroy for a private queue.
#  Perform queue management and completion on the same controlling thread; do not access GUI or call management waits from workers.
#  @sa JobItem, SyncCall
#
# \~
class JobQueue(threading.Thread):
    ## \~japanese
    # すべてのJobQueueに関してcheck()を呼び出す
    # 
    # \~english
    # Call check() on every registered JobQueue
    # 
    # \~
    @staticmethod
    def checkAll():
        for job_queue in _job_queue_list:
            job_queue.check()

    ## \~japanese
    # すべてのJobQueueに関してjoin()を呼び出す
    # 
    # \~english
    # Call join() on every registered JobQueue
    # 
    # \~
    @staticmethod
    def joinAll():
        for job_queue in _job_queue_list:
            job_queue.join()

    ## \~japanese
    # すべてのJobQueueに関してcancel()を呼び出す
    # 
    # \~english
    # Call cancel() on every registered JobQueue
    # 
    # \~
    @staticmethod
    def cancelAll():
        for job_queue in _job_queue_list:
            job_queue.cancel()

    ## \~japanese
    # デフォルトキューを作成する
    # 
    # \~english
    # Create the default queue
    # 
    # \~
    @staticmethod
    def createDefaultQueue():
        global _job_queue
        _job_queue = JobQueue()

    ## \~japanese
    # デフォルトキューを取得する
    # 
    #  @return 既存のJobQueue、作成前ならNone。新しいキューは作りません。
    #  通常のコマンド実行時には本体が作成済みです。モジュールimport時に既存と決めつけず、実行時に取得します。
    #
    # \~english
    # Get the default queue
    # 
    #  @return Existing JobQueue, or None before creation. Do not create a queue.
    #  The application has created it by normal command execution. Obtain it when executing, not assuming it exists during module import.
    #
    # \~
    @staticmethod
    def defaultQueue():
        return _job_queue

    ## \~japanese
    # コンストラクタ
    #  引数なしで新しい管理対象キューを作り、ワーカースレッドを開始します。起動だけではジョブを実行しません。
    #  独自キューの所有者はcheckで処理を進め、cancel・join・destroyの順で停止・登録解除します。
    #
    # \~english
    # Constructor
    #  Create a new managed queue and start its worker thread with no arguments. This alone does not execute jobs.
    #  A private queue's owner must poll check, then use cancel/join/destroy to request cancellation, stop, and unregister.
    #
    # \~
    def __init__(self):
        threading.Thread.__init__(self)
        self.sema = threading.Semaphore(0)
        self.items = []
        self.cancel_requested = False
        self.pause_requested = False
        self.pause_waiting = False
        _job_queue_list.append(self)
        self.start()

    ## \~japanese
    # キューを管理対象から外す
    # 
    #  スレッドは終了しません。join() で終了を待ったあとに呼び出してください。
    # \~english
    # Remove the queue from management
    # 
    #  This does not stop the thread. Call after join() has waited for termination.
    # \~
    def destroy(self):
        _job_queue_list.remove(self)

    def run(self):
        ckitcore.setBlockDetector()

        while True:
            self.sema.acquire()

            if self.cancel_requested:
                break

            item = self.items[0]

            while self.pause_requested and not self.cancel_requested and not item.isCanceled():
                self.pause_waiting = True
                time.sleep(0.1)
            self.pause_waiting = False

            try:
                if not item.isCanceled() and item.subthread_func:
                    item.subthread_func(item)
            except BaseException:  # noqa: BLE001  # Keep failed callbacks from stranding jobs.
                traceback.print_exc()

            item.status = JOB_STATUS_FINISHED

    ## \~japanese
    # キューにジョブを投入する
    # 
    #  @param self  -
    #  @param item  JobItemオブジェクト
    # 
    #  実行開始と完了通知には check() が必要です。通常はメインスレッドのタイマーから checkAll() を呼び出します。
    # 
    # \~english
    # Enqueue a job
    # 
    #  @param self  -
    #  @param item  JobItem instance
    # 
    #  Execution and completion notifications require check(). Normally call checkAll() from a main-thread timer.
    # 
    # \~
    def enqueue(self, item):
        self.items.append(item)

    ## \~japanese
    # キューの状態をチェックし必要な処理を実行する
    # 
    #  @return None。先頭ジョブを開始するか、終了済み項目の完了関数を実行して次へ進みます。
    #  UIを操作する完了関数がある場合はUIスレッドから呼び、別スレッドから並行に呼ばないでください。
    #
    # \~english
    # Check queue state and process pending work
    # 
    #  @return None. Start the head job, or run finished callbacks and advance to subsequent items.
    #  Call on the UI thread when completion touches GUI, and do not call concurrently from other threads.
    #
    # \~
    def check(self):
        while True:
            if len(self.items) == 0:
                return

            item = self.items[0]

            if item.status == JOB_STATUS_WAITING:
                if item.isCanceled():
                    item.status = JOB_STATUS_FINISHED
                else:
                    item.status = JOB_STATUS_RUNNING
                    self.sema.release()
                    return

            elif item.status == JOB_STATUS_RUNNING:
                return

            elif item.status == JOB_STATUS_FINISHED:
                for finished_func in item.finished_func_list:
                    if finished_func:
                        try:
                            finished_func(item)
                        except BaseException:  # noqa: BLE001  # Finish queue cleanup even if a completion callback fails.
                            traceback.print_exc()

                if len(self.items):
                    del self.items[0]

            else:
                assert 0

    ## \~japanese
    # キューに登録されているジョブの数を調査する
    #  @return 未開始・実行中・完了通知待ちの項目数を表す整数。停止を待つ操作ではありません。
    #
    # \~english
    # Get the number of jobs registered in the queue
    #  @return Integer count including waiting, running and pending-completion items; do not wait for termination.
    #
    # \~
    def numItems(self):
        return len(self.items)

    ## \~japanese
    # キューに登録されている全てのジョブへキャンセルを要求する
    # 
    #  未開始のジョブは実行しません。実行中の処理は isCanceled() を確認して終了する必要があります。
    # \~english
    # Request cancellation of every registered job
    # 
    #  Unstarted jobs are skipped. Running functions must check isCanceled() and exit cooperatively.
    # \~
    def cancel(self):
        for item in self.items:
            item.cancel()

    ## \~japanese
    # キューに登録されている全てのジョブの終了を待つ
    # 
    #  完了通知も処理し、最後にキューのスレッドを終了します。終了後のキューは再利用できません。
    #  一時停止を解除して待機します。キャンセル要求は行いません。
    #  完了通知を実行するスレッドから呼び出してください。キュー自身の実行関数からは呼び出せません。
    # \~english
    # Wait for all registered jobs to finish
    # 
    #  Process completion notifications and finally stop the queue thread. A stopped queue cannot be reused.
    #  Resume paused processing before waiting. Do not request cancellation.
    #  Call from the thread responsible for completion notifications, never from the queue's own worker function.
    # \~
    def join(self):
        self.restart()
        while True:
            if len(self.items) == 0:
                break
            self.check()
            time.sleep(0.1)

        self.cancel_requested = True
        self.sema.release()

        threading.Thread.join(self)

    ## \~japanese
    # キューの処理を一時停止する
    #  実行中の処理が一時停止するか終了するまで待ちます。未開始ジョブの開始や完了通知は行いません。
    # \~english
    # Pause queue processing
    #  Wait until running work pauses or finishes. Do not start waiting jobs or deliver completion notifications.
    # \~
    def pause(self):
        self.pause_requested = True
        for item in self.items:
            item.pause()

        while True:
            if len(self.items) == 0:
                break
            if self.items[0].status != JOB_STATUS_RUNNING:
                break
            if self.cancel_requested:
                break
            if self.pause_waiting:
                break
            if self.items[0].pause_waiting:
                break
            time.sleep(0.1)

    ## \~japanese
    # 一時停止されたキューの処理を再開する
    # \~english
    # Resume paused queue processing
    # \~
    def restart(self):
        self.pause_requested = False
        for item in self.items:
            item.restart()


# -------------------------------------------------------------------------


## \~japanese
# 定期的なサブスレッド処理
# 
#  Cronのエントリ１つを意味するクラスです。
#  CronItemオブジェクトを、CronTable.add() に渡すことで、実行を予約することが出来ます。
#  関数は func(item) としてテーブルのスレッドから呼び出され、同じテーブル内では逐次実行されます。
#  最初は作成時から interval 秒経過後、その後は前回の処理完了から interval 秒経過後に実行します。
#  時刻の確認は約0.1秒間隔で行うため、指定時刻ちょうどの実行は保証しません。
# 
#  @sa CronTable
# 
# \~english
# Periodic background work
# 
#  Represents one periodic task.
#  Pass a CronItem to CronTable.add() to schedule it.
#  Call func(item) on the table's thread; functions in one table run sequentially.
#  Run first after interval seconds from item creation, then after interval seconds from the previous completion.
#  Check the time approximately every 0.1 seconds; exact execution times are not guaranteed.
# 
#  @sa CronTable
# 
# \~
class CronItem:
    ## \~japanese
    # コンストラクタ
    #  @param self      -
    #  @param func      サブスレッドの中で実行される関数
    #  @param interval  呼び出し間隔 (sec)
    #  func(item)の戻り値は使いません。処理中の例外はテーブル側が通知し、以後の周期実行は継続します。
    #  intervalには秒数を数値で渡し、処理時間を含む厳密な周期・リアルタイム実行は期待しないでください。
    #
    # \~english
    # Constructor
    #  @param self      -
    #  @param func      Function executed in the worker thread
    #  @param interval  Interval between calls in seconds
    #  Ignore the return value of func(item). The table reports callback exceptions and continues later scheduling.
    #  Pass a numeric interval in seconds; do not expect strict periods including runtime or real-time execution.
    #
    # \~
    def __init__(self, func, interval):
        self.status = JOB_STATUS_WAITING
        self.cancel_requested = False
        self.func = func
        self.interval = interval
        self.last = time.time()

    ## \~japanese
    # Cronのキャンセルを要求する
    # 
    #  以降の未開始の呼び出しを停止します。呼び出し直前の確認を通過した回は実行される場合があります。
    #  実行中の関数は強制停止せず、完了も待ちません。関数側で isCanceled() を確認して終了してください。
    #  登録は解除しません。繰り返し呼び出しても結果は同じで、再開には新しい CronItem を作成します。
    # \~english
    # Request cancellation of the periodic task
    # 
    #  Stop future unstarted calls. A call that has passed the final cancellation check may still run.
    #  Do not forcibly stop or wait for a running function. The function should check isCanceled() and exit cooperatively.
    #  Keep the item registered. Repeated cancellation is harmless; create a new CronItem to resume.
    # \~
    def cancel(self):
        self.cancel_requested = True

    ## \~japanese
    # Cronのキャンセルが要求されているかをチェックする
    # 
    #  @return True:キャンセルが要求されている  False:キャンセルが要求されていない
    # 
    # \~english
    # Check whether cancellation of the periodic task was requested
    # 
    #  @return True if cancellation was requested; False otherwise
    # 
    # \~
    def isCanceled(self):
        return self.cancel_requested


_cron_thread_list = []
_cron_thread = None


## \~japanese
# 定期的なサブスレッド処理を管理するためのテーブル
# 
#  CronItemを定期的に処理する機能を持つクラスです。
# 
#  @sa CronItem
# 
#  本体は通常CronTableを作成しません。defaultCronTable()は作成前ならNoneです。
#  作成でスレッドが始まり、JobQueueと違ってUIによるcheckは不要です。関数はGUIへ直接アクセスしないでください。
#  独自テーブルは所有者がjoinしてからdestroyします。完了通知の専用コールバックや関数の戻り値転送はありません。
#  intervalは秒で、GUIタイマー・registerStatusBarのミリ秒とは異なります。
#
# \~english
# Manage periodic background work
# 
#  Periodically execute registered CronItem functions.
# 
#  @sa CronItem
# 
#  The application does not normally create a CronTable; defaultCronTable() returns None before creation.
#  Construction starts its thread; unlike JobQueue, no UI check is needed. Callbacks must not access GUI directly.
#  An owner of a private table must join before destroy. There is no separate completion callback or result forwarding.
#  interval is in seconds, unlike GUI timers/registerStatusBar intervals in milliseconds.
#
# \~
class CronTable(threading.Thread):
    ## \~japanese
    # 管理対象のすべてのCronTableに関してjoin()を呼び出す
    # 
    #  全テーブルへキャンセルを要求してから、各テーブルの終了を待ちます。
    # 
    # \~english
    # Call join() on every managed CronTable
    # 
    #  Request cancellation on all tables before waiting for each to terminate.
    # 
    # \~
    @staticmethod
    def joinAll():
        CronTable.cancelAll()
        for cron_thread in _cron_thread_list:
            cron_thread.join()

    ## \~japanese
    # 管理対象のすべてのCronTableに関してcancel()を呼び出す
    # 
    # \~english
    # Call cancel() on every managed CronTable
    # 
    # \~
    @staticmethod
    def cancelAll():
        for cron_thread in _cron_thread_list:
            cron_thread.cancel()

    ## \~japanese
    # デフォルトCronTableを作成する
    # 
    # \~english
    # Create the default CronTable
    # 
    # \~
    @staticmethod
    def createDefaultCronTable():
        global _cron_thread
        _cron_thread = CronTable()

    ## \~japanese
    # デフォルトCronTableを取得する
    # 
    # \~english
    # Get the default CronTable
    # 
    # \~
    @staticmethod
    def defaultCronTable():
        return _cron_thread

    ## \~japanese
    # コンストラクタ
    #  引数なしで管理対象テーブルを作り、スレッドを開始する。登録はadd(CronItem(...))で行います。
    #
    # \~english
    # Constructor
    #  Create a managed table and start its thread with no arguments; register tasks using add(CronItem(...)).
    #
    # \~
    def __init__(self):
        threading.Thread.__init__(self)
        self.lock = threading.Lock()
        self.items = []
        self.cancel_requested = False
        _cron_thread_list.append(self)
        self.start()

    ## \~japanese
    # CronTableを管理対象から外す
    # 
    #  スレッドは終了しません。join() で終了を待ったあとに呼び出してください。
    # \~english
    # Remove the CronTable from management
    # 
    #  This does not stop the thread. Call after join() has waited for termination.
    # \~
    def destroy(self):
        _cron_thread_list.remove(self)

    def run(self):
        ckitcore.setBlockDetector()

        while True:
            with self.lock:
                if self.cancel_requested:
                    return
                items = list(self.items)

            for item in items:
                with self.lock:
                    if self.cancel_requested:
                        return
                    if item not in self.items or item.isCanceled():
                        continue

                    now = time.time()
                    delta = now - item.last
                    if delta <= item.interval:
                        continue

                # Release the lock during callbacks so registration and cancellation can proceed.
                try:
                    item.func(item)
                except BaseException:  # noqa: BLE001  # Report timer callback failures without stopping the timer thread.
                    traceback.print_exc()
                item.last = time.time()

            time.sleep(0.1)

    ## \~japanese
    # CronTableにアイテムを登録する
    # 
    #  @param self  -
    #  @param item  CronItemオブジェクト
    # 
    #  join() の開始後は RuntimeError になります。キャンセル済みの項目を登録しても再開しません。
    # 
    # \~english
    # Register an item in the CronTable
    # 
    #  @param self  -
    #  @param item  CronItem instance
    # 
    #  Raise RuntimeError after join() begins. Registering a canceled item does not restart it.
    # 
    # \~
    def add(self, item):
        self.lock.acquire()
        try:
            if self.cancel_requested:
                raise RuntimeError("Cannot add an item to a stopped CronTable")
            self.items.append(item)
        finally:
            self.lock.release()

    ## \~japanese
    # CronTableからアイテムを削除する
    # 
    #  @param self  -
    #  @param item  CronItemオブジェクト
    # 
    #  以降の未開始の呼び出しを停止します。開始が確定した回は実行される場合があります。
    #  実行中の関数へキャンセルは要求しません。必要な場合は item.cancel() も呼び出してください。
    # 
    # \~english
    # Remove an item from the CronTable
    # 
    #  @param self  -
    #  @param item  CronItem instance
    # 
    #  Stop future unstarted calls. A call whose start was already committed may still run.
    #  Do not request cancellation of a running function. Call item.cancel() as well if needed.
    # 
    # \~
    def remove(self, item):
        self.lock.acquire()
        try:
            self.items.remove(item)
        finally:
            self.lock.release()

    ## \~japanese
    # CronTableから全てのアイテムを削除する
    # 
    #  @param self  -
    # 
    #  登録解除だけを行い、実行中の関数へキャンセルは要求しません。
    #  開始が確定した回は実行される場合があります。
    # 
    # \~english
    # Remove all items from the CronTable
    # 
    #  @param self  -
    # 
    #  Only unregister items; do not request cancellation of running functions.
    #  A call whose start was already committed may still run.
    # 
    # \~
    def clear(self):
        self.lock.acquire()
        try:
            del self.items[:]
        finally:
            self.lock.release()

    ## \~japanese
    # CronTableに登録されているアイテムの数を調査する
    # 
    #  キャンセル済みでも登録解除していない項目は件数に含めます。
    # \~english
    # Get the number of registered CronTable items
    # 
    #  Include canceled items that have not been unregistered.
    # \~
    def numItems(self):
        return len(self.items)

    ## \~japanese
    # 現在登録されている全てのアイテムへキャンセルを要求する
    # 
    #  実行中の関数の完了は待たず、登録も解除しません。テーブル自体は存続し、新しい項目を登録できます。
    # \~english
    # Request cancellation of every currently registered item
    # 
    #  Do not wait for running functions or unregister items. The table remains active and accepts new items.
    # \~
    def cancel(self):
        self.lock.acquire()
        try:
            for item in self.items:
                item.cancel()
        finally:
            self.lock.release()

    ## \~japanese
    # 呼び出しを停止し、実行中の関数とテーブルのスレッドの終了を待つ
    # 
    #  登録項目にもキャンセルを要求します。将来の予約をすべて実行する操作ではありません。
    #  開始後は新しい項目を登録できません。実行関数自身からは呼び出せません。
    #  関数が終了要求に応答しない場合は、その関数が戻るまで待ちます。通信等にはタイムアウトを設けてください。
    # \~english
    # Stop scheduling and wait for the running function and table thread to terminate
    # 
    #  Also request cancellation of registered items. Do not execute all future scheduled calls.
    #  New items cannot be added after this begins. Never call from the table's own worker function.
    #  If a function ignores cancellation, wait until it returns. Use timeouts for network operations and other blocking work.
    # \~
    def join(self):
        with self.lock:
            self.cancel_requested = True
            for item in self.items:
                item.cancel()
        threading.Thread.join(self)


## @} threadutil

# -------------------------------------------------------------------------
