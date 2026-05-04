#!/usr/bin/env python3
import sys
import os
import logging
import subprocess

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def main():
    try:
        from database import DatabaseManager
    except ImportError:
        logger.error("Could not import DatabaseManager. Ensure you are running from the project root.")
        sys.exit(1)

    try:
        db = DatabaseManager()
        latest_runs = db.get_latest_run_stats(limit=1)
        
        if latest_runs:
            latest_run = latest_runs[0]
            status = latest_run.get("status")
            
            if status == "ongoing":
                logger.info("Job extraction is currently ongoing. Exiting gracefully.")
                # Ensure we close connection before exiting
                db.close()
                sys.exit(0)
            else:
                logger.info(f"Latest run status is '{status}'. Proceeding to run main.py...")
        else:
            logger.info("No previous runs found. Proceeding to run main.py...")
            
        db.close()
            
    except Exception as e:
        logger.error(f"Error checking database status: {e}")
        logger.info("Proceeding to run main.py as fallback.")
        
    # Execute main.py
    script_dir = os.path.dirname(os.path.abspath(__file__))
    main_script_path = os.path.join(script_dir, "main.py")
    
    logger.info(f"Executing {main_script_path}...")
    try:
        # Run main.py using the same python executable
        subprocess.run([sys.executable, main_script_path], check=True)
    except subprocess.CalledProcessError as e:
        logger.error(f"Error executing main.py: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
