"""
Muse API integration for job extraction

Handles fetching jobs from The Muse public API and transforming
raw API responses into JobMongo objects for storage.
"""
import logging
import requests
from typing import Dict, Optional, Tuple, List, Any
from datetime import datetime, timezone

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import JobMongo, generate_redirect_path
from parser import JobPostingParser
from muse.muse_parser_extensions import MuseParserExtensions
import config


class MuseAPI:
    """API client for processing Muse job postings"""

    def __init__(self, parser: JobPostingParser):
        """
        Initialize Muse API client

        Args:
            parser: JobPostingParser instance for processing job data
        """
        self.parser = parser
        self.base_url = config.MUSE_API_BASE_URL
        self.api_key = config.MUSE_API_KEY

    def _get_api_params(self) -> Dict:
        """Get API parameters including API key if available"""
        params = {}
        if self.api_key:
            params['api_key'] = self.api_key
        return params

    def transform_muse_job(
        self,
        job: Dict[str, Any],
        company_name: str,
        employer_id: str,
        logo: str,
        unique_name: str
    ) -> Tuple[Optional[JobMongo], str]:
        """
        Transform Muse job data to JobMongo object

        Args:
            job: Raw job data from Muse API
            company_name: Company name
            employer_id: Employer ID from employers collection
            logo: Company logo URL
            unique_name: Company unique name (muse_short_name)

        Returns:
            Tuple of (JobMongo object, status message)
        """
        try:
            muse_id = job.get('id')
            title = job.get('name', '')
            content = job.get('contents', '')
            locations = job.get('locations', [])
            categories = job.get('categories', [])
            levels = job.get('levels', [])
            tags = job.get('tags', [])
            refs = job.get('refs', {})
            publication_date = job.get('publication_date')

            if not title or not content:
                logging.warning(f"Incomplete data for Muse job ID {muse_id}")
                return None, 'Error'

            # Get location string
            location_str = self._get_physical_location(locations)

            # Use parser to extract all fields
            job_data, location_result = self.parser.process_job_data(
                title=title,
                content=content,
                location=location_str,
                company_name=company_name
            )

            if not job_data:
                logging.warning(f"Failed to parse job data for Muse ID: {muse_id}")
                return None, 'Error'

            # Extract salary range using Muse parser extensions
            salary_min, salary_max, salary_currency = MuseParserExtensions.extract_salary_range(content)

            # Calculate midpoint for salary field
            if salary_min and salary_max:
                salary = int((salary_min + salary_max) / 2)
            elif salary_min:
                salary = int(salary_min)
            elif salary_max:
                salary = int(salary_max)
            else:
                salary = None

            # Clean HTML content for description
            cleaned_description = self.parser.clean_html_content(content)

            # Extract structured data using Muse parser extensions
            responsibilities = MuseParserExtensions.extract_responsibilities(content)
            required_skills = MuseParserExtensions.extract_required_skills(content)
            job_benefits = MuseParserExtensions.extract_job_benefits(content)

            # Location from parser or fallback
            if location_result:
                loc_country = location_result.country
                loc_state = location_result.state
                loc_city = location_result.city
            else:
                loc_country = 'United States'
                loc_state = 'Unknown'
                loc_city = 'Unknown'

            # Combine Muse API tags with parser-extracted tags
            muse_tag_names = [t.get('name') for t in tags if t.get('name')]
            all_tags = list(set(muse_tag_names + (job_data.tags or [])))[:15]

            # Get categories from Muse API
            category_names = [c.get('name') for c in categories if c.get('name')]

            # Get job URL
            absolute_url = refs.get('landing_page', '')

            # Parse publication date
            created_date = None
            if publication_date:
                try:
                    created_date = datetime.fromisoformat(publication_date.replace('Z', '+00:00'))
                except (ValueError, TypeError):
                    created_date = datetime.now(timezone.utc)
            else:
                created_date = datetime.now(timezone.utc)

            # Construct JobMongo object
            job_mongo = JobMongo(
                title=title,
                description=cleaned_description,
                api_description=content,
                logo=logo,
                duration=None,
                company=company_name,
                address=location_str if location_str else None,
                country=loc_country,
                state=loc_state,
                city=loc_city,
                category=category_names if category_names else [],
                tags=all_tags if all_tags else [],
                responsibilities=responsibilities if responsibilities else [],
                english_fluency=None,
                experience=job_data.experience,
                workplace_type=job_data.workplace_type,
                url=absolute_url,
                overview=None,
                job_type=job_data.job_type,
                required_skills=required_skills if required_skills else [],
                job_benefits=job_benefits if job_benefits else [],
                salary=salary,
                salary_duration="Yearly" if salary else None,
                salary_min=int(salary_min) if salary_min else None,
                salary_max=int(salary_max) if salary_max else None,
                salary_currency=salary_currency if (salary or salary_min or salary_max) else None,
                related_jobs=None,
                created_date=created_date,
                employer_id=employer_id,
                is_archived=False,
                scraped_url=absolute_url,
                deprecated_date=None,
                distance=None,
                industry=job_data.industry,
                greenhouse_id=None,
                muse_id=muse_id,
                source="muse",
                inserted_date=datetime.now(timezone.utc),
                redirect_path=generate_redirect_path(title)
            )

            logging.info(f"Successfully processed Muse job: {title} (ID: {muse_id})")
            return job_mongo, 'Success'

        except Exception as e:
            logging.error(f"Error processing Muse job: {e}")
            return None, 'Error'

    def _get_physical_location(self, locations: List[Dict[str, Any]]) -> str:
        """Get physical location from locations list, skipping remote entries"""
        for loc in locations:
            name = loc.get('name', '')
            if name and 'remote' not in name.lower() and 'flexible' not in name.lower():
                return name

        # Return first available if all are remote
        if locations:
            return locations[0].get('name', '')
        return ''

    def fetch_job_by_id(self, job_id: int) -> Optional[Dict]:
        """
        Fetch a single job from Muse API by ID

        Args:
            job_id: Muse job ID

        Returns:
            Job data dict or None if not found
        """
        try:
            url = f"{self.base_url}/jobs/{job_id}"
            params = self._get_api_params()
            response = requests.get(url, params=params, timeout=30)

            if response.status_code == 200:
                return response.json()
            elif response.status_code == 404:
                logging.warning(f"Muse job not found: {job_id}")
                return None
            else:
                logging.error(f"Failed to fetch Muse job {job_id}: {response.status_code}")
                return None

        except requests.exceptions.RequestException as e:
            logging.error(f"Error fetching Muse job {job_id}: {e}")
            return None

    def get_job_from_muse(
        self,
        job_id: int,
        company_name: str,
        employer_id: str,
        logo: str,
        unique_name: str
    ) -> Tuple[Optional[JobMongo], str]:
        """
        Fetch job from Muse API and transform to JobMongo object.
        This follows the same pattern as Greenhouse's get_job_from_greenhouse.

        Args:
            job_id: Muse job ID
            company_name: Company name
            employer_id: Employer ID from employers collection
            logo: Company logo URL
            unique_name: Company unique name (muse_short_name)

        Returns:
            Tuple of (JobMongo object, status message)
            Status messages: 'Success', 'NotFound', 'Error'
        """
        if not job_id:
            logging.warning("Job ID is missing for Muse job")
            return None, 'Error'

        logging.info(f"Fetching Muse job ID {job_id} from API | Company: {company_name}")

        # Fetch job data from Muse API
        job_data = self.fetch_job_by_id(job_id)

        if not job_data:
            logging.warning(f"Muse job {job_id} not found in API")
            return None, 'NotFound'

        # Transform the API response to JobMongo
        return self.transform_muse_job(job_data, company_name, employer_id, logo, unique_name)
