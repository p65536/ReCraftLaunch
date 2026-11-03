import ckit

# --------------------------------------------------------------------


class StatusBarLayer:
    def __init__(self, priority):
        self.priority = priority

    def paint(self, window, x, y, width, height):
        attr = ckit.Attribute(fg=ckit.getColor("bar_fg"))
        window.putString(x, y, width, height, attr, " " * width)


class SimpleStatusBarLayer(StatusBarLayer):
    def __init__(self, priority=-1, message="", align=ckit.ALIGN_LEFT):
        StatusBarLayer.__init__(self, priority)
        self.message = message
        self.align = align
        self.error = False

    def setMessage(self, message, error=False):
        self.message = message
        self.error = error

    def paint(self, window, x, y, width, height):
        if self.align == ckit.ALIGN_RIGHT:
            s = ckit.adjustStringWidth(window, self.message, width - 2, align=ckit.ALIGN_RIGHT) + "  "
        else:
            s = " %s" % (self.message)  # noqa: UP031  # Preserve percent-s conversion for public values.
            s = ckit.adjustStringWidth(window, s, width - 1)
        if self.error:
            attr = ckit.Attribute(fg=ckit.getColor("bar_error_fg"))
        else:
            attr = ckit.Attribute(fg=ckit.getHintColor())
        window.putString(x, y, width, height, attr, s)


class _CustomStatusBarLayer(StatusBarLayer):
    """Own the custom callback's drawing and timer, without importing MainWindow."""

    def __init__(self, window, func, priority, interval, paint_flag):
        super().__init__(priority)
        self.window = window
        self.func = func
        self.interval = interval
        self.paint_flag = paint_flag
        if interval:
            window.setTimer(self.onTimer, interval)

    def destroy(self):
        if self.interval:
            self.window.killTimer(self.onTimer)

    def paint(self, window, x, y, width, height):
        s = " %s" % (self.func(width))  # noqa: UP031  # Preserve percent-s conversion for public values.
        s = ckit.adjustStringWidth(window, s, width - 1)
        attr = ckit.Attribute(fg=ckit.getColor("bar_fg"))
        window.putString(x, y, width, height, attr, s)

    def onTimer(self):
        if self.window.commandline_edit is None and self.window.status_bar.isActiveLayer(self):
            self.window.paint(self.paint_flag)


class StatusBar:
    def __init__(self):
        self.layer_list = []

    def registerLayer(self, layer):
        self.layer_list.append(layer)
        self.layer_list.sort(key=lambda layer: layer.priority)

    def unregisterLayer(self, layer):
        self.layer_list.remove(layer)

    def isActiveLayer(self, layer):
        if len(self.layer_list) > 0:
            active_layer = self.layer_list[0]
        else:
            active_layer = None
        return layer == active_layer

    def paint(self, window, x, y, width, height):
        if len(self.layer_list) > 0:
            self.layer_list[0].paint(window, x, y, width, height)
        else:
            attr = ckit.Attribute(fg=ckit.getColor("bar_fg"))
            window.putString(x, y, width, height, attr, " " * width)
