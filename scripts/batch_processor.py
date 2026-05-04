"""
Multi-processing batch job processor for efficient parallel processing
"""

import multiprocessing as mp
import logging
import time
import psutil
from typing import List, Dict, Optional
from datetime import datetime
from config import setup_logging
from logtail_handler import setup_logtail_logging

class ResourceMonitor:
    """Monitor system and process resources"""
    
    def __init__(self, process_name="batch_processor"):
        self.process_name = process_name
        self.start_time = time.time()
        
    def get_process_stats(self):
        """Get current process resource usage"""
        try:
            current_process = psutil.Process()
            
            stats = {
                'timestamp': datetime.now().isoformat(),
                'cpu_percent': current_process.cpu_percent(),
                'memory_mb': round(current_process.memory_info().rss / 1024 / 1024, 2),
                'memory_percent': round(current_process.memory_percent(), 2),
                'num_threads': current_process.num_threads(),
                'num_fds': current_process.num_fds() if hasattr(current_process, 'num_fds') else 0,
            }
            
            return stats
        except Exception as e:
            logging.warning(f"Could not get process stats: {e}")
            return {}
    
    def get_system_stats(self):
        """Get overall system resource usage"""
        try:
            cpu_percent = psutil.cpu_percent(interval=0.1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            
            return {
                'timestamp': datetime.now().isoformat(),
                'cpu_percent': round(cpu_percent, 2),
                'memory_percent': round(memory.percent, 2),
                'available_memory_gb': round(memory.available / 1024 / 1024 / 1024, 2),
                'disk_usage_percent': round(disk.percent, 2),
                'total_memory_gb': round(memory.total / 1024 / 1024 / 1024, 2),
            }
        except Exception as e:
            logging.warning(f"Could not get system stats: {e}")
            return {}
    
    def log_resources(self, prefix="📊"):
        """Log current resource usage"""
        try:
            process_stats = self.get_process_stats()
            system_stats = self.get_system_stats()
            
            if process_stats:
                logging.info(f"{prefix} Process: CPU {process_stats['cpu_percent']}%, "
                           f"Memory {process_stats['memory_mb']}MB ({process_stats['memory_percent']}%), "
                           f"Threads {process_stats['num_threads']}")
            
            if system_stats:
                logging.info(f"🖥️ System: CPU {system_stats['cpu_percent']}%, "
                           f"Memory {system_stats['memory_percent']}% "
                           f"({system_stats['available_memory_gb']}GB free)")
                           
        except Exception as e:
            logging.warning(f"Could not log resource stats: {e}")


class BatchJobProcessor:
    """Multi-process job processor that handles large datasets efficiently"""
    
    def __init__(self, total_documents: int = 1231, batch_size: int = 300, num_processes: int = None):
        self.total_documents = total_documents
        self.batch_size = batch_size
        self.num_processes = num_processes or min(4, mp.cpu_count())
        self.monitor = ResourceMonitor("batch_processor")
        
        # Setup logging
        setup_logging()
        setup_logtail_logging()
        
        logging.info(f"🚀 Batch processor initialized:")
        logging.info(f"  📊 Total documents: {total_documents}")
        logging.info(f"  📦 Batch size: {batch_size}")
        logging.info(f"  🔄 Number of processes: {self.num_processes}")
        logging.info(f"  💻 Available CPU cores: {mp.cpu_count()}")
        
        # Log initial system resources
        self.monitor.log_resources("🔧")
    
    def calculate_batches(self) -> List[Dict]:
        """Calculate batch ranges for processing"""
        batches = []
        for i in range(0, self.total_documents, self.batch_size):
            batch = {
                'batch_id': len(batches) + 1,
                'skip': i,
                'limit': min(self.batch_size, self.total_documents - i),
                'start_doc': i + 1,
                'end_doc': min(i + self.batch_size, self.total_documents)
            }
            batches.append(batch)
        
        logging.info(f"📋 Created {len(batches)} batches for processing:")
        for batch in batches:
            logging.info(f"  Batch {batch['batch_id']}: docs {batch['start_doc']}-{batch['end_doc']} "
                        f"(skip={batch['skip']}, limit={batch['limit']})")
        
        return batches
    
    def process_batch(self, batch_info: Dict) -> Dict:
        """Process a single batch of companies"""
        batch_id = batch_info['batch_id']
        skip = batch_info['skip']
        limit = batch_info['limit']
        
        # Import here to avoid import issues with multiprocessing
        from service import JobExtractionService
        
        # Set up logging for this process
        setup_logging()
        setup_logtail_logging()
        process_logger = logging.getLogger(f"batch_{batch_id}")
        
        # Create monitor for this process
        batch_monitor = ResourceMonitor(f"batch_{batch_id}")
        
        try:
            process_logger.info(f"🚀 Starting batch {batch_id} processing "
                              f"(docs {batch_info['start_doc']}-{batch_info['end_doc']})")
            start_time = time.time()
            
            # Log initial resources for this batch
            batch_monitor.log_resources("🔧")
            
            # Create service instance for this process
            service = JobExtractionService()
            
            # Process this batch
            stats = service.process_companies_batch(skip=skip, limit=limit, batch_id=batch_id)
            
            end_time = time.time()
            processing_time = end_time - start_time
            
            # Log final resources for this batch
            batch_monitor.log_resources("✅")
            
            result = {
                'batch_id': batch_id,
                'processing_time': round(processing_time, 2),
                'companies_processed': stats.get('companies_processed', 0),
                'jobs_processed': stats.get('jobs_processed', 0),
                'jobs_inserted': stats.get('jobs_inserted', 0),
                'jobs_existed': stats.get('jobs_existed', 0),
                'jobs_failed': stats.get('jobs_failed', 0),
                'success': True,
                'start_doc': batch_info['start_doc'],
                'end_doc': batch_info['end_doc']
            }
            
            process_logger.info(f"✅ Batch {batch_id} completed in {processing_time:.2f}s")
            process_logger.info(f"  📊 Companies: {result['companies_processed']}")
            process_logger.info(f"  💼 Jobs processed: {result['jobs_processed']}")
            process_logger.info(f"  ✅ Jobs inserted: {result['jobs_inserted']}")
            process_logger.info(f"  🔄 Jobs existed: {result['jobs_existed']}")
            process_logger.info(f"  ❌ Jobs failed: {result['jobs_failed']}")
            
            return result
            
        except Exception as e:
            process_logger.error(f"❌ Batch {batch_id} failed: {e}", exc_info=True)
            return {
                'batch_id': batch_id,
                'error': str(e),
                'success': False,
                'start_doc': batch_info['start_doc'],
                'end_doc': batch_info['end_doc']
            }
    
    def run_parallel_processing(self) -> Dict:
        """Run all batches in parallel using multiprocessing"""
        batches = self.calculate_batches()
        
        logging.info(f"🚀 Starting parallel processing with {self.num_processes} processes...")
        start_time = time.time()
        
        # Log initial system resources
        self.monitor.log_resources("🔧")
        
        try:
            # Use multiprocessing pool
            with mp.Pool(processes=self.num_processes) as pool:
                # Map batches to processes
                results = pool.map(self.process_batch, batches)
            
            end_time = time.time()
            total_time = end_time - start_time
            
            # Log final system resources
            self.monitor.log_resources("🏁")
            
            # Aggregate results
            successful_batches = [r for r in results if r.get('success', False)]
            failed_batches = [r for r in results if not r.get('success', False)]
            
            total_stats = {
                'total_time': round(total_time, 2),
                'total_batches': len(batches),
                'successful_batches': len(successful_batches),
                'failed_batches': len(failed_batches),
                'total_companies': sum(r.get('companies_processed', 0) for r in successful_batches),
                'total_jobs_processed': sum(r.get('jobs_processed', 0) for r in successful_batches),
                'total_jobs_inserted': sum(r.get('jobs_inserted', 0) for r in successful_batches),
                'total_jobs_existed': sum(r.get('jobs_existed', 0) for r in successful_batches),
                'total_jobs_failed': sum(r.get('jobs_failed', 0) for r in successful_batches),
                'average_batch_time': round(sum(r.get('processing_time', 0) for r in successful_batches) / max(len(successful_batches), 1), 2),
                'jobs_per_second': round(sum(r.get('jobs_processed', 0) for r in successful_batches) / max(total_time, 1), 2)
            }
            
            # Log comprehensive summary
            logging.info("🎉 Parallel processing completed!")
            logging.info(f"  ⏱️  Total time: {total_stats['total_time']}s")
            logging.info(f"  📊 Successful batches: {total_stats['successful_batches']}/{total_stats['total_batches']}")
            logging.info(f"  🏢 Companies processed: {total_stats['total_companies']}")
            logging.info(f"  💼 Jobs processed: {total_stats['total_jobs_processed']}")
            logging.info(f"  ✅ Jobs inserted: {total_stats['total_jobs_inserted']}")
            logging.info(f"  🔄 Jobs existed: {total_stats['total_jobs_existed']}")
            logging.info(f"  ❌ Jobs failed: {total_stats['total_jobs_failed']}")
            logging.info(f"  ⚡ Average batch time: {total_stats['average_batch_time']}s")
            logging.info(f"  🚀 Processing rate: {total_stats['jobs_per_second']} jobs/second")
            
            if failed_batches:
                failed_batch_info = []
                for b in failed_batches:
                    failed_batch_info.append(f"Batch {b['batch_id']} (docs {b['start_doc']}-{b['end_doc']})")
                logging.error(f"❌ Failed batches: {failed_batch_info}")
                for batch in failed_batches:
                    logging.error(f"  Batch {batch['batch_id']} error: {batch.get('error', 'Unknown error')}")
            
            return total_stats
            
        except Exception as e:
            logging.error(f"❌ Parallel processing failed: {e}", exc_info=True)
            return {
                'error': str(e),
                'success': False,
                'total_time': time.time() - start_time
            }


if __name__ == "__main__":
    # Direct execution for testing
    processor = BatchJobProcessor(total_documents=1231, batch_size=300, num_processes=4)
    stats = processor.run_parallel_processing()
    print(f"Final stats: {stats}")