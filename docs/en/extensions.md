# Implementing Python Extensions

This guide assumes basic Python knowledge. You can follow the examples without reading the application source. Each example is independent: merge the calls into your existing configure function instead of defining it a second time.

## Choose where to write code

Use config for standard settings and commands.json for application/URL registrations. Use custom.py for custom behavior. Put reusable or larger functions in Python modules under scripts/ in the active settings location, and import and call them from custom.py.

| File | Location and role |
|---|---|
| custom.py | In the active settings directory; optionally defines configure(window) and configure_ListWindow(window) |
| scripts/my_echo.py | Under that same directory; your module implementing a feature |
| extensions/ | Shared modules supplied beside the application; avoid giving a personal module the same name |

With application-local settings, these are settings/custom.py and settings/scripts/my_echo.py. With AppData settings, they are %APPDATA%/ReCraftLaunch/custom.py and %APPDATA%/ReCraftLaunch/scripts/my_echo.py. Check config > Settings location. Do not edit an inactive copy.

If custom.py does not exist, copy the bundled settings/_custom.py to the active location. Do not overwrite an existing file. Both hooks may be omitted. If defined, each must be callable and accept one window argument; do not assign None or a number. Callable validation happens before old resources are released. Keep one definition of each hook and add calls in the desired order. A plain scripts module may use its own entry function name; configure(window) is a convention used in these examples.

configure receives the existing MainWindow at startup and on reload, after standard keys and standard/JSON commands have been installed. configure_ListWindow receives each ListWindow after its standard keymap is set up. Do not create another MainWindow. Import clnch for application APIs, ckit for shared components/constants, and pyauto for external-window/input automation.

## Write a command directly in custom.py

Add the following to custom.py (merge into its existing configure if present).

<!-- example: echo_inline -->
```python
def configure(window):
    def command_Echo(info):
        if not info.args:
            print("Usage: myecho;text [more text]")
            return
        print(" | ".join(info.args))
    window.launcher.command_list.append(("myecho", command_Echo))
```

Save and run reload (config > Reload configuration). Open the console with Ctrl+F10 and execute myecho;hello world. The console shows hello | world. myecho alone prints the usage message. myecho;hello "" world includes an empty argument and prints hello |  | world.

The registered handler takes one CommandInfo. Do not call command_Echo while registering it. Named input splits only at the first semicolon. CommandInfo.args is the Windows-parsed list after the name; arg_string retains the original quotes, spaces and later semicolons. For example, myecho;"a b" "" one;two gives args=["a b", "", "one;two"]. ShellExecuteCommand uses arg_string when it is not None, without rebuilding it from args. Set arg_string=None if Python changes args before launching. A directly constructed CommandInfo defaults to arg_string=None and retains the existing joinArgs quoting of its args list.

## Move code into scripts/ and add a key

Create scripts/my_echo.py with this complete content:

<!-- example: echo_module -->
```python
def configure(window):
    def command_Echo(info):
        if not info.args:
            print("Usage: myecho;text [more text]")
            return
        print(" | ".join(info.args))

    def command_KeyEcho(info):
        print("Input: " + " | ".join(info.args))

    window.launcher.command_list.append(("myecho", command_Echo))
    window.keymap["C-F9"] = command_KeyEcho
```

Add these calls to custom.py:

<!-- example: echo_setup -->
```python
def configure(window):
    import my_echo
    my_echo.configure(window)
```

Run reload after creating or changing my_echo.py. Execute myecho;hello world as before. Type draft;one, then press Ctrl+F9: the console shows Input: draft;one, and the main input remains available.

The two handlers are separate because named commands and keys receive different input:

| Invocation | CommandInfo.args | CommandInfo.mod |
|---|---|---|
| myecho;a b followed by Enter | ["a", "b"] | Modifiers held when Enter is accepted |
| A main-input key binding, with myecho;a b in the input | ["myecho;a b"] | 0, regardless of the bound modifier |
| A ListWindow key binding | [] | 0 |

List-window keys leave arg_string=None. File associations receive the file path first in args; arg_string contains that quoted path followed by the original argument text. Custom commandline_list protocols retain their own input syntax and CommandInfo contracts.

Use bit masks such as ckit.MODKEY_CTRL when testing named-command modifiers. A handler's Python return value is not a general success flag. CommandSequence tests info.result, initially True; set it to False to try the next handler in that sequence. A string returned by an input command can replace a still-existing input field, but does not open a new field after the top-level input has ended. Prefer an explicit action as in these examples.

window.keymap handles a main-input key without automatically ending input or recording history. window.cmd_keymap is checked first and normally ends input and records its text. Standard Alt+Enter preserves input, selection and focus when disabled, and ends input when enabled. Standard F12 ends input regardless of the result. Neither adds history. F12 deactivates the main window. External launches leave focus changes to the target application. Both keymaps pass the entire input as one args element and as arg_string, without parsing semicolons or quotes. To bind an existing application command, use a callable such as window.command.ConsoleToggle, without parentheses. Key strings accept C-/Ctrl-, S-/Shift-, A-/Alt-, W-/Win- combinations, for example C-S-F9; key names are case-insensitive. Assigning a key replaces its existing binding. Use del window.keymap["C-F9"] to remove that binding; it does not restore the previous function.

### Command names and JSON

