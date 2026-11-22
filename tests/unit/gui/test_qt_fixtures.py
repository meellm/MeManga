"""The shared Qt fixtures: a GUI test starts without the widgets earlier
tests left for the garbage collector."""

from __future__ import annotations

import gc
import weakref


def _window_names(app):
    return {w.objectName() for w in app.topLevelWidgets()}


def test_qapp_frees_widgets_left_in_a_reference_cycle(qapp_session, request):
    from PySide6.QtWidgets import QWidget

    gc.collect()
    gc.disable()  # only the fixture may collect the cycle below
    try:
        widget = QWidget()
        widget.setObjectName("left-in-a-cycle")
        widget.cycle = widget
        alive = weakref.ref(widget)
        del widget
        # Only the cyclic collector can free it: still a window.
        assert alive() is not None
        assert "left-in-a-cycle" in _window_names(qapp_session)

        request.getfixturevalue("qapp")

        assert alive() is None
        assert "left-in-a-cycle" not in _window_names(qapp_session)
    finally:
        gc.enable()
