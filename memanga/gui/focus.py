"""
Keyboard focus helpers for the desktop app (issue #396).

Qt style sheets have no :focus-visible. On Windows and Linux a clicked
button takes focus, so a plain ``:focus`` ring would stay on every button
after a click. ``install_focus_marker`` tags each button that gains focus
with a ``focusVisible`` property instead, decided the way browsers decide
:focus-visible: by the user's last input. After a key press (Tab, Enter on
a card, a shortcut) focus is "true", wherever it lands and whoever moves
it; after a mouse press or touch it is "false"; before any input (at
launch) it is "false". The theme style sheet draws the ring only for
"true".
"""

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QAbstractButton, QApplication, QScrollArea, QWidget

_INSTALLED = "memangaFocusMarker"


def _set_focus_visible(widget: QWidget, value: str) -> None:
    """Store ``focusVisible`` and re-polish so the style sheet picks it up."""
    if widget.property("focusVisible") == value:
        return
    widget.setProperty("focusVisible", value)
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


_MODIFIER_KEYS = {
    Qt.Key.Key_Shift, Qt.Key.Key_Control, Qt.Key.Key_Alt, Qt.Key.Key_Meta,
    Qt.Key.Key_AltGr, Qt.Key.Key_CapsLock,
}
_KEY_EVENTS = {QEvent.Type.KeyPress, QEvent.Type.ShortcutOverride}
_POINTER_EVENTS = {
    QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick,
    QEvent.Type.TouchBegin, QEvent.Type.TabletPress,
}


class InputModality(QObject):
    """Application event filter remembering whether the last input was
    the keyboard or a pointer. A modifier pressed on its own (Shift before
    a click) changes nothing. It only reads event types and never consumes
    an event."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.keyboard = False

    def eventFilter(self, obj, event):
        et = event.type()
        if et in _POINTER_EVENTS:
            self.keyboard = False
        elif et == QEvent.Type.Shortcut:
            self.keyboard = True
        elif et in _KEY_EVENTS and event.key() not in _MODIFIER_KEYS:
            self.keyboard = True
        return False


_modality = None


def last_input_was_keyboard() -> bool:
    return _modality is not None and _modality.keyboard


def _mark(widget: QWidget) -> None:
    """Set ``focusVisible`` on a focused button from the last input. A
    button still held down is a click in progress whatever came before."""
    if not isinstance(widget, QAbstractButton):
        return
    visible = (last_input_was_keyboard() and QGuiApplication.mouseButtons()
               == Qt.MouseButton.NoButton)
    _set_focus_visible(widget, "true" if visible else "false")


def mark_focus_source(_old: QWidget, new: QWidget) -> None:
    """Slot for ``QApplication.focusChanged``: mark a button that just
    gained focus. This covers every way focus arrives (Tab, the page
    handoff, Qt restoring focus when the window is activated again), so
    the ring can't depend on which of them got there first."""
    if new is not None:
        _mark(new)


def install_focus_marker(qapp: QApplication) -> None:
    """Install the input tracker and connect ``mark_focus_source`` once
    per application, however many main windows are created."""
    global _modality
    if qapp is None or qapp.property(_INSTALLED):
        return
    _modality = InputModality(qapp)
    qapp.installEventFilter(_modality)
    qapp.focusChanged.connect(mark_focus_source)
    qapp.setProperty(_INSTALLED, True)


class _FocusWithin(QObject):
    """Event filter behind ``ring_container_on_focus``."""

    def __init__(self, field: QWidget, container: QWidget):
        super().__init__(field)
        self._container = container

    def eventFilter(self, obj, event):
        et = event.type()
        if et in (QEvent.Type.FocusIn, QEvent.Type.FocusOut):
            c = self._container
            c.setProperty("focusWithin",
                          "true" if et == QEvent.Type.FocusIn else "false")
            c.style().unpolish(c)
            c.style().polish(c)
            c.update()
        return False


