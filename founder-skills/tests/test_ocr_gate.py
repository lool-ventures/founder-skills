"""Step 4's gate on Step 3.95 (`slide_reviews.py --ledger --deck-text --ocr-check`).

The gate is the step's only enforcement: when a figure the numbers section uses sits on a slide read from how it
looks, the slide reviews are not written until this run's machine-read check exists for this reconciliation and
this deck. A deck with no such figure needs no file.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "deck-review" / "scripts"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "deck-review" / "slide_reviews.json"
RUN = "RID"


def _dir(tmp: Path, source: str = "inventory") -> Path:
    d = tmp / "review"
    d.mkdir()
    (d / "deck_text.md").write_text(
        f"---\nrun_id: {RUN}\nsource: {source}\npages_source: {{1: {source}, 2: {source}}}\ndeck_sha256: abc\n---\n"
        "## Slide 1\n\nT\n\n## Slide 2\n\nARR $1.2M\n"
    )
    figs = [{"id": "a", "raw": "$1.2M", "unit_kind": "money", "slide": 2}]
    figs.append({"id": "b", "raw": "$100K", "unit_kind": "money", "slide": 2})
    (d / "ledger.json").write_text(json.dumps({"figures": figs, "metadata": {"run_id": RUN}}))
    recon = {"status": "checked", "relations": [{"operands": ["b"], "expected_id": "a"}], "metadata": {"run_id": RUN}}
    (d / "reconciliation.json").write_text(json.dumps(recon))
    return d


def _check(d: Path, **over: Any) -> Path:
    sha = hashlib.sha256((d / "reconciliation.json").read_bytes()).hexdigest()
    body: dict[str, Any] = {"status": "checked", "metadata": {"run_id": RUN, "reconciliation_sha256": sha}}
    for key, value in over.items():
        if key in ("run_id", "reconciliation_sha256"):
            body["metadata"][key] = value
        else:
            body[key] = value
    path = d / "ocr_check.json"
    path.write_text(json.dumps(body))
    return path


def _pipe(d: Path, *, ocr_check: Path | None) -> tuple[int, dict[str, Any]]:
    body = json.loads(FIXTURE.read_text())
    body.pop("metadata", None)
    argv = [sys.executable, str(SCRIPTS / "slide_reviews.py"), "--run-id", RUN, "-o", str(d / "slide_reviews.json")]
    argv += ["--reconciliation", str(d / "reconciliation.json"), "--deck-text", str(d / "deck_text.md")]
    argv += ["--ledger", str(d / "ledger.json")]
    if ocr_check is not None:
        argv += ["--ocr-check", str(ocr_check)]
    proc = subprocess.run(argv, input=json.dumps(body), capture_output=True, text=True)
    last = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else "{}"
    try:
        out = json.loads(last)
    except ValueError:
        out = json.loads(proc.stdout)
    return proc.returncode, out


def test_a_text_deck_needs_no_check(tmp_path: Path) -> None:
    d = _dir(tmp_path, source="extracted")
    rc, _ = _pipe(d, ocr_check=None)
    assert rc == 0 and (d / "slide_reviews.json").exists()


def test_an_image_deck_with_this_runs_check_passes(tmp_path: Path) -> None:
    d = _dir(tmp_path)
    rc, _ = _pipe(d, ocr_check=_check(d))
    assert rc == 0 and (d / "slide_reviews.json").exists()


@pytest.mark.parametrize(
    ("case", "code"),
    [
        ("omitted", "OCR_CHECK_MISSING"),
        ("absent", "OCR_CHECK_MISSING"),
        ("other_run", "OCR_CHECK_OTHER_RUN"),
        ("stale", "OCR_CHECK_STALE"),
        ("wrong_deck", "OCR_CHECK_WRONG_DECK"),
    ],
)
def test_an_image_deck_without_a_usable_check_is_refused(tmp_path: Path, case: str, code: str) -> None:
    d = _dir(tmp_path)
    path: Path | None
    if case == "omitted":
        path = None
    elif case == "absent":
        path = d / "ocr_check.json"
    elif case == "other_run":
        path = _check(d, run_id="OTHER")
    elif case == "stale":
        path = _check(d, reconciliation_sha256="0" * 64)
    else:
        path = _check(d, status="not_applicable", reason="deck_mismatch")
    rc, out = _pipe(d, ocr_check=path)
    assert (rc, out.get("code")) == (1, code), out
    assert "Step 3.95" in out["message"] or "Step 2" in out["message"]
    assert not (d / "slide_reviews.json").exists()
