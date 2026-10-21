"""competitive-positioning's coaching payload, held byte-for-byte on the fixture.

The CP page work changes compose, `_cp_view` and the pages, and must not change what the coach reads: CP has no
paid lane, so nothing else would notice. The golden is a sha256 of each payload key's value (the insertion marker
and the two paths stripped), not a digest of the source, so a legitimate edit elsewhere in `_cp_view` leaves it
alone and a failure names the key that moved. Hashes, not the text: the payload's sentences are also in kept runs
of this fixture, which the local privacy guard reads as private sources.

Regenerate, only for a deliberate payload change: `python founder-skills/tests/test_cp_payload_golden.py`.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from compose_invocations import drive_compose

HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "fixtures" / "competitive-positioning"
GOLDEN = HERE / "fixtures" / "golden" / "competitive-positioning" / "coaching_payload.sha256.json"
_RUN_SPECIFIC = ("insertion_marker", "review_dir", "report_path")


def _strip(payload: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in payload.items() if k not in _RUN_SPECIFIC}


def _digest(payload: dict[str, Any]) -> dict[str, str]:
    return {
        k: hashlib.sha256(json.dumps(v, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
        for k, v in payload.items()
    }


def _payload_from(report_json: Path) -> dict[str, str]:
    return _digest(_strip(json.loads(report_json.read_text(encoding="utf-8"))["coaching_payload"]))


def _fixture_payload() -> dict[str, str]:
    with tempfile.TemporaryDirectory() as td:
        return _payload_from(drive_compose("competitive-positioning", FIXTURE, Path(td)))


def test_coaching_payload_equals_the_golden() -> None:
    assert GOLDEN.exists(), f"missing {GOLDEN}; regenerate with `python {Path(__file__).name}`"
    assert _fixture_payload() == json.loads(GOLDEN.read_text(encoding="utf-8"))


def test_the_golden_sees_a_one_word_edit_in_claim_sentences(tmp_path: Path) -> None:
    """Lever: compose from a copy of the scripts whose claim sentences say one word differently. (The fixture's
    positioning predates the map geometry, so its map sentences are empty and cannot be the lever.)"""
    plugin = tmp_path / "founder-skills"  # compose loads the plugin's shared modules by path, so copy the plugin
    shutil.copytree(HERE.parent, plugin, ignore=shutil.ignore_patterns("tests", "__pycache__"))
    copy = plugin / "skills" / "competitive-positioning" / "scripts"
    view = copy / "_cp_view.py"
    src = view.read_text(encoding="utf-8")
    old = '"partially_holds": "only partly holds",'
    assert src.count(old) == 1, "the lever's anchor moved; pick another word in claim_sentences' output"
    view.write_text(src.replace(old, '"partially_holds": "only partially holds",'), encoding="utf-8")
    work = tmp_path / "work"
    work.mkdir()
    for f in FIXTURE.iterdir():
        shutil.copy2(f, work / f.name)
    proc = subprocess.run(
        [
            sys.executable,
            str(copy / "compose_report.py"),
            "--dir",
            str(work),
            "-o",
            str(work / "report.json"),
            "--write-md",
            str(work / "report.md"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    edited = _payload_from(work / "report.json")
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert edited != golden
    assert edited["claim_verdicts"] != golden["claim_verdicts"]


if __name__ == "__main__":
    sys.path.insert(0, str(HERE))
    GOLDEN.parent.mkdir(parents=True, exist_ok=True)
    GOLDEN.write_text(json.dumps(_fixture_payload(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {GOLDEN}")
