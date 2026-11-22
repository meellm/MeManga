"""Widgets of the Settings page tabs (issue #299).

``SettingsPage`` (memanga/gui/pages/settings.py) composes one mixin per
tab::

    GeneralTabMixin     general.py       appearance, delivery, naming
    EmailTabMixin       kindle_email.py  Kindle / SMTP account
    AdvancedTabMixin    advanced.py      reader, network, scheduling, tools
    AboutTabMixin       about.py         version and environment rows
    SettingsFormMixin   common.py        section headings, labeled entries

A tab mixin builds its widgets onto the page and keeps them in sync. The
page owns what the widgets trigger: saving and loading config, email
tests, scheduled checks, import/export and diagnostics. The mixins are
plain classes, not QObjects, so the page keeps its Qt class name, slots
and style selectors.
"""

from .about import AboutTabMixin
from .advanced import SCHEDULING_UNAVAILABLE_TEXT, AdvancedTabMixin
from .common import SettingsFormMixin
from .general import GeneralTabMixin
from .kindle_email import EmailTabMixin

__all__ = [
    "SCHEDULING_UNAVAILABLE_TEXT",
    "AboutTabMixin",
    "AdvancedTabMixin",
    "EmailTabMixin",
    "GeneralTabMixin",
    "SettingsFormMixin",
]
