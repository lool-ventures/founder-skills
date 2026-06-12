"""Brand-theme sync invariants.

Every skill ships an identical copy of scripts/_theme.py (standalone PEP 723
scripts can't reliably import across skills, so the module is vendored
per-skill). These tests catch copies drifting apart and the brand font
disappearing — either would silently degrade generated HTML artifacts.
"""

from __future__ import annotations

from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_SKILLS_DIR = _REPO / "skills"
_BRAND_FONT = _REPO / "references" / "brand" / "fonts" / "Sora-variable.woff2"


def _theme_copies() -> list[Path]:
    return sorted(_SKILLS_DIR.glob("*/scripts/_theme.py"))


def test_every_skill_has_a_theme_copy() -> None:
    skills = sorted(p.name for p in _SKILLS_DIR.iterdir() if p.is_dir())
    skills_with_theme = sorted(p.parent.parent.name for p in _theme_copies())
    assert skills_with_theme == skills, (
        f"skills missing scripts/_theme.py: {sorted(set(skills) - set(skills_with_theme))}"
    )


def test_theme_copies_are_identical() -> None:
    copies = _theme_copies()
    assert copies, "no _theme.py copies found"
    contents = {p.read_bytes() for p in copies}
    assert len(contents) == 1, (
        "scripts/_theme.py copies have drifted apart; "
        "edit one and re-copy it to every skill: " + ", ".join(str(p.relative_to(_REPO)) for p in copies)
    )


def test_brand_font_present_and_woff2() -> None:
    assert _BRAND_FONT.is_file(), f"missing brand font: {_BRAND_FONT}"
    with open(_BRAND_FONT, "rb") as f:
        magic = f.read(4)
    assert magic == b"wOF2", "Sora-variable.woff2 is not a valid woff2 file"


def test_theme_module_embeds_font() -> None:
    import importlib.util

    theme_path = _theme_copies()[0]
    spec = importlib.util.spec_from_file_location("_theme_sync_check", theme_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    css = module.brand_css()
    assert "data:font/woff2;base64," in css
    assert "--lool-blue: #0D549D" in css
    assert "font-weight: 100 800" in css
