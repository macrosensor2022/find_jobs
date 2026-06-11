import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL', 'sqlite:///jobs.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    PORT = int(os.getenv('PORT', 8080))
    
    # Default profile info (§4.1)
    DEFAULT_NAME = os.getenv('DEFAULT_NAME', 'Vinay Varshigan SJ')
    DEFAULT_GITHUB_URL = os.getenv('DEFAULT_GITHUB_URL', 'https://github.com/macrosensor2022')
    DEFAULT_TARGET_ROLE = os.getenv(
        'DEFAULT_TARGET_ROLE',
        'Data Engineer / BI Engineer / Data Scientist (Full-time, New Grad)',
    )
    
    GITHUB_PROFILE = os.getenv('GITHUB_PROFILE', 'https://github.com/macrosensor2022')
    RESUME_PATH = os.getenv('RESUME_PATH', '')
    
    # LinkedIn crawls keyword × location, so keep this list short to avoid
    # 150+ page fetches.  Other scrapers use TARGET_LOCATIONS for post-filter.
    LINKEDIN_LOCATIONS = [
        "Boston, Massachusetts",
        "New York, New York",
        "Portland, Maine",
        "United States",
        "Remote",
    ]
    
    # Target locations (§4.1 — primary + broad US + remote)
    TARGET_LOCATIONS = [
        "United States", "USA",
        "Boston", "Massachusetts",
        "Portland", "Maine",
        "New York", "New Jersey",
        "Texas", "Colorado", "Utah", "Nevada", "Arizona",
        "Idaho", "Montana", "Wyoming", "New Mexico", "Kansas", "Nebraska", "Iowa",
        "Arkansas", "Oklahoma", "Missouri", "Kentucky", "Tennessee", "Alabama",
        "South Carolina", "North Dakota", "South Dakota", "Wisconsin", "Minnesota",
        "Indiana", "Ohio", "Michigan", "Pennsylvania", "Vermont", "New Hampshire",
        "Remote",
    ]
    
    # ---- Search keywords (§5.3) -------------------------------------------------
    # Default focus: full-time / new-grad roles in data eng / BI / data science / AI-NLP
    SEARCH_KEYWORDS = [
        # Data Engineering / BI (primary lane)
        "Data Engineer",
        "Business Intelligence Engineer",
        "BI Engineer",
        "BI Developer",
        "Analytics Engineer",
        "ETL Developer",
        "Data Warehouse Engineer",
        # Data Analysis / Science
        "Data Analyst",
        "Data Scientist",
        "Business Analyst Data",
        # ML / AI / NLP
        "Machine Learning Engineer",
        "ML Engineer",
        "AI Engineer",
        "NLP Engineer",
        "Applied Scientist",
        # New-grad / entry-level variants
        "New Grad Data Engineer",
        "New Grad Data Analyst",
        "New Grad Data Scientist",
        "Entry Level Data Engineer",
        "Entry Level Data Analyst",
        "Entry Level Data Scientist",
        "Associate Data Engineer",
        "Associate Data Analyst",
        "Junior Data Engineer",
        "Junior Data Analyst",
        "Early Career Data",
        "University Graduate Engineer",
        "Engineer I",
    ]
    
    # Optional co-op/internship set (toggle for interim searches before grad)
    SEARCH_KEYWORDS_INTERN = [
        "Data Science Intern",
        "Data Analyst Intern",
        "Data Engineer Intern",
        "BI Intern",
        "Machine Learning Intern",
        "AI Engineer Intern",
        "Data Science Co-op",
        "Data Analyst Co-op",
        "Data Engineer Co-op",
    ]
    
    # NUWorks credentials (set via environment variables for security)
    NUWORKS_USERNAME = os.getenv('NUWORKS_USERNAME', '')
    NUWORKS_PASSWORD = os.getenv('NUWORKS_PASSWORD', '')
    
    # Job sources
    JOB_SOURCES = {
        'nuworks': 'https://northeastern-csm.symplicity.com/students/',
        'linkedin': 'https://www.linkedin.com/jobs/',
        'remoteok': 'https://remoteok.com/',
        'indeed': 'https://www.indeed.com/',
        'themuse': 'https://www.themuse.com/',
        'adzuna': 'https://www.adzuna.com/',
    }
    
    # Adzuna API credentials (optional)
    ADZUNA_APP_ID = os.getenv('ADZUNA_APP_ID', '')
    ADZUNA_APP_KEY = os.getenv('ADZUNA_APP_KEY', '')
    
    # ---- Profile matcher (§4.2, §4.3, §5.3) -------------------------------------
    # Weighted skill list built from the owner's experience and target lane.
    # HIGH = 15, MED = 8-10, role-level terms = 8-15, intern/co-op demoted to 5.
    _default_skills = {
        # HIGH — core target-lane skills
        'python': 15,
        'sql': 15,
        'mysql': 12,
        'etl': 15,
        'data pipeline': 15,
        'data pipelines': 15,
        'data modeling': 15,
        'data model': 12,
        'star schema': 15,
        'dimensional modeling': 15,
        'business intelligence': 15,
        'power bi': 15,
        'dashboard': 12,
        'dashboards': 12,
        'reporting': 10,
        'aws': 12,
        'ec2': 10,
        'cloud': 10,
        'ai': 12,
        'nlp': 12,
        'natural language processing': 12,
        'llm': 12,
        'llms': 12,
        'machine learning': 12,
        'deep learning': 10,
        'data science': 12,
        'data engineer': 15,
        'data engineering': 15,
        'data analyst': 12,
        'data analysis': 10,
        
        # MED — supporting skills from §4.2
        'numpy': 8,
        'pandas': 10,
        'matplotlib': 6,
        'flask': 8,
        'rest api': 8,
        'rest apis': 8,
        'postman': 6,
        'linux': 8,
        'nginx': 6,
        'performance tuning': 8,
        'index management': 8,
        'data cleaning': 8,
        'cryptography': 6,
        'fernet': 6,
        
        # Data tools
        'spark': 8,
        'hadoop': 6,
        'airflow': 8,
        'kafka': 8,
        'snowflake': 8,
        'dbt': 8,
        'postgresql': 8,
        'mongodb': 6,
        'redis': 6,
        'database': 6,
        'tableau': 8,
        'jupyter': 5,
        
        # Cloud & DevOps
        'azure': 8,
        'gcp': 8,
        'docker': 8,
        's3': 6,
        'git': 5,
        
        # AI/ML frameworks
        'pytorch': 10,
        'tensorflow': 10,
        'scikit-learn': 8,
        'sklearn': 8,
        'transformer': 10,
        'bert': 10,
        'computer vision': 8,
        'langchain': 8,
        
        # Role-level terms — full-time focus
        'full-time': 12,
        'full time': 12,
        'new grad': 15,
        'new graduate': 15,
        'entry level': 12,
        'entry-level': 12,
        'associate': 8,
        'early career': 10,
        'junior': 8,
        'engineer i': 8,
        'graduate': 8,
        
        # Intern/co-op — kept but de-prioritized (was 20/25, now 5)
        'intern': 5,
        'internship': 5,
        'co-op': 5,
    }
    
    _env_skills = os.getenv('PROFILE_MATCHER_SKILLS')
    if _env_skills:
        import json
        try:
            PROFILE_MATCHER_SKILLS = json.loads(_env_skills)
        except json.JSONDecodeError:
            PROFILE_MATCHER_SKILLS = _default_skills
    else:
        PROFILE_MATCHER_SKILLS = _default_skills
    
    # Negative keywords (reduce match_score)
    _default_negative = {
        'senior': -8,
        'sr.': -8,
        'staff': -8,
        'principal': -10,
        'lead': -5,
        'manager': -6,
        '5+ years': -10,
        '7+ years': -15,
        '10+ years': -20,
        'director': -12,
        'vp': -12,
        'phd required': -8,
        'security clearance': -15,
        'us citizen only': -15,
        'us citizens only': -15,
    }
    
    _env_negative = os.getenv('PROFILE_MATCHER_NEGATIVE_KEYWORDS')
    if _env_negative:
        import json
        try:
            PROFILE_MATCHER_NEGATIVE_KEYWORDS = json.loads(_env_negative)
        except json.JSONDecodeError:
            PROFILE_MATCHER_NEGATIVE_KEYWORDS = _default_negative
    else:
        PROFILE_MATCHER_NEGATIVE_KEYWORDS = _default_negative
    
    PROFILE_MATCHER_MAX_SCORE = int(os.getenv('PROFILE_MATCHER_MAX_SCORE', 150))
    
    # ---- OPT-specific thresholds (§5.3, §5.4) -----------------------------------
    
    # match_score >= this → opt_field_related = True
    OPT_FIELD_MATCH_MIN = int(os.getenv('OPT_FIELD_MATCH_MIN', 40))
    
    # "Apply fast" freshness badge threshold (hours)
    FRESHNESS_FAST_HOURS = int(os.getenv('FRESHNESS_FAST_HOURS', 24))
    
    # Regex patterns to detect citizenship / clearance / no-sponsorship language.
    # Applied to title + description to set sponsorship_screen flag.
    SPONSORSHIP_SCREEN_PATTERNS = [
        r'must be a u\.?s\.? citizen',
        r'u\.?s\.? citizen(s)?\s+(only|required)',
        r'united states citizen(s)?\s+(only|required)',
        r'security clearance\s+required',
        r'active\s+security clearance',
        r'(ts|top secret)\s*[/\\]\s*(sci|ssbi)',
        r'not\s+(able|willing)\s+to\s+sponsor',
        r'will\s+not\s+sponsor',
        r'cannot\s+sponsor',
        r'without\s+(current\s+or\s+future\s+)?sponsorship',
        r'no\s+sponsorship',
        r'(require[sd]?)\s+(us|u\.s\.?)\s+work\s+authorization',
        r'must\s+be\s+authorized\s+to\s+work.*without.*sponsor',
        r'permanent\s+resident\s+or\s+citizen',
    ]
