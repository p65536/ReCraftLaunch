ReCraftLaunch
Keyboard launcher for Windows

ReCraftLaunch is a derivative of CraftLaunch 3.40 by craftware.
It is developed independently by p65536; craftware is not involved in the development of ReCraftLaunch.
See docs/en/differences.html for changes from the original project.

System requirements
- Windows x64
- Python 3.15 is bundled; no separate installation is needed.
- Microsoft Visual C++ v14 Redistributable (x64)
  Install the latest version if needed.

Installation
1. Download the latest ReCraftLaunch_<version>.zip from https://github.com/p65536/ReCraftLaunch/releases.
2. Extract the ZIP to any folder and run reclnch.exe.
Settings are stored in the settings/ folder in the installation folder by default.
You can select %APPDATA%\ReCraftLaunch in config > Settings location; the change takes effect after restarting the application and does not copy or move existing settings.

Language settings
Japanese and English UI and help are included.
The default language is English. To switch to Japanese:
1. Open the configuration menu (type config in the main input field and press Enter, or press Ctrl+S in the main input field).
2. Open Language, select Japanese, and press Enter.
3. Restart ReCraftLaunch.
   1. Exit ReCraftLaunch: type quit in the main input field and press Enter.
   2. Start ReCraftLaunch: run reclnch.exe.

Updating
1. Download the latest ReCraftLaunch_<version>.zip from https://github.com/p65536/ReCraftLaunch/releases.
2. Overwrite the installation folder with the extracted files. Your personal settings are not overwritten.

Uninstallation
1. Exit ReCraftLaunch and delete the extracted folder. This also deletes settings stored inside that folder.
2. If you store settings in the AppData folder, delete %APPDATA%\ReCraftLaunch.
3. Remove any shortcuts or startup entries you created.
ReCraftLaunch does not modify the Windows registry, so no registry cleanup is required.

Further information
For usage and settings,
open docs/en/index.html.
You can also press F1 in the application to open help.

Licenses
See LICENSE.md and licenses/.
