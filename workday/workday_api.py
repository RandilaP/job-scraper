"""
Workday API integration for job extraction
"""
import logging
import time
import re
import html
from typing import Dict, Optional, Tuple
import requests
from datetime import datetime
import sys
import os

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import JobMongo, generate_redirect_path
from parser import JobPostingParser
from cache_utils import TTLCache, CacheManager


class WorkdayAPI:
    """API client for fetching and processing Workday job postings with optimized HTTP requests"""

    def __init__(self, parser: JobPostingParser):
        """
        Initialize Workday API client
        
        Args:
            parser: JobPostingParser instance for processing job data
        """
        self.parser = parser
        self.max_retries = 3  # Reduced from 5 to 3
        self.backoff_factor = 0.5  # Reduced from 1 to 0.5 for faster retries
        
        # Session for connection pooling and reuse
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            'Accept': 'application/json'
        })
        
        # API response cache: 5 minute TTL, max 2000 entries
        self.api_cache = TTLCache(ttl=300, maxsize=2000)
        CacheManager.register_cache('workday_api_responses', self.api_cache)
        logging.info("🎯 Workday API caching enabled (TTL=300s, maxsize=2000)")

    def _convert_workday_url(self, link: str) -> str:
        """
        Convert public Workday job URL to API endpoint URL
        
        Args:
            link: Public job posting URL
            
        Returns:
            API endpoint URL
        """
        # Convert: https://company.wd3.myworkdayjobs.com/en-US/careers/job/...
        # To: https://company.wd3.myworkdayjobs.com/wday/cxs/company/careers/job/...
        modified_url = re.sub(
            r"(https://)(\w+)(\.wd\d+\.myworkdayjobs\.com/)(en-US)(/)",
            r"\1\2\3wday/cxs/\2/",
            link
        )
        return modified_url

    def _fetch_job_api_data(self, link: str) -> Tuple[Optional[Dict], str]:
        """
        Fetch job data from Workday API with retries and optimized timeouts
        
        Args:
            link: Job posting URL
            
        Returns:
            Tuple of (job_data_dict, status_message)
        """
        # Check cache first
        cached_result = self.api_cache.get(link)
        if cached_result is not None:
            logging.debug(f"🎯 Cache hit for Workday API: {link}")
            return cached_result
        
        modified_url = self._convert_workday_url(link)

        for attempt in range(self.max_retries):
            try:
                # Use session for connection pooling, reduced timeout from 30 to 10 seconds
                response = self.session.get(modified_url, timeout=10)

                if response.status_code == 200:
                    job_api_data = response.json()
                    result = (job_api_data, 'Success')
                    # Cache successful responses
                    self.api_cache.set(link, result)
                    logging.debug(f"📦 Cached Workday API response: {link}")
                    return result

                elif response.status_code == 403 or response.status_code == 404:
                    logging.warning(f"Job not found (403/404) for URL: {link}")
                    result = (None, 'NotFound')
                    # Cache 404 responses to avoid repeated requests
                    self.api_cache.set(link, result)
                    return result

                elif response.status_code == 429:
                    # Exponential backoff with reduced base wait time
                    wait_time = self.backoff_factor * (2 ** attempt)
                    logging.warning(
                        f"Rate limit exceeded for {link}. "
                        f"Retrying in {wait_time} seconds..."
                    )
                    time.sleep(wait_time)

                else:
                    logging.error(
                        f"Failed to fetch data for {link}, "
                        f"status code: {response.status_code}"
                    )
                    return None, 'Error'

            except requests.exceptions.Timeout:
                # Don't retry on timeout, fail fast
                logging.error(f"Timeout fetching {link}")
                return None, 'Error'
            except requests.exceptions.RequestException as e:
                # Fast fail on network errors
                logging.error(f"Error making API call for {link}: {e}")
                return None, 'Error'

        logging.error(f"All retry attempts failed for {link}")
        return None, 'Error'

    def get_job_from_workday(
        self,
        link: str,
        company_name: str,
        employer_id: str,
        logo: str
    ) -> Tuple[Optional[JobMongo], str]:
        """
        Fetch and process a job from Workday
        
        Args:
            link: Job posting URL
            company_name: Company name
            employer_id: Company employer ID
            logo: Company logo URL
            
        Returns:
            Tuple of (JobMongo object, status message)
        """
        if not link:
            logging.warning("Empty job link provided")
            return None, 'Error'

        logging.info(f"Fetching job from Workday: {link}")

        # Fetch job data from API
        job_api_data, status = self._fetch_job_api_data(link)

        if status != 'Success' or not job_api_data:
            return None, status

        # Extract job posting info
        try:
            job_posting_info = job_api_data.get("jobPostingInfo", {})
            title = job_posting_info.get("title")
            content = job_posting_info.get("jobDescription")
            location = job_posting_info.get("location")
            start_date = job_posting_info.get("startDate")

            if not title or not content:
                logging.warning(f"Incomplete data for job: {link}")
                return None, 'Error'

            # Decode HTML entities
            decoded_content = html.unescape(content)

            # Use parser to extract all fields (same as Greenhouse)
            job_data, location_result = self.parser.process_job_data(
                title=title,
                content=decoded_content,
                location=location or "",
                company_name=company_name
            )

            if not job_data:
                logging.warning(f"Failed to parse job data for: {link}")
                return None, 'Error'

            # Parse location if we have one (parser already handles this in process_job_data)
            # But if location string exists, we can extract more details
            location_data = None
            if location:
                location_data = self.parser.parse_location(location)

            # Construct JobMongo object matching the model structure
            job_mongo = JobMongo(
                title=title,
                description=job_data.description,
                api_description=None,  # Workday doesn't provide separate API description
                logo=logo,
                duration=None,
                company=company_name,
                address=location or None,
                country=location_data.get('country') if location_data else (location_result.country if location_result else None),
                state=location_data.get('state') if location_data else (location_result.state if location_result else None),
                city=location_data.get('city') if location_data else (location_result.city if location_result else None),
                category=None,
                tags=job_data.tags if job_data.tags else None,
                responsibilities=None,
                english_fluency=None,
                experience=job_data.experience,
                workplace_type=job_data.workplace_type,
                url=link,
                overview=None,
                job_type=job_data.job_type,
                required_skills=None,
                job_benefits=None,
                salary=int(job_data.salary) if job_data.salary else None,
                salary_duration=None,
                salary_min=None,
                salary_max=None,
                salary_currency=job_data.salary_currency if job_data.salary_currency else None,
                related_jobs=None,
                created_date=datetime.fromisoformat(start_date.replace('Z', '+00:00')) if start_date else datetime.utcnow(),
                employer_id=employer_id,
                is_archived=False,
                scraped_url=link,
                deprecated_date=None,
                distance=None,
                industry=job_data.industry,
                greenhouse_id=None,
                source="workday",
                inserted_date=datetime.utcnow(),
                redirect_path=generate_redirect_path(title)
            )

            logging.info(f"Successfully processed Workday job: {title}")
            return job_mongo, 'Success'

        except Exception as e:
            logging.error(f"Error processing Workday job {link}: {e}")
            return None, 'Error'