JSON names cannot contain the semicolon (`;`) argument separator or any whitespace, including leading, trailing, or internal spaces, tabs, line breaks, and full-width spaces (`str.isspace()`). The empty name remains valid. An empty JSON registration, such as `{"about": {}}`, takes priority over a same-name built-in and does nothing for named input or aliases. See <a href="command_json.html">commands.json Format</a> for the JSON schema and GUI validation of the empty command.

Names are matched case-insensitively, and the first matching entry in window.launcher.command_list wins. Use a unique lowercase name. An appended custom entry does not override an existing standard/JSON entry of the same name. These Python commands do not appear in the JSON command editor/list. JSON aliases and F12 path resolution do not resolve custom handlers appended to this public list. After GUI JSON saves, duplication, or deletion, existing managed entries are updated or removed in place, preserving the relative positions and order of custom entries. A custom command registered at the front with insert(0, ...) keeps its priority. New names are inserted just after the last managed slot (including a slot being deleted), before trailing custom entries. If the current list has no managed entries, new entries follow the custom entries. A full Reload rebuilds standard/JSON registrations and uses the result of custom.configure() as the new baseline.

### Change list-window keys

Add this separate hook to custom.py:

<!-- example: list_setup -->
```python
def configure_ListWindow(window):
    window.keymap["C-P"] = window.command.CursorUp
    window.keymap["C-N"] = window.command.CursorDown
```

Run reload, then open a list such as history. Ctrl+P/Ctrl+N move up/down. This hook also applies to other ListWindow-based lists, including menus created by popMenu; it is not limited to the JSON command list. Main-window and list-window keymaps are different objects.

## Ask for text and offer completion

Create scripts/my_input.py:

<!-- example: input_module -->
```python
def configure(window):
    def command_Ask(info):
        def candidates(update_info):
            left = update_info.text[:update_info.selectionLeft()]
            return [s for s in ("apple", "apricot", "banana") if s.startswith(left)], 0

        text = window.commandLine(
            "Fruit", candidate_handler=candidates, auto_complete=False
        )
        if text is None:
            print("Canceled")
            return
        print("Fruit: " + text)

    window.launcher.command_list.append(("myask", command_Ask))
```

Add these calls to custom.py and run reload:

<!-- example: input_setup -->
```python
def configure(window):
    import my_input
    my_input.configure(window)
```

Execute myask. Type ap and press Tab to complete the common prefix; choose apple or apricot with the completion keys and press Enter. The console prints Fruit: followed by the accepted text. For cancellation, clear the input with Esc, hide the console with Esc if visible, and press Esc with empty input. The console prints Canceled.

commandLine returns text captured on Enter, or None if input ends before any capture. This example uses its default Enter handling, so empty-string input is a valid accepted value. Do not use if not text to distinguish cancellation from empty input. Esc first clears nonempty input or hides the console; it is not unconditionally a cancel button.

The completion callback receives update_info with text and selection. selectionLeft() gives the left end of the selection. Return (candidate_strings, replacement_start); here replacement starts at character 0. Indices are Python string positions, not pixels. Callbacks run during input on the UI thread; keep them short and do not retain the input-control object after the call ends. See the MainWindow.commandLine API for update, key, Enter, Esc and status callbacks.

## Show a menu and handle cancellation

Create scripts/my_menu.py:

<!-- example: menu_module -->
```python
from clnch import popMenu

def configure(window):
    def command_Pick(info):
        items = [("Documents", "docs"), ("Downloads", "downloads")]
        index = popMenu(window, 40, 12, title="Choose", items=items)
        if index < 0:
            print("Canceled")
            return
        print("Choice: " + items[index][1])

    window.launcher.command_list.append(("mypick", command_Pick))
```

Add these calls to custom.py and run reload:

<!-- example: menu_setup -->
```python
def configure(window):
    import my_menu
    my_menu.configure(window)
```

Execute mypick. Choose Downloads with the arrow keys and Enter; the console prints Choice: downloads. Esc prints Canceled. Check the negative result before indexing items: Python index -1 would otherwise select the final item.

max_width and max_height can be omitted. Omitted axes follow the work-area limit; an integer adds a limit for that axis.

popMenu returns a zero-based index, or -1 on cancellation. With return_modkey=True it returns (index, modifiers), including on cancellation; unpack it before checking the index. Each item is a tuple whose first field is the display label; you own any additional fields. popMenu manages disabling/restoring its parent and destroying the temporary window. A directly constructed ListWindow requires you to manage those operations and its lifetime yourself.

## Build a dialog with multiple fields

Create scripts/my_form.py:

<!-- example: dialog_module -->
```python
from contextlib import ExitStack
import ckit

def configure(window):
    def command_Form(info):
        was_enabled = window.isEnabled()
        dialog = ckit.Dialog(window, "Profile", [
            ckit.Dialog.Edit("name", 0, 32, "Name", "Alex"),
            ckit.Dialog.Choice("style", 0, "Style", ["Short", "Long"], 0),
        ])
        with ExitStack() as cleanup:
            if was_enabled:
                cleanup.callback(window.activate)
                cleanup.callback(window.enable, True)
            cleanup.callback(dialog.destroy)
            window.enable(False)
            dialog.messageLoop()
            result, values = dialog.getResult()
        if result == ckit.Dialog.RESULT_OK:
            print("Profile: " + values["name"] + ", " + str(values["style"]))
        else:
            print("Canceled")

    window.launcher.command_list.append(("myform", command_Form))
```

