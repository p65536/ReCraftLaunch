# -*- coding: utf_8 -*-

import os
import sys

# Initialize the module search path before importing local packages.
sys.path[0:0] = [
    os.path.abspath(os.path.join(os.path.split(sys.argv[0])[0], "../../..")),
]

import pyauto


def dump(wnd, indent):
    if not wnd:
        return

    if wnd.isVisible() and not wnd.isMinimized():

        def Window_getProcessName(wnd):
            try:
                return wnd.getProcessName()
            except Exception:  # noqa: BLE001  # Keep dumping other windows when process inspection fails.
                return "(error)"

        print(
            f"{' ' * indent}{Window_getProcessName(wnd)}:{wnd.getText()}:"
            f"{wnd.getClassName()}{wnd.getRect()!s}"
        )

        child = wnd.getFirstChild()

        while child:
            dump(child, indent + 4)

            child = child.getNext()


root = pyauto.Window.getDesktop()

dump(root, 0)
