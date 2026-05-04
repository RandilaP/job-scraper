# OpenSearch Integration for Job Extraction System

This document describes the OpenSearch integration for the job extraction system, enabling advanced search capabilities for job data.

## Overview

The OpenSearch integration provides:
- **Real-time indexing**: Jobs are indexed to OpenSearch as they are extracted
- **Advanced search**: Full-text search with filters for location, job type, experience level, etc.
- **Bulk operations**: Efficient bulk indexing for existing job data
- **Geospatial search**: Location-based job searches using coordinates
- **Aggregations**: Statistical analysis of job data

## Components

### 1. OpenSearch Service (`opensearch_service.py`)
Core service for OpenSearch operations:
- Client initialization and connection management
- Index creation with custom mappings
- Document CRUD operations (Create, Read, Update, Delete)
- Bulk indexing with batch processing
- Advanced query building with multiple filters
- Index statistics and management

### 2. OpenSearch Configuration (`opensearch_config.py`)
Configuration settings for OpenSearch connection:
- Host and port
- Authentication credentials
- SSL/TLS settings
- Index names and bulk size

### 3. Bulk Indexing Script (`bulk_index_to_opensearch.py`)
Script for migrating existing MongoDB jobs to OpenSearch:
- Batch processing for large datasets
- Progress tracking and statistics
- Verification of indexing completeness
- Error handling and retry logic

### 4. Service Integration (`service.py`)
Integration with the main job extraction pipeline:
- Automatic indexing of new jobs
- Statistics tracking for OpenSearch operations
- Graceful fallback if OpenSearch is unavailable

## Setup

### 1. Install Dependencies
```bash
pip install opensearch-py
```

### 2. Configure OpenSearch
Add these settings to your `.env` file:

```bash
# OpenSearch Host (DigitalOcean)
OPENSEARCH_HOST=your-cluster.db.ondigitalocean.com
OPENSEARCH_PORT=25060

# Authentication
OPENSEARCH_USERNAME=doadmin
OPENSEARCH_PASSWORD=your_password

# Security
OPENSEARCH_USE_SSL=true
OPENSEARCH_VERIFY_CERTS=false

# Index Settings
OPENSEARCH_JOB_INDEX=jobs
OPENSEARCH_BULK_SIZE=500
```

### 3. Create Index
The index will be created automatically when you run the bulk indexing script or when the first job is indexed.

Alternatively, create it manually:
```python
from opensearch_service import OpenSearchService

opensearch = OpenSearchService()
opensearch.create_index(delete_if_exists=True)
```

## Usage

### Test OpenSearch Connection
```bash
python test_opensearch_integration.py
```

This will run comprehensive tests including:
- Connection verification
- Index creation
- Document indexing
- Search operations
- Update operations
- Statistics retrieval
- Delete operations

### Bulk Index Existing Jobs
To index all existing jobs from MongoDB to OpenSearch:

```bash
python bulk_index_to_opensearch.py
```

This will:
1. Create/recreate the jobs index
2. Fetch jobs from MongoDB in batches
3. Index them to OpenSearch
4. Provide progress updates
5. Display summary statistics

### Enable OpenSearch in Job Extraction
OpenSearch is **enabled by default** in the job extraction service. New jobs will be automatically indexed as they are extracted.

To disable OpenSearch:
```python
from service import JobExtractionService

service = JobExtractionService(enable_opensearch=False)
service.run()
```

### Search for Jobs
```python
from opensearch_service import OpenSearchService

opensearch = OpenSearchService()

# Build search query
query = opensearch.build_search_query(
    keywords="Python developer",
    location="San Francisco",
    job_type=["Full-time"],
    experience_level=["Senior", "Mid-Level"],
    workplace_type=["Remote", "Hybrid"],
    industry=["Technology", "Software"],
    salary_min=100000,
    posted_after="2024-01-01T00:00:00Z",
    size=20
)

# Execute search
results = opensearch.search_jobs(query)

# Process results
hits = results['hits']['hits']
for hit in hits:
    job = hit['_source']
    print(f"{job['title']} at {job['company']}")
```

### Get Job by ID
```python
job = opensearch.get_job_by_id("673a1b2c3d4e5f6789012345")
print(job['title'])
```

### Update Job
```python
opensearch.update_job(
    "673a1b2c3d4e5f6789012345",
    {"is_active": False, "updated_at": "2024-01-20T10:00:00Z"}
)
```

### Delete Job
```python
opensearch.delete_job("673a1b2c3d4e5f6789012345")
```

### Get Index Statistics
```python
stats = opensearch.get_index_stats()
print(f"Documents: {stats['document_count']}")
print(f"Size: {stats['store_size']} bytes")
```

## Index Mapping

The jobs index has the following field mappings:

### Core Fields
- `job_id` (keyword): Unique job identifier
- `url` (keyword): Job posting URL
- `title` (text + keyword): Job title with full-text search
- `description` (text): Job description
- `company` (text + keyword): Company name

