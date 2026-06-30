#!/usr/bin/env python3
"""
Simple Job Extractor Server - Main Entry Point
"""

import logging
import os
import traceback
from datetime import datetime
import config
from config import setup_logging
from database import DatabaseManager
from models import RunStats
from greenhouse.greenhouse_service import GreenhouseExtractionService
from workday.workday_service import WorkdayExtractionService
from muse.muse_service import MuseExtractionService
from logtail_handler import setup_logtail_logging
from sync_opensearch_mongodb import JobSyncService
from cache_utils import CacheManager


def main() -> None:
    """Main function to run the job extraction service."""
    # Setup both local and remote logging
    setup_logging()
    setup_logtail_logging()
    
    logger = logging.getLogger(__name__)
    
    job_source = config.JOB_SOURCE
    logger.info(f"Starting job extraction service for source: {job_source}")
    
    # Initialize database and create run stat
    db_manager = DatabaseManager()
    start_time = datetime.utcnow()
    
    # Create initial run stat with "ongoing" status
    run_stat = RunStats(
        status="ongoing",
        start_time=start_time,
        job_source=job_source,
        environment=os.getenv('ENVIRONMENT', 'production'),
        hostname=os.getenv('HOSTNAME', 'unknown')
    )
    
    stat_id = db_manager.create_run_stat(run_stat)
    logger.info(f"📊 Run tracking started with ID: {stat_id}")
    
    # Initialize stats aggregation
    total_stats = {
        'greenhouse_jobs_new': 0,
        'greenhouse_jobs_inserted': 0,
        'greenhouse_jobs_existed': 0,
        'greenhouse_jobs_failed': 0,
        'greenhouse_jobs_not_found': 0,
        'workday_jobs_new': 0,
        'workday_jobs_inserted': 0,
        'workday_jobs_existed': 0,
        'workday_jobs_failed': 0,
        'workday_jobs_not_found': 0,
        'muse_jobs_processed': 0,
        'muse_jobs_inserted': 0,
        'muse_jobs_failed': 0,
        'muse_jobs_not_found': 0,
        'muse_companies_processed': 0,
        'muse_expired_removed': 0,
        'companies_processed': 0,
        'opensearch_indexed': 0,
        'opensearch_deleted': 0
    }

    def _aggregate_muse_stats(muse_stats: dict) -> None:
        """Fold a MuseExtractionService.run() result into total_stats."""
        if not muse_stats:
            return
        total_stats['muse_jobs_processed'] += muse_stats.get('jobs_processed', 0)
        total_stats['muse_jobs_inserted'] += muse_stats.get('jobs_inserted', 0)
        total_stats['muse_jobs_failed'] += muse_stats.get('jobs_failed', 0)
        total_stats['muse_jobs_not_found'] += muse_stats.get('jobs_not_found', 0)
        total_stats['muse_companies_processed'] += muse_stats.get('companies_processed', 0)
        total_stats['muse_expired_removed'] += muse_stats.get('id_maintenance_expired', 0)
        total_stats['companies_processed'] += muse_stats.get('companies_processed', 0)
        total_stats['opensearch_indexed'] += muse_stats.get('jobs_indexed_opensearch', 0)
    
    try:
        # Determine which service(s) to run based on JOB_SOURCE
        if job_source == 'greenhouse':
            logger.info("Running Greenhouse extraction only")
            service = GreenhouseExtractionService(
                max_workers=config.GREENHOUSE_COMPANY_WORKERS,
                max_job_workers=config.GREENHOUSE_JOB_WORKERS,
                id_maintenance_workers=config.GREENHOUSE_ID_MAINTENANCE_WORKERS
            )
            gh_stats = service.run()
            
            # Aggregate Greenhouse stats
            if gh_stats:
                total_stats['greenhouse_jobs_inserted'] = gh_stats.get('jobs_inserted', 0)
                total_stats['greenhouse_jobs_existed'] = gh_stats.get('jobs_existed', 0)
                total_stats['greenhouse_jobs_failed'] = gh_stats.get('jobs_failed', 0)
                total_stats['greenhouse_jobs_not_found'] = gh_stats.get('jobs_not_found', 0)
                total_stats['companies_processed'] = gh_stats.get('companies_processed', 0)
                total_stats['opensearch_indexed'] = gh_stats.get('jobs_indexed_opensearch', 0)
            
        elif job_source == 'workday':
            logger.info("Running Workday extraction only")
            workday_service = WorkdayExtractionService()
            wd_stats = workday_service.run()
            
            # Aggregate Workday stats
            if wd_stats:
                total_stats['workday_jobs_inserted'] = wd_stats.get('jobs_inserted', 0)
                total_stats['workday_jobs_existed'] = wd_stats.get('jobs_existed', 0)
                total_stats['workday_jobs_failed'] = wd_stats.get('jobs_failed', 0)
                total_stats['workday_jobs_not_found'] = wd_stats.get('jobs_not_found', 0)
                total_stats['companies_processed'] = wd_stats.get('companies_processed', 0)
                total_stats['opensearch_indexed'] = wd_stats.get('jobs_indexed_opensearch', 0)
            
        elif job_source == 'both':
            logger.info("Running both Greenhouse and Workday extraction")
            # Run Greenhouse first
            logger.info("Starting Greenhouse extraction...")
            greenhouse_service = GreenhouseExtractionService(
                max_workers=config.GREENHOUSE_COMPANY_WORKERS,
                max_job_workers=config.GREENHOUSE_JOB_WORKERS,
                id_maintenance_workers=config.GREENHOUSE_ID_MAINTENANCE_WORKERS
            )
            gh_stats = greenhouse_service.run()
            logger.info("Greenhouse extraction completed")
            
            # Aggregate Greenhouse stats
            if gh_stats:
                total_stats['greenhouse_jobs_inserted'] = gh_stats.get('jobs_inserted', 0)
                total_stats['greenhouse_jobs_existed'] = gh_stats.get('jobs_existed', 0)
                total_stats['greenhouse_jobs_failed'] = gh_stats.get('jobs_failed', 0)
                total_stats['greenhouse_jobs_not_found'] = gh_stats.get('jobs_not_found', 0)
                total_stats['companies_processed'] += gh_stats.get('companies_processed', 0)
                total_stats['opensearch_indexed'] += gh_stats.get('jobs_indexed_opensearch', 0)
            
            # Then run Workday
            logger.info("Starting Workday extraction...")
            workday_service = WorkdayExtractionService()
            wd_stats = workday_service.run()
            logger.info("Workday extraction completed")
            
            # Aggregate Workday stats
            if wd_stats:
                total_stats['workday_jobs_inserted'] = wd_stats.get('jobs_inserted', 0)
                total_stats['workday_jobs_existed'] = wd_stats.get('jobs_existed', 0)
                total_stats['workday_jobs_failed'] = wd_stats.get('jobs_failed', 0)
                total_stats['workday_jobs_not_found'] = wd_stats.get('jobs_not_found', 0)
                total_stats['companies_processed'] += wd_stats.get('companies_processed', 0)
                total_stats['opensearch_indexed'] += wd_stats.get('jobs_indexed_opensearch', 0)

        elif job_source == 'muse':
            logger.info("Running Muse extraction only")
            muse_service = MuseExtractionService()
            muse_stats = muse_service.run(
                limit_companies=config.MUSE_TEST_COMPANY_LIMIT,
                limit_jobs_per_company=config.MUSE_TEST_JOB_LIMIT
            )
            _aggregate_muse_stats(muse_stats)

        elif job_source == 'all':
            logger.info("Running Greenhouse, Workday and Muse extraction")
            # Run Greenhouse first
            logger.info("Starting Greenhouse extraction...")
            greenhouse_service = GreenhouseExtractionService(
                max_workers=config.GREENHOUSE_COMPANY_WORKERS,
                max_job_workers=config.GREENHOUSE_JOB_WORKERS,
                id_maintenance_workers=config.GREENHOUSE_ID_MAINTENANCE_WORKERS
            )
            gh_stats = greenhouse_service.run()
            logger.info("Greenhouse extraction completed")

            if gh_stats:
                total_stats['greenhouse_jobs_inserted'] = gh_stats.get('jobs_inserted', 0)
                total_stats['greenhouse_jobs_existed'] = gh_stats.get('jobs_existed', 0)
                total_stats['greenhouse_jobs_failed'] = gh_stats.get('jobs_failed', 0)
                total_stats['greenhouse_jobs_not_found'] = gh_stats.get('jobs_not_found', 0)
                total_stats['companies_processed'] += gh_stats.get('companies_processed', 0)
                total_stats['opensearch_indexed'] += gh_stats.get('jobs_indexed_opensearch', 0)

            # Then run Workday
            logger.info("Starting Workday extraction...")
            workday_service = WorkdayExtractionService()
            wd_stats = workday_service.run()
            logger.info("Workday extraction completed")

            if wd_stats:
                total_stats['workday_jobs_inserted'] = wd_stats.get('jobs_inserted', 0)
                total_stats['workday_jobs_existed'] = wd_stats.get('jobs_existed', 0)
                total_stats['workday_jobs_failed'] = wd_stats.get('jobs_failed', 0)
                total_stats['workday_jobs_not_found'] = wd_stats.get('jobs_not_found', 0)
                total_stats['companies_processed'] += wd_stats.get('companies_processed', 0)
                total_stats['opensearch_indexed'] += wd_stats.get('jobs_indexed_opensearch', 0)

            # Finally run Muse
            logger.info("Starting Muse extraction...")
            muse_service = MuseExtractionService()
            muse_stats = muse_service.run(
                limit_companies=config.MUSE_TEST_COMPANY_LIMIT,
                limit_jobs_per_company=config.MUSE_TEST_JOB_LIMIT
            )
            logger.info("Muse extraction completed")
            _aggregate_muse_stats(muse_stats)

        else:
            logger.error(f"Invalid JOB_SOURCE: {job_source}. Must be 'greenhouse', 'workday', 'muse', 'both', or 'all'")
            error_msg = f"Invalid JOB_SOURCE: {job_source}"
            db_manager.add_run_error(stat_id, "ConfigError", error_msg)
            raise ValueError(error_msg)
        
        # Log cache statistics
        logger.info("\n" + "="*60)
        logger.info("📊 CACHE STATISTICS")
        logger.info("="*60)
        CacheManager.log_cache_stats()
        
        # Get cache stats for run tracking
        cache_stats = CacheManager.get_all_stats()
        total_hits = sum(stats['hits'] for stats in cache_stats.values())
        total_misses = sum(stats['misses'] for stats in cache_stats.values())
        total_requests = total_hits + total_misses
        cache_hit_rate = (total_hits / total_requests * 100) if total_requests > 0 else 0
        
        # Cleanup expired cache entries
        logger.info("\n🧹 Cleaning up expired cache entries...")
        cleanup_results = CacheManager.cleanup_all_expired()
        total_cleaned = sum(cleanup_results.values())
        if total_cleaned > 0:
            logger.info(f"✅ Cleaned {total_cleaned} expired entries across all caches")
        else:
            logger.info("✅ No expired entries found")
        
        # Sync OpenSearch with MongoDB at the end
        logger.info("\n" + "="*60)
        logger.info("🔄 Starting OpenSearch-MongoDB synchronization...")
        logger.info("="*60)
        
        opensearch_synced = False
        try:
            sync_service = JobSyncService()
            sync_result = sync_service.sync(dry_run=False)
            logger.info(f"✅ Synchronization completed: {sync_result}")
            
            # Update stats with sync results
            if sync_result:
                total_stats['opensearch_deleted'] = sync_result.get('deleted_count', 0)
                opensearch_synced = True
            
            # Close sync service connections
            sync_service.db_manager.close()
            sync_service.opensearch_service.close()
            
        except ImportError:
            logger.warning("⚠️  OpenSearch not available, skipping synchronization")
            db_manager.add_run_error(stat_id, "ImportError", "OpenSearch module not available")
        except Exception as e:
            error_msg = f"Synchronization failed: {e}"
            logger.error(f"❌ {error_msg}")
            logger.warning("Continuing despite sync failure...")
            db_manager.add_run_error(stat_id, "SyncError", error_msg, traceback.format_exc())
        
        # Calculate duration
        end_time = datetime.utcnow()
        duration = (end_time - start_time).total_seconds()
        
        # Update run stat to completed
        final_updates = {
            'status': 'completed',
            'end_time': end_time,
            'duration_seconds': duration,
            **total_stats,
            'opensearch_synced': opensearch_synced,
            'cache_hit_rate': cache_hit_rate,
            'cache_total_hits': total_hits,
            'cache_total_misses': total_misses
        }
        
        db_manager.update_run_stat(stat_id, final_updates)
        logger.info(f"📊 Run stats updated - Status: completed, Duration: {duration:.2f}s")
        logger.info("Job extraction service completed successfully")
        
    except KeyboardInterrupt:
        logger.info("Job extraction interrupted by user")
        # Update run stat as failed
        end_time = datetime.utcnow()
        duration = (end_time - start_time).total_seconds()
        db_manager.update_run_stat(stat_id, {
            'status': 'failed',
            'end_time': end_time,
            'duration_seconds': duration,
            'failed_reason': 'Interrupted by user',
            **total_stats
        })
        db_manager.add_run_error(stat_id, "KeyboardInterrupt", "User interrupted execution")
        
    except Exception as e:
        logger.error(f"Error in main: {e}")
        error_trace = traceback.format_exc()
        logger.error(error_trace)
        
        # Update run stat as failed
        end_time = datetime.utcnow()
        duration = (end_time - start_time).total_seconds()
        db_manager.update_run_stat(stat_id, {
            'status': 'failed',
            'end_time': end_time,
            'duration_seconds': duration,
            'failed_reason': str(e),
            **total_stats
        })
        db_manager.add_run_error(stat_id, type(e).__name__, str(e), error_trace)
        raise
    
    finally:
        # Always close database connection
        db_manager.close()
    
    logger.info("Job extraction service stopped")


if __name__ == "__main__":
    main()