Add these calls to custom.py and run reload:

<!-- example: dialog_setup -->
```python
def configure(window):
    import my_form
    my_form.configure(window)
```

Execute myform to enter a name and style. Leave Alex and Short selected and press Enter to print Profile: Alex, 0; Esc prints Canceled. Tab/Shift+Tab move focus, and Left/Right change the style. Choice values are zero-based indices, not display strings.

Dialog.getResult() returns (RESULT_OK or RESULT_CANCEL, dictionary_of_values_by_ID). Cancellation still returns values, but this example does not apply them. Edit width and indent use display cells. Give fields unique IDs. ExitStack destroys the dialog and restores parent state on acceptance, cancellation or exceptions, without enabling/activating a parent that was already disabled.

Dialog.Item subclasses accept visible(dialog) predicates. Hidden fields still appear in the result dictionary, so decide separately whether their values apply. Rebuilding visibility can recreate edit controls; do not retain their internal widget references. Prefer Dialog for ordinary forms. Directly placed Widget objects require you to handle paint, keys, characters, focus and destruction yourself.

## Run work while keeping the UI responsive

Create scripts/my_worker.py:

<!-- example: worker_module -->
```python
import threading

def configure(window):
    def command_Count(info):
        canceled = threading.Event()

        def work():
            count = 0
            for unused in range(20):
                if canceled.wait(0.05):
                    return None
                count += 1
            return count

        result = window.subThreadCall(
            work, (), canceled.set, raise_error=True
        )
        if result is None:
            print("Canceled")
        else:
            window.setStatusMessage("Count: " + str(result), timeout=2000)

    window.launcher.command_list.append(("mycount", command_Count))
```

Add these calls to custom.py and run reload:

<!-- example: worker_setup -->
```python
def configure(window):
    import my_worker
    my_worker.configure(window)
```

Execute mycount and wait about one second. A Count: 20 status message appears for two seconds. Execute it again and press Esc during the wait; the console prints Canceled. No files or network services are changed.

subThreadCall runs work on a worker thread while the UI thread processes messages. Its return value is the worker result. The Esc callback runs on the UI thread and only requests cancellation; work must cooperate. This example uses an Event so the worker can stop. Do not access GUI objects from work. The status update occurs after the call returns, on the UI thread.

raise_error=True re-raises a worker exception in the caller; the default reports it and returns None. UI-side exceptions have a different lifetime: hooks are restored, but a running worker is not forcibly stopped or joined without limit. Keep worker-owned resources bounded and close them in the worker.

For work that should return immediately to normal launcher input, use JobItem and the application's JobQueue.defaultQueue(). A worker callback takes the JobItem; its completion callback also takes that item and runs on the thread polling the queue (normally the UI thread). Store results explicitly on the item; a worker return value is not delivered automatically. Cancellation is cooperative and completion may run even for skipped/canceled work. Do not join or destroy the application's default queue from an extension.

For a console program, window.subProcessCall([program, argument, ...]) forwards combined output to the console and returns the exit code, or None after a reported worker failure. Pass a list without manual quoting; it uses shell=False. cwd=None and env=None inherit the parent's directory and environment. enable_cancel=True requests process exit on Esc; programs without a suitable window may continue running. See the subprocess API for encoding and cancellation limits.

## Queue a job and return to normal input

Create scripts/my_job.py:

<!-- example: job_module -->
```python
import time
import ckit

_active = None

def configure(window):
    def release():
        if _active is not None:
            _active.cancel()
            raise RuntimeError("Job is stopping; retry reload after completion")

    window.registerConfigCleanup(release)

    def command_Start(info):
        global _active
        if _active is not None:
            print("Already queued")
            return
        queue = ckit.JobQueue.defaultQueue()
        if queue is None:
            print("No default job queue")
            return

        def work(item):
            try:
                for unused in range(20):
                    if item.isCanceled():
                        return
                    item.waitPaused()
                    time.sleep(0.05)
                    item.count += 1
            except Exception as error:
                item.error = error

        def finished(item):
            global _active
            try:
                if item.error is not None:
                    print("Job failed: " + str(item.error))
                elif item.isCanceled():
                    print("Canceled")
                else:
                    window.setStatusMessage("Job: " + str(item.count), timeout=2000)
            finally:
                _active = None

        item = ckit.JobItem(work, finished)
        item.count = 0
        item.error = None
        _active = item
        queue.enqueue(item)

    def command_Cancel(info):
        if _active is not None:
            _active.cancel()

    window.launcher.command_list.append(("myjob", command_Start))
    window.launcher.command_list.append(("mycancel", command_Cancel))
```

Add these calls to custom.py and run reload:

<!-- example: job_setup -->
```python
def configure(window):
    import my_job
    my_job.configure(window)
```

Execute myjob: normal launcher input is available immediately, and Job: 20 appears after completion. Execute mycancel while it runs to request cancellation. A second myjob during a pending job prints Already queued. Canceling before the worker starts also prints Canceled when the application polls completion.

