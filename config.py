"""
Configuration settings and constants for the job extraction system
"""

import os
import logging
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Skills categories
SKILLS = [
    "MANUFACTURING",
    "INFORMATION TECHNOLOGY",
    "ACCOUNTING & FINANCE",
    "TOURISM & HOSPITALITY",
    "MARKETING & BUSINESS ADMINISTRATION",
    "FOOD SERVICE & HOSPITALITY",
    "HUMAN RESOURCES",
    "HEALTH CARE",
    "LAW ENFORCEMENT",
    "OFFICE & ADMINISTRATIVE",
    "RETAIL & CUSTOMER SERVICE",
    "MANAGEMENT",
    "EDUCATION",
    "LOGISTICS & PURCHASING",
    "LEGAL",
    "SOCIAL WORK",
    "ENGINEERING & SCIENTIFIC",
    "TRAVEL & TRANSPORTATION",
    "PUBLIC RELATIONS",
    "ARCHITECTURE & CONSTRUCTION",
    "REAL ESTATE & CONSTRUCTION",
    "SALES & MARKETING",
    "MAINTENANCE & REPAIR",
    "CREATIVE & CULTURAL",
    "NGO & NON-PROFIT",
    "TRANSPORTATION",
    "DATA SCIENCE & ANALYTICS",
    "ENVIRONMENTAL SCIENCE & SUSTAINABILITY",
    "ENTERTAINMENT & MEDIA",
    "SPORTS & RECREATION",
    "ART & DESIGN",
    "PHARMACEUTICAL & BIOTECH",
    "TELECOMMUNICATIONS",
    "GOVERNMENT & PUBLIC ADMINISTRATION",
    "MILITARY",
    "AGRICULTURE & NATURAL RESOURCES",
]

# Environment variables
MONGODB_URI = os.getenv('PROD_MONGODB_URI')

# Job source configuration
# Values: 'greenhouse', 'workday', 'both'
JOB_SOURCE = os.getenv('JOB_SOURCE', 'both').lower()

# Greenhouse parallel processing configuration
GREENHOUSE_COMPANY_WORKERS = int(os.getenv('GREENHOUSE_COMPANY_WORKERS', '20'))  # Increased from 10
GREENHOUSE_JOB_WORKERS = int(os.getenv('GREENHOUSE_JOB_WORKERS', '10'))  # Increased from 5
GREENHOUSE_ID_MAINTENANCE_WORKERS = int(os.getenv('GREENHOUSE_ID_MAINTENANCE_WORKERS', '20'))  # New parallel ID maintenance

# Workday parallel processing configuration (more resource-intensive due to Selenium)
WORKDAY_SELENIUM_WORKERS = int(os.getenv('WORKDAY_SELENIUM_WORKERS', '6'))  # Selenium drivers for ID maintenance (increased from 3)
WORKDAY_PARALLEL_WORKERS = int(os.getenv('WORKDAY_PARALLEL_WORKERS', '20'))  # Job processing workers (increased from 14)
WORKDAY_BATCH_SIZE = int(os.getenv('WORKDAY_BATCH_SIZE', '150'))  # Batch size (increased from 100)

# Required environment variables
REQUIRED_ENV_VARS = ['PROD_MONGODB_URI']

def setup_logging():
    """Setup logging configuration"""
    logging.basicConfig(
        level=logging.INFO, 
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

def validate_environment():
    """Validate that all required environment variables are set"""
    for var in REQUIRED_ENV_VARS:
        if not os.getenv(var):
            logging.error(f"Required environment variable {var} is not set")
            logging.error("Please check your .env file")
            raise ValueError(f"Missing required environment variable: {var}")

# Database configuration
DATABASE_CONFIG = {
    'server_selection_timeout_ms': 60000,  # Increased from 5000 to 60000 (60 seconds)
    'connect_timeout_ms': 30000,  # Increased from 10000 to 30000 (30 seconds)
    'socket_timeout_ms': 120000,  # Increased from 30000 to 120000 (120 seconds)
    'retry_writes': True,
    'retry_reads': True,
    'max_pool_size': int(os.getenv('MONGODB_MAX_POOL_SIZE', '100')),  # Connection pool size
    'min_pool_size': int(os.getenv('MONGODB_MIN_POOL_SIZE', '10')),
}