"""Download the latest version of every catalogued feed, and unpack it.

    python -m gtfs_bench.download                    # every included feed
    python -m gtfs_bench.download --feeds tcl,idfm   # some feeds, included or not
    python -m gtfs_bench.download --layer all        # the long-distance layer too
    python -m gtfs_bench.download --force            # ignore what is already on disk
    python -m gtfs_bench.download --register tcl     # a zip placed by hand in data/raw/

Each feed lands in data/raw/<feed_id>.zip and is unpacked into data/extracted/<feed_id>/.
data/raw/manifest.csv records, per feed, what was fetched, from where, its checksum, the
dates its calendar covers, and for a failure what went wrong and what to try.

A second run only downloads what changed: the previous ETag / Last-Modified go out as a
conditional GET, and a 304 keeps the file on disk. Downloads are untrusted files. They are
written to a temporary name, checked to be a zip holding a GTFS feed, and only then moved
into place. Extraction keeps the feed's .txt files and nothing else, flattened to bare file
names, so no entry can be written outside its folder.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import shutil
import sys
import threading
import time
import zipfile
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, fields
from pathlib import Path, PurePosixPath

import requests

from .catalog import BENCHMARK_DIR, read_catalog
from .credentials import CredentialStore, MissingCredentials

DATA_DIR = BENCHMARK_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
EXTRACTED_DIR = DATA_DIR / "extracted"
MANIFEST = RAW_DIR / "manifest.csv"

USER_AGENT = "raptor-gtfs-pipeline-benchmark"
TIMEOUT = (30, 300)  # connect, read
ATTEMPTS = 3
#: Refuse to unpack more than this per feed. IDFM, the largest, is about 1.5 GB unpacked.
MAX_UNCOMPRESSED = 10 * 1024**3
REQUIRED_FILES = ("stops.txt", "routes.txt", "trips.txt", "stop_times.txt")

OK_STATUSES = ("downloaded", "not_modified", "manual")


@dataclass
class FeedResult:
    feed_id: str
    status: str = "failed"          # downloaded | not_modified | manual | failed
    http_status: int | None = None
    url: str = ""
    final_url: str = ""
    size: int | None = None
    sha256: str = ""
    etag: str = ""
    last_modified: str = ""
    downloaded_at: str = ""
    service_start: str = ""
    service_end: str = ""
    validity_source: str = ""
    files: str = ""
    error: str = ""
    hint: str = ""

    @property
    def ok(self) -> bool:
        return self.status in OK_STATUSES


MANIFEST_COLUMNS = [f.name for f in fields(FeedResult)]


class DownloadError(Exception):
    def __init__(self, message: str, hint: str = "", http_status: int | None = None):
        super().__init__(message)
        self.hint = hint
        self.http_status = http_status


# ── Checking what came back ──────────────────────────────────────────────────────────


def check_payload(head: bytes, content_type: str = "") -> None:
    """Raise unless the first bytes of a response are a zip."""
    if head.startswith(b"PK\x03\x04"):
        return
    sniff = head[:512].lstrip().lower()
    if sniff.startswith((b"<!doctype html", b"<html")) or "html" in content_type.lower():
        raise DownloadError(
            "got an HTML page instead of a zip",
            hint="A login page or a download-confirmation page (Google Drive does this for "
                 "large files). Open the URL in a browser to see which.",
        )
    raise DownloadError(
        f"not a zip (starts with {head[:8]!r}, content-type {content_type or 'unknown'})",
        hint="The producer may have changed format or URL: run `python -m gtfs_bench.catalog check`.",
    )


def _member_path(name: str) -> PurePosixPath:
    # Zips written on Windows may use backslashes; treat them as separators so that a
    # name like "..\\..\\x.txt" cannot hide a parent reference from PurePosixPath.
    return PurePosixPath(name.replace("\\", "/"))


def _gtfs_root(names: list[str]) -> PurePosixPath | None:
    """The folder holding stops.txt, if exactly one does."""
    roots = {_member_path(n).parent for n in names if _member_path(n).name.lower() == "stops.txt"}
    return roots.pop() if len(roots) == 1 else None


def unwrap_nested_zip(path: Path, depth: int = 2) -> bool:
    """Replace a zip that only wraps another zip (Mobigo Jura) by the inner one."""
    unwrapped = False
    for _ in range(depth):
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if _gtfs_root(names) is not None:
                return unwrapped
            inner = [n for n in names if n.lower().endswith(".zip")]
            if len(inner) != 1:
                return unwrapped
            data = archive.read(inner[0])
        if not data.startswith(b"PK\x03\x04"):
            return unwrapped
        path.write_bytes(data)
        unwrapped = True
    return unwrapped


def check_gtfs(path: Path) -> None:
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            bad = archive.testzip()
    except zipfile.BadZipFile as error:
        raise DownloadError(f"corrupt zip: {error}", hint="Retry; the transfer may have been cut short.")
    if bad is not None:
        raise DownloadError(f"corrupt zip member {bad}", hint="Retry; the transfer may have been cut short.")
    root = _gtfs_root(names)
    if root is None:
        raise DownloadError("no single stops.txt in the zip", hint="Not a GTFS feed, or several feeds in one zip.")
    present = {_member_path(n).name.lower() for n in names if _member_path(n).parent == root}
    missing = [f for f in REQUIRED_FILES if f not in present]
    if missing:
        raise DownloadError(f"GTFS files missing: {', '.join(missing)}", hint="The feed is incomplete at the source.")


# ── Unpacking ────────────────────────────────────────────────────────────────────────


def extract_feed(zip_path: Path, dest: Path) -> list[str]:
    """Unpack the feed's .txt files into `dest`, flat and lower-cased. Returns their names."""
    with zipfile.ZipFile(zip_path) as archive:
        members = [m for m in archive.infolist() if not m.is_dir() and m.filename.lower().endswith(".txt")]
        root = _gtfs_root([m.filename for m in members])
        if root is None:
            raise DownloadError("no single stops.txt in the zip")
        chosen = [m for m in members if _member_path(m.filename).parent == root]
        total = sum(m.file_size for m in chosen)
        if total > MAX_UNCOMPRESSED:
            raise DownloadError(f"feed unpacks to {total / 1024**3:.1f} GB, over the {MAX_UNCOMPRESSED / 1024**3:.0f} GB limit")
        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True)
        base = dest.resolve()
        written = []
        for member in chosen:
            name = _member_path(member.filename).name.lower()
            target = (dest / name).resolve()
            if target.parent != base or name in ("", ".", ".."):
                raise DownloadError(f"refusing zip entry {member.filename!r}")
            with archive.open(member) as source, target.open("wb") as sink:
                shutil.copyfileobj(source, sink, length=1024 * 1024)
            written.append(name)
    return sorted(written)


