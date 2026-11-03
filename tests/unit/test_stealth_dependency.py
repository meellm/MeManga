"""#213: the Playwright scrapers use the ``Stealth`` class from playwright-stealth
2.x. Dependency declarations must not allow the 1.x releases, which lack it."""
import re
from pathlib import Path

import pytest
from packaging.specifiers import SpecifierSet

ROOT = Path(__file__).resolve().parents[2]
COMPATIBLE = SpecifierSet(">=2.0,<3")
LOCKS = [f"requirements/{name}.txt" for name in ("cli", "gui", "dev", "build")]


def _declared_spec(name):
    text = (ROOT / name).read_text(encoding="utf-8")
    pattern = r"""["']?playwright-stealth([<>=!~][^"',\s]*(?:\s*,\s*[<>=!~][^"',\s]*)*)"""
    match = re.search(pattern, text)
    assert match, f"playwright-stealth not declared in {name}"
    return SpecifierSet(match.group(1).strip())


def test_playwright_stealth_declaration_requires_2x():
    spec = _declared_spec("pyproject.toml")
    assert not spec.contains("1.0.6"), f"pyproject.toml allows {spec} (includes 1.0.6)"
    assert spec.contains("2.0.3"), f"pyproject.toml excludes 2.x: {spec}"


@pytest.mark.parametrize("name", LOCKS)
def test_playwright_stealth_locks_pin_2x(name):
    # Docker, the builds and source setups install from these locks.
    spec = _declared_spec(name)
    pins = [s.version for s in spec if s.operator == "=="]
    assert len(pins) == 1, f"{name} must pin exactly: {spec}"
    assert COMPATIBLE.contains(pins[0]), f"{name} pins {pins[0]}, need {COMPATIBLE}"
