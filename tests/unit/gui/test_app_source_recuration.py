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
        # was a deliberate choice, and seeding rewrites the list anyway.
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


class TestFreshInstallUnaffected:
    def test_seeding_still_leaves_asura_enabled(self, stub_app, config):
        # Repair runs before seeding on every launch; on a fresh config
        # it must be a no-op that doesn't disturb the curated set.
        _repair(stub_app)
        _seed(stub_app)

        disabled = config.get("sources.disabled")
        assert "asurascans.com" not in disabled
        assert config.get("sources.first_run_seeded") is True
        # The aliases are seeded disabled, as before.
        assert "asuracomic.net" in disabled
        assert "asuratoon.com" in disabled

    def test_repair_after_seeding_is_a_no_op(self, stub_app, config):
        _seed(stub_app)
        before = list(config.get("sources.disabled"))

        _repair(stub_app)

        assert config.get("sources.disabled") == before
