import os
import sys
import tempfile

from dotenv import load_dotenv

load_dotenv()


def _under_test():
    """True when this process is a test run.

    Importing ``backend.app`` runs migrations, backfills and a background
    rescore against whatever ``DATABASE_URL`` resolves to. Without this guard
    the default is ``instance/jobs.db`` — so simply running the suite would
    migrate and rewrite the user's real job data. Setting ``DATABASE_URL``
    explicitly always wins, so this only affects the unset default.
    """
    if os.getenv('JOBTRACKER_TEST') == '1':
        return True
    if 'PYTEST_CURRENT_TEST' in os.environ:
        return True
    # `python -m unittest` / `python -m pytest` leave the runner's package name
    # on __main__. This is exact where argv[0] is not: on Windows/conda argv[0]
    # comes through as the literal string "python.exe -m unittest".
    main = sys.modules.get('__main__')
    if getattr(main, '__package__', None) in ('unittest', 'pytest', '_pytest'):
        return True

    entry = (sys.argv[0] or '').replace('\\', '/').lower()
    if os.path.basename(entry) in ('pytest', 'py.test', 'pytest.exe'):
        return True
    return any(
        token in entry for token in ('unittest', 'pytest', 'py.test', 'nose')
    )


UNDER_TEST = _under_test()
_DEFAULT_DB = (
    f"sqlite:///{os.path.join(tempfile.gettempdir(), 'jobtracker_test.db')}"
    if UNDER_TEST else 'sqlite:///jobs.db'
)


