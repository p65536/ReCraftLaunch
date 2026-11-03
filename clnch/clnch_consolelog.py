"""Retained console text and display rows, independent of the GUI toolkit."""
import bisect
import threading


class Log:
    def __init__(self):
        self.lock = threading.Lock()
        self.log = [""]
        self.last_line_terminated = False
        self.revision = 0
        self.first_line = 0

    def write(self, s):
        self.lock.acquire()
        try:
            changed = bool(s)
            while True:
                return_pos = s.find("\n")
                if return_pos < 0:
                    break
                if self.last_line_terminated:
                    self.log.append("")
                self.log[-1] += s[:return_pos]
                # Consume only the CR paired with this LF, including across writes.
                self.log[-1] = self.log[-1].removesuffix("\r")
                s = s[return_pos + 1 :]
                self.last_line_terminated = True
            if len(s) > 0:
                if self.last_line_terminated:
                    self.log.append("")
                self.log[-1] += s
                self.last_line_terminated = False
            if len(self.log) > 1000:
                self.first_line += len(self.log) - 1000
                self.log = self.log[-1000:]
            if changed:
                self.revision += 1
        finally:
            self.lock.release()

    def numLines(self):
        return len(self.log)

    def snapshot(self):
        with self.lock:
            return self.revision, self.first_line, self.log[:]

    def getLine(self, lineno):
        try:
            return self.log[lineno]
        except IndexError:
            return ""


def _wrapLine(text, width, measure, char_widths):
    if measure(text) <= width:
        return [(0, len(text))]
    spans = []
    start, columns = 0, 0
    for index, char in enumerate(text):
        if char == "\t":
            char_width = 4 - columns % 4
        else:
            if char not in char_widths:
                char_widths[char] = measure(char)
            char_width = char_widths[char]
        if columns + char_width > width and index > start:
            spans.append((start, index))
            start, columns = index, 0
            if char == "\t":
                char_width = 4
        columns += char_width
    spans.append((start, len(text)))
    return spans


class _LogLayout:
    """One stable text/row snapshot; construction never mutates its predecessor."""

    def __init__(self, log, width, measure, previous=None):
        self.log = log
        self.width = max(width, 1)
        self.revision, self.first_line, lines = log.snapshot()
        reusable = previous if previous is not None and previous.log is log and previous.width == self.width else None
        if reusable is not None and reusable.revision == self.revision:
            self.lines, self.rows = reusable.lines, reusable.rows
            return
        removed = self.first_line - reusable.first_line if reusable is not None else 0
        if reusable is not None:
            # Only the old last logical line and newly appended lines can change.
            prefix = max(len(reusable.lines) - removed - 1, 0)
            self.lines = reusable.lines[removed : removed + prefix]
            first = bisect.bisect_left(reusable.rows, (self.first_line,))
            last = bisect.bisect_left(reusable.rows, (self.first_line + prefix,))
            self.rows = reusable.rows[first:last]
        else:
            self.lines, self.rows = [], []
        char_widths = {}
        for lineno in range(len(self.lines), len(lines)):
            text = lines[lineno]
            old = lineno + removed
            if reusable is not None and old < len(reusable.lines) and reusable.lines[old][0] == text:
                spans = reusable.lines[old][1]
            else:
                spans = _wrapLine(text, self.width, measure, char_widths)
            self.lines.append((text, spans))
            self.rows.extend((self.first_line + lineno, start, end) for start, end in spans)

    def selectedText(self, selection):
        left, right = sorted(selection)
        return "\r\n".join(
            self.lines[line][0][left[1] if line == left[0] else 0 :
                               right[1] if line == right[0] else None]
            for line in range(left[0], min(right[0] + 1, len(self.lines)))
        )