def ring_container_on_focus(field: QWidget, container: QWidget) -> None:
    """Set ``focusWithin`` on ``container`` while ``field`` has focus, for
    a borderless field whose visible box is the container around it."""
    field.installEventFilter(_FocusWithin(field, container))


def give_focus(widget: QWidget) -> None:
    """Focus ``widget`` on the user's behalf. Its ring follows the last
    input, like any other focus change: shown after a key, not after a
    click. Marked here too because ``setFocus`` on the widget that already
    has focus emits no ``focusChanged``."""
    widget.setFocus(Qt.FocusReason.TabFocusReason)
    _mark(widget)


def disable_scroll_area_focus(root: QWidget) -> None:
    """Take the scroll areas inside ``root`` out of the Tab order.

    Qt makes every scroll area a Tab stop, which in this app is an
    invisible one: the area has no border to ring. Scrolling still works
    from the keyboard: Tab scrolls the focused control into view, keys a
    control inside the area doesn't use (Page Up/Down, arrows) still
    reach the area, and ``BasePage`` scrolls for controls outside it."""
    for area in root.findChildren(QScrollArea):
        area.setFocusPolicy(Qt.FocusPolicy.NoFocus)


def _is_tab_stop(w: QWidget) -> bool:
    """A control Tab would stop on. Scroll areas are left out: landing
    there would hide where the user is."""
    return (not isinstance(w, QScrollArea)
            and w.focusProxy() is None
            and w.isVisible() and w.isEnabled()
            and bool(w.focusPolicy().value & Qt.FocusPolicy.TabFocus.value))


def _on_screen(w: QWidget, container: QWidget) -> bool:
    """Whether some of ``w`` shows inside ``container``: its rectangle
    clipped by every ancestor up to the container, as a scroll area's
    viewport clips its content. Plain geometry, so it doesn't depend on
    paint state or on siblings Qt counts as covering it, as
    ``visibleRegion`` does."""
    rect = QRect(QPoint(0, 0), w.size())
    widget = w
    while widget is not container:
        parent = widget.parentWidget()
        if parent is None:
            return False
        rect = rect.translated(widget.pos()) & parent.rect()
        if rect.isEmpty():
            return False
        widget = parent
    return True


def first_focusable(container: QWidget):
    """The first control inside ``container`` in reading order: the top
    row, then its leftmost control.

    Not the focus chain: that is a ring through the whole window in
    creation order, so walking it from a page reaches widgets the page
    rebuilt after start-up (cards, chapter rows), and the ones about to be
    replaced, before the header built with the page. Controls scrolled out
    of view are skipped, so a scrolled page still starts at the top of
    what is on screen."""
    def span(w):
        top_left = w.mapTo(container, QPoint(0, 0))
        return top_left.y(), top_left.y() + w.height(), top_left.x()

    stops = [(w, span(w)) for w in container.findChildren(QWidget)
             if _is_tab_stop(w) and _on_screen(w, container)]
    if not stops:
        return None
    _w, (row_top, row_bottom, _x) = min(stops, key=lambda s: s[1][0])
    row = [s for s in stops if s[1][0] < row_bottom and s[1][1] > row_top]
    return min(row, key=lambda s: (s[1][2], s[1][0]))[0]


def focus_into(container: QWidget) -> None:
    """Move keyboard focus into ``container`` unless a control there
    already has it, so a page opened from the keyboard doesn't leave focus
    behind on a hidden page or bounce it back to the sidebar. Focus on the
    container itself (the reader) counts; focus on a scroll area doesn't.

    Call it once control is back in the event loop after a page rebuilt
    its content: new widgets are shown only by a queued call, so right
    after ``on_show`` they are not visible yet."""
    if not container.isVisible():
        return
    current = QApplication.focusWidget()
    if (current is not None and current.isVisible()
            and not isinstance(current, QScrollArea)
            and (current is container or container.isAncestorOf(current))):
        return
    target = first_focusable(container)
    if target is not None:
        give_focus(target)
