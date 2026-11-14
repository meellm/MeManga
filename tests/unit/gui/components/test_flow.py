"""FlowFrame: a row of widgets that wraps instead of running past its
right edge."""

from __future__ import annotations

import pytest


@pytest.fixture
def host(qapp, theme):
    """A shown window holding one FlowFrame of five buttons, with a
    label below it to show whether the frame takes the height it needs."""
    from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget
    from memanga.gui.components.flow import FlowFrame
    window = QWidget()
    layout = QVBoxLayout(window)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    frame = FlowFrame(h_spacing=6, v_spacing=6, last_right=True)
    buttons = [QPushButton(f"Button number {i}") for i in range(5)]
    for button in buttons:
        frame.addWidget(button)
    below = QLabel("below")
    layout.addWidget(frame)
    layout.addWidget(below)
    layout.addStretch(1)
    window.show()
    yield window, frame, buttons, below
    window.close()


def _settle(qapp, window, width):
    window.resize(width, 400)
    for _ in range(3):
        qapp.processEvents()


def test_one_line_when_there_is_room(qapp, host):
    window, frame, buttons, _below = host
    _settle(qapp, window, frame.flow().sizeHint().width() + 200)
    assert len({b.y() for b in buttons}) == 1
    # The last one sits at the right end, like a row ending in a stretch.
    last = buttons[-1]
    assert last.x() + last.width() == frame.width()
    assert buttons[-2].x() + buttons[-2].width() < last.x()


def test_wraps_and_takes_the_height_it_needs(qapp, host):
    window, frame, buttons, below = host
    one_line = frame.flow().sizeHint().width()
    _settle(qapp, window, one_line // 2)
    assert len({b.y() for b in buttons}) > 1
    for b in buttons:
        assert b.x() >= 0 and b.x() + b.width() <= frame.width()
        assert b.width() == b.sizeHint().width()   # not squeezed
        assert b.y() + b.height() <= frame.height()
    # The next widget starts below the last line, not over it.
    assert below.y() >= frame.y() + frame.height()
    assert frame.height() >= frame.heightForWidth(frame.width())


def test_goes_back_to_one_line(qapp, host):
    window, frame, buttons, _below = host
    one_line = frame.flow().sizeHint().width()
    _settle(qapp, window, one_line // 2)
    tall = frame.height()
    _settle(qapp, window, one_line + 200)
    assert len({b.y() for b in buttons}) == 1
    assert frame.height() < tall


def test_minimum_is_the_widest_item(qapp, host):
    _window, frame, buttons, _below = host
    # Buttons do not shrink below their size hint, so that is their
    # minimum in a layout.
    widest = max(b.sizeHint().width() for b in buttons)
    assert frame.minimumSizeHint().width() == widest
    assert frame.flow().sizeHint().width() > 2 * widest


def test_tab_order_is_the_reading_order(qapp, host):
    _window, frame, buttons, _below = host
    chain, widget = [], buttons[0]
    while len(chain) < len(buttons) - 1:
        widget = widget.nextInFocusChain()
        if widget in buttons:
            chain.append(widget)
    assert chain == buttons[1:]
