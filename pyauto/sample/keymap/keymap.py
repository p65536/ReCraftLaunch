# -*- coding: utf_8 -*-

import os
import sys

# Initialize the module search path before importing local packages.
sys.path[0:0] = [
    os.path.abspath(os.path.join(os.path.split(sys.argv[0])[0], "../../..")),
]

# Preserve the public API exported by these modules.
from keymap_hook import *  # noqa: I001  # Preserve public re-export and initialization order.
from keymap_config import (
    loadConfigFile as loadConfigFile,  # noqa: PLC0414  # Explicit public re-export.
    user_namespace as user_namespace,  # noqa: PLC0414  # Explicit public re-export.
)

if __name__ == "__main__":
    import pyauto

    loadConfigFile()

    print("-- keymap start --")

    pyauto.messageLoop()

    print("-- keymap end --")