# ── Calendar coverage ────────────────────────────────────────────────────────────────


def _rows(folder: Path, name: str):
    path = folder / name
    if not path.exists():
        return
    with path.open(encoding="utf-8-sig", errors="replace", newline="") as handle:
        for row in csv.DictReader(handle):
            yield {(k or "").strip(): (v or "").strip() for k, v in row.items()}


def _iso(value: str) -> str | None:
    try:
        return dt.datetime.strptime(value, "%Y%m%d").date().isoformat()
    except ValueError:
        return None


def service_window(folder: Path) -> tuple[str, str, str]:
    """(first, last, source) dates the feed's calendars give service on, ISO formatted.

    calendar.txt spans and calendar_dates.txt additions are unioned. feed_info.txt is only
    the fallback: it states what the producer intends, not what the calendars hold.
    """
    dates: list[str] = []
    sources = []
    for row in _rows(folder, "calendar.txt"):
        start, end = _iso(row.get("start_date", "")), _iso(row.get("end_date", ""))
        if start and end:
            dates += [start, end]
            if "calendar" not in sources:
                sources.append("calendar")
    for row in _rows(folder, "calendar_dates.txt"):
        if row.get("exception_type") == "1":
            day = _iso(row.get("date", ""))
            if day:
                dates.append(day)
                if "calendar_dates" not in sources:
                    sources.append("calendar_dates")
    if dates:
        return min(dates), max(dates), "+".join(sources)
    for row in _rows(folder, "feed_info.txt"):
        start, end = _iso(row.get("feed_start_date", "")), _iso(row.get("feed_end_date", ""))
        if start or end:
            return start or "", end or "", "feed_info"
    return "", "", "none"


