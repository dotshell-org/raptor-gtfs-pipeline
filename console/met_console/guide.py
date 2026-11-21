"""The console's user guide: screenshots of the real console, docs/GUIDE.md, a PDF.

    python -m met_console.guide              # screenshots, HTML, PDF
    python -m met_console.guide --no-shots   # reuse the screenshots

1. **Screenshots**: the console runs headless on the installed version (console/data) with the
   real engine, and every tab is captured as SVG in docs/img/. Addresses come from a fixed list
   (no request to Photon). The Mise à jour shots install the server's latest version for real,
   into a temporary folder (about 45 MB downloaded), so they show a real update.
2. **HTML**: docs/GUIDE.md rendered with markdown-it (shipped with Textual), images inline.
3. **PDF**: Microsoft Edge prints the HTML (--headless --print-to-pdf) to docs/guide-console.pdf.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import datetime as dt
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .paths import DEFAULT_DATA_DIR, DOCS_DIR

IMG = DOCS_DIR / "img"
GUIDE_MD = DOCS_DIR / "GUIDE.md"
GUIDE_PDF = DOCS_DIR / "guide-console.pdf"
SIZE = (170, 52)
EDGE_PATHS = (Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
              Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"))


class CannedGeocoder:
    """A few real addresses, so the screenshots never depend on Photon being reachable."""

    def __init__(self):
        from .geocode import Address
        self.addresses = [Address("10 Rue de la République", "69002 Lyon", 45.7655, 4.8358),
                          Address("10 Rue de la République", "69150 Décines-Charpieu", 45.7702, 4.9592),
                          Address("Tour métallique de Fourvière", "Montée Nicolas de Lange, 69005 Lyon", 45.7623, 4.8211)]

    def search(self, text, near=None, limit=6):
        key = text.lower()
        if "fourvi" in key:
            return self.addresses[2:]
        return self.addresses[:2] if "rue" in key else []


async def wait_ready(app, pilot, seconds: float = 120) -> None:
    for _ in range(int(seconds * 10)):
        await pilot.pause(0.1)
        if app.index is not None and not app.query_one("#from").disabled:
            return
    raise RuntimeError("the console never got ready")


async def _route_shots(data: Path, shot) -> None:
    from .app import Explorer

    app = Explorer(data, geocoder=CannedGeocoder())
    if app.installed is None:
        raise RuntimeError(f"no version installed in {data}: start the console once and install one")
    shot.app = app
    async with app.run_test(size=SIZE) as pilot:
        for _ in range(40):
            await pilot.pause(0.05)
        shot("01-chargement")
        await wait_ready(app, pilot)
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

        saturday = next((d for d in app.dates if d.weekday() == 5 and d != app.day), None)
        if saturday:
            app.query_one("#day").value = saturday.isoformat()
            await pilot.pause(4.0)
            shot("09-samedi")
        app.query_one("#school").value = False
        await pilot.pause(2.0)
        shot("10-sans-scolaires")
        app.query_one("#school").value = True
        await pilot.pause(1.0)

        app.action_tab("tab-data")
        await pilot.pause(0.6)
        shot("14-donnees")
        data_pane = app.query_one("#data")
        data_pane.query_one("#src-search").value = "mobilit"
        await pilot.pause(0.4)
        shot("15-donnees-sources")
        app.action_tab("tab-settings")
        await pilot.pause(0.4)
        shot("16-parametres")
        app.action_tab("tab-help")
        await pilot.pause(0.6)
        shot("17-aide")


async def _update_shots(data: Path, shot) -> None:
    """A real installation from the official delivery, into a temporary folder."""
    from .app import Explorer

    scratch = Path(tempfile.mkdtemp(prefix="met-console-guide-"))
    try:
        if (data / "cache").exists():
            shutil.copytree(data / "cache", scratch / "cache")
        app = Explorer(scratch, geocoder=CannedGeocoder())
        shot.app = app
        async with app.run_test(size=SIZE) as pilot:
            update = app.query_one("#update")
            for _ in range(300):
                await pilot.pause(0.1)
                if update.running is None and update.latest is not None:
                    break
            shot("11-mise-a-jour")
            update.start(check=False)
            for _ in range(600):
                await pilot.pause(0.1)
                if update.progress and update.progress[0] > update.progress[1] * 0.4:
                    break
            shot("12-mise-a-jour-en-cours")
            for _ in range(1800):
                await pilot.pause(0.1)
                if update.running is None:
                    break
            await pilot.pause(1.0)
            shot("13-mise-a-jour-bilan")
            await wait_ready(app, pilot)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def screenshots(data: Path = DEFAULT_DATA_DIR, out: Path = IMG, update: bool = True) -> list[Path]:
    # The guide shows the console in colour, whatever this terminal asks for (Textual reads it).
    os.environ.pop("NO_COLOR", None)
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.svg"):
        old.unlink()
    saved: list[Path] = []

    def shot(stem: str) -> None:
        saved.append(Path(shot.app.save_screenshot(f"{stem}.svg", str(out))))

    asyncio.run(_route_shots(data, shot))
    if update:
        asyncio.run(_update_shots(data, shot))
    return saved


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


def render_html(markdown_path: Path = GUIDE_MD, out: Path | None = None, img_dir: Path = IMG) -> Path:
    """GUIDE.md -> one self-contained HTML file (images inlined), ready to print."""
    from markdown_it import MarkdownIt

    out = out or Path(tempfile.gettempdir()) / "met-console-guide" / "guide.html"
    text = markdown_path.read_text(encoding="utf-8")
    html = MarkdownIt("commonmark", {"html": True}).enable("table").render(text)
    for svg in sorted(img_dir.glob("*.svg")):
        data = base64.b64encode(svg.read_bytes()).decode("ascii")
        html = html.replace(f'src="img/{svg.name}"', f'src="data:image/svg+xml;base64,{data}"')
    cover = ("<div class='cover'><h1>Guide de la console</h1><p class='sub'>france-live dans un terminal<br>"
             "Les itinéraires, les mises à jour par différences et les données de la livraison officielle.</p>"
             f"<p class='date'>Dépôt raptor-gtfs-pipeline, dossier <code>console/</code> · {dt.date.today():%d/%m/%Y}</p></div>")
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


def print_pdf(html: Path, pdf: Path = GUIDE_PDF) -> Path:
    browser = edge()
    if browser is None:
        raise FileNotFoundError(f"Microsoft Edge not found: open {html} and print it to PDF")
    pdf.parent.mkdir(parents=True, exist_ok=True)
    profile = html.parent / "edge-profile"
    subprocess.run([str(browser), "--headless", "--disable-gpu", "--no-pdf-header-footer", f"--user-data-dir={profile}",
                    f"--print-to-pdf={pdf}", html.resolve().as_uri()], check=True, timeout=180,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return pdf


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m met_console.guide", description=__doc__.splitlines()[0])
    parser.add_argument("--no-shots", action="store_true", help="keep the screenshots in docs/img")
    parser.add_argument("--no-update", action="store_true", help="no real installation for the Mise à jour shots")
    parser.add_argument("--no-pdf", action="store_true", help="HTML only")
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA_DIR, help="the console's data folder")
    args = parser.parse_args(argv)
    if not args.no_shots:
        shots = screenshots(args.data.resolve(), update=not args.no_update)
        print(f"{len(shots)} screenshots in {IMG}")
    html = render_html()
    print(f"HTML: {html}")
    if not args.no_pdf:
        pdf = print_pdf(html)
        print(f"PDF: {pdf} ({pdf.stat().st_size / 1024**2:.1f} MB, {dt.datetime.now():%H:%M})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
