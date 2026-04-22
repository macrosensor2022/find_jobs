import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL', 'sqlite:///jobs.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    PORT = int(os.getenv('PORT', 8080))
    
    # Default profile info (can be overridden via environment or API)
    DEFAULT_NAME = os.getenv('DEFAULT_NAME', 'Job Seeker')
    DEFAULT_GITHUB_URL = os.getenv('DEFAULT_GITHUB_URL', '')
    DEFAULT_TARGET_ROLE = os.getenv('DEFAULT_TARGET_ROLE', 'Software Engineer')
    
    # Your profile info
    GITHUB_PROFILE = os.getenv('GITHUB_PROFILE', '')
    RESUME_PATH = os.getenv('RESUME_PATH', '')
    
    # Target locations for job search
    TARGET_LOCATIONS = [
        # Original
        "Maine", "New Jersey", "New York", "Texas", "Colorado", "Utah", "Nevada", "Arizona",
        # Lower competition states
        "Idaho", "Montana", "Wyoming", "New Mexico", "Kansas", "Nebraska", "Iowa",
        "Arkansas", "Oklahoma", "Missouri", "Kentucky", "Tennessee", "Alabama",
        "South Carolina", "North Dakota", "South Dakota", "Wisconsin", "Minnesota",
        "Indiana", "Ohio", "Michigan", "Pennsylvania", "Vermont", "New Hampshire",
        # Remote
        "Remote"
    ]
    
    # Job search keywords based on your profile
    SEARCH_KEYWORDS = [
        # Data roles
        "Data Science Intern",
        "Data Science Summer Intern",
        "Data Science Fall Intern",
        "Data Analyst Intern",
        "Data Analyst Summer Intern",
        "Data Analyst Fall Intern",
        "Data Engineer Intern",
        "Data Engineer Summer Intern",
        "Data Engineer Fall Intern",
        "Data Science Co-op",
        "Data Analyst Co-op",
        "Data Engineer Co-op",
        # AI/ML roles
        "Machine Learning Intern",
        "Machine Learning Summer Intern",
        "Machine Learning Fall Intern",
        "AI Engineer Intern",
        "NLP Engineer Intern",
        "ML Engineer Intern",
        "AI/ML Intern",
        "Machine Learning Co-op",
        # SDE roles with AI focus
        "Software Engineer Intern AI",
        "Software Development Engineer Intern",
        "Software Engineer Summer Intern",
        "Software Engineer Fall Intern",
        "SDE Intern",
        "Software Engineer Intern Machine Learning",
        "Software Engineer Intern",
        # Research roles
        "Research Intern Machine Learning",
        "AI Research Intern",
        "NLP Research Intern"
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
        'adzuna': 'https://www.adzuna.com/'
    }
    
    # Adzuna API credentials (optional - get free key at https://developer.adzuna.com/)
    ADZUNA_APP_ID = os.getenv('ADZUNA_APP_ID', '')
    ADZUNA_APP_KEY = os.getenv('ADZUNA_APP_KEY', '')
    
    # Profile matcher configuration (can be overridden via environment as JSON)
    # These define the skills and keywords used for job matching
    _default_skills = {
        # Programming Languages (weight: high)
        'python': 15,
        'java': 10,
        'sql': 10,
        'r': 6,
        
        # Data Science & ML (weight: very high)
        'machine learning': 15,
        'deep learning': 12,
        'data science': 15,
        'data analyst': 12,
        'data analysis': 12,
        'data engineering': 12,
        'data engineer': 12,
        'nlp': 15,
        'natural language processing': 15,
        'neural network': 10,
        'transformer': 12,
        'bert': 12,
        'pytorch': 12,
        'tensorflow': 12,
        'scikit-learn': 10,
        'sklearn': 10,
        'pandas': 10,
        'numpy': 8,
        'matplotlib': 6,
        'seaborn': 6,
        
        # AI/ML specific
        'ai': 12,
        'artificial intelligence': 12,
        'computer vision': 10,
        'cnn': 10,
        'resnet': 8,
        'sentiment analysis': 10,
        'text classification': 10,
        'recommendation system': 10,
        'llm': 12,
        'gpt': 10,
        'langchain': 10,
        
        # Data Engineering
        'etl': 10,
        'data pipeline': 10,
        'spark': 8,
        'hadoop': 6,
        'airflow': 8,
        'kafka': 8,
        'snowflake': 8,
        'dbt': 8,
        
        # Cloud & DevOps
        'aws': 10,
        'ec2': 8,
        'docker': 8,
        's3': 6,
        'cloud': 8,
        'azure': 8,
        'gcp': 8,
        
        # Databases
        'mysql': 8,
        'postgresql': 8,
        'mongodb': 6,
        'database': 6,
        'redis': 6,
        
        # Tools
        'git': 5,
        'power bi': 8,
        'tableau': 8,
        'jupyter': 5,
        'excel': 5,
        
        # Soft skills / Role types - high weight for internships
        'intern': 20,
        'internship': 20,
        'co-op': 25,
        'entry level': 15,
        'entry-level': 15,
        'junior': 12,
        'graduate': 10,
        'new grad': 12,
        'masters': 8,
        'university': 8,
    }
    
    # Load skills from environment or use defaults
    _env_skills = os.getenv('PROFILE_MATCHER_SKILLS')
    if _env_skills:
        import json
        try:
            PROFILE_MATCHER_SKILLS = json.loads(_env_skills)
        except json.JSONDecodeError:
            PROFILE_MATCHER_SKILLS = _default_skills
    else:
        PROFILE_MATCHER_SKILLS = _default_skills
    
    # Negative keywords (reduce score) - can be overridden via environment
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
    
    # Maximum match score for normalization
    PROFILE_MATCHER_MAX_SCORE = int(os.getenv('PROFILE_MATCHER_MAX_SCORE', 150))
