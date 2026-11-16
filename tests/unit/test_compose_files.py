"""The Compose files: compose.yaml runs the published image, and
compose.dev.yaml builds from source (issue #328)."""

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]

# ${NAME:-default}, the only interpolation form the files use.
_VARIABLE = re.compile(r"^\$\{(?P<name>[A-Z_]+):-(?P<default>[^}]*)\}$")


def _load(name):
    return yaml.safe_load((ROOT / name).read_text(encoding="utf-8"))


def _default(value):
    """The name and default of a ``${NAME:-default}`` value."""
    match = _VARIABLE.match(value)
    assert match, value
    return match["name"], match["default"]


def _image_volumes():
    """The paths the Dockerfile declares as volumes."""
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    line = next(line for line in text.splitlines() if line.startswith("VOLUME "))
    return set(re.findall(r'"([^"]+)"', line))


def _mounts(service):
    """{volume name: path in the container} of a service."""
    return dict(entry.split(":", 1) for entry in service["volumes"])


@pytest.fixture(scope="module")
def published():
    return _load("compose.yaml")


@pytest.fixture(scope="module")
def development():
    return _load("compose.dev.yaml")


class TestPublishedImageFile:
    def test_no_service_builds_from_source(self, published):
        # The file must work without a checkout: nothing to build.
        for name, service in published["services"].items():
            assert "build" not in service, name

    def test_image_defaults_to_a_pinned_release_and_can_be_overridden(
            self, published):
        variable, default = _default(published["services"]["memanga"]["image"])
        assert variable == "MEMANGA_IMAGE"
        repository, _, tag = default.rpartition(":")
        assert repository == "meellm/memanga"
        # A full version, not a tag that moves such as latest or 0.4.
        assert re.fullmatch(r"\d+\.\d+\.\d+", tag), tag

    def test_every_service_gets_an_init_process(self, published):
        # The 0.4.4 image starts memanga directly as PID 1.
        for name, service in published["services"].items():
            assert service.get("init") is True, name

    def test_no_service_needs_a_command_the_release_lacks(self, published):
        # `memanga watch` is not in the pinned release, so nothing may run
        # it or be set up as a long-running service.
        for name, service in published["services"].items():
            assert "watch" not in service.get("command", []), name
            assert "restart" not in service, name
        assert set(published["services"]) == {"memanga"}

    def test_time_zone_is_optional_and_defaults_to_utc(self, published):
        environment = published["services"]["memanga"]["environment"]
        assert _default(environment["TZ"]) == ("TZ", "UTC")

    def test_both_image_volumes_are_kept_in_named_volumes(self, published):
        mounts = _mounts(published["services"]["memanga"])
        assert set(mounts.values()) == _image_volumes()
        assert set(mounts) == set(published["volumes"])


class TestDevelopmentFile:
    def test_every_service_builds_from_the_checkout(self, development):
        for name, service in development["services"].items():
            assert service["build"] == ".", name
            assert service["image"] == "memanga:cli", name

    def test_scheduler_runs_watch_and_has_time_to_stop(self, development):
        scheduler = development["services"]["scheduler"]
        assert scheduler["command"][0] == "watch"
        assert scheduler["restart"] == "unless-stopped"
        assert scheduler["stop_grace_period"] == "1m"

    def test_one_off_service_is_kept(self, development):
        assert development["services"]["memanga"]["command"] == ["list"]


class TestBothFiles:
    def test_same_volumes_so_data_is_shared(self, published, development):
        # Compose names a volume after the project and this key, so equal
        # keys and paths mean both files open the same data.
        assert set(published["volumes"]) == set(development["volumes"])
        expected = _mounts(published["services"]["memanga"])
        for name, service in development["services"].items():
            assert _mounts(service) == expected, name

    def test_development_setup_is_never_loaded_automatically(self):
        # Compose merges these names into compose.yaml without being
        # asked, which would bring the local build back for everyone.
        for name in ("compose.override.yaml", "compose.override.yml",
                     "docker-compose.override.yaml",
                     "docker-compose.override.yml",
                     "docker-compose.yaml", "docker-compose.yml"):
            assert not (ROOT / name).exists(), name

    def test_each_file_says_how_it_is_used(self):
        default = (ROOT / "compose.yaml").read_text(encoding="utf-8")
        assert "compose.dev.yaml" in default
        dev = (ROOT / "compose.dev.yaml").read_text(encoding="utf-8")
        assert "docker compose -f compose.dev.yaml" in dev


def test_docker_guide_shows_the_real_file():
    # The site page includes compose.yaml itself, so the file a reader
    # copies cannot differ from the one that is tested here.
    guide = (ROOT / "docs/guide/docker.md").read_text(encoding="utf-8")
    assert "\n<<< ../../compose.yaml\n" in guide
