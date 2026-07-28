"""
Muse job extraction service

Orchestrates the full Muse extraction pipeline:
1. ID maintenance (discover new/expired jobs via UsersDB.employers)
2. Process new jobs (fetch from API, transform, insert to DB)
3. Optional OpenSearch indexing
"""
import logging
import time
from typing import List, Dict, Optional

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import DatabaseManager
from parser import JobPostingParser
from muse.muse_api import MuseAPI
from muse.muse_id_maintainer import MuseIDMaintainer
import config

# Optional OpenSearch — allows test runs without credentials
try:
    from opensearch_service import OpenSearchService
    OPENSEARCH_AVAILABLE = True
except ImportError:
    OPENSEARCH_AVAILABLE = False


class MuseExtractionService:
    """Service class for Muse job extraction"""

    def __init__(self, enable_opensearch: bool = True):
        """
        Initialize the Muse extraction service

        Args:
            enable_opensearch: Whether to enable OpenSearch indexing
        """
        self.db_manager = DatabaseManager()
        self.parser = JobPostingParser()
        self.muse_api = MuseAPI(self.parser)
        self.id_maintainer = MuseIDMaintainer(self.db_manager)
        self.enable_opensearch = enable_opensearch

        # Initialize OpenSearch if enabled and available
        self.opensearch = None
        if self.enable_opensearch and OPENSEARCH_AVAILABLE:
            try:
                self.opensearch = OpenSearchService()
                logging.info("OpenSearch integration enabled for Muse")
            except Exception as e:
                logging.warning(f"Failed to initialize OpenSearch: {e}")
                logging.warning("Continuing without OpenSearch indexing")
                self.opensearch = None

    def run(self, limit_companies: Optional[int] = None, limit_jobs_per_company: Optional[int] = None) -> Dict:
        """
        Run the full Muse job extraction process.

        Args:
            limit_companies: Optional limit on companies to process (for testing)
            limit_jobs_per_company: Optional limit on jobs per company (for testing)

        Returns:
            Dictionary with aggregate extraction statistics
        """
        try:
            logging.info("=" * 60)
            logging.info("Starting Muse job extraction process...")
            logging.info("=" * 60)

            if limit_companies or limit_jobs_per_company:
                logging.info(f"⚠️  TEST MODE: limit_companies={limit_companies}, limit_jobs_per_company={limit_jobs_per_company}")

            # Phase 1: ID Maintenance
            logging.info("\n📋 Phase 1: ID Maintenance")
            id_stats = self.id_maintainer.maintain_all_companies(
                limit_companies=limit_companies
            )

            # Phase 2: Process new jobs
            logging.info("\n💼 Phase 2: Processing new jobs")
            batch_size = getattr(config, 'MUSE_BATCH_SIZE', 100)
            logging.info(f"Processing Muse companies in batches of {batch_size}")

            skip = 0
            total_stats = {
                'companies_processed': 0,
                'jobs_processed': 0,
                'jobs_inserted': 0,
                'jobs_existed': 0,
                'jobs_failed': 0,
                'jobs_not_found': 0,
                'jobs_indexed_opensearch': 0,
                'jobs_opensearch_failed': 0,
                # Include ID maintenance stats
                'id_maintenance_new': id_stats.get('new_jobs_total', 0),
                'id_maintenance_expired': id_stats.get('expired_jobs_total', 0),
            }

            batch_num = 1
            while True:
                logging.info(f"\n{'=' * 60}")
                logging.info(f"🔄 Starting Muse batch {batch_num} (skip={skip}, limit={batch_size})")
                logging.info(f"{'=' * 60}")

                batch_stats = self.process_companies_batch(
                    skip=skip,
                    limit=batch_size,
                    batch_id=batch_num,
                    limit_jobs_per_company=limit_jobs_per_company
                )

                # Aggregate statistics
                for key in ['companies_processed', 'jobs_processed', 'jobs_inserted',
                           'jobs_existed', 'jobs_failed', 'jobs_not_found',
                           'jobs_indexed_opensearch', 'jobs_opensearch_failed']:
                    total_stats[key] += batch_stats.get(key, 0)

                # If we processed fewer companies than the batch size, we're done
                if batch_stats['companies_processed'] < batch_size:
                    logging.info(f"✅ Processed final batch with {batch_stats['companies_processed']} companies")
                    break

                skip += batch_size
                batch_num += 1

            logging.info("\n" + "=" * 60)
            logging.info("🎉 Muse job extraction process completed")
            logging.info(f"📊 Final Muse processing stats: {total_stats}")
            logging.info("=" * 60)
            return total_stats

        except Exception as e:
            logging.error(f"Error in Muse job extraction process: {e}")
            raise
        finally:
            # Save geocoding cache (same pattern as Greenhouse)
            try:
                self.parser._save_geocoding_cache()
                logging.info(f"💾 Saved {len(self.parser._location_cache)} cached locations")
            except:
                pass
            self.close()

    def process_companies_batch(
        self, skip: int = 0, limit: int = 100, batch_id: int = None,
        limit_jobs_per_company: Optional[int] = None
    ) -> Dict:
        """Process a batch of Muse companies and return detailed statistics"""
        batch_logger = logging.getLogger(f"muse_batch_{batch_id}" if batch_id else "muse_service")

        stats = {
            'companies_processed': 0,
            'jobs_processed': 0,
            'jobs_inserted': 0,
            'jobs_existed': 0,
            'jobs_failed': 0,
            'jobs_not_found': 0,
            'jobs_indexed_opensearch': 0,
            'jobs_opensearch_failed': 0,
            'start_time': time.time(),
            'batch_id': batch_id,
            'source': 'muse'
        }

        try:
            batch_logger.info(f"📊 Fetching Muse companies (skip={skip}, limit={limit})")

            # Fetch company data from database
            company_data = self.db_manager.fetch_muse_company_data(skip=skip, limit=limit)

            if not company_data:
                batch_logger.warning("No Muse company data found for this batch")
                return stats

            batch_logger.info(f"🏢 Processing {len(company_data)} Muse companies...")

            for idx, record in enumerate(company_data, 1):
                try:
                    company_name = record.get("company", "Unknown")
                    new_jobs = record.get("new_jobs", [])

                    # Apply job limit for testing
                    if limit_jobs_per_company and len(new_jobs) > limit_jobs_per_company:
                        new_jobs = new_jobs[:limit_jobs_per_company]
                        batch_logger.info(f"  ⚠️  TEST MODE: Limited to {limit_jobs_per_company} jobs for {company_name}")

                    new_job_count = len(new_jobs)

                    if idx % 10 == 0 or new_job_count > 0:
                        batch_logger.info(f"[{idx}/{len(company_data)}] Processing {company_name} ({new_job_count} jobs)")

                    company_stats = self._process_company_with_stats(record, new_jobs, batch_logger)

                    stats['companies_processed'] += 1
                    stats['jobs_processed'] += company_stats['jobs_processed']
                    stats['jobs_inserted'] += company_stats['jobs_inserted']
                    stats['jobs_existed'] += company_stats['jobs_existed']
                    stats['jobs_failed'] += company_stats['jobs_failed']
                    stats['jobs_not_found'] += company_stats.get('jobs_not_found', 0)
                    stats['jobs_indexed_opensearch'] += company_stats.get('jobs_indexed_opensearch', 0)
                    stats['jobs_opensearch_failed'] += company_stats.get('jobs_opensearch_failed', 0)

                except Exception as e:
                    batch_logger.error(f"Error processing Muse company {record.get('company', 'Unknown')}: {e}")
                    continue

            stats['end_time'] = time.time()
            stats['processing_time'] = stats['end_time'] - stats['start_time']

            batch_logger.info(f"✅ Muse batch processing completed: {stats}")
            return stats

        except Exception as e:
            batch_logger.error(f"Muse batch processing failed: {e}", exc_info=True)
            stats['error'] = str(e)
            return stats

    def _process_company_with_stats(self, record: Dict, new_jobs: list, logger) -> Dict:
        """Process a single Muse company record and return statistics"""
        company_stats = {
            'jobs_processed': 0,
            'jobs_inserted': 0,
            'jobs_existed': 0,
            'jobs_failed': 0,
            'jobs_not_found': 0,
            'jobs_indexed_opensearch': 0,
            'jobs_opensearch_failed': 0
        }

        company_name = record.get("company")
        logo = record.get("logo")
        employer_id = record.get("employer_id")
        unique_name = record.get("unique_name")

        if not new_jobs:
            logger.debug(f"No new jobs for Muse company: {company_name}")
            return company_stats

        logger.info(f"🏢 Processing Muse company {company_name}: {len(new_jobs)} new jobs")

        for job in new_jobs:
            company_stats['jobs_processed'] += 1
            muse_id = job.get('id')

            try:
                job_result = self._process_job_with_stats(
                    job, company_name, employer_id, logo, unique_name, logger
                )

                if job_result['status'] == 'inserted':
                    company_stats['jobs_inserted'] += 1
                    if job_result.get('opensearch_indexed'):
                        company_stats['jobs_indexed_opensearch'] += 1
                    elif self.opensearch:
                        company_stats['jobs_opensearch_failed'] += 1
                elif job_result['status'] == 'existed':
                    company_stats['jobs_existed'] += 1
                elif job_result['status'] == 'not_found':
                    company_stats['jobs_not_found'] += 1
                else:
                    company_stats['jobs_failed'] += 1

            except Exception as e:
                logger.error(f"Error processing Muse job {muse_id}: {e}")
                company_stats['jobs_failed'] += 1

        return company_stats

    def _process_job_with_stats(
        self, job: Dict, company_name: str, employer_id: str, logo: str, unique_name: str, logger
    ) -> Dict:
        """
        Process a single Muse job and return result status.
        Fetches job data from Muse API (like Greenhouse/Workday).

        Returns:
            Dict with 'status' and 'opensearch_indexed' keys
        """
        result = {
            'status': 'failed',
            'opensearch_indexed': False
        }

        muse_id = job.get('id')
        if not muse_id:
            logger.warning("Job ID is missing")
            return result

        logger.info(f"💼 Processing Muse job | Company: {company_name} | ID: {muse_id}")

        try:
            # Check if job already exists
            if self.db_manager.muse_job_exists(muse_id):
                logger.info(f"🔄 Job already exists | Muse ID: {muse_id}")
                self.db_manager.update_muse_company_job_status(unique_name, muse_id)
                result['status'] = 'existed'
                return result

            # Fetch job from Muse API and transform to JobMongo
            job_mongo, status = self.muse_api.get_job_from_muse(
                muse_id, company_name, employer_id, logo, unique_name
            )

            if status == 'NotFound':
                self.db_manager.update_muse_company_job_status(unique_name, muse_id)
                logger.warning(f"🚫 Job {muse_id} not found in Muse API | Company: {company_name} | Removed from new_jobs")
                result['status'] = 'not_found'
                return result

            if status == 'Error' or not job_mongo:
                logger.error(f"❌ Error fetching/transforming Muse job | Company: {company_name} | ID: {muse_id}")
                return result

            # Insert job into database
            inserted_id = self.db_manager.insert_job(job_mongo)

            if inserted_id:
                # Process and insert job tokens
                token_document = self.parser.process_document(inserted_id, job_mongo)
                token_success = self.db_manager.insert_job_tokens(token_document)

                if token_success:
                    # Remove job from new_jobs
                    self.db_manager.update_muse_company_job_status(unique_name, muse_id)
                    logger.info(f"✅ Job inserted to MongoDB | MongoDB ID: {inserted_id} | Company: {company_name} | Title: {job_mongo.title}")
                    result['status'] = 'inserted'

                    # Index to OpenSearch if enabled
                    if self.opensearch:
                        opensearch_success = self._index_job_to_opensearch(
                            inserted_id, job_mongo, logger
                        )
                        result['opensearch_indexed'] = opensearch_success

                    return result
                else:
                    logger.error(f"❌ Failed to insert tokens for Muse job")
                    return result
            else:
                logger.error(f"❌ Failed to insert Muse job into database")
                return result

        except Exception as e:
            logger.error(f"❌ Error processing Muse job for {company_name}: {e}")
            return result

    def _index_job_to_opensearch(self, job_id: str, job_mongo, logger) -> bool:
        """
        Index a job to OpenSearch

        Args:
            job_id: MongoDB job ID
            job_mongo: JobMongo model instance
            logger: Logger instance

        Returns:
            True if indexed successfully, False otherwise
        """
        try:
            job_dict = job_mongo.model_dump(by_alias=True)
            job_dict['_id'] = job_id

            success = self.opensearch.index_job(job_id, job_dict)

            if success:
                logger.info(f"🔍 Indexed to OpenSearch | MongoDB ID: {job_id} | Title: {job_mongo.title}")
            else:
                logger.warning(f"⚠️ OpenSearch indexing failed | MongoDB ID: {job_id}")

            return success

        except Exception as e:
            logger.error(f"❌ Error indexing Muse job {job_id} to OpenSearch: {e}")
            return False

    def close(self):
        """Close all connections"""
        self.db_manager.close()
        if self.opensearch:
            self.opensearch.close()
