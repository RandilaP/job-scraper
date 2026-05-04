"""
Job posting parser that extracts data from HTML content
"""

import re
import time
import logging
import spacy
import json
import os
from typing import List, Dict, Optional, Tuple
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError
from models import JobData, LocationResult, JobMongo, JobDescriptionTokensMongo
from datetime import datetime
from industry_classifier import classify_job_industry
from threading import RLock

class JobPostingParser:
    """
    Manual job posting parser that extracts data from HTML content
    Uses pattern matching and heuristics instead of LLM calls
    """
    
    def __init__(self):
        # Initialize geocoder once
        self.geolocator = Nominatim(user_agent="jobhelpers-geocoder")
        self.last_geocode_time = 0
        self.geocode_delay = 1.1  # Rate limit: max 1 request per second
        
        # Persistent location cache to avoid repeated API calls
        self._location_cache = {}
        self._cache_file = "geocoding_cache.json"
        self._cache_lock = RLock()
        self._load_geocoding_cache()
        logging.info(f"🎯 Loaded {len(self._location_cache)} cached locations")
        
        # Initialize spaCy
        try:
            self.nlp = spacy.load("en_core_web_sm")
        except OSError:
            logging.error("spaCy English model not found. Please install it with: python -m spacy download en_core_web_sm")
            raise
        
        # Patterns for different data extraction
        self.workplace_patterns = {
            'Remote': [
                # Title-specific remote patterns (higher priority)
                r'(?i)\b(remote|wfh|work from home|telecommute|distributed|virtual)\b',
                r'(?i)(100% remote|fully remote|completely remote|remote position)',
                r'(?i)(work remotely|remote team|remote first|work from anywhere)',
                r'(?i)(home office|remote opportunity|remote job|remote work)',
                r'(?i)(anywhere|location independent|no office required)',
                r'(?i)(remote.{0,20}position|position.{0,20}remote)',
                r'(?i)(digital nomad|location flexible)',
            ],
            'Hybrid': [
                r'(?i)\b(hybrid)\b',
                r'(?i)(hybrid work|hybrid model|hybrid arrangement|hybrid position)',
                r'(?i)(office and remote|some days office|part office)',
                r'(?i)(blend of|combination of|part remote|partially remote)',
                r'(?i)(work from home.*office|office.*work from home)',
                r'(?i)(\d+\s*days?\s*(in\s*)?office.*remote|\d+\s*days?\s*remote.*office)',
                r'(?i)(flexible.*remote.*office|flexible.*office.*remote)',
                r'(?i)(split.*office.*home|split.*home.*office)',
                r'(?i)(some remote|occasional remote|flexible location)',
            ],
            'Office': [
                r'(?i)\b(on-site|onsite|in-person|on site)\b',
                r'(?i)(headquarters|building|facility|campus)',
                r'(?i)(come into|report to|work at our|at our office)',
                r'(?i)(in office|office based|office environment)',
                r'(?i)(office space|downtown office|our office)(?!.*remote)',
                r'(?i)(local.*position|local.*job|must be local)',
                r'(?i)(relocation.*required|must relocate)',
            ]
        }
        
        self.job_type_patterns = {
            'Contract': [
                # Contract has higher priority to catch specific contract terms
                r'(?i)\b(contract|contractor|freelance|consulting|freelancer)\b',
                r'(?i)(temporary|temp|contract to hire|c2h|contract-to-hire)',
                r'(?i)(1099|independent contractor|corp to corp|c2c)',
                r'(?i)(project based|short term|contract position|contract work)',
                r'(?i)(consultant|consulting|consultancy)',
                r'(?i)(gig|project|assignment|engagement)',
                r'(?i)(fixed term|term contract|temporary assignment)',
            ],
            'Internship': [
                # Internship second priority as it's very specific
                r'(?i)\b(intern|internship|student|co-op|coop|trainee)\b',
                r'(?i)(graduate program|entry level.*intern|intern.*entry)',
                r'(?i)(summer intern|winter intern|spring intern|fall intern)',
                r'(?i)(student position|academic.*position|university.*program)',
                r'(?i)(apprentice|apprenticeship|rotation|rotational)',
                r'(?i)(new grad.*program|graduate.*trainee)',
            ],
            'Parttime': [
                r'(?i)\b(part.time|part time|part-time|parttime|pt)\b',
                r'(?i)(flexible hours|reduced hours|hourly)',
                r'(?i)(\d{1,2}\s*hours|15 hours|20 hours|25 hours|30 hours)',
                r'(?i)(part time position|flexible schedule|part-time work)',
                r'(?i)(less than.*hours|under.*hours|up to.*hours)',
                r'(?i)(evening|weekend|nights|casual)',
            ],
            'Fulltime': [
                r'(?i)\b(full.time|full time|full-time|fulltime|permanent|ft)\b',
                r'(?i)(40 hours|full time position|permanent position)',
                r'(?i)(employee|regular|staff|salaried)',
                r'(?i)(direct hire|perm|benefits eligible|with benefits)',
                r'(?i)(permanent.*role|permanent.*position|full.*benefits)',
                r'(?i)(standard.*hours|regular.*hours|traditional.*schedule)',
            ]
        }
        
        self.experience_patterns = {
            'Executive': [
                # C-level and executive titles (highest priority)
                r'(?i)\b(ceo|cto|cfo|coo|cmo|cpo|cso|chief)\b',
                r'(?i)\b(vp|vice president|president|evp|svp)\b',
                r'(?i)(executive|c-level|c level|c.level)',
                r'(?i)(15\+|20\+|25\+|\b15\+\s*years|\b20\+\s*years|\b25\+\s*years)',
                r'(?i)(founder|co-founder|owner|partner|board)',
                r'(?i)(chairman|chairwoman|chair)',
            ],
            'Director': [
                r'(?i)\b(director|head of|department head|division head)\b',
                r'(?i)(10\+|12\+|15\+|\b10\+\s*years|\b12\+\s*years|\b15\+\s*years)',
                r'(?i)(managing director|executive director|regional director)',
                r'(?i)(senior leadership|leadership team)',
                r'(?i)(global.*director|international.*director)',
            ],
            'Manager': [
                r'(?i)\b(manager|management|supervisor|team lead|leader|lead)\b',
                r'(?i)(3\+|4\+|5\+|\b[3-6]\+\s*years)',
                r'(?i)(project manager|product manager|program manager)',
                r'(?i)(supervisory|managerial|leadership)',
                r'(?i)(group.*manager|area.*manager|operations.*manager)',
                r'(?i)(team.*lead|tech.*lead|technical.*lead)',
            ],
            'Senior': [
                r'(?i)\b(senior|sr\.|principal|staff|lead)\b',
                r'(?i)(5\+|6\+|7\+|8\+|9\+|\b[5-9]\+\s*years)',
                r'(?i)(senior level|advanced|expert)',
                r'(?i)(architect|specialist|consultant)',
                r'(?i)(principal.*engineer|senior.*engineer|staff.*engineer)',
                r'(?i)(technical.*specialist|subject.*matter.*expert)',
            ],
            'Associate': [
                r'(?i)\b(associate|junior|entry|entry level|jr\.|grad)\b',
                r'(?i)(0-2|1-3|0-3|0-1|1-2|recent graduate|new grad)',
                r'(?i)(trainee|assistant|analyst|coordinator)',
                r'(?i)(beginner|starting|early career|no experience)',
                r'(?i)(college.*hire|university.*hire|campus.*hire)',
                r'(?i)(level.*1|grade.*1|band.*1)',
            ]
        }
        
        self.salary_patterns = [
            r'\$([0-9,]+)(?:\s*-\s*\$?([0-9,]+))?(?:\s*(k|K|thousand|million))?(?:\s*(per year|annually|yearly|/year))?',
            r'([0-9,]+)(?:\s*-\s*([0-9,]+))?\s*(?:k|K|thousand)\s*(?:per year|annually|yearly|/year)?',
            r'salary:?\s*\$?([0-9,]+)',
        ]
        
        # Legacy industry mapping (kept for backward compatibility)
        # The new IndustryClassifier handles this more comprehensively
        
        # US State abbreviations mapping
        self.us_states = {
            'AL': 'Alabama', 'AK': 'Alaska', 'AZ': 'Arizona', 'AR': 'Arkansas', 'CA': 'California',
            'CO': 'Colorado', 'CT': 'Connecticut', 'DE': 'Delaware', 'FL': 'Florida', 'GA': 'Georgia',
            'HI': 'Hawaii', 'ID': 'Idaho', 'IL': 'Illinois', 'IN': 'Indiana', 'IA': 'Iowa',
            'KS': 'Kansas', 'KY': 'Kentucky', 'LA': 'Louisiana', 'ME': 'Maine', 'MD': 'Maryland',
            'MA': 'Massachusetts', 'MI': 'Michigan', 'MN': 'Minnesota', 'MS': 'Mississippi', 'MO': 'Missouri',
            'MT': 'Montana', 'NE': 'Nebraska', 'NV': 'Nevada', 'NH': 'New Hampshire', 'NJ': 'New Jersey',
            'NM': 'New Mexico', 'NY': 'New York', 'NC': 'North Carolina', 'ND': 'North Dakota', 'OH': 'Ohio',
            'OK': 'Oklahoma', 'OR': 'Oregon', 'PA': 'Pennsylvania', 'RI': 'Rhode Island', 'SC': 'South Carolina',
            'SD': 'South Dakota', 'TN': 'Tennessee', 'TX': 'Texas', 'UT': 'Utah', 'VT': 'Vermont',
            'VA': 'Virginia', 'WA': 'Washington', 'WV': 'West Virginia', 'WI': 'Wisconsin', 'WY': 'Wyoming',
            'DC': 'District of Columbia'
        }
    
    def clean_html_content(self, html_content: str) -> str:
        """Clean and structure HTML content"""
        if not html_content:
            return ""
        
        # Remove unwanted attributes but keep structure
        cleaned = re.sub(r'data-[^=]*="[^"]*"', '', html_content)
        cleaned = re.sub(r'style="[^"]*"', '', cleaned)
        cleaned = re.sub(r'class="[^"]*"', '', cleaned)
        
        # Clean up whitespace
        cleaned = re.sub(r'\s+', ' ', cleaned)
        cleaned = re.sub(r'>\s+<', '><', cleaned)
        
        return cleaned.strip()
    
    def extract_workplace_type(self, title: str, content: str) -> str:
        """Extract workplace type from title and content"""
        title_lower = title.lower() if title else ""
        content_lower = content.lower() if content else ""
        
        # Check title first (higher priority for remote detection)
        for workplace_type, patterns in self.workplace_patterns.items():
            for pattern in patterns:
                if re.search(pattern, title_lower):
                    return workplace_type
        
        # Then check content
        for workplace_type, patterns in self.workplace_patterns.items():
            for pattern in patterns:
                if re.search(pattern, content_lower):
                    return workplace_type
        
        # Default to Office if no remote/hybrid indicators found
        return 'Office'
    
    def extract_job_type(self, title: str, content: str) -> str:
        """Extract job type from title and content with salary-based override"""
        title_lower = title.lower() if title else ""
        content_lower = content.lower() if content else ""
        
        # First check for salary indicators - high salary usually means NOT internship
        salary_match = re.search(r'£?[\$€]?\s*(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)\s*(?:k|K|thousand|per\s+(?:year|annum)|annually)', content_lower)
        has_high_salary = False
        if salary_match:
            try:
                salary_value = float(salary_match.group(1).replace(',', ''))
                # If salary is above 20k, it's likely not an internship
                has_high_salary = salary_value > 20000 or (salary_value > 20 and ('k' in content_lower or 'K' in content_lower))
            except:
                pass
        
        # Check for explicit full-time indicators first (higher priority)
        if has_high_salary or re.search(r'(?i)(permanent|career|professional|qualified|experienced)', content_lower):
            # Skip internship check if clear full-time indicators
            for job_type in ['Fulltime', 'Contract', 'Parttime']:
                for pattern in self.job_type_patterns.get(job_type, []):
                    if re.search(pattern, title_lower) or re.search(pattern, content_lower):
                        return job_type
        
        # Check title first (for all patterns if not overridden)
        for job_type, patterns in self.job_type_patterns.items():
            for pattern in patterns:
                if re.search(pattern, title_lower):
                    # Override trainee/intern if high salary detected
                    if job_type == 'Internship' and has_high_salary:
                        continue
                    return job_type
        
        # Then check content (with priority order)
        for job_type, patterns in self.job_type_patterns.items():
            for pattern in patterns:
                if re.search(pattern, content_lower):
                    # Override trainee/intern if high salary detected
                    if job_type == 'Internship' and has_high_salary:
                        continue
                    return job_type
        
        return 'Fulltime'  # Default
    
    def extract_experience_level(self, title: str, content: str) -> str:
        """Extract experience level from title and content"""
        title_lower = title.lower() if title else ""
        content_lower = content.lower() if content else ""
        
        # Check title first (job titles often contain level indicators)
        for experience, patterns in self.experience_patterns.items():
            for pattern in patterns:
                if re.search(pattern, title_lower):
                    return experience
        
        # Then check content (with priority order)
        for experience, patterns in self.experience_patterns.items():
            for pattern in patterns:
                if re.search(pattern, content_lower):
                    return experience
        
        return 'Associate'  # Default
    
    def extract_salary(self, content: str) -> Tuple[float, str]:
        """Extract salary information"""
        content_lower = content.lower()
        
        for pattern in self.salary_patterns:
            matches = re.findall(pattern, content_lower)
            if matches:
                # Process first match
                match = matches[0]
                if isinstance(match, tuple):
                    # Handle tuple matches
                    salary_str = match[0].replace(',', '')
                    try:
                        salary = float(salary_str)
                        # Convert k/thousand to actual number
                        if len(match) > 2 and match[2].lower() in ['k', 'thousand']:
                            salary *= 1000
                        return salary, 'USD'
                    except ValueError:
                        continue
                else:
                    # Handle string matches
                    salary_str = match.replace(',', '')
                    try:
                        return float(salary_str), 'USD'
                    except ValueError:
                        continue
        
        return 0, 'USD'  # Default
    
    def extract_industry(self, title: str, content: str, company_name: str = "") -> str:
        """Extract industry using advanced classification"""
        # Use the new advanced industry classifier
        industry = classify_job_industry(title, content, company_name)
        
        # Log the classification for debugging
        logging.debug(f"Industry classified: '{title[:50]}...' -> {industry}")
        
        return industry
    
    def extract_tags(self, content: str) -> List[str]:
        """Extract relevant tags from content"""
        # Common job-related keywords
        tag_patterns = [
            r'(?i)(python|java|javascript|react|node\.js|angular|vue)',
            r'(?i)(aws|azure|gcp|cloud|docker|kubernetes)',
            r'(?i)(sql|database|mongodb|postgresql|mysql)',
            r'(?i)(api|rest|graphql|microservices)',
            r'(?i)(agile|scrum|devops|ci/cd)',
            r'(?i)(machine learning|ai|data science|analytics)',
            r'(?i)(frontend|backend|fullstack|full-stack)',
        ]
        
        tags = []
        content_lower = content.lower()
        
        for pattern in tag_patterns:
            matches = re.findall(pattern, content_lower)
            tags.extend([match.title() for match in matches])
        
        # Remove duplicates and limit
        return list(set(tags))[:10]
    
    def _load_geocoding_cache(self):
        """Load persistent geocoding cache from disk"""
        try:
            if os.path.exists(self._cache_file):
                with open(self._cache_file, 'r') as f:
                    cache_data = json.load(f)
                    # Convert stored dict back to cache format
                    for location, result in cache_data.items():
                        self._location_cache[location] = result
        except Exception as e:
            logging.warning(f"Failed to load geocoding cache: {e}")
    
    def _save_geocoding_cache(self):
        """Save geocoding cache to disk (only parsed results)"""
        try:
            with self._cache_lock:
                # Save only the parsed results, not the raw geocoder objects
                cache_data = {}
                for location, result in self._location_cache.items():
                    if isinstance(result, dict):  # Already parsed result
                        cache_data[location] = result
                
                with open(self._cache_file, 'w') as f:
                    json.dump(cache_data, f)
        except Exception as e:
            logging.warning(f"Failed to save geocoding cache: {e}")
    
    def _rate_limited_geocode(self, location_string: str):
        """Rate-limited geocoding with persistent caching"""
        # Check cache first
        if location_string in self._location_cache:
            cached = self._location_cache[location_string]
            if cached is not None:
                logging.debug(f"🎯 Geocoding cache hit: {location_string}")
            return cached
        
        # Rate limiting: ensure at least 1.1 seconds between requests
        current_time = time.time()
        time_since_last = current_time - self.last_geocode_time
        if time_since_last < self.geocode_delay:
            time.sleep(self.geocode_delay - time_since_last)
        
        try:
            result = self.geolocator.geocode(location_string, timeout=10, addressdetails=True)
            self.last_geocode_time = time.time()
            
            # Cache the result (store parsed dict instead of geopy object)
            if result and result.raw.get('address'):
                address = result.raw['address']
                parsed_result = {
                    'city': (address.get('city') or address.get('town') or 
                           address.get('village') or address.get('hamlet') or 'Unknown'),
                    'state': (address.get('state') or address.get('state_district') or 'Unknown'),
                    'country': address.get('country', 'Unknown')
                }
                self._location_cache[location_string] = parsed_result
                logging.debug(f"📦 Cached geocoding result: {location_string}")
            else:
                self._location_cache[location_string] = None
            
            # Periodically save cache (every 50 new entries)
            if len(self._location_cache) % 50 == 0:
                self._save_geocoding_cache()
            
            return result
            
        except (GeocoderTimedOut, GeocoderServiceError) as e:
            logging.warning(f"Geocoding failed for '{location_string}': {e}")
            self._location_cache[location_string] = None
            return None
        except Exception as e:
            logging.warning(f"Unexpected geocoding error for '{location_string}': {e}")
            self._location_cache[location_string] = None
            return None
    
    def parse_location(self, location_string: str) -> Dict[str, str]:
        """Parse location string using cached/manual parsing with geopy fallback"""
        if not location_string:
            return {'country': 'United States', 'state': 'Unknown', 'city': 'Unknown'}
        
        # Clean the location string
        clean_location = re.sub(r'^(Remote\s*-?\s*|Hybrid\s*-?\s*)', '', location_string.strip(), flags=re.IGNORECASE)
        
        # Check if we have a cached parsed result (dict format)
        cached_result = self._location_cache.get(clean_location)
        if isinstance(cached_result, dict) and cached_result.get('city') != 'Unknown':
            return cached_result
        
        # Try manual parsing first (faster than geocoding)
        manual_result = self._try_manual_parse(clean_location)
        if manual_result and manual_result['city'] != 'Unknown' and manual_result['state'] != 'Unknown':
            # Cache the manual parse result
            self._location_cache[clean_location] = manual_result
            return manual_result
        
        # Fall back to geopy only if manual parsing failed
        location = self._rate_limited_geocode(clean_location)
        
        # If we have a cached dict result (from geocoding), use it
        if isinstance(location, dict):
            return location
        
        if location and location.raw.get('address'):
            address = location.raw['address']
            
            # Extract components with various field options
            city = (address.get('city') or address.get('town') or 
                   address.get('village') or address.get('hamlet') or 'Unknown')
            
            state = (address.get('state') or address.get('state_district') or 'Unknown')
            country = address.get('country', 'Unknown')
            
            # If we have valid city, state, country, use geopy result
            if city != 'Unknown' and state != 'Unknown' and country != 'Unknown':
                return {
                    'city': city,
                    'state': state,
                    'country': country
                }
        
        # Final fallback to manual parsing
        manual_result = self._try_manual_parse(clean_location, allow_unknown=True)
        return manual_result
    
    def _try_manual_parse(self, clean_location: str, allow_unknown: bool = False) -> Optional[Dict[str, str]]:
        """Try to parse location manually using common patterns"""
        # Handle common patterns manually (faster than geocoding)
        location_patterns = [
            r'([^,]+),\s*([A-Z]{2})\s*$',  # City, ST (abbreviation)
            r'([^,]+),\s*([^,]+),\s*([^,]+)',  # City, State, Country
            r'([^,]+),\s*([^,]+)',  # City, State or State, Country
        ]
        
        for pattern in location_patterns:
            match = re.match(pattern, clean_location)
            if match:
                parts = [part.strip() for part in match.groups()]
                
                if len(parts) == 2 and len(parts[1]) == 2 and parts[1].upper() in self.us_states:
                    # Handle state abbreviation
                    return {
                        'city': parts[0],
                        'state': self.us_states[parts[1].upper()],
                        'country': 'United States'
                    }
                elif len(parts) == 3:
                    return {
                        'city': parts[0],
                        'state': parts[1],
                        'country': parts[2]
                    }
                elif len(parts) == 2:
                    # Assume it's City, State (US)
                    return {
                        'city': parts[0],
                        'state': parts[1],
                        'country': 'United States'
                    }
        
        # If no pattern matches and we allow unknown, treat whole string as city
        if allow_unknown:
            return {
                'city': clean_location,
                'state': 'Unknown',
                'country': 'United States'
            }
        
        return None
    
    def get_important_tokens(self, text: str) -> List[str]:
        """Extract important tokens from text using spaCy"""
        cleaned_text = (
            text.replace("\n", " ")
            .replace("\t", " ")
            .replace("\r", " ")
            .replace("/", "")
            .replace("•", "")
        )
        doc = self.nlp(cleaned_text)
        output_list = set(
            token.lemma_
            for token in doc
            if (not token.is_punct)
            and (not token.is_stop)
            and (not token.is_digit)
            and (not token.like_num)
            and (not token.text.isspace())
            and (
                not re.search(r"[^\w\s]", token.text)
            )
            and (not re.search(r"\d", token.text))
        )
        verified_keyword = set()

        for each_keyword in output_list:
            if each_keyword.isalpha() and len(each_keyword) >= 3:
                verified_keyword.add(each_keyword)

        return list(verified_keyword)
    
    def create_job_description(self, data: JobMongo) -> str:
        """Create a formatted job description string"""
        job_description = f"Job Title: {data.title}\n"
        job_description += f"\nCompany: {data.company}"
        job_description += f"\nLocation: {data.address or ''}, {data.city or ''}, {data.state or ''}, {data.country or ''}"
        job_description += f"\n\nDescription: {data.description or 'N/A'}"
        job_description += "\n\nResponsibilities:\n"
        if data.responsibilities:
            for resp in data.responsibilities:
                job_description += f"- {resp}\n"
        else:
            job_description += "N/A\n"
        job_description += f"\nOverview: {data.overview or 'N/A'}"
        if data.category is not None:
            job_description += f"\n\nCategory: {', '.join(data.category)}"
        if data.tags is not None:
            job_description += f"\nTags: {', '.join(data.tags)}"
        if data.required_skills is not None:
            job_description += f"\nRequired Skills: {', '.join(data.required_skills)}"
        job_description += f"\nJob Type: {data.job_type or 'N/A'}"
        job_description += f"\nWorkplace Type: {data.workplace_type or 'N/A'}"
        job_description += f"\nExperience: {data.experience or 'N/A'}"
        job_description += f"\nIndustry: {data.industry or 'N/A'}"
        return job_description
    
    def process_job_data(self, title: str, content: str, location: str, company_name: str = "") -> Tuple[Optional[JobData], Optional[LocationResult]]:
        """Process job data and return structured information"""
        try:
            # Clean the content
            cleaned_content = self.clean_html_content(content)
            
            # Extract all data using both title and content
            workplace_type = self.extract_workplace_type(title, content)
            job_type = self.extract_job_type(title, content)
            experience = self.extract_experience_level(title, content)
            salary, salary_currency = self.extract_salary(content)
            industry = self.extract_industry(title, content, company_name)
            tags = self.extract_tags(content)
            location_data = self.parse_location(location)
            
            job_data = JobData(
                description=cleaned_content,
                industry=industry,
                tags=tags,
                workplace_type=workplace_type,
                job_type=job_type,
                experience=experience,
                salary_currency=salary_currency,
                salary=salary
            )
            
            location_result = LocationResult(
                country=location_data['country'],
                state=location_data['state'],
                city=location_data['city']
            )
            
            return job_data, location_result
            
        except Exception as e:
            logging.error(f"Error processing job data: {e}")
            return None, None
    
    def process_document(self, job_id: str, document: JobMongo) -> JobDescriptionTokensMongo:
        """Process a document and extract tokens"""
        job_description = self.create_job_description(document)
        tokens = self.get_important_tokens(job_description)
        return JobDescriptionTokensMongo(
            job_id=job_id, 
            tokens=tokens,
            inserted_date=document.inserted_date
        )