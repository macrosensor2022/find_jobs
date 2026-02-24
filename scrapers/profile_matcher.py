"""
Profile Matching System
Calculates match score between job postings and user profile
"""

import re
import html
from typing import Dict, List, Tuple


class ProfileMatcher:
    def __init__(self):
        # Your skills and keywords from your GitHub profile
        self.skills = {
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
            
            # Your specific experience
            'fasttext': 8,
            'log classification': 6,
            'iot': 6,
            'rest api': 6,
            'analytics': 10,
            'statistics': 8,
            'visualization': 8,
        }
        
        # Negative keywords (reduce score) - reduced penalties
        self.negative_keywords = {
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
        
        # Target locations
        self.target_locations = [
            # Original states
            'maine', 'me', 'new jersey', 'nj', 'new york', 'ny', 'nyc',
            'texas', 'tx', 'austin', 'dallas', 'houston',
            'colorado', 'co', 'denver', 'boulder',
            'utah', 'ut', 'salt lake', 'nevada', 'nv', 'arizona', 'az',
            # Lower competition states
            'idaho', 'id', 'boise', 'montana', 'mt', 'wyoming', 'wy',
            'new mexico', 'nm', 'albuquerque', 'kansas', 'ks', 'nebraska', 'ne',
            'iowa', 'ia', 'arkansas', 'ar', 'oklahoma', 'ok', 'missouri', 'mo',
            'kentucky', 'ky', 'tennessee', 'tn', 'nashville', 'alabama', 'al',
            'south carolina', 'sc', 'north dakota', 'nd', 'south dakota', 'sd',
            'wisconsin', 'wi', 'madison', 'minnesota', 'mn', 'minneapolis',
            'indiana', 'in', 'indianapolis', 'ohio', 'oh', 'columbus', 'cleveland',
            'michigan', 'mi', 'detroit', 'ann arbor', 'pennsylvania', 'pa', 'pittsburgh',
            'vermont', 'vt', 'new hampshire', 'nh',
            # Remote
            'remote', 'hybrid', 'anywhere', 'work from home', 'wfh'
        ]
        
        # Maximum possible score for normalization (use a reasonable cap)
        self.max_score = 150  # Adjusted for realistic scoring
    
    def _clean_html(self, text: str) -> str:
        """Remove HTML tags and decode entities"""
        if not text:
            return ''
        # Remove HTML tags
        clean = re.sub(r'<[^>]+>', ' ', text)
        # Decode HTML entities
        clean = html.unescape(clean)
        # Clean up whitespace
        clean = re.sub(r'\s+', ' ', clean)
        return clean.strip()
    
    def calculate_match_score(self, job: Dict) -> Tuple[int, List[str]]:
        """
        Calculate match score for a job posting.
        Returns (score_percentage, matched_skills)
        """
        title = (job.get('title') or '').lower()
        description = (job.get('description') or '').lower()
        location = (job.get('location') or '').lower()
        company = (job.get('company') or '').lower()
        
        # Clean HTML from description
        description = self._clean_html(description)
        
        # Combine all text for matching
        full_text = f"{title} {description} {company}"
        
        score = 0
        matched_skills = []
        
        # Match skills
        for skill, weight in self.skills.items():
            if self._word_match(skill, full_text):
                score += weight
                matched_skills.append(skill)
        
        # Apply negative keywords
        for keyword, penalty in self.negative_keywords.items():
            if self._word_match(keyword, full_text):
                score += penalty  # penalty is negative
        
        # Location bonus
        for loc in self.target_locations:
            if loc in location:
                score += 5
                break
        
        # Title relevance bonus
        title_keywords = ['data', 'machine learning', 'ml', 'ai', 'nlp', 'analyst', 'engineer', 'scientist', 'intern']
        for kw in title_keywords:
            if kw in title:
                score += 5
        
        # Ensure score is not negative
        score = max(0, score)
        
        # Normalize to percentage (cap at 100)
        percentage = min(100, int((score / self.max_score) * 100))
        
        return percentage, matched_skills
    
    def _word_match(self, keyword: str, text: str) -> bool:
        """Check if keyword exists in text (word boundary aware)"""
        # For multi-word keywords, do simple substring match
        if ' ' in keyword or '-' in keyword:
            return keyword in text
        # For single words, use word boundary
        pattern = r'\b' + re.escape(keyword) + r'\b'
        return bool(re.search(pattern, text, re.IGNORECASE))
    
    def filter_jobs_by_match(self, jobs: List[Dict], min_score: int = 40) -> List[Dict]:
        """
        Filter jobs that match at least min_score percent.
        Adds 'match_score' and 'matched_skills' to each job.
        """
        matched_jobs = []
        
        for job in jobs:
            score, skills = self.calculate_match_score(job)
            job['match_score'] = score
            job['matched_skills'] = skills
            
            if score >= min_score:
                matched_jobs.append(job)
        
        # Sort by match score (highest first)
        matched_jobs.sort(key=lambda x: x['match_score'], reverse=True)
        
        return matched_jobs
    
    def get_match_summary(self, job: Dict) -> str:
        """Get a human-readable match summary"""
        score, skills = self.calculate_match_score(job)
        
        if score >= 70:
            level = "Excellent Match"
        elif score >= 50:
            level = "Good Match"
        elif score >= 40:
            level = "Moderate Match"
        else:
            level = "Low Match"
        
        top_skills = skills[:5]
        return f"{level} ({score}%) - Matching: {', '.join(top_skills)}"
