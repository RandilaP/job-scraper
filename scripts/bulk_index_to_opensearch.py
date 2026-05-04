"""
Bulk Indexing Script for Migrating Existing Jobs to OpenSearch
"""
import logging
from datetime import datetime
from typing import List, Dict
from database import DatabaseManager
from opensearch_service import OpenSearchService

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class BulkIndexer:
    """Bulk index existing jobs from MongoDB to OpenSearch"""

    def __init__(self):
        """Initialize database and OpenSearch connections"""
        self.db_manager = DatabaseManager()
        self.opensearch = OpenSearchService()

    def fetch_jobs_batch(self, skip: int, limit: int) -> List[Dict]:
        """
        Fetch a batch of jobs from MongoDB
        
        Args:
            skip: Number of documents to skip
            limit: Maximum number of documents to fetch
            
        Returns:
            List of job documents
        """
        try:
            jobs = self.db_manager.job_extractions_collection.find({}).skip(skip).limit(limit)
            return list(jobs)
        except Exception as e:
            logger.error(f"Failed to fetch jobs batch: {e}")
            return []

    def get_total_jobs_count(self) -> int:
        """
        Get total number of jobs in MongoDB
        
        Returns:
            Total job count
        """
        try:
            count = self.db_manager.job_extractions_collection.count_documents({})
            logger.info(f"Total jobs in MongoDB: {count}")
            return count
        except Exception as e:
            logger.error(f"Failed to get job count: {e}")
            return 0

    def index_all_jobs(self, batch_size: int = 500, create_index: bool = True):
        """
        Index all jobs from MongoDB to OpenSearch in batches
        
        Args:
            batch_size: Number of jobs to index per batch
            create_index: Whether to create/recreate the index
        """
        try:
            # Create index if requested
            if create_index:
                logger.info("Creating OpenSearch index...")
                self.opensearch.create_index(delete_if_exists=True)

            # Get total jobs
            total_jobs = self.get_total_jobs_count()
            if total_jobs == 0:
                logger.warning("No jobs found in MongoDB")
                return

            # Process in batches
            skip = 0
            total_indexed = 0
            total_failed = 0
            start_time = datetime.now()

            logger.info(f"Starting bulk indexing of {total_jobs} jobs...")

            while skip < total_jobs:
                # Fetch batch
                logger.info(f"Fetching jobs {skip} to {skip + batch_size}...")
                jobs_batch = self.fetch_jobs_batch(skip, batch_size)

                if not jobs_batch:
                    logger.warning(f"No jobs returned for batch starting at {skip}")
                    break

                # Index batch
                logger.info(f"Indexing batch of {len(jobs_batch)} jobs...")
                result = self.opensearch.bulk_index_jobs(jobs_batch)

                total_indexed += result['success']
                total_failed += result['failed']

                # Log progress
                progress = (skip + len(jobs_batch)) / total_jobs * 100
                logger.info(
                    f"Progress: {progress:.1f}% "
                    f"({skip + len(jobs_batch)}/{total_jobs}) - "
                    f"Success: {result['success']}, Failed: {result['failed']}"
                )

                skip += batch_size

            # Calculate duration
            duration = (datetime.now() - start_time).total_seconds()

            # Final summary
            logger.info("=" * 60)
            logger.info("BULK INDEXING SUMMARY")
            logger.info("=" * 60)
            logger.info(f"Total jobs processed: {total_jobs}")
            logger.info(f"Successfully indexed: {total_indexed}")
            logger.info(f"Failed: {total_failed}")
            logger.info(f"Duration: {duration:.2f} seconds")
            logger.info(f"Average rate: {total_indexed / duration:.2f} jobs/second")
            logger.info("=" * 60)

            # Get index stats
            stats = self.opensearch.get_index_stats()
            if stats:
                logger.info(f"Index statistics: {stats}")

        except Exception as e:
            logger.error(f"Bulk indexing failed: {e}")
            raise

    def reindex_specific_jobs(self, job_ids: List[str]):
        """
        Reindex specific jobs by their IDs
        
        Args:
            job_ids: List of job IDs to reindex
        """
        try:
            from bson import ObjectId

            logger.info(f"Reindexing {len(job_ids)} specific jobs...")

            for job_id in job_ids:
                try:
                    # Fetch job from MongoDB
                    job = self.db_manager.job_extractions_collection.find_one(
                        {"_id": ObjectId(job_id)}
                    )

                    if not job:
                        logger.warning(f"Job {job_id} not found in MongoDB")
                        continue

                    # Index to OpenSearch
                    success = self.opensearch.index_job(job_id, job)
                    if success:
                        logger.info(f"Successfully reindexed job {job_id}")
                    else:
                        logger.error(f"Failed to reindex job {job_id}")

                except Exception as e:
                    logger.error(f"Error reindexing job {job_id}: {e}")

        except Exception as e:
            logger.error(f"Reindexing failed: {e}")
            raise

    def verify_indexing(self):
        """
        Verify that indexing was successful
        """
        try:
            # Get counts from both systems
            mongo_count = self.get_total_jobs_count()
            
            stats = self.opensearch.get_index_stats()
            opensearch_count = stats.get('document_count', 0)

            logger.info("=" * 60)
            logger.info("VERIFICATION RESULTS")
            logger.info("=" * 60)
            logger.info(f"MongoDB jobs: {mongo_count}")
            logger.info(f"OpenSearch documents: {opensearch_count}")
            logger.info(f"Difference: {abs(mongo_count - opensearch_count)}")

            if mongo_count == opensearch_count:
                logger.info("✓ Counts match - indexing successful!")
            else:
                logger.warning("✗ Counts don't match - some jobs may not be indexed")

            logger.info("=" * 60)

        except Exception as e:
            logger.error(f"Verification failed: {e}")

    def close(self):
        """Close all connections"""
        self.db_manager.close()
        self.opensearch.close()
        logger.info("All connections closed")


def main():
    """Main execution function"""
    indexer = None
    try:
        logger.info("Starting bulk indexing process...")
        
        # Initialize indexer
        indexer = BulkIndexer()
        
        # Index all jobs (batch_size=500, create_index=True)
        indexer.index_all_jobs(batch_size=500, create_index=True)
        
        # Verify indexing
        indexer.verify_indexing()
        
        logger.info("Bulk indexing completed successfully!")

    except Exception as e:
        logger.error(f"Bulk indexing process failed: {e}")
        raise

    finally:
        if indexer:
            indexer.close()


if __name__ == "__main__":
    main()
