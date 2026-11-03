import fnmatch

import clnch_ini
import clnch_inisettings as ini_settings


class IncrementalSearch:
    def __init__(self):
        self.isearch_value = ""
        self.isearch_type = ini_settings.MISC_ISEARCH_TYPE.get(clnch_ini)

    def fnmatch(self, name, pattern, isearch_type=None):
        if isearch_type is None:
            isearch_type = self.isearch_type

        if isearch_type == "partial":
            return fnmatch.fnmatch(name, "*" + pattern + "*")

        elif isearch_type == "inaccurate":
            new_pattern = "*"
            for ch in pattern:
                new_pattern += ch + "*"
            return fnmatch.fnmatch(name, new_pattern)

        else:
            return fnmatch.fnmatch(name, pattern + "*")

    def cursorUp(
        self, get_string, length, select, scroll_pos, visible_height, margin=0
    ):
        for i in range(select - 1, -1, -1):
            if self.fnmatch(get_string(i), self.isearch_value):
                select = i
                break
        return select

    def cursorDown(
        self, get_string, length, select, scroll_pos, visible_height, margin=0
    ):
        for i in range(select + 1, length):
            if self.fnmatch(get_string(i), self.isearch_value):
                select = i
                break
        return select

    def cursorPageUp(
        self, get_string, length, select, scroll_pos, visible_height, margin=0
    ):
        last_found = -1

        for begin, end in (
            (select - 1, scroll_pos - 1 + margin),
            (scroll_pos - 1, scroll_pos - 1 - visible_height + +margin),
        ):
            for i in range(begin, max(end, -1), -1):
                if self.fnmatch(get_string(i), self.isearch_value):
                    last_found = i

            if last_found != -1:
                break

        if last_found == -1:
            return self.cursorUp(
                get_string, length, select, scroll_pos, visible_height, margin
            )

        return last_found

    def cursorPageDown(
        self, get_string, length, select, scroll_pos, visible_height, margin=0
    ):
        last_found = -1

        for begin, end in (
            (select + 1, scroll_pos + visible_height - margin),
            (
                scroll_pos + visible_height,
                scroll_pos + visible_height + visible_height - margin,
            ),
        ):
            for i in range(begin, min(end, length)):
                if self.fnmatch(get_string(i), self.isearch_value):
                    last_found = i

            if last_found != -1:
                break

        if last_found == -1:
            return self.cursorDown(
                get_string, length, select, scroll_pos, visible_height, margin
            )

        return last_found
