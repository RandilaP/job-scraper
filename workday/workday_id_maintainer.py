"""
Workday Job Link Maintenance
Maintains job links by scraping current jobs from Workday career pages
Identifies new and expired job links
Validates existing jobs are still active with async HTTP requests
"""

import logging
import time
import re
import random
import requests
import asyncio
import aiohttp
from typing import Dict, Set, List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager
import sys
import os

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import DatabaseManager


class WorkdayIDMaintainer:
    """Maintains Workday job links for all companies using parallel Selenium instances"""
    
    def __init__(self, db_manager: DatabaseManager, headless: bool = True, max_workers: int = None):
        """
        Initialize the ID maintainer with parallel processing support
        
        Args:
            db_manager: Database manager instance
            headless: Whether to run Chrome in headless mode
            max_workers: Number of parallel Selenium workers (default: from config, was 3)
        """
        self.db_manager = db_manager
        self.logger = logging.getLogger(__name__)
        self.headless = headless
        # Use config value if not specified
        if max_workers is None:
            import config
            max_workers = config.WORKDAY_SELENIUM_WORKERS
        self.max_workers = max_workers
        self.logger.info(f"🔄 Workday ID Maintainer initialized with {max_workers} Selenium workers")
    
    def _create_driver(self, worker_id: int) -> webdriver.Chrome:
        """
        Create a Selenium Chrome driver for a worker
        
        Args:
            worker_id: ID of the worker (for logging)
            
        Returns:
            Chrome WebDriver instance
        """
        try:
            options = webdriver.ChromeOptions()
            if self.headless:
                options.add_argument("--headless")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-gpu")
            options.add_argument("--window-size=1920,1080")
            options.add_argument(f"--user-data-dir=/tmp/chrome_worker_{worker_id}")  # Separate profile per worker
            
            driver = webdriver.Chrome(
                service=Service(ChromeDriverManager().install()), 
                options=options
            )
            self.logger.info(f"Worker {worker_id}: Selenium WebDriver initialized")
            return driver
        except Exception as e:
            self.logger.error(f"Worker {worker_id}: Failed to initialize WebDriver: {e}")
            raise
    
    def maintain_all_company_jobs(self) -> Dict:
        """
        Maintain job links for all Workday companies using parallel Selenium workers
        
        Returns:
            Dictionary with statistics about the maintenance process
        """
        stats = {
            'companies_processed': 0,
            'companies_failed': 0,
            'total_new_jobs': 0,
            'total_expired_jobs': 0,
            'total_current_jobs': 0,
            'total_validated_jobs': 0,
            'total_removed_inactive': 0
        }
        
        self.logger.info(f"🔄 Starting Workday job link maintenance with {self.max_workers} parallel workers...")
        
        try:
            # Fetch all Workday companies
            companies = list(self.db_manager.workday_company_collection.find({}))
            total_companies = len(companies)
            
            if total_companies == 0:
                self.logger.warning("No Workday companies found in database")
                return stats
            
            self.logger.info(f"Found {total_companies} Workday companies to process")
            
            # Process companies in parallel using ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                # Create worker futures
                futures = []
                for worker_id in range(self.max_workers):
                    # Calculate which companies this worker should process
                    worker_companies = companies[worker_id::self.max_workers]
                    
                    if worker_companies:
                        future = executor.submit(
                            self._process_companies_worker,
                            worker_id,
                            worker_companies
                        )
                        futures.append(future)
                
                # Collect results from all workers
                for future in as_completed(futures):
                    try:
                        worker_stats = future.result()
                        
                        # Aggregate statistics
                        stats['companies_processed'] += worker_stats['companies_processed']
                        stats['companies_failed'] += worker_stats['companies_failed']
                        stats['total_new_jobs'] += worker_stats['total_new_jobs']
                        stats['total_expired_jobs'] += worker_stats['total_expired_jobs']
                        stats['total_current_jobs'] += worker_stats['total_current_jobs']
                        
                    except Exception as e:
                        self.logger.error(f"Worker failed with error: {e}")
            
            self.logger.info(f"✅ Parallel processing completed: {stats}")
            
            # Validate existing jobs in database (after all workers complete)
            validation_stats = self._validate_existing_jobs()
            stats['total_validated_jobs'] = validation_stats['validated']
            stats['total_removed_inactive'] = validation_stats['removed']
            
            self.logger.info(f"✅ Workday job link maintenance completed: {stats}")
            
        except Exception as e:
            self.logger.error(f"Error in maintenance process: {e}")
            raise
        
        return stats
    
    def _process_companies_worker(self, worker_id: int, companies: List[Dict]) -> Dict:
        """
        Worker function that processes multiple companies with a reused browser session
        
        Args:
            worker_id: ID of this worker
            companies: List of company documents to process
            
        Returns:
            Dictionary with worker statistics
        """
        worker_stats = {
            'companies_processed': 0,
            'companies_failed': 0,
            'total_new_jobs': 0,
            'total_expired_jobs': 0,
            'total_current_jobs': 0
        }
        
        driver = None
        
        try:
            # Create driver for this worker (reused for all companies)
            driver = self._create_driver(worker_id)
            
            self.logger.info(f"Worker {worker_id}: Processing {len(companies)} companies")
            
            for idx, company in enumerate(companies, 1):
                try:
                    company_name = company.get('company', 'Unknown')
                    self.logger.info(f"Worker {worker_id}: [{idx}/{len(companies)}] Processing {company_name}")
                    
                    # Process company with reused driver
                    company_stats = self._maintain_company_jobs_with_driver(driver, company, worker_id)
                    
                    worker_stats['companies_processed'] += 1
                    worker_stats['total_new_jobs'] += company_stats['new_jobs_count']
                    worker_stats['total_expired_jobs'] += company_stats['expired_jobs_count']
                    worker_stats['total_current_jobs'] += company_stats['current_jobs_count']
                    
                except Exception as e:
                    worker_stats['companies_failed'] += 1
                    company_name = company.get('company', 'Unknown')
                    self.logger.error(f"Worker {worker_id}: Failed to process {company_name}: {e}")
                    continue
            
            self.logger.info(f"Worker {worker_id}: Completed - {worker_stats}")
            
        except Exception as e:
            self.logger.error(f"Worker {worker_id}: Critical error: {e}")
            raise
        
        finally:
            # Clean up driver
            if driver:
                try:
                    driver.quit()
                    self.logger.info(f"Worker {worker_id}: Browser closed")
                except Exception as e:
                    self.logger.warning(f"Worker {worker_id}: Error closing browser: {e}")
        
        return worker_stats
    
    def _maintain_company_jobs_with_driver(self, driver: webdriver.Chrome, company: Dict, worker_id: int) -> Dict:
        """
        Maintain job links for a single company using provided driver
        
        Args:
            driver: Selenium WebDriver instance
            company: Company document from MongoDB
            worker_id: ID of the worker (for logging)
            
        Returns:
            Dictionary with company-level statistics
        """
        company_name = company.get('company')
        base_url = company.get('base_url')
        job_links = company.get('job_links', [])
        
        stats = {
            'new_jobs_count': 0,
            'expired_jobs_count': 0,
            'current_jobs_count': 0
        }
        
        # Early exit: missing company name
        if not company_name:
            self.logger.warning(f"Worker {worker_id}: ⚡ Early exit: Company name missing")
            return stats
        
        # Early exit: missing base URL
        if not base_url:
            self.logger.warning(f"Worker {worker_id}: ⚡ Early exit: {company_name} has no base_url")
            return stats
        
        try:
            # Scrape current job links from Workday
            current_job_links = self._scrape_job_links_with_driver(driver, base_url, company_name, worker_id)
            
            # Early exit: no jobs found (likely invalid URL or empty careers page)
            if not current_job_links:
                self.logger.warning(f"Worker {worker_id}: ⚡ Early exit: No jobs found for {company_name}")
                return stats
            
            # Convert to sets for comparison
            current_job_set = set(current_job_links)
            existing_job_set = set(job_links)
            
            # Identify new and expired jobs
            new_job_links = current_job_set - existing_job_set
            expired_job_links = existing_job_set - current_job_set
            
            stats['new_jobs_count'] = len(new_job_links)
            stats['expired_jobs_count'] = len(expired_job_links)
            stats['current_jobs_count'] = len(current_job_set)
            
            # Update company document
            update_data = {
                "job_links": list(current_job_set),
                "new_job_links": list(new_job_links),
                "removed_job_links": list(expired_job_links)
            }
            
            self.db_manager.workday_company_collection.update_one(
                {"company": company_name},
                {"$set": update_data}
            )
            
            # Remove expired jobs from jobs collection
            if expired_job_links:
                deleted_count = self.db_manager.bulk_delete_jobs_by_ids(
                    list(expired_job_links), 
                    id_field='url'
                )
                self.logger.info(f"Worker {worker_id}: 🗑️  Bulk deleted {deleted_count} expired jobs from {company_name}")
            
            if new_job_links or expired_job_links:
                self.logger.info(
                    f"Worker {worker_id}: 📊 {company_name}: {len(new_job_links)} new jobs, "
                    f"{len(expired_job_links)} expired jobs, "
                    f"{len(current_job_set)} current jobs"
                )
            
        except Exception as e:
            self.logger.error(f"Worker {worker_id}: Error maintaining jobs for {company_name}: {e}")
            raise
        
        return stats
    
    def _scrape_job_links_with_driver(
        self, 
        driver: webdriver.Chrome, 
        base_url: str, 
        company_name: str, 
        worker_id: int
    ) -> List[str]:
        """
        Scrape all job links from a Workday career page using provided driver
        
        Args:
            driver: Selenium WebDriver instance
            base_url: Base URL of the Workday career page
            company_name: Name of the company (for logging)
            worker_id: ID of the worker (for logging)
            
        Returns:
            List of job links
        """
        job_links = []
        
        try:
            self.logger.info(f"Worker {worker_id}: 🌐 Scraping {company_name}: {base_url}")
            driver.get(base_url)
            
            page_num = 1
            while True:
                try:
                    # Wait for job listings to load
                    WebDriverWait(driver, 10).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "#mainContent > div > div > section > ul"))
                    )
                    
                    # Get all job listing links on the current page
                    job_elements = driver.find_elements(
                        By.CSS_SELECTOR, 
                        "#mainContent > div > div > section > ul > li > div > div > div > h3 > a"
                    )
                    
                    page_job_count = 0
                    for job_element in job_elements:
                        job_link = job_element.get_attribute("href")
                        if job_link and job_link not in job_links:
                            job_links.append(job_link)
                            page_job_count += 1
                    
                    self.logger.info(f"Worker {worker_id}: 📄 {company_name} page {page_num}: {page_job_count} jobs")
                    
                    # Check if the "Next" button is present and enabled
                    try:
                        next_button = WebDriverWait(driver, 2).until(
                            EC.element_to_be_clickable((By.XPATH, "//button[@aria-label='next']"))
                        )
                        next_button.click()
                        # Reduced sleep from 2 to 0.5 seconds - WebDriverWait handles most waiting
                        time.sleep(0.5)
                        page_num += 1
                    except TimeoutException:
                        self.logger.info(f"Worker {worker_id}: ✅ {company_name}: {len(job_links)} total jobs")
                        break
                    
                except Exception as e:
                    self.logger.warning(f"Worker {worker_id}: Error on page {page_num} for {company_name}: {e}")
                    break
            
        except Exception as e:
            self.logger.error(f"Worker {worker_id}: Failed to scrape {base_url}: {e}")
            raise
        
        return job_links
    
    async def _is_job_active_async(self, session: aiohttp.ClientSession, url: str) -> tuple[str, bool]:
        """
        Async check if a Workday job is still active
        
        Args:
            session: aiohttp ClientSession
            url: Job URL to check
            
        Returns:
            Tuple of (url, is_active)
        """
        if not url:
            return (url, False)
        
        # Create a modified URL to check job status via the API
        modified_url = re.sub(
            r"(https://)(\w+)(\.wd\d+\.myworkdayjobs\.com/)(en-US)(/)", 
            r"\1\2\3wday/cxs/\2/", 
            url
        )
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Accept": "application/json"
        }
        
        try:
            async with session.get(modified_url, headers=headers, timeout=aiohttp.ClientTimeout(total=5)) as response:
                # HTTP status codes that indicate job is no longer active
                if response.status in [403, 404]:
                    return (url, False)
                
                # If we get a successful response, job is likely active
                if response.status == 200:
                    return (url, True)
                
                # Assume active if uncertain
                return (url, True)
                
        except Exception as e:
            # Assume active if there's an error
            return (url, True)
    
    async def _validate_jobs_batch_async(self, jobs: List[Dict]) -> Dict:
        """
        Validate a batch of jobs asynchronously
        
        Args:
            jobs: List of job documents from MongoDB
            
        Returns:
            Dictionary with validation results
        """
        if not jobs:
            return {'validated': 0, 'inactive_jobs': []}
        
        # Create async HTTP session with optimized connection pooling
        connector = aiohttp.TCPConnector(limit=100, limit_per_host=20)  # Increased from 50/10
        timeout = aiohttp.ClientTimeout(total=15)  # Reduced from 30 to 15
        
        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            # Create tasks for all jobs
            tasks = [
                self._is_job_active_async(session, job.get('url'))
                for job in jobs
            ]
            
            # Execute all tasks concurrently
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Find inactive jobs
            inactive_jobs = []
            for idx, result in enumerate(results):
                if isinstance(result, Exception):
                    # Error occurred, assume job is active
                    continue
                    
                url, is_active = result
                if not is_active:
                    inactive_jobs.append({
                        '_id': jobs[idx].get('_id'),
                        'url': url,
                        'title': jobs[idx].get('title', 'Unknown')
                    })
            
            return {
                'validated': len(jobs),
                'inactive_jobs': inactive_jobs
            }
    
    def _validate_existing_jobs(self) -> Dict:
        """
        Validate existing Workday jobs in the database with async HTTP requests
        Remove jobs that are no longer active using bulk operations
        
        Returns:
            Dictionary with validation statistics
        """
        self.logger.info("🔍 Validating existing Workday jobs in database (async)...")
        
        stats = {
            'validated': 0,
            'removed': 0
        }
        
        # Find all Workday jobs
        workday_query = {"url": {"$regex": "myworkdayjobs\\.com"}}
        total_jobs = self.db_manager.job_extractions_collection.count_documents(workday_query)
        
        self.logger.info(f"Found {total_jobs} Workday jobs to validate")
        
        # Early exit: no jobs to validate
        if total_jobs == 0:
            self.logger.info("⚡ Early exit: No Workday jobs to validate")
            return stats
        
        # Process in larger batches with optimized async validation
        batch_size = 200  # Increased from 100 to 200 with higher connection limits
        all_inactive_jobs = []
        
        for skip in range(0, total_jobs, batch_size):
            batch = list(
                self.db_manager.job_extractions_collection
                .find(workday_query)
                .skip(skip)
                .limit(batch_size)
            )
            
            self.logger.info(f"Validating batch of {len(batch)} jobs (skip={skip})...")
            
            # Run async validation
            batch_results = asyncio.run(self._validate_jobs_batch_async(batch))
            
            stats['validated'] += batch_results['validated']
            all_inactive_jobs.extend(batch_results['inactive_jobs'])
            
            self.logger.info(
                f"Batch complete: {batch_results['validated']} validated, "
                f"{len(batch_results['inactive_jobs'])} inactive"
            )
        
        # Bulk delete all inactive jobs
        if all_inactive_jobs:
            inactive_ids = [str(job['_id']) for job in all_inactive_jobs]
            deleted_count = self.db_manager.bulk_delete_jobs_by_ids(inactive_ids, id_field='_id')
            stats['removed'] = deleted_count
            
            self.logger.info(f"🗑️  Bulk deleted {deleted_count} inactive jobs")
            
            # Log sample of removed jobs
            for job in all_inactive_jobs[:5]:
                self.logger.info(f"  - Removed: {job['title']}")
        
        self.logger.info(
            f"✅ Job validation complete: {stats['validated']} validated, "
            f"{stats['removed']} inactive jobs removed"
        )
        
        return stats

