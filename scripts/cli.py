"""
Command Line Interface for Job Extraction Server
Provides flexible processing modes: single, batch, parallel
Supports multiple sources: Greenhouse, Workday, or both
"""

import argparse
import sys
import logging
from config import setup_logging
from logtail_handler import setup_logtail_logging
from batch_processor import BatchJobProcessor
from workday_batch_processor import WorkdayBatchProcessor
from service import JobExtractionService
import config


def setup_cli_parser():
    """Setup command line argument parser"""
    parser = argparse.ArgumentParser(
        description='Job Extraction Server - Flexible Processing Modes',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run with default parallel processing (4 processes, 300 batch size)
  python cli.py

  # Run only Greenhouse jobs
  python cli.py --source greenhouse

  # Run only Workday jobs (14 parallel workers, 100 batch size)
  python cli.py --source workday

  # Run both sources
  python cli.py --source both

  # Run single batch for testing (skip first 300, process next 300)
  python cli.py --mode single --skip 300 --limit 300 --source greenhouse

  # Run sequential batches (one at a time)
  python cli.py --mode sequential --batch-size 200

  # Run parallel with custom settings
  python cli.py --mode parallel --processes 6 --batch-size 250 --total-docs 1231

  # Resource monitoring mode
  python cli.py --mode parallel --monitor-resources --processes 2
        """
    )
    
    # Source selection
    parser.add_argument(
        '--source',
        choices=['greenhouse', 'workday', 'both'],
        default=None,
        help=f'Job source to process (default: from config - {config.JOB_SOURCE})'
    )
    
    # Processing mode
    parser.add_argument(
        '--mode', 
        choices=['single', 'sequential', 'parallel'], 
        default='parallel', 
        help='Processing mode (default: parallel)'
    )
    
    # Parallel processing options
    parser.add_argument(
        '--processes', 
        type=int, 
        default=4, 
        help='Number of parallel processes (default: 4)'
    )
    
    # Batch configuration
    parser.add_argument(
        '--batch-size', 
        type=int, 
        default=300, 
        help='Batch size for processing (default: 300)'
    )
    
    parser.add_argument(
        '--total-docs', 
        type=int, 
        default=1231, 
        help='Total number of documents to process (default: 1231)'
    )
    
    # Single batch mode options
    parser.add_argument(
        '--skip', 
        type=int, 
        default=0, 
        help='Skip documents (for single batch mode, default: 0)'
    )
    
    parser.add_argument(
        '--limit', 
        type=int, 
        default=300, 
        help='Limit documents (for single batch mode, default: 300)'
    )
    
    # Monitoring options
    parser.add_argument(
        '--monitor-resources', 
        action='store_true', 
        help='Enable detailed resource monitoring'
    )
    
    # Logging options
    parser.add_argument(
        '--log-level', 
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'], 
        default='INFO', 
        help='Logging level (default: INFO)'
    )
    
    parser.add_argument(
        '--disable-remote-logging', 
        action='store_true', 
        help='Disable remote logging to Logtail'
    )
    
    return parser


def run_single_batch(args):
    """Run a single batch of companies"""
    source = args.source or config.JOB_SOURCE
    print(f"🔄 Running single batch mode for {source} (skip={args.skip}, limit={args.limit})")
    
    service = JobExtractionService(source=source)
    stats = service.process_companies_batch(skip=args.skip, limit=args.limit)
    
    print(f"✅ Single batch completed!")
    print(f"📊 Statistics:")
    print(f"  🏢 Companies processed: {stats.get('companies_processed', 0)}")
    print(f"  💼 Jobs processed: {stats.get('jobs_processed', 0)}")
    print(f"  ✅ Jobs inserted: {stats.get('jobs_inserted', 0)}")
    print(f"  🔄 Jobs existed: {stats.get('jobs_existed', 0)}")
    print(f"  ❌ Jobs failed: {stats.get('jobs_failed', 0)}")
    print(f"  ⏱️  Processing time: {stats.get('processing_time', 0):.2f}s")
    
    return stats


def run_sequential_batches(args):
    """Run all batches sequentially"""
    source = args.source or config.JOB_SOURCE
    print(f"🔄 Running sequential batch mode for {source} (batch_size={args.batch_size})")
    
    if source == 'greenhouse' or source == 'both':
        print("\n📦 Processing Greenhouse jobs sequentially...")
        processor = BatchJobProcessor(
            total_documents=args.total_docs,
            batch_size=args.batch_size,
            num_processes=1  # Sequential processing
        )
        
        batches = processor.calculate_batches()
        results = []
        
        for i, batch in enumerate(batches, 1):
            print(f"\n📦 Processing Greenhouse batch {i}/{len(batches)}: {batch['start_doc']}-{batch['end_doc']}")
            result = processor.process_batch(batch)
            results.append(result)
            
            if result.get('success', False):
                print(f"✅ Batch {i} completed in {result.get('processing_time', 0):.2f}s")
            else:
                print(f"❌ Batch {i} failed: {result.get('error', 'Unknown error')}")
    
    if source == 'workday' or source == 'both':
        print("\n📦 Processing Workday jobs sequentially...")
        workday_processor = WorkdayBatchProcessor(num_workers=1)  # Sequential
        workday_results = workday_processor.process_all_companies()
        print(f"✅ Workday processing completed!")
    
    print("\n✅ All sequential processing completed!")
    
    # Calculate totals
    successful_batches = [r for r in results if r.get('success', False)]
    
    print(f"\n🎉 Sequential processing completed!")
    print(f"📊 Final Statistics:")
    print(f"  📦 Successful batches: {len(successful_batches)}/{len(batches)}")
    print(f"  🏢 Total companies: {sum(r.get('companies_processed', 0) for r in successful_batches)}")
    print(f"  💼 Total jobs processed: {sum(r.get('jobs_processed', 0) for r in successful_batches)}")
    print(f"  ✅ Total jobs inserted: {sum(r.get('jobs_inserted', 0) for r in successful_batches)}")
    
    return results


def run_parallel_processing(args):
    """Run parallel batch processing"""
    source = args.source or config.JOB_SOURCE
    print(f"🚀 Running parallel processing mode for {source}")
    print(f"   Processes: {args.processes}, Batch size: {args.batch_size}")
    
    results = {}
    
    if source == 'greenhouse' or source == 'both':
        print("\n📦 Processing Greenhouse jobs in parallel...")
        processor = BatchJobProcessor(
            total_documents=args.total_docs,
            batch_size=args.batch_size,
            num_processes=args.processes
        )
        
        greenhouse_stats = processor.process_all_batches()
        results['greenhouse'] = greenhouse_stats
        
        print(f"\n✅ Greenhouse parallel processing completed!")
        print(f"📊 Statistics:")
        print(f"  🏢 Companies processed: {greenhouse_stats.get('companies_processed', 0)}")
        print(f"  💼 Jobs processed: {greenhouse_stats.get('jobs_processed', 0)}")
        print(f"  ✅ Jobs inserted: {greenhouse_stats.get('jobs_inserted', 0)}")
        print(f"  🔄 Jobs existed: {greenhouse_stats.get('jobs_existed', 0)}")
        print(f"  ❌ Jobs failed: {greenhouse_stats.get('jobs_failed', 0)}")
        print(f"  ⏱️  Total time: {greenhouse_stats.get('total_time', 0):.2f}s")
    
    if source == 'workday' or source == 'both':
        print("\n📦 Processing Workday jobs in parallel...")
        workday_processor = WorkdayBatchProcessor(
            num_workers=config.WORKDAY_PARALLEL_WORKERS
        )
        
        workday_stats = workday_processor.process_all_companies()
        results['workday'] = workday_stats
        
        print(f"\n✅ Workday parallel processing completed!")
        print(f"📊 Statistics:")
        print(f"  🏢 Companies processed: {workday_stats.get('companies_processed', 0)}")
        print(f"  💼 Jobs processed: {workday_stats.get('jobs_processed', 0)}")
        print(f"  ✅ Jobs inserted: {workday_stats.get('jobs_inserted', 0)}")
        print(f"  🔄 Jobs existed: {workday_stats.get('jobs_existed', 0)}")
        print(f"  ❌ Jobs failed: {workday_stats.get('jobs_failed', 0)}")
        print(f"  ⏱️  Total time: {workday_stats.get('total_time', 0):.2f}s")
    
    print("\n🎉 All parallel processing completed!")
    return results


def main():
    """Main CLI entry point"""
    parser = setup_cli_parser()
    args = parser.parse_args()
    
    # Setup logging
    setup_logging()
    if not args.disable_remote_logging:
        setup_logtail_logging()
    
    # Set logging level
    logging.getLogger().setLevel(getattr(logging, args.log_level))
    
    logger = logging.getLogger(__name__)
    source = args.source or config.JOB_SOURCE
    logger.info(f"🚀 Starting Job Extraction CLI in {args.mode} mode for {source}")
    
    try:
        # Display configuration
        print(f"🔧 Configuration:")
        print(f"  Source: {source}")
        print(f"  Mode: {args.mode}")
        print(f"  Total documents: {args.total_docs}")
        print(f"  Batch size: {args.batch_size}")
        if args.mode == 'parallel':
            print(f"  Processes: {args.processes}")
        elif args.mode == 'single':
            print(f"  Skip: {args.skip}, Limit: {args.limit}")
        print(f"  Resource monitoring: {'Enabled' if args.monitor_resources else 'Disabled'}")
        print(f"  Remote logging: {'Disabled' if args.disable_remote_logging else 'Enabled'}")
        print()
        
        # Run based on mode
        if args.mode == 'single':
            stats = run_single_batch(args)
        elif args.mode == 'sequential':
            stats = run_sequential_batches(args)
        elif args.mode == 'parallel':
            stats = run_parallel_processing(args)
        else:
            print(f"❌ Unknown mode: {args.mode}")
            sys.exit(1)
        
        logger.info("✅ CLI processing completed successfully")
        
    except KeyboardInterrupt:
        logger.info("⏹️ CLI interrupted by user")
        print("\n👋 Processing stopped by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"❌ CLI processing failed: {e}", exc_info=True)
        print(f"❌ Processing failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()