"""
Greenhouse API interaction functions
"""

import re
import logging
import requests
from typing import Dict, Optional, Tuple
from datetime import datetime
import sys
import os

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import JobMongo, JobData, LocationResult, generate_redirect_path
from parser import JobPostingParser
from cache_utils import TTLCache, CacheManager

class GreenhouseAPI:
    """Handles interactions with the Greenhouse API"""
    
    def __init__(self, parser: JobPostingParser):
        self.parser = parser
        
        # API response cache: 5 minute TTL, max 2000 entries
        self.api_cache = TTLCache(ttl=300, maxsize=2000)
        CacheManager.register_cache('greenhouse_api_responses', self.api_cache)
        logging.info("🎯 Greenhouse API caching enabled (TTL=300s, maxsize=2000)")
    
    def get_job_from_greenhouse(self, job_id: int, unique_name: str, company_name: str, 
                               employer_id: str, logo: str) -> Tuple[Optional[JobMongo], str]:
        """
        Fetch job data from Greenhouse API
        
        Returns:
            Tuple of (JobMongo object or None, status message)
            Status messages: 'Success', 'Exist', 'NotFound', 'Error'
        """
        if not job_id:
            return None, 'Error'
        
        # Check cache first
        cache_key = f"{unique_name}:{job_id}"
        cached_result = self.api_cache.get(cache_key)
        if cached_result is not None:
            logging.debug(f"🎯 Cache hit for Greenhouse job: {job_id}")
            return cached_result
        
        api_url = f"https://boards-api.greenhouse.io/v1/boards/{unique_name}/jobs/{job_id}"
        
        try:
            # Use shorter timeout to avoid hanging on slow responses
            response = requests.get(api_url, timeout=10)  # 10 second timeout
            
            if response.status_code == 200:
                job_api_data = response.json()
                absolute_url = job_api_data.get("absolute_url")
                
                # Check if job already exists (this check should be done by caller)
                # Returning the data for the caller to decide
                
                title = job_api_data.get("title")
                content = job_api_data.get("content")
                location = job_api_data.get("location", {}).get("name", "")
                updated_at = job_api_data.get("updated_at")
                
                if not all([title, location, content, absolute_url]):
                    logging.warning(f"Incomplete data for job ID {job_id}")
                    return None, 'Error'
                
                # Clean content
                clean_content = self._clean_api_content(content)
                
                job_data = {
                    "greenhouse_id": job_id,
                    "company": company_name,
                    "logo": logo,
                    "employer_id": employer_id,
                    "absolute_url": absolute_url,
                    "title": title,
                    "api_description": clean_content,
                    "location": location,
                    "updated_at": updated_at
                }

                final_job_data = self._construct_job_mongo(job_data)
                if final_job_data:
                    result = (final_job_data, 'Success')
                    # Cache successful responses
                    self.api_cache.set(cache_key, result)
                    logging.debug(f"📦 Cached Greenhouse API response: {job_id}")
                    return result
                else:
                    return None, 'Error'
                    
            elif response.status_code == 403:
                logging.error(f"Job ID {job_id} not found at {company_name}, status code: 403")
                result = (None, 'NotFound')
                # Cache 403 responses to avoid repeated requests
                self.api_cache.set(cache_key, result)
                return result
                return None, 'NotFound'
            else:
                logging.error(f"Failed to fetch data for job ID {job_id} at {company_name}, status code: {response.status_code}")
                return None, 'Error'
                
        except requests.exceptions.RequestException as e:
            logging.error(f"Error making API call for job ID {job_id} at {company_name}: {e}")
            return None, 'Error'
    
    def _clean_api_content(self, content: str) -> str:
        """Clean content received from API"""
        if not content:
            return ""
        
        # Clean HTML entities and formatting
        content = (content.replace("&lt;", "<")
                         .replace("&gt;", ">")
                         .replace("&amp;nbsp;", " ")
                         .replace("&amp;", "&")
                         .replace('\n', " ")
                         .replace('&quot;', '"'))
        
        # Remove unwanted attributes
        clean_content = re.sub(r'(class|style)="[^"]*"', '', content)
        clean_content = re.sub(r'\s+>', '>', clean_content)
        
        return clean_content
    
    def _get_missing_data(self, title: str, job_description: str, company_name: str = "") -> Optional[JobData]:
        """Extract missing data using pattern matching"""
        try:
            job_data, _ = self.parser.process_job_data(title, job_description, "", company_name)
            return job_data
        except Exception as e:
            logging.error(f"Error in manual data extraction: {e}")
            return None
    
    def _get_location_data(self, address: str) -> Optional[LocationResult]:
        """Parse location data"""
        try:
            location_data = self.parser.parse_location(address)
            return LocationResult(
                country=location_data['country'],
                state=location_data['state'],
                city=location_data['city']
            )
        except Exception as e:
            logging.error(f"Error in location parsing: {e}")
            return None
    
    def _construct_job_mongo(self, job: Dict) -> Optional[JobMongo]:
        """Construct JobMongo object from job data"""
        try:
            # Get missing data if necessary
            job_description = job['api_description'].encode('ascii', 'ignore').decode('ascii')
            company_name = job.get('location', '').split(' - ')[-1] if ' - ' in job.get('location', '') else ''
            job_missing_data = self._get_missing_data(job['title'], job_description, company_name)
            
            if not job_missing_data:
                logging.error("Failed to extract job data")
                return None

            location_data = self._get_location_data(job['location'])
            if not location_data:
                logging.error("Failed to parse location data")
                return None

            # Construct JobMongo object using available and fetched data
            job_mongo = JobMongo(
                title=job["title"],
                description=job_missing_data.description,
                api_description=job.get("api_description"),
                logo=job.get("logo"),
                duration=None,
                company=job.get("company"),
                address=job.get("location"),
                country=location_data.country, 
                state=location_data.state,
                city=location_data.city,
                category=None,
                tags=job_missing_data.tags,
                responsibilities=None,
                english_fluency=None,
                experience=job_missing_data.experience,
                workplace_type=job_missing_data.workplace_type,
                url=job.get("absolute_url"),
                overview=None,
                job_type=job_missing_data.job_type,
                required_skills=None,
                job_benefits=None,
                salary=job_missing_data.salary,
                salary_duration=None,
                salary_min=None,
                salary_max=None,
                salary_currency=job_missing_data.salary_currency,
                related_jobs=None,
                created_date=job.get("updated_at"),
                employer_id=job.get("employer_id"),
                scraped_url=job.get("absolute_url"),
                deprecated_date=None,
                distance=None,
                greenhouse_id=job.get("greenhouse_id"),
                industry=job_missing_data.industry,
                inserted_date=datetime.utcnow(),
                redirect_path=generate_redirect_path(job["title"])
            )
            return job_mongo
            
        except Exception as e:
            logging.error(f"Error constructing JobMongo object: {e}")
            return None