On reload, the old generation's release requests cooperative cancellation and raises to defer application until completion is reported. Wait for Canceled in the console, then run reload again. The old module and registrations remain in place meanwhile; no running job is forcibly stopped. After completion, the new module starts with _active set to None. Results and errors are initialized before enqueue so the completion callback can handle even a skipped job. The worker does no GUI work; finished runs on the application's queue-polling/UI thread. Do not call checkAll yourself while the application already polls it. This module owns the item, not the application's queue. Run mycancel and allow completion before exiting.

## Edit multiple lines in an owned window

Use commandLine for ordinary input and Dialog for forms. For a dedicated multiline editor, embed [TextWidget](@ref textwidget) in a parent TextWindow. Save the following as scripts/my_text.py in the active settings directory. This example is a keyboard-only temporary editor.

Standard launcher themes lack the full editor palette, so prepare_colors initializes TextWidget's shared color_* cache from current fg/bg/selection colors. Other TextWidgets also use these colors. Extensions using syntax colors should supply editor theme colors and call TextWidget.updateColor() instead. This example does not change the application theme or settings files.

<!-- example: textwidget_module -->
```python
import ckit


def prepare_colors():
    fg = ckit.getColor("fg")
    bg = ckit.getColor("bg")
    selected = ckit.getColor("select_bg")
    for name in ("fg", "bar_fg", "bar_error_fg", "bookmark1", "bookmark2", "bookmark3",
                 "syntax_text", "syntax_keyword", "syntax_name", "syntax_number", "syntax_string",
                 "syntax_preproc", "syntax_comment", "syntax_space", "syntax_error"):
        setattr(ckit.TextWidget, "color_" + name, fg)
    for name in ("diff_bg1", "diff_bg2", "diff_bg3", "line_cursor", "search_mark"):
        setattr(ckit.TextWidget, "color_" + name, bg)
    ckit.TextWidget.color_select_fg = ckit.getColor("select_fg")
    ckit.TextWidget.color_select_bg = selected
    gray = sum(selected) // 3
    ckit.TextWidget.color_select_bg_inactive = (gray, gray, gray)


class EditorWindow(ckit.TextWindow):
    def __init__(self, owner):
        self.edit = None
        self.result = None
        super().__init__(parent_window=owner, width=60, height=12,
                         title="Text: Ctrl+Enter prints, Esc cancels", title_bar=True,
                         sysmenu=True, resizable=False, show=False, caret=True,
                         bg_color=ckit.getColor("bg"),
                         activate_handler=self.onActivate, close_handler=self.quit,
                         keydown_handler=self.onKeyDown, char_handler=self.onChar,
                         move_handler=self.onMove)
        try:
            self.command = ckit.CommandMap(self)
            self.edit = ckit.TextWidget(self, 0, 0, self.width(), self.height())
            self.edit_list = [self.edit]
            self.edit.configure()
            bindings = {
                "Left": "CursorLeft", "Right": "CursorRight", "Up": "CursorUp", "Down": "CursorDown",
                "Home": "CursorLineBegin", "End": "CursorLineEnd",
                "S-Left": "SelectLeft", "S-Right": "SelectRight", "S-Up": "SelectUp", "S-Down": "SelectDown",
                "Return": "InsertReturn", "Back": "DeleteCharLeft", "Delete": "DeleteCharRight",
                "C-A": "SelectDocument", "C-Z": "Undo", "C-Y": "Redo", "C-Space": "CompleteAbbrev",
            }
            for key, name in bindings.items():
                self.edit.keymap[key] = getattr(self.edit, "command_" + name)
            self.edit.modifyText(text="apple apricot\nType here")
            self.edit.doc.clearModified()
        except BaseException:
            self.destroy()
            raise

    def onActivate(self, active):
        if self.edit is not None:
            self.edit.enableCursor(active)
            if not active:
                self.setCursorPos(-1, -1)
                self.edit.closeList()
            self.edit.paint()

    def onMove(self, x, y):
        if self.edit is not None:
            self.edit.onWindowMove()

    def onKeyDown(self, vk, mod):
        if vk == ckit.VK_ESCAPE:
            self.quit()
            return True
        if vk == ckit.VK_RETURN and mod == ckit.MODKEY_CTRL:
            self.result = self.edit.getText(self.edit.pointDocumentBegin(), self.edit.pointDocumentEnd())
            self.quit()
            return True
        return self.edit.onKeyDown(vk, mod)

    def onChar(self, ch, mod):
        self.edit.onChar(ch, mod)

    def executeCommand(self, name, info):
        return self.edit.executeCommand(name, info)

    def destroy(self):
        try:
            if self.edit is not None:
                self.edit.destroy()
                self.edit = None
        finally:
            super().destroy()


def configure(window):
    def command_Text(info):
        prepare_colors()
        enabled = window.isEnabled()
        editor = EditorWindow(window)
        try:
            window.enable(False)
            editor.show(True)
            editor.activate()
            editor.messageLoop()
            print("Canceled" if editor.result is None else editor.result)
        finally:
            try:
                editor.destroy()
            finally:
                window.enable(enabled)
                if enabled:
                    window.activate()
    window.launcher.command_list.append(("mytext", command_Text))
```

Merge these calls into the existing custom.py configure and run reload:

<!-- example: textwidget_setup -->
```python
def configure(window):
    import my_text
    my_text.configure(window)
```

