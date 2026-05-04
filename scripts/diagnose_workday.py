#!/usr/bin/env python3
"""
Diagnostic script to identify Workday extraction bottlenecks
"""

import logging
import time
from config import setup_logging
from database import DatabaseManager
from logtail_handler import setup_logtail_logging

def diagnose():
    """Run diagnostics on Workday extraction"""
    setup_logging()
    setup_logtail_logging()
    
    logger = logging.getLogger(__name__)
    logger.info("="*60)
    logger.info("🔍 Starting Workday Extraction Diagnostics")
    logger.info("="*60)
    
    db = DatabaseManager()
    
    # Test 1: Count total documents
    logger.info("\n📊 Test 1: Counting total Workday companies...")
    start = time.time()
    total = db.workday_company_collection.count_documents({})
    elapsed = time.time() - start
    logger.info(f"✅ Total companies: {total} (took {elapsed:.2f}s)")
    
    # Test 2: Count companies with new_job_links
    logger.info("\n📊 Test 2: Counting companies with new jobs...")
    start = time.time()
    with_jobs = db.workday_company_collection.count_documents(
        {"new_job_links": {"$exists": True, "$ne": []}}
    )
    elapsed = time.time() - start
    logger.info(f"✅ Companies with new jobs: {with_jobs} (took {elapsed:.2f}s)")
    
    # Test 3: Fetch 10 companies
    logger.info("\n📊 Test 3: Fetching 10 companies...")
    start = time.time()
    companies = list(db.workday_company_collection.find(
        {"new_job_links": {"$exists": True, "$ne": []}},
        {"company": 1, "new_job_links": 1}
    ).limit(10))
    elapsed = time.time() - start
    logger.info(f"✅ Fetched {len(companies)} companies (took {elapsed:.2f}s)")
    
    # Test 4: Count total new jobs
    logger.info("\n📊 Test 4: Counting total new jobs to process...")
    start = time.time()
    pipeline = [
        {"$match": {"new_job_links": {"$exists": True, "$ne": []}}},
        {"$project": {"job_count": {"$size": "$new_job_links"}}},
        {"$group": {"_id": None, "total_jobs": {"$sum": "$job_count"}}}
    ]
    result = list(db.workday_company_collection.aggregate(pipeline))
    total_jobs = result[0]['total_jobs'] if result else 0
    elapsed = time.time() - start
    logger.info(f"✅ Total new jobs to process: {total_jobs} (took {elapsed:.2f}s)")
    
    # Test 5: Sample company details
    logger.info("\n📊 Test 5: Sample company details...")
    for i, company in enumerate(companies[:3], 1):
        job_count = len(company.get('new_job_links', []))
        logger.info(f"  {i}. {company.get('company')}: {job_count} new jobs")
    
    # Test 6: Fetch 100 companies
    logger.info("\n📊 Test 6: Fetching 100 companies (simulating batch)...")
    start = time.time()
    batch = db.fetch_workday_company_data(skip=0, limit=100)
    elapsed = time.time() - start
    logger.info(f"✅ Fetched {len(batch)} companies (took {elapsed:.2f}s)")
    
    logger.info("\n" + "="*60)
    logger.info("📋 SUMMARY")
    logger.info("="*60)
    logger.info(f"Total companies: {total}")
    logger.info(f"Companies with new jobs: {with_jobs}")
    logger.info(f"Total new jobs: {total_jobs}")
    logger.info(f"Average jobs per company: {total_jobs/with_jobs if with_jobs > 0 else 0:.1f}")
    logger.info(f"Estimated processing time: ~{(with_jobs * 2 / 60):.1f} minutes (at 2s per job)")
    logger.info("="*60)
    
    db.close()

if __name__ == "__main__":
    diagnose()
