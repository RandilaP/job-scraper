#!/usr/bin/env python3
"""
Test runner — scoped, safe, built-in way to exercise the extraction pipeline.

Lets you run any single source or the whole pipeline against a small slice of data,
optionally without writing anything. It wraps the services' existing public methods and
deliberately bypasses main.py, so it never creates a RunStats document.

Examples:
    # Dry run (fetch + parse, write nothing) — 2 Muse companies, 3 jobs each
    python test_runner.py --source muse --limit 2 --jobs-limit 3 --dry-run

    # Real, scoped Muse run incl. the discovery/diff phase (use a test/seeded DB)
    python test_runner.py --source muse --limit 2 --jobs-limit 3 --id-maintenance

    # Whole pipeline, dry run, 2 companies per source
    python test_runner.py --source all --limit 2 --dry-run

    # Single Greenhouse batch of 5 companies, no OpenSearch indexing
    python test_runner.py --source greenhouse --limit 5 --no-opensearch

Notes:
- Construction of a service still connects to MongoDB (PROD_MONGODB_URI required) because
  the processing path READS company docs / job-existence. Dry-run only suppresses WRITES.
- Dry-run forces --id-maintenance off: the ID maintainers write directly to collections
  (bypassing the db_manager write methods we no-op), so dry-run exercises the
  fetch -> parse -> would-insert/index path against the EXISTING new_jobs in the DB.
"""

import argparse
import logging

from bson import ObjectId

from config import setup_logging

logger = logging.getLogger(__name__)


def _apply_dry_run(db_manager) -> None:
    """Monkeypatch a DatabaseManager instance so all writes become no-ops.

    Reads are left intact. insert_job returns a synthetic ObjectId string so the
    downstream token-generation and (would-be) indexing path still executes.
    """
    db_manager.insert_job = lambda *a, **k: str(ObjectId())
    db_manager.insert_job_tokens = lambda *a, **k: True
    db_manager.update_company_job_status = lambda *a, **k: None
    db_manager.remove_job_from_new_jobs = lambda *a, **k: None
    db_manager.update_workday_company_job_status = lambda *a, **k: None
    db_manager.remove_workday_job_from_new_links = lambda *a, **k: None
    db_manager.update_muse_company_job_status = lambda *a, **k: None
    db_manager.bulk_insert_jobs = lambda *a, **k: {'inserted_count': 0, 'inserted_ids': []}
    db_manager.bulk_insert_tokens = lambda *a, **k: 0
    db_manager.bulk_delete_jobs_by_ids = lambda *a, **k: 0
    logger.info("🧪 DRY-RUN: MongoDB writes are no-ops (reads still hit the DB)")


def _close(service) -> None:
    """Close a service's DB + OpenSearch connections (services lack a uniform close())."""
    db_manager = getattr(service, 'db_manager', None)
    if db_manager is not None:
        try:
            db_manager.close()
        except Exception as e:
            logger.warning(f"Error closing db_manager: {e}")
    opensearch = getattr(service, 'opensearch', None)
    if opensearch is not None:
        try:
            opensearch.close()
        except Exception as e:
            logger.warning(f"Error closing opensearch: {e}")


def run_greenhouse(limit: int, dry_run: bool, enable_os: bool, id_maint: bool) -> dict:
    from greenhouse.greenhouse_service import GreenhouseExtractionService
    service = GreenhouseExtractionService(enable_opensearch=enable_os)
    if dry_run:
        _apply_dry_run(service.db_manager)
    try:
        if id_maint and not dry_run:
            logger.info("Running Greenhouse ID maintenance...")
            service.greenhouse_id_maintainer.maintain_all_company_jobs()
        return service.process_companies_parallel(skip=0, limit=limit)
    finally:
        _close(service)


def run_workday(limit: int, dry_run: bool, enable_os: bool, id_maint: bool) -> dict:
    from workday.workday_service import WorkdayExtractionService
    service = WorkdayExtractionService(enable_opensearch=enable_os)
    if dry_run:
        _apply_dry_run(service.db_manager)
    try:
        if id_maint and not dry_run:
            logger.info("Running Workday ID maintenance...")
            service.workday_id_maintainer.maintain_all_company_jobs()
        return service.process_companies_batch(skip=0, limit=limit, batch_id=1)
    finally:
        _close(service)


def run_muse(limit: int, jobs_limit, dry_run: bool, enable_os: bool, id_maint: bool) -> dict:
    from muse.muse_service import MuseExtractionService
    service = MuseExtractionService(enable_opensearch=enable_os)
    if dry_run:
        _apply_dry_run(service.db_manager)
    try:
        if id_maint and not dry_run:
            logger.info("Running Muse ID maintenance...")
            service.id_maintainer.maintain_all_companies(limit_companies=limit)
        return service.process_companies_batch(
            skip=0, limit=limit, batch_id=1, limit_jobs_per_company=jobs_limit
        )
    finally:
        _close(service)


def _print_summary(source: str, stats: dict) -> None:
    print(f"\n{'─' * 60}")
    print(f"  {source.upper()} — result")
    print(f"{'─' * 60}")
    if not stats:
        print("  (no stats returned)")
        return
    for key in ('companies_processed', 'jobs_processed', 'jobs_inserted',
                'jobs_existed', 'jobs_failed', 'jobs_not_found',
                'jobs_indexed_opensearch', 'jobs_opensearch_failed'):
        if key in stats:
            print(f"  {key:24}: {stats[key]}")
    if stats.get('error'):
        print(f"  error                   : {stats['error']}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scoped test runner for the job-extraction pipeline.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument('--source', required=True,
                        choices=['greenhouse', 'workday', 'muse', 'all'],
                        help="Which source(s) to test")
    parser.add_argument('--limit', type=int, default=5,
                        help="Max companies to process in a single skip=0 batch (default: 5)")
    parser.add_argument('--jobs-limit', type=int, default=None,
                        help="Muse only: cap jobs processed per company (default: all)")
    parser.add_argument('--dry-run', action='store_true',
                        help="Fetch + parse but write nothing (forces --id-maintenance off)")
    parser.add_argument('--no-opensearch', action='store_true',
                        help="Disable OpenSearch indexing for this run")
    parser.add_argument('--id-maintenance', action='store_true',
                        help="Also run the write-heavy discovery/diff phase first "
                             "(ignored in --dry-run)")

    args = parser.parse_args()
    setup_logging()

    enable_os = (not args.dry_run) and (not args.no_opensearch)
    id_maint = args.id_maintenance and not args.dry_run

    print("=" * 60)
    print("🧪 TEST RUNNER")
    print(f"  source         : {args.source}")
    print(f"  limit          : {args.limit}")
    print(f"  jobs-limit     : {args.jobs_limit}")
    print(f"  dry-run        : {args.dry_run}")
    print(f"  opensearch     : {'on' if enable_os else 'off'}")
    print(f"  id-maintenance : {id_maint}")
    print("=" * 60)

    results = {}
    if args.source in ('greenhouse', 'all'):
        results['greenhouse'] = run_greenhouse(args.limit, args.dry_run, enable_os, id_maint)
    if args.source in ('workday', 'all'):
        results['workday'] = run_workday(args.limit, args.dry_run, enable_os, id_maint)
    if args.source in ('muse', 'all'):
        results['muse'] = run_muse(args.limit, args.jobs_limit, args.dry_run, enable_os, id_maint)

    print("\n" + "=" * 60)
    print("📊 SUMMARY")
    print("=" * 60)
    for source, stats in results.items():
        _print_summary(source, stats)
    print()


if __name__ == "__main__":
    main()
