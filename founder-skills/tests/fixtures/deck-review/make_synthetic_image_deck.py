"""Build `synthetic-image-deck.pdf`: an image-only pitch deck for a fictional company, with no text layer.

Every slide is text drawn onto a picture, so deck review reads it from how the slides look and Step 3.95's
machine read has figures to check: the unit-economics slide states a gross profit that its own revenue and
margin do not produce, so the numbers section keeps that relation and its three figures are in scope.
The company, people and figures are invented. Regenerate with `python3 make_synthetic_image_deck.py`
(needs Pillow with JPEG support); never hand-edit the PDF.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SLIDES = [
    ["Larkspur Kilns (fictional)", "Kiln scheduling for ceramics studios", "Seed round, 2026"],
    ["The problem", "Studios lose a firing a week to", "double-booked kilns and missed cool-downs."],
    ["Traction", "2025 revenue: $1.2M", "Monthly recurring revenue: $100K", "Paying studios: 340"],
    ["Unit economics", "Gross margin: 75%", "2025 gross profit: $690K"],
    ["Market", "Ceramics studios in the US: 18,000", "We start with studios of 2 to 10 kilns."],
    ["The ask", "Raising $2.5M to reach 1,000 studios", "This deck is synthetic test data."],
]


def _font(size: int) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    for name in ("/System/Library/Fonts/Supplemental/Arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def build(out: Path) -> None:
    pages = []
    for lines in SLIDES:
        page = Image.new("RGB", (16 * 80, 9 * 80), "white")  # 16:9
        draw = ImageDraw.Draw(page)
        y = 90
        for i, line in enumerate(lines):
            draw.text((90, y), line, fill="black", font=_font(64 if i == 0 else 46))
            y += 120 if i == 0 else 90
        pages.append(page)
    pages[0].save(out, save_all=True, append_images=pages[1:], resolution=96, quality=70)


if __name__ == "__main__":
    build(Path(__file__).with_name("synthetic-image-deck.pdf"))
