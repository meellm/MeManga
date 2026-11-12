"""Theme-change subscriptions: widgets that come and go must not stay
subscribed after they are gone."""

from __future__ import annotations

import gc

import pytest


@pytest.fixture
def subscribers(theme):
    """The theme module with its subscriber list restored afterwards."""
    before = list(theme._subscribers)
    yield theme
    theme._subscribers[:] = before


class _Listener:
    def __init__(self):
        self.calls = 0

    def on_theme(self):
        self.calls += 1


class TestWeakMethodSubscribers:
    def test_bound_method_is_called(self, qapp, subscribers):
        listener = _Listener()
        subscribers.on_theme_change(listener.on_theme)
        subscribers.set_theme("light", qapp)
        assert listener.calls == 1

    def test_same_method_subscribes_once(self, qapp, subscribers):
        listener = _Listener()
        subscribers.on_theme_change(listener.on_theme)
        subscribers.on_theme_change(listener.on_theme)
        subscribers.set_theme("light", qapp)
        assert listener.calls == 1

    def test_subscriber_goes_away_with_its_object(self, qapp, subscribers):
        before = subscribers.subscriber_count()
        listener = _Listener()
        subscribers.on_theme_change(listener.on_theme)
        assert subscribers.subscriber_count() == before + 1
        del listener
        gc.collect()
        assert subscribers.subscriber_count() == before
        subscribers.set_theme("light", qapp)  # nothing left to call

    def test_off_theme_change_removes_a_method(self, qapp, subscribers):
        listener = _Listener()
        subscribers.on_theme_change(listener.on_theme)
        subscribers.off_theme_change(listener.on_theme)
        subscribers.set_theme("light", qapp)
        assert listener.calls == 0

    def test_lambda_stays_subscribed(self, qapp, subscribers):
        # Functions and lambdas have no owner to follow; they stay until
        # removed, as before.
        calls = []
        subscribers.on_theme_change(lambda: calls.append(1))
        gc.collect()
        subscribers.set_theme("light", qapp)
        assert calls == [1]


class TestWidgetSubscribers:
    def test_deleted_widget_is_dropped_not_called(self, qapp, subscribers):
        import shiboken6
        from PySide6.QtWidgets import QWidget

        class Probe(QWidget):
            calls = 0

            def on_theme(self):
                Probe.calls += 1

        before = subscribers.subscriber_count()
        probe = Probe()
        subscribers.on_theme_change(probe.on_theme)
        shiboken6.delete(probe)  # the C++ widget is gone, the wrapper is not
        subscribers.set_theme("light", qapp)
        assert Probe.calls == 0
        assert subscribers.subscriber_count() == before

    def test_rebuilt_cards_do_not_pile_up(self, qapp, subscribers,
                                          sample_manga):
        # The Library rebuilds its cards on every refresh; each card
        # subscribes twice (cover area and labels).
        import shiboken6
        from PySide6.QtGui import QPixmap
        from memanga.gui.components.manga_card import MangaCard

        before = subscribers.subscriber_count()
        for _ in range(5):
            card = MangaCard(None, manga=sample_manga, cover_image=QPixmap())
            shiboken6.delete(card)
        del card
        gc.collect()
        assert subscribers.subscriber_count() == before