class Config:
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL', _DEFAULT_DB)
    TESTING_MODE = UNDER_TEST
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # SQLite under a background scrape + a live UI.
    #
    # `timeout` makes a writer wait for the lock instead of raising
    # "database is locked" immediately, which is what used to abort a long
    # rescore mid-run. `pool_pre_ping` drops connections a crashed thread left
    # behind, and `check_same_thread` lets the scrape thread use the pool.
    # WAL journal mode (set per-connection in backend/app.py) lets the UI keep
    # reading while the scrape writes.
    SQLITE_BUSY_TIMEOUT_SECONDS = float(os.getenv('SQLITE_BUSY_TIMEOUT_SECONDS', '30'))
    SQLALCHEMY_ENGINE_OPTIONS = {
        'connect_args': {
            'check_same_thread': False,
            'timeout': SQLITE_BUSY_TIMEOUT_SECONDS,
        },
        'pool_pre_ping': True,
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
        "New York, New York",
        "Philadelphia, Pennsylvania",
        "Baltimore, Maryland",
        "Arlington, Virginia",
        "Washington, DC",
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

    # Legacy alias used by older scrapers. The live ranking path uses
    # PREFERRED_STATES from user preferences (editable in the UI).
    TARGET_STATES = [
        'MA', 'ME', 'CT', 'NJ', 'TX', 'NY', 'PA', 'MD', 'VA', 'DC',
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
        {'platform': 'greenhouse', 'slug': 'toast', 'company': 'Toast', 'hint': 'Boston, MA'},
        {'platform': 'greenhouse', 'slug': 'hubspot', 'company': 'HubSpot', 'hint': 'Cambridge, MA'},
        {'platform': 'greenhouse', 'slug': 'cloudflare', 'company': 'Cloudflare', 'hint': 'Austin, TX'},
        {'platform': 'greenhouse', 'slug': 'twilio', 'company': 'Twilio', 'hint': 'Austin, TX'},
        {'platform': 'greenhouse', 'slug': 'datadog', 'company': 'Datadog', 'hint': 'New York, NY'},
        {'platform': 'greenhouse', 'slug': 'stripe', 'company': 'Stripe', 'hint': 'Remote'},
        {'platform': 'greenhouse', 'slug': 'shopify', 'company': 'Shopify', 'hint': 'Remote'},
        {'platform': 'greenhouse', 'slug': 'airbnb', 'company': 'Airbnb', 'hint': 'Remote'},
        {'platform': 'greenhouse', 'slug': 'duolingo', 'company': 'Duolingo', 'hint': 'Pittsburgh, PA'},
        {'platform': 'lever', 'slug': 'netflix', 'company': 'Netflix', 'hint': 'Remote'},
        {'platform': 'ashby', 'slug': 'ramp', 'company': 'Ramp', 'hint': 'New York, NY'},
        # Common public boards in target metros (slugs verified via public API)
        {'platform': 'greenhouse', 'slug': 'fidelity', 'company': 'Fidelity Investments', 'hint': 'Boston, MA'},
        {'platform': 'greenhouse', 'slug': 'wayfair', 'company': 'Wayfair', 'hint': 'Boston, MA'},
        {'platform': 'greenhouse', 'slug': 'chewy', 'company': 'Chewy', 'hint': 'Boston, MA'},
        {'platform': 'greenhouse', 'slug': 'indeed', 'company': 'Indeed', 'hint': 'Austin, TX'},
        {'platform': 'greenhouse', 'slug': 'dropbox', 'company': 'Dropbox', 'hint': 'Remote'},
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
        
        # Role-level terms — full-time new-grad is the default (MS CS, May 2027)
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
        
        # Intern/co-op — demoted; full-time new-grad is the default search.
        'intern': 2,
        'internship': 2,
        'co-op': 2,
        'coop': 2,
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
    
    # ---- NUWorks: disabled from the normal workflow (code kept, isolated) ------
    NUWORKS_ENABLED = os.getenv('NUWORKS_ENABLED', 'false').lower() == 'true'

    # ---- Candidate profile (authoritative; seeds the DB on first run) ----------
    EDUCATION = [
        {
            'degree': 'MS',
            'field': 'Computer Science',
            'school': 'Northeastern University',
            'gpa': 4.0,
            'end_date': '2027-05-01',
            'is_current': True,
        },
        {
            'degree': 'BS',
            'field': 'Computer Science Engineering',
            'school': None,
            'gpa': None,
            'end_date': None,
            'is_current': False,
        },
    ]

    # Structured from PROFILE_SUMMARY already stored in this file. Nothing invented.
    EXPERIENCE = [
        {
            'title': 'Data Engineering Co-op',
            'company': 'Bangor Savings Bank',
            'location': 'Bangor, ME',
            'start_date': '2026-07-01',
            'end_date': '2026-08-31',
            'employment_type': 'co-op',
            'description': (
                'T-SQL audit framework for SQL Server service accounts (Agent, SSISDB, '
                'credentials, proxies, roles, sessions); extended production data mart '
                'with DimTags via SQL Server + SSIS; ETL package updates, data-quality '
                'filters, Git/Azure DevOps production promotions; partnered with Data & '
                'Analytics / Reporting for BI-facing pipelines.'
            ),
            'skills_used': [
                'SQL Server', 'T-SQL', 'SSIS', 'Azure DevOps', 'ETL', 'Data Modeling',
            ],
        },
        {
            'title': 'Research Assistant – Conversational Intelligence',
            'company': 'Steelcase / Roux Working Lab',
            'location': 'Portland, ME',
            'start_date': '2026-02-01',
            'end_date': '2026-05-31',
            'employment_type': 'research',
            'description': 'Conversational intelligence research: AI/NLP, embeddings.',
            'skills_used': ['Python', 'NLP', 'Embeddings', 'Machine Learning'],
        },
        {
            'title': 'Graduate Teaching Assistant – Algorithms',
            'company': 'Northeastern University',
            'location': 'Boston, MA',
            'start_date': '2026-01-01',
            'end_date': '2026-04-30',
            'employment_type': 'part-time',
            'description': 'Graduate teaching assistant for Algorithms.',
            'skills_used': ['Python'],
        },
        {
            'title': 'Data Science Intern',
            'company': 'Besant',
            'location': None,
            'start_date': None,
            'end_date': None,
            'employment_type': 'internship',
            'description': 'Python, MySQL, Power BI, ETL, Fernet.',
            'skills_used': ['Python', 'MySQL', 'Power BI', 'ETL'],
        },
        {
            'title': 'Software Developer Intern',
            'company': 'Bluebase',
            'location': None,
            'start_date': None,
            'end_date': None,
            'employment_type': 'internship',
            'description': 'Flask on AWS EC2, Nginx, Linux.',
            'skills_used': ['Python', 'Flask', 'AWS', 'Linux'],
        },
    ]

    # Skills the candidate can actually claim. Category drives dimension scoring.
    PROFILE_SKILLS = [
        ('Python', 'language', 5),
        ('SQL', 'language', 5),
        ('Java', 'language', 3),
        ('C', 'language', 2),
        ('C++', 'language', 2),
        ('T-SQL', 'language', 4),
        ('Azure', 'cloud', 5),
        ('Azure SQL', 'cloud', 4),
        ('Azure DevOps', 'devops', 4),
        ('AWS', 'cloud', 3),
        ('SQL Server', 'database', 5),
        ('SSIS', 'etl', 5),
        ('ETL', 'etl', 5),
        ('ELT', 'etl', 4),
        ('Data Engineering', 'domain', 5),
        ('Data Pipelines', 'domain', 5),
        ('Data Quality', 'domain', 4),
        ('Data Validation', 'domain', 4),
        ('Data Warehousing', 'domain', 4),
        ('Data Modeling', 'domain', 4),
        ('Spark', 'bigdata', 3),
        ('Hadoop', 'bigdata', 2),
        ('Databricks', 'bigdata', 2),
        ('Power BI', 'bi', 5),
        ('Machine Learning', 'ml', 3),
        ('NLP', 'ml', 3),
        ('Transformers', 'ml', 2),
        ('BERT', 'ml', 2),
        ('Embeddings', 'ml', 2),
        ('TensorFlow', 'ml', 2),
        ('PyTorch', 'ml', 2),
        ('Git', 'tooling', 4),
        ('GitHub', 'tooling', 3),
        ('Docker', 'devops', 3),
        ('Cloud Computing', 'cloud', 3),
        ('DevOps', 'devops', 3),
    ]

    # ---- Role tiers (semantic classification targets) -------------------------
    ROLE_TIERS = {
        1: [
            'analytics engineer', 'data analyst', 'business intelligence analyst',
            'bi analyst', 'bi engineer', 'business intelligence engineer',
            'data quality analyst', 'data governance analyst', 'data integration',
            'junior data engineer', 'associate data engineer', 'etl developer',
            'business intelligence developer', 'bi developer', 'reporting analyst',
        ],
        2: [
            'data engineer', 'cloud data engineer', 'azure data engineer',
            'data platform engineer', 'data operations engineer', 'dataops',
            'backend data engineer', 'analytics developer', 'data warehouse engineer',
            'database developer', 'data infrastructure engineer',
        ],
        3: [
            'data scientist', 'ml engineer', 'machine learning engineer',
            'ai engineer', 'nlp engineer', 'applied scientist',
            'research engineer', 'decision scientist',
        ],
    }

    # Titles that are a poor fit regardless of keyword overlap
    ROLE_AVOID = [
        'frontend', 'front-end', 'front end', 'ui developer', 'ui engineer',
        'react developer', 'angular developer', 'vue developer', 'web designer',
        'ux designer', 'ux researcher', 'graphic designer', 'ios developer',
        'android developer', 'mobile developer', 'game developer',
        'salesforce developer', 'wordpress', 'seo ', 'qa tester',
        # Pure product/SWE titles that previously leaked in via "engineer" overlap
        # (Avoid phrases that also appear inside good titles like "Data Platform Engineer")
        'backend engineer', 'back-end engineer', 'back end engineer',
        'software engineer', 'full stack', 'fullstack', 'full-stack',
        'growth engineer', 'devops engineer',
        'site reliability', 'sre ', 'security engineer',
        'solutions engineer', 'sales engineer', 'support engineer',
    ]

    ROLE_TIER_WEIGHT = {1: 100.0, 2: 85.0, 3: 60.0}
    ROLE_UNKNOWN_SCORE = float(os.getenv('ROLE_UNKNOWN_SCORE', '35'))

    # ---- Candidate match score weights (must sum to 1.0) ----------------------
    MATCH_WEIGHTS = {
        'skills': float(os.getenv('W_SKILLS', '0.30')),
        'responsibilities': float(os.getenv('W_RESPONSIBILITIES', '0.25')),
        'experience': float(os.getenv('W_EXPERIENCE', '0.15')),
        'education': float(os.getenv('W_EDUCATION', '0.10')),
        'role': float(os.getenv('W_ROLE', '0.10')),
        'location': float(os.getenv('W_LOCATION', '0.05')),
        'authorization': float(os.getenv('W_AUTHORIZATION', '0.05')),
    }

    # FINAL = CANDIDATE_MATCH_WEIGHT * match + OPPORTUNITY_WEIGHT * opportunity
    CANDIDATE_MATCH_WEIGHT = float(os.getenv('CANDIDATE_MATCH_WEIGHT', '0.70'))
    OPPORTUNITY_WEIGHT = float(os.getenv('OPPORTUNITY_WEIGHT', '0.30'))

    # Opportunity sub-weights (normalized internally)
    OPPORTUNITY_WEIGHTS = {
        'freshness': 0.25,
        'sponsorship': 0.20,
        'role_priority': 0.15,
        'company_preference': 0.10,
        'location': 0.10,
        'accessibility': 0.10,
        'experience_difficulty': 0.10,
    }

    # ---- Location preferences (editable from the UI; these are seed defaults) --
    PREFERRED_STATES = ['MA', 'ME', 'CT', 'NJ', 'TX', 'NY', 'PA', 'MD', 'VA', 'DC']
    ACCEPTABLE_STATES = ['NH', 'RI', 'VT', 'DE', 'NC', 'OH', 'TN', 'MN', 'AZ', 'UT', 'CO', 'IL', 'GA']
    ALLOW_REMOTE_US = os.getenv('ALLOW_REMOTE_US', 'true').lower() == 'true'
    ALLOW_HYBRID = os.getenv('ALLOW_HYBRID', 'true').lower() == 'true'
    ALLOW_RELOCATION = os.getenv('ALLOW_RELOCATION', 'true').lower() == 'true'

    # ---- Freshness / expiry ---------------------------------------------------
    # Thresholds are hour ceilings; `bucket_for` returns the first bucket the
    # age is below. Strictly increasing so the mapping is unambiguous.
    FRESHNESS_BUCKETS = [
        (6, 'hot'),         # 0-6h
        (24, 'fresh'),      # 6-24h
        (72, 'recent'),     # 1-3 days
        (168, 'aging'),     # 3-7 days
        (336, 'old'),       # 7-14 days
        (None, 'stale'),    # 14+ days
    ]
    # ---- Job age policy -------------------------------------------------------
    # One consistent policy, measured against the *source posting date*
    # (`date_posted`) — never against scrape/rediscovery time. Jobs with an
    # unknown posting date are never auto-expired; they are labelled 'unknown'.
    #
    #   MAX_JOB_AGE_DAYS   — beyond this a stored posting is treated as expired
    #   TODAY_MAX_AGE_DAYS — Today only recommends postings younger than this
    #   WATCH_MAX_AGE_DAYS — still worth watching, but not a Today headline
    #   SCRAPE_MAX_AGE_DAYS — sources drop listings older than this at ingest
    MAX_JOB_AGE_DAYS = int(os.getenv('MAX_JOB_AGE_DAYS', '30'))
    TODAY_MAX_AGE_DAYS = int(os.getenv('TODAY_MAX_AGE_DAYS', '14'))
    WATCH_MAX_AGE_DAYS = int(os.getenv('WATCH_MAX_AGE_DAYS', '21'))
    SCRAPE_MAX_AGE_DAYS = int(os.getenv('SCRAPE_MAX_AGE_DAYS', '14'))

    # Kept as the historical name for MAX_JOB_AGE_DAYS so existing callers and
    # stored preferences keep working. Both always agree.
    JOB_EXPIRY_DAYS = MAX_JOB_AGE_DAYS
    VERIFY_STALE_AFTER_HOURS = int(os.getenv('VERIFY_STALE_AFTER_HOURS', '48'))
    VERIFY_TOP_N = int(os.getenv('VERIFY_TOP_N', '25'))

    # ---- Daily briefing ------------------------------------------------------
    DAILY_TOP_N = int(os.getenv('DAILY_TOP_N', '10'))
    # Today briefing: only Tier 1–2 by default (set 3 to include ML/AI stretch)
    BRIEFING_MAX_ROLE_TIER = int(os.getenv('BRIEFING_MAX_ROLE_TIER', '2'))
    STRONG_MATCH_MIN = int(os.getenv('STRONG_MATCH_MIN', '75'))
    EXCELLENT_MATCH_MIN = int(os.getenv('EXCELLENT_MATCH_MIN', '90'))

    # ---- Scheduler -----------------------------------------------------------
    SCHEDULE_ENABLED = os.getenv('SCHEDULE_ENABLED', 'true').lower() == 'true'
    # 'daily' -> SCHEDULE_HOUR:SCHEDULE_MINUTE; 'interval' -> every SCHEDULE_INTERVAL_HOURS
    SCHEDULE_MODE = os.getenv('SCHEDULE_MODE', 'interval')
    SCHEDULE_HOUR = int(os.getenv('SCHEDULE_HOUR', '7'))
    SCHEDULE_MINUTE = int(os.getenv('SCHEDULE_MINUTE', '0'))
    SCHEDULE_TIMEZONE = os.getenv('SCHEDULE_TIMEZONE', 'America/New_York')
    SCHEDULE_INTERVAL_HOURS = float(os.getenv('SCHEDULE_INTERVAL_HOURS', '3'))

    # Sources used by the scheduled daily run (NUWorks + LinkedIn excluded)
    DAILY_SOURCES = [
        'github_newgrad', 'ats', 'adzuna', 'jsearch',
        'remoteok', 'themuse', 'remotive', 'arbeitnow',
    ]

    # ---- Source enablement ---------------------------------------------------
    # Explicit on/off switches. A source that is switched off, or that is
    # missing its credentials, is reported as DISABLED with a reason — it is
    # never reported as "succeeded with 0 jobs".
    ENABLE_GITHUB_NEWGRAD = os.getenv('ENABLE_GITHUB_NEWGRAD', 'true').lower() == 'true'
    ENABLE_GITHUB_INTERN = os.getenv('ENABLE_GITHUB_INTERN', 'false').lower() == 'true'
    ENABLE_ATS = os.getenv('ENABLE_ATS', 'true').lower() == 'true'
    ENABLE_REMOTEOK = os.getenv('ENABLE_REMOTEOK', 'true').lower() == 'true'
    ENABLE_THEMUSE = os.getenv('ENABLE_THEMUSE', 'true').lower() == 'true'
    ENABLE_REMOTIVE = os.getenv('ENABLE_REMOTIVE', 'true').lower() == 'true'
    ENABLE_ARBEITNOW = os.getenv('ENABLE_ARBEITNOW', 'true').lower() == 'true'
    ENABLE_ADZUNA = os.getenv('ENABLE_ADZUNA', 'true').lower() == 'true'
    ENABLE_JSEARCH = os.getenv('ENABLE_JSEARCH', 'true').lower() == 'true'
    ENABLE_LINKEDIN = os.getenv('ENABLE_LINKEDIN', 'false').lower() == 'true'
    ENABLE_NUWORKS = os.getenv('ENABLE_NUWORKS', 'false').lower() == 'true'

    # Per-source metadata. `requires` lists Config attributes that must be
    # non-empty for the source to run; `enable_flag` is the on/off switch.
    SOURCE_REGISTRY = {
        'github_newgrad': {
            'label': 'GitHub New Grad',
            'kind': 'feed', 'enable_flag': 'ENABLE_GITHUB_NEWGRAD', 'requires': [],
        },
        'github_intern': {
            'label': 'GitHub Internships',
            'kind': 'feed', 'enable_flag': 'ENABLE_GITHUB_INTERN', 'requires': [],
        },
        'ats': {
            'label': 'Company ATS (Greenhouse / Lever / Ashby)',
            'kind': 'api', 'enable_flag': 'ENABLE_ATS', 'requires': [],
        },
        'remoteok': {
            'label': 'RemoteOK',
            'kind': 'api', 'enable_flag': 'ENABLE_REMOTEOK', 'requires': [],
        },
        'themuse': {
            'label': 'The Muse',
            'kind': 'api', 'enable_flag': 'ENABLE_THEMUSE', 'requires': [],
        },
        'remotive': {
            'label': 'Remotive',
            'kind': 'api', 'enable_flag': 'ENABLE_REMOTIVE', 'requires': [],
        },
        'arbeitnow': {
            'label': 'Arbeitnow',
            'kind': 'api', 'enable_flag': 'ENABLE_ARBEITNOW', 'requires': [],
        },
        'adzuna': {
            'label': 'Adzuna',
            'kind': 'api', 'enable_flag': 'ENABLE_ADZUNA',
            'requires': ['ADZUNA_APP_ID', 'ADZUNA_APP_KEY'],
            'signup_url': 'https://developer.adzuna.com/',
        },
        'jsearch': {
            'label': 'JSearch (RapidAPI)',
            'kind': 'api', 'enable_flag': 'ENABLE_JSEARCH',
            'requires': ['JSEARCH_API_KEY'],
            'signup_url': 'https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch',
        },
        'linkedin': {
            'label': 'LinkedIn',
            'kind': 'web', 'enable_flag': 'ENABLE_LINKEDIN', 'requires': [],
        },
        'nuworks': {
            'label': 'NUWorks',
            'kind': 'web', 'enable_flag': 'ENABLE_NUWORKS',
            'requires': ['NUWORKS_USERNAME', 'NUWORKS_PASSWORD'],
        },
    }

    # Sources that ignore the keyword argument and always return one full feed,
    # using the keyword only to filter the response afterwards. The manager
    # fetches these ONCE per run and filters locally instead of re-downloading
    # the same payload for every keyword.
    #
    # Remotive is deliberately NOT here: it passes the keyword to the API as a
    # server-side `search` param, so one keyword-less call returns a genuinely
    # narrower result set rather than the same data.
    FULL_FEED_SOURCES = ['remoteok', 'arbeitnow', 'themuse']

    # Wall-clock budget per source, so one slow board cannot stall a whole run.
    SOURCE_TIME_BUDGET_SECONDS = int(os.getenv('SOURCE_TIME_BUDGET_SECONDS', '180'))

    # ---- Follow-ups ---------------------------------------------------------
    FOLLOWUP_DAYS = [int(d) for d in os.getenv('FOLLOWUP_DAYS', '7,14').split(',') if d.strip()]

    # ---- Company watchlist seed (evidence-based data filled in at runtime) ----
    WATCHLIST_COMPANIES = [
        'Capital One', 'Fidelity', 'Liberty Mutual', 'Optum',
        'JPMorgan Chase', 'Bank of America', 'Wells Fargo',
        'Amazon', 'Microsoft', 'Google', 'Deloitte', 'Accenture',
        'IBM', 'Oracle', 'Datadog', 'Snowflake', 'Databricks', 'Nationwide',
    ]

    # ---- External search launcher (NOT integrated sources) -------------------
    EXTERNAL_SEARCH_SITES = [
        {'name': 'LinkedIn', 'url': 'https://www.linkedin.com/jobs/search/?keywords={q}&location={loc}&f_TPR=r86400'},
        {'name': 'Indeed', 'url': 'https://www.indeed.com/jobs?q={q}&l={loc}&fromage=1'},
        {'name': 'Dice', 'url': 'https://www.dice.com/jobs?q={q}&location={loc}'},
        {'name': 'Built In', 'url': 'https://builtin.com/jobs?search={q}'},
        {'name': 'Wellfound', 'url': 'https://wellfound.com/jobs?query={q}'},
        {'name': 'Simplify', 'url': 'https://simplify.jobs/jobs?query={q}'},
    ]

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

    # ---- Work-authorization classification -----------------------------------
    # Each entry: (pattern, reason). A match sets status RED and stores the
    # matched sentence as evidence. Never inferred from the employer name.
    AUTH_BLOCKING_PATTERNS = [
        (r'must be a u\.?s\.? citizen', 'US citizenship required'),
        (r'u\.?s\.? citizen(?:s|ship)?\s+(?:only|is required|required)', 'US citizenship required'),
        (r'united states citizen(?:s|ship)?\s+(?:only|required)', 'US citizenship required'),
        (r'(?:active\s+)?security clearance\s+(?:is\s+)?required', 'Security clearance required'),
        (r'active\s+(?:ts|top secret|secret)\s+clearance', 'Security clearance required'),
        (r'(?:ts|top secret)\s*[/\\]\s*(?:sci|ssbi)', 'Security clearance required'),
        (r'ability to obtain (?:a )?security clearance', 'Security clearance required'),
        (r'(?:we (?:are )?(?:do|will) not|cannot|unable to)\s+(?:be able to\s+)?sponsor', 'Employer states it will not sponsor'),
        (r'\b(?:do|does|will|can|could)\s*(?:not|n\'t)\s+sponsor\b', 'Employer states it will not sponsor'),
        (r'\b(?:do|does|will|can|could)\s*(?:not|n\'t)\s+(?:be able to\s+)?'
         r'(?:provide|offer|support|pursue|file|apply for)\b[^.]{0,80}?'
         r'(?:sponsorship|visa|immigration)', 'Employer states it will not sponsor'),
        (r'\b(?:is|are)\s+not\s+(?:currently\s+)?(?:providing|offering|sponsoring)'
         r'\b[^.]{0,60}(?:sponsorship|visa|immigration)', 'Employer states it will not sponsor'),
        (r'\b(?:unable|not able|not willing|unwilling)\s+to\s+'
         r'(?:sponsor|provide sponsorship|offer sponsorship)', 'Employer states it will not sponsor'),
        (r'(?:visa\s+|immigration[\s-]related\s+)?sponsorship\s+(?:is\s+|will\s+)?'
         r'not\s+(?:be\s+)?(?:available|offered|provided|possible|supported)',
         'No sponsorship available'),
        (r'no\s+(?:visa\s+|immigration\s+)?sponsorship\s+(?:is\s+)?'
         r'(?:available|provided|offered)', 'No sponsorship available'),
        (r'\bnot\s+eligible\s+for\b[^.]{0,50}(?:sponsorship|visa)',
         'Role stated as not eligible for sponsorship'),
        # In posting language "no sponsorship required/needed" is addressed at the
        # candidate: you must already be authorized without employer sponsorship.
        (r'\bno\s+(?:visa\s+)?sponsorship\s+(?:is\s+)?(?:required|needed)',
         'Requires authorization without sponsorship'),
        (r'\bno\s+(?:visa\s+)?sponsorship\b', 'No sponsorship available'),
        (r'\bwithout\s+sponsorship\b', 'Requires authorization without sponsorship'),
        (r'without\s+(?:the need for\s+)?(?:current or future\s+)?(?:visa\s+)?sponsorship', 'Requires authorization without sponsorship'),
        (r'do(?:es)? not (?:now or in the future )?require sponsorship', 'Requires authorization without sponsorship'),
        (r'(?:must|do|does|will|can)\s?not\s+(?:now or in the future\s+)?require\b[^.]{0,60}sponsorship', 'Requires authorization without sponsorship'),
        (r'not require sponsorship (?:now or in the future|to work)', 'Requires authorization without sponsorship'),
        (r'permanent resident(?:s)?\s+(?:or|and)\s+citizen(?:s)?\s+only', 'Citizen/PR only'),
        (r'green card holder(?:s)?\s+(?:or|and)\s+(?:u\.?s\.? )?citizen(?:s)?\s+only', 'Citizen/PR only'),
        (r'itar', 'ITAR / export-control restriction'),
        (r'(?:must be a )?(?:u\.?s\.? )?person(?:s)? as defined by (?:itar|export)', 'ITAR / export-control restriction'),
    ]

    # A match sets status GREEN with the matched sentence as evidence.
    AUTH_FRIENDLY_PATTERNS = [
        (r'(?:will|can|do)\s+sponsor', 'Employer states it sponsors'),
        (r'(?:visa|h-?1b|h1-?b)\s+sponsorship\s+(?:is\s+)?(?:available|offered|provided)', 'Sponsorship available'),
        (r'sponsor(?:ship)?\s+(?:for\s+)?(?:eligible\s+)?(?:candidates|applicants|employees)', 'Sponsorship offered'),
        (r'open to (?:candidates on\s+)?(?:f-?1|opt|stem opt|cpt)', 'Open to OPT/F-1'),
        (r'(?:e-?verify|e verify)\s+(?:employer|participant)', 'E-Verify employer (supports STEM OPT)'),
        (r'we\s+(?:provide|offer)\s+(?:visa\s+)?sponsorship', 'Sponsorship offered'),
        (r'cap[\s-]?exempt', 'H-1B cap-exempt employer'),
    ]

    # Phrases that indicate authorization is discussed but the outcome is unclear.
    AUTH_UNCLEAR_PATTERNS = [
        (r'must be (?:legally )?authorized to work', 'Requires work authorization; sponsorship not addressed'),
        (r'work authorization', 'Work authorization mentioned without detail'),
        (r'sponsorship', 'Sponsorship mentioned without a clear position'),
        (r'visa status', 'Visa status mentioned without detail'),
    ]

    # ---- Responsibility taxonomy (drives the responsibilities dimension) ------
    # Each bucket maps to phrases found in job descriptions that the candidate
    # can demonstrably do. Coverage of these buckets = responsibilities score.
    RESPONSIBILITY_BUCKETS = {
        'pipeline_build': [
            'build data pipeline', 'develop data pipeline', 'etl pipeline',
            'elt pipeline', 'data ingestion', 'batch processing', 'ingest data',
            'build etl', 'develop etl', 'data integration',
        ],
        'sql_development': [
            'write sql', 'complex sql', 'stored procedure', 'query optimization',
            'sql queries', 'tune queries', 't-sql', 'database queries',
        ],
        'warehouse_modeling': [
            'data warehouse', 'dimensional model', 'star schema', 'data model',
            'data mart', 'schema design', 'snowflake schema',
        ],
        'data_quality': [
            'data quality', 'data validation', 'data accuracy', 'reconciliation',
            'data integrity', 'unit test', 'data governance', 'data lineage',
        ],
        'reporting_bi': [
            'dashboard', 'power bi', 'tableau', 'reporting', 'visualization',
            'kpi', 'self-service analytics', 'looker',
        ],
        'analysis': [
            'ad hoc analysis', 'analyze data', 'insights', 'trend analysis',
            'root cause', 'business requirements', 'stakeholder',
        ],
        'cloud_platform': [
            'azure', 'aws', 'gcp', 'cloud platform', 'data factory',
            'synapse', 'databricks', 'snowflake', 's3', 'redshift',
        ],
        'automation_devops': [
            'automate', 'ci/cd', 'version control', 'git', 'docker',
            'orchestration', 'airflow', 'scheduling', 'monitoring',
        ],
        'ml_modeling': [
            'machine learning model', 'train model', 'feature engineering',
            'nlp', 'predictive model', 'deploy model',
        ],
        'documentation': [
            'document', 'documentation', 'runbook', 'best practices',
            'code review', 'collaborate with',
        ],
    }

    # How strongly the candidate can demonstrate each responsibility bucket
    # (0.0-1.0). Derived from real experience/projects, editable in settings.
    RESPONSIBILITY_COVERAGE = {
        'pipeline_build': 1.0,
        'sql_development': 1.0,
        'warehouse_modeling': 0.9,
        'data_quality': 1.0,
        'reporting_bi': 0.9,
        'analysis': 0.8,
        'cloud_platform': 0.85,
        'automation_devops': 0.7,
        'ml_modeling': 0.6,
        'documentation': 0.9,
    }

    # Candidate's highest completed/in-progress degree level
    CANDIDATE_DEGREE_LEVEL = os.getenv('CANDIDATE_DEGREE_LEVEL', 'masters')

    # Education requirement detection
    EDUCATION_PATTERNS = {
        'phd': [r'\bph\.?d\b', r'\bdoctorate\b'],
        'masters': [r"\bmaster'?s?\b", r'\bm\.?s\.?\b(?!\s*office)', r'\bmba\b', r'\bgraduate degree\b'],
        'bachelors': [r"\bbachelor'?s?\b", r'\bb\.?s\.?\b', r'\bb\.?a\.?\b', r'\bundergraduate degree\b'],
        'associates': [r"\bassociate'?s degree\b"],
    }

    # ---- Job quality thresholds ---------------------------------------------
    # Sources ranked by trustworthiness of the data they return.
    SOURCE_TRUST = {
        'greenhouse': 1.0, 'lever': 1.0, 'ashby': 1.0, 'smartrecruiters': 1.0,
        'ats': 1.0, 'workday': 0.95,
        'github_newgrad': 0.9, 'github_intern': 0.9,
        'themuse': 0.8, 'remotive': 0.75, 'remoteok': 0.75, 'arbeitnow': 0.7,
        'adzuna': 0.65, 'jsearch': 0.6,
        'linkedin': 0.5, 'nuworks': 0.5,
    }
    MIN_QUALITY_FOR_RANKING = float(os.getenv('MIN_QUALITY_FOR_RANKING', '40'))

    # Below this many characters a description cannot be assessed, so the
    # text-dependent match dimensions are scored as unknown rather than clean.
    MIN_DESCRIPTION_CHARS = int(os.getenv('MIN_DESCRIPTION_CHARS', '200'))

    # A location dimension at or below this score (non-US, excluded state) makes
    # a job unrealistic to apply to, no matter how well the skills line up.
    LOCATION_BLOCK_MAX = float(os.getenv('LOCATION_BLOCK_MAX', '20'))
    # A role dimension below this means the title is not one of my target roles.
    ROLE_BLOCK_MIN = float(os.getenv('ROLE_BLOCK_MIN', '40'))

    # =========================================================================
    # V3 — Industry Intelligence + Hiring Manager / Recruiter Intelligence
    # =========================================================================

    # ---- Industry taxonomy -------------------------------------------------
    # "core" == the user's conventional high-volume target industries.
    # "under-the-radar" == outside those, surfaced as a research signal (NOT a
    # claim of lower competition).
    CORE_INDUSTRIES = [
        'TECHNOLOGY', 'FINANCE', 'HEALTHCARE', 'CONSULTING',
        'RETAIL', 'INSURANCE', 'TELECOMMUNICATIONS', 'GOVERNMENT', 'EDUCATION',
    ]
    UNDER_THE_RADAR_INDUSTRIES = [
        'MANUFACTURING', 'ENERGY', 'LOGISTICS', 'SUPPLY_CHAIN', 'AGRICULTURE',
        'CONSTRUCTION', 'WATER', 'INDUSTRIAL_AUTOMATION', 'CHEMICALS',
        'AEROSPACE', 'DEFENSE', 'REAL_ESTATE', 'FOOD', 'MINING',
        'ENVIRONMENTAL_SERVICES',
    ]

    # Title/description keyword evidence -> industry. First match wins. These
    # are hints combined with job content; they never override a poor role match.
    INDUSTRY_SIGNALS = {
        'TECHNOLOGY': [
            'software', 'technology', 'tech ', 'platform', 'cloud', 'saas',
            'data center', 'internet', 'developer', 'engineering',
        ],
        'FINANCE': [
            'bank', 'financial', 'finance', 'investment', 'asset management',
            'hedge fund', 'capital', 'credit', 'trading', 'payments', 'wealth',
            'insurance',
        ],
        'HEALTHCARE': [
            'health', 'medical', 'pharma', 'biotech', 'clinical', 'hospital',
            'care ', 'wellness', 'diagnostic',
        ],
        'CONSULTING': [
            'consult', 'advisory', 'strategy',
        ],
        'RETAIL': [
            'retail', 'e-commerce', 'ecommerce', 'commerce', 'consumer',
            'store',
        ],
        'INSURANCE': [
            'insurance', 'underwriting', 'actuarial', 'reinsurance',
        ],
        'TELECOMMUNICATIONS': [
            'telecom', 'telecommunication', 'network', 'wireless', '5g', 'broadband',
        ],
        'GOVERNMENT': [
            'government', 'federal', 'public sector', 'municipal', 'state agency',
            'agency', 'civic',
        ],
        'EDUCATION': [
            'education', 'university', 'school', 'college', 'campus',
        ],
        'MANUFACTURING': [
            'manufactur', 'industrial', 'factory', 'plant', 'production ',
            'automotive', 'semiconductor', 'electronics manufacturing',
        ],
        'ENERGY': [
            'energy', 'utilities', 'electric', 'solar', 'renewable', 'power ',
            'oil', 'gas', 'grid',
        ],
        'LOGISTICS': [
            'logistic', 'transportation', 'shipping', 'freight', 'supply chain',
            'warehouse', 'distribution', 'fleet', 'delivery',
        ],
        'SUPPLY_CHAIN': [
            'supply chain', 'procurement', 'sourcing', 'inventory',
        ],
        'AGRICULTURE': [
            'agriculture', 'agtech', 'agri', 'farming', 'crop', 'food processing',
        ],
        'CONSTRUCTION': [
            'construction', 'infrastructure', 'real estate development', 'engineering & construction',
        ],
        'WATER': [
            'water', 'wastewater', 'utilities - water',
        ],
        'INDUSTRIAL_AUTOMATION': [
            'automation', 'industrial automation', 'robotics', 'control system',
            'plc', 'scada',
        ],
        'CHEMICALS': [
            'chemical', 'specialty chemical', 'petrochemical',
        ],
        'AEROSPACE': [
            'aerospace', 'aviation', 'aircraft', 'space',
        ],
        'DEFENSE': [
            'defense', 'defence', 'military', 'intelligence', 'missile',
            'munitions', 'defense contractor',
        ],
        'REAL_ESTATE': [
            'real estate', 'property', 'facilities', 'asset management real estate',
        ],
        'FOOD': [
            'food', 'food tech', 'restaurants', 'beverage', 'grocery',
        ],
        'MINERALS': [
            'mining', 'minerals', 'metals',
        ],
        'ENVIRONMENTAL_SERVICES': [
            'environmental', 'recycling', 'waste management', 'sustainability',
        ],
    }
    DEFAULT_INDUSTRY = 'UNKNOWN'

    # Industry names shown to the user, mapped from the internal label.
    INDUSTRY_LABELS = {
        'TECHNOLOGY': 'Technology / Software',
        'FINANCE': 'Finance / Banking / Fintech',
        'HEALTHCARE': 'Healthcare / Medical',
        'CONSULTING': 'Consulting',
        'RETAIL': 'Retail / Ecommerce',
        'INSURANCE': 'Insurance',
        'TELECOMMUNICATIONS': 'Telecommunications',
        'GOVERNMENT': 'Government',
        'EDUCATION': 'Education',
        'MANUFACTURING': 'Manufacturing / Industrial',
        'ENERGY': 'Energy / Utilities',
        'LOGISTICS': 'Logistics / Transportation',
        'SUPPLY_CHAIN': 'Supply Chain',
        'AGRICULTURE': 'Agriculture / Agtech',
        'CONSTRUCTION': 'Construction / Infrastructure',
        'WATER': 'Water / Wastewater',
        'INDUSTRIAL_AUTOMATION': 'Industrial Automation',
        'CHEMICALS': 'Chemicals',
        'AEROSPACE': 'Aerospace',
        'DEFENSE': 'Defense',
        'REAL_ESTATE': 'Real Estate / Facilities',
        'FOOD': 'Food / Food Tech',
        'MINERALS': 'Mining / Materials',
        'ENVIRONMENTAL_SERVICES': 'Environmental Services',
    }

    # Industry opportunity weights (aggregated across the live scored pool).
    INDUSTRY_OPPORTUNITY_WEIGHTS = {
        'matching_job_count': 0.30,
        'fresh_jobs': 0.20,
        'entry_level_jobs': 0.10,
        'target_role_family_jobs': 0.15,
        'url_verify_rate': 0.10,
        'authorization_evidence_rate': 0.10,
        'competition': 0.05,
    }
    INDUSTRY_OPPORTUNITY_MIN_JOBS = int(os.getenv('INDUSTRY_OPPORTUNITY_MIN_JOBS', '2'))

    # ---- Golden opportunity score (V3 §21) ---------------------------------
    # Combined "how valuable right now" score. Reuses existing sub-scores and is
    # a SIBLING signal to final_score — never overrides a poor match. Weights
    # are normalized inside score_golden.
    GOLDEN_SCORE_WEIGHTS = {
        'job_fit': 0.28,          # candidate_match_score
        'freshness': 0.18,        # freshness score
        'authorization': 0.16,    # sponsorship/authorization compat
        'job_quality': 0.14,      # job_quality_score
        'application_effort': 0.08,  # lower effort -> higher
        'industry_opportunity': 0.07,
        'contact_relevance': 0.05,
        'competition': 0.04,      # only when evidence exists
    }
    # Contact relevance sub-weights (evidence quality dominates).
    CONTACT_RELEVANCE_WEIGHTS = {
        'role_match': 0.30,
        'department_match': 0.20,
        'seniority': 0.15,
        'company_matches': 0.10,
        'role_family': 0.10,
        'evidence_quality': 0.15,
    }

    # ---- Contact discovery gating (selective, Part 13) --------------------
    CONTACT_TRIGGER_PRIORITY = float(os.getenv('CONTACT_TRIGGER_PRIORITY', '85'))
    CONTACT_REQUIRE_VERIFIED_URL = True      # only for verified apply URLs
    CONTACT_REQUIRE_STRONG_MATCH = float(os.getenv('CONTACT_REQUIRE_STRONG_MATCH', '75'))

    # Contact relevance thresholds
    CONTACT_RELEVANCE_HIGH = 80.0
    CONTACT_RELEVANCE_MEDIUM = 55.0
    CONTACT_RELEVANCE_LOW = 30.0

    # Confidence labels
    CONTACT_CONFIDENCE_HIGH = 'HIGH'
    CONTACT_CONFIDENCE_MEDIUM = 'MEDIUM'
    CONTACT_CONFIDENCE_LOW = 'LOW'
    CONTACT_CONFIDENCE_UNKNOWN = 'UNKNOWN'

    # Email states
    EMAIL_VERIFIED_PUBLIC = 'VERIFIED_PUBLIC'
    EMAIL_PUBLIC_UNVERIFIED = 'PUBLIC_UNVERIFIED'
    EMAIL_PATTERN_INFERRED = 'PATTERN_INFERRED'
    EMAIL_NOT_FOUND = 'NOT_FOUND'
    EMAIL_UNKNOWN = 'UNKNOWN'

    # Default outreach cadence (in days) for follow-up scheduling. Never auto-
    # sends, only builds a draft the user approves.
    OUTREACH_FOLLOWUP_DAYS = int(os.getenv('OUTREACH_FOLLOWUP_DAYS', '7'))

    # Friendliest recruiting-contact role labels, in discovery priority
    # order (hiring manager → technical recruiter → university recruiter → …).
    CONTACT_PRIORITY_TYPES = [
        'hiring_manager', 'engineering_manager', 'data_manager',
        'technical_recruiter', 'university_recruiter', 'talent_acquisition',
        'department_leader',
    ]

    # ---- V3 source_type labels (used by industry/contact evidence) --------
    SOURCE_TYPE_LABELS = {
        'curated_community_github': 'Curated community GitHub new-grad list',
    }
