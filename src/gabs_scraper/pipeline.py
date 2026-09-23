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


def do_prune(entries):
    conn = db.connect()
    try:
        gone_tt, gone_routes = load_mod.prune_superseded(conn, entries)
        print(f"[prune] removed {gone_tt} superseded timetable(s) "
              f"and {gone_routes} route(s) left with none")
    finally:
        conn.close()

    # Reconcile the download cache too, or it grows by the whole delta every refresh.
    gone_pdfs, freed = dl_mod.prune_pdfs(entries)
    print(f"[prune] removed {gone_pdfs} superseded PDF(s) ({freed / 1024 / 1024:.0f} MB)")
    return gone_tt, gone_routes, gone_pdfs


def do_load(entries, workers, force, reparse=False):
    results = dl_mod.download_all(entries, workers=workers, force=force)
    by_name = {r.pdf_filename: r for r in results}

    conn = db.connect()
    db.apply_schema(conn)  # safety net; schema also applied at container init

    # Golden Arrow reissues a handful of timetables a week and republishes the rest
    # byte for byte, but every run re-parsed all of them: 2,874 PDFs, 7,288 seconds. The
    # checksum of the file each timetable came from is already stored, so an unchanged
    # file has nothing left to work out. --reparse forces the old behaviour, which is
    # what you want after a change to the parser itself.
    loaded_sha = {} if reparse else load_mod.already_loaded(conn)

    n_ok = n_fail = n_same = 0
    failures: list[tuple[str, str]] = []
    t0 = time.time()
    for i, e in enumerate(entries, 1):
        r = by_name.get(e.pdf_filename)
        if r is not None and r.ok and r.sha256 and loaded_sha.get(e.pdf_filename) == r.sha256:
            # Checked against the operator today and unchanged, so say so: freshness is
            # measured from scraped_at and this timetable is as current as a re-parsed one.
            load_mod.touch_timetable(conn, e.pdf_filename)
            n_same += 1
            continue
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
    print(f"[load] parsed_ok={n_ok} unchanged={n_same} failed={n_fail} "
          f"in {time.time() - t0:.0f}s")
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
    ap.add_argument("--reparse", action="store_true",
                    help="parse every PDF again, even ones whose bytes have not "
                         "changed since they were loaded (use after a parser change)")
    ap.add_argument(
        "--no-prune", action="store_true",
        help="keep timetables GABS no longer publishes (default is to delete them)",
    )
    args = ap.parse_args(argv)

    do_h = args.harvest or args.all
    do_d = args.download or args.all
    do_l = args.load or args.all
    if not (do_h or do_d or do_l):
        ap.error("choose at least one of --harvest, --download, --load, --all")

    entries = do_harvest() if do_h else _load_manifest()

    limited = bool(args.limit)
    if limited:
        entries = entries[: args.limit]
        print(f"[limit] using first {len(entries)} entries")

    if do_d and not do_l:
        do_download(entries, args.workers, args.force)
    if do_l:
        do_load(entries, args.workers, args.force, reparse=args.reparse)
        # Prune only after a successful full load. With --limit the entry list is a
        # sample, so pruning against it would delete almost the whole database.
        if limited:
            print("[prune] skipped: --limit means these entries are only a sample")
        elif args.no_prune:
            print("[prune] skipped: --no-prune")
        else:
            do_prune(entries)


if __name__ == "__main__":
    main()
