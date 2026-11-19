"""The console's user guide: screenshots of the real console, docs/GUIDE.md, a PDF.

    python -m gtfs_bench.guide              # screenshots, HTML, PDF
    python -m gtfs_bench.guide --no-shots   # reuse the screenshots

1. **Screenshots**: the console runs headless on a real network (france-live, else the Lyon
   tier) with the real engine, and every tab is captured as SVG in docs/img/. Addresses come
   from a fixed list (no request to Photon), so the guide is the same on every run.
2. **HTML**: docs/GUIDE.md rendered with markdown-it (shipped with Textual), images inline.
3. **PDF**: Microsoft Edge prints the HTML (--headless --print-to-pdf) to docs/guide-console.pdf.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import datetime as dt
import shutil
import subprocess
import sys
from pathlib import Path

from .catalog import BENCHMARK_DIR
from .convert import RAPTOR_DIR

DOCS = BENCHMARK_DIR / "docs"
IMG = DOCS / "img"
GUIDE_MD = DOCS / "GUIDE.md"
GUIDE_HTML = BENCHMARK_DIR / "data" / "tmp" / "guide" / "guide.html"
GUIDE_PDF = DOCS / "guide-console.pdf"
SIZE = (170, 52)
EDGE_PATHS = (Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
              Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"))


class CannedGeocoder:
    """A few real addresses, so the screenshots never depend on Photon being reachable."""

    def __init__(self):
        from .explorer.geocode import Address
        self.addresses = [Address("10 Rue de la République", "69002 Lyon", 45.7655, 4.8358),
                          Address("10 Rue de la République", "69150 Décines-Charpieu", 45.7702, 4.9592),
                          Address("Tour métallique de Fourvière", "Montée Nicolas de Lange, 69005 Lyon", 45.7623, 4.8211)]

    def search(self, text, near=None, limit=6):
        key = text.lower()
        if "fourvi" in key:
            return self.addresses[2:]
        return self.addresses[:2] if "rue" in key else []


async def _shots(out: Path) -> list[Path]:
    from .explorer.app import NETWORK_NAMES, Explorer, reference_day
    from .horizon import Plan

    live = RAPTOR_DIR / "france-live"
    if (live / "horizon.json").exists():
        data, name, plan = live, NETWORK_NAMES["france-live"], Plan.read(live / "horizon.json")
    else:
        data, name, plan = RAPTOR_DIR / "metropole-lyon" / "bench", "Métropole de Lyon", None
    app = Explorer(data, name, xmx="2g", cache_dir=BENCHMARK_DIR / "data" / "tmp" / "explorer",
                   reference_day=reference_day(BENCHMARK_DIR / "results"), geocoder=CannedGeocoder(), plan=plan)
    out.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []

    def shot(stem: str) -> None:
        saved.append(Path(app.save_screenshot(f"{stem}.svg", str(out))))

    async with app.run_test(size=SIZE) as pilot:
        for _ in range(40):
            await pilot.pause(0.05)
        shot("01-chargement")
        for _ in range(900):
            await pilot.pause(0.1)
            if app.index is not None and not app.query_one("#from").disabled:
                break
        await pilot.pause(1.2)
        shot("02-pret")

        a = app.index.search("bellecour")[0]
        b = app.index.search("gare part dieu")[0]
        await pilot.click("#from")
        await pilot.press(*"bellecour")
        await pilot.pause(0.6)
        shot("03-recherche-arret")
        app.choose("from", a)
        await pilot.click("#to")
        await pilot.press(*"10 rue de la republique")
        await pilot.pause(0.8)
        shot("04-recherche-adresse")
        app.choose("to", b)
        await pilot.pause(2.0)
        shot("05-itineraire")

        app.chosen["to"] = None
        app.choose("to", app.geocoder.search("tour fourviere")[0])
        await pilot.pause(2.0)
        shot("06-adresse-carte")

        app.query_one("#map").focus()
        await pilot.press("minus")
        await pilot.pause(0.3)
        shot("07-carte-zoom")
        await pilot.press("f")
        await pilot.pause(0.3)
        shot("08-carte-france")
        await pilot.press("0")

        if plan:
            saturday = next(d for d in app.dates if d.weekday() == 5)
            app.query_one("#day").value = saturday.isoformat()
            await pilot.pause(4.0)
            shot("09-samedi")
        app.query_one("#school").value = False
        await pilot.pause(2.0)
        shot("10-sans-scolaires")
        app.query_one("#school").value = True

        app.action_tab("tab-catalogue")
        catalogue = app.query_one("#catalogue")
        catalogue.query_one("#cat-search").value = "lyon"
        await pilot.pause(0.5)
        catalogue.show("tcl")
        await pilot.pause(0.3)
        shot("11-catalogue")
        app.action_tab("tab-networks")
        await pilot.pause(0.4)
        shot("12-reseaux")
        app.action_tab("tab-actions")
        app.query_one("#actions").select("refresh")
        await pilot.pause(0.4)
        shot("13-actions")
        app.action_tab("tab-settings")
        await pilot.pause(0.4)
        shot("14-parametres")
        app.action_tab("tab-results")
        await pilot.pause(0.6)
        shot("15-resultats")
        results = app.query_one("#results")
        csv_file = next((p for p in results.files if p.name == "engine_memory.csv"), None)
        if csv_file:
            results.show(csv_file)
            await pilot.pause(0.4)
            shot("16-resultats-tableau")
        app.action_tab("tab-help")
        await pilot.pause(0.6)
        shot("17-aide")
    return saved


def screenshots(out: Path = IMG) -> list[Path]:
    return asyncio.run(_shots(out))


CSS = """
@page { size: A4; margin: 16mm 14mm 18mm 14mm; }
body { font-family: 'Segoe UI', system-ui, sans-serif; font-size: 10.5pt; line-height: 1.5; color: #1f1e1b; }
h1 { font-size: 26pt; margin: 0 0 4mm 0; color: #2a78d6; }
h2 { font-size: 16pt; margin-top: 10mm; border-bottom: 2px solid #2a78d6; padding-bottom: 1mm; page-break-after: avoid; }
h3 { font-size: 12.5pt; margin-top: 6mm; page-break-after: avoid; }
p, li { text-align: left; }
code { font-family: 'Cascadia Mono', Consolas, monospace; font-size: 9pt; background: #f1f0ec; padding: 0 2px; border-radius: 3px; }
pre { background: #f1f0ec; padding: 3mm; border-radius: 4px; font-size: 8.5pt; overflow-wrap: anywhere; white-space: pre-wrap; }
pre code { background: none; padding: 0; }
table { border-collapse: collapse; margin: 3mm 0; font-size: 9.5pt; width: 100%; }
th, td { border: 1px solid #d6d4cc; padding: 1.5mm 2mm; vertical-align: top; text-align: left; }
th { background: #eef3fb; }
img { width: 100%; border: 1px solid #c9c8c0; border-radius: 4px; margin: 2mm 0 1mm 0; page-break-inside: avoid; }
blockquote { border-left: 3px solid #eda100; margin: 3mm 0; padding: 1mm 4mm; background: #fdf6e6; }
.cover { text-align: left; margin-top: 30mm; page-break-after: always; }
.cover .sub { font-size: 14pt; color: #555; }
.cover .date { margin-top: 20mm; color: #777; }
"""


def render_html(markdown_path: Path = GUIDE_MD, out: Path = GUIDE_HTML, img_dir: Path = IMG) -> Path:
    """GUIDE.md -> one self-contained HTML file (images inlined), ready to print."""
    from markdown_it import MarkdownIt

    text = markdown_path.read_text(encoding="utf-8")
    html = MarkdownIt("commonmark", {"html": True}).enable("table").render(text)
    for svg in sorted(img_dir.glob("*.svg")):
        data = base64.b64encode(svg.read_bytes()).decode("ascii")
        html = html.replace(f'src="img/{svg.name}"', f'src="data:image/svg+xml;base64,{data}"')
    cover = ("<div class='cover'><h1>Guide de la console</h1><p class='sub'>Benchmark « GTFS France entière » "
             "de raptor-kmp<br>L'itinéraire, les données, la chaîne du notebook, les mesures et les réglages, depuis "
             f"un seul terminal.</p><p class='date'>Dépôt raptor-gtfs-pipeline, dossier <code>benchmark/</code> · "
             f"{dt.date.today():%d/%m/%Y}</p></div>")
    # The cover replaces the Markdown title and its subtitle (kept for the console's Aide tab).
    html = html.split("</h1>", 1)[1].split("</p>", 1)[1] if "</h1>" in html else html
    page = (f"<!doctype html><html lang='fr'><head><meta charset='utf-8'><title>Guide de la console</title>"
            f"<style>{CSS}</style></head><body>{cover}{html}</body></html>")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    return out


def edge() -> Path | None:
    found = shutil.which("msedge")
    if found:
        return Path(found)
    return next((p for p in EDGE_PATHS if p.exists()), None)


def print_pdf(html: Path = GUIDE_HTML, pdf: Path = GUIDE_PDF) -> Path:
    browser = edge()
    if browser is None:
        raise FileNotFoundError("Microsoft Edge not found: open data/tmp/guide/guide.html and print it to PDF")
    pdf.parent.mkdir(parents=True, exist_ok=True)
    profile = html.parent / "edge-profile"
    subprocess.run([str(browser), "--headless", "--disable-gpu", "--no-pdf-header-footer", f"--user-data-dir={profile}",
                    f"--print-to-pdf={pdf}", html.resolve().as_uri()], check=True, timeout=180,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return pdf


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m gtfs_bench.guide", description=__doc__.splitlines()[0])
    parser.add_argument("--no-shots", action="store_true", help="keep the screenshots in docs/img")
    parser.add_argument("--no-pdf", action="store_true", help="HTML only")
    args = parser.parse_args(argv)
    if not args.no_shots:
        shots = screenshots()
        print(f"{len(shots)} screenshots in {IMG}")
    html = render_html()
    print(f"HTML: {html}")
    if not args.no_pdf:
        pdf = print_pdf(html)
        print(f"PDF: {pdf} ({pdf.stat().st_size / 1024**2:.1f} MB, {dt.datetime.now():%H:%M})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
