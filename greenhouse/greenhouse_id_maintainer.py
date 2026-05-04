"""
Greenhouse Job ID Maintenance
Maintains job IDs by comparing current API jobs with stored jobs
Identifies new and expired jobs
"""

import logging
import requests
from typing import Dict, Set, List
from concurrent.futures import ThreadPoolExecutor, as_completed
import sys
import os

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import DatabaseManager


class GreenhouseIDMaintainer:
    """Maintains Greenhouse job IDs for all companies"""
    
    def __init__(self, db_manager: DatabaseManager, max_workers: int = 20):
        """
        Initialize the ID maintainer
        
        Args:
            db_manager: Database manager instance
            max_workers: Maximum parallel workers for ID maintenance (default: 20)
        """
        self.db_manager = db_manager
        self.logger = logging.getLogger(__name__)
        self.max_workers = max_workers
        self.logger.info(f"🔄 Greenhouse ID Maintainer initialized with {max_workers} workers")
    
    def maintain_all_company_jobs(self) -> Dict:
        """
        Maintain job IDs for all companies in parallel
        
        Returns:
            Dictionary with statistics about the maintenance process
        """
        stats = {
            'companies_processed': 0,
            'companies_failed': 0,
            'total_new_jobs': 0,
            'total_expired_jobs': 0,
            'total_current_jobs': 0
        }
        
        self.logger.info(f"🔄 Starting Greenhouse job ID maintenance with {self.max_workers} workers...")
        
        # Fetch all companies
        companies = list(self.db_manager.company_collection.find({}))
        total_companies = len(companies)
        self.logger.info(f"📊 Processing {total_companies} companies in parallel...")
        
        # Process companies in parallel
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_company = {
                executor.submit(self._maintain_company_jobs, company): company
                for company in companies
            }
            
            for future in as_completed(future_to_company):
                company = future_to_company[future]
                try:
                    company_stats = future.result()
                    
                    stats['companies_processed'] += 1
                    stats['total_new_jobs'] += company_stats['new_jobs_count']
                    stats['total_expired_jobs'] += company_stats['expired_jobs_count']
                    stats['total_current_jobs'] += company_stats['current_jobs_count']
                    
                    # Log progress every 50 companies
                    if stats['companies_processed'] % 50 == 0:
                        self.logger.info(
                            f"Progress: {stats['companies_processed']}/{total_companies} companies | "
                            f"New: {stats['total_new_jobs']} | Expired: {stats['total_expired_jobs']}"
                        )
                    
                except Exception as e:
                    stats['companies_failed'] += 1
                    company_name = company.get('company', 'Unknown')
                    self.logger.error(f"Failed to maintain jobs for {company_name}: {e}")
                    continue
        
        self.logger.info(f"✅ Job ID maintenance completed: {stats}")
        return stats
    
    def _maintain_company_jobs(self, company: Dict) -> Dict:
        """
        Maintain job IDs for a single company
        
        Args:
            company: Company document from MongoDB
            
        Returns:
            Dictionary with company-level statistics
        """
        unique_name = company.get('unique_name')
        company_name = company.get('company')
        jobs = company.get('jobs', [])
        
        stats = {
            'new_jobs_count': 0,
            'expired_jobs_count': 0,
            'current_jobs_count': 0
        }
        
        if not unique_name:
            self.logger.warning(f"Company {company_name} has no unique_name")
            return stats
        
        api_url = f"https://boards-api.greenhouse.io/v1/boards/{unique_name}/jobs/"
        
        try:
            # Make GET request to the API with timeout
            response = requests.get(api_url, timeout=15)  # 15 second timeout
            response.raise_for_status()
            
            data = response.json()
            
            # Get current job IDs from API
            current_job_ids = set(job['id'] for job in data.get('jobs', []))
            
            # Get existing job IDs from database
            existing_job_ids = set(job['id'] for job in jobs)
            
            # Identify new and expired jobs
            new_job_ids = current_job_ids - existing_job_ids
            expired_job_ids = existing_job_ids - current_job_ids
            
            stats['new_jobs_count'] = len(new_job_ids)
            stats['expired_jobs_count'] = len(expired_job_ids)
            stats['current_jobs_count'] = len(current_job_ids)
            
            # Update company document
            update_data = {
                "jobs": [{"id": job_id} for job_id in current_job_ids],
                "new_jobs": [{"id": job_id} for job_id in new_job_ids],
                "removed_jobs": [{"id": job_id} for job_id in expired_job_ids]
            }
            
            self.db_manager.company_collection.update_one(
                {"unique_name": unique_name},
                {"$set": update_data}
            )
            
            # Remove expired jobs from jobs collection
            if expired_job_ids:
                for job_id in expired_job_ids:
                    self.db_manager.job_extractions_collection.delete_one({"greenhouse_id": job_id})
                    self.logger.info(f"🗑️  Removed expired job {job_id} from {company_name}")
            
            if new_job_ids or expired_job_ids:
                self.logger.info(
                    f"📊 {company_name}: {len(new_job_ids)} new jobs, "
                    f"{len(expired_job_ids)} expired jobs, "
                    f"{len(current_job_ids)} current jobs"
                )
            
        except requests.exceptions.RequestException as e:
            self.logger.error(f"API request failed for {company_name}: {e}")
            raise
        
        return stats
