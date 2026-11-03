def configure(window):
    import os

    from clnch_misc import checkNetConnection

    def command_NetDrive(info):
        if len(info.args) not in (1, 2):
            print("Map a drive   : NetDrive;<drive letter> <path>")
            print("Unmap a drive : NetDrive;<drive letter>")
            return
        drive_letter = info.args[0]
        if len(info.args) == 2:
            path = info.args[1]
            checkNetConnection(path)
            args = ["net", "use", drive_letter + ":", os.path.normpath(path), "/yes"]
        else:
            args = ["net", "use", drive_letter + ":", "/D"]
        if window.subProcessCall(args, cwd=None, env=None, enable_cancel=False) == 0:
            if len(info.args) == 2:
                print(f"Mapped drive {drive_letter}: to {path}.")
            else:
                print(f"Drive {drive_letter}: has been unmapped.")

    window.launcher.command_list += [("NetDrive", command_NetDrive)]
