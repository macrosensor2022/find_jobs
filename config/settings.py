import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL', 'sqlite:///jobs.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # Allow background scrape thread to share the SQLite connection safely
    SQLALCHEMY_ENGINE_OPTIONS = {
        'connect_args': {'check_same_thread': False},
    }
    PORT = int(os.getenv('PORT', 8080))
    
    # Default profile info (§4.1)
    DEFAULT_NAME = os.getenv('DEFAULT_NAME', 'Vinay Varshigan SJ')
    # LinkedIn export contact; school mail still used on some resumes
    DEFAULT_EMAIL = os.getenv('DEFAULT_EMAIL', 'varsvinay911@gmail.com')
    DEFAULT_GITHUB_URL = os.getenv('DEFAULT_GITHUB_URL', 'https://github.com/macrosensor2022')
    DEFAULT_LINKEDIN_URL = os.getenv(
        'DEFAULT_LINKEDIN_URL',
        'https://www.linkedin.com/in/vinaysj2003/',
    )
    DEFAULT_TARGET_ROLE = os.getenv(
        'DEFAULT_TARGET_ROLE',
        'Data Engineer / Analytics Engineer / BI Engineer '
        '(SQL Server, SSIS, Azure, Power BI) — Full-Time New Grad',
    )
    # Synced from LinkedIn PDF export Profile (1).pdf — Aug 19, 2026
    PROFILE_SUMMARY = (
        "Data Engineering Co-op @ Bangor Savings Bank (Jul–Aug 2026, Bangor ME): "
        "T-SQL audit framework for SQL Server service accounts (Agent, SSISDB, credentials, "
        "proxies, roles, sessions); extended production data mart with DimTags via SQL Server + SSIS; "
        "ETL package updates, data-quality filters, Git/Azure DevOps production promotions; "
        "partnered with Data & Analytics / Reporting for BI-facing pipelines. "
        "MS CS @ Northeastern (Sep 2025–Dec 2027), Portland ME / Boston. "
        "RA – Steelcase conversational intelligence (Feb–May 2026, Roux Working Lab: AI/NLP, embeddings). "
        "GTA – Algorithms (Jan–Apr 2026). "
        "Prior: Data Science Intern @ Besant (Python, MySQL, Power BI, ETL, Fernet); "
        "Software Developer Intern @ Bluebase (Flask on AWS EC2, Nginx, Linux). "
        "Stack: Python | SQL | SQL Server | T-SQL | SSIS | Azure | Azure DevOps | AWS | "
        "ETL | Data Modeling | Power BI | AI/NLP | ML | Git. "
        "Top skills on LinkedIn: Microsoft 365 Copilot, SSMS, Azure DevOps."
    )

    GITHUB_PROFILE = os.getenv('GITHUB_PROFILE', 'https://github.com/macrosensor2022')
    RESUME_PATH = os.getenv('RESUME_PATH', '')
    
    # LinkedIn crawl seeds — TARGET_STATES metros (more locations, not harder paging).
    LINKEDIN_LOCATIONS = [
        "Portland, Maine",
        "Bangor, Maine",
        "Boston, Massachusetts",
        "Hartford, Connecticut",
        "Newark, New Jersey",
        "Dallas, Texas",
        "Austin, Texas",
        "Houston, Texas",
        "Charlotte, North Carolina",
        "Nashville, Tennessee",
        "Columbus, Ohio",
        "Minneapolis, Minnesota",
        "Phoenix, Arizona",
        "Salt Lake City, Utah",
        "Denver, Colorado",
        "United States",
        "Remote",
    ]
    LINKEDIN_JOB_TYPES = ['F']  # full-time only (no internship filter)

    # Seeking FT new-grad roles — drop co-op / internship titles in match + scrapers
    SEEKING_FULL_TIME_NEW_GRAD = True

    # State allowlist (+ Remote-US). Deliberately EXCLUDES CA / WA / OR.
    TARGET_STATES = [
        'ME', 'TX', 'CT', 'NJ', 'MA', 'TN', 'NC', 'OH', 'MN', 'AZ', 'UT', 'CO',
    ]
    EXCLUDED_STATES = ['CA', 'WA', 'OR']

    METRO_FLAGS = {
        '25540': 'high_opportunity',  # Hartford CT
        '16740': 'high_opportunity',  # Charlotte NC
        '18140': 'high_opportunity',  # Columbus OH
        '19100': 'high_volume',       # Dallas–Fort Worth
        '14460': 'high_competition',  # Boston MA
    }
    DE_SOC_CODES = ['15-1243', '15-2051', '15-1211']

    # ATS-direct boards (Greenhouse / Lever / Ashby) — sponsor-dense employers
    ATS_BOARDS = [
        {'platform': 'greenhouse', 'slug': 'toast', 'hint': 'Boston, MA'},
        {'platform': 'greenhouse', 'slug': 'hubspot', 'hint': 'Cambridge, MA'},
        {'platform': 'greenhouse', 'slug': 'cloudflare', 'hint': 'Austin, TX'},
        {'platform': 'greenhouse', 'slug': 'twilio', 'hint': 'Austin, TX'},
        {'platform': 'greenhouse', 'slug': 'datadog', 'hint': 'New York, NY'},
        {'platform': 'greenhouse', 'slug': 'stripe', 'hint': 'Remote'},
        {'platform': 'greenhouse', 'slug': 'shopify', 'hint': 'Remote'},
        {'platform': 'greenhouse', 'slug': 'airbnb', 'hint': 'Remote'},
        {'platform': 'greenhouse', 'slug': 'duolingo', 'hint': 'Pittsburgh, PA'},
        {'platform': 'lever', 'slug': 'netflix', 'hint': 'Remote'},
        {'platform': 'ashby', 'slug': 'ramp', 'hint': 'New York, NY'},
        # Common public boards in target metros (slugs verified via public API)
        {'platform': 'greenhouse', 'slug': 'fidelity', 'hint': 'Boston, MA'},
        {'platform': 'greenhouse', 'slug': 'wayfair', 'hint': 'Boston, MA'},
        {'platform': 'greenhouse', 'slug': 'chewy', 'hint': 'Boston, MA'},
        {'platform': 'greenhouse', 'slug': 'indeed', 'hint': 'Austin, TX'},
        {'platform': 'greenhouse', 'slug': 'dropbox', 'hint': 'Remote'},
    ]

    # Legacy location strings for post-filter (prefer TARGET_STATES)
    TARGET_LOCATIONS = [
        "United States", "USA",
        "Maine", "ME", "Portland", "Bangor",
        "Massachusetts", "MA", "Boston",
        "Connecticut", "CT", "Hartford",
        "New Jersey", "NJ",
        "Texas", "TX", "Dallas", "Austin", "Houston",
        "Tennessee", "TN", "Nashville",
        "North Carolina", "NC", "Charlotte",
        "Ohio", "OH", "Columbus",
        "Minnesota", "MN", "Minneapolis",
        "Arizona", "AZ", "Phoenix",
        "Utah", "UT",
        "Colorado", "CO", "Denver",
        "Remote",
    ]
    
    # ---- Search keywords — full-time / new-grad DE & analytics lane ----
    SEARCH_KEYWORDS = [
        "Data Engineer",
        "Analytics Engineer",
        "BI Engineer",
        "Business Intelligence Engineer",
        "ETL Developer",
        "SSIS Developer",
        "SQL Server",
        "Azure Data Engineer",
        "Data Analyst",
        "Data Scientist",
        "Power BI Developer",
        "NLP Engineer",
        "Machine Learning Engineer",
        "New Grad Data Engineer",
        "New Grad Data Analyst",
        "New Grad Data Scientist",
        "Entry Level Data Engineer",
        "Associate Data Engineer",
        "Junior Data Engineer",
        "Early Career Data Engineer",
        "University Grad Data Engineer",
    ]

    # Kept for optional intern scrapes (github_intern) — not used in default FT scrape
    SEARCH_KEYWORDS_INTERN = [
        "Data Engineer Co-op",
        "Data Science Co-op",
        "Data Analyst Co-op",
        "Analytics Co-op",
        "BI Co-op",
        "Data Engineer Intern",
        "Data Science Intern",
        "Data Analyst Intern",
        "Machine Learning Intern",
        "AI Engineer Intern",
        "BI Intern",
        "Power BI Intern",
        "NLP Intern",
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
        'jsearch': 'https://jsearch.p.rapidapi.com/',
    }
    
    # Adzuna API credentials (optional) — free ~1000 calls/month
    ADZUNA_APP_ID = os.getenv('ADZUNA_APP_ID', '')
    ADZUNA_APP_KEY = os.getenv('ADZUNA_APP_KEY', '')
    MAX_ADZUNA_CALLS = int(os.getenv('MAX_ADZUNA_CALLS', '20'))
    ADZUNA_COUNTRIES = ['us', 'in']
    ADZUNA_LOCATIONS_US = [
        'Boston, MA', 'Dallas, TX', 'Austin, TX', 'Hartford, CT',
        'Charlotte, NC', 'Remote',
    ]
    ADZUNA_LOCATIONS_IN = [
        'Bangalore', 'Hyderabad', 'Chennai', 'Mumbai', 'Pune', 'Remote',
    ]

    # JSearch (RapidAPI / OpenWeb Ninja) — free ~200 calls/month; use sparingly
    JSEARCH_API_KEY = os.getenv('JSEARCH_API_KEY', '')
    JSEARCH_HOST = os.getenv('JSEARCH_HOST', 'jsearch.p.rapidapi.com')
    JSEARCH_BASE_URL = os.getenv(
        'JSEARCH_BASE_URL',
        'https://jsearch.p.rapidapi.com/search',
    )
    MAX_JSEARCH_CALLS = int(os.getenv('MAX_JSEARCH_CALLS', '8'))
    JSEARCH_CORE_ROLES = [
        'Data Engineer',
        'Analytics Engineer',
        'ETL Developer',
        'Data Engineer Intern',
    ]
    JSEARCH_QUERIES = [
        'Data Engineer in Boston, MA, USA',
        'Data Engineer in Dallas, TX, USA',
        'Data Engineer Intern in United States',
        'Analytics Engineer in Austin, TX, USA',
        'Data Engineer in Bangalore, India',
        'Data Engineer in Hyderabad, India',
        'ETL Developer in Chennai, India',
        'Data Engineer Intern in India',
    ]

    # SimplifyJobs / Pitt CSC public GitHub listing feeds (no API key)
    GITHUB_SIMPLIFY_FEEDS = [
        {
            'kind': 'newgrad',
            'job_type': 'full-time',
            'url': (
                'https://raw.githubusercontent.com/SimplifyJobs/New-Grad-Positions/'
                'dev/.github/scripts/listings.json'
            ),
        },
        {
            'kind': 'intern',
            'job_type': 'internship',
            'url': (
                'https://raw.githubusercontent.com/SimplifyJobs/Summer2026-Internships/'
                'dev/.github/scripts/listings.json'
            ),
        },
        {
            'kind': 'intern',
            'job_type': 'internship',
            'url': (
                'https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships/'
                'dev/.github/scripts/listings.json'
            ),
        },
    ]
    
    # ---- Profile matcher (§4.2, §4.3, §5.3) -------------------------------------
    # Weighted skill list built from the owner's experience and target lane.
    # HIGH = 15, MED = 8-10, role-level terms = 8-15, intern/co-op demoted to 5.
    _default_skills = {
        # HIGH — Bangor DE co-op + LinkedIn export (Aug 2026)
        'python': 15,
        'sql': 15,
        'sql server': 15,
        'mssql': 15,
        't-sql': 15,
        'tsql': 15,
        'ssis': 15,
        'ssisdb': 12,
        'sql server agent': 10,
        'azure devops': 12,
        'devops': 8,
        'mysql': 12,
        'etl': 15,
        'data pipeline': 15,
        'data pipelines': 15,
        'data mart': 14,
        'data modeling': 15,
        'data model': 12,
        'star schema': 15,
        'dimensional modeling': 15,
        'dimension': 8,
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
        'conversational ai': 12,
        'embeddings': 10,
        'llm': 12,
        'llms': 12,
        'machine learning': 12,
        'deep learning': 10,
        'data science': 12,
        'data engineer': 15,
        'data engineering': 15,
        'data analyst': 12,
        'data analysis': 10,
        'banking': 10,
        'financial services': 8,
        'fintech': 6,
        
        # MED — supporting skills (LinkedIn + resumes)
        'numpy': 8,
        'pandas': 10,
        'matplotlib': 6,
        'flask': 8,
        'java': 8,
        'c++': 6,
        'rest api': 8,
        'rest apis': 8,
        'api': 6,
        'postman': 6,
        'linux': 8,
        'nginx': 6,
        'gunicorn': 6,
        'performance tuning': 8,
        'index management': 8,
        'data cleaning': 8,
        'data preprocessing': 8,
        'data quality': 10,
        'cryptography': 6,
        'web development': 6,
        'web application': 6,
        'microsoft 365': 5,
        'copilot': 4,
        'ssms': 8,
        
        # Data tools
        'spark': 8,
        'hadoop': 6,
        'airflow': 8,
        'kafka': 8,
        'snowflake': 8,
        'dbt': 8,
        'postgresql': 8,
        'pymysql': 6,
        'mongodb': 6,
        'redis': 6,
        'database': 6,
        'tableau': 8,
        'jupyter': 5,
        'excel': 5,
        
        # Cloud & DevOps — Azure boosted for Bangor stack
        'azure': 14,
        'gcp': 8,
        'docker': 8,
        's3': 6,
        'glue': 6,
        'vpc': 5,
        'auto scaling': 5,
        'git': 8,
        'ci/cd': 10,
        
        # AI/ML frameworks
        'pytorch': 10,
        'tensorflow': 10,
        'scikit-learn': 8,
        'sklearn': 8,
        'transformer': 10,
        'bert': 10,
        'computer vision': 8,
        'langchain': 8,
        'dbscan': 6,
        'clustering': 6,
        'sentiment analysis': 8,
        
        # Role-level terms — co-op/intern + full-time (still in school till Dec 2027)
        'full-time': 10,
        'full time': 10,
        'new grad': 12,
        'new graduate': 12,
        'entry level': 12,
        'entry-level': 12,
        'associate': 8,
        'early career': 10,
        'junior': 10,
        'engineer i': 8,
        'graduate': 8,
        
        # Intern/co-op — boosted (currently in MS, graduating Dec 2027)
        'intern': 12,
        'internship': 12,
        'co-op': 15,
        'coop': 15,
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

    # Experience gate — Vinay has <1yr professional (intern + Bangor DE co-op).
    # Hard-drop postings requiring >= EXP_HARD_DROP_YEARS or senior titles.
    EXP_YEARS = float(os.getenv('EXP_YEARS', '0.75'))
    EXP_HARD_DROP_YEARS = float(os.getenv('EXP_HARD_DROP_YEARS', '3'))
    EXP_SOFT_PENALTY = int(os.getenv('EXP_SOFT_PENALTY', '12'))   # match_score points
    EXP_EARLY_CAREER_BOOST = int(os.getenv('EXP_EARLY_CAREER_BOOST', '15'))
    
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
