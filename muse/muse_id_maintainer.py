"""
Muse ID Maintainer

Maintains job IDs for Muse companies by comparing current API data
with stored data in museCompanyData. Identifies new and removed jobs,
and handles removal of expired jobs from JobsDB.

Uses UsersDB.employers as the source of Muse companies, then updates
GreenhouseDB.museCompanyData with current job IDs.
"""
import logging
import time
import requests
from typing import Dict, Set, Optional, List, Any
from datetime import datetime, timezone
from bson import ObjectId

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import DatabaseManager
import config


class MuseIDMaintainer:
    """Maintains Muse job IDs by syncing with the Muse API"""

    def __init__(self, db_manager: DatabaseManager):
        """
        Initialize Muse ID maintainer

        Args:
            db_manager: Shared DatabaseManager instance
        """
        self.db_manager = db_manager
        self.logger = logging.getLogger(__name__)
        self.base_url = config.MUSE_API_BASE_URL
        self.api_key = config.MUSE_API_KEY

    def _get_api_params(self) -> Dict:
        """Get API parameters including API key if available"""
        params = {}
        if self.api_key:
            params['api_key'] = self.api_key
        return params

    def maintain_all_companies(self, limit_companies: Optional[int] = None) -> Dict:
        """
        Run ID maintenance for all Muse companies.

        Reads from UsersDB.employers (where muse_company_id exists),
        compares API job IDs with stored museCompanyData, and handles
        new/removed jobs.

        Args:
            limit_companies: Optional limit for testing (set to None for production)

        Returns:
            Dictionary with aggregate maintenance statistics
        """
        self.logger.info("Starting Muse ID maintenance...")

        stats = {
            'companies_processed': 0,
            'new_jobs_total': 0,
            'expired_jobs_total': 0,
            'current_jobs_total': 0,
            'errors': 0
        }

        # Find all employers with muse_company_id
        query = {"muse_company_id": {"$exists": True, "$ne": None}}
        employers = list(self.db_manager.employers_collection.find(query))

        if limit_companies:
            employers = employers[:limit_companies]
            self.logger.info(f"⚠️  TEST MODE: Limited to {limit_companies} companies")

        self.logger.info(f"Found {len(employers)} employers with Muse IDs to maintain")

        for idx, employer in enumerate(employers, 1):
            try:
                company_stats = self._maintain_company_jobs(employer, idx, len(employers))

                stats['companies_processed'] += 1
                stats['new_jobs_total'] += company_stats['new_jobs_count']
                stats['expired_jobs_total'] += company_stats['expired_jobs_count']
                stats['current_jobs_total'] += company_stats['current_jobs_count']

            except Exception as e:
                self.logger.error(f"Error maintaining company {employer.get('full_name', 'Unknown')}: {e}")
                stats['errors'] += 1

            # Rate limiting
            time.sleep(0.5)

        self.logger.info(
            f"\n📊 Muse ID Maintenance Complete:\n"
            f"  Companies processed: {stats['companies_processed']}\n"
            f"  New jobs found: {stats['new_jobs_total']}\n"
            f"  Expired jobs removed: {stats['expired_jobs_total']}\n"
            f"  Current jobs total: {stats['current_jobs_total']}\n"
            f"  Errors: {stats['errors']}"
        )

        return stats

    def _maintain_company_jobs(self, employer: Dict, idx: int, total: int) -> Dict:
        """
        Maintain job IDs for a single company.

        Compares current API job IDs with stored museCompanyData,
        identifies new/removed jobs, updates the collection, and
        removes expired jobs from JobsDB.

        Args:
            employer: Employer document from UsersDB.employers
            idx: Current index for logging
            total: Total companies for logging

        Returns:
            Dictionary with company-level statistics
        """
        employer_id = str(employer['_id'])
        company_name = employer.get('full_name')
        muse_short_name = employer.get('muse_short_name')
        logo_url = employer.get('logo_url')

        stats = {
            'new_jobs_count': 0,
            'expired_jobs_count': 0,
            'current_jobs_count': 0
        }

        if not company_name:
            self.logger.warning(f"Employer {employer_id} has no full_name, skipping")
            return stats

        self.logger.info(f"[{idx}/{total}] Processing '{company_name}'")

        # Fetch current job IDs from Muse API
        current_job_ids = self._fetch_company_job_ids(company_name)
        self.logger.info(f"  Found {len(current_job_ids)} jobs on Muse API")

        stats['current_jobs_count'] = len(current_job_ids)

        # Get existing company data from museCompanyData
        existing_data = self.db_manager.muse_company_collection.find_one(
            {"unique_name": muse_short_name}
        )

        if existing_data:
            # Get existing job IDs
            existing_job_ids = set(job.get('id') for job in existing_data.get('jobs', []))

            # Calculate new and removed jobs
            new_job_ids = current_job_ids - existing_job_ids
            removed_job_ids = existing_job_ids - current_job_ids

            stats['new_jobs_count'] = len(new_job_ids)
            stats['expired_jobs_count'] = len(removed_job_ids)

            self.logger.info(f"  New jobs: {len(new_job_ids)}, Removed jobs: {len(removed_job_ids)}")

            # Update the document
            self.db_manager.muse_company_collection.update_one(
                {"unique_name": muse_short_name},
                {
                    "$set": {
                        "company": company_name,
                        "logo": logo_url,
                        "employer_id": employer_id,
                        "jobs": [{"id": job_id} for job_id in current_job_ids],
                        "new_jobs": [{"id": job_id} for job_id in new_job_ids],
                        "removed_jobs": [{"id": job_id} for job_id in removed_job_ids],
                        "updated_date": datetime.now(timezone.utc)
                    }
                }
            )

            # Remove expired jobs from JobsDB.jobs
            if removed_job_ids:
                self._remove_expired_jobs(removed_job_ids, company_name)

        else:
            # First time — all jobs are "new"
            self.logger.info(f"  First sync — all {len(current_job_ids)} jobs are new")

            self.db_manager.muse_company_collection.insert_one({
                "_id": ObjectId(),
                "unique_name": muse_short_name,
                "company": company_name,
                "logo": logo_url,
                "employer_id": employer_id,
                "jobs": [{"id": job_id} for job_id in current_job_ids],
                "new_jobs": [{"id": job_id} for job_id in current_job_ids],
                "removed_jobs": [],
                "inserted_date": datetime.now(timezone.utc),
                "updated_date": datetime.now(timezone.utc)
            })

            stats['new_jobs_count'] = len(current_job_ids)

        return stats

    def _fetch_company_job_ids(self, company_full_name: str) -> Set[int]:
        """
        Fetch all job IDs for a company from Muse API.
        Uses the FULL company name for the API filter.

        Args:
            company_full_name: Full company name (e.g., "Modern Animal, Inc.")

        Returns:
            Set of job IDs currently available on Muse for this company
        """
        all_job_ids = set()
        page = 0

        while True:
            params = self._get_api_params()
            params['page'] = page
            params['company'] = company_full_name

            url = f"{self.base_url}/jobs"

            try:
                response = requests.get(url, params=params, timeout=30)
                response.raise_for_status()
                data = response.json()

                results = data.get('results', [])
                if not results:
                    break

                for job in results:
                    job_id = job.get('id')
                    if job_id:
                        all_job_ids.add(job_id)

                # Check if we've reached the last page
                current_page = data.get('page', 0)
                total_pages = data.get('page_count', 1)

                if current_page >= total_pages - 1:
                    break

                page += 1
                time.sleep(0.2)  # Rate limiting

            except requests.exceptions.RequestException as e:
                self.logger.error(f"Error fetching jobs for '{company_full_name}' page {page}: {e}")
                break

        return all_job_ids

    def _remove_expired_jobs(self, expired_job_ids: Set[int], company_name: str):
        """
        Remove expired jobs from JobsDB.jobs by muse_id.
        Same pattern as greenhouse_id_maintainer deleting by greenhouse_id.

        Args:
            expired_job_ids: Set of muse job IDs to remove
            company_name: Company name for logging
        """
        for job_id in expired_job_ids:
            try:
                result = self.db_manager.job_extractions_collection.delete_one({"muse_id": job_id})
                if result.deleted_count:
                    self.logger.info(f"  🗑️  Removed expired Muse job {job_id} from {company_name}")
            except Exception as e:
                self.logger.error(f"  Error removing Muse job {job_id}: {e}")
