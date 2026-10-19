"""`deck_text.py` writes one canonical deck-text file, and refuses loudly without touching `-o`.

Fixtures are built from invented company names and figures only. The PPTX is written with
`zipfile` and the smallest XML parts this reader needs; the PDF tests monkeypatch
`_pdf_pages.page_texts` so image pages are simulated without a PDF toolchain. The one real
text-layer PDF test skips unless both `pdftotext` and reportlab are present.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

import pytest

TESTS = Path(__file__).resolve().parent
SCRIPTS = TESTS.parent / "skills" / "deck-review" / "scripts"
SCRIPT = SCRIPTS / "deck_text.py"

sys.path.insert(0, str(SCRIPTS))

import _deck_text_file  # type: ignore[import-not-found]  # noqa: E402
import _pdf_pages  # type: ignore[import-not-found]  # noqa: E402
import deck_text  # type: ignore[import-not-found]  # noqa: E402

_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_P = "http://schemas.openxmlformats.org/presentationml/2006/main"

_NOTES_TEXT = "Mention the invented pilot cohort."
_SLIDE_NUMBER = "SLIDENUM-77"


def _paragraphs(*lines: str) -> str:
    return "".join(
        "<a:p>" + "".join(f"<a:r><a:t>{escape(run)}</a:t></a:r>" for run in line.split("|")) + "</a:p>"
        for line in lines
    )


def _slide_xml(lines: list[str]) -> str:
    return (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<p:sld xmlns:a="{_A}" xmlns:p="{_P}"><p:cSld><p:spTree><p:sp><p:txBody>'
        f"{_paragraphs(*lines)}"
        f"</p:txBody></p:sp></p:spTree></p:cSld></p:sld>"
    )


def _notes_xml() -> str:
    return (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<p:notes xmlns:a="{_A}" xmlns:p="{_P}"><p:cSld><p:spTree>'
        f'<p:sp><p:nvSpPr><p:nvPr><p:ph type="body"/></p:nvPr></p:nvSpPr><p:txBody>'
        f"{_paragraphs(_NOTES_TEXT)}"
        f"</p:txBody></p:sp>"
        f'<p:sp><p:nvSpPr><p:nvPr><p:ph type="sldNum"/></p:nvPr></p:nvSpPr><p:txBody>'
        f"{_paragraphs(_SLIDE_NUMBER)}"
        f"</p:txBody></p:sp>"
        f"</p:spTree></p:cSld></p:notes>"
    )


def _presentation_parts(order: list[str]) -> dict[str, str]:
    slide_rels = "".join(
        f'<Relationship Id="rIdSlide{index}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" '
        f'Target="{name}"/>'
        for index, name in enumerate(order, 1)
    )
    presentation = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<p:presentation xmlns:a="{_A}" xmlns:p="{_P}" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        "<p:sldIdLst>"
        + "".join(f'<p:sldId id="{255 + index}" r:id="rIdSlide{index}"/>' for index in range(1, len(order) + 1))
        + "</p:sldIdLst></p:presentation>"
    )
    return {
        "ppt/presentation.xml": presentation,
        "ppt/_rels/presentation.xml.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + slide_rels
            + "</Relationships>"
        ),
    }


def _write_pptx(path: Path, order: list[str] | None = None) -> None:
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/ppt/slides/slide1.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>'
        '<Override PartName="/ppt/slides/slide2.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>'
        '<Override PartName="/ppt/notesSlides/notesSlide1.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.presentationml.notesSlide+xml"/>'
        "</Types>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId2" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/notesSlide" '
        'Target="../notesSlides/notesSlide1.xml"/>'
        "</Relationships>"
    )
    parts = _presentation_parts(order or ["slides/slide1.xml", "slides/slide2.xml"])
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("ppt/slides/slide1.xml", _slide_xml(["Acme Cloud for Small Firms"]))
        archive.writestr(
            "ppt/slides/slide2.xml",
            _slide_xml(["Invented revenue: |$4.2M ARR", "Ask: $6.83M seed"]),
        )
        archive.writestr("ppt/slides/_rels/slide1.xml.rels", rels)
        archive.writestr("ppt/notesSlides/notesSlide1.xml", _notes_xml())
        for name, xml in parts.items():
            archive.writestr(name, xml)


def _write_inventory(path: Path, count: int) -> None:
    slides = [
        {
            "number": number,
            "headline": f"Invented headline {number}",
            "content_summary": f"Invented summary {number}",
            "visuals": f"Invented visual {number}",
        }
        for number in range(1, count + 1)
    ]
    path.write_text(json.dumps({"slides": slides}), encoding="utf-8")


def _run(*args: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *[str(arg) for arg in args]],
        capture_output=True,
        text=True,
    )


def _invoke(argv: list[object]) -> int:
    previous = sys.argv
    sys.argv = [str(SCRIPT), *[str(arg) for arg in argv]]
    try:
        return int(deck_text.main())
    finally:
        sys.argv = previous


def _front_matter(text: str) -> dict[str, str]:
    assert text.startswith("---\n"), text[:40]
    end = text.index("\n---\n", 4)
    block = text[4:end]
    return dict(line.split(": ", 1) for line in block.splitlines())


def _dummy_pdf(path: Path) -> None:
    path.write_bytes(b"%PDF-1.4\n% invented fixture, readers are monkeypatched\n")


def _long_text() -> str:
    return (
        "Invented accounts retained for the invented cohort across two invented regions "
        "and three invented quarters of measured usage. "
    )


def test_pptx_text_and_notes_land_in_the_notes_block(tmp_path: Path) -> None:
    deck = tmp_path / "deck.pptx"
    _write_pptx(deck)
    inventory = tmp_path / "deck_inventory.json"
    _write_inventory(inventory, 2)
    out = tmp_path / "deck_text.md"

    proc = _run("--deck", deck, "--inventory", inventory, "--run-id", "RID", "-o", out)

    assert proc.returncode == 0, proc.stderr
    body = out.read_text(encoding="utf-8")
    assert "## Slide 1" in body and "## Slide 2" in body
    assert "Acme Cloud for Small Firms" in body
    assert "Invented revenue: $4.2M ARR" in body  # one line per a:p, runs joined
    assert "Ask: $6.83M seed" in body
    assert "Invented headline" not in body  # extracted text wins over the inventory
    before, separator, after = body.partition("Speaker notes:")
    assert separator
    assert _NOTES_TEXT not in before
    assert _NOTES_TEXT in after
    assert body.count("Speaker notes:") == 1
    assert _SLIDE_NUMBER not in body


def test_pptx_slide_order_comes_from_the_presentation_not_the_file_names(tmp_path: Path) -> None:
    deck = tmp_path / "deck.pptx"
    _write_pptx(deck, order=["slides/slide2.xml", "slides/slide1.xml"])
    inventory = tmp_path / "deck_inventory.json"
    _write_inventory(inventory, 2)
    out = tmp_path / "deck_text.md"

    proc = _run("--deck", deck, "--inventory", inventory, "--run-id", "RID", "-o", out)

    assert proc.returncode == 0, proc.stderr
    body = out.read_text(encoding="utf-8")
    before, separator, after = body.partition("## Slide 2")
    slide_one = before.split("## Slide 1", 1)[1]
    assert "Invented revenue: $4.2M ARR" in slide_one  # file slide2 is shown first
    assert "Acme Cloud for Small Firms" not in slide_one
    assert separator
    assert "Acme Cloud for Small Firms" in after  # file slide1 is shown second
    assert _NOTES_TEXT in after  # notes follow their file's slide, whatever its position
    assert _NOTES_TEXT not in before
    assert body.count("Speaker notes:") == 1


def test_inventory_slide_numbers_key_sections_not_list_positions(tmp_path: Path) -> None:
    deck = tmp_path / "deck.pptx"
    _write_pptx(deck)
    inventory = tmp_path / "deck_inventory.json"
    inventory.write_text(
        json.dumps(
            {
                "slides": [
                    {"number": 2, "headline": "Invented headline two", "content_summary": "Invented summary two"},
                    {"number": 5, "headline": "Invented headline five", "content_summary": "Invented summary five"},
                ]
            }
        ),
        encoding="utf-8",
    )
    out = tmp_path / "deck_text.md"

    proc = _run("--deck", deck, "--inventory", inventory, "--run-id", "RID", "-o", out)

    assert proc.returncode == 0, proc.stderr
    body = out.read_text(encoding="utf-8")
    assert "## Slide 2" in body and "## Slide 5" in body
    assert "## Slide 1" not in body and "## Slide 3" not in body
    after_two, _, after_five = body.partition("## Slide 5")
    assert "Invented revenue: $4.2M ARR" in after_two.split("## Slide 2", 1)[1]  # page 2 is extracted
    assert "Invented headline five" in after_five  # page 5 has no text, so the inventory describes it
    receipt = json.loads(proc.stdout)
    assert receipt["pages_source"] == {"2": "extracted", "5": "inventory"}


def test_pdf_image_page_falls_back_to_the_inventory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    deck = tmp_path / "deck.pdf"
    _dummy_pdf(deck)
    inventory = tmp_path / "deck_inventory.json"
    _write_inventory(inventory, 1)
    out = tmp_path / "deck_text.md"
    monkeypatch.setattr(_pdf_pages, "page_texts", lambda _pdf: {1: "  \n\t "})
    monkeypatch.setattr(_pdf_pages, "page_count", lambda _pdf: 1)

    rc = _invoke(["--deck", deck, "--inventory", inventory, "--run-id", "RID", "-o", out])

    captured = capsys.readouterr()
    assert rc == 0
    body = out.read_text(encoding="utf-8")
    assert "Invented headline 1" in body
    assert "Invented summary 1" in body
    assert "Visuals: Invented visual 1" in body
    receipt = json.loads(captured.out)
    assert receipt["source"] == "inventory"
    assert receipt["pages_source"] == {"1": "inventory"}


def test_pdf_mixes_extracted_and_inventory_pages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    deck = tmp_path / "deck.pdf"
    _dummy_pdf(deck)
    inventory = tmp_path / "deck_inventory.json"
    _write_inventory(inventory, 2)
    out = tmp_path / "deck_text.md"
    long_text = _long_text()
    monkeypatch.setattr(_pdf_pages, "page_texts", lambda _pdf: {1: long_text, 2: "short"})
    monkeypatch.setattr(_pdf_pages, "page_count", lambda _pdf: 2)

    rc = _invoke(["--deck", deck, "--inventory", inventory, "--run-id", "RID", "-o", out])

    captured = capsys.readouterr()
    assert rc == 0
    body = out.read_text(encoding="utf-8")
    assert long_text.rstrip() in body
    assert "Invented headline 1" not in body
    assert "Invented headline 2" in body
    receipt = json.loads(captured.out)
    assert receipt["source"] == "mixed"
    assert receipt["pages_source"] == {"1": "extracted", "2": "inventory"}
    assert _front_matter(body)["pages_source"] == "{1: extracted, 2: inventory}"


def test_front_matter_records_the_run_source_pages_and_deck(tmp_path: Path) -> None:
    deck = tmp_path / "deck.pptx"
    _write_pptx(deck)
    inventory = tmp_path / "deck_inventory.json"
    _write_inventory(inventory, 2)
    out = tmp_path / "deck_text.md"

    assert _run("--deck", deck, "--inventory", inventory, "--run-id", "RID", "-o", out).returncode == 0

    body = out.read_text(encoding="utf-8")
    front = _front_matter(body)
    assert front["run_id"] == "RID"
    assert front["source"] == "extracted"
    assert front["pages_source"] == "{1: extracted, 2: extracted}"
    assert front["deck_sha256"] == hashlib.sha256(deck.read_bytes()).hexdigest()
    assert body.endswith("\n")
    assert "\n\n## Slide 1\n\n" in body


def test_receipt_sha_equals_sha256_of_the_written_file(tmp_path: Path) -> None:
    deck = tmp_path / "deck.pptx"
    _write_pptx(deck)
    inventory = tmp_path / "deck_inventory.json"
    _write_inventory(inventory, 2)
    out = tmp_path / "deck_text.md"

    proc = _run("--deck", deck, "--inventory", inventory, "--run-id", "RID", "-o", out)

    assert proc.returncode == 0, proc.stderr
    receipt = json.loads(proc.stdout)
    assert receipt["ok"] is True
    assert receipt["slides"] == 2
    assert receipt["pages_source"] == {"1": "extracted", "2": "extracted"}
    assert receipt["deck_text_sha256"] == _deck_text_file.body_sha256(out.read_bytes())


@pytest.mark.parametrize("case", ["missing_deck", "missing_inventory", "no_slides", "wrong_format"])
def test_each_loud_refusal_leaves_an_existing_output_byte_identical(case: str, tmp_path: Path) -> None:
    deck = tmp_path / "deck.pptx"
    _write_pptx(deck)
    inventory = tmp_path / "deck_inventory.json"
    _write_inventory(inventory, 2)
    if case == "missing_deck":
        deck = tmp_path / "absent.pdf"
    elif case == "missing_inventory":
        inventory = tmp_path / "absent.json"
    elif case == "no_slides":
        inventory = tmp_path / "no_slides.json"
        inventory.write_text('{"company_name": "Invented Co"}', encoding="utf-8")
    elif case == "wrong_format":
        deck = tmp_path / "deck.docx"
        deck.write_text("not a deck", encoding="utf-8")
    out = tmp_path / "deck_text.md"
    sentinel = b"prior good deck text\n"
    out.write_bytes(sentinel)

    proc = _run("--deck", deck, "--inventory", inventory, "--run-id", "RID", "-o", out)

    assert proc.returncode == 1, (case, proc.stdout, proc.stderr)
    diagnostic = json.loads(proc.stdout.strip().splitlines()[-1])
    assert diagnostic["status"] == "rejected"
    assert diagnostic["code"]
    assert proc.stderr.strip()
    assert out.read_bytes() == sentinel


def test_page_count_mismatch_warns_but_still_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    deck = tmp_path / "deck.pdf"
    _dummy_pdf(deck)
    inventory = tmp_path / "deck_inventory.json"
    _write_inventory(inventory, 2)
    out = tmp_path / "deck_text.md"
    long_text = _long_text()
    monkeypatch.setattr(_pdf_pages, "page_texts", lambda _pdf: {1: long_text, 2: long_text})
    monkeypatch.setattr(_pdf_pages, "page_count", lambda _pdf: 3)

    rc = _invoke(["--deck", deck, "--inventory", inventory, "--run-id", "RID", "-o", out])

    captured = capsys.readouterr()
    assert rc == 0
    assert out.is_file()
    receipt = json.loads(captured.out)
    assert receipt["warnings"] == ["PAGE_COUNT_MISMATCH: deck has 3 pages, inventory has 2 slides"]
    assert "PAGE_COUNT_MISMATCH" in captured.err


def test_two_runs_write_identical_bytes(tmp_path: Path) -> None:
    deck = tmp_path / "deck.pptx"
    _write_pptx(deck)
    inventory = tmp_path / "deck_inventory.json"
    _write_inventory(inventory, 2)
    first = tmp_path / "first.md"
    second = tmp_path / "second.md"

    assert _run("--deck", deck, "--inventory", inventory, "--run-id", "RID", "-o", first).returncode == 0
    assert _run("--deck", deck, "--inventory", inventory, "--run-id", "RID", "-o", second).returncode == 0

    assert first.read_bytes() == second.read_bytes()


def _write_text_deck(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def _write_inventory_numbers(path: Path, numbers: list[int]) -> None:
    slides = [
        {
            "number": number,
            "headline": f"Invented headline {number}",
            "content_summary": f"Invented summary {number}",
        }
        for number in numbers
    ]
    path.write_text(json.dumps({"slides": slides}), encoding="utf-8")


def test_text_deck_markers_become_extracted_slides(tmp_path: Path) -> None:
    deck = tmp_path / "deck.txt"
    _write_text_deck(
        deck,
        "SLIDE 1: TITLE\nFoobarbaz Quux — invented tools for invented teams\n\n"
        "SLIDE 2: TRACTION\n412 users paying $6.83M annualized\n",
    )
    inventory = tmp_path / "deck_inventory.json"
    _write_inventory(inventory, 2)
    out = tmp_path / "deck_text.md"

    proc = _run("--deck", deck, "--inventory", inventory, "--run-id", "RID", "-o", out)

    assert proc.returncode == 0, proc.stderr
    body = out.read_text(encoding="utf-8")
    assert "## Slide 1" in body and "## Slide 2" in body
    assert "Foobarbaz Quux — invented tools for invented teams" in body
    assert "412 users paying $6.83M annualized" in body
    assert "Invented headline 1" not in body
    receipt = json.loads(proc.stdout)
    assert receipt["source"] == "extracted"
    assert receipt["pages_source"] == {"1": "extracted", "2": "extracted"}
    assert "warnings" not in receipt


def test_a_short_text_slide_is_still_extracted(tmp_path: Path) -> None:
    deck = tmp_path / "deck.txt"
    _write_text_deck(deck, "SLIDE 1: TITLE\nAsk: $6.83M\n")
    inventory = tmp_path / "deck_inventory.json"
    _write_inventory(inventory, 1)
    out = tmp_path / "deck_text.md"

    proc = _run("--deck", deck, "--inventory", inventory, "--run-id", "RID", "-o", out)

    assert proc.returncode == 0, proc.stderr
    body = out.read_text(encoding="utf-8")
    assert "Ask: $6.83M" in body
    assert "Invented headline 1" not in body
    assert json.loads(proc.stdout)["pages_source"] == {"1": "extracted"}


def test_a_sentence_mentioning_slide_is_not_a_marker(tmp_path: Path) -> None:
    deck = tmp_path / "deck.txt"
    _write_text_deck(
        deck,
        "SLIDE 1: TITLE\nInvented intro\n\nSLIDE 2: TRACTION\nSlide 4 shows our traction of 417 users\n",
    )
    inventory = tmp_path / "deck_inventory.json"
    _write_inventory(inventory, 2)
    out = tmp_path / "deck_text.md"

    proc = _run("--deck", deck, "--inventory", inventory, "--run-id", "RID", "-o", out)

    assert proc.returncode == 0, proc.stderr
    body = out.read_text(encoding="utf-8")
    assert "## Slide 4" not in body
    assert "Slide 4 shows our traction of 417 users" in body.split("## Slide 2", 1)[1]
    assert json.loads(proc.stdout)["pages_source"] == {"1": "extracted", "2": "extracted"}


def test_text_before_the_first_marker_joins_slide_one(tmp_path: Path) -> None:
    deck = tmp_path / "deck.txt"
    _write_text_deck(deck, "Invented preamble line\n\nSLIDE 1: TITLE\nInvented title\n")
    inventory = tmp_path / "deck_inventory.json"
    _write_inventory(inventory, 1)
    out = tmp_path / "deck_text.md"

    proc = _run("--deck", deck, "--inventory", inventory, "--run-id", "RID", "-o", out)

    assert proc.returncode == 0, proc.stderr
    slide_one = out.read_text(encoding="utf-8").split("## Slide 1", 1)[1]
    assert "Invented preamble line" in slide_one
    assert "Invented title" in slide_one


def test_a_duplicate_marker_joins_its_sections_and_warns(tmp_path: Path) -> None:
    deck = tmp_path / "deck.txt"
    _write_text_deck(
        deck,
        "SLIDE 1: TITLE\nInvented first part\n\nSLIDE 2: ASK\nInvented ask\n\n"
        "SLIDE 1: TITLE AGAIN\nInvented second part\n",
    )
    inventory = tmp_path / "deck_inventory.json"
    _write_inventory(inventory, 2)
    out = tmp_path / "deck_text.md"

    proc = _run("--deck", deck, "--inventory", inventory, "--run-id", "RID", "-o", out)

    assert proc.returncode == 0, proc.stderr
    body = out.read_text(encoding="utf-8")
    slide_one = body.split("## Slide 1", 1)[1].split("## Slide 2", 1)[0]
    assert "Invented first part" in slide_one
    assert "Invented second part" in slide_one
    receipt = json.loads(proc.stdout)
    assert receipt["warnings"] == ["DUPLICATE_SLIDE_MARKER: 1"]
    assert "DUPLICATE_SLIDE_MARKER" in proc.stderr


def test_a_missing_marker_falls_back_to_the_inventory_and_mixes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    deck = tmp_path / "deck.txt"
    _write_text_deck(deck, "SLIDE 1: TITLE\nInvented first slide\n")
    inventory = tmp_path / "deck_inventory.json"
    _write_inventory(inventory, 2)
    out = tmp_path / "deck_text.md"

    rc = _invoke(["--deck", deck, "--inventory", inventory, "--run-id", "RID", "-o", out])

    captured = capsys.readouterr()
    assert rc == 0
    body = out.read_text(encoding="utf-8")
    assert "Invented first slide" in body.split("## Slide 1", 1)[1].split("## Slide 2", 1)[0]
    assert "Invented headline 2" in body.split("## Slide 2", 1)[1]
    receipt = json.loads(captured.out)
    assert receipt["source"] == "mixed"
    assert receipt["pages_source"] == {"1": "extracted", "2": "inventory"}
    assert receipt["warnings"] == ["PAGE_COUNT_MISMATCH: deck has 1 slides, inventory has 2 slides"]


def test_a_marked_slide_the_inventory_does_not_know_is_still_written(tmp_path: Path) -> None:
    deck = tmp_path / "deck.txt"
    _write_text_deck(deck, "SLIDE 1: TITLE\nInvented first\n\nSLIDE 7: ASK\nInvented seventh\n")
    inventory = tmp_path / "deck_inventory.json"
    _write_inventory_numbers(inventory, [1])
    out = tmp_path / "deck_text.md"

    proc = _run("--deck", deck, "--inventory", inventory, "--run-id", "RID", "-o", out)

    assert proc.returncode == 0, proc.stderr
    body = out.read_text(encoding="utf-8")
    assert "## Slide 7" in body
    assert "Invented seventh" in body
    receipt = json.loads(proc.stdout)
    assert receipt["source"] == "extracted"
    assert receipt["pages_source"] == {"1": "extracted", "7": "extracted"}


def test_no_markers_at_all_reads_the_inventory_and_warns(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    deck = tmp_path / "deck.txt"
    _write_text_deck(deck, "An invented deck with no slide markers at all.\n")
    inventory = tmp_path / "deck_inventory.json"
    _write_inventory(inventory, 2)
    out = tmp_path / "deck_text.md"

    rc = _invoke(["--deck", deck, "--inventory", inventory, "--run-id", "RID", "-o", out])

    captured = capsys.readouterr()
    assert rc == 0
    body = out.read_text(encoding="utf-8")
    assert "Invented headline 1" in body
    assert "Invented headline 2" in body
    assert "An invented deck with no slide markers at all." not in body
    receipt = json.loads(captured.out)
    assert receipt["source"] == "inventory"
    assert receipt["warnings"] == ["NO_SLIDE_MARKERS"]
    assert _front_matter(body)["warnings"] == "[NO_SLIDE_MARKERS]"


def test_staged_text_deck_sections_are_pasted(tmp_path: Path) -> None:
    deck = tmp_path / "deck.md"
    _write_text_deck(deck, "## Slide 1\nInvented pasted text\n")
    inventory = tmp_path / "deck_inventory.json"
    _write_inventory(inventory, 1)
    out = tmp_path / "deck_text.md"

    proc = _run("--deck", deck, "--inventory", inventory, "--run-id", "RID", "--staged", "-o", out)

    assert proc.returncode == 0, proc.stderr
    receipt = json.loads(proc.stdout)
    assert receipt["source"] == "pasted"
    assert receipt["pages_source"] == {"1": "pasted"}


@pytest.mark.parametrize("name", ["deck.pdf", "deck.pptx"])
def test_staged_on_a_binary_deck_is_refused_without_touching_the_output(name: str, tmp_path: Path) -> None:
    deck = tmp_path / name
    deck.write_bytes(b"invented binary deck")
    inventory = tmp_path / "deck_inventory.json"
    _write_inventory(inventory, 1)
    out = tmp_path / "deck_text.md"
    sentinel = b"prior good deck text\n"
    out.write_bytes(sentinel)

    proc = _run("--deck", deck, "--inventory", inventory, "--run-id", "RID", "--staged", "-o", out)

    assert proc.returncode == 1
    diagnostic = json.loads(proc.stdout.strip().splitlines()[-1])
    assert diagnostic["code"] == "STAGED_FORMAT"
    assert proc.stderr.strip()
    assert out.read_bytes() == sentinel


def test_text_warnings_land_in_the_front_matter(tmp_path: Path) -> None:
    deck = tmp_path / "deck.txt"
    _write_text_deck(deck, "SLIDE 1: TITLE\nInvented first\n\nSLIDE 1: AGAIN\nInvented again\n")
    inventory = tmp_path / "deck_inventory.json"
    _write_inventory(inventory, 1)
    out = tmp_path / "deck_text.md"

    assert _run("--deck", deck, "--inventory", inventory, "--run-id", "RID", "-o", out).returncode == 0

    front = _front_matter(out.read_text(encoding="utf-8"))
    assert front["warnings"] == "[DUPLICATE_SLIDE_MARKER]"
    assert "message" not in front["warnings"]


def test_text_receipt_sha_equals_the_body_hash_of_the_written_file(tmp_path: Path) -> None:
    deck = tmp_path / "deck.txt"
    _write_text_deck(deck, "SLIDE 1: TITLE\nInvented text\n")
    inventory = tmp_path / "deck_inventory.json"
    _write_inventory(inventory, 1)
    out = tmp_path / "deck_text.md"

    proc = _run("--deck", deck, "--inventory", inventory, "--run-id", "RID", "-o", out)

    assert proc.returncode == 0, proc.stderr
    receipt = json.loads(proc.stdout)
    assert receipt["deck_text_sha256"] == _deck_text_file.body_sha256(out.read_bytes())


def test_an_undecodable_text_deck_is_unreadable(tmp_path: Path) -> None:
    deck = tmp_path / "deck.txt"
    deck.write_bytes(b"SLIDE 1\n\xff\xfe invented bytes\n")
    inventory = tmp_path / "deck_inventory.json"
    _write_inventory(inventory, 1)
    out = tmp_path / "deck_text.md"
    sentinel = b"prior good deck text\n"
    out.write_bytes(sentinel)

    proc = _run("--deck", deck, "--inventory", inventory, "--run-id", "RID", "-o", out)

    assert proc.returncode == 1
    assert json.loads(proc.stdout.strip().splitlines()[-1])["code"] == "DECK_UNREADABLE"
    assert out.read_bytes() == sentinel


@pytest.mark.parametrize(
    ("name", "count"),
    [
        ("synthetic-seed-deck.txt", 6),
        ("synthetic-contradiction-deck.txt", 7),
        ("synthetic-numeric-operators-deck.txt", 7),
    ],
)
def test_each_fixture_deck_splits_into_its_slides_with_no_warnings(
    name: str, count: int, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    deck = TESTS / "fixtures" / "decks" / name
    inventory = tmp_path / "deck_inventory.json"
    _write_inventory(inventory, count)
    out = tmp_path / "deck_text.md"

    rc = _invoke(["--deck", deck, "--inventory", inventory, "--run-id", "RID", "-o", out])

    captured = capsys.readouterr()
    assert rc == 0
    body = out.read_text(encoding="utf-8")
    assert [line for line in body.splitlines() if line.startswith("## Slide ")] == [
        f"## Slide {number}" for number in range(1, count + 1)
    ]
    receipt = json.loads(captured.out)
    assert "warnings" not in receipt
    assert receipt["pages_source"] == {str(number): "extracted" for number in range(1, count + 1)}
    assert "warnings" not in _front_matter(body)


def test_a_real_text_layer_pdf_is_extracted(tmp_path: Path) -> None:
    if shutil.which("pdftotext") is None:
        pytest.skip("pdftotext is not available")
    pytest.importorskip("reportlab")
    from reportlab.pdfgen import canvas  # type: ignore[import-untyped]

    deck = tmp_path / "deck.pdf"
    page_one = "Invented page one names the Acme Cloud pilot and the invented retention cohort. "
    page_two = "Invented page two states $4.2M ARR from the invented pilot and 87 retained accounts. "
    pdf = canvas.Canvas(str(deck))
    pdf.setFont("Helvetica", 6)
    pdf.drawString(24, 750, page_one * 2)
    pdf.showPage()
    pdf.drawString(24, 750, page_two * 2)
    pdf.showPage()
    pdf.save()
    inventory = tmp_path / "deck_inventory.json"
    _write_inventory(inventory, 2)
    out = tmp_path / "deck_text.md"

    proc = _run("--deck", deck, "--inventory", inventory, "--run-id", "RID", "-o", out)

    assert proc.returncode == 0, proc.stderr
    body = out.read_text(encoding="utf-8")
    assert "Acme Cloud pilot" in body
    assert "$4.2M ARR" in body
    assert "Invented headline 1" not in body
    receipt = json.loads(proc.stdout)
    assert receipt["source"] == "extracted"
