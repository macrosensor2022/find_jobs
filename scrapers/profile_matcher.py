"""
Profile Matching System + OPT Screening

Calculates skill match score, detects sponsorship dealbreakers,
and computes a separate OPT-viability score.
"""

import re
import html
import logging
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)


class ProfileMatcher:
    def __init__(self):
        from config.settings import Config
        
        self.skills = Config.PROFILE_MATCHER_SKILLS
        self.negative_keywords = Config.PROFILE_MATCHER_NEGATIVE_KEYWORDS
        self.max_score = Config.PROFILE_MATCHER_MAX_SCORE
        self.opt_field_match_min = Config.OPT_FIELD_MATCH_MIN
        
        self.sponsorship_patterns = [
            re.compile(p, re.IGNORECASE)
            for p in Config.SPONSORSHIP_SCREEN_PATTERNS
        ]
        
        self.target_locations = [
            # Primary targets (§4.1)
            'boston', 'ma', 'massachusetts',
            'portland', 'me', 'portland me', 'portland maine', 'maine',
            'new york', 'ny', 'nyc',
            # Broader US
            'new jersey', 'nj',
            'texas', 'tx', 'austin', 'dallas', 'houston',
            'colorado', 'co', 'denver', 'boulder',
            'utah', 'ut', 'salt lake', 'nevada', 'nv', 'arizona', 'az',
            'idaho', 'id', 'boise', 'montana', 'mt', 'wyoming', 'wy',
            'new mexico', 'nm', 'albuquerque', 'kansas', 'ks', 'nebraska', 'ne',
            'iowa', 'ia', 'arkansas', 'ar', 'oklahoma', 'ok', 'missouri', 'mo',
            'kentucky', 'ky', 'tennessee', 'tn', 'nashville', 'alabama', 'al',
            'south carolina', 'sc', 'north dakota', 'nd', 'south dakota', 'sd',
            'wisconsin', 'wi', 'madison', 'minnesota', 'mn', 'minneapolis',
            'indiana', 'in', 'indianapolis', 'ohio', 'oh', 'columbus', 'cleveland',
            'michigan', 'mi', 'detroit', 'ann arbor', 'pennsylvania', 'pa', 'pittsburgh',
            'vermont', 'vt', 'new hampshire', 'nh',
            'california', 'ca', 'san francisco', 'los angeles',
            'seattle', 'wa', 'chicago', 'il', 'atlanta', 'ga', 'miami', 'fl',
            # Remote
            'remote', 'hybrid', 'anywhere', 'work from home', 'wfh',
        ]
        
        logger.debug(f"ProfileMatcher initialized with {len(self.skills)} skills")
    
    # ------------------------------------------------------------------
    # HTML cleaning
    # ------------------------------------------------------------------

    def _clean_html(self, text: str) -> str:
        """Remove HTML tags and decode entities."""
        if not text:
            return ''
        clean = re.sub(r'<[^>]+>', ' ', text)
        clean = html.unescape(clean)
        clean = re.sub(r'\s+', ' ', clean)
        return clean.strip()
    
    # ------------------------------------------------------------------
    # Skill match score (existing, unchanged contract)
    # ------------------------------------------------------------------

    def calculate_match_score(self, job: Dict) -> Tuple[int, List[str]]:
        """Calculate match score for a job posting.
        Returns (score_percentage, matched_skills).
        """
        title = (job.get('title') or '').lower()
        description = (job.get('description') or '').lower()
        location = (job.get('location') or '').lower()
        company = (job.get('company') or '').lower()
        
        description = self._clean_html(description)
        full_text = f"{title} {description} {company}"
        
        score = 0
        matched_skills = []
        
        for skill, weight in self.skills.items():
            if self._word_match(skill, full_text):
                score += weight
                matched_skills.append(skill)
        
        for keyword, penalty in self.negative_keywords.items():
            if self._word_match(keyword, full_text):
                score += penalty  # penalty is negative
        
        for loc in self.target_locations:
            if loc in location:
                score += 5
                break
        
        title_keywords = [
            'data', 'machine learning', 'ml', 'ai', 'nlp',
            'analyst', 'engineer', 'scientist', 'bi',
            'business intelligence', 'etl', 'analytics', 'warehouse',
        ]
        for kw in title_keywords:
            if kw in title:
                score += 5
        
        score = max(0, score)
        percentage = min(100, int((score / self.max_score) * 100))
        
        return percentage, matched_skills
    
    def _word_match(self, keyword: str, text: str) -> bool:
        """Check if keyword exists in text (word boundary aware)."""
        if ' ' in keyword or '-' in keyword:
            return keyword in text
        pattern = r'\b' + re.escape(keyword) + r'\b'
        return bool(re.search(pattern, text, re.IGNORECASE))
    
    # ------------------------------------------------------------------
    # Sponsorship screen detection (§5.4)
    # ------------------------------------------------------------------

    def detect_sponsorship_screen(self, title: str, description: str) -> bool:
        """Return True if the posting screens out visa-sponsored candidates.

        Matches SPONSORSHIP_SCREEN_PATTERNS against title + description.
        """
        text = f"{(title or '').lower()} {self._clean_html((description or '').lower())}"
        for pattern in self.sponsorship_patterns:
            if pattern.search(text):
                return True
        return False
    
    # ------------------------------------------------------------------
    # OPT fit score (§5.4)
    # ------------------------------------------------------------------

    @staticmethod
    def compute_opt_fit_score(match_score, is_everify, sponsorship_screen, opt_field_related):
        """Compute composite OPT-viability score (0–100).

        Separate from match_score so the UI can show skill match
        and OPT viability independently.

        Formula:
            start at match_score
            +15 if is_everify
            +5  if opt_field_related
            cap at <=20 if sponsorship_screen (dealbreaker)

        H-1B data (lca_count, wage_level) intentionally excluded —
        background info only, never gates.
        """
        score = match_score or 0

        if is_everify:
            score += 15

        if opt_field_related:
            score += 5

        if sponsorship_screen:
            score = min(score, 20)

        return max(0, min(100, score))
    
    # ------------------------------------------------------------------
    # Filter & summary (existing, unchanged contract)
    # ------------------------------------------------------------------

    def filter_jobs_by_match(self, jobs: List[Dict], min_score: int = 40) -> List[Dict]:
        """Filter jobs that match at least min_score percent.
        Adds 'match_score' and 'matched_skills' to each job.
        """
        matched_jobs = []
        
        for job in jobs:
            score, skills = self.calculate_match_score(job)
            job['match_score'] = score
            job['matched_skills'] = skills
            
            if score >= min_score:
                matched_jobs.append(job)
        
        matched_jobs.sort(key=lambda x: x['match_score'], reverse=True)
        return matched_jobs
    
    def get_match_summary(self, job: Dict) -> str:
        """Get a human-readable match summary."""
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
