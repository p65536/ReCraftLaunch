# -*- coding: utf_8 -*-

import os
import sys

# Initialize the module search path before importing local packages.
sys.path[0:0] = [
    os.path.abspath(os.path.join(os.path.split(sys.argv[0])[0], "../../..")),
]

import pyauto

print(pyauto.Window.getMonitorInfo())
