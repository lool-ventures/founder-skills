"""The plugin folder must install through Desktop's plugin download.

Desktop extracts a plugin with a zip-bomb guard: an entry that compresses better than 50:1 fails the whole
plugin, silently. The install then reports nothing, and the plugin never appears. Every file the plugin
ships (everything tracked under founder-skills/, tests included) is held well under that guard.
"""

from __future__ import annotations

import subprocess
import zlib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_DIR = "founder-skills"
# Desktop refuses above 50:1. Zip's deflate and zlib at level 9 differ slightly, so hold a wide margin.
MAX_RATIO = 30.0
# Below this size, a zip header outweighs any compression, and the ratio is not meaningful.
MIN_BYTES = 1024


def _tracked_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "-z", PLUGIN_DIR], cwd=REPO_ROOT, capture_output=True, check=True
    ).stdout.decode("utf-8")
    return [REPO_ROOT / name for name in out.split("\0") if name]


def _ratio(data: bytes) -> float:
    return len(data) / max(1, len(zlib.compress(data, 9)))


def test_the_ratio_measure_catches_a_repetitive_file() -> None:
    """Control: a highly repetitive payload, the shape of the fixture that tripped the guard, is over the
    limit, and an ordinary one is not."""
    assert _ratio(b'{"k": "same text"}, ' * 20000) > MAX_RATIO
    assert _ratio(bytes(range(256)) * 8) < MAX_RATIO


def test_no_shipped_file_compresses_past_the_desktop_guard() -> None:
    files = _tracked_files()
    assert len(files) > 100, "control: the plugin's tracked files were listed"
    over = []
    for path in files:
        if not path.is_file():
            continue
        data = path.read_bytes()
        if len(data) >= MIN_BYTES and _ratio(data) > MAX_RATIO:
            over.append(f"{path.relative_to(REPO_ROOT)}: {_ratio(data):.1f}:1")
    assert not over, (
        "these files compress past the limit; Desktop refuses a plugin with an entry above 50:1. "
        "Store a large repetitive fixture gzipped: " + ", ".join(over)
    )
