"""
Greenhouse Job Extraction Service with Parallel Processing
"""

import logging
import time
from typing import List, Dict, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from database import DatabaseManager
from parser import JobPostingParser
from greenhouse.greenhouse_api import GreenhouseAPI
from greenhouse.greenhouse_id_maintainer import GreenhouseIDMaintainer
from cache_utils import TTLCache, CacheManager
import config

# Conditionally import OpenSearch
try:
    from opensearch_service import OpenSearchService
    OPENSEARCH_AVAILABLE = True
except ImportError:
    OPENSEARCH_AVAILABLE = False
    logging.warning("OpenSearch not available")


class GreenhouseExtractionService:
    """Main service class for Greenhouse job extraction with parallel processing"""
    
    def __init__(self, enable_opensearch: bool = True, max_workers: int = 20, max_job_workers: int = 10, id_maintenance_workers: int = 20):
        """
        Initialize the service with required components
        
        Args:
            enable_opensearch: Whether to enable OpenSearch indexing (default: True)
            max_workers: Maximum parallel workers for company processing (default: 20, increased from 10)
            max_job_workers: Maximum parallel workers for job processing per company (default: 10, increased from 5)
            id_maintenance_workers: Maximum parallel workers for ID maintenance (default: 20)
        """
        self.db_manager = DatabaseManager()
        self.parser = JobPostingParser()
        self.greenhouse_api = GreenhouseAPI(self.parser)
        self.greenhouse_id_maintainer = GreenhouseIDMaintainer(self.db_manager, max_workers=id_maintenance_workers)
        self.enable_opensearch = enable_opensearch
        self.max_workers = max_workers
        self.max_job_workers = max_job_workers
        
        # Job existence cache: 10 minute TTL, max 5000 entries
        self.job_exists_cache = TTLCache(ttl=600, maxsize=5000)
        CacheManager.register_cache('greenhouse_job_exists', self.job_exists_cache)
        
        logging.info(f"🚀 Greenhouse service initialized:")
        logging.info(f"   - Company workers: {max_workers} (parallel company processing)")
        logging.info(f"   - Job workers: {max_job_workers} (per company)")
        logging.info(f"   - ID maintenance workers: {id_maintenance_workers}")
        logging.info("🎯 Greenhouse service caching enabled")
        
        # Initialize OpenSearch if enabled and available
        self.opensearch = None
        if self.enable_opensearch and OPENSEARCH_AVAILABLE:
            try:
                self.opensearch = OpenSearchService()
                logging.info("OpenSearch integration enabled")
            except Exception as e:
                logging.warning(f"Failed to initialize OpenSearch: {e}")
                logging.warning("Continuing without OpenSearch indexing")
                self.opensearch = None
    
    def run(self):
        """Run the main job extraction process"""
        try:
            logging.info("Starting Greenhouse job extraction process...")
            
            # Step 1: Maintain Greenhouse job IDs (identify new and expired jobs)
            logging.info("🔄 Step 1: Maintaining Greenhouse job IDs in parallel...")
            id_maintenance_stats = self.greenhouse_id_maintainer.maintain_all_company_jobs()
            logging.info(f"✅ ID maintenance completed: {id_maintenance_stats}")
            
            # Step 2: Process companies and scrape job descriptions with parallel processing
            logging.info("🔄 Step 2: Processing company jobs in parallel...")
            stats = self.process_companies_parallel(skip=0, limit=1231)
            
            # Combine statistics
            combined_stats = {
                **stats,
                'id_maintenance': id_maintenance_stats
            }
            
            logging.info("Greenhouse job extraction process completed")
            logging.info(f"Final processing stats: {combined_stats}")
            
            # Save geocoding cache
            logging.info("💾 Saving geocoding cache...")
            self.parser._save_geocoding_cache()
            logging.info(f"✅ Saved {len(self.parser._location_cache)} cached locations")
            
            return combined_stats
            
        except Exception as e:
            logging.error(f"Error in Greenhouse job extraction process: {e}")
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
    
    def process_companies_parallel(self, skip: int = 0, limit: int = 1231) -> Dict:
        """
        Process companies in parallel with specified workers
        
        Args:
            skip: Number of companies to skip
            limit: Maximum number of companies to process
            
        Returns:
            Dictionary with processing statistics
        """
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
        }
        
        try:
            logging.info(f"📊 Fetching companies (skip={skip}, limit={limit})")
            
            # Fetch company data from database
            company_data = self.db_manager.fetch_company_data(skip=skip, limit=limit)
            
            # Early exit: no companies in this batch
            if not company_data:
                logging.info(f"⚡ Early exit: No company data found")
                return stats
            
            logging.info(f"🏢 Processing {len(company_data)} companies in parallel with {self.max_workers} workers...")
            
            # Process companies in parallel
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                # Submit all company processing tasks
                future_to_company = {
                    executor.submit(self._process_company_with_stats, company): company
                    for company in company_data
                }
                
                # Collect results as they complete
                for future in as_completed(future_to_company):
                    company = future_to_company[future]
                    try:
                        company_stats = future.result()
                        
                        # Update batch statistics
                        stats['companies_processed'] += 1
                        stats['jobs_processed'] += company_stats['jobs_processed']
                        stats['jobs_inserted'] += company_stats['jobs_inserted']
                        stats['jobs_existed'] += company_stats['jobs_existed']
                        stats['jobs_failed'] += company_stats['jobs_failed']
                        stats['jobs_not_found'] += company_stats.get('jobs_not_found', 0)
                        stats['jobs_indexed_opensearch'] += company_stats.get('jobs_indexed_opensearch', 0)
                        stats['jobs_opensearch_failed'] += company_stats.get('jobs_opensearch_failed', 0)
                        
                        # Log progress
                        if stats['companies_processed'] % 10 == 0:
                            logging.info(f"Progress: {stats['companies_processed']}/{len(company_data)} companies processed")
                        
                    except Exception as e:
                        logging.error(f"Error processing company {company.get('company', 'Unknown')}: {e}")
                        continue
            
            # Calculate final statistics
            stats['end_time'] = time.time()
            stats['processing_time'] = stats['end_time'] - stats['start_time']
            
            logging.info(f"✅ Parallel processing completed: {stats}")
            return stats
            
        except Exception as e:
            logging.error(f"Parallel processing failed: {e}", exc_info=True)
            stats['error'] = str(e)
            return stats
    
    def _process_company_with_stats(self, record: Dict) -> Dict:
        """
        Process a single company record with parallel job processing
        
        Args:
            record: Company record from database
            
        Returns:
            Dictionary with company-level statistics
        """
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
        unique_name = record.get("unique_name")
        if not company_name or not unique_name:
            logging.warning(f"⚡ Early exit: Missing company name or unique_name")
            return company_stats
        
        # Early exit: no new jobs to process
        new_jobs = record.get("new_jobs", [])
        if not new_jobs:
            logging.debug(f"⚡ Early exit: No new jobs for {company_name}")
            return company_stats
        
        logo = record.get("logo")
        employer_id = record.get("employer_id")
        
        logging.info(f"🏢 Processing {company_name}: {len(new_jobs)} new jobs")
        
        # Process jobs in parallel for this company
        with ThreadPoolExecutor(max_workers=self.max_job_workers) as executor:
            future_to_job = {
                executor.submit(
                    self._process_job_with_stats, 
                    job.get("id"), 
                    unique_name, 
                    company_name, 
                    employer_id, 
                    logo, 
                    job
                ): job
                for job in new_jobs
            }
            
            for future in as_completed(future_to_job):
                job = future_to_job[future]
                company_stats['jobs_processed'] += 1
                
                try:
                    job_result = future.result()
                    
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
                    logging.error(f"Error processing job {job.get('id')}: {e}")
                    company_stats['jobs_failed'] += 1
        
        return company_stats
    
    def _process_job_with_stats(
        self, job_id: int, unique_name: str, company_name: str, 
        employer_id: str, logo: str, job_data: Dict
    ) -> Dict:
        """
        Process a single job and return result status with OpenSearch indexing
        
        Returns:
            Dict with 'status' and 'opensearch_indexed' keys
        """
        result = {
            'status': 'failed',
            'opensearch_indexed': False
        }
        
        # Early exit: missing job ID
        if not job_id:
            logging.warning(f"⚡ Early exit: Job ID missing for {company_name}")
            return result
        
        try:
            # Fetch job data from Greenhouse API
            job_mongo, status = self.greenhouse_api.get_job_from_greenhouse(
                job_id, unique_name, company_name, employer_id, logo
            )
            
            if status == 'NotFound':
                # Remove job from new_jobs if not found (403 error)
                self.db_manager.remove_job_from_new_jobs(company_name, job_id)
                logging.warning(f"🚫 Job {job_id} not found (403) | {company_name}")
                result['status'] = 'not_found'
                return result
            
            elif status == 'Error':
                logging.error(f"❌ Error fetching job {job_id} | {company_name}")
                return result
            
            elif status == 'Success' and job_mongo:
                # Check if job already exists (with caching)
                exists = self.job_exists_cache.get(job_mongo.url)
                if exists is None:
                    exists = self.db_manager.job_exists(job_mongo.url)
                    self.job_exists_cache.set(job_mongo.url, exists)
                    logging.debug(f"📦 Cached job existence check: {job_mongo.url}")
                else:
                    logging.debug(f"🎯 Cache hit for job existence: {job_mongo.url}")
                
                if exists:
                    # Move from new_jobs to jobs
                    self.db_manager.update_company_job_status(unique_name, job_id, job_data)
                    result['status'] = 'existed'
                    return result
                
                # Insert job into database
                inserted_id = self.db_manager.insert_job(job_mongo)
                
                if inserted_id:
                    # Process and insert job tokens
                    token_document = self.parser.process_document(inserted_id, job_mongo)
                    token_success = self.db_manager.insert_job_tokens(token_document)
                    
                    if token_success:
                        # Update company data: move job from new_jobs to jobs
                        self.db_manager.update_company_job_status(unique_name, job_id, job_data)
                        logging.info(f"✅ Job inserted | ID: {inserted_id} | {job_mongo.title}")
                        result['status'] = 'inserted'
                        
                        # Index to OpenSearch if enabled
                        if self.opensearch:
                            opensearch_success = self._index_job_to_opensearch(inserted_id, job_mongo)
                            result['opensearch_indexed'] = opensearch_success
                        
                        return result
                    else:
                        logging.error(f"❌ Failed to insert tokens for job {job_id}")
                        return result
                else:
                    logging.error(f"❌ Failed to insert job {job_id}")
                    return result
            else:
                logging.warning(f"⚠️ Unexpected status for job {job_id}: {status}")
                return result
            
        except Exception as e:
            logging.error(f"❌ Error processing job {job_id} for {company_name}: {e}")
            return result
    
    def _index_job_to_opensearch(self, job_id: str, job_mongo) -> bool:
        """Index a job to OpenSearch"""
        try:
            job_dict = job_mongo.model_dump(by_alias=True)
            job_dict['_id'] = job_id
            
            success = self.opensearch.index_job(job_id, job_dict)
            
            if success:
                logging.debug(f"🔍 Indexed to OpenSearch | {job_id}")
            else:
                logging.warning(f"⚠️ OpenSearch indexing failed | {job_id}")
                
            return success
            
        except Exception as e:
            logging.error(f"❌ Error indexing job {job_id} to OpenSearch: {e}")
            return False
