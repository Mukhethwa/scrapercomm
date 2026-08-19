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
