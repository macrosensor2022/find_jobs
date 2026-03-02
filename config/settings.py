import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL', 'sqlite:///jobs.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    PORT = int(os.getenv('PORT', 8080))
    
    # Your profile info
    GITHUB_PROFILE = "https://github.com/macrosensor2022"
    RESUME_PATH = os.getenv('RESUME_PATH', r"C:\Users\varsv\Downloads\big_resume_modified_datascience_dataanalyt_Dataengineer.docx (15).pdf")
    
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
        "Data Analyst Intern",
        "Data Engineer Intern",
        "Data Science Co-op",
        "Data Analyst Co-op",
        "Data Engineer Co-op",
        # AI/ML roles
        "Machine Learning Intern",
        "AI Engineer Intern",
        "NLP Engineer Intern",
        "ML Engineer Intern",
        "AI/ML Intern",
        "Machine Learning Co-op",
        # SDE roles with AI focus
        "Software Engineer Intern AI",
        "Software Development Engineer Intern",
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
