"""
Muse Company Sync (standalone, prerequisite for Muse extraction)

Fetches all companies from The Muse API and upserts them into UsersDB.employers
(keyed by muse_company_id). The Muse pipeline in main.py reads this collection
during ID maintenance, so this script must be run at least once — and periodically
thereafter — before/independently of the cron extraction run.

This is intentionally NOT part of the per-run cron (the company list changes
rarely and the full crawl is ~49 pages). Run manually or on a slower schedule:

    python muse_company_sync.py            # full sync
    MUSE_TEST_COMPANY_LIMIT=2 python muse_company_sync.py   # first 2 pages only

It writes to whatever cluster PROD_MONGODB_URI points at (via DatabaseManager),
so it shares the same database as the extractor.
"""
import logging
import time
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from bson import ObjectId

import requests

import config
from config import setup_logging
from database import DatabaseManager

logger = logging.getLogger(__name__)


def _get_muse_api_params() -> Dict[str, Any]:
    """API params including the optional API key for higher rate limits."""
    params: Dict[str, Any] = {}
    if config.MUSE_API_KEY:
        params['api_key'] = config.MUSE_API_KEY
    return params


def parse_location(location_name: str) -> Dict[str, Optional[str]]:
    """Parse a location string like 'Culver City, CA' into components."""
    if not location_name:
        return {"address": None, "city": None, "state": None, "country": None}

    parts = [p.strip() for p in location_name.split(',')]

    result = {
        "address": location_name,  # Store full string in address
        "city": None,
        "state": None,
        "country": "United States"  # Default assumption for Muse
    }

    if len(parts) >= 1:
        result["city"] = parts[0]
    if len(parts) >= 2:
        result["state"] = parts[1]
    if len(parts) >= 3:
        result["country"] = parts[2]

    return result


def fetch_companies_page(page: int) -> Optional[Dict[str, Any]]:
    """Fetch a single page of companies from the Muse API."""
    params = _get_muse_api_params()
    params['page'] = page

    url = f"{config.MUSE_API_BASE_URL}/companies"

    try:
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching companies page {page}: {e}")
        return None


def transform_company_to_employer(company: Dict[str, Any]) -> Dict[str, Any]:
    """Transform a Muse company record to the employers collection format."""
    locations = company.get('locations', [])
    location_data = parse_location(locations[0].get('name', '') if locations else '')

    industries = company.get('industries', [])
    industry = industries[0].get('name') if industries else None

    size_data = company.get('size', {})
    company_size = size_data.get('name') if size_data else None

    refs = company.get('refs', {})

    employer = {
        # Standard fields matching existing employer structure
        "username": None,
        "email": None,
        "auth0_id": "scraped",
        "is_completed": False,
        "website": refs.get('landing_page'),
        "logo_url": refs.get('logo_image'),
        "banner_url": None,
        "video_url": None,
        "portfolio": None,
        "market_cap": None,
        "full_name": company.get('name'),
        "phone_number": None,
        "category": None,
        "about": company.get('description'),
        "company_size": company_size,
        "social_media": [],
        "address": location_data.get('address'),
        "country": location_data.get('country'),
        "state": location_data.get('state'),
        "city": location_data.get('city'),
        "open_positions": [],
        "saved_candidates": [],
        "industry": industry,
        "kudos_id": [],
        "kudos_count": None,

        # Muse-specific fields
        "muse_company_id": company.get('id'),
        "muse_short_name": company.get('short_name'),

        # Metadata
        "source": "muse",
        "inserted_date": datetime.now(timezone.utc),
        "updated_date": datetime.now(timezone.utc)
    }

    return employer


def sync_companies(max_pages: Optional[int] = None):
    """
    Sync all companies from the Muse API into UsersDB.employers.

    Args:
        max_pages: Optional limit on pages to fetch (for testing).
    """
    logger.info("Starting Muse company sync...")

    db_manager = DatabaseManager()
    employers_collection = db_manager.employers_collection

    try:
        # Fetch page 0 to learn total page/company counts
        first_page = fetch_companies_page(0)
        if not first_page:
            logger.error("Failed to fetch first page. Aborting.")
            return

        total_pages = first_page.get('page_count', 1)
        total_companies = first_page.get('total', 0)

        if max_pages:
            total_pages = min(total_pages, max_pages)

        logger.info(f"Total companies: {total_companies}, Total pages: {total_pages}")

        inserted_count = 0
        updated_count = 0
        skipped_count = 0

        for page in range(total_pages):
            if page == 0:
                data = first_page
            else:
                data = fetch_companies_page(page)
                if not data:
                    logger.warning(f"Skipping page {page} due to fetch error")
                    continue

            results = data.get('results', [])
            logger.info(f"Processing page {page + 1}/{total_pages} ({len(results)} companies)")

            for company in results:
                muse_id = company.get('id')
                if not muse_id:
                    skipped_count += 1
                    continue

                employer_data = transform_company_to_employer(company)

                result = employers_collection.update_one(
                    {"muse_company_id": muse_id},
                    {
                        "$set": employer_data,
                        "$setOnInsert": {"_id": ObjectId()}
                    },
                    upsert=True
                )

                if result.upserted_id:
                    inserted_count += 1
                elif result.modified_count > 0:
                    updated_count += 1
                else:
                    skipped_count += 1

            # Rate limiting: be nice to the API
            if page < total_pages - 1:
                time.sleep(0.5)

        logger.info(
            f"Sync complete! Inserted: {inserted_count}, "
            f"Updated: {updated_count}, Skipped: {skipped_count}"
        )

    finally:
        db_manager.close()


if __name__ == "__main__":
    setup_logging()
    # MUSE_TEST_COMPANY_LIMIT doubles as a page limit for a quick test sync.
    sync_companies(max_pages=config.MUSE_TEST_COMPANY_LIMIT)
