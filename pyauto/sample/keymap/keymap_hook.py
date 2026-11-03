# -*- coding: utf_8 -*-

import re

import pyauto

MODKEY_ALT = 0x00000001
MODKEY_CTRL = 0x00000002
MODKEY_SHIFT = 0x00000004
MODKEY_WIN = 0x00000008
MODKEY_USER0 = 0x00000010
MODKEY_USER1 = 0x00000020
MODKEY_USER2 = 0x00000040
MODKEY_USER3 = 0x00000080

MODKEY_ALT_L = MODKEY_ALT | 0x00000100
MODKEY_CTRL_L = MODKEY_CTRL | 0x00000200
MODKEY_SHIFT_L = MODKEY_SHIFT | 0x00000400
MODKEY_WIN_L = MODKEY_WIN | 0x00000800
MODKEY_USER0_L = MODKEY_USER0 | 0x00001000
MODKEY_USER1_L = MODKEY_USER1 | 0x00002000
MODKEY_USER2_L = MODKEY_USER2 | 0x00004000
MODKEY_USER3_L = MODKEY_USER3 | 0x00008000

MODKEY_ALT_R = MODKEY_ALT | 0x00010000
MODKEY_CTRL_R = MODKEY_CTRL | 0x00020000
MODKEY_SHIFT_R = MODKEY_SHIFT | 0x00040000
MODKEY_WIN_R = MODKEY_WIN | 0x00080000
MODKEY_USER0_R = MODKEY_USER0 | 0x00100000
MODKEY_USER1_R = MODKEY_USER1 | 0x00200000
MODKEY_USER2_R = MODKEY_USER2 | 0x00400000
MODKEY_USER3_R = MODKEY_USER3 | 0x00800000


_keymap_list = []
_current_keymap = None
_modifier = 0
_vk_mod_map = {}


def checkModifier(mod1, mod2):
    _mod1 = mod1 & 0xFF
    _mod2 = mod2 & 0xFF
    _mod1_L = (mod1 & 0xFF00) >> 8
    _mod2_L = (mod2 & 0xFF00) >> 8
    _mod1_R = (mod1 & 0xFF0000) >> 16
    _mod2_R = (mod2 & 0xFF0000) >> 16
    if _mod1 != _mod2:
        return False
    if _mod1_L & _mod2_R:
        return False
    return not (_mod1_R & _mod2_L)


def createKeySequence_ModifierDown(mod):
    seq = []
    for vk_mod in _vk_mod_map.items():
        if checkModifier(vk_mod[1], mod):
            seq.append(pyauto.KeyDown(vk_mod[0]))
    return seq


def createKeySequence_ModifierUp(mod):
    seq = []
    for vk_mod in _vk_mod_map.items():
        if checkModifier(vk_mod[1], mod):
            seq.append(pyauto.KeyUp(vk_mod[0]))
    return seq


class KeyStroke:
    def __init__(self, vk, mod=0, prefix=None):
        if type(vk) is str and len(vk) == 1:
            vk = ord(vk)
        self.vk = vk
        self.mod = mod
        self.prefix = prefix

    def __hash__(self):
        return self.vk

    def __eq__(self, other):
        if self.vk != other.vk:
            return False
        if self.prefix != other.prefix:
            return False
        return checkModifier(self.mod, other.mod)


K = KeyStroke


class Keymap:
    def __init__(self, hwnd):
        # print "Keymap.__init__"
        self.keydown_table = {}
        self.keyup_table = {}
        self.prefix = None

    def onKeyDown(self, vk, mod):
        key = KeyStroke(vk, mod, self.prefix)
        if key in self.keydown_table:
            handler = self.keydown_table[key]
            if type(handler) is list or type(handler) is tuple:
                key_seq = (
                    createKeySequence_ModifierUp(_modifier)
                    + (list(handler) if isinstance(handler, tuple) else handler)
                    + createKeySequence_ModifierDown(_modifier)
                )
                pyauto.Input.send(key_seq)
            elif callable(handler):
                handler()
            else:
                raise TypeError
            return True
        return False

    def onKeyUp(self, vk, mod):
        key = KeyStroke(vk, mod, self.prefix)
        if key in self.keyup_table:
            handler = self.keyup_table[key]
            if type(handler) is list or type(handler) is tuple:
                key_seq = (
                    createKeySequence_ModifierUp(_modifier)
                    + (list(handler) if isinstance(handler, tuple) else handler)
                    + createKeySequence_ModifierDown(_modifier)
                )
                pyauto.Input.send(key_seq)
            elif callable(handler):
                handler()
            else:
                raise TypeError
            return True
        return False

    def registerKeyDownHandler(self, keystroke, handler):
        self.keydown_table[keystroke] = handler

    def registerKeyUpHandler(self, keystroke, handler):
        self.keyup_table[keystroke] = handler

    def setPrefix(self, prefix):
        self.prefix = prefix

    def resetPrefix(self):
        self.prefix = None


def defineModifier(vk, mod):
    _vk_mod_map[vk] = mod


def registorKeymap(condition, constructor):
    _condition: list[re.Pattern[str] | None] = [None, None, None]

    if condition[0] is not None:
        _condition[0] = re.compile(condition[0])
    if condition[1] is not None:
        _condition[1] = re.compile(condition[1])
    if condition[2] is not None:
        _condition[2] = re.compile(condition[2])

    _keymap_list.insert(0, (tuple(_condition), constructor))


def quitKeymap():
    global _hook
    # print "quitKeymap"
    del _hook


def _onKeyDown(vk, scan):
    global _modifier

    try:
        # print "onKeyDown : ", vk

        if vk in _vk_mod_map:
            _modifier |= _vk_mod_map[vk]

        if _current_keymap:
            return _current_keymap.onKeyDown(vk, _modifier)
        else:
            return False
    except Exception as e:  # noqa: BLE001  # Release the hook after arbitrary keymap callback failures.
        print(e)
        quitKeymap()


def _onKeyUp(vk, scan):
    global _modifier

    try:
        # print "onKeyUp : ", vk

        if vk in _vk_mod_map:
            _modifier &= ~_vk_mod_map[vk]

        if _current_keymap:
            return _current_keymap.onKeyUp(vk, _modifier)
        else:
            return False
    except Exception as e:  # noqa: BLE001  # Release the hook after arbitrary keymap callback failures.
        print(e)
        quitKeymap()


_hook = pyauto.Hook()

_hook.keydown = _onKeyDown
_hook.keyup = _onKeyUp

defineModifier(pyauto.VK_LSHIFT, MODKEY_SHIFT_L)
defineModifier(pyauto.VK_RSHIFT, MODKEY_SHIFT_R)
defineModifier(pyauto.VK_LCONTROL, MODKEY_CTRL_L)
defineModifier(pyauto.VK_RCONTROL, MODKEY_CTRL_R)
defineModifier(pyauto.VK_LMENU, MODKEY_ALT_L)
defineModifier(pyauto.VK_RMENU, MODKEY_ALT_R)
defineModifier(pyauto.VK_LWIN, MODKEY_WIN_L)
defineModifier(pyauto.VK_RWIN, MODKEY_WIN_R)
