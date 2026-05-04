"""
Logtail (Better Stack) logging handler for remote log monitoring
"""

import logging
import requests
import json
from datetime import datetime
import os
from threading import Thread
import queue
import time

class LogtailHandler(logging.Handler):
    """Async Logtail handler that sends logs to Better Stack"""
    
    def __init__(self, token, endpoint="https://s1535529.eu-nbg-2.betterstackdata.com"):
        super().__init__()
        self.token = token
        self.endpoint = endpoint
        self.queue = queue.Queue(maxsize=1000)  # Buffer up to 1000 logs
        self.worker_thread = Thread(target=self._worker, daemon=True)
        self.worker_thread.start()
        
    def emit(self, record):
        """Add log to queue for async processing"""
        try:
            log_entry = {
                "dt": datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC'),
                "message": self.format(record),
                "level": record.levelname,
                "source": {
                    "service": "job-extractor",
                    "module": getattr(record, 'module', record.name),
                    "function": getattr(record, 'funcName', ''),
                    "line": getattr(record, 'lineno', ''),
                },
                "environment": os.getenv('ENVIRONMENT', 'production'),
                "hostname": os.getenv('HOSTNAME', 'ec2-server')
            }
            
            # Add to queue (non-blocking)
            try:
                self.queue.put_nowait(log_entry)
            except queue.Full:
                # If queue is full, drop oldest log and add new one
                try:
                    self.queue.get_nowait()
                    self.queue.put_nowait(log_entry)
                except queue.Empty:
                    pass
                
        except Exception:
            pass  # Don't let logging errors crash the app
    
    def _worker(self):
        """Background worker to send logs to Logtail"""
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }
        
        while True:
            try:
                # Get log from queue (blocking with timeout)
                log_entry = self.queue.get(timeout=1)
                
                # Send to Logtail
                response = requests.post(
                    self.endpoint,
                    json=log_entry,
                    headers=headers,
                    timeout=10,
                    verify=False  # Using --insecure like your curl example
                )
                
                # Check if successful
                if response.status_code != 200:
                    # Could log to console, but avoid infinite loops
                    pass
                
                self.queue.task_done()
                
            except queue.Empty:
                continue
            except Exception as e:
                # If sending fails, just continue
                # Could log to console for debugging
                # print(f"Logtail error: {e}")
                continue
            
            # Small delay to avoid rate limiting
            time.sleep(0.1)

def setup_logtail_logging():
    """Setup logging with Logtail integration"""
    # Get root logger
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    
    # Clear any existing handlers to avoid duplicates
    logger.handlers.clear()
    
    # Console handler (for local viewing)
    console_handler = logging.StreamHandler()
    console_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)
    
    # Logtail handler (for remote viewing)
    logtail_token = os.getenv('LOGTAIL_TOKEN')
    if logtail_token:
        logtail_handler = LogtailHandler(logtail_token)
        logtail_formatter = logging.Formatter('%(message)s')  # Simple format for Logtail
        logtail_handler.setFormatter(logtail_formatter)
        logger.addHandler(logtail_handler)
        logger.info("🚀 Logtail remote logging enabled")
    else:
        logger.warning("⚠️ LOGTAIL_TOKEN not found - remote logging disabled")
    
    return logger

def test_logtail_connection():
    """Test Logtail connection"""
    token = os.getenv('LOGTAIL_TOKEN')
    if not token:
        print("❌ LOGTAIL_TOKEN not found in environment")
        return False
    
    endpoint = "https://s1535529.eu-nbg-2.betterstackdata.com"
    
    test_log = {
        "dt": datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC'),
        "message": "🧪 Test connection from Job Extractor",
        "level": "INFO",
        "source": {
            "service": "job-extractor",
            "module": "test",
            "function": "test_connection"
        }
    }
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    try:
        response = requests.post(
            endpoint,
            json=test_log,
            headers=headers,
            timeout=10,
            verify=False
        )
        
        if response.status_code == 200:
            print("✅ Logtail connection successful!")
            print("📊 Check your logs at: https://logtail.com")
            return True
        else:
            print(f"❌ Logtail connection failed: {response.status_code}")
            print(f"Response: {response.text}")
            return False
            
    except Exception as e:
        print(f"❌ Logtail connection error: {e}")
        return False

if __name__ == "__main__":
    # Test the connection
    test_logtail_connection()