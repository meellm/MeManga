"""Issue #177 — Asura Scans was unticked in the curated default set
while its search was broken, so every install seeded before the fix
has ``asurascans.com`` written into ``sources.disabled``. Putting the
domain back into ``DEFAULT_ENABLED_SOURCES`` only helps fresh installs;
upgrading users need the stale entry removed once.

``_recurate_fixed_sources`` is exercised unbound on a stub app object —
constructing a full MeMangaApp window per test is slow and no widget is
involved.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest


@pytest.fixture
def stub_app(config):
    # The repair reads its curated list and flag key off the class, so
    # mirror them onto the stub rather than restating the values here.
    from memanga.gui.app import MeMangaApp
    return SimpleNamespace(
        config=config,
        _RECURATED_SOURCES=MeMangaApp._RECURATED_SOURCES,
        _RECURATION_FLAG=MeMangaApp._RECURATION_FLAG,
    )


def _repair(stub):
    from memanga.gui.app import MeMangaApp
    MeMangaApp._recurate_fixed_sources(stub)


def _seed(stub):
    from memanga.gui.app import MeMangaApp
    MeMangaApp._seed_default_sources_if_first_launch(stub)


def _flag():
    from memanga.gui.app import MeMangaApp
    return MeMangaApp._RECURATION_FLAG


class TestRecurateFixedSources:
    def test_seeded_config_gets_asura_back(self, stub_app, config):
        config.set("sources.first_run_seeded", True)
        config.set("sources.disabled", ["asurascans.com", "mgeko.cc"])

        _repair(stub_app)

        assert config.get("sources.disabled") == ["mgeko.cc"]
        assert config.get(_flag()) is True

    def test_other_disabled_sources_are_untouched(self, stub_app, config):
        # The repair is a targeted removal, not a re-seed: a user who
        # unticked half the catalogue keeps their selection.
        disabled = ["asuracomic.net", "asurascans.com", "asuratoon.com",
                    "mangadex.org", "mgeko.cc"]
        config.set("sources.first_run_seeded", True)
        config.set("sources.disabled", list(disabled))

        _repair(stub_app)

        assert config.get("sources.disabled") == [
            "asuracomic.net", "asuratoon.com", "mangadex.org", "mgeko.cc"]

    def test_retired_aliases_stay_disabled(self, stub_app, config):
        # Only the canonical domain is curated — the aliases are served
        # by the same scraper and must not rejoin the search sweep.
        config.set("sources.first_run_seeded", True)
        config.set("sources.disabled", ["asuracomic.net", "asuratoon.com"])

        _repair(stub_app)

        assert config.get("sources.disabled") == [
            "asuracomic.net", "asuratoon.com"]

    def test_runs_only_once(self, stub_app, config):
        config.set("sources.first_run_seeded", True)
        config.set("sources.disabled", ["asurascans.com"])
        _repair(stub_app)

        # User deliberately unticks Asura again — the next launch must
        # honour that instead of overriding it forever.
        config.set("sources.disabled", ["asurascans.com"])
        _repair(stub_app)

        assert config.get("sources.disabled") == ["asurascans.com"]

    def test_flag_is_set_even_when_nothing_to_remove(self, stub_app, config):
        config.set("sources.first_run_seeded", True)
        config.set("sources.disabled", ["mgeko.cc"])

        _repair(stub_app)

        assert config.get(_flag()) is True
        assert config.get("sources.disabled") == ["mgeko.cc"]

    def test_unseeded_config_is_left_alone(self, stub_app, config):
        # Pre-seeding installs ran everything-on; whatever they disabled
        # was a deliberate choice, and seeding keeps a saved list.
        config.set("sources.disabled", ["asurascans.com"])

        _repair(stub_app)

        assert config.get("sources.disabled") == ["asurascans.com"]
        assert config.get(_flag()) is True

    def test_change_is_persisted(self, stub_app, config):
        config.set("sources.first_run_seeded", True)
        config.set("sources.disabled", ["asurascans.com", "mgeko.cc"])

        _repair(stub_app)

        from memanga.config import Config
        reloaded = Config()
        assert reloaded.get("sources.disabled") == ["mgeko.cc"]
        assert reloaded.get(_flag()) is True


def _ticked(config):
    """Search sources left enabled: template sites are never disabled
    and never searched, so they are not part of the selection."""
    from memanga.scrapers import SCRAPERS
    from memanga.scrapers.registry import TEMPLATE_SCRAPERS
    disabled = set(config.get("sources.disabled"))
    return {d for d in SCRAPERS
            if d not in disabled and d not in TEMPLATE_SCRAPERS}


class TestFreshInstallUnaffected:
    def test_seeding_ticks_exactly_the_default_selection(self, stub_app,
                                                         config):
        # Repair runs before seeding on every launch; on a fresh config
        # it must be a no-op that doesn't disturb the default selection.
        from memanga.scrapers import DEFAULT_ENABLED_SOURCES
        from memanga.search import compute_search_sources
        _repair(stub_app)
        _seed(stub_app)

        assert _ticked(config) == {
            "mangadex.org", "mangapark.cc", "mangafire.to",
            "mangabuddy.com", "weebcentral.com"}
        assert config.get("sources.first_run_seeded") is True
        # The Search page and `memanga search` sweep those same five.
        assert sorted(compute_search_sources(config)) == sorted(
            DEFAULT_ENABLED_SOURCES)
        # Sources outside the selection, and aliases, are seeded disabled.
        disabled = config.get("sources.disabled")
        for domain in ("mangapill.com", "asurascans.com",
                       "asuracomic.net", "asuratoon.com"):
            assert domain in disabled

    @pytest.mark.parametrize("saved", [
        [],
        ["mangadex.org", "mgeko.cc"],
    ])
    def test_seeding_keeps_a_list_saved_before_first_launch(
            self, stub_app, config, saved):
        # A list written before the desktop app ever ran (by hand, or by
        # a pre-seeding install) is a selection; an empty one means
        # everything ticked. Seeding must not replace either.
        config.set("sources.disabled", list(saved))

        _seed(stub_app)

        assert config.get("sources.disabled") == saved
        assert config.get("sources.first_run_seeded") is True

    def test_seeding_keeps_everything_disabled(self, stub_app, config):
        from memanga.scrapers import SCRAPERS
        everything = sorted(SCRAPERS)
        config.set("sources.disabled", list(everything))

        _seed(stub_app)

        assert config.get("sources.disabled") == everything

    def test_seeded_selection_survives_a_new_default_set(self, stub_app,
                                                         config):
        # A config seeded by an earlier release keeps the sources it was
        # given, and any edits, when the default selection changes.
        from memanga.scrapers import SCRAPERS
        from memanga.scrapers.registry import TEMPLATE_SCRAPERS
        kept = {"mangadex.org", "mangapill.com", "mangakatana.com",
                "comix.to"}
        disabled = sorted(d for d in SCRAPERS
                          if d not in kept and d not in TEMPLATE_SCRAPERS)
        config.set("sources.first_run_seeded", True)
        config.set("sources.disabled", list(disabled))

        _repair(stub_app)
        _seed(stub_app)

        # The one-time Asura repair still applies; nothing else moves.
        assert _ticked(config) == kept | {"asurascans.com"}

    def test_second_launch_keeps_the_seeded_selection(self, stub_app, config):
        # Every launch runs the repair, then seeding. On a fresh install
        # the repair sets its flag before anything is seeded, so the next
        # launch must not tick Asura Scans, which seeding left disabled.
        _repair(stub_app)
        _seed(stub_app)
        before = list(config.get("sources.disabled"))
        assert "asurascans.com" in before

        _repair(stub_app)
        _seed(stub_app)

        assert config.get("sources.disabled") == before

    def test_second_launch_keeps_the_users_changes(self, stub_app, config):
        _repair(stub_app)
        _seed(stub_app)
        # The user unticks one default and ticks a source outside them.
        disabled = set(config.get("sources.disabled"))
        disabled.add("mangadex.org")
        disabled.discard("mangapill.com")
        config.set("sources.disabled", sorted(disabled))

        _repair(stub_app)
        _seed(stub_app)

        assert _ticked(config) == {
            "mangapark.cc", "mangafire.to", "mangabuddy.com",
            "weebcentral.com", "mangapill.com"}