### Location Fields
- `location` (text + keyword): Full location string
- `country`, `city`, `state`, `postal_code` (keyword): Location components
- `coordinates` (geo_point): Latitude/longitude for geospatial search

### Job Details
- `salary_range` (nested): Min, max, currency, frequency
- `posted_date` (date): When the job was posted
- `job_type` (keyword): Full-time, Part-time, Contract, etc.
- `experience_level` (keyword): Entry, Mid-Level, Senior, etc.
- `workplace_type` (keyword): Remote, Hybrid, On-site
- `industry` (keyword): Job industry classification

### Additional Fields
- `skills` (keyword): Array of required skills
- `benefits`, `requirements`, `responsibilities`, `qualifications` (text): Job details
- `application_deadline` (date): Application deadline
- `is_active` (boolean): Whether the job is currently active
- `created_at`, `updated_at` (date): Timestamps

## Search Features

### Full-Text Search
Search across title, description, and skills with fuzzy matching:
```python
query = opensearch.build_search_query(keywords="Python Django AWS")
```

### Location-Based Search
Filter by location with multi-field matching:
```python
query = opensearch.build_search_query(location="San Francisco")
```

### Multiple Filters
Combine multiple filters for precise results:
```python
query = opensearch.build_search_query(
    keywords="senior developer",
    location="New York",
    job_type=["Full-time"],
    experience_level=["Senior"],
    workplace_type=["Remote", "Hybrid"],
    industry=["Technology"],
    salary_min=150000
)
```

### Salary Range Search
Find jobs within a salary range:
```python
query = opensearch.build_search_query(
    salary_min=100000,
    salary_max=150000
)
```

### Date Filtering
Get recently posted jobs:
```python
query = opensearch.build_search_query(
    posted_after="2024-01-01T00:00:00Z"
)
```

### Pagination
Control result size and offset:
```python
query = opensearch.build_search_query(
    keywords="developer",
    size=20,  # Results per page
    from_=40  # Offset (page 3 with size=20)
)
```

## Performance

### Bulk Indexing Performance
- **Batch size**: 500 jobs per batch (configurable)
- **Expected rate**: 50-100 jobs/second depending on network and cluster size
- **1231 jobs**: ~12-25 seconds total

### Search Performance
- **Simple searches**: < 100ms
- **Complex queries with filters**: < 200ms
- **Aggregations**: < 500ms

## Monitoring

### Statistics Tracking
The job extraction service tracks OpenSearch statistics:
```python
stats = {
    'jobs_indexed_opensearch': 100,
    'jobs_opensearch_failed': 2
}
```

### Index Health
Check index statistics:
```python
stats = opensearch.get_index_stats()
print(f"Documents: {stats['document_count']}")
print(f"Size: {stats['store_size']} bytes")
print(f"Searches: {stats['search_total']}")
```

## Error Handling

### Graceful Degradation
If OpenSearch is unavailable:
- Jobs are still saved to MongoDB
- A warning is logged
- Job extraction continues normally

### Retry Logic
- Bulk indexing includes automatic retry for failed batches
- Individual job indexing failures are logged but don't block processing

## Troubleshooting

### Connection Issues
```
Failed to connect to OpenSearch: Connection refused
```
**Solution**: Check OPENSEARCH_HOST and OPENSEARCH_PORT in .env file

### Authentication Errors
```
Failed to connect to OpenSearch: Unauthorized
```
**Solution**: Verify OPENSEARCH_USERNAME and OPENSEARCH_PASSWORD

### SSL/TLS Errors
```
SSL: CERTIFICATE_VERIFY_FAILED
```
**Solution**: Set `OPENSEARCH_VERIFY_CERTS=false` in .env file

### Index Already Exists
```
resource_already_exists_exception
```
**Solution**: Use `delete_if_exists=True` when creating index, or manually delete:
```python
opensearch.client.indices.delete(index="jobs")
```

### Document Count Mismatch
If MongoDB count ≠ OpenSearch count:
1. Check for indexing errors in logs
2. Run verification: `python bulk_index_to_opensearch.py`
3. Reindex specific jobs if needed

## Next Steps

### Recommended Enhancements
1. **Aggregations**: Add faceted search for filtering
2. **Synonyms**: Configure synonym analyzer for better search
3. **Autocomplete**: Implement suggest/completion queries
4. **Geospatial**: Add radius-based location search
5. **Analytics**: Track search queries and popular jobs
6. **Highlighting**: Show matched text snippets in results
7. **Boosting**: Adjust field weights for relevance tuning

### Production Considerations
1. **Scaling**: Increase shards/replicas based on load
2. **Monitoring**: Set up alerts for index health
3. **Backup**: Configure snapshots for disaster recovery
4. **Security**: Enable fine-grained access control
5. **Rate Limiting**: Implement query throttling if needed

## Resources

- [OpenSearch Python Client Documentation](https://opensearch.org/docs/latest/clients/python/)
- [OpenSearch Query DSL](https://opensearch.org/docs/latest/query-dsl/)
- [DigitalOcean OpenSearch](https://docs.digitalocean.com/products/databases/opensearch/)
