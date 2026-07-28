"""
Database connection and operations for MongoDB
"""

import logging
import certifi
import time
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError, NetworkTimeout, CursorNotFound
from bson import ObjectId
from typing import List, Dict, Optional
from config import MONGODB_URI, DATABASE_CONFIG, validate_environment
from models import JobMongo, JobDescriptionTokensMongo

class DatabaseManager:
    """Handles MongoDB connections and operations"""
    
    def __init__(self):
        """Initialize database connections"""
        validate_environment()
        
        # Get CA certificate path
        self.ca = certifi.where()
        
        # Initialize MongoDB client
        self._init_mongodb_connection()
        
        # Initialize database collections
        self._init_collections()
    
    def _init_mongodb_connection(self, connection_pool_size: int = 100):
        """Initialize MongoDB connection with error handling and connection pooling"""
        try:
            self.client = MongoClient(
                MONGODB_URI,
                tlsCAFile=self.ca,
                # Increased timeouts for Workday parallel operations
                serverSelectionTimeoutMS=60000,  # 60 seconds (was 5000)
                connectTimeoutMS=30000,  # 30 seconds (was 10000)
                socketTimeoutMS=120000,  # 120 seconds (was 30000)
                
                # Connection pooling configuration
                maxPoolSize=connection_pool_size,  # Maximum connections
                minPoolSize=10,  # Minimum connections to maintain
                maxIdleTimeMS=300000,  # 5 minutes before closing idle connections
                waitQueueTimeoutMS=30000,  # Wait 30s for connection from pool
                
                # Retry configuration
                retryWrites=DATABASE_CONFIG['retry_writes'],
                retryReads=DATABASE_CONFIG['retry_reads'],
                
                # Additional reliability settings
                appname='JobExtractor-Workday',  # Helps identify connections in MongoDB logs
                compressors='snappy,zlib',  # Enable compression to reduce network traffic
            )
            
            # Test the connection
            self.client.admin.command('ismaster')
            logging.info(f"Successfully connected to MongoDB (pool size: {connection_pool_size})")
            
        except Exception as e:
            logging.error(f"Failed to connect to MongoDB: {e}")
            logging.error("Please check your network connection and MongoDB URI")
            raise
    
    def _init_collections(self):
        """Initialize database collections"""
        try:
            # Greenhouse database
            self.greenhouse_db = self.client['GreenhouseDB']
            self.company_collection = self.greenhouse_db['CompanyData']
            
            # Workday database
            self.workday_company_collection = self.greenhouse_db['WorkdayCompanyData']

            # Muse company data (job-ID tracking per company)
            self.muse_company_collection = self.greenhouse_db['museCompanyData']

            # Employers collection (UsersDB) - source of Muse companies for ID maintenance
            self.users_db = self.client['UsersDB']
            self.employers_collection = self.users_db['employers']

            # Stats collection for tracking runs
            self.stats_collection = self.greenhouse_db['stats']
            
            # Jobs database
            self.jobs_db = self.client["JobsDB"]
            self.job_extractions_collection = self.jobs_db["jobs"]
            
            # Tokens database
            self.tokens_db = self.client["TokensDB"]
            self.job_token_collection = self.tokens_db["jobs"]
            
            logging.info("Database collections initialized successfully")
            
        except Exception as e:
            logging.error(f"Error accessing MongoDB databases: {e}")
            raise
    
    def _retry_operation(self, operation, max_retries: int = 3, retry_delay: float = 2.0):
        """Retry a database operation on timeout/connection errors
        
        Args:
            operation: Lambda function containing the database operation
            max_retries: Maximum number of retry attempts
            retry_delay: Delay between retries in seconds
            
        Returns:
            Result of the operation
        """
        last_error = None
        
        for attempt in range(max_retries):
            try:
                return operation()
            except (ConnectionFailure, ServerSelectionTimeoutError, NetworkTimeout, CursorNotFound) as e:
                last_error = e
                if attempt < max_retries - 1:
                    wait_time = retry_delay * (attempt + 1)
                    logging.warning(f"Database operation failed (attempt {attempt + 1}/{max_retries}): {e}")
                    logging.warning(f"Retrying in {wait_time} seconds...")
                    time.sleep(wait_time)
                else:
                    logging.error(f"Database operation failed after {max_retries} attempts: {e}")
        
        raise last_error
    
    def fetch_company_data(self, skip: int = 0, limit: int = 300) -> List[Dict]:
        """Fetch company data from MongoDB (Greenhouse) with retry logic"""
        def _fetch():
            try:
                total_count = self.company_collection.count_documents({})
                logging.info(f"Total Greenhouse documents in collection: {total_count}")

                sample_doc = self.company_collection.find_one({})
                logging.info(f"Sample document fields: {list(sample_doc.keys()) if sample_doc else None}")
                
                # Use no_cursor_timeout to prevent cursor expiring during slow processing
                company_data = self.company_collection.find({}, {
                    "company": 1,
                    "_id": 1,  
                    "unique_name": 1,
                    "logo": 1,
                    "jobs": 1,
                    "new_jobs": 1,
                    "employer_id": 1
                }, no_cursor_timeout=True).sort("_id", 1).skip(skip).limit(limit)
                
                # Convert to list immediately and close cursor
                try:
                    result = list(company_data)
                finally:
                    company_data.close()
                logging.info(f"Query returned {len(result)} Greenhouse documents")
                return result

            except Exception as e:
                logging.error(f"An error occurred while fetching Greenhouse company data: {str(e)}")
                return []
        
        return self._retry_operation(_fetch)
    
    def fetch_workday_company_data(self, skip: int = 0, limit: int = 100) -> List[Dict]:
        """Fetch company data from MongoDB (Workday) with retry logic - only companies with new_job_links"""
        def _fetch():
            try:
                # Only log total count on first batch to avoid overhead
                if skip == 0:
                    total_count = self.workday_company_collection.count_documents(
                        {"new_job_links": {"$exists": True, "$ne": []}}
                    )
                    logging.info(f"Total Workday companies with new jobs: {total_count}")
                
                logging.info(f"Fetching Workday companies: skip={skip}, limit={limit}")
                
                # Only fetch companies that have new_job_links to process
                # Use projection to minimize data transfer and batch_size for memory optimization
                # no_cursor_timeout prevents cursor expiring during Selenium scraping (which can be slow)
                company_data = self.workday_company_collection.find(
                    {"new_job_links": {"$exists": True, "$ne": []}},
                    {
                        "company": 1,
                        "_id": 1,
                        "logo": 1,
                        "new_job_links": 1,
                        "employer_id": 1
                    },
                    no_cursor_timeout=True
                ).sort("_id", 1).skip(skip).limit(limit).batch_size(20)  # Smaller batch size
                
                logging.info(f"Converting cursor to list...")
                try:
                    result = list(company_data)
                finally:
                    company_data.close()
                logging.info(f"✅ Fetched {len(result)} Workday companies with new jobs")
                return result

            except Exception as e:
                logging.error(f"An error occurred while fetching Workday company data: {str(e)}")
                return []
        
        return self._retry_operation(_fetch)
    
    def job_exists(self, url: str) -> bool:
        """Check if a job with the given URL already exists with retry logic"""
        def _check():
            return self.job_extractions_collection.find_one({"url": url}, {"_id": 1}) is not None
        
        return self._retry_operation(_check)
    
    def insert_job(self, job_data: JobMongo) -> Optional[str]:
        """Insert a job into the database and return the inserted ID with retry logic"""
        def _insert():
            try:
                job_custom_id = ObjectId()
                document_mongo_dict = job_data.model_dump(by_alias=True)
                document_mongo_dict["_id"] = job_custom_id

                result = self.job_extractions_collection.insert_one(document_mongo_dict)
                logging.info(f"Job inserted successfully with ID: {result.inserted_id}")
                return str(result.inserted_id)
                
            except Exception as e:
                logging.error(f"Failed to insert job data: {e}")
                return None
        
        return self._retry_operation(_insert)
    
    def insert_job_tokens(self, token_document: JobDescriptionTokensMongo) -> bool:
        """Insert job tokens into the database with retry logic"""
        def _insert():
            try:
                token_custom_id = ObjectId()
                token_document_dict = token_document.model_dump(by_alias=True)
                token_document_dict["_id"] = token_custom_id

                result = self.job_token_collection.insert_one(token_document_dict)
                logging.info(f"Tokens inserted successfully for job ID: {token_document.job_id}")
                return True
                
            except Exception as e:
                logging.error(f"Failed to insert token data: {e}")
                return False
        
        return self._retry_operation(_insert)
    
    def update_company_job_status(self, unique_name: str, job_id: int, job_data: Dict):
        """Move job from new_jobs to jobs in company data with retry logic"""
        def _update():
            try:
                self.company_collection.update_one(
                    {"unique_name": unique_name},
                    {
                        "$pull": {"new_jobs": {"id": job_id}},
                        "$push": {"jobs": job_data}
                    }
                )
                logging.info(f"Updated company data for unique_name: {unique_name}, moved job ID {job_id} from 'new_jobs' to 'jobs'.")
                
            except Exception as e:
                logging.error(f"Failed to update company job status: {e}")
        
        return self._retry_operation(_update)
    
    def remove_job_from_new_jobs(self, company_name: str, job_id: int):
        """Remove job from new_jobs list when not found (403 error) - Greenhouse with retry logic"""
        def _remove():
            try:
                self.company_collection.update_one(
                    {"company": company_name},
                    {"$pull": {"new_jobs": {"id": job_id}}}
                )
                logging.info(f"Removed job ID {job_id} from new_jobs for company: {company_name}")
                
            except Exception as e:
                logging.error(f"Failed to remove job from new_jobs: {e}")
        
        return self._retry_operation(_remove)
    
    def remove_workday_job_from_new_links(self, company_name: str, job_link: str):
        """Remove job link from new_job_links list when not found - Workday with retry logic"""
        def _remove():
            try:
                self.workday_company_collection.update_one(
                    {"company": company_name},
                    {"$pull": {"new_job_links": job_link}}
                )
                logging.info(f"Removed job link {job_link} from new_job_links for company: {company_name}")
                
            except Exception as e:
                logging.error(f"Failed to remove Workday job from new_job_links: {e}")
        
        return self._retry_operation(_remove)
    
    def update_workday_company_job_status(self, company_name: str, job_link: str):
        """Move job link from new_job_links to job_links in Workday company data with retry logic"""
        def _update():
            try:
                self.workday_company_collection.update_one(
                    {"company": company_name},
                    {
                        "$pull": {"new_job_links": job_link},
                        "$push": {"job_links": job_link}
                    }
                )
                logging.info(f"Updated Workday company data for company: {company_name}, moved job link from 'new_job_links' to 'job_links'.")
                
            except Exception as e:
                logging.error(f"Failed to update Workday company job status: {e}")
        
        return self._retry_operation(_update)
    
    def bulk_insert_jobs(self, jobs_data: List[JobMongo]) -> Dict:
        """
        Bulk insert multiple jobs at once
        
        Args:
            jobs_data: List of JobMongo objects to insert
            
        Returns:
            Dictionary with 'inserted_count' and 'inserted_ids'
        """
        def _bulk_insert():
            try:
                if not jobs_data:
                    return {'inserted_count': 0, 'inserted_ids': []}
                
                documents = []
                for job_data in jobs_data:
                    job_custom_id = ObjectId()
                    document_dict = job_data.model_dump(by_alias=True)
                    document_dict["_id"] = job_custom_id
                    documents.append(document_dict)
                
                result = self.job_extractions_collection.insert_many(documents, ordered=False)
                inserted_ids = [str(id) for id in result.inserted_ids]
                
                logging.info(f"Bulk inserted {len(inserted_ids)} jobs successfully")
                return {
                    'inserted_count': len(inserted_ids),
                    'inserted_ids': inserted_ids
                }
                
            except Exception as e:
                logging.error(f"Failed to bulk insert jobs: {e}")
                return {'inserted_count': 0, 'inserted_ids': []}
        
        return self._retry_operation(_bulk_insert)
    
    def bulk_delete_jobs_by_ids(self, job_ids: List[str], id_field: str = '_id') -> int:
        """
        Bulk delete jobs by their IDs
        
        Args:
            job_ids: List of job IDs to delete
            id_field: Field name for the ID ('_id', 'greenhouse_id', 'url', etc.)
            
        Returns:
            Number of deleted jobs
        """
        def _bulk_delete():
            try:
                if not job_ids:
                    return 0
                
                # Convert to ObjectId if using _id field
                if id_field == '_id':
                    query_ids = [ObjectId(id) for id in job_ids]
                else:
                    query_ids = job_ids
                
                result = self.job_extractions_collection.delete_many({
                    id_field: {"$in": query_ids}
                })
                
                logging.info(f"Bulk deleted {result.deleted_count} jobs")
                return result.deleted_count
                
            except Exception as e:
                logging.error(f"Failed to bulk delete jobs: {e}")
                return 0
        
        return self._retry_operation(_bulk_delete)
    
    def bulk_insert_tokens(self, tokens_data: List[JobDescriptionTokensMongo]) -> int:
        """
        Bulk insert multiple job tokens at once
        
        Args:
            tokens_data: List of JobDescriptionTokensMongo objects
            
        Returns:
            Number of successfully inserted token documents
        """
        def _bulk_insert():
            try:
                if not tokens_data:
                    return 0
                
                documents = []
                for token_data in tokens_data:
                    token_custom_id = ObjectId()
                    document_dict = token_data.model_dump(by_alias=True)
                    document_dict["_id"] = token_custom_id
                    documents.append(document_dict)
                
                result = self.job_token_collection.insert_many(documents, ordered=False)
                
                logging.info(f"Bulk inserted {len(result.inserted_ids)} token documents")
                return len(result.inserted_ids)
                
            except Exception as e:
                logging.error(f"Failed to bulk insert tokens: {e}")
                return 0
        
        return self._retry_operation(_bulk_insert)
    
    def close(self):
        """Close database connection"""
        if hasattr(self, 'client'):
            self.client.close()
            logging.info("Database connection closed")
    
    # ===== Run Stats Methods =====
    
    def create_run_stat(self, run_stat: 'RunStats') -> Optional[str]:
        """
        Create a new run statistics entry
        
        Args:
            run_stat: RunStats model instance
            
        Returns:
            String ID of the inserted document, or None if failed
        """
        def _insert():
            try:
                stat_id = ObjectId()
                stat_dict = run_stat.model_dump(by_alias=True)
                stat_dict["_id"] = stat_id
                
                result = self.stats_collection.insert_one(stat_dict)
                logging.info(f"📊 Run stats created with ID: {result.inserted_id}")
                return str(result.inserted_id)
                
            except Exception as e:
                logging.error(f"Failed to create run stats: {e}")
                return None
        
        return self._retry_operation(_insert)
    
    def update_run_stat(self, stat_id: str, updates: Dict) -> bool:
        """
        Update an existing run statistics entry
        
        Args:
            stat_id: The ObjectId of the stat document to update
            updates: Dictionary of fields to update
            
        Returns:
            True if successful, False otherwise
        """
        def _update():
            try:
                result = self.stats_collection.update_one(
                    {"_id": ObjectId(stat_id)},
                    {"$set": updates}
                )
                
                if result.modified_count > 0:
                    logging.info(f"📊 Run stats updated: {stat_id}")
                    return True
                else:
                    logging.warning(f"No run stats document found with ID: {stat_id}")
                    return False
                    
            except Exception as e:
                logging.error(f"Failed to update run stats: {e}")
                return False
        
        return self._retry_operation(_update)
    
    def add_run_error(self, stat_id: str, error_type: str, error_message: str, traceback: Optional[str] = None) -> bool:
        """
        Add an error to the run stats
        
        Args:
            stat_id: The ObjectId of the stat document
            error_type: Type/category of error
            error_message: Error message
            traceback: Optional full traceback
            
        Returns:
            True if successful, False otherwise
        """
        def _add_error():
            try:
                from datetime import datetime
                error_entry = {
                    "type": error_type,
                    "message": error_message,
                    "timestamp": datetime.utcnow(),
                }
                if traceback:
                    error_entry["traceback"] = traceback
                
                result = self.stats_collection.update_one(
                    {"_id": ObjectId(stat_id)},
                    {
                        "$push": {"errors": error_entry},
                        "$inc": {"error_count": 1}
                    }
                )
                
                if result.modified_count > 0:
                    logging.info(f"📊 Error added to run stats: {error_type}")
                    return True
                return False
                    
            except Exception as e:
                logging.error(f"Failed to add error to run stats: {e}")
                return False
        
        return self._retry_operation(_add_error)
    
    def get_latest_run_stats(self, limit: int = 10) -> List[Dict]:
        """
        Get the latest run statistics
        
        Args:
            limit: Number of recent runs to retrieve
            
        Returns:
            List of run stat documents
        """
        def _get_stats():
            try:
                cursor = (
                    self.stats_collection
                    .find()
                    .sort("start_time", -1)
                    .limit(limit)
                )
                try:
                    stats = list(cursor)
                finally:
                    cursor.close()
                return stats
            except Exception as e:
                logging.error(f"Failed to get run stats: {e}")
                return []
        
        return self._retry_operation(_get_stats)
    
    def get_run_stat_by_id(self, stat_id: str) -> Optional[Dict]:
        """
        Get a specific run stat by ID
        
        Args:
            stat_id: The ObjectId of the stat document
            
        Returns:
            Stat document or None
        """
        def _get_stat():
            try:
                return self.stats_collection.find_one({"_id": ObjectId(stat_id)})
            except Exception as e:
                logging.error(f"Failed to get run stat: {e}")
                return None

        return self._retry_operation(_get_stat)

    # ===== Muse Methods =====

    def fetch_muse_company_data(self, skip: int = 0, limit: int = 100) -> List[Dict]:
        """Fetch Muse companies with new_jobs from museCompanyData with retry logic"""
        def _fetch():
            try:
                # Only log total count on first batch to avoid overhead
                if skip == 0:
                    total_count = self.muse_company_collection.count_documents(
                        {"new_jobs": {"$exists": True, "$ne": []}}
                    )
                    logging.info(f"Total Muse companies with new jobs: {total_count}")

                logging.info(f"Fetching Muse companies: skip={skip}, limit={limit}")

                # Only fetch companies that have new_jobs to process.
                # no_cursor_timeout prevents the cursor expiring during slow API+parse work.
                company_data = self.muse_company_collection.find(
                    {"new_jobs": {"$exists": True, "$ne": []}},
                    {
                        "company": 1,
                        "_id": 1,
                        "logo": 1,
                        "new_jobs": 1,
                        "employer_id": 1,
                        "unique_name": 1
                    },
                    no_cursor_timeout=True
                ).sort("_id", 1).skip(skip).limit(limit)

                try:
                    result = list(company_data)
                finally:
                    company_data.close()
                logging.info(f"Query returned {len(result)} Muse companies")
                return result

            except Exception as e:
                logging.error(f"Error fetching Muse company data: {str(e)}")
                return []

        return self._retry_operation(_fetch)

    def muse_job_exists(self, muse_id: int) -> bool:
        """Check if a job with the given muse_id already exists with retry logic"""
        def _check():
            return self.job_extractions_collection.find_one({"muse_id": muse_id}, {"_id": 1}) is not None

        return self._retry_operation(_check)

    def update_muse_company_job_status(self, unique_name: str, job_id: int):
        """Remove job from new_jobs in Muse company data after processing with retry logic"""
        def _update():
            try:
                self.muse_company_collection.update_one(
                    {"unique_name": unique_name},
                    {"$pull": {"new_jobs": {"id": job_id}}}
                )
                logging.debug(f"Updated Muse company data for unique_name: {unique_name}, removed job ID {job_id} from 'new_jobs'.")

            except Exception as e:
                logging.error(f"Failed to update Muse company job status: {e}")

        return self._retry_operation(_update)