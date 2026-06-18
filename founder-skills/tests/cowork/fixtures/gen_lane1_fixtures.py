# /// script
# requires-python = ">=3.11"
# dependencies = ["reportlab>=4"]
# ///
"""Generate synthetic Lane-1 instrument PDFs for the cap-table cowork-harness scenarios.

Source text is the SYNTHETIC cap-table-eval fixtures (ACMECORP / Foobar placeholders, invented
numbers) — never real founder/company data. Run: `uv run gen_lane1_fixtures.py`.
Outputs land next to this script (committed fixtures).
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas

HERE = Path(__file__).resolve().parent
EVAL = HERE.parent.parent / "fixtures" / "cap-table-eval"

# (source .txt in cap-table-eval, output PDF name)
DOCS = [
    ("template_blank_exclusivity__source.txt", "term_sheet_blank_exclusivity.pdf"),
    ("cap_plus_discount_clean__source.txt", "safe_cap_plus_discount.pdf"),
]


def txt_to_pdf(src: Path, dst: Path) -> None:
    text = src.read_text(encoding="utf-8")
    c = canvas.Canvas(str(dst), pagesize=LETTER)
    width, height = LETTER
    c.setFont("Courier", 10)
    x, y = inch, height - inch
    leading = 13
    for raw in text.splitlines():
        # preserve the literal blank (e.g. "of  days") — do not collapse whitespace
        c.drawString(x, y, raw)
        y -= leading
        if y < inch:
            c.showPage()
            c.setFont("Courier", 10)
            y = height - inch
    c.showPage()
    c.save()


def main() -> None:
    for src_name, dst_name in DOCS:
        src = EVAL / src_name
        dst = HERE / dst_name
        if not src.exists():
            raise SystemExit(f"missing source fixture: {src}")
        txt_to_pdf(src, dst)
        print(f"wrote {dst.relative_to(HERE.parent.parent.parent)} ({dst.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
