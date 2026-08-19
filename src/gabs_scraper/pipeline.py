"""CLI orchestration for the GABS timetable pipeline.

    python -m gabs_scraper.pipeline --all              # harvest + download + load
    python -m gabs_scraper.pipeline --harvest
    python -m gabs_scraper.pipeline --download
    python -m gabs_scraper.pipeline --load --limit 20  # smoke test on 20 PDFs

Each stage is idempotent; --load re-parses and upserts, replacing child rows.
"""
from __future__ import annotations

import argparse
import json
import time

from . import db
from . import download as dl_mod
from . import load as load_mod
from . import parse as parse_mod
from .config import settings
from .harvest import ManifestEntry, harvest


def _load_manifest() -> list[ManifestEntry]:
    data = json.loads(settings.manifest_path.read_text(encoding="utf-8"))
    return [ManifestEntry(**e) for e in data]


def do_harvest() -> list[ManifestEntry]:
    entries = harvest(write=True)
    print(f"[harvest] {len(entries)} entries -> {settings.manifest_path}")
    return entries


def do_download(entries, workers, force):
    settings.ensure_dirs()
    results = dl_mod.download_all(entries, workers=workers, force=force)
    ok = sum(1 for r in results if r.ok)
    skipped = sum(1 for r in results if r.skipped)
    fail = [r for r in results if not r.ok]
    print(f"[download] ok={ok} (skipped={skipped}) fail={len(fail)}")
    for r in fail[:20]:
        print(f"   FAIL {r.pdf_filename}: {r.error}")
    return results


def do_load(entries, workers, force):
    results = dl_mod.download_all(entries, workers=workers, force=force)
    by_name = {r.pdf_filename: r for r in results}

    conn = db.connect()
    db.apply_schema(conn)  # safety net; schema also applied at container init

    n_ok = n_fail = 0
    failures: list[tuple[str, str]] = []
    t0 = time.time()
    for i, e in enumerate(entries, 1):
        r = by_name.get(e.pdf_filename)
        if r is None or not r.ok:
            try:
                load_mod.load_failed(conn, e, r, error=(r.error if r else "not downloaded"))
            except Exception:  # noqa: BLE001
                conn.rollback()
            n_fail += 1
            failures.append((e.pdf_filename, "download failed"))
            continue
        try:
            parsed = parse_mod.parse_pdf(r.path)
            load_mod.load_timetable(conn, e, r, parsed)
            n_ok += 1
        except Exception as ex:  # noqa: BLE001 — isolate per-PDF failures
            conn.rollback()
            try:
                load_mod.load_failed(conn, e, r, error=repr(ex))
            except Exception:  # noqa: BLE001
                conn.rollback()
            n_fail += 1
            failures.append((e.pdf_filename, repr(ex)))
        if i % 200 == 0:
            print(f"   loaded {i}/{len(entries)} ...", flush=True)

    conn.close()
    print(f"[load] parsed_ok={n_ok} failed={n_fail} in {time.time() - t0:.0f}s")
    for f, err in failures[:25]:
        print(f"   FAILED {f}: {err}")
    return n_ok, n_fail


def main(argv=None):
    ap = argparse.ArgumentParser(description="GABS timetable scraper pipeline")
    ap.add_argument("--harvest", action="store_true", help="scrape manifest of PDF URLs")
    ap.add_argument("--download", action="store_true", help="download PDFs from manifest")
    ap.add_argument("--load", action="store_true", help="parse + load PDFs into Postgres")
    ap.add_argument("--all", action="store_true", help="harvest + download + load")
    ap.add_argument("--limit", type=int, default=None, help="cap entries (smoke test)")
    ap.add_argument("--workers", type=int, default=12, help="download concurrency")
    ap.add_argument("--force", action="store_true", help="re-download existing PDFs")
    args = ap.parse_args(argv)

    do_h = args.harvest or args.all
    do_d = args.download or args.all
    do_l = args.load or args.all
    if not (do_h or do_d or do_l):
        ap.error("choose at least one of --harvest, --download, --load, --all")

    entries = do_harvest() if do_h else _load_manifest()
    if args.limit:
        entries = entries[: args.limit]
        print(f"[limit] using first {len(entries)} entries")

    if do_d and not do_l:
        do_download(entries, args.workers, args.force)
    if do_l:
        do_load(entries, args.workers, args.force)


if __name__ == "__main__":
    main()
