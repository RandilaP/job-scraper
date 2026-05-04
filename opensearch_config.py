"""
OpenSearch Configuration
"""
import os
from dotenv import load_dotenv

load_dotenv()

# OpenSearch connection settings
OPENSEARCH_HOST = os.getenv("OPENSEARCH_HOST", "localhost")
OPENSEARCH_PORT = int(os.getenv("OPENSEARCH_PORT", "9200"))
OPENSEARCH_USERNAME = os.getenv("OPENSEARCH_USERNAME", "admin")
OPENSEARCH_PASSWORD = os.getenv("OPENSEARCH_PASSWORD", "")
OPENSEARCH_USE_SSL = os.getenv("OPENSEARCH_USE_SSL", "true").lower() == "true"
OPENSEARCH_VERIFY_CERTS = os.getenv("OPENSEARCH_VERIFY_CERTS", "false").lower() == "true"

# Index settings
OPENSEARCH_JOB_INDEX = os.getenv("OPENSEARCH_JOB_INDEX", "jobs")
OPENSEARCH_BULK_SIZE = int(os.getenv("OPENSEARCH_BULK_SIZE", "500"))