# ── Fetching ─────────────────────────────────────────────────────────────────────────

_local = threading.local()


def _session() -> requests.Session:
    session = getattr(_local, "session", None)
    if session is None:
        session = requests.Session()
        session.headers["User-Agent"] = USER_AGENT
        _local.session = session
    return session


def _hint_for_status(status: int, authenticated: bool) -> str:
    if status in (401, 403):
        if authenticated:
            return "Credentials refused: check the values in benchmark/.env (see .env.example)."
        return "The source now asks for authentication: add an `auth` key to the catalogue row."
    if status in (404, 410):
        return "The file moved or was withdrawn: run `python -m gtfs_bench.catalog check` and update the url."
    if status == 429:
        return "Rate limited: retry later, or with fewer --workers."
    if status >= 500:
        return "Server error at the producer: retry later."
    return ""


def _get(url: str, headers: dict, auth) -> requests.Response:
    last_error: Exception | None = None
    for attempt in range(1, ATTEMPTS + 1):
        try:
            response = _session().get(url, headers=headers, auth=auth, stream=True, timeout=TIMEOUT)
            if response.status_code in (429, 500, 502, 503, 504) and attempt < ATTEMPTS:
                response.close()
                time.sleep(5 * attempt)
                continue
            return response
        except requests.exceptions.SSLError as error:
            raise DownloadError(
                f"TLS error: {error.__class__.__name__}",
                hint="The producer's certificate is not accepted. Try the PAN url of the resource, or report it.",
            )
        except (requests.ConnectionError, requests.Timeout) as error:
            last_error = error
            if attempt < ATTEMPTS:
                time.sleep(5 * attempt)
    raise DownloadError(
        f"{last_error.__class__.__name__} after {ATTEMPTS} attempts",
        hint="Slow or unreachable server: retry, or with --workers 1.",
    )


