"""Download behaviour against a local HTTP server: no network, no real feed."""

import base64
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from gtfs_bench.credentials import CredentialStore
from gtfs_bench.download import (
    DownloadError,
    download_all,
    extract_feed,
    read_manifest,
    service_window,
)
from tests.gtfs_fixtures import MINIMAL_FEED, feed_zip, zip_bytes

FEED = feed_zip()
ROUTES = {
    "/feed.zip": FEED,
    "/nested.zip": zip_bytes({"jura/outer.zip": FEED}),
    "/sub.zip": feed_zip("GTFS_2026/"),
    "/notgtfs.zip": zip_bytes({"readme.txt": "hello"}),
    "/html": b"<!DOCTYPE html><html><body>Please sign in</body></html>",
}
BASIC = "Basic " + base64.b64encode(b"alice:s3cret").decode()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path == "/private.zip":
            if self.headers.get("Authorization") != BASIC:
                self.send_response(401)
                self.send_header("WWW-Authenticate", 'Basic realm="test"')
                self.end_headers()
                return
            body = FEED
        elif self.path in ROUTES:
            body = ROUTES[self.path]
        else:
            self.send_response(404)
            self.end_headers()
            return
        if self.path == "/feed.zip" and self.headers.get("If-None-Match") == '"v1"':
            self.send_response(304)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html" if self.path == "/html" else "application/zip")
        self.send_header("Content-Length", str(len(body)))
        if self.path == "/feed.zip":
            self.send_header("ETag", '"v1"')
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture(scope="module")
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


@pytest.fixture
def dirs(tmp_path):
    return dict(raw_dir=tmp_path / "raw", extracted_dir=tmp_path / "extracted", manifest=tmp_path / "raw" / "manifest.csv")


def row(feed_id, url, auth=""):
    return {"feed_id": feed_id, "url": url, "auth": auth}


def run(rows, dirs, credentials=None):
    return download_all(rows, credentials or CredentialStore(None, environ={}), workers=2,
                        progress=lambda line: None, **dirs)


def test_download_extract_and_read_calendar_coverage(server, dirs):
    [result] = run([row("demo", f"{server}/feed.zip")], dirs)
    assert result.status == "downloaded", result.error
    assert result.etag == '"v1"' and result.size == len(FEED) and len(result.sha256) == 64
    assert (dirs["raw_dir"] / "demo.zip").read_bytes() == FEED
    assert set(result.files.split()) == set(MINIMAL_FEED)
    # calendar.txt spans 2 Nov - 18 Dec; calendar_dates adds 19 Dec.
    assert (result.service_start, result.service_end) == ("2026-11-02", "2026-12-19")
    assert read_manifest(dirs["manifest"])["demo"].sha256 == result.sha256


def test_unchanged_feed_is_not_downloaded_again(server, dirs):
    run([row("demo", f"{server}/feed.zip")], dirs)
    [again] = run([row("demo", f"{server}/feed.zip")], dirs)
    assert again.status == "not_modified" and again.http_status == 304
    assert again.service_end == "2026-12-19"
    assert (dirs["raw_dir"] / "demo.zip").exists()


def test_zip_inside_a_zip_is_unwrapped(server, dirs):
    [result] = run([row("jura", f"{server}/nested.zip")], dirs)
    assert result.status == "downloaded", result.error
    assert (dirs["extracted_dir"] / "jura" / "stops.txt").exists()


def test_feed_in_a_subfolder_is_extracted_flat(server, dirs):
    [result] = run([row("sub", f"{server}/sub.zip")], dirs)
    assert result.status == "downloaded", result.error
    assert sorted(p.name for p in (dirs["extracted_dir"] / "sub").iterdir()) == sorted(MINIMAL_FEED)


@pytest.mark.parametrize("path, error, hint", [
    ("/html", "HTML page", "browser"),
    ("/missing.zip", "HTTP 404", "catalog check"),
    ("/notgtfs.zip", "stops.txt", ""),
])
def test_failures_explain_themselves(server, dirs, path, error, hint):
    [result] = run([row("bad", f"{server}{path}")], dirs)
    assert result.status == "failed"
    assert error in result.error and hint in result.hint
    assert not (dirs["raw_dir"] / "bad.zip").exists()
    assert not list(dirs["raw_dir"].glob("*.part"))


