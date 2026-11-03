import clnch_strings as strings

clnch_appname = "ReCraftLaunch"
clnch_dirname = "ReCraftLaunch"
clnch_version = "1.0.0"
clnch_window_class_prefix = "ReClnch"
clnch_window_class = clnch_window_class_prefix + "WindowClass"


def startupString():
    return strings.STARTUP.format(
        app=clnch_appname,
        version=clnch_version,
        project_url="https://github.com/p65536/ReCraftLaunch",
        releases_url="https://github.com/p65536/ReCraftLaunch/releases",
        origin="CraftLaunch 3.40",
        author="craftware",
        source_url="https://github.com/crftwr/clnch",
        url="https://sites.google.com/site/craftware/",
    )