def fetch(row: dict, previous: FeedResult | None, credentials: CredentialStore, force: bool = False,
          raw_dir: Path = RAW_DIR) -> FeedResult:
    """Download one feed into raw_dir/<feed_id>.zip. Never raises: failures are in the result."""
    feed_id, url = row["feed_id"], row["url"]
    target = raw_dir / f"{feed_id}.zip"
    result = FeedResult(feed_id=feed_id, url=url, downloaded_at=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"))
    partial = target.with_name(target.name + ".part")
    try:
        auth = credentials.get(row["auth"]).as_basic_auth() if row.get("auth") else None
        headers = {}
        if not force and target.exists() and previous is not None and previous.ok:
            if previous.etag:
                headers["If-None-Match"] = previous.etag
            if previous.last_modified:
                headers["If-Modified-Since"] = previous.last_modified
        response = _get(url, headers, auth)
        with response:
            result.http_status = response.status_code
            result.final_url = response.url
            if response.status_code == 304 and previous is not None:
                kept = asdict(previous)
                kept.update(status="not_modified", http_status=304, downloaded_at=result.downloaded_at, error="", hint="")
                return FeedResult(**kept)
            if response.status_code >= 400:
                raise DownloadError(f"HTTP {response.status_code}", _hint_for_status(response.status_code, auth is not None),
                                    response.status_code)
            result.etag = response.headers.get("ETag", "")
            result.last_modified = response.headers.get("Last-Modified", "")
            digest, size, head = hashlib.sha256(), 0, b""
            raw_dir.mkdir(parents=True, exist_ok=True)
            with partial.open("wb") as sink:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if not chunk:
                        continue
                    if not head:
                        head = chunk[:1024]
                        check_payload(head, response.headers.get("Content-Type", ""))
                    digest.update(chunk)
                    size += len(chunk)
                    sink.write(chunk)
            if size == 0:
                raise DownloadError("empty response", hint="Retry later; the producer served nothing.")
        if unwrap_nested_zip(partial):
            data = partial.read_bytes()
            digest, size = hashlib.sha256(data), len(data)
        check_gtfs(partial)
        partial.replace(target)
        result.status, result.size, result.sha256 = "downloaded", size, digest.hexdigest()
        return result
    except MissingCredentials as error:
        result.error, result.hint = str(error), "Fill benchmark/.env from .env.example."
    except DownloadError as error:
        result.error, result.hint = str(error), error.hint
        result.http_status = error.http_status or result.http_status
    except Exception as error:  # a broken feed must not stop the other 200
        result.error, result.hint = f"{error.__class__.__name__}: {error}", ""
    if partial.exists():
        partial.unlink()
    return result


# ── Manifest ─────────────────────────────────────────────────────────────────────────


def read_manifest(path: Path = MANIFEST) -> dict[str, FeedResult]:
    if not path.exists():
        return {}
    results = {}
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            values = {k: row.get(k, "") for k in MANIFEST_COLUMNS}
            values["http_status"] = int(values["http_status"]) if values["http_status"] else None
            values["size"] = int(values["size"]) if values["size"] else None
            results[row["feed_id"]] = FeedResult(**values)
    return results


def write_manifest(results: dict[str, FeedResult], path: Path = MANIFEST) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANIFEST_COLUMNS)
        writer.writeheader()
        for feed_id in sorted(results):
            writer.writerow(asdict(results[feed_id]))
    temporary.replace(path)


# ── Running it all ───────────────────────────────────────────────────────────────────


def select_rows(catalog: list[dict], feeds: list[str] | None = None, layer: str = "regional") -> list[dict]:
    if feeds:
        wanted = set(feeds)
        unknown = wanted - {r["feed_id"] for r in catalog}
        if unknown:
            raise SystemExit(f"unknown feed_id: {', '.join(sorted(unknown))}")
        return [r for r in catalog if r["feed_id"] in wanted]
    return [r for r in catalog if r["include"] and (layer == "all" or r["layer"] == layer)]


def finish(result: FeedResult, extract: bool, raw_dir: Path = RAW_DIR, extracted_dir: Path = EXTRACTED_DIR) -> FeedResult:
    """Unpack a fetched feed (if needed) and read its calendar coverage."""
    if not result.ok:
        return result
    dest = extracted_dir / result.feed_id
    try:
        if extract and (result.status == "downloaded" or not (dest / "stops.txt").exists()):
            result.files = " ".join(extract_feed(raw_dir / f"{result.feed_id}.zip", dest))
        if (dest / "stops.txt").exists():
            result.service_start, result.service_end, result.validity_source = service_window(dest)
    except Exception as error:
        result.status, result.error = "failed", f"extraction: {error}"
        result.hint = "The zip passed the checks but could not be unpacked."
    return result