Execute mytext and type. Enter inserts a line break, Shift+arrows select, Ctrl+A selects all and Ctrl+Z/Y undo/redo. Type ap at a word end and press Ctrl+Space for apple/apricot candidates; Enter commits. Ctrl+Enter prints the entire document to the console and closes. Esc or the close button prints Canceled. No file is saved. Remove the setup call and run reload to disable it.

Supply host.command before constructing the control, call configure to create its keymap, then assign keys. WordCompletion collects from host.edit_list. Route activation/caret/candidate changes and parent movement, and destroy the control before its owned window. Resizable hosts also need onWindowSize, setPosSize and paint wiring. To support mouse input, pass parent clientToChar cell coordinates/fractions to onLeftButtonDown and related methods, and manage drag capture in the host.

### Documents, positions and saving

- edit.doc is a Document; edit.selection is a Selection. point(line, index) takes zero-based lines and Python character positions, not display cells. Range endpoints are exclusive on the right. Reacquire Points after edits.
- setDocument(doc) switches notifications and moves to the beginning. After a mode change, call configure and reapply custom keys. The major mode configures first, then minor modes in insertion order; command lookup searches minor modes in reverse order.
- Document(path, TextMode(), encoding=None) reads an existing file. None and nonexistent paths create empty documents. readFile requires a seekable binary stream; writeFile writes at the current position of binary output without seeking, truncating, closing or marking saved. Open the destination appropriately; after successful writing, the caller updates filename, clearModified and clearFileModified as needed.
- modifyText replaces a selection; getText retrieves a range. Pair atomicUndoBegin and atomicUndoEnd in try/finally to group edits. Nesting and rollback on exceptions are not provided.
- getColumnFromIndex/getIndexFromColumn convert Python character positions and display cells, including supplementary characters, tabs and wide characters. Low-level getStringColumns still uses UTF-16 units; do not use its positions directly as Python string indices. offset in getStringWidth/getStringColumns is the starting cell for tabs; results are relative widths starting at 0. For example, getStringWidth("a\tb", 4, 3) returns 6.
- Plain case=False searches compare uppercased strings and return original Python spans. In ßx, x matches (1, 2); ss or s matches the whole ß at (0, 1). Start/end bounds also use original character positions. Whole-word and regex matching rules remain the same.

### Standalone Widgets

The host manages [Widget controls](@ref widget), including input, painting, focus and lifetime. Prefer the Dialog example for ordinary forms.

| Control | Result and cleanup |
|---|---|
| ButtonWidget | Space/Enter calls handler() synchronously; its return is ignored |
| CheckBoxWidget / ChoiceWidget | getValue returns check value / zero-based choice index |
| HotKeyWidget | getValue returns a two-element integer list `[vk, mod]`; the host registers the OS hotkey |
| ColorWidget | Retrieve RGB; show also toggles both planes. Call the control's destroy to release both |
| TimeWidget | Six integers; initial values and getValue validate the calendar/time and raise ValueError for invalid values. setPosSize moves all fields in a fixed 22 by 1 cell area. Call destroy |
| ProgressBarWidget | Number or per-row progress; None means busy. Input lists/tuples are copied and clamped. One timer runs only while visible and busy; determinate mode, hiding and destroy remove it |

TimeWidget allows zero and temporarily invalid dates during editing. Call getValue() before accepting; on ValueError keep the window open for corrections. Dates are never corrected automatically. Release ColorWidget/TimeWidget through the control's destroy(), without destroying internal resources individually. Widget.enableIme applies the requested value to the parent only while focused; otherwise it stores it for the next focus.

## Inspect windows and prepare input with pyauto

[Native pyauto APIs](@ref pyauto_native) provide Window references to OS windows, RGB Image objects, Input events and Hook monitoring. ckit.Window creates your UI; pyauto.Window refers to an existing HWND and releasing its wrapper does not close the OS window.

Save the following as scripts/my_native.py in the active settings directory. It reports the launcher's own window, a visible-window count and a match in generated pixel data, then prepares input objects. It does not send input to the desktop.

<!-- example: native_module -->
```python
import pyauto


def configure(window):
    def command_Inspect(info):
        target = pyauto.Window.fromHWND(window.getHWND())
        if target is None:
            print("No window")
            return
        print("Title:", target.getText())
        print("Class:", target.getClassName())
        print("Rect:", target.getRect())
        visible = []
        def collect(candidate, result):
            if candidate.isVisible():
                result.append(candidate.getHWND())
            return 1
        pyauto.Window.enum(collect, visible)
        print("Visible windows:", len(visible))
        image = pyauto.Image.fromString("RGB", (2, 1), bytes([255, 0, 0, 0, 255, 0]))
        needle = pyauto.Image.fromString("RGB", (1, 1), bytes([0, 255, 0]))
        print("Pixel match:", image.find(needle))
        events = [pyauto.Key("A"), pyauto.Char("A")]
        print("Prepared events:", len(events))
    window.launcher.command_list.append(("mynative", command_Inspect))
```

Merge these calls into the existing custom.py configure, run reload, and execute mynative:

<!-- example: native_setup -->
```python
def configure(window):
    import my_native
    my_native.configure(window)
```

Title/Class/Rect and the visible-window count depend on the environment. Pixel match is (1, 0); Prepared events is 2. Remove the setup call and run reload to disable it.

