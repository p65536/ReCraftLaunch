# ReCraftLaunch Release Notes {#release_notes}

## 1.0.1 - 2026-11-18

- **Additions**
  - Added ReCraftLaunch release history to the offline Japanese and English manuals.
- **Improvements**
  - Improved warnings when saving commands. If the editor rejects a `Link` as relative, the warning shows the command name, the modifier combination, the entered `Link`, and possible causes. Closing the warning focuses the affected `Link` field and keeps your unsaved edits.
  - Added details to command launch failure logs. The console shows the command name, the modifier combination used, the expanded `Link`, and the working directory (`WorkDir`). For an alias, the log shows the command name and modifier combination you invoked.
- **Fixes**
  - Fixed horizontal scrolling in the command editor. When the editor opens, unfocused fields show the start of long values. Switching modifiers or dropping files resets the scroll position in fields whose values were replaced. The editor selects all text and scrolls long values to the end in the initially focused field and in fields reached with Tab or an access key, matching standard Win32 dialogs.

## 1.0.0 - 2026-11-03

- Initial release.