def download_all(rows: list[dict], credentials: CredentialStore | None = None, workers: int = 6,
                 force: bool = False, extract: bool = True, progress=print,
                 raw_dir: Path = RAW_DIR, extracted_dir: Path = EXTRACTED_DIR,
                 manifest: Path = MANIFEST) -> list[FeedResult]:
    """Fetch every row (one request per distinct URL), unpack, and update the manifest."""
    credentials = credentials or CredentialStore()
    previous = read_manifest(manifest)
    by_url: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_url[row["url"]].append(row)

    results: dict[str, FeedResult] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(fetch, group[0], previous.get(group[0]["feed_id"]), credentials, force, raw_dir): group
            for group in by_url.values()
        }
        for done, future in enumerate(as_completed(futures), 1):
            group = futures[future]
            first = finish(future.result(), extract, raw_dir, extracted_dir)
            results[first.feed_id] = first
            # Feeds sharing a URL (sncf-ter and sncf-grandes-lignes) share one download.
            for other in group[1:]:
                copy = FeedResult(**{**asdict(first), "feed_id": other["feed_id"]})
                if first.ok:
                    shutil.copyfile(raw_dir / f"{first.feed_id}.zip", raw_dir / f"{other['feed_id']}.zip")
                    copy = finish(copy, extract, raw_dir, extracted_dir)
                results[other["feed_id"]] = copy
            size = f"{first.size / 1024**2:7.1f} MB" if first.size else "         -"
            progress(f"[{done:>3}/{len(futures)}] {first.status:<12} {size}  {first.feed_id}"
                     + (f"  — {first.error}" if first.error else ""))

    merged = {**previous, **results}
    write_manifest(merged, manifest)
    return [results[r["feed_id"]] for r in rows]


def register_local(feed_id: str, raw_dir: Path = RAW_DIR, extracted_dir: Path = EXTRACTED_DIR,
                   manifest: Path = MANIFEST) -> FeedResult:
    """Record a zip someone placed in raw_dir by hand (a source the script cannot reach).

    It goes through the same checks as a download, is unpacked afresh, and is marked
    `manual` so the manifest says it was not fetched by the script. A later download run
    replaces it only with --force: the conditional GET has no ETag to send for it.
    """
    path = raw_dir / f"{feed_id}.zip"
    result = FeedResult(feed_id=feed_id, url="", final_url=str(path),
                        downloaded_at=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"))
    try:
        if not path.exists():
            raise DownloadError(f"{path} does not exist", hint=f"Put the feed's zip at {path}.")
        unwrap_nested_zip(path)
        check_gtfs(path)
        data = path.read_bytes()
        # Unpacked afresh even if a folder is there: the same rules as for any download.
        result.files = " ".join(extract_feed(path, extracted_dir / feed_id))
        result.service_start, result.service_end, result.validity_source = service_window(extracted_dir / feed_id)
        result.status, result.size, result.sha256 = "manual", len(data), hashlib.sha256(data).hexdigest()
    except DownloadError as error:
        result.status, result.error, result.hint = "failed", str(error), error.hint
    merged = read_manifest(manifest)
    merged[feed_id] = result
    write_manifest(merged, manifest)
    return result


def summarize(results: list[FeedResult]) -> str:
    lines = []
    counts = defaultdict(int)
    for r in results:
        counts[r.status] += 1
    total = sum(r.size or 0 for r in results if r.ok)
    lines.append(", ".join(f"{n} {status}" for status, n in sorted(counts.items()))
                 + f" — {total / 1024**3:.2f} GB on disk")
    failed = [r for r in results if not r.ok]
    for r in failed:
        lines.append(f"  FAILED {r.feed_id}: {r.error}")
        if r.hint:
            lines.append(f"         → {r.hint}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m gtfs_bench.download", description=__doc__.splitlines()[0])
    parser.add_argument("--feeds", help="comma-separated feed_ids (included or not)")
    parser.add_argument("--layer", choices=["regional", "all"], default="regional")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--force", action="store_true", help="download even if unchanged")
    parser.add_argument("--no-extract", action="store_true")
    parser.add_argument("--prompt", action="store_true", help="ask for missing credentials")
    parser.add_argument("--register", metavar="FEED_ID",
                        help="record a zip placed by hand at data/raw/<FEED_ID>.zip instead of downloading")
    args = parser.parse_args(argv)

    if args.register:
        result = register_local(args.register)
        print(summarize([result]))
        return 0 if result.ok else 1

    rows = select_rows(read_catalog(), args.feeds.split(",") if args.feeds else None, args.layer)
    results = download_all(rows, CredentialStore(interactive=args.prompt), workers=args.workers,
                           force=args.force, extract=not args.no_extract)
    print(summarize(results))
    return 0 if all(r.ok for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
