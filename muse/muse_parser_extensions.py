"""
Muse Parser Extensions

Additional extraction methods for Muse job processing.
These methods extend the base JobPostingParser with rich field extraction
from HTML job description content.

Functions:
    - extract_section_items: Core helper for HTML section parsing
    - extract_responsibilities: Extract job responsibilities
    - extract_required_skills: Extract required qualifications/skills
    - extract_job_benefits: Extract benefits/perks
    - extract_salary_range: Extract salary min/max from content
"""

import re
from typing import List, Tuple, Optional


class MuseParserExtensions:
    """Extension methods for extracting structured data from job postings"""

    @staticmethod
    def _strip_html_inline(text: str) -> str:
        """Minimal inline HTML stripping for list item content only"""
        if not text:
            return ""
        text = re.sub(r'<[^>]+>', '', text)
        text = text.replace("&nbsp;", " ").replace("&amp;", "&")
        text = text.replace("&lt;", "<").replace("&gt;", ">")
        text = text.replace("&quot;", '"').replace("&#39;", "'")
        return re.sub(r'\s+', ' ', text).strip()

    @staticmethod
    def extract_section_items(html_content: str, section_patterns: List[str], stop_patterns: List[str] = None) -> List[str]:
        """
        Extract list items from a section of HTML content.
        Looks for section headers matching patterns, then extracts <li> items until a stop pattern.
        """
        if not html_content:
            return []

        items = []
        content_lower = html_content.lower()

        for pattern in section_patterns:
            # Find section header
            match = re.search(pattern, content_lower, re.IGNORECASE)
            if not match:
                continue

            # Get content after the header
            start_pos = match.end()
            section_content = html_content[start_pos:]

            # Find end of section (next major header or stop pattern)
            end_patterns = stop_patterns or [
                r'<h[1-3]',
                r'<strong>\s*(about|what we offer|benefits|requirements|qualifications|responsibilities)',
            ]

            end_pos = len(section_content)
            for end_pattern in end_patterns:
                end_match = re.search(end_pattern, section_content, re.IGNORECASE)
                if end_match:
                    end_pos = min(end_pos, end_match.start())

            section_content = section_content[:end_pos]

            # Extract list items
            li_matches = re.findall(r'<li[^>]*>(.*?)</li>', section_content, re.IGNORECASE | re.DOTALL)
            for li in li_matches:
                clean_item = MuseParserExtensions._strip_html_inline(li)
                if clean_item and len(clean_item) > 5:  # Filter out very short items
                    items.append(clean_item)

            if items:
                break

        return items[:20]  # Limit to 20 items

    @staticmethod
    def extract_responsibilities(html_content: str) -> List[str]:
        """Extract responsibilities/duties from HTML content"""
        patterns = [
            r'<strong>\s*responsibilities\s*:?\s*</strong>',
            r'<h[1-3][^>]*>\s*responsibilities\s*</h[1-3]>',
            r'<strong>\s*what you\'?ll do\s*:?\s*</strong>',
            r'<h[1-3][^>]*>\s*what you\'?ll do\s*</h[1-3]>',
            r'<strong>\s*(key )?(duties|tasks)\s*:?\s*</strong>',
            r'<strong>\s*in this role\s*,?\s*you will\s*:?\s*</strong>',
            r'responsibilities\s*:',
            r'what you\'?ll do\s*:',
        ]

        stop_patterns = [
            r'<h[1-3]',
            r'<strong>\s*(qualifications|requirements|skills|benefits|about|who you are)',
        ]

        return MuseParserExtensions.extract_section_items(html_content, patterns, stop_patterns)

    @staticmethod
    def extract_required_skills(html_content: str) -> List[str]:
        """Extract required skills/qualifications from HTML content"""
        patterns = [
            r'<strong>\s*qualifications?\s*:?\s*</strong>',
            r'<h[1-3][^>]*>\s*qualifications?\s*</h[1-3]>',
            r'<strong>\s*requirements?\s*:?\s*</strong>',
            r'<h[1-3][^>]*>\s*requirements?\s*</h[1-3]>',
            r'<strong>\s*skills?\s*:?\s*</strong>',
            r'<strong>\s*what we\'?re looking for\s*:?\s*</strong>',
            r'<strong>\s*who you are\s*:?\s*</strong>',
            r'<strong>\s*you have\s*:?\s*</strong>',
            r'qualifications?\s*:',
            r'requirements?\s*:',
            r'what we\'?re looking for\s*:',
        ]

        stop_patterns = [
            r'<h[1-3]',
            r'<strong>\s*(responsibilities|duties|benefits|perks|about)',
        ]

        return MuseParserExtensions.extract_section_items(html_content, patterns, stop_patterns)

    @staticmethod
    def extract_job_benefits(html_content: str) -> List[str]:
        """Extract job benefits/perks from HTML content"""
        patterns = [
            r'<strong>\s*benefits?\s*:?\s*</strong>',
            r'<h[1-3][^>]*>\s*benefits?\s*</h[1-3]>',
            r'<strong>\s*perks?\s*:?\s*</strong>',
            r'<strong>\s*what we offer\s*:?\s*</strong>',
            r'<h[1-3][^>]*>\s*what we offer\s*</h[1-3]>',
            r'<strong>\s*why (join|work)',
            r'benefits?\s*:',
            r'perks?\s*:',
            r'what we offer\s*:',
        ]

        stop_patterns = [
            r'<h[1-3]',
            r'<strong>\s*(responsibilities|qualifications|requirements|about|apply)',
        ]

        return MuseParserExtensions.extract_section_items(html_content, patterns, stop_patterns)

    @staticmethod
    def extract_salary_range(content: str) -> Tuple[Optional[float], Optional[float], str]:
        """
        Extract salary range information from content.

        Returns:
            Tuple of (salary_min, salary_max, currency)
            - salary_min: Minimum salary or None
            - salary_max: Maximum salary or None
            - currency: Currency code (default 'USD')
        """
        if not content:
            return None, None, 'USD'

        content_lower = content.lower()

        # Reasonable annual salary bounds for filtering
        MIN_ANNUAL_SALARY = 10000   # $10K minimum
        MAX_ANNUAL_SALARY = 1000000  # $1M maximum

        # Patterns for salary ranges (ordered by specificity)
        range_patterns = [
            # $80K - $120K or $80k-$120k (K suffix explicit)
            r'\$([0-9,]+)\s*(k|K)\s*[-–—to]+\s*\$?([0-9,]+)\s*(k|K)',
            # $80,000 - $120,000 (full numbers)
            r'\$([0-9,]+)\s*[-–—to]+\s*\$?([0-9,]+)(?:\s*(?:per year|annually|yearly|/year|/yr))?',
            # Salary: $80,000 - $120,000
            r'(?:salary|compensation|pay)\s*(?:range)?\s*:?\s*\$?([0-9,]+)\s*[-–—to]+\s*\$?([0-9,]+)',
            # 80,000 - 120,000 USD/year (must have yearly indicator)
            r'([0-9,]+)\s*[-–—to]+\s*([0-9,]+)\s*(?:usd|USD)\s*(?:per year|annually|yearly|/year|/yr)',
        ]

        # Single salary patterns (fallback — require yearly indicator)
        single_patterns = [
            # $80K per year
            r'\$([0-9,]+)\s*(k|K)\s*(?:per year|annually|yearly|/year|/yr)',
            # $80,000 per year
            r'\$([0-9,]+)\s*(?:per year|annually|yearly|/year|/yr)',
            # Salary: $80,000
            r'(?:salary|compensation|pay)\s*(?:range)?\s*:?\s*\$([0-9,]+)\s*(k|K)?',
        ]

        def parse_salary_value(value_str: str, has_k_suffix: bool = False) -> Optional[float]:
            """Parse salary string to float, handling K suffix only from matched text"""
            if not value_str:
                return None
            try:
                value = float(value_str.replace(',', ''))
                # Only multiply by 1000 if K suffix was explicitly in the matched text
                if has_k_suffix and value < 1000:
                    value *= 1000
                return value
            except ValueError:
                return None

        def is_reasonable_salary(value: float) -> bool:
            """Check if a value looks like a reasonable annual salary"""
            return MIN_ANNUAL_SALARY <= value <= MAX_ANNUAL_SALARY

        # Try range patterns first
        for pattern in range_patterns:
            match = re.search(pattern, content_lower)
            if match:
                groups = match.groups()
                # Determine which groups are values vs K suffixes
                values = [g for g in groups if g and g.lower() != 'k']
                k_flags = [g for g in groups if g and g.lower() == 'k']
                has_k = len(k_flags) > 0

                if len(values) >= 2:
                    salary_min = parse_salary_value(values[0], has_k)
                    salary_max = parse_salary_value(values[1], has_k)

                    if salary_min and salary_max:
                        # Ensure min <= max
                        if salary_min > salary_max:
                            salary_min, salary_max = salary_max, salary_min
                        # Sanity check: must look like annual salaries
                        if is_reasonable_salary(salary_min) or is_reasonable_salary(salary_max):
                            return salary_min, salary_max, 'USD'

        # Try single value patterns
        for pattern in single_patterns:
            match = re.search(pattern, content_lower)
            if match:
                groups = match.groups()
                value_str = groups[0]
                has_k = len(groups) > 1 and groups[1] and groups[1].lower() == 'k'
                salary = parse_salary_value(value_str, has_k)
                if salary and is_reasonable_salary(salary):
                    return salary, None, 'USD'

        return None, None, 'USD'