### References, input and monitoring

- Window coordinates are pixels. fromHWND(0) and unsuccessful find return None. Holding a wrapper does not extend the OS window's lifetime; a window can disappear after find/enum.
- enum calls callback(window, arg) synchronously. Return C int 1 to continue or 0 to stop, never None. sendMessage waits for the target; arguments/results use C int width and cannot carry 64-bit pointers.
- Key("A") is a virtual key; Char("A") is a UTF-16 character unit. Key does not uppercase a string such as "a". Char does not automatically turn a supplementary character into a surrogate pair.
- Explicit Input.send(events) submits to the OS input stream and affects its current recipient. Construction and submission are separate. Mouse coordinates use virtual-desktop screen pixels, including negative coordinates on displays to the left/above. Out-of-bounds values are clamped on each axis; wheel events do not move the pointer. Prefer existing keymaps and command calls for ordinary application actions.
- Use one owner for Hook per process; do not create overlapping monitoring. Existing application keymaps handle ordinary custom keys. mousemove(x, y) reports screen pixels. destroy() alone releases all monitoring and callback references. See the native Hook section for callback contracts and teardown. Register window.registerConfigCleanup(hook.destroy) after creating a Hook to release it on reload and shutdown.

### IME composition in another process

Window.getImeStatus() only reports whether the IME is open. For a foreign edit control, target.isImeConverting(1000) distinguishes True (a nonempty active uncommitted composition range), False (a supported provider reports no range or an empty range), and None (unsupported). Do not convert TimeoutError or other OSError failures into False. It uses Windows 8.1-or-later UI Automation TextEditPattern and prefers a focused UIA descendant of the supplied HWND, even when the HWND host also reports keyboard focus, including browser edit fields without their own HWND. Only when no focused element is found does it query the HWND itself. Discovery stays in the UIA control view of that window; an unsupported or failed selected element never falls back to a parent's False. It does not query IMM/TSF directly or inject a custom DLL. Same-process targets raise ValueError.

An HTML textarea in Edge has been checked for windowless edit selection and False when idle. Editors without a suitable provider remain unsupported; this does not establish real IME transitions or support for every application/IME.

Save this helper in scripts/my_ime.py and import it with from my_ime import describe_ime in your own worker code. While another application has focus, obtain its edit control with target = pyauto.Window.getFocus() and pass it to describe_ime(target) to get a state string or failure reason. Placement alone starts no registration or monitoring. Remove the call to disable it; run reload after changing the imported module.

<!-- example: ime_query -->
```python
def describe_ime(target):
    if target is None:
        return "No focus"
    try:
        state = target.isImeConverting(250)
    except (OSError, ValueError) as error:
        return f"{type(error).__name__}: {error}"
    if state is None:
        return "Unsupported"
    return "Composing" if state else "Idle"
```

Arguments are positional; the wait limit is 1..60000 milliseconds. If provider cleanup remains after a timeout, subsequent queries raise OSError (winerror=170, busy). Wait for completion, or restart the caller if the provider never returns. Results are snapshots, and some applications commit text when focus moves away. Avoid frequent synchronous queries in UI/hook callbacks. Do not assume support for elevated windows, windowless editors, or every IME. See the [Window contract](@ref pyauto_Window).

## Native drawing and file information

[Native ckit APIs](@ref ckit_native) cover Window, Planes, Font, Image, menus and line data; [clnch_native APIs](@ref clnch_native_api) cover files, shares, Shell and color selection. Prefer Dialog for ordinary forms and TextWindow for text windows.

Save this as scripts/my_planes.py in the active settings directory to draw text and an RGBA image in a custom pixel-sized window.

<!-- example: planes_module -->
```python
import ckit


def configure(window):
    def command_Preview(info):
        enabled = window.isEnabled()
        left, top, _, _ = window.getWindowRect()
        preview = ckit.Window(
            x=left, y=top, width=320, height=88, parent_window=window,
            title="Native preview", show=False, resizable=False,
            bg_color=(24, 24, 24),
            close_handler=lambda: preview.quit(),
            keydown_handler=lambda vk, mod: preview.quit() if vk == ckit.VK_ESCAPE else None)
        try:
            if not preview.getHWND():
                raise RuntimeError("Could not create preview")
            text = ckit.TextPlane(preview, (8, 8), (304, 24), 0.0)
            text.setFont(ckit.getStockedFont("MS Gothic", 16))
            text.putString(0, 0, 30, 1, ckit.Attribute(fg=(240, 240, 240)), "Native planes: Esc to close")
            image = ckit.Image.fromBytes((2, 1), bytes([255, 0, 0, 255, 0, 255, 0, 255]))
            picture = ckit.ImagePlane(preview, (8, 40), (64, 32), 1.0)
            picture.setImage(image)
            window.enable(False)
            preview.show(True)
            preview.messageLoop()
        finally:
            try:
                preview.destroy()
            finally:
                window.enable(enabled)
                if enabled:
                    window.activate()
    window.launcher.command_list.append(("mypreview", command_Preview))
```

Merge these calls into the existing custom.py configure and run reload.

<!-- example: planes_setup -->
```python
def configure(window):
    import my_planes
    my_planes.configure(window)
```

