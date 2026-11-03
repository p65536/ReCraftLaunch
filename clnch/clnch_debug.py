import ctypes
import os
import sys
import threading
import time
import traceback

import clnch_resource
import clnch_strings as strings

import ckit

# --------------------------------------------------------------------

block_detect_thread = None


def enableBlockDetector():
    global block_detect_thread

    # Callback invoked when the interpreter is blocked for too long.
    def blockDetector():
        print()
        print(strings.BLOCK_DETECTED)
        traceback.print_stack()
        print()

    ckit.enableBlockDetector(blockDetector)

    # Keep the interpreter running periodically so the block detector
    # can detect prolonged blocking.
    class BlockDetectThread(threading.Thread):
        def __init__(self):
            threading.Thread.__init__(self)
            self.canceled = False

        def run(self):
            ckit.setBlockDetector()
            while not self.canceled:
                time.sleep(0.1)

        def cancel(self):
            self.canceled = True

    block_detect_thread = BlockDetectThread()
    block_detect_thread.start()

    ckit.setBlockDetector()


def disableBlockDetector():
    global block_detect_thread

    if block_detect_thread:
        block_detect_thread.cancel()
        block_detect_thread.join()
        block_detect_thread = None


# --------------------------------------------------------------------

exit_timeout_thread = None


def _forceAbort():
    # Collect information about remaining threads.
    message = strings.EXIT_THREADS
    message += "\n"

    for thread in threading.enumerate():
        message += "  %s\n" % str(thread)  # noqa: UP031  # Preserve diagnostic string conversion for custom thread/frame values.
    message += "\n"

    for threadId, stack in sys._current_frames().items():
        message += strings.EXIT_THREAD_ID.format(thread_id=threadId)
        for filename, lineno, name, line in traceback.extract_stack(stack):
            message += strings.EXIT_FRAME.format(
                filename=filename, line=lineno, name=name
            )
            if line:
                message += "    %s\n" % (line.strip())  # noqa: UP031  # Preserve diagnostic string conversion for custom thread/frame values.
        message += "\n"

    ctypes.windll.user32.MessageBoxW(0, message, clnch_resource.clnch_appname, 0)

    os.abort()


def enableExitTimeout():
    global exit_timeout_thread

    # Wait up to ten seconds for cancellation, then report remaining threads
    # and abort the process if shutdown has not completed.
    class ExitTimeoutThread(threading.Thread):
        def __init__(self):
            threading.Thread.__init__(self)
            self.event = threading.Event()

        def run(self):
            ckit.setBlockDetector()
            self.event.wait(10.0)
            if not self.event.isSet():
                _forceAbort()

        def cancel(self):
            self.event.set()

    exit_timeout_thread = ExitTimeoutThread()
    exit_timeout_thread.start()


def disableExitTimeout():
    global exit_timeout_thread

    if exit_timeout_thread:
        exit_timeout_thread.cancel()
        exit_timeout_thread.join()
        exit_timeout_thread = None


# --------------------------------------------------------------------

print_errorinfo_enabled = False


def enablePrintErrorInfo():
    global print_errorinfo_enabled
    print_errorinfo_enabled = True


def disablePrintErrorInfo():
    global print_errorinfo_enabled
    print_errorinfo_enabled = False


def printErrorInfo():
    if print_errorinfo_enabled:
        print(strings.DEBUG_PREFIX, end="")
        traceback.print_exc()


# --------------------------------------------------------------------
