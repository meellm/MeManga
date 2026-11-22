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


# ─────────────────────────────────────────────────────────────────────────
# Contrast and text size (issue #395)
# ─────────────────────────────────────────────────────────────────────────

# WCAG 2.x AA for normal-size text.
AA = 4.5

SURFACES = ("surfaces.bg_0", "surfaces.bg_1", "surfaces.bg_2",
            "surfaces.bg_3", "surfaces.root_bg")
# Page, card and raised surfaces: where coloured text is written.
TEXT_SURFACES = ("surfaces.bg_0", "surfaces.bg_1", "surfaces.bg_2")


def _rgb(value: str):
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def _luminance(rgb) -> float:
    def channel(v):
        v /= 255
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(v) for v in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a, b) -> float:
    high, low = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def _over(rgba: str, background):
    """The colour an ``rgba(r,g,b,a)`` tint shows as on ``background``."""
    import re
    r, g, b, alpha = re.fullmatch(
        r"rgba\((\d+),\s*(\d+),\s*(\d+),\s*([\d.]+)\)", rgba).groups()
    alpha = float(alpha)
    return tuple(round(int(fg) * alpha + bg * (1 - alpha))
                 for fg, bg in zip((r, g, b), background))


@pytest.fixture(params=["dark", "light"])
def flat_theme(request):
    from memanga.gui.theme.tokens import THEMES, flat
    return request.param, flat(THEMES[request.param])


class TestContrast:
    """Text colours reach AA on the surfaces they are used on."""

    @pytest.mark.parametrize("text", ["text.t_1", "text.t_2", "text.t_3"])
    @pytest.mark.parametrize("surface", SURFACES)
    def test_text_on_every_surface(self, flat_theme, text, surface):
        name, t = flat_theme
        ratio = _contrast(_rgb(t[text]), _rgb(t[surface]))
        assert ratio >= AA, f"{name}: {text} on {surface} is {ratio:.2f}:1"

    @pytest.mark.parametrize("colour", [
        "accent.primary", "secondary_lilac.primary", "status.danger",
        "status.warn", "status.info", "status.success"])
    @pytest.mark.parametrize("surface", TEXT_SURFACES)
    def test_accent_and_status_colours_as_text(self, flat_theme, colour,
                                               surface):
        name, t = flat_theme
        ratio = _contrast(_rgb(t[colour]), _rgb(t[surface]))
        assert ratio >= AA, f"{name}: {colour} on {surface} is {ratio:.2f}:1"

    @pytest.mark.parametrize("fill", [
        "accent.primary", "accent.primary_2", "status.success",
        "status.warn", "status.danger"])
    def test_on_primary_text_on_fills(self, flat_theme, fill):
        # Primary buttons, the NEW badge and toasts write
        # accent.on_primary on these fills.
        name, t = flat_theme
        ratio = _contrast(_rgb(t["accent.on_primary"]), _rgb(t[fill]))
        assert ratio >= AA, f"{name}: on_primary on {fill} is {ratio:.2f}:1"

    @pytest.mark.parametrize("colour,tint,surfaces", [
        # Source pill, active nav item.
        ("accent.primary", "accent.soft_10", ("surfaces.bg_0", "surfaces.bg_1")),
        # Count badge of the active nav item, in the sidebar.
        ("accent.primary", "accent.soft_16", ("surfaces.bg_1",)),
        # Backup-source pill.
        ("status.warn", "status.warn_soft", ("surfaces.bg_0", "surfaces.bg_1")),
        # Danger button, hovered.
        ("status.danger", "status.danger_soft", ("surfaces.bg_0", "surfaces.bg_1")),
    ])
    def test_colour_on_its_own_tint(self, flat_theme, colour, tint, surfaces):
        name, t = flat_theme
        for surface in surfaces:
            shown = _over(t[tint], _rgb(t[surface]))
            ratio = _contrast(_rgb(t[colour]), shown)
            assert ratio >= AA, (
                f"{name}: {colour} on {tint} over {surface} is {ratio:.2f}:1")


class TestMinimumTextSize:
    def test_no_typography_size_below_the_minimum(self):
        from memanga.gui.theme.tokens import TYPOGRAPHY
        smallest = TYPOGRAPHY["size_min"]
        assert smallest >= 9
        for key, value in TYPOGRAPHY.items():
            if key.startswith("size_"):
                assert value >= smallest, key

    def test_stylesheet_has_no_smaller_font_size(self):
        import re
        from memanga.gui.theme.qss_builder import build_stylesheet
        from memanga.gui.theme.tokens import THEMES, TYPOGRAPHY
        sizes = re.findall(r"font-size:\s*([\d.]+)pt",
                           build_stylesheet(THEMES["dark"]))
        assert sizes
        assert min(float(s) for s in sizes) >= TYPOGRAPHY["size_min"]

    def test_gui_sources_have_no_smaller_font_size(self):
        # Inline style sheets and painted fonts: nothing under the
        # minimum, in points or pixels.
        import re
        from pathlib import Path
        import memanga.gui as gui
        from memanga.gui.theme.tokens import TYPOGRAPHY
        smallest = TYPOGRAPHY["size_min"]
        offenders = []
        for path in Path(gui.__file__).parent.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for match in re.finditer(
                    r"font-size:\s*([\d.]+)pt|setPointSizeF?\(([\d.]+)\)", text):
                size = float(match.group(1) or match.group(2))
                if size < smallest:
                    offenders.append(f"{path.name}: {match.group(0)}")
        assert not offenders, offenders


class TestStatusLabels:
    def test_one_wording_per_status(self):
        from memanga.gui.theme.tokens import (STATUS_ORDER, STATUS_TOKEN,
                                              status_label)
        assert [status_label(s) for s in STATUS_ORDER] == [
            "Reading", "Plan to read", "On hold", "Completed", "Dropped"]
        # The older spelling reads the same.
        assert status_label("paused") == status_label("on-hold")
        assert status_label(None) == "Reading"
        assert status_label("re-reading") == "Re reading"
        # Every listed status has a colour.
        assert set(STATUS_ORDER) <= set(STATUS_TOKEN)
