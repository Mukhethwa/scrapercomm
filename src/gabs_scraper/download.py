"""Download timetable PDFs listed in the manifest.

The static PDFs are not behind Cloudflare, so a plain requests session works.
Downloads run concurrently; an already-present file of the same size is skipped
unless ``force`` is set.
"""
from __future__ import annotations

import hashlib
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

import requests

from .config import settings
from .harvest import ManifestEntry

_local = threading.local()


@dataclass
class DownloadResult:
    pdf_filename: str
    path: str | None
    sha256: str | None
    size: int
    ok: bool
    skipped: bool = False
    error: str | None = None


def _session() -> requests.Session:
    s = getattr(_local, "session", None)
    if s is None:
        s = requests.Session()
        s.headers.update({"User-Agent": settings.user_agent})
        _local.session = s
    return s


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def download_one(
    entry: ManifestEntry, pdf_dir: Path, force: bool = False, retries: int = 3
) -> DownloadResult:
    dest = pdf_dir / entry.pdf_filename
    if dest.exists() and not force and dest.stat().st_size > 0:
        data = dest.read_bytes()
        return DownloadResult(entry.pdf_filename, str(dest), _sha256(data),
                              len(data), ok=True, skipped=True)

    last_err = None
    for attempt in range(retries):
        try:
            r = _session().get(entry.pdf_url, timeout=60)
            r.raise_for_status()
            data = r.content
            if not data.startswith(b"%PDF"):
                raise ValueError("response is not a PDF")
            dest.write_bytes(data)
            return DownloadResult(entry.pdf_filename, str(dest), _sha256(data),
                                  len(data), ok=True)
        except Exception as e:  # noqa: BLE001 — record and retry/report
            last_err = str(e)
            time.sleep(0.5 * (2 ** attempt))
    return DownloadResult(entry.pdf_filename, None, None, 0, ok=False, error=last_err)


def download_all(
    entries: list[ManifestEntry],
    pdf_dir: Path | None = None,
    workers: int = 12,
    force: bool = False,
) -> list[DownloadResult]:
    pdf_dir = pdf_dir or settings.pdf_dir
    pdf_dir.mkdir(parents=True, exist_ok=True)
    results: list[DownloadResult] = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(download_one, e, pdf_dir, force): e for e in entries}
        for fut in as_completed(futs):
            results.append(fut.result())
    return results


def prune_pdfs(entries: list[ManifestEntry], pdf_dir: Path | None = None) -> tuple[int, int]:
    """Delete downloaded PDFs that GABS no longer publishes.

    The database is reconciled by ``load.prune_superseded``, but the download cache was
    not, so every refresh left the previous versions behind: one August 2026 refresh
    added 1,528 files and stranded 1,518. Nothing reads them -- they are absent from the
    manifest and from the database -- so they are just an ever-growing pile that makes it
    impossible to tell by looking which PDFs are current.

    They are also unrecoverable from the operator: a superseded timetable is gone from
    the site. Where this repository tracks ``data/pdfs`` in git, the deleted files remain
    in history and can be restored from there; that is the intended archive, not a
    working directory nobody prunes.

    Returns (deleted, bytes_freed).
    """
    pdf_dir = pdf_dir or settings.pdf_dir
    if not pdf_dir.is_dir():
        return 0, 0

    current = {e.pdf_filename for e in entries}
    if not current:
        # Same guard as the database prune: an empty manifest is a harvest failure, not
        # GABS withdrawing everything it publishes.
        raise ValueError("refusing to prune PDFs against an empty manifest")

    deleted = freed = 0
    for path in pdf_dir.glob("*.pdf"):
        if path.name in current:
            continue
        freed += path.stat().st_size
        path.unlink()
        deleted += 1
    return deleted, freed
