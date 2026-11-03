"""UI wording facade; initialize once after reading the startup INI."""

from clnch_strings_ja import *

_language = "ja"


def initialize(language="en"):
    """Select startup wording without changing either definition module."""
    global _language
    if language == "ja":
        import clnch_strings_ja as definitions
    else:
        import clnch_strings_en as definitions
    globals().update((name, value) for name, value in vars(definitions).items() if name.isupper())
    _language = "ja" if language == "ja" else "en"


def get_language():
    return _language
