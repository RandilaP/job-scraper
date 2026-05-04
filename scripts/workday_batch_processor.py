"""
Batch processor for Workday job extraction with parallel processing
"""
import logging
import time
import psutil
from multiprocessing import Pool, cpu_count
from typing import Dict, List
from workday_service import WorkdayExtractionService
import config


class WorkdayBatchProcessor:
    """Handles parallel batch processing for Workday job extraction"""
    
    def __init__(self, num_workers: int = None, enable_opensearch: bool = True):
        """
        Initialize the batch processor
        
        Args:
            num_workers: Number of parallel workers (default: from config)
            enable_opensearch: Whether to enable OpenSearch indexing
        """
        self.num_workers = num_workers or config.WORKDAY_PARALLEL_WORKERS
        self.enable_opensearch = enable_opensearch
        self.resource_monitor = ResourceMonitor()
        
        logging.info(f"Initialized Workday batch processor with {self.num_workers} workers")
    
    def process_all_companies(self, total_companies: int = None) -> Dict:
        """
        Process all Workday companies using parallel batch processing
        
        Args:
            total_companies: Total number of companies to process (default: all)
            
        Returns:
            Aggregated processing statistics
        """
        batch_size = config.WORKDAY_BATCH_SIZE
        
        # If total_companies not specified, get count from database
        if total_companies is None:
            from database import DatabaseManager
            db = DatabaseManager()
            try:
                total_companies = db.workday_company_collection.count_documents({})
                logging.info(f"Found {total_companies} Workday companies to process")
            finally:
                db.close()
        
        # Calculate number of batches
        num_batches = (total_companies + batch_size - 1) // batch_size
        
        logging.info(f"🚀 Starting Workday parallel processing:")
        logging.info(f"   Total companies: {total_companies}")
        logging.info(f"   Batch size: {batch_size}")
        logging.info(f"   Number of batches: {num_batches}")
        logging.info(f"   Parallel workers: {self.num_workers}")
        
        # Prepare batch arguments
        batch_args = []
        for i in range(num_batches):
            skip = i * batch_size
            batch_args.append((skip, batch_size, i + 1, self.enable_opensearch))
        
        # Start resource monitoring
        self.resource_monitor.start()
        start_time = time.time()
        
        # Process batches in parallel
        with Pool(processes=self.num_workers) as pool:
            batch_results = pool.starmap(process_workday_batch_worker, batch_args)
        
        # Stop resource monitoring
        end_time = time.time()
        self.resource_monitor.stop()
        
        # Aggregate results
        aggregated_stats = self._aggregate_results(batch_results, start_time, end_time)
        
        # Log final summary
        self._log_summary(aggregated_stats)
        
        return aggregated_stats
    
    def _aggregate_results(self, batch_results: List[Dict], start_time: float, end_time: float) -> Dict:
        """Aggregate results from all batches"""
        aggregated = {
            'source': 'workday',
            'total_batches': len(batch_results),
            'companies_processed': 0,
            'jobs_processed': 0,
            'jobs_inserted': 0,
            'jobs_existed': 0,
            'jobs_failed': 0,
            'jobs_indexed_opensearch': 0,
            'jobs_opensearch_failed': 0,
            'total_time': end_time - start_time,
            'batch_details': []
        }
        
        for batch_result in batch_results:
            aggregated['companies_processed'] += batch_result.get('companies_processed', 0)
            aggregated['jobs_processed'] += batch_result.get('jobs_processed', 0)
            aggregated['jobs_inserted'] += batch_result.get('jobs_inserted', 0)
            aggregated['jobs_existed'] += batch_result.get('jobs_existed', 0)
            aggregated['jobs_failed'] += batch_result.get('jobs_failed', 0)
            aggregated['jobs_indexed_opensearch'] += batch_result.get('jobs_indexed_opensearch', 0)
            aggregated['jobs_opensearch_failed'] += batch_result.get('jobs_opensearch_failed', 0)
            
            aggregated['batch_details'].append({
                'batch_id': batch_result.get('batch_id'),
                'processing_time': batch_result.get('processing_time', 0),
                'jobs_processed': batch_result.get('jobs_processed', 0),
                'jobs_inserted': batch_result.get('jobs_inserted', 0)
            })
        
        # Add resource usage
        aggregated['resource_usage'] = self.resource_monitor.get_stats()
        
        return aggregated
    
    def _log_summary(self, stats: Dict):
        """Log processing summary"""
        logging.info("=" * 80)
        logging.info("WORKDAY BATCH PROCESSING SUMMARY")
        logging.info("=" * 80)
        logging.info(f"Source: {stats['source']}")
        logging.info(f"Total batches: {stats['total_batches']}")
        logging.info(f"Companies processed: {stats['companies_processed']}")
        logging.info(f"Jobs processed: {stats['jobs_processed']}")
        logging.info(f"Jobs inserted: {stats['jobs_inserted']}")
        logging.info(f"Jobs existed: {stats['jobs_existed']}")
        logging.info(f"Jobs failed: {stats['jobs_failed']}")
        logging.info(f"Jobs indexed to OpenSearch: {stats['jobs_indexed_opensearch']}")
        logging.info(f"OpenSearch indexing failed: {stats['jobs_opensearch_failed']}")
        logging.info(f"Total processing time: {stats['total_time']:.2f} seconds")
        
        if stats['jobs_processed'] > 0:
            success_rate = (stats['jobs_inserted'] / stats['jobs_processed']) * 100
            avg_time_per_job = stats['total_time'] / stats['jobs_processed']
            logging.info(f"Success rate: {success_rate:.1f}%")
            logging.info(f"Average time per job: {avg_time_per_job:.2f} seconds")
        
        # Resource usage
        resource_stats = stats.get('resource_usage', {})
        logging.info(f"Peak CPU usage: {resource_stats.get('peak_cpu', 0):.1f}%")
        logging.info(f"Peak memory usage: {resource_stats.get('peak_memory', 0):.1f} MB")
        logging.info(f"Average CPU usage: {resource_stats.get('avg_cpu', 0):.1f}%")
        logging.info(f"Average memory usage: {resource_stats.get('avg_memory', 0):.1f} MB")
        logging.info("=" * 80)