Execute mypreview to display the instruction and a red/green strip. Esc or the close button exits and restores the parent's enabled state. preview.destroy destroys its owned Planes together. An originally disabled parent stays disabled. Remove the setup call and run reload to disable it.

Plane placement/sizes use client pixels; putString uses cells. Call setFont first. Smaller priorities appear in front. setPriority changes overlap order after construction, preserving the existing relative order of equal priorities. getFont/getImage return new wrappers sharing native resources, without Python is-identity guarantees. clear invalidates all Planes, so do not use it on TextWindow. This direct Window example has no TextWidget editing/IME features.

Image.fromBytes reports short buffers, dimension-product overflow and allocation/GDI failures as exceptions. Window destruction also releases its hit-test callback and menu tree. TaskTrayIcon requires explicit destroy; later operations raise ValueError.

Save this as scripts/my_files.py to enumerate a wildcard's metadata on a worker.

<!-- example: files_module -->
```python
import clnch_native


def configure(window):
    def command_Stat(info):
        if len(info.args) != 1 or not info.args[0]:
            print(r"Usage: mystat;C:\folder\*")
            return
        pattern = info.args[0]
        items = window.subThreadCall(lambda: clnch_native.findFile(pattern, use_cache=False), (), raise_error=True)
        print("Entries:", len(items))
        for name, size, stamp, attributes in sorted(items):
            print(name, size, stamp, hex(attributes))
    window.launcher.command_list.append(("mystat", command_Stat))
```

Merge these calls into the existing custom.py configure and run reload.

<!-- example: files_setup -->
```python
def configure(window):
    import my_files
    my_files.configure(window)
```

Execute `mystat;C:\folder\*` with an existing directory. The console shows the count and each name, byte size, local last-write tuple and attribute bits. No matches prints Entries: 0; OS errors such as a missing parent are reported to the console. No files are changed. use_cache=False avoids stale cached metadata. The example does not connect or authenticate. Remove the setup call and run reload to disable it.

setFileTime(path, (2024, 2, 29, 12, 34, 56)) sets the last-write time using local time. Invalid dates raise ValueError before file changes; OS failures raise OSError. Read-only attributes are temporarily cleared and restored. Read the exception notes because cleanup can fail after the timestamp was updated; the timestamp is not rolled back. Shell menu/drag None returns do not distinguish success from cancellation. Apply chooseColor's color only when the returned result is nonzero. See the API pages above for these limits, cleanup and arguments.

For byte-oriented line access to large files, use from ckit.ckit_hugefile import HugeTextFile and pass an open binary file to HugeTextFile(fd.fileno(), encoding, offset). offset is the starting byte position, for example after a BOM; getLine uses zero-based line numbers. UTF-16LE/BE CR, LF and CRLF are detected only at two-byte boundaries relative to offset; similar byte sequences inside characters are not line breaks. Returned bytes include the newline, with an empty final line after a trailing newline. Positions are scanned and cached in 64 KiB blocks up to the requested line, without copying the entire file to bytes. Call reader.close() to release the mmap before closing fd yourself. See the [HugeTextFile API](@ref misc).

## Display a status message and manage resources

Call window.setStatusMessage("Saved", timeout=2000) on the UI thread to display a message for 2000 milliseconds; error=True selects the error color. timeout=None keeps the message until replacement or clearStatusMessage(). Replacing a message cancels its previous expiry timer.

For a custom idle status display, registerStatusBar(func, priority=-1, interval=None) takes a callback func(width) returning text. width is in display cells; interval is in milliseconds. Smaller priorities take precedence. Keep the function short. unregisterStatusBar(func) removes that exact registered callback and its timer. Register resource cleanup with registerConfigCleanup(func) to run it on the UI thread after the next successful load, before replacement, and on application shutdown. Callbacks take no arguments, their return values are ignored, and they run in reverse registration order. Repeated registration of the same callable object is ignored.

This standalone example can be added to custom.py. Merge the body into an existing configure and run reload. Leaving input shows Reload safe; removing the call and running reload removes the display and its timer.

<!-- example: reload_cleanup -->
```python
def configure(window):
    def status(width):
        return "Reload safe"

    window.registerConfigCleanup(lambda: window.unregisterStatusBar(status))
    window.registerStatusBar(status, interval=1000)
```

For acquired windows, register window.registerConfigCleanup(child.destroy); for Hooks, window.registerConfigCleanup(hook.destroy); for custom timers, window.registerConfigCleanup(lambda: window.killTimer(tick)). Capture the old resource in a closure or bound method instead of looking it up through new module definitions. Make cleanup retryable. Remaining callbacks run after a failure; successful callbacks are removed and only failures are retried. A cleanup failure on reload defers new custom application and removes old custom keys, commands, associations, input providers and list hooks, falling back to standard features and validated JSON. Already released resources are not recreated. Old modules and failed cleanup callbacks remain available for retry; after fixing the source or waiting for jobs to finish, reload retries cleanup and applies custom settings. Shutdown reports cleanup failures and continues destroying the application.

This fallback does not stop or update directly registered timers, Hooks, running jobs or external references to old functions outside the registrations rebuilt by the application. A timer whose cleanup failed before stopping it can still reference a window destroyed by another cleanup. Owners must stop dependent callbacks first and keep resources used by jobs alive until those jobs finish. If one cleanup partly succeeds before raising, make its retry avoid releasing the same resource twice. Restart if callbacks cannot be stopped or references recovered.

