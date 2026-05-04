"""
Synchronization Script for OpenSearch and MongoDB
This script removes jobs from OpenSearch that don't exist in MongoDB
"""

import logging
from typing import Set
from database import DatabaseManager
from opensearch_service import OpenSearchService
from opensearchpy import helpers

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class JobSyncService:
    """Service to synchronize jobs between MongoDB and OpenSearch"""
    
    def __init__(self):
        """Initialize database and OpenSearch connections"""
        self.db_manager = DatabaseManager()
        self.opensearch_service = OpenSearchService()
    
    def get_all_mongodb_job_ids(self) -> Set[str]:
        """
        Fetch all job IDs from MongoDB
        
        Returns:
            Set of job IDs as strings
        """
        logger.info("Fetching all job IDs from MongoDB...")
        try:
            # Early exit: check if collection has any documents
            total_count = self.db_manager.job_extractions_collection.count_documents({})
            if total_count == 0:
                logger.info("⚡ Early exit: No jobs found in MongoDB")
                return set()
            
            # Fetch only _id field to minimize memory usage
            jobs_cursor = self.db_manager.job_extractions_collection.find(
                {},
                {"_id": 1}
            ).batch_size(1000)
            
            # Convert ObjectIds to strings and create a set
            job_ids = {str(job["_id"]) for job in jobs_cursor}
            
            logger.info(f"Found {len(job_ids)} jobs in MongoDB")
            return job_ids
            
        except Exception as e:
            logger.error(f"Error fetching MongoDB job IDs: {e}")
            raise
    
    def get_all_opensearch_job_ids(self) -> Set[str]:
        """
        Fetch all job IDs from OpenSearch
        
        Returns:
            Set of job IDs as strings
        """
        logger.info("Fetching all job IDs from OpenSearch...")
        try:
            job_ids = set()
            
            # Use scroll API to fetch all documents efficiently
            query = {
                "query": {
                    "match_all": {}
                },
                "_source": False  # Don't fetch document source, only IDs
            }
            
            # Initialize scroll
            response = self.opensearch_service.client.search(
                index=self.opensearch_service.index_name,
                body=query,
                scroll='5m',
                size=1000
            )
            
            scroll_id = response['_scroll_id']
            hits = response['hits']['hits']
            
            # Process first batch
            for hit in hits:
                job_ids.add(hit['_id'])
            
            # Continue scrolling until no more results
            while len(hits) > 0:
                response = self.opensearch_service.client.scroll(
                    scroll_id=scroll_id,
                    scroll='5m'
                )
                scroll_id = response['_scroll_id']
                hits = response['hits']['hits']
                
                for hit in hits:
                    job_ids.add(hit['_id'])
            
            # Clear scroll
            self.opensearch_service.client.clear_scroll(scroll_id=scroll_id)
            
            logger.info(f"Found {len(job_ids)} jobs in OpenSearch")
            return job_ids
            
        except Exception as e:
            logger.error(f"Error fetching OpenSearch job IDs: {e}")
            raise
    
    def delete_orphaned_jobs(self, orphaned_job_ids: Set[str]) -> dict:
        """
        Delete jobs from OpenSearch that don't exist in MongoDB
        Uses bulk deletion for improved performance
        
        Args:
            orphaned_job_ids: Set of job IDs to delete
            
        Returns:
            Dictionary with deletion statistics
        """
        logger.info(f"Deleting {len(orphaned_job_ids)} orphaned jobs from OpenSearch using bulk operations...")
        
        if not orphaned_job_ids:
            return {
                "total_orphaned": 0,
                "deleted": 0,
                "failed": 0,
                "failed_ids": []
            }
        
        # Convert set to list for bulk deletion
        orphaned_list = list(orphaned_job_ids)
        
        # Use bulk deletion for better performance
        result = self.opensearch_service.bulk_delete_jobs(orphaned_list)
        
        logger.info(f"Bulk deletion completed: {result['success']} succeeded, {result['failed']} failed")
        
        return {
            "total_orphaned": len(orphaned_job_ids),
            "deleted": result['success'],
            "failed": result['failed'],
            "failed_ids": []  # bulk operation doesn't track individual failures
        }
    
    def sync(self, dry_run: bool = False) -> dict:
        """
        Synchronize OpenSearch with MongoDB by removing orphaned jobs
        
        Args:
            dry_run: If True, only report what would be deleted without actually deleting
            
        Returns:
            Dictionary with sync statistics
        """
        logger.info("Starting synchronization process...")
        logger.info(f"Dry run mode: {dry_run}")
        
        # Get all job IDs from both sources
        mongodb_ids = self.get_all_mongodb_job_ids()
        
        # Early exit: no MongoDB jobs (nothing to sync)
        if not mongodb_ids:
            logger.info("⚡ Early exit: No jobs in MongoDB, nothing to sync")
            return {
                "mongodb_count": 0,
                "opensearch_count": 0,
                "orphaned_count": 0,
                "deleted": 0,
                "failed": 0
            }
        
        opensearch_ids = self.get_all_opensearch_job_ids()
        
        # Early exit: OpenSearch is empty (already in sync)
        if not opensearch_ids:
            logger.info("⚡ Early exit: OpenSearch is empty (already in sync)")
            return {
                "mongodb_count": len(mongodb_ids),
                "opensearch_count": 0,
                "orphaned_count": 0,
                "deleted": 0,
                "failed": 0
            }
        
        # Find orphaned jobs (in OpenSearch but not in MongoDB)
        orphaned_ids = opensearch_ids - mongodb_ids
        
        logger.info(f"\nSynchronization Summary:")
        logger.info(f"  MongoDB jobs: {len(mongodb_ids)}")
        logger.info(f"  OpenSearch jobs: {len(opensearch_ids)}")
        logger.info(f"  Orphaned jobs (to be deleted): {len(orphaned_ids)}")
        
        # Early exit: no orphaned jobs (already in sync)
        if len(orphaned_ids) == 0:
            logger.info("⚡ Early exit: No orphaned jobs found. OpenSearch is in sync with MongoDB!")
            return {
                "mongodb_count": len(mongodb_ids),
                "opensearch_count": len(opensearch_ids),
                "orphaned_count": 0,
                "deleted": 0,
                "failed": 0
            }
        
        if dry_run:
            logger.info(f"\nDRY RUN: Would delete {len(orphaned_ids)} jobs")
            logger.info(f"Sample orphaned job IDs (first 10): {list(orphaned_ids)[:10]}")
            return {
                "mongodb_count": len(mongodb_ids),
                "opensearch_count": len(opensearch_ids),
                "orphaned_count": len(orphaned_ids),
                "deleted": 0,
                "failed": 0,
                "dry_run": True
            }
        
        # Delete orphaned jobs
        deletion_result = self.delete_orphaned_jobs(orphaned_ids)
        
        logger.info(f"\nDeletion Results:")
        logger.info(f"  Successfully deleted: {deletion_result['deleted']}")
        logger.info(f"  Failed: {deletion_result['failed']}")
        
        if deletion_result['failed'] > 0:
            logger.warning(f"  Failed job IDs: {deletion_result['failed_ids'][:10]}")
        
        return {
            "mongodb_count": len(mongodb_ids),
            "opensearch_count": len(opensearch_ids),
            "orphaned_count": len(orphaned_ids),
            **deletion_result
        }


def main():
    """Main execution function"""
    import sys
    
    # Parse command line arguments
    dry_run = "--dry-run" in sys.argv or "-d" in sys.argv
    
    logger.info("=" * 60)
    logger.info("OpenSearch-MongoDB Synchronization Tool")
    logger.info("=" * 60)
    
    try:
        sync_service = JobSyncService()
        result = sync_service.sync(dry_run=dry_run)
        
        logger.info("\n" + "=" * 60)
        logger.info("Synchronization completed successfully!")
        logger.info(f"Final statistics: {result}")
        logger.info("=" * 60)
        
    except Exception as e:
        logger.error(f"\nSynchronization failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
