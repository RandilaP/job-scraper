"""Main entry point for the job extraction service with parallel processing."""

import sys
import logging
from config import setup_logging
from logtail_handler import setup_logtail_logging
from batch_processor import BatchJobProcessor


def main() -> None:
    """Main function to run the job extraction service with parallel processing."""
    try:
        print("🚀 Starting Job Extraction Server with Parallel Processing...")
        
        # Setup both local and remote logging
        setup_logging()
        setup_logtail_logging()
        
        logger = logging.getLogger(__name__)
        logger.info("🚀 Job Extraction Server starting with parallel processing...")
        
        # Initialize batch processor for all 1231 documents
        processor = BatchJobProcessor(
            total_documents=1231,    # Your actual total
            batch_size=300,          # Your preferred batch size
            num_processes=4          # Parallel processes (adjustable)
        )
        
        # Run parallel processing
        stats = processor.run_parallel_processing()
        
        if stats.get('success', True):
            logger.info("✅ Job Extraction Server completed successfully")
            print(f"🎉 Processing completed successfully!")
            print(f"📊 Final Statistics:")
            print(f"  ⏱️  Total time: {stats.get('total_time', 0)}s")
            print(f"  🏢 Companies processed: {stats.get('total_companies', 0)}")
            print(f"  💼 Jobs processed: {stats.get('total_jobs_processed', 0)}")
            print(f"  ✅ Jobs inserted: {stats.get('total_jobs_inserted', 0)}")
            print(f"  🔄 Jobs existed: {stats.get('total_jobs_existed', 0)}")
            print(f"  ❌ Jobs failed: {stats.get('total_jobs_failed', 0)}")
            print(f"  🚀 Processing rate: {stats.get('jobs_per_second', 0)} jobs/second")
        else:
            logger.error("❌ Job Extraction Server failed")
            print(f"❌ Processing failed: {stats.get('error', 'Unknown error')}")
            sys.exit(1)
        
    except KeyboardInterrupt:
        logger.info("⏹️ Job Extraction Server interrupted by user")
        print("\n👋 Server stopped by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"❌ Job extraction failed: {e}", exc_info=True)
        print(f"❌ Server failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()