Use the application's existing JobQueue and SyncCall rather than starting unmanaged queues or timers. Custom timers, background threads, native windows and hooks need their own release/stop path. A configure failure does not roll back everything already changed by that function.

SystemExit and KeyboardInterrupt from custom loading, hooks and registered cleanup are also reported as errors while the application continues. Undefined hooks are valid. If initial custom.py loading or hook validation fails, startup uses standard keys, built-in commands and validated JSON without applying custom settings. Open the console with Ctrl+F10 to read the traceback, fix custom.py or its imported source in the active settings location, and enter reload in the main input. If configure() has already started when it fails, partial changes remain even at initial startup. Failures suppress the Reload success notification.

## Reflect changes, disable a feature, and diagnose problems

reload first reads commands.json and validates its syntax, schema and names before loading custom.py or releasing old resources. A JSON read or validation failure reports an error, preserves existing commands, aliases, keys, custom settings and registered resources, and suppresses the success notification. Fix the file and reload to apply the validated snapshot. A missing file means empty registrations: existing JSON entries are removed and standard/custom settings are reapplied. Other I/O errors, including access denial, are reported as failures. Standard/custom application failures also suppress the success notification, but partial application is not rolled back.

| Change | How to apply it |
|---|---|
| custom.py itself | Run reload; the file is evaluated in a fresh namespace |
| Python sources and dependencies selected by ordinary or supported dynamic imports in scripts/ or extensions/ | Run reload; read them into fresh namespaces |
| Remove these examples' command/key setup calls from custom.py | Run reload; the standard command list and keymaps are rebuilt |
| Remove a resource-creating setup call | Register its cleanup with registerConfigCleanup, then reload; release unregistered resources explicitly |
| Edit reclnch.ini directly | Exit, edit, and restart; reload does not reread this file |

Keep setup calls inside the hooks. The order of calls is the application order. Module placement alone does not enable the supplied extensions. Avoid module names such as ckit, clnch or the names of supplied extensions: the core/standard library search paths precede extensions/, which precedes the active scripts/.

The scope is Python sources (.py), regular and namespace packages, and dependencies within the active settings location's scripts/ and the application's extensions/. Tracking covers ordinary import/from-import statements in custom.py and selected sources, plus importlib.import_module calls at the top level, in configure/configure_ListWindow and in selected sources called by them. It also supports from importlib import import_module (including aliases) in these sources, and relative imports with a package name.

The next reload removes the old generation's cache; imports determine loading order. Cycles follow Python's normal rules: from-import of a definition that has not yet initialized still fails. Deleted definitions and from-import references are replaced in the new generation, and source is read even for edits with identical timestamps and sizes. Standard-library, product and unselected modules are preserved. There is no automatic discovery or file monitoring. C extensions, modules outside these locations, original import_module functions supplied by external libraries, and custom loaders are outside this scope. Arbitrary background work and all deferred imports after hooks return are not guaranteed.

To check module syntax/loading while keeping old registrations, put import my_module at the top level of custom.py and call my_module.configure(window) inside configure. When reloading a valid configuration, failure of top-level syntax/loading or configure/configure_ListWindow callable validation preserves the old namespace, selected modules, registrations and resources. Imports inside hooks load when those hooks run, so their failures are application-stage failures. Modules first imported by configure_ListWindow load when the next list opens.

After application starts, failures leave partial settings and registered cleanup in place. Fix the source and reload to clean up and reapply. External references to old functions, running jobs and already open lists are not rewritten. For jobs, request cancellation and retry after completion as shown above; close and reopen lists. Do not acquire windows or start threads at import time; acquire and register cleanup inside configure. Arbitrary Python side effects cannot be completely rolled back. Restart when unregistered resources cannot be recovered or modules outside the reload scope change.

Open the console with Ctrl+F10 to read print output and tracebacks. Check the active settings directory, spelling of the registered name, same-name standard/JSON entries, and whether failure occurred during loading, cleanup or application; fix it and run reload. Same-name JSON precedence, preservation of custom registrations after JSON editing, and using in-memory INI values are unchanged.

The code in the examples uses ASCII messages so the same code works in both help languages. Customize those messages after confirming the example. Integrate new calls into existing hooks rather than copying another def configure over them.

## API reference

- [Main window and input](@ref mainwindow): MainWindow, commandLine, ShellExecuteCommand, UrlCommand, status and worker calls.
- [Commands](@ref command): CommandInfo, CommandMap and CommandSequence.
- [List windows](@ref listwindow): ListWindow and popMenu.
- [Thread utilities](@ref threadutil): JobItem, JobQueue and SyncCall.
- [Subprocesses](@ref subprocess): SubProcess.
- [Widgets and forms](@ref widget): TextWindow, Widget controls, EditWidget and Dialog.
- [Multiline editing](@ref textwidget): TextWidget, Document, Point, Selection, Mode, Lexer, Completion and Search.
- [pyauto input helpers](@ref pyautoinput) and [native contracts](@ref pyauto_native): Window, Image, Input, Hook and Shell.
- [Native ckit APIs](@ref ckit_native) and [clnch_native APIs](@ref clnch_native_api): low-level drawing, menus, lines, files and Shell.
- <a href="topics.html">All API topics</a>.
