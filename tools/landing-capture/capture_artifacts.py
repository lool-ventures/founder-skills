#!/usr/bin/env python3
"""Capture the gallery stills (M3-M8) from the generated skill reports.

    uv run --with playwright python tools/landing-capture/capture_artifacts.py \
        --sources artifacts/landing-capture-review/sources \
        --out assets/landing

Every intermediate goes to a temp dir outside the repo; the ONLY thing written
inside the repo is `--out`, which holds the eight final assets. Playwright's
screenshot path defaults to the process CWD, so every path here is absolute —
a bare filename drops PNGs at the repo root, which has happened before.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from targets import DPR, TARGETS, VIEWPORT  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parents[2]


def guard_workdir(work: pathlib.Path) -> None:
    """Refuse to scribble intermediates into the repo, even if asked to."""
    try:
        work.resolve().relative_to(REPO)
    except ValueError:
        return
    sys.exit(f"work dir {work} is inside the repo; intermediates must live outside it")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", required=True, help="dir of <slot>.html reports")
    ap.add_argument("--out", required=True, help="dir for the final PNGs (inside the repo)")
    ap.add_argument("--work-dir", default=None)
    ap.add_argument("--port", type=int, default=8792)
    ap.add_argument("--only", default=None, help="capture a single slot")
    args = ap.parse_args()

    work = pathlib.Path(args.work_dir or tempfile.mkdtemp(prefix="fs-landing-"))
    guard_workdir(work)
    work.mkdir(parents=True, exist_ok=True)
    out = pathlib.Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    sources = pathlib.Path(args.sources).resolve()

    from playwright.sync_api import sync_playwright

    srv = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(args.port), "--bind", "127.0.0.1"],
        cwd=sources,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        import time

        time.sleep(1.2)
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(
                viewport={"width": VIEWPORT[0], "height": VIEWPORT[1]},
                device_scale_factor=DPR,
            )
            for slot, t in TARGETS.items():
                if args.only and slot != args.only:
                    continue
                page.goto(f"http://127.0.0.1:{args.port}/{t['file']}", wait_until="networkidle")
                found = page.evaluate(
                    """(a) => {
                        const hs = [...document.querySelectorAll('h1,h2,h3')];
                        const h = hs.find(x => x.textContent.trim().toLowerCase().includes(a));
                        if (!h) return null;
                        return Math.round(h.getBoundingClientRect().top + window.scrollY);
                    }""",
                    t["anchor"].lower(),
                )
                if found is None:
                    print(f"  !! {slot}: anchor {t['anchor']!r} NOT FOUND — template drifted")
                    continue
                page.evaluate("(y) => window.scrollTo(0, y)", max(0, found - t["offset"]))
                page.wait_for_timeout(450)
                dest = out / f"artifact-{slot}.png"
                page.screenshot(path=str(dest))  # absolute, always
                print(f"  {slot:<26} anchor@{found:<5} -> {dest.name}")
            browser.close()
    finally:
        srv.terminate()

    # compress in place; line-art reports quantise very well
    for p in sorted(out.glob("artifact-*.png")):
        before = p.stat().st_size
        subprocess.run(["pngquant", "--force", "--quality", "65-90", "--output", str(p), str(p)], check=False)
        subprocess.run(["oxipng", "-o", "4", "-q", str(p)], check=False)
        print(f"  {p.name:<44} {before / 1024:6.0f} KB -> {p.stat().st_size / 1024:6.0f} KB")

    print(f"\nintermediates: {work}")


if __name__ == "__main__":
    main()