def test_basic_auth(server, dirs):
    url = f"{server}/private.zip"
    [missing] = run([row("tcl", url, auth="grandlyon")], dirs)
    assert missing.status == "failed" and "GRANDLYON_PASSWORD" in missing.error

    wrong = CredentialStore(None, environ={"GRANDLYON_USER": "alice", "GRANDLYON_PASSWORD": "nope"})
    [refused] = run([row("tcl", url, auth="grandlyon")], dirs, wrong)
    assert refused.http_status == 401 and "benchmark/.env" in refused.hint
    assert "nope" not in refused.error + refused.hint

    right = CredentialStore(None, environ={"GRANDLYON_USER": "alice", "GRANDLYON_PASSWORD": "s3cret"})
    [ok] = run([row("tcl", url, auth="grandlyon")], dirs, right)
    assert ok.status == "downloaded", ok.error


def test_feeds_sharing_a_url_share_one_download(server, dirs):
    results = run([row("sncf-ter", f"{server}/feed.zip"), row("sncf-grandes-lignes", f"{server}/feed.zip")], dirs)
    assert [r.status for r in results] == ["downloaded", "downloaded"]
    assert (dirs["extracted_dir"] / "sncf-grandes-lignes" / "stops.txt").exists()


def test_register_a_zip_placed_by_hand(dirs):
    from gtfs_bench.download import register_local

    dirs["raw_dir"].mkdir(parents=True)
    (dirs["raw_dir"] / "tcl.zip").write_bytes(feed_zip("GTFS_TCL/"))
    result = register_local("tcl", **dirs)
    assert result.status == "manual" and result.ok, result.error
    assert (dirs["extracted_dir"] / "tcl" / "stop_times.txt").exists()
    assert read_manifest(dirs["manifest"])["tcl"].service_end == "2026-12-19"

    (dirs["raw_dir"] / "bad.zip").write_bytes(zip_bytes({"readme.txt": "x"}))
    assert register_local("bad", **dirs).status == "failed"


def test_a_manual_feed_is_left_alone_by_downloads(server, dirs):
    from gtfs_bench.download import register_local

    dirs["raw_dir"].mkdir(parents=True)
    (dirs["raw_dir"] / "tcl.zip").write_bytes(FEED)
    register_local("tcl", **dirs)
    # The URL would answer 401: the run must not even try, nor overwrite the entry.
    [kept] = run([row("tcl", f"{server}/private.zip", auth="grandlyon")], dirs)
    assert kept.status == "manual"
    assert read_manifest(dirs["manifest"])["tcl"].status == "manual"


def test_extraction_never_writes_outside_its_folder(tmp_path):
    archive = tmp_path / "evil.zip"
    files = dict(MINIMAL_FEED)
    files["..\\..\\evil.txt"] = "x"
    files["sub/../../evil2.txt"] = "x"
    archive.write_bytes(zip_bytes(files))
    dest = tmp_path / "out" / "feed"
    names = extract_feed(archive, dest)
    assert sorted(names) == sorted(MINIMAL_FEED)
    assert not list(tmp_path.rglob("evil*.txt"))


def test_extraction_refuses_two_feeds_in_one_zip(tmp_path):
    archive = tmp_path / "two.zip"
    archive.write_bytes(zip_bytes({"a/stops.txt": "stop_id\n", "b/stops.txt": "stop_id\n"}))
    with pytest.raises(DownloadError, match="stops.txt"):
        extract_feed(archive, tmp_path / "out")


def test_service_window_falls_back_to_feed_info(tmp_path):
    (tmp_path / "feed_info.txt").write_text(
        "feed_publisher_name,feed_publisher_url,feed_lang,feed_start_date,feed_end_date\n"
        "x,https://x,fr,20261201,20270131\n", encoding="utf-8")
    assert service_window(tmp_path) == ("2026-12-01", "2027-01-31", "feed_info")


def test_service_window_reads_a_bom(tmp_path):
    (tmp_path / "calendar.txt").write_bytes("﻿".encode() + MINIMAL_FEED["calendar.txt"].encode())
    assert service_window(tmp_path)[:2] == ("2026-11-02", "2026-12-18")
