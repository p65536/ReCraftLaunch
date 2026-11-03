# Operation Reference

Look up keyboard and mouse operations by screen, or find a built-in command by name.
For first use, feature explanations, and configuration procedures, open the User Manual with F1.
These are the standard bindings. Overrides in `custom.py` take priority.

- [Main input field](#main-input-field)
- [Built-in commands](#built-in-commands)
- [Command List](#command-list)
- [Command editor](#command-editor)
- [Configuration menus and input dialogs](#configuration-menus-and-input-dialogs)
- [History list](#history-list)
- [Console](#console)
- [Confirmation and error dialogs](#confirmation-and-error-dialogs)

Main input uses `name;arg1 arg2`, or `name;"argument 1" arg2` for spaces. Only the first `;` separates the name; later semicolons, quotes, spaces and backslashes are preserved. Direct URLs remain whole.

## Main input field

| Operation | Keys / input | Notes |
|---|---|---|
| Execute | Enter | Windows argument text after the first semicolon is passed unchanged |
| Execute modifier action | Ctrl+Enter / Shift+Enter / Ctrl+Shift+Enter | Uses the registered action, or the modifier default |
| Close candidates / clear input / close console / deactivate | Esc | Close visible candidates first, then clear nonempty input, close a visible console, or deactivate |
| Complete the common prefix | Tab by default | Requires auto-completion on and available candidates; config > Input options can change this to clearing input |
| Insert a space | Space by default | Can be changed to completion; candidate navigation requires auto-completion on and available candidates |
| Edit a registered command / open Command List | Ctrl+E | Edit when a name is entered; list when empty |
| Create a command | Run `new` | See [Command editor](#command-editor) |
| Open the config menu | Ctrl+S | Preserves input text and history |
| Toggle console | Ctrl+F10 | Opening it moves focus to the console |
| Open local help | F1 | Preserves input and selection; missing help produces restoration guidance |
| Copy registered Link string | F12 | Normal JSON action, following aliases to the terminal Link; no OS search, absolute-path conversion or existence check; ends input and deactivates regardless of outcome; no history added |
| Pass input elsewhere / show properties | Alt+Enter / Ctrl+Alt+Enter / Shift+Alt+Enter / Ctrl+Shift+Alt+Enter | config > Alt+Enter action; four independent keys, separate from registered command Modifiers; properties options belong to plain Alt+Enter only; all disabled by default, preserving input, selection and focus; enabled actions end input; never adds history; leaves focus changes to the target application |
| Remove the current candidate from history | Ctrl+K | When history is enabled |
| Open a file or folder context menu | Ctrl+\ (106-key layout) / Ctrl+/ (101-key layout) | Existing path before the first `;`, optionally enclosed in one quote pair; missing target, empty input, or name alone preserves input, selection, and history |
| Register a command from a target file | Drop a file onto the main window | Review in the editor before saving |
| Activate the main window | Key configured under config > Hotkey options | Choose Activate or Toggle in the same submenu |

## Built-in commands

Names are registered in lowercase. Input and execution are case-insensitive.

| Input | Action |
|---|---|
| `config` | Open the application configuration menu |
| `reload` | Reapply standard features, JSON commands, and `custom.py`; does not reread the INI file from disk |
| `history` | Open command history; accumulation and persistence follow the input options |
| `about` | Print the product name, version, repository, download location, and original CraftLaunch information to the console |
| `quit` | Exit ReCraftLaunch |
| `new` | Open the editor for a new command |
| `_ra;<target> arguments…` | Run a registered target, EXE, or supported document association as administrator; see "Run as Administrator" in the User Manual for limits |

## Command List

| Operation | Keys / mouse | Notes |
|---|---|---|
| Move selection | Up / Down, PageUp / PageDown, Home / End | Home / End do not accept |
| Select the next matching initial | Character key | Cycles by one character, including plain F |
| Edit selection | Enter / Ctrl+E | Name is fixed when editing the empty command |
| Create | Insert | All modifiers start empty |
| Duplicate selection | Ctrl+Insert | Saves without confirmation and selects the duplicate; an unregistered empty row does nothing |
| Confirm deletion | Delete | The empty command cannot be deleted |
| Start substring search | Ctrl+F | Case-insensitive |
| Extend query / remove last character | Typing / Backspace | While searching; symbols are literal |
| End search only | Enter / Esc | Restores all rows and keeps selection; press Enter again to edit |
| Open a new registration | Drop a file | Disabled while searching; dropping does not save |
| Close list | Esc / close the window | Does not accept a selection. During search, Esc exits search first |

Editing, creating, duplicating, deleting, and dropping are disabled while searching.

If deletion or duplication is saved but applying the commands fails, the message confirms that the file was saved. Use reload to apply it again instead of repeating the deletion or duplication.

## Command editor

While the editor is open, the main window or Command List that opened it remains visible and does not accept input. Saving or pressing Esc returns to that window. Editing, creating, or dropping a command from Command List returns to the list; pressing Esc in the list returns to the main window.
Editors opened from Command List appear to its right, with the tops of the title bars aligned. Editors opened directly from the main window continue to prefer a position below it. Near screen edges, the position is adjusted to fit the work area.

Name cannot contain semicolons (`;`) or whitespace characters, including Unicode whitespace. New-drop suggestions remove these characters; manually entered text is kept and checked when saving.
Named commands can be saved with zero launch actions. GUI saving of the empty command requires at least one Link.

| Operation | Keys / mouse |
|---|---|
| Next / previous field| Tab / Shift+Tab; selects all text in destination input |
| Next / previous choice | Right / Left, Space / Shift+Space; wraps at the ends |
| Direct choice | Click |
| Select Modifier | Alt+E: None; Alt+C: Ctrl; Alt+S: Shift; Alt+X: Ctrl+Shift |
| Select ViewMode | Alt+1: Normal; Alt+2: Minimized; Alt+3: Maximized |
| Focus a field | Alt+N/L/A/W/V/M |
| Save / cancel | Enter / Esc from any field |

| Drop destination | Action |
|---|---|
| Name / Link / Args / WorkDir | Fill that field; the empty command's Name cannot be changed |
| Outside input fields | Fill Link |

## Configuration menus and input dialogs

| Screen | Operation | Keys / mouse |
|---|---|---|
| Menus and lists | Move selection | Up / Down, PageUp / PageDown, Home / End |
| Menus | Accept / return | Enter / Esc; closing the window also cancels |
| Language | Select Japanese / English (applied after restart) | Enter to save, Esc to cancel |
| Input dialogs | Next / previous field | Tab / Shift+Tab |
| Input dialogs | Accept / cancel | Enter / Esc |
| Source-folder list | Edit / add / remove | Enter / Insert / Delete |
| Source-folder list | Reorder | Ctrl+Up / Ctrl+Down |
| Source-folder list | Save / discard changes | Save and Return / Cancel or Esc |
| Input dialogs or editors taller than the work area | Scroll | Wheel / PageUp / PageDown |

## History list

| Operation | Keys |
|---|---|
| Move selection | Up / Down, PageUp / PageDown, Home / End |
| Start search | F |
| Delete selected history | Delete |
| Accept / return | Enter / Esc |

## Console

| Operation | Keys / mouse |
|---|---|
| Toggle | Ctrl+F10; opening moves focus to the console |
| Close and return to main | Esc / Ctrl+F10 / close button |
| Scroll one line / page | Up / Down; PageUp / PageDown or Left / Right; wheel also works |
| Select a range and copy | Drag and release |
| Select a word and copy | Double-click and release |
| Select all retained text | Ctrl+A; does not copy by itself |
| Copy selection | Ctrl+C |
| Select and copy all retained text | Triple-click the body and release |
| Open help | F1 |

LF and CRLF logical line breaks are copied as CRLF. Standalone CR characters are preserved; display wrapping adds no copied line breaks.

## Confirmation and error dialogs

| Operation | Keys / mouse |
|---|---|
| Scroll long text | Up / Down, PageUp / PageDown, Home / End, wheel |
| Activate a button | Click / Enter |
| Close / cancel | Esc |
