"""Tests for memanga.gui.theme.tokens — the design-system source of truth."""

import pytest


class TestThemeTable:
    def test_dark_and_light_both_present(self):
        from memanga.gui.theme.tokens import THEMES
        assert "dark" in THEMES and "light" in THEMES

    def test_required_top_level_groups(self):
        from memanga.gui.theme.tokens import THEMES
        for name, theme in THEMES.items():
            for group in ("surfaces", "text", "accent", "status",
                          "scrollbar", "secondary_lilac"):
                assert group in theme, f"{name} missing {group}"

    def test_every_surface_key_present(self):
        from memanga.gui.theme.tokens import THEMES
        required = {"bg_0", "bg_1", "bg_2", "bg_3", "bg_4",
                    "border", "border_strong", "root_bg"}
        for name, theme in THEMES.items():
            missing = required - set(theme["surfaces"].keys())
            assert not missing, f"{name} surfaces missing {missing}"

    def test_colors_are_valid_hex_or_rgba(self):
        from memanga.gui.theme.tokens import THEMES, flat
        import re
        # Accept hex, rgba(), or the CSS keyword "transparent" (used by
        # the scrollbar track to fall back to the parent background).
        ok = re.compile(r"^(#[0-9A-Fa-f]{6}|rgba\(.+\)|transparent)$")
        for name, theme in THEMES.items():
            for k, v in flat(theme).items():
                if k == "label":
                    continue
                assert ok.match(str(v)), f"{name}.{k}={v} not hex/rgba"


class TestFlatHelper:
    def test_flattens_nested(self):
        from memanga.gui.theme.tokens import flat
        out = flat({"a": {"b": "x"}, "c": "y"})
        assert out == {"a.b": "x", "c": "y"}

    def test_get_resolves_dotted_key(self):
        from memanga.gui.theme.tokens import get
        # bg_0 must always resolve
        v = get("surfaces.bg_0", "dark")
        assert v.startswith("#")
