"""Static popMenu return contracts; run with Pyright, not Python."""
from typing import assert_type

from clnch_listwindow import _split_list_result, popMenu

from ckit import TextWindow


def check_return_types(window: TextWindow, flag: bool) -> None:
    assert_type(popMenu(window), int)
    assert_type(popMenu(window, return_modkey=False), int)
    assert_type(popMenu(window, return_modkey=True), tuple[int, int])
    assert_type(popMenu(window, 40, 16, "menu", [], 0, True, False, False), int)
    assert_type(popMenu(window, 40, 16, "menu", [], 0, True, False, True), tuple[int, int])
    assert_type(popMenu(window, return_modkey=flag), int | tuple[int, int])
    assert_type(popMenu(window, 40, 16, "menu", [], 0, True, False, flag), int | tuple[int, int])
    assert_type(popMenu(window, 40, 16, "menu", [], 0, True, False, True, None, None, 5), tuple[int, int])

    captured = _split_list_result(popMenu(window, return_modkey=flag))
    assert_type(captured, tuple[int, int | None])
    assert_type(captured[0], int)
    assert_type(captured[1], int | None)
