# -*- coding: utf_8 -*-

user_namespace = {}


def loadConfigFile():
    filepath = "config.py"

    try:
        print("-- keymap config --")
        with open(filepath, "r", encoding="utf-8") as fd:
            fileimage = fd.read()
    except OSError:
        print("ERROR : no config file.")
        return

    try:
        code = compile(fileimage, filepath, "exec")
        exec(code, user_namespace, user_namespace)  # noqa: S102  # Load the selected Python configuration.
    except SyntaxError as e:
        print(e)
