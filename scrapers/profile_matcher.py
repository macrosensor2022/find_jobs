"""
Profile Matching System
Calculates match score between job postings and user profile
"""

import re
import html
import logging
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)


class ProfileMatcher:
    def __init__(self):
        from config.settings import Config
        
        # Load skills from configuration (can be overridden via environment)
        self.skills = Config.PROFILE_MATCHER_SKILLS
        self.negative_keywords = Config.PROFILE_MATCHER_NEGATIVE_KEYWORDS
        self.max_score = Config.PROFILE_MATCHER_MAX_SCORE
        
        # Target locations - also configurable via settings if needed
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
        
        logger.debug(f"ProfileMatcher initialized with {len(self.skills)} skills")
    
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
