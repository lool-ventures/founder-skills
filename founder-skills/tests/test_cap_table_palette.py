"""Unit tests for the shared cap-table ownership palette (_palette.py)."""

from __future__ import annotations

import os
import sys
import types
from typing import Any

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPTS = os.path.join(_REPO, "founder-skills", "skills", "cap-table", "scripts")
sys.path.insert(0, SCRIPTS)

import _palette  # type: ignore[import-not-found]  # noqa: E402


def _import_visualize() -> Any:
    import importlib.util

    mod_name = "_test_palette_viz"
    path = os.path.join(SCRIPTS, "visualize.py")
    spec = importlib.util.spec_from_file_location(mod_name, path)
    assert spec and spec.loader
    mod = types.ModuleType(mod_name)
    mod.__spec__ = spec
    mod.__file__ = path
    theme_stub = types.ModuleType("_theme")
    theme_stub.brand_css = lambda: ""  # type: ignore[attr-defined]
    theme_stub.FOOTER_CREDIT_HTML = ""  # type: ignore[attr-defined]
    sys.modules.setdefault("_theme", theme_stub)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_visualize_reexports_palette_from_module() -> None:
    viz = _import_visualize()
    assert viz.PALETTE is _palette.PALETTE, "visualize.PALETTE must be the shared dict"
    assert hasattr(viz, "EXCLUDED_OWNERSHIP_KEYS")


def test_money_compact_strips_round_decimals_only() -> None:
    viz = _import_visualize()
    assert viz._money_compact(18_000_000) == "$18M"
    assert viz._money_compact(5_000_000) == "$5M"
    assert viz._money_compact(18_500_000) == "$18.50M"
    assert viz._money_compact(4_250_000) == "$4.25M"
    assert viz._money_compact(None) == "—"


def test_palette_has_mock_values() -> None:
    assert _palette.PALETTE["founders"] == "#0D549D"
    assert _palette.PALETTE["option_pool"] == "#C9892B"
    assert _palette.PALETTE["safe"] == "#7A5EA8"
    assert _palette.PALETTE["note"] == "#B0563C"
    assert _palette.PALETTE["new_money"] == "#2F8A56"
    assert _palette.PALETTE["other_common"] == "#5E6E82"


def test_order_lists_cover_every_renderable_class() -> None:
    renderable = set(_palette.PALETTE) - {"neutral"}
    assert renderable <= set(_palette.ORDER_DONUT), "ORDER_DONUT missing a palette class"
    assert renderable <= set(_palette.ORDER_LEGEND), "ORDER_LEGEND missing a palette class"
    assert _palette.ORDER_DONUT[1] == "other_common", "other_common must sit right after founders"


def test_slice_color_tolerates_pct_suffix() -> None:
    assert _palette.slice_color("founders_pct") == "#0D549D"
    assert _palette.slice_color("founders") == "#0D549D"
    assert _palette.slice_color("totally_unknown") == _palette.PALETTE["neutral"]


def test_slice_label_is_human() -> None:
    assert _palette.slice_label("founders_pct") == "Founders"
    assert _palette.slice_label("new_money") == "New investors"
    assert _palette.slice_label("mystery_class") == "mystery class"
