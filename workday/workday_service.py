"""
Workday job extraction service
"""

import logging
import time
from typing import List, Dict
import sys
import os

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import DatabaseManager
from parser import JobPostingParser
from workday.workday_api import WorkdayAPI
from workday.workday_id_maintainer import WorkdayIDMaintainer
from cache_utils import TTLCache, CacheManager
import config

class WorkdayExtractionService:
    """Service class for Workday job extraction with parallel Selenium support"""
    
    def __init__(self, enable_opensearch: bool = True, headless: bool = True, max_selenium_workers: int = None):
        """
        Initialize the Workday extraction service
        
        Args:
            enable_opensearch: Whether to enable OpenSearch indexing
            headless: Whether to run Selenium in headless mode
            max_selenium_workers: Number of parallel Selenium workers for ID maintenance (default: from config)
        """
        # Use config value if not specified
        if max_selenium_workers is None:
            max_selenium_workers = config.WORKDAY_SELENIUM_WORKERS
        
        self.db_manager = DatabaseManager()
        self.parser = JobPostingParser()
        self.workday_api = WorkdayAPI(self.parser)
        self.workday_id_maintainer = WorkdayIDMaintainer(
            self.db_manager, 
            headless=headless,
            max_workers=max_selenium_workers
        )
        self.enable_opensearch = enable_opensearch
        self.max_selenium_workers = max_selenium_workers
        
        # Job existence cache: 10 minute TTL, max 5000 entries
        self.job_exists_cache = TTLCache(ttl=600, maxsize=5000)
        CacheManager.register_cache('workday_job_exists', self.job_exists_cache)
        
        # Company data cache: 30 minute TTL, max 500 entries
        self.company_cache = TTLCache(ttl=1800, maxsize=500)
        CacheManager.register_cache('workday_company_data', self.company_cache)
        
        logging.info(f"🚀 Workday service initialized:")
        logging.info(f"   - Selenium workers: {max_selenium_workers} (parallel ID maintenance)")
        logging.info(f"   - Job processing workers: {config.WORKDAY_PARALLEL_WORKERS}")
        logging.info(f"   - Batch size: {config.WORKDAY_BATCH_SIZE}")
        logging.info("🎯 Workday service caching enabled")
        
        # Initialize OpenSearch if enabled
        self.opensearch = None
        if self.enable_opensearch:
            try:
                from opensearch_service import OpenSearchService
                self.opensearch = OpenSearchService()
                logging.info("OpenSearch integration enabled for Workday")
            except Exception as e:
                logging.warning(f"Failed to initialize OpenSearch: {e}")
                logging.warning("Continuing without OpenSearch indexing")
                self.opensearch = None
    
    def run(self):
        """Run the main Workday job extraction process"""
        try:
            logging.info("Starting Workday job extraction process...")
            
            # Step 1: Maintain Workday job links (identify new and expired jobs)
            logging.info("🔄 Step 1: Maintaining Workday job links...")
            id_maintenance_stats = self.workday_id_maintainer.maintain_all_company_jobs()
            logging.info(f"✅ ID maintenance completed: {id_maintenance_stats}")
            
            # Step 2: Process companies and scrape job descriptions
            logging.info("🔄 Step 2: Processing company jobs...")
            
            # Use configured batch size
            batch_size = config.WORKDAY_BATCH_SIZE
            
            logging.info(f"Processing Workday companies in batches of {batch_size}")
            logging.info(f"Using {config.WORKDAY_PARALLEL_WORKERS} parallel workers for job processing")
            
            # Process all companies in batches
            skip = 0
            total_stats = {
                'companies_processed': 0,
                'jobs_processed': 0,
                'jobs_inserted': 0,
                'jobs_existed': 0,
                'jobs_failed': 0,
                'jobs_indexed_opensearch': 0,
                'jobs_opensearch_failed': 0
            }
            
            batch_num = 1
            while True:
                logging.info(f"\n{'='*60}")
                logging.info(f"🔄 Starting batch {batch_num} (skip={skip}, limit={batch_size})")
                logging.info(f"{'='*60}")
                
                batch_stats = self.process_companies_batch(skip=skip, limit=batch_size, batch_id=batch_num)
                
                # Early exit: no companies processed (end of data)
                if batch_stats['companies_processed'] == 0:
                    logging.info(f"⚡ Early exit: No more companies to process")
                    break
                
                # Aggregate statistics
                for key in ['companies_processed', 'jobs_processed', 'jobs_inserted', 
                           'jobs_existed', 'jobs_failed', 'jobs_indexed_opensearch', 
                           'jobs_opensearch_failed']:
                    total_stats[key] += batch_stats.get(key, 0)
                
                # Early exit: processed fewer companies than batch size (last batch)
                if batch_stats['companies_processed'] < batch_size:
                    logging.info(f"✅ Processed final batch with {batch_stats['companies_processed']} companies")
                    break
                
                skip += batch_size
                batch_num += 1
            
            # Combine statistics
            combined_stats = {
                **total_stats,
                'id_maintenance': id_maintenance_stats
            }
            
            logging.info("\n" + "="*60)
            logging.info("🎉 Workday job extraction process completed")
            logging.info(f"📊 Final Workday processing stats: {combined_stats}")
            logging.info("="*60)
            
            # Save geocoding cache
            logging.info("💾 Saving geocoding cache...")
            self.parser._save_geocoding_cache()
            logging.info(f"✅ Saved {len(self.parser._location_cache)} cached locations")
            
            return combined_stats
            
        except Exception as e:
            logging.error(f"Error in Workday job extraction process: {e}")
            # Save cache even on error
            try:
                self.parser._save_geocoding_cache()
            except:
                pass
            raise
        finally:
            # Clean up connections
            self.db_manager.close()
            if self.opensearch:
                self.opensearch.close()
    
    def process_companies_batch(self, skip: int = 0, limit: int = 100, batch_id: int = None) -> Dict:
        """Process a batch of Workday companies and return detailed statistics"""
        batch_logger = logging.getLogger(f"workday_batch_{batch_id}" if batch_id else "workday_service")
        
        # Initialize statistics
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
            'source': 'workday'
        }
        
        try:
            batch_logger.info(f"📊 Fetching Workday companies (skip={skip}, limit={limit})")
            
            # Fetch company data from database
            company_data = self.db_manager.fetch_workday_company_data(skip=skip, limit=limit)
            
            # Early exit: no companies in this batch
            if not company_data:
                batch_logger.info(f"⚡ Early exit: No Workday company data found for this batch")
                return stats
            
            batch_logger.info(f"🏢 Processing {len(company_data)} Workday companies...")
            
            # Process each company
            for idx, record in enumerate(company_data, 1):
                try:
                    company_name = record.get("company", "Unknown")
                    new_job_count = len(record.get("new_job_links", []))
                    
                    # Log progress every 10 companies or if company has jobs
                    if idx % 10 == 0 or new_job_count > 0:
                        batch_logger.info(f"[{idx}/{len(company_data)}] Processing {company_name} ({new_job_count} jobs)")
                    
                    company_stats = self._process_company_with_stats(record, batch_logger)
                    
                    # Update batch statistics
                    stats['companies_processed'] += 1
                    stats['jobs_processed'] += company_stats['jobs_processed']
                    stats['jobs_inserted'] += company_stats['jobs_inserted']
                    stats['jobs_existed'] += company_stats['jobs_existed']
                    stats['jobs_failed'] += company_stats['jobs_failed']
                    stats['jobs_not_found'] += company_stats.get('jobs_not_found', 0)
                    stats['jobs_indexed_opensearch'] += company_stats.get('jobs_indexed_opensearch', 0)
                    stats['jobs_opensearch_failed'] += company_stats.get('jobs_opensearch_failed', 0)
                    
                except Exception as e:
                    batch_logger.error(f"Error processing Workday company {record.get('company', 'Unknown')}: {e}")
                    continue
            
            # Calculate final statistics
            stats['end_time'] = time.time()
            stats['processing_time'] = stats['end_time'] - stats['start_time']
            
            batch_logger.info(f"✅ Workday batch processing completed: {stats}")
            return stats
            
        except Exception as e:
            batch_logger.error(f"Workday batch processing failed: {e}", exc_info=True)
            stats['error'] = str(e)
            return stats
    
    def _process_company_with_stats(self, record: Dict, logger) -> Dict:
        """Process a single Workday company record and return statistics"""
        company_stats = {
            'jobs_processed': 0,
            'jobs_inserted': 0,
            'jobs_existed': 0,
            'jobs_failed': 0,
            'jobs_not_found': 0,
            'jobs_indexed_opensearch': 0,
            'jobs_opensearch_failed': 0
        }

        # Early exit: missing required company data
        company_name = record.get("company")
        if not company_name:
            logger.warning("⚡ Early exit: Company name missing")
            return company_stats
        
        # Early exit: no new jobs to process
        new_job_links = record.get("new_job_links", [])
        if not new_job_links:
            logger.debug(f"⚡ Early exit: No new job links for {company_name}")
            return company_stats
        
        logo = record.get("logo")
        employer_id = record.get("employer_id")
        
        logger.info(f"🏢 Processing Workday company {company_name}: {len(new_job_links)} new jobs")
        
        for job_link in new_job_links:
            company_stats['jobs_processed'] += 1
            
            try:
                job_result = self._process_job_with_stats(
                    job_link, company_name, employer_id, logo, logger
                )
                
                # Update company statistics based on job result
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
                logger.error(f"Error processing Workday job {job_link}: {e}")
                company_stats['jobs_failed'] += 1
        
        return company_stats
    
    def _process_job_with_stats(
        self, job_link: str, company_name: str, employer_id: str, logo: str, logger
    ) -> Dict:
        """
        Process a single Workday job and return result status
        
        Returns:
            Dict with 'status' and 'opensearch_indexed' keys
        """
        result = {
            'status': 'failed',
            'opensearch_indexed': False
        }
        
        # Early exit: missing job link
        if not job_link:
            logger.warning("Job link is missing")
            return result
        
        # Early exit: job already exists (skip expensive API call)
        # Check cache first, then database
        exists = self.job_exists_cache.get(job_link)
        if exists is None:
            # Not in cache, check database
            exists = self.db_manager.job_exists(job_link)
            self.job_exists_cache.set(job_link, exists)
            logger.debug(f"📦 Cached job existence check: {job_link}")
        else:
            logger.debug(f"🎯 Cache hit for job existence: {job_link}")
        
        if exists:
            logger.info(f"⚡ Job already exists (early exit) | Company: {company_name} | URL: {job_link[:80]}...")
            # Move from new_job_links to job_links
            self.db_manager.update_workday_company_job_status(company_name, job_link)
            result['status'] = 'existed'
            return result
        
        logger.info(f"💼 Processing Workday job | Company: {company_name} | URL: {job_link[:80]}...")
        
        try:
            # Fetch job data from Workday API
            job_mongo, status = self.workday_api.get_job_from_workday(
                job_link, company_name, employer_id, logo
            )
            
            if status == 'NotFound':
                # Remove job link from new_job_links if not found
                self.db_manager.remove_workday_job_from_new_links(company_name, job_link)
                logger.warning(f"🚫 Workday job not found | Company: {company_name} | Removed from new_job_links")
                result['status'] = 'not_found'
                return result
            
            elif status == 'Error':
                logger.error(f"❌ Error fetching Workday job from API | Company: {company_name}")
                return result
            
            elif status == 'Success' and job_mongo:
                # Check if job already exists (with caching)
                exists = self.job_exists_cache.get(job_mongo.url)
                if exists is None:
                    exists = self.db_manager.job_exists(job_mongo.url)
                    self.job_exists_cache.set(job_mongo.url, exists)
                
                if exists:
                    logger.info(f"🔄 Job already exists | Company: {company_name} | Title: {job_mongo.title} | URL: {job_mongo.url}")
                    # Move from new_job_links to job_links
                    self.db_manager.update_workday_company_job_status(company_name, job_link)
                    result['status'] = 'existed'
                    return result
                
                # Insert job into database
                inserted_id = self.db_manager.insert_job(job_mongo)
                
                if inserted_id:
                    # Process and insert job tokens
                    token_document = self.parser.process_document(inserted_id, job_mongo)
                    token_success = self.db_manager.insert_job_tokens(token_document)
                    
                    if token_success:
                        # Update company data: move job link from new_job_links to job_links
                        self.db_manager.update_workday_company_job_status(company_name, job_link)
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
                        logger.error(f"❌ Failed to insert tokens for Workday job")
                        return result
                else:
                    logger.error(f"❌ Failed to insert Workday job into database")
                    return result
            else:
                logger.warning(f"⚠️ Unexpected status for Workday job: {status}")
                return result
            
        except Exception as e:
            logger.error(f"❌ Error processing Workday job for {company_name}: {e}")
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
            # Convert Pydantic model to dict
            job_dict = job_mongo.model_dump(by_alias=True)
            job_dict['_id'] = job_id
            
            # Index to OpenSearch
            success = self.opensearch.index_job(job_id, job_dict)
            
            if success:
                logger.info(f"🔍 Indexed to OpenSearch | MongoDB ID: {job_id} | Title: {job_mongo.title}")
            else:
                logger.warning(f"⚠️ OpenSearch indexing failed | MongoDB ID: {job_id}")
                
            return success
            
        except Exception as e:
            logger.error(f"❌ Error indexing Workday job {job_id} to OpenSearch: {e}")
            return False
    
    def close(self):
        """Close all connections"""
        self.db_manager.close()
        if self.opensearch:
            self.opensearch.close()
