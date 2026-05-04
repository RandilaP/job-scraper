"""
OpenSearch Service for Job Indexing and Search
"""
import logging
from typing import List, Dict, Optional, Any
from opensearchpy import OpenSearch, helpers
from opensearchpy.exceptions import OpenSearchException
import opensearch_config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class OpenSearchService:
    """Service for managing OpenSearch operations for job data"""

    def __init__(self):
        """Initialize OpenSearch client"""
        self.client = None
        self.index_name = opensearch_config.OPENSEARCH_JOB_INDEX
        self._connect()

    def _connect(self):
        """Establish connection to OpenSearch"""
        try:
            self.client = OpenSearch(
                hosts=[{
                    'host': opensearch_config.OPENSEARCH_HOST,
                    'port': opensearch_config.OPENSEARCH_PORT
                }],
                http_auth=(
                    opensearch_config.OPENSEARCH_USERNAME,
                    opensearch_config.OPENSEARCH_PASSWORD
                ),
                use_ssl=opensearch_config.OPENSEARCH_USE_SSL,
                verify_certs=opensearch_config.OPENSEARCH_VERIFY_CERTS,
                ssl_show_warn=False
            )
            
            # Test connection
            info = self.client.info()
            logger.info(f"Connected to OpenSearch: {info['version']['number']}")
            
        except Exception as e:
            logger.error(f"Failed to connect to OpenSearch: {e}")
            raise

    def create_index(self, delete_if_exists: bool = False):
        """
        Create the jobs index with appropriate mappings
        
        Args:
            delete_if_exists: If True, delete existing index before creating
        """
        try:
            # Check if index exists
            if self.client.indices.exists(index=self.index_name):
                if delete_if_exists:
                    self.client.indices.delete(index=self.index_name)
                    logger.info(f"Deleted existing index: {self.index_name}")
                else:
                    logger.info(f"Index {self.index_name} already exists")
                    return

            # Define index mappings for job data
            mappings = {
                "settings": {
                    "number_of_shards": 2,
                    "number_of_replicas": 1,
                    "analysis": {
                        "analyzer": {
                            "custom_analyzer": {
                                "type": "custom",
                                "tokenizer": "standard",
                                "filter": ["lowercase", "stop", "snowball"]
                            }
                        }
                    }
                },
                "mappings": {
                    "properties": {
                        "mongo_id": {"type": "keyword"},
                        "address": {"type": "text"},
                        "api_description": {"type": "text"},
                        "category": {"type": "keyword"},
                        "city": {"type": "keyword"},
                        "company": {
                            "type": "text",
                            "fields": {
                                "keyword": {"type": "keyword"}
                            }
                        },
                        "country": {"type": "keyword"},
                        "created_date": {"type": "date"},
                        "deprecated_date": {"type": "date"},
                        "description": {"type": "text"},
                        "duration": {"type": "keyword"},
                        "employer_id": {"type": "keyword"},
                        "english_fluency": {"type": "keyword"},
                        "experience": {"type": "keyword"},
                        "greenhouse_id": {
                            "type": "text",
                            "fields": {
                                "keyword": {"type": "keyword"}
                            }
                        },
                        "industry": {"type": "keyword"},
                        "inserted_date": {"type": "date"},
                        "is_active": {"type": "boolean"},
                        "is_archived": {"type": "boolean"},
                        "job_api_job_id": {
                            "type": "text",
                            "fields": {
                                "keyword": {"type": "keyword"}
                            }
                        },
                        "job_benefits": {"type": "text"},
                        "job_type": {"type": "keyword"},
                        "logo": {"type": "keyword"},
                        "overview": {"type": "text"},
                        "required_skills": {"type": "keyword"},
                        "responsibilities": {"type": "text"},
                        "salary": {"type": "integer"},
                        "salary_currency": {"type": "keyword"},
                        "salary_duration": {"type": "keyword"},
                        "salary_max": {"type": "integer"},
                        "salary_min": {"type": "integer"},
                        "scraped_url": {"type": "keyword"},
                        "source": {
                            "type": "text",
                            "fields": {
                                "keyword": {"type": "keyword"}
                            }
                        },
                        "state": {"type": "keyword"},
                        "tags": {"type": "keyword"},
                        "title": {
                            "type": "text",
                            "fields": {
                                "keyword": {"type": "keyword"}
                            }
                        },
                        "url": {"type": "keyword"},
                        "workplace_type": {"type": "keyword"}
                    }
                }
            }

            # Create the index
            self.client.indices.create(index=self.index_name, body=mappings)
            logger.info(f"Created index: {self.index_name}")

        except OpenSearchException as e:
            logger.error(f"Failed to create index: {e}")
            raise

    def index_job(self, job_id: str, job_data: Dict) -> bool:
        """
        Index a single job document
        
        Args:
            job_id: Unique identifier for the job
            job_data: Job data dictionary
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Prepare document for indexing
            doc = self._prepare_job_document(job_data)
            
            # Index the document
            response = self.client.index(
                index=self.index_name,
                id=job_id,
                body=doc,
                refresh=True
            )
            
            logger.info(f"Indexed job {job_id}: {response['result']}")
            return response['result'] in ['created', 'updated']
            
        except OpenSearchException as e:
            logger.error(f"Failed to index job {job_id}: {e}")
            return False

    def bulk_index_jobs(self, jobs: List[Dict]) -> Dict[str, int]:
        """
        Bulk index multiple jobs
        
        Args:
            jobs: List of job dictionaries with '_id' field
            
        Returns:
            Dictionary with success and failure counts
        """
        # Early exit: no jobs to index
        if not jobs:
            logger.info("⚡ Early exit: No jobs to index")
            return {'success': 0, 'failed': 0}
        
        try:
            actions = []
            for job in jobs:
                job_id = str(job.get('_id', ''))
                if not job_id:
                    logger.warning("Skipping job without _id")
                    continue

                doc = self._prepare_job_document(job)
                
                actions.append({
                    '_index': self.index_name,
                    '_id': job_id,
                    '_source': doc
                })

            # Early exit: no valid actions after filtering
            if not actions:
                logger.warning("⚡ Early exit: No valid jobs to index after filtering")
                return {'success': 0, 'failed': 0}

            # Execute bulk indexing
            success, failed = helpers.bulk(
                self.client,
                actions,
                chunk_size=opensearch_config.OPENSEARCH_BULK_SIZE,
                raise_on_error=False,
                stats_only=True
            )

            logger.info(f"Bulk indexed {success} jobs, {failed} failed")
            return {'success': success, 'failed': failed}

        except Exception as e:
            logger.error(f"Bulk indexing failed: {e}")
            return {'success': 0, 'failed': len(jobs)}

    def search_jobs(self, query: Dict) -> Dict:
        """
        Search for jobs using OpenSearch query
        
        Args:
            query: OpenSearch query dictionary
            
        Returns:
            Search results
        """
        try:
            response = self.client.search(
                index=self.index_name,
                body=query
            )
            return response
            
        except OpenSearchException as e:
            logger.error(f"Search failed: {e}")
            return {'hits': {'hits': [], 'total': {'value': 0}}}

    def build_search_query(
        self,
        keywords: Optional[str] = None,
        location: Optional[str] = None,
        job_type: Optional[List[str]] = None,
        experience_level: Optional[List[str]] = None,
        workplace_type: Optional[List[str]] = None,
        industry: Optional[List[str]] = None,
        company: Optional[str] = None,
        salary_min: Optional[float] = None,
        salary_max: Optional[float] = None,
        posted_after: Optional[str] = None,
        size: int = 10,
        from_: int = 0
    ) -> Dict:
        """
        Build a search query with filters
        
        Args:
            keywords: Search keywords for title/description
            location: Location filter
            job_type: List of job types (e.g., ['Full-time', 'Part-time'])
            experience_level: List of experience levels
            workplace_type: List of workplace types (e.g., ['Remote', 'Hybrid'])
            industry: List of industries
            company: Company name
            salary_min: Minimum salary
            salary_max: Maximum salary
            posted_after: Date filter (ISO format)
            size: Number of results to return
            from_: Pagination offset
            
        Returns:
            OpenSearch query dictionary
        """
        query = {
            "size": size,
            "from": from_,
            "query": {
                "bool": {
                    "must": [],
                    "filter": []
                }
            },
            "sort": [
                {"posted_date": {"order": "desc"}},
                "_score"
            ]
        }

        # Keyword search in title and description
        if keywords:
            query["query"]["bool"]["must"].append({
                "multi_match": {
                    "query": keywords,
                    "fields": ["title^3", "description", "skills^2"],
                    "type": "best_fields",
                    "operator": "or",
                    "fuzziness": "AUTO"
                }
            })

        # Location filter
        if location:
            query["query"]["bool"]["must"].append({
                "multi_match": {
                    "query": location,
                    "fields": ["location", "city", "state", "country"],
                    "type": "best_fields"
                }
            })

        # Company filter
        if company:
            query["query"]["bool"]["filter"].append({
                "match": {
                    "company": company
                }
            })

        # Job type filter
        if job_type:
            query["query"]["bool"]["filter"].append({
                "terms": {
                    "job_type": job_type
                }
            })

        # Experience level filter
        if experience_level:
            query["query"]["bool"]["filter"].append({
                "terms": {
                    "experience_level": experience_level
                }
            })

        # Workplace type filter
        if workplace_type:
            query["query"]["bool"]["filter"].append({
                "terms": {
                    "workplace_type": workplace_type
                }
            })

        # Industry filter
        if industry:
            query["query"]["bool"]["filter"].append({
                "terms": {
                    "industry": industry
                }
            })

        # Salary range filter
        if salary_min is not None or salary_max is not None:
            salary_filter = {
                "nested": {
                    "path": "salary_range",
                    "query": {
                        "bool": {
                            "must": []
                        }
                    }
                }
            }
            
            if salary_min is not None:
                salary_filter["nested"]["query"]["bool"]["must"].append({
                    "range": {
                        "salary_range.max": {"gte": salary_min}
                    }
                })
            
            if salary_max is not None:
                salary_filter["nested"]["query"]["bool"]["must"].append({
                    "range": {
                        "salary_range.min": {"lte": salary_max}
                    }
                })
            
            query["query"]["bool"]["filter"].append(salary_filter)

        # Posted date filter
        if posted_after:
            query["query"]["bool"]["filter"].append({
                "range": {
                    "posted_date": {
                        "gte": posted_after
                    }
                }
            })

        # Active jobs only
        query["query"]["bool"]["filter"].append({
            "term": {
                "is_active": True
            }
        })

        # If no must clauses, match all
        if not query["query"]["bool"]["must"]:
            query["query"]["bool"]["must"].append({
                "match_all": {}
            })

        return query

    def get_job_by_id(self, job_id: str) -> Optional[Dict]:
        """
        Get a job document by ID
        
        Args:
            job_id: Job ID
            
        Returns:
            Job document or None
        """
        try:
            response = self.client.get(
                index=self.index_name,
                id=job_id
            )
            return response['_source']
            
        except OpenSearchException as e:
            logger.error(f"Failed to get job {job_id}: {e}")
            return None

    def update_job(self, job_id: str, update_data: Dict) -> bool:
        """
        Update a job document
        
        Args:
            job_id: Job ID
            update_data: Fields to update
            
        Returns:
            True if successful, False otherwise
        """
        try:
            response = self.client.update(
                index=self.index_name,
                id=job_id,
                body={'doc': update_data},
                refresh=True
            )
            logger.info(f"Updated job {job_id}: {response['result']}")
            return response['result'] == 'updated'
            
        except OpenSearchException as e:
            logger.error(f"Failed to update job {job_id}: {e}")
            return False

    def delete_job(self, job_id: str) -> bool:
        """
        Delete a job document
        
        Args:
            job_id: Job ID
            
        Returns:
            True if successful, False otherwise
        """
        try:
            response = self.client.delete(
                index=self.index_name,
                id=job_id,
                refresh=True
            )
            logger.info(f"Deleted job {job_id}: {response['result']}")
            return response['result'] == 'deleted'
            
        except OpenSearchException as e:
            logger.error(f"Failed to delete job {job_id}: {e}")
            return False

    def bulk_delete_jobs(self, job_ids: List[str]) -> Dict[str, int]:
        """
        Bulk delete multiple jobs
        
        Args:
            job_ids: List of job IDs to delete
            
        Returns:
            Dictionary with success and failure counts
        """
        # Early exit: no jobs to delete
        if not job_ids:
            logger.info("⚡ Early exit: No job IDs provided for deletion")
            return {'success': 0, 'failed': 0}
        
        try:
            actions = []
            for job_id in job_ids:
                actions.append({
                    '_op_type': 'delete',
                    '_index': self.index_name,
                    '_id': str(job_id)
                })

            # Execute bulk deletion
            success, failed = helpers.bulk(
                self.client,
                actions,
                chunk_size=opensearch_config.OPENSEARCH_BULK_SIZE,
                raise_on_error=False,
                stats_only=True
            )

            logger.info(f"Bulk deleted {success} jobs, {failed} failed")
            return {'success': success, 'failed': failed}

        except Exception as e:
            logger.error(f"Bulk deletion failed: {e}")
            return {'success': 0, 'failed': len(job_ids)}

    def _prepare_job_document(self, job_data: Dict) -> Dict:
        """
        Prepare job data for indexing
        
        Args:
            job_data: Raw job data from MongoDB
            
        Returns:
            Processed document for indexing
        """
        doc = {}
        
        # Map MongoDB fields to OpenSearch fields (matching new 37-field schema)
        field_mapping = {
            '_id': 'mongo_id',  # Map MongoDB _id to mongo_id field (searchable)
            'address': 'address',
            'api_description': 'api_description',
            'category': 'category',
            'city': 'city',
            'company': 'company',
            'country': 'country',
            'created_date': 'created_date',
            'deprecated_date': 'deprecated_date',
            'description': 'description',
            'duration': 'duration',
            'employer_id': 'employer_id',
            'english_fluency': 'english_fluency',
            'experience': 'experience',
            'greenhouse_id': 'greenhouse_id',
            'industry': 'industry',
            'inserted_date': 'inserted_date',
            'is_active': 'is_active',
            'is_archived': 'is_archived',
            'job_api_job_id': 'job_api_job_id',
            'job_benefits': 'job_benefits',
            'job_type': 'job_type',
            'logo': 'logo',
            'overview': 'overview',
            'required_skills': 'required_skills',
            'responsibilities': 'responsibilities',
            'salary': 'salary',
            'salary_currency': 'salary_currency',
            'salary_duration': 'salary_duration',
            'salary_max': 'salary_max',
            'salary_min': 'salary_min',
            'scraped_url': 'scraped_url',
            'source': 'source',
            'state': 'state',
            'tags': 'tags',
            'title': 'title',
            'url': 'url',
            'workplace_type': 'workplace_type'
        }

        for mongo_field, opensearch_field in field_mapping.items():
            if mongo_field in job_data and job_data[mongo_field] is not None:
                value = job_data[mongo_field]
                # Convert ObjectId to string for mongo_id field
                if mongo_field == '_id':
                    value = str(value)
                doc[opensearch_field] = value

        # Ensure is_active defaults to True
        if 'is_active' not in doc:
            doc['is_active'] = True
        
        # Ensure is_archived defaults to False
        if 'is_archived' not in doc:
            doc['is_archived'] = False

        return doc

    def get_index_stats(self) -> Dict:
        """
        Get statistics about the jobs index
        
        Returns:
            Index statistics
        """
        try:
            stats = self.client.indices.stats(index=self.index_name)
            count = self.client.count(index=self.index_name)
            
            return {
                'index_name': self.index_name,
                'document_count': count['count'],
                'store_size': stats['indices'][self.index_name]['total']['store']['size_in_bytes'],
                'search_total': stats['indices'][self.index_name]['total']['search']['query_total']
            }
            
        except OpenSearchException as e:
            logger.error(f"Failed to get index stats: {e}")
            return {}

    def close(self):
        """Close OpenSearch connection"""
        if self.client:
            self.client.close()
            logger.info("OpenSearch connection closed")
