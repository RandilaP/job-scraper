"""
Pydantic models for job extraction
"""

import re
import random
from datetime import datetime
from typing import Dict, Optional, List
from pydantic import BaseModel, Field

class JobData(BaseModel):
    description: str = Field(
        description="The description of the job. Also it should be wrapped customly in html tags like <p> and <ul> and <li> etc. As for headers and titles like responsibilities use <h1> and <h2> tags and they should be bold with <strong> tags. If you really cannot to find a description use 'N/A' as default"
    )
    industry: str = Field(
        description="Enter the relevant industry name, ensuring it is properly capitalized and contains only alphabetic characters and spaces."
    )
    tags: List[str] = Field(description="some of keywords from the job description")
    workplace_type: str = Field(
        description="Select the relevant type of the job description from these types: ['Office', 'Remote', 'Hybrid'], If you really cannot to find a type use 'Hybrid' as default"
    )
    job_type: str = Field(
        description="Select the relevant Job type of the job description from these types: ['Fulltime', 'Partime', 'Internship', 'Contract'], If you really cannot to find a type use 'Fulltime' as default"
    )
    experience: str = Field(
        description="Enter the expected experince level from the candidate according to the job description it should be one of these: ['Associate', 'Manager', 'Senior', 'Director', 'Executive'], If you really cannot to find a type use 'Associate' as default"
    )
    salary_currency: Optional[str] = Field(description="Currency type of the salary, If you really cannot to find a type use 'USD' as default")
    salary: Optional[float] = Field(description="Salary amount for the job position, If you really cannot to find a type use 0 as default. Get the yearly salary")

class LocationResult(BaseModel):
    country: str = Field(description="The country corresponding to the given address.")
    state: str = Field(description="The state corresponding to the given address.")
    city: str = Field(description="The city corresponding to the given address.")

def generate_redirect_path(title: str) -> str:
    """
    Generate a URL-friendly redirect path from a job title.
    Example: "Senior Software Engineer" -> "/senior_software_engineer_842315"
    """
    # Convert to lowercase and replace spaces/special chars with underscores
    cleaned = re.sub(r'[^a-z0-9]+', '_', title.lower())
    # Remove leading/trailing underscores
    cleaned = cleaned.strip('_')
    # Generate random 6-digit number
    random_num = random.randint(100000, 999999)
    return f"/{cleaned}_{random_num}"

class JobDescriptionTokensMongo(BaseModel):
    job_id: str
    tokens: List[str]
    inserted_date: Optional[datetime] = None

class JobMongo(BaseModel):
    title: str
    description: Optional[str] = None
    api_description: Optional[str] = None
    logo: Optional[str] = None
    duration: Optional[str] = None
    company: Optional[str] = None
    address: Optional[str] = None
    country: Optional[str] = None
    state: Optional[str] = None
    city: Optional[str] = None
    category: Optional[List[str]] = None
    tags: Optional[List[str]] = None
    responsibilities: Optional[List[str]] = None
    english_fluency: Optional[str] = None
    experience: Optional[str] = None
    workplace_type: Optional[str] = None
    url: Optional[str] = None
    overview: Optional[str] = None
    job_type: Optional[str] = None
    required_skills: Optional[List[str]] = None
    job_benefits: Optional[List[str]] = None
    salary: Optional[int] = None
    salary_duration: Optional[str] = None
    salary_min: Optional[int] = None
    salary_max: Optional[int] = None
    salary_currency: Optional[str] = None
    related_jobs: Optional[List[str]] = None
    created_date: Optional[datetime] = Field(default=None)
    employer_id: Optional[str] = None
    is_archived: bool = False
    scraped_url: Optional[str] = None
    deprecated_date: Optional[datetime] = None
    distance: Optional[float] = None
    industry: str
    greenhouse_id: Optional[int] = None
    source: Optional[str] = "greenhouse"
    inserted_date: Optional[datetime] = None
    redirect_path: Optional[str] = None


class RunStats(BaseModel):
    """Model for tracking job extraction run statistics"""
    status: str = Field(description="Run status: 'ongoing' or 'completed'")
    start_time: datetime = Field(description="When the run started")
    end_time: Optional[datetime] = Field(default=None, description="When the run completed")
    duration_seconds: Optional[float] = Field(default=None, description="Total run duration in seconds")
    
    # Job counts
    greenhouse_jobs_new: int = Field(default=0, description="New Greenhouse jobs found")
    greenhouse_jobs_inserted: int = Field(default=0, description="Greenhouse jobs inserted to DB")
    greenhouse_jobs_existed: int = Field(default=0, description="Greenhouse jobs already existed")
    greenhouse_jobs_failed: int = Field(default=0, description="Greenhouse jobs failed to process")
    
    workday_jobs_new: int = Field(default=0, description="New Workday jobs found")
    workday_jobs_inserted: int = Field(default=0, description="Workday jobs inserted to DB")
    workday_jobs_existed: int = Field(default=0, description="Workday jobs already existed")
    workday_jobs_failed: int = Field(default=0, description="Workday jobs failed to process")
    
    # Processing info
    job_source: str = Field(description="Source: 'greenhouse', 'workday', or 'both'")
    companies_processed: int = Field(default=0, description="Total companies processed")
    
    # OpenSearch sync
    opensearch_synced: bool = Field(default=False, description="Whether OpenSearch sync completed")
    opensearch_indexed: int = Field(default=0, description="Jobs indexed to OpenSearch")
    opensearch_deleted: int = Field(default=0, description="Jobs deleted from OpenSearch")
    
    # Cache statistics
    cache_hit_rate: Optional[float] = Field(default=None, description="Overall cache hit rate percentage")
    cache_total_hits: int = Field(default=0, description="Total cache hits")
    cache_total_misses: int = Field(default=0, description="Total cache misses")
    
    # Errors
    errors: List[Dict[str, str]] = Field(default_factory=list, description="List of errors that occurred")
    error_count: int = Field(default=0, description="Total number of errors")
    failed_reason: Optional[str] = Field(default=None, description="Reason for failure if status is failed")
    
    # Environment
    environment: str = Field(default="production", description="Environment where run executed")
    hostname: str = Field(default="unknown", description="Hostname of the server")
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }