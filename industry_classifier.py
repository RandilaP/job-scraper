"""
Improved Industry Classification System
Uses multiple techniques to accurately map job content to industries
"""

import re
import logging
import hashlib
from typing import Dict, List, Set, Optional, Tuple
from collections import defaultdict
from cache_utils import TTLCache, CacheManager

class IndustryClassifier:
    """Advanced industry classification using multiple detection methods"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        
        # Classification result cache: 30 minute TTL, max 3000 entries
        self.classification_cache = TTLCache(ttl=1800, maxsize=3000)
        CacheManager.register_cache('industry_classification', self.classification_cache)
        logging.info("🎯 Industry classification caching enabled (TTL=1800s, maxsize=3000)")
        
        # Complete industry list from your data
        self.industries = [
            "Accounting & Finance",
            "Aerospace & Aviation", 
            "Agriculture & Farming",
            "Architecture & Planning",
            "Arts & Entertainment",
            "Automotive",
            "Banking & Financial Services",
            "Biotechnology & Pharmaceuticals",
            "Broadcasting & Media",
            "Business Services & Consulting",
            "Construction & Real Estate",
            "Consumer Goods & Services",
            "Design & Creative Services",
            "Education & Training",
            "Energy & Utilities",
            "Engineering & Manufacturing",
            "Environmental Services",
            "Government & Public Administration",
            "Healthcare & Medical",
            "Hospitality & Tourism",
            "Human Resources",
            "Information Technology & Services",
            "Legal Services",
            "Logistics & Supply Chain",
            "Marketing & Advertising",
            "Non-Profit & Social Services",
            "Retail & Wholesale",
            "Safety & Security",
            "Telecommunications",
            "Transportation",
            "Warehousing"
        ]
        
        # Build comprehensive keyword mappings
        self.industry_keywords = self._build_keyword_mappings()
        
        # Company name patterns (common companies in each industry)
        self.company_patterns = self._build_company_patterns()
        
        # Job title patterns  
        self.job_title_patterns = self._build_job_title_patterns()
        
        # Skills and technology keywords
        self.skills_keywords = self._build_skills_mappings()
        
        self.logger.info(f"Industry classifier initialized with {len(self.industries)} industries")
    
    def _build_keyword_mappings(self) -> Dict[str, Set[str]]:
        """Build comprehensive and balanced keyword mappings for each industry"""
        return {
            "Accounting & Finance": {
                "accounting", "finance", "financial", "cpa", "bookkeeping", "audit", "auditing", 
                "tax", "taxation", "payroll", "budgeting", "controller", "cfo", "accountant",
                "financial analyst", "treasury", "fiscal", "revenue", "expense", "budget",
                "accounts payable", "accounts receivable", "financial planning", "cost accounting",
                "financial reporting", "cash flow", "variance analysis", "reconciliation", "gaap"
            },
            
            "Aerospace & Aviation": {
                "aerospace", "aviation", "aircraft", "airline", "pilot", "flight", "aviation",
                "boeing", "airbus", "airport", "maintenance", "avionics", "aerospace engineering",
                "flight attendant", "air traffic control", "runway", "hangar", "cockpit",
                "turbine", "propeller", "navigation", "radar", "satellite", "spacecraft",
                "missile", "defense contractor", "faa", "flight operations", "ground crew"
            },
            
            "Agriculture & Farming": {
                "agriculture", "farming", "farm", "agricultural", "crop", "livestock", "dairy",
                "irrigation", "harvest", "pesticide", "fertilizer", "agronomy", "veterinary",
                "ranching", "poultry", "cattle", "sheep", "pig", "chicken", "organic farming",
                "greenhouse", "tractor", "combine", "tillage", "soil", "seed", "grain",
                "farmer", "ranch", "pasture", "barn", "silo", "agricultural equipment"
            },
            
            "Architecture & Planning": {
                "architecture", "architect", "architectural", "design", "planning", "urban planning",
                "landscape", "interior design", "cad", "autocad", "construction", "building design",
                "blueprints", "drafting", "structural", "zoning", "permits", "building codes",
                "residential design", "commercial design", "site planning", "landscape architecture",
                "urban design", "city planning", "environmental planning", "revit", "3d modeling"
            },
            
            "Arts & Entertainment": {
                "arts", "entertainment", "creative", "artist", "musician", "actor", "director",
                "producer", "film", "music", "theater", "gallery", "museum", "creative director",
                "painting", "sculpture", "photography", "cinema", "broadway", "concert",
                "performance", "show business", "recording", "studio", "stage", "talent",
                "entertainment industry", "hollywood", "band", "orchestra", "dance", "opera"
            },
            
            "Automotive": {
                "automotive", "auto", "car", "vehicle", "dealership", "mechanic", "parts",
                "manufacturing", "assembly", "quality control", "automotive engineering",
                "automobile", "truck", "motorcycle", "repair", "service", "technician",
                "body shop", "paint", "collision", "transmission", "engine", "brake",
                "tire", "oil change", "diagnostic", "warranty", "recall", "automotive sales"
            },
            
            "Banking & Financial Services": {
                "bank", "banking", "financial services", "credit union", "mortgage", "loan",
                "investment", "wealth management", "portfolio", "trading", "securities",
                "teller", "branch", "atm", "checking", "savings", "certificate of deposit",
                "interest rate", "lending", "underwriting", "financial advisor", "broker",
                "insurance", "retirement", "401k", "mutual fund", "stock", "bond", "equity"
            },
            
            "Biotechnology & Pharmaceuticals": {
                "biotech", "biotechnology", "pharmaceutical", "pharma", "drug", "medicine",
                "clinical", "research", "laboratory", "fda", "regulatory", "clinical trials",
                "genetic", "molecular", "protein", "vaccine", "therapy", "treatment",
                "prescription", "over-the-counter", "manufacturing", "quality assurance",
                "biomanufacturing", "cell culture", "fermentation", "purification", "validation"
            },
            
            "Broadcasting & Media": {
                "broadcasting", "media", "television", "radio", "news", "journalist", "reporter",
                "editor", "production", "studio", "content", "digital media", "streaming",
                "anchor", "correspondent", "cameraman", "sound engineer", "video editor",
                "podcast", "social media", "youtube", "instagram", "facebook", "twitter",
                "content creator", "influencer", "public relations", "communications", "press"
            },
            
            "Business Services & Consulting": {
                "consulting", "consultant", "business services", "advisory", "strategy", 
                "management consulting", "operations", "process improvement", "transformation",
                "business analyst", "project management", "change management", "optimization",
                "efficiency", "workflow", "business process", "organizational development",
                "strategic planning", "market research", "feasibility study", "due diligence"
            },
            
            "Construction & Real Estate": {
                "construction", "real estate", "property", "contractor", "builder", "development",
                "project management", "site", "residential", "commercial", "renovation",
                "realtor", "agent", "broker", "property management", "leasing", "appraisal",
                "inspection", "mortgage", "closing", "listing", "mls", "property development",
                "building", "framing", "roofing", "plumbing", "electrical", "hvac", "concrete"
            },
            
            "Consumer Goods & Services": {
                "consumer goods", "retail", "products", "manufacturing", "brand", "marketing",
                "product management", "consumer", "merchandise", "wholesale",
                "product development", "packaging", "distribution", "supply chain",
                "quality control", "inventory management", "vendor relations", "procurement",
                "category management", "pricing", "promotion", "market analysis", "trend analysis"
            },
            
            "Design & Creative Services": {
                "design", "creative", "graphic design", "web design", "ux", "ui", "designer",
                "creative services", "branding", "advertising", "digital design",
                "logo design", "typography", "illustration", "layout", "creative director",
                "art director", "visual design", "user experience", "user interface",
                "print design", "packaging design", "motion graphics", "animation", "adobe"
            },
            
            "Education & Training": {
                "education", "school", "university", "college", "teacher", "instructor", "professor",
                "training", "curriculum", "academic", "student", "learning", "educational",
                "classroom", "lesson plan", "assessment", "tutoring", "principal", "dean",
                "admissions", "registrar", "counselor", "librarian", "online learning",
                "e-learning", "corporate training", "professional development", "certification"
            },
            
            "Energy & Utilities": {
                "energy", "utilities", "power", "electric", "gas", "oil", "renewable", "solar",
                "wind", "nuclear", "utility", "grid", "transmission", "distribution",
                "power plant", "generator", "turbine", "pipeline", "refinery", "drilling",
                "exploration", "petroleum", "natural gas", "coal", "hydroelectric",
                "energy efficiency", "smart grid", "meter reading", "line worker", "substation"
            },
            
            "Engineering & Manufacturing": {
                "engineering", "engineer", "manufacturing", "production", "industrial", "mechanical",
                "electrical", "civil", "chemical", "software engineering", "quality", "lean",
                "design engineer", "process engineer", "project engineer", "maintenance",
                "operations", "plant", "factory", "assembly line", "automation", "robotics",
                "cad", "prototype", "testing", "validation", "six sigma", "continuous improvement"
            },
            
            "Environmental Services": {
                "environmental", "sustainability", "green", "recycling", "waste management",
                "environmental consulting", "remediation", "ecology", "conservation",
                "pollution control", "air quality", "water treatment", "hazardous waste",
                "environmental compliance", "environmental impact", "renewable energy",
                "carbon footprint", "environmental assessment", "epa", "cleanup", "restoration"
            },
            
            "Government & Public Administration": {
                "government", "public", "federal", "state", "local", "municipal", "city", "county",
                "administration", "policy", "regulatory", "compliance", "public service",
                "civil service", "bureaucracy", "agency", "department", "office", "clerk",
                "administrator", "public affairs", "constituent services", "permits", "licensing",
                "public safety", "emergency management", "social services", "public health"
            },
            
            "Healthcare & Medical": {
                "healthcare", "medical", "health", "hospital", "clinic", "nurse", "doctor",
                "physician", "medical device", "pharmaceutical", "patient", "clinical",
                "surgery", "emergency", "intensive care", "radiology", "laboratory",
                "pharmacy", "physical therapy", "occupational therapy", "mental health",
                "dental", "veterinary", "nursing", "medical assistant", "healthcare administration"
            },
            
            "Hospitality & Tourism": {
                "hospitality", "tourism", "hotel", "restaurant", "travel", "resort", "hospitality",
                "food service", "guest", "customer service", "tourism", "leisure",
                "chef", "cook", "server", "bartender", "housekeeper", "concierge",
                "front desk", "catering", "event planning", "banquet", "conference",
                "vacation", "cruise", "airline", "tour guide", "recreation", "entertainment"
            },
            
            "Human Resources": {
                "human resources", "hr", "recruiting", "recruitment", "talent", "benefits",
                "compensation", "payroll", "employee", "personnel", "training", "onboarding",
                "hiring", "interviewing", "performance management", "employee relations",
                "diversity", "inclusion", "workplace", "labor relations", "employment law",
                "talent acquisition", "organizational development", "workforce planning"
            },
            
            "Information Technology & Services": {
                "information technology", "it", "software", "technology", "computer", "programming",
                "development", "database", "network", "cybersecurity", "cloud", "devops",
                "web development", "mobile development", "data analysis", "system administration",
                "technical support", "help desk", "infrastructure", "server", "coding"
            },
            
            "Legal Services": {
                "legal", "law", "attorney", "lawyer", "legal services", "litigation", "contract",
                "compliance", "regulatory", "paralegal", "law firm", "court",
                "legal assistant", "legal secretary", "judge", "counsel", "advocacy",
                "legal research", "case management", "document review", "deposition",
                "trial", "settlement", "intellectual property", "corporate law", "criminal law"
            },
            
            "Logistics & Supply Chain": {
                "logistics", "supply chain", "distribution", "warehouse", "shipping", "freight",
                "transportation", "inventory", "procurement", "sourcing", "vendor management",
                "supply planning", "demand planning", "materials management", "operations",
                "fulfillment", "delivery", "import", "export", "customs", "forwarding",
                "logistics coordinator", "supply chain analyst", "purchasing", "buyer"
            },
            
            "Marketing & Advertising": {
                "marketing", "advertising", "digital marketing", "social media", "campaign",
                "brand", "promotion", "content marketing", "seo", "sem", "analytics",
                "market research", "customer acquisition", "lead generation", "email marketing",
                "public relations", "communications", "creative", "copywriting", "media planning",
                "brand management", "product marketing", "event marketing", "trade shows"
            },
            
            "Non-Profit & Social Services": {
                "non-profit", "nonprofit", "charity", "social services", "foundation", "volunteer",
                "community", "social work", "fundraising", "grant", "advocacy",
                "social worker", "case manager", "program coordinator", "outreach",
                "community outreach", "development", "donor relations", "event planning",
                "public benefit", "mission", "cause", "humanitarian", "philanthropy"
            },
            
            "Retail & Wholesale": {
                "retail", "wholesale", "store", "sales", "merchandise", "inventory", "cashier",
                "customer service", "ecommerce", "online retail", "distribution",
                "sales associate", "store manager", "buyer", "merchandiser", "visual merchandising",
                "point of sale", "pos", "shopping", "mall", "outlet", "chain store",
                "retail management", "loss prevention", "stock", "planogram", "markdown"
            },
            
            "Safety & Security": {
                "safety", "security", "guard", "protection", "surveillance", "compliance",
                "risk management", "emergency", "fire", "police", "safety officer",
                "security guard", "loss prevention", "background check", "access control",
                "alarm", "patrol", "investigation", "incident response", "safety training",
                "occupational safety", "osha", "workplace safety", "safety inspector"
            },
            
            "Telecommunications": {
                "telecommunications", "telecom", "phone", "mobile", "wireless", "network",
                "communication", "internet", "broadband", "cellular", "tower",
                "fiber optic", "cable", "satellite", "voip", "call center", "customer service",
                "technical support", "installation", "repair", "maintenance", "signal",
                "telecommunications engineer", "network engineer", "field technician"
            },
            
            "Transportation": {
                "transportation", "transport", "logistics", "driver", "shipping", "delivery",
                "fleet", "trucking", "maritime", "rail", "transit", "logistics",
                "truck driver", "bus driver", "taxi", "uber", "lyft", "dispatch",
                "route planning", "fleet management", "freight", "cargo", "passenger",
                "public transportation", "subway", "train", "airline", "pilot", "captain"
            },
            
            "Warehousing": {
                "warehouse", "warehousing", "distribution", "fulfillment", "inventory",
                "storage", "picking", "packing", "dock", "forklift", "material handling",
                "warehouse worker", "warehouse manager", "shipping clerk", "receiving",
                "order fulfillment", "inventory control", "cycle counting", "wms",
                "warehouse management system", "loading", "unloading", "palletizing"
            }
        }
    
    def _build_company_patterns(self) -> Dict[str, Set[str]]:
        """Build patterns for common companies in each industry"""
        return {
            "Information Technology & Services": {
                "microsoft", "google", "amazon", "apple", "meta", "facebook", "netflix", "uber",
                "airbnb", "spotify", "slack", "zoom", "salesforce", "oracle", "ibm", "intel"
            },
            "Banking & Financial Services": {
                "jpmorgan", "bank of america", "wells fargo", "goldman sachs", "morgan stanley",
                "citigroup", "american express", "visa", "mastercard", "paypal"
            },
            "Healthcare & Medical": {
                "johnson & johnson", "pfizer", "merck", "abbott", "medtronic", "kaiser",
                "anthem", "humana", "unitedhealth", "cvs health"
            },
            "Retail & Wholesale": {
                "walmart", "target", "costco", "home depot", "lowes", "macys", "nordstrom",
                "best buy", "staples", "office depot"
            },
            "Automotive": {
                "ford", "general motors", "tesla", "toyota", "honda", "nissan", "bmw",
                "mercedes", "audi", "volkswagen", "chrysler", "dodge"
            },
            "Aerospace & Aviation": {
                "boeing", "lockheed martin", "northrop grumman", "raytheon", "airbus",
                "united airlines", "delta", "american airlines", "southwest"
            },
            "Energy & Utilities": {
                "exxonmobil", "chevron", "conocophillips", "duke energy", "southern company",
                "nextera energy", "exelon", "dominion", "pge", "edison"
            }
        }
    
    def _build_job_title_patterns(self) -> Dict[str, Set[str]]:
        """Build comprehensive job title patterns for all industries"""
        return {
            "Accounting & Finance": {
                "accountant", "financial analyst", "controller", "cfo", "bookkeeper", "auditor",
                "tax specialist", "financial advisor", "treasury analyst", "budget analyst",
                "accounts payable", "accounts receivable", "payroll specialist", "tax preparer"
            },
            "Aerospace & Aviation": {
                "pilot", "flight attendant", "aircraft mechanic", "aerospace engineer",
                "air traffic controller", "aviation technician", "flight instructor",
                "aircraft inspector", "ground crew", "flight dispatcher", "avionics technician"
            },
            "Agriculture & Farming": {
                "farmer", "rancher", "agricultural engineer", "farm manager", "livestock specialist",
                "crop specialist", "veterinarian", "agricultural inspector", "farm worker",
                "dairy farmer", "greenhouse manager", "irrigation specialist", "agronomist"
            },
            "Architecture & Planning": {
                "architect", "urban planner", "landscape architect", "interior designer",
                "architectural drafter", "city planner", "design coordinator", "project architect",
                "architectural technician", "building inspector", "construction manager"
            },
            "Arts & Entertainment": {
                "artist", "musician", "actor", "director", "producer", "photographer",
                "graphic designer", "creative director", "art director", "curator",
                "entertainment manager", "talent agent", "sound engineer", "video editor"
            },
            "Automotive": {
                "automotive technician", "mechanic", "auto sales", "service advisor",
                "automotive engineer", "parts specialist", "body shop technician",
                "automotive inspector", "service manager", "dealership manager", "car salesperson"
            },
            "Banking & Financial Services": {
                "bank teller", "loan officer", "financial advisor", "investment advisor",
                "branch manager", "credit analyst", "mortgage specialist", "wealth manager",
                "portfolio manager", "trading specialist", "insurance agent", "financial planner"
            },
            "Biotechnology & Pharmaceuticals": {
                "research scientist", "lab technician", "clinical research", "regulatory affairs",
                "quality assurance", "biotech engineer", "pharmaceutical sales",
                "clinical trial coordinator", "biomanufacturing", "medical writer"
            },
            "Broadcasting & Media": {
                "journalist", "reporter", "news anchor", "editor", "producer", "cameraman",
                "sound engineer", "media coordinator", "content creator", "social media manager",
                "communications specialist", "public relations", "media planner"
            },
            "Business Services & Consulting": {
                "consultant", "business analyst", "management consultant", "strategy consultant",
                "operations consultant", "project manager", "business advisor",
                "process improvement", "change management", "organizational development"
            },
            "Construction & Real Estate": {
                "construction worker", "project manager", "real estate agent", "contractor",
                "construction manager", "property manager", "real estate broker",
                "construction supervisor", "estimator", "inspector", "realtor", "appraiser"
            },
            "Consumer Goods & Services": {
                "product manager", "brand manager", "merchandiser", "buyer", "product developer",
                "category manager", "supply chain manager", "quality control",
                "packaging engineer", "consumer insights", "market research"
            },
            "Design & Creative Services": {
                "graphic designer", "web designer", "ux designer", "ui designer", "creative director",
                "art director", "visual designer", "brand designer", "motion graphics designer",
                "interior designer", "product designer", "user experience"
            },
            "Education & Training": {
                "teacher", "professor", "instructor", "principal", "dean", "counselor",
                "librarian", "tutor", "trainer", "curriculum developer", "academic advisor",
                "admissions counselor", "registrar", "educational coordinator"
            },
            "Energy & Utilities": {
                "power plant operator", "utility worker", "electrical engineer", "energy analyst",
                "line worker", "meter reader", "substation technician", "renewable energy",
                "oil rig worker", "pipeline operator", "energy consultant", "utility manager"
            },
            "Engineering & Manufacturing": {
                "mechanical engineer", "electrical engineer", "manufacturing engineer",
                "process engineer", "quality engineer", "production manager",
                "plant manager", "maintenance technician", "assembly worker", "machinist"
            },
            "Environmental Services": {
                "environmental scientist", "environmental engineer", "sustainability coordinator",
                "waste management", "environmental consultant", "recycling coordinator",
                "environmental compliance", "air quality specialist", "water treatment operator"
            },
            "Government & Public Administration": {
                "government worker", "civil servant", "public administrator", "policy analyst",
                "government clerk", "public affairs", "regulatory specialist",
                "municipal worker", "federal employee", "state employee", "city clerk"
            },
            "Healthcare & Medical": {
                "nurse", "doctor", "physician", "medical assistant", "therapist", "pharmacist",
                "medical technician", "healthcare administrator", "clinical coordinator",
                "medical receptionist", "radiologic technician", "laboratory technician"
            },
            "Hospitality & Tourism": {
                "hotel manager", "restaurant manager", "chef", "cook", "server", "bartender",
                "front desk clerk", "housekeeper", "concierge", "tour guide",
                "event coordinator", "catering manager", "travel agent", "hospitality coordinator"
            },
            "Human Resources": {
                "hr manager", "recruiter", "talent acquisition", "hr generalist", "compensation analyst",
                "benefits administrator", "training coordinator", "hr business partner",
                "employee relations", "hr specialist", "workforce planning"
            },
            "Information Technology & Services": {
                "software engineer", "developer", "programmer", "data scientist", "devops engineer",
                "system administrator", "network engineer", "cybersecurity analyst", "it manager",
                "web developer", "database administrator", "technical support", "it specialist"
            },
            "Legal Services": {
                "lawyer", "attorney", "paralegal", "legal assistant", "legal secretary",
                "counsel", "law clerk", "legal researcher", "compliance officer",
                "contract specialist", "legal advisor", "judicial assistant"
            },
            "Logistics & Supply Chain": {
                "logistics coordinator", "supply chain manager", "warehouse manager",
                "purchasing agent", "buyer", "procurement specialist", "logistics analyst",
                "supply chain analyst", "inventory manager", "distribution manager"
            },
            "Marketing & Advertising": {
                "marketing manager", "digital marketer", "social media manager", "content creator",
                "brand manager", "advertising manager", "campaign manager", "seo specialist",
                "marketing coordinator", "public relations", "communications manager"
            },
            "Non-Profit & Social Services": {
                "social worker", "case manager", "program coordinator", "fundraiser",
                "development coordinator", "outreach coordinator", "volunteer coordinator",
                "grant writer", "nonprofit manager", "community outreach"
            },
            "Retail & Wholesale": {
                "sales associate", "store manager", "cashier", "retail manager", "buyer",
                "merchandiser", "inventory specialist", "customer service representative",
                "loss prevention", "visual merchandiser", "retail coordinator"
            },
            "Safety & Security": {
                "security guard", "safety officer", "security manager", "safety inspector",
                "loss prevention", "security coordinator", "emergency manager",
                "occupational safety", "security analyst", "safety specialist"
            },
            "Telecommunications": {
                "telecommunications technician", "network engineer", "customer service representative",
                "technical support", "field technician", "installation technician",
                "telecommunications engineer", "call center representative", "network specialist"
            },
            "Transportation": {
                "truck driver", "bus driver", "delivery driver", "dispatcher", "transportation manager",
                "fleet manager", "logistics coordinator", "driver", "pilot", "captain",
                "transportation coordinator", "route planner"
            },
            "Warehousing": {
                "warehouse worker", "warehouse manager", "forklift operator", "shipping clerk",
                "receiving clerk", "inventory specialist", "warehouse supervisor",
                "order picker", "packer", "material handler", "warehouse coordinator"
            }
        }
    
    def _build_skills_mappings(self) -> Dict[str, Set[str]]:
        """Build comprehensive skill-based mappings for all industries"""
        return {
            "Accounting & Finance": {
                "quickbooks", "excel", "gaap", "financial modeling", "sap", "oracle financials",
                "tax preparation", "auditing", "budgeting", "financial analysis", "cpa"
            },
            "Aerospace & Aviation": {
                "flight operations", "avionics", "aircraft maintenance", "faa regulations",
                "flight planning", "navigation", "aircraft systems", "safety procedures"
            },
            "Agriculture & Farming": {
                "crop management", "livestock care", "irrigation systems", "farm equipment operation",
                "organic farming", "pest control", "soil management", "agricultural technology"
            },
            "Architecture & Planning": {
                "autocad", "revit", "sketchup", "architectural design", "building codes",
                "construction drawings", "3d modeling", "project management", "zoning laws"
            },
            "Arts & Entertainment": {
                "creative direction", "artistic skills", "performance", "production",
                "entertainment industry knowledge", "talent management", "event production"
            },
            "Automotive": {
                "automotive repair", "diagnostic tools", "automotive systems", "customer service",
                "parts knowledge", "automotive technology", "quality control"
            },
            "Banking & Financial Services": {
                "banking operations", "loan processing", "financial products", "customer service",
                "regulatory compliance", "investment knowledge", "risk assessment"
            },
            "Biotechnology & Pharmaceuticals": {
                "laboratory techniques", "clinical research", "regulatory compliance", "gmp",
                "biotechnology", "pharmaceutical knowledge", "data analysis", "quality assurance"
            },
            "Broadcasting & Media": {
                "journalism", "video production", "audio production", "content creation",
                "social media management", "broadcasting equipment", "editing software"
            },
            "Business Services & Consulting": {
                "business analysis", "project management", "strategic planning", "process improvement",
                "change management", "consulting skills", "client management"
            },
            "Construction & Real Estate": {
                "construction management", "project management", "real estate knowledge",
                "building codes", "construction safety", "property management", "mls"
            },
            "Consumer Goods & Services": {
                "product development", "brand management", "market research", "supply chain",
                "consumer insights", "retail operations", "merchandising"
            },
            "Design & Creative Services": {
                "photoshop", "illustrator", "indesign", "sketch", "figma", "adobe creative suite",
                "ui/ux design", "web design", "graphic design", "branding", "typography"
            },
            "Education & Training": {
                "curriculum development", "instructional design", "classroom management",
                "educational technology", "assessment", "student counseling", "academic planning"
            },
            "Energy & Utilities": {
                "power systems", "electrical safety", "utility operations", "renewable energy",
                "energy efficiency", "grid operations", "maintenance procedures"
            },
            "Engineering & Manufacturing": {
                "autocad", "solidworks", "matlab", "lean manufacturing", "six sigma", "quality control",
                "project management", "process engineering", "manufacturing processes"
            },
            "Environmental Services": {
                "environmental regulations", "sustainability practices", "waste management",
                "environmental assessment", "pollution control", "recycling processes"
            },
            "Government & Public Administration": {
                "public policy", "government regulations", "public administration",
                "compliance", "public service", "bureaucratic processes", "policy analysis"
            },
            "Healthcare & Medical": {
                "patient care", "medical procedures", "healthcare regulations", "medical terminology",
                "clinical skills", "healthcare administration", "medical equipment"
            },
            "Hospitality & Tourism": {
                "customer service", "hospitality management", "food service", "event planning",
                "travel planning", "guest relations", "hotel operations", "restaurant operations"
            },
            "Human Resources": {
                "hr management", "recruiting", "employee relations", "benefits administration",
                "payroll", "training development", "performance management", "compliance"
            },
            "Information Technology & Services": {
                "python", "java", "javascript", "react", "node.js", "aws", "azure", "docker",
                "kubernetes", "sql", "mongodb", "git", "agile", "scrum", "machine learning"
            },
            "Legal Services": {
                "legal research", "case management", "legal writing", "litigation support",
                "contract law", "regulatory compliance", "legal procedures", "court procedures"
            },
            "Logistics & Supply Chain": {
                "supply chain management", "logistics planning", "inventory management",
                "procurement", "vendor management", "distribution", "warehouse management"
            },
            "Marketing & Advertising": {
                "google analytics", "facebook ads", "google ads", "seo", "sem", "content marketing",
                "social media marketing", "email marketing", "crm", "hubspot", "salesforce"
            },
            "Non-Profit & Social Services": {
                "fundraising", "grant writing", "program management", "community outreach",
                "social work", "volunteer management", "nonprofit administration"
            },
            "Retail & Wholesale": {
                "retail operations", "customer service", "inventory management", "merchandising",
                "pos systems", "sales techniques", "loss prevention", "visual merchandising"
            },
            "Safety & Security": {
                "security procedures", "safety protocols", "emergency response", "risk assessment",
                "surveillance systems", "safety training", "incident management"
            },
            "Telecommunications": {
                "telecommunications systems", "network troubleshooting", "customer service",
                "technical support", "installation procedures", "communication systems"
            },
            "Transportation": {
                "commercial driving", "route planning", "fleet management", "logistics coordination",
                "transportation safety", "vehicle maintenance", "dispatch operations"
            },
            "Warehousing": {
                "warehouse operations", "inventory management", "forklift operation",
                "shipping procedures", "warehouse management systems", "material handling"
            }
        }
    
    def _analyze_context(self, title: str, content: str) -> Dict[str, float]:
        """Analyze contextual clues for better industry classification"""
        context_scores = defaultdict(float)
        
        # Combine title and content for analysis
        text = f"{title} {content}".lower()
        
        # Context patterns that strongly indicate specific industries
        strong_indicators = {
            "Information Technology & Services": [
                r'\b(software|programming|coding|development|api|database|cloud|devops)\b',
                r'\b(python|java|javascript|react|aws|azure|docker|kubernetes)\b'
            ],
            "Healthcare & Medical": [
                r'\b(patient|medical|clinical|healthcare|hospital|treatment|diagnosis)\b',
                r'\b(nurse|doctor|physician|therapist|medical device|pharmaceutical)\b'
            ],
            "Banking & Financial Services": [
                r'\b(banking|financial|investment|trading|portfolio|loan|credit|mortgage)\b',
                r'\b(compliance|risk management|regulatory|audit|financial analysis)\b'
            ],
            "Education & Training": [
                r'\b(student|teacher|curriculum|educational|academic|learning|training)\b',
                r'\b(university|college|school|classroom|instruction|pedagogy)\b'
            ],
            "Marketing & Advertising": [
                r'\b(marketing|advertising|campaign|branding|social media|seo|analytics)\b',
                r'\b(content|digital marketing|brand management|customer acquisition)\b'
            ]
        }
        
        for industry, patterns in strong_indicators.items():
            score = 0.0
            for pattern in patterns:
                matches = len(re.findall(pattern, text))
                if matches > 0:
                    score += min(matches * 0.2, 0.5)  # Cap per pattern
            
            if score > 0:
                context_scores[industry] = min(score, 0.8)  # Cap total context score
        
        return context_scores
    
    def classify_industry(self, title: str, content: str, company_name: str = "") -> Tuple[str, float]:
        """
        Enhanced industry classification using multiple detection methods with contextual analysis
        Returns tuple of (industry_name, confidence_score)
        """
        # Create cache key from inputs (use hash to keep key short)
        cache_input = f"{title}|{company_name}|{content[:500]}"
        cache_key = hashlib.md5(cache_input.encode()).hexdigest()
        
        # Check cache first
        cached_result = self.classification_cache.get(cache_key)
        if cached_result is not None:
            self.logger.debug(f"🎯 Cache hit for industry classification")
            return cached_result
        
        # Combine all text for analysis
        full_text = f"{title} {content} {company_name}".lower()
        
        # Score each industry using multiple methods
        industry_scores = defaultdict(float)
        
        # Method 1: Keyword matching (45% weight - increased)
        for industry, keywords in self.industry_keywords.items():
            keyword_score = self._score_keywords(full_text, keywords)
            industry_scores[industry] += keyword_score * 0.45
        
        # Method 2: Job title patterns (30% weight - increased)
        title_score = self._score_job_title_patterns(title)
        for industry, score in title_score.items():
            industry_scores[industry] += score * 0.30
        
        # Method 3: Company name matching (15% weight - decreased)
        company_score = self._score_company_patterns(company_name)
        for industry, score in company_score.items():
            industry_scores[industry] += score * 0.15
        
        # Method 4: Skills and technology keywords (10% weight)
        skills_score = self._score_skills_keywords(full_text)
        for industry, score in skills_score.items():
            industry_scores[industry] += score * 0.10
        
        # Find best match
        if not industry_scores:
            result = ("Other", 0.0)
            self.classification_cache.set(cache_key, result)
            return result
        
        # Get top candidates for disambiguation
        sorted_scores = sorted(industry_scores.items(), key=lambda x: x[1], reverse=True)
        
        if len(sorted_scores) >= 2:
            best_score = sorted_scores[0][1]
            second_score = sorted_scores[1][1]
            
            # If top two scores are very close, add disambiguation logic
            if best_score - second_score < 0.1 and best_score > 0.3:
                # Use additional heuristics for tie-breaking
                best_industry = self._disambiguate_close_matches(sorted_scores[:2], title, content, company_name)
            else:
                best_industry = sorted_scores[0][0]
        else:
            best_industry = sorted_scores[0][0]
        
        confidence = min(industry_scores[best_industry], 1.0)  # Cap at 1.0
        
        # Adjust confidence threshold based on content quality - much lower thresholds
        min_threshold = 0.08 if len(content.split()) > 10 else 0.05  # Much lower thresholds
        
        # Only return if confidence is above threshold
        if confidence < min_threshold:
            result = ("Other", confidence)
            self.classification_cache.set(cache_key, result)
            return result
        
        result = (best_industry, confidence)
        # Cache the successful classification
        self.classification_cache.set(cache_key, result)
        self.logger.debug(f"📦 Cached industry classification: {best_industry}")
        self.logger.debug(f"Industry classification: {best_industry} (confidence: {confidence:.3f})")
        return result
    
    def _disambiguate_close_matches(self, top_matches: List[Tuple[str, float]], title: str, content: str, company_name: str) -> str:
        """Disambiguate between very close industry matches using additional heuristics"""
        # Simple tie-breaking rules
        title_lower = title.lower()
        content_lower = content.lower()
        
        # Technology vs other industries
        tech_keywords = ['software', 'developer', 'programming', 'coding', 'technical', 'system', 'data']
        if any(keyword in title_lower for keyword in tech_keywords):
            for industry, _ in top_matches:
                if 'Technology' in industry or 'Information' in industry:
                    return industry
        
        # Healthcare vs other industries
        health_keywords = ['medical', 'health', 'clinical', 'patient', 'nurse', 'doctor']
        if any(keyword in title_lower or keyword in content_lower for keyword in health_keywords):
            for industry, _ in top_matches:
                if 'Healthcare' in industry or 'Medical' in industry:
                    return industry
        
        # Finance vs other industries
        finance_keywords = ['financial', 'banking', 'investment', 'analyst', 'accounting']
        if any(keyword in title_lower for keyword in finance_keywords):
            for industry, _ in top_matches:
                if 'Financial' in industry or 'Banking' in industry or 'Accounting' in industry:
                    return industry
        
        # Default to first match
        return top_matches[0][0]
    
    def _score_keywords(self, text: str, keywords: Set[str]) -> float:
        """Balanced keyword scoring that prevents bias toward industries with more keywords"""
        if not keywords:
            return 0.0
        
        matches = 0
        total_weight = 0
        context_bonus = 0
        
        # Create word list for proximity analysis
        words = re.findall(r'\\b\\w+\\b', text.lower())
        word_positions = {word: i for i, word in enumerate(words)}
        
        for keyword in keywords:
            # Use word boundaries to avoid partial matches
            pattern = r'\\b' + re.escape(keyword.lower()) + r'\\b'
            keyword_matches = re.findall(pattern, text, re.IGNORECASE)
            count = len(keyword_matches)
            
            if count > 0:
                matches += 1
                
                # Base weight for keyword presence (normalized by keyword set size)
                base_weight = len(keyword.split()) * count
                
                # Equal weight for all job role keywords (no bias toward specific roles)
                if any(important in keyword.lower() for important in [
                    'engineer', 'manager', 'analyst', 'developer', 'director', 
                    'coordinator', 'specialist', 'technician', 'assistant', 'worker',
                    'administrator', 'supervisor', 'representative', 'officer'
                ]):
                    base_weight *= 1.2  # Smaller multiplier for fairness
                
                # Context bonus for keyword clustering
                if len(keyword.split()) == 1 and keyword.lower() in word_positions:
                    pos = word_positions[keyword.lower()]
                    for other_keyword in keywords:
                        if other_keyword != keyword and other_keyword.lower() in word_positions:
                            other_pos = word_positions[other_keyword.lower()]
                            distance = abs(pos - other_pos)
                            if distance <= 5:  # Within 5 words
                                context_bonus += 0.05  # Smaller bonus to prevent over-weighting
                
                total_weight += base_weight
        
        if matches == 0:
            return 0.0
        
        # Balanced scoring formula with more generous scoring
        match_percentage = matches / len(keywords)  # Percentage of keywords matched
        
        # More generous frequency scoring
        frequency_factor = min(total_weight / max(len(keywords), 1), 2.0)  # Allow higher scores
        
        context_score = min(context_bonus, 0.3)  # Context bonus
        
        # More generous weighted combination
        final_score = (match_percentage * 0.5) + (frequency_factor * 0.4) + (context_score * 0.1)
        
        return min(final_score, 1.0)  # Cap at 1.0
    
    def _score_company_patterns(self, company_name: str) -> Dict[str, float]:
        """Enhanced company pattern matching with partial matching and confidence levels"""
        scores = defaultdict(float)
        
        if not company_name.strip():
            return scores
        
        company_name = company_name.lower().strip()
        
        for industry, companies in self.company_patterns.items():
            best_match_score = 0.0
            
            for company in companies:
                company_lower = company.lower()
                
                # Exact match (highest confidence)
                if company_lower == company_name:
                    best_match_score = max(best_match_score, 0.9)
                # Full substring match
                elif company_lower in company_name or company_name in company_lower:
                    best_match_score = max(best_match_score, 0.7)
                # Partial word match
                else:
                    company_words = set(company_lower.split())
                    name_words = set(company_name.split())
                    
                    if company_words & name_words:  # Any word overlap
                        overlap_ratio = len(company_words & name_words) / len(company_words)
                        if overlap_ratio >= 0.5:  # At least 50% word overlap
                            best_match_score = max(best_match_score, 0.5 + overlap_ratio * 0.2)
            
            if best_match_score > 0:
                scores[industry] = best_match_score
        
        return scores
    
    def _score_job_title_patterns(self, title: str) -> Dict[str, float]:
        """Enhanced job title pattern matching with fuzzy matching and role hierarchy"""
        scores = defaultdict(float)
        title_lower = title.lower()
        title_words = set(re.findall(r'\b\w+\b', title_lower))
        
        for industry, patterns in self.job_title_patterns.items():
            industry_score = 0.0
            
            for pattern in patterns:
                pattern_lower = pattern.lower()
                pattern_words = set(re.findall(r'\b\w+\b', pattern_lower))
                
                # Exact phrase match (highest score)
                if pattern_lower in title_lower:
                    industry_score = max(industry_score, 0.6)
                # Word overlap match
                elif pattern_words & title_words:
                    overlap_ratio = len(pattern_words & title_words) / len(pattern_words)
                    if overlap_ratio >= 0.7:  # At least 70% word overlap
                        industry_score = max(industry_score, 0.4 + overlap_ratio * 0.2)
                    elif overlap_ratio >= 0.5:  # At least 50% word overlap
                        industry_score = max(industry_score, 0.3 + overlap_ratio * 0.1)
            
            if industry_score > 0:
                scores[industry] = industry_score
        
        return scores
    
    def _score_skills_keywords(self, text: str) -> Dict[str, float]:
        """Score based on skills and technology keywords"""
        scores = defaultdict(float)
        
        for industry, skills in self.skills_keywords.items():
            skill_matches = 0
            for skill in skills:
                if skill.lower() in text:
                    skill_matches += 1
            
            if skill_matches > 0:
                scores[industry] = skill_matches / len(skills)
        
        return scores
    
    def get_detailed_classification(self, title: str, content: str, company_name: str = "") -> Dict:
        """Get detailed classification results with breakdown of all scoring methods"""
        full_text = f"{title} {content} {company_name}".lower()
        
        # Calculate scores for each method
        keyword_scores = {}
        for industry, keywords in self.industry_keywords.items():
            keyword_scores[industry] = self._score_keywords(full_text, keywords)
        
        company_scores = self._score_company_patterns(company_name)
        title_scores = self._score_job_title_patterns(title)
        skills_scores = self._score_skills_keywords(full_text)
        context_scores = self._analyze_context(title, content)
        
        # Calculate final weighted scores
        final_scores = defaultdict(float)
        for industry in self.industries:
            final_scores[industry] = (
                keyword_scores.get(industry, 0) * 0.35 +
                company_scores.get(industry, 0) * 0.25 +
                title_scores.get(industry, 0) * 0.20 +
                skills_scores.get(industry, 0) * 0.10 +
                context_scores.get(industry, 0) * 0.10
            )
        
        # Get top classification
        best_industry, confidence = self.classify_industry(title, content, company_name)
        
        return {
            'classification': best_industry,
            'confidence': confidence,
            'method_scores': {
                'keywords': dict(keyword_scores),
                'company': dict(company_scores),
                'title': dict(title_scores),
                'skills': dict(skills_scores),
                'context': dict(context_scores)
            },
            'final_scores': dict(final_scores),
            'top_5': sorted(final_scores.items(), key=lambda x: x[1], reverse=True)[:5]
        }
    
    def get_industry_suggestions(self, text: str, top_n: int = 5) -> List[Tuple[str, float]]:
        """Get top N industry suggestions with confidence scores"""
        title = ""
        content = text
        company = ""
        
        # Try to extract title and company if structured
        lines = text.split('\n')
        if len(lines) > 1:
            title = lines[0]
            content = '\n'.join(lines[1:])
        
        # Use detailed classification for better results
        details = self.get_detailed_classification(title, content, company)
        return details['top_5'][:top_n]


# Global instance for easy import
industry_classifier = IndustryClassifier()


def classify_job_industry(title: str, content: str, company_name: str = "") -> str:
    """
    Convenience function to classify job industry
    Returns the most likely industry name
    """
    industry, confidence = industry_classifier.classify_industry(title, content, company_name)
    
    # Log classification for debugging
    logging.getLogger(__name__).debug(
        f"Classified job '{title[:50]}...' as '{industry}' (confidence: {confidence:.3f})"
    )
    
    return industry


if __name__ == "__main__":
    # Test the classifier
    classifier = IndustryClassifier()
    
    # Test cases
    test_cases = [
        ("Software Engineer", "Python Django React AWS cloud development", "Google"),
        ("Registered Nurse", "Patient care medical hospital healthcare", "Kaiser Permanente"),
        ("Financial Analyst", "Investment banking portfolio analysis Excel", "Goldman Sachs"),
        ("Marketing Manager", "Digital marketing SEO social media campaigns", ""),
        ("Mechanical Engineer", "AutoCAD manufacturing quality control", "Ford")
    ]
    
    for title, content, company in test_cases:
        industry, confidence = classifier.classify_industry(title, content, company)
        print(f"Job: {title}")
        print(f"Industry: {industry} (confidence: {confidence:.3f})")
        print("---")