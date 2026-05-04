#!/usr/bin/env python3
"""
View Run Statistics - Display recent job extraction run stats from MongoDB
"""

import sys
from datetime import datetime
from database import DatabaseManager
from bson import ObjectId


def format_duration(seconds):
    """Format duration in seconds to human readable format"""
    if seconds is None:
        return "N/A"
    
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    
    if hours > 0:
        return f"{hours}h {minutes}m {secs}s"
    elif minutes > 0:
        return f"{minutes}m {secs}s"
    else:
        return f"{secs}s"


def format_time(dt):
    """Format datetime object"""
    if dt is None:
        return "N/A"
    if isinstance(dt, str):
        return dt
    return dt.strftime("%Y-%m-%d %H:%M:%S UTC")


def display_stats(limit=10):
    """Display recent run statistics"""
    db_manager = DatabaseManager()
    
    print("=" * 100)
    print("📊 JOB EXTRACTION RUN STATISTICS")
    print("=" * 100)
    print()
    
    stats_list = db_manager.get_latest_run_stats(limit=limit)
    
    if not stats_list:
        print("No run statistics found.")
        db_manager.close()
        return
    
    for idx, stat in enumerate(stats_list, 1):
        print(f"\n{'─' * 100}")
        print(f"Run #{idx} - ID: {stat['_id']}")
        print(f"{'─' * 100}")
        
        # Basic info
        print(f"\n📌 BASIC INFO:")
        print(f"  Status:       {stat.get('status', 'N/A').upper()}")
        print(f"  Source:       {stat.get('job_source', 'N/A')}")
        print(f"  Environment:  {stat.get('environment', 'N/A')}")
        print(f"  Hostname:     {stat.get('hostname', 'N/A')}")
        
        # Timing
        print(f"\n⏱️  TIMING:")
        print(f"  Started:      {format_time(stat.get('start_time'))}")
        print(f"  Ended:        {format_time(stat.get('end_time'))}")
        print(f"  Duration:     {format_duration(stat.get('duration_seconds'))}")
        
        # Greenhouse stats
        gh_total = (stat.get('greenhouse_jobs_inserted', 0) + 
                   stat.get('greenhouse_jobs_existed', 0) + 
                   stat.get('greenhouse_jobs_failed', 0))
        if gh_total > 0:
            print(f"\n🏢 GREENHOUSE JOBS:")
            print(f"  Inserted:     {stat.get('greenhouse_jobs_inserted', 0)}")
            print(f"  Existed:      {stat.get('greenhouse_jobs_existed', 0)}")
            print(f"  Failed:       {stat.get('greenhouse_jobs_failed', 0)}")
            print(f"  Total:        {gh_total}")
        
        # Workday stats
        wd_total = (stat.get('workday_jobs_inserted', 0) + 
                   stat.get('workday_jobs_existed', 0) + 
                   stat.get('workday_jobs_failed', 0))
        if wd_total > 0:
            print(f"\n💼 WORKDAY JOBS:")
            print(f"  Inserted:     {stat.get('workday_jobs_inserted', 0)}")
            print(f"  Existed:      {stat.get('workday_jobs_existed', 0)}")
            print(f"  Failed:       {stat.get('workday_jobs_failed', 0)}")
            print(f"  Total:        {wd_total}")
        
        # Processing
        print(f"\n🔄 PROCESSING:")
        print(f"  Companies:    {stat.get('companies_processed', 0)}")
        
        # OpenSearch
        print(f"\n🔍 OPENSEARCH:")
        print(f"  Synced:       {'Yes' if stat.get('opensearch_synced') else 'No'}")
        print(f"  Indexed:      {stat.get('opensearch_indexed', 0)}")
        print(f"  Deleted:      {stat.get('opensearch_deleted', 0)}")
        
        # Cache stats
        if stat.get('cache_hit_rate') is not None:
            print(f"\n🎯 CACHE PERFORMANCE:")
            print(f"  Hit Rate:     {stat.get('cache_hit_rate', 0):.2f}%")
            print(f"  Total Hits:   {stat.get('cache_total_hits', 0)}")
            print(f"  Total Misses: {stat.get('cache_total_misses', 0)}")
        
        # Errors
        errors = stat.get('errors', [])
        error_count = stat.get('error_count', 0)
        if error_count > 0:
            print(f"\n❌ ERRORS ({error_count}):")
            for err in errors[:5]:  # Show first 5 errors
                print(f"  [{err.get('type', 'Unknown')}] {err.get('message', 'N/A')}")
                if err.get('timestamp'):
                    print(f"    Time: {format_time(err.get('timestamp'))}")
            
            if len(errors) > 5:
                print(f"  ... and {len(errors) - 5} more errors")
        
        if stat.get('failed_reason'):
            print(f"\n💥 FAILURE REASON:")
            print(f"  {stat.get('failed_reason')}")
    
    print("\n" + "=" * 100)
    print(f"Showing {len(stats_list)} most recent runs")
    print("=" * 100)
    
    db_manager.close()


def display_single_stat(stat_id):
    """Display details of a single run by ID"""
    db_manager = DatabaseManager()
    
    try:
        stat = db_manager.get_run_stat_by_id(stat_id)
        
        if not stat:
            print(f"❌ No run statistics found with ID: {stat_id}")
            db_manager.close()
            return
        
        display_stats_detail(stat)
        
    except Exception as e:
        print(f"❌ Error retrieving stats: {e}")
    
    db_manager.close()


def display_stats_detail(stat):
    """Display detailed stats for a single run"""
    print("\n" + "=" * 100)
    print(f"📊 DETAILED RUN STATISTICS - ID: {stat['_id']}")
    print("=" * 100)
    
    # All fields
    for key, value in stat.items():
        if key == '_id':
            continue
        
        if key == 'errors' and value:
            print(f"\n{key}:")
            for idx, err in enumerate(value, 1):
                print(f"  Error #{idx}:")
                for err_key, err_val in err.items():
                    if err_key == 'traceback':
                        print(f"    {err_key}: [truncated]")
                    else:
                        print(f"    {err_key}: {err_val}")
        else:
            print(f"{key}: {value}")
    
    print("=" * 100)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="View job extraction run statistics")
    parser.add_argument('-n', '--number', type=int, default=10, help='Number of recent runs to show (default: 10)')
    parser.add_argument('-i', '--id', type=str, help='Show details for a specific run ID')
    
    args = parser.parse_args()
    
    if args.id:
        display_single_stat(args.id)
    else:
        display_stats(limit=args.number)