class ResourceMonitor:
    """Monitor system resource usage during processing"""
    
    def __init__(self):
        self.monitoring = False
        self.cpu_samples = []
        self.memory_samples = []
        self.process = psutil.Process()
    
    def start(self):
        """Start monitoring"""
        self.monitoring = True
        self.cpu_samples = []
        self.memory_samples = []
    
    def stop(self):
        """Stop monitoring"""
        self.monitoring = False
    
    def sample(self):
        """Take a resource usage sample"""
        if self.monitoring:
            try:
                cpu_percent = self.process.cpu_percent()
                memory_mb = self.process.memory_info().rss / 1024 / 1024
                
                self.cpu_samples.append(cpu_percent)
                self.memory_samples.append(memory_mb)
            except Exception as e:
                logging.warning(f"Error sampling resource usage: {e}")
    
    def get_stats(self) -> Dict:
        """Get resource usage statistics"""
        if not self.cpu_samples or not self.memory_samples:
            return {
                'peak_cpu': 0,
                'peak_memory': 0,
                'avg_cpu': 0,
                'avg_memory': 0
            }
        
        return {
            'peak_cpu': max(self.cpu_samples),
            'peak_memory': max(self.memory_samples),
            'avg_cpu': sum(self.cpu_samples) / len(self.cpu_samples),
            'avg_memory': sum(self.memory_samples) / len(self.memory_samples)
        }


def process_workday_batch_worker(skip: int, limit: int, batch_id: int, enable_opensearch: bool) -> Dict:
    """
    Worker function for processing a single batch
    This runs in a separate process
    """
    try:
        # Create service instance for this worker
        service = WorkdayExtractionService(enable_opensearch=enable_opensearch)
        
        # Process the batch
        stats = service.process_companies_batch(skip=skip, limit=limit, batch_id=batch_id)
        
        # Clean up
        service.close()
        
        return stats
        
    except Exception as e:
        logging.error(f"Worker {batch_id} failed: {e}")
        return {
            'batch_id': batch_id,
            'error': str(e),
            'companies_processed': 0,
            'jobs_processed': 0,
            'jobs_inserted': 0,
            'jobs_existed': 0,
            'jobs_failed': 0
        }
