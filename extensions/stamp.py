def configure(window):
    import datetime

    from ckit import setClipboardText

    def command_Stamp(info):
        setClipboardText(datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S"))

    window.launcher.command_list += [("stamp", command_Stamp)]
