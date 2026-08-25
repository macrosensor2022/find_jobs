"""
Profile Matching System + OPT Screening + Experience Gate

Calculates skill match score, detects sponsorship dealbreakers,
experience-level hard drops / soft penalties, and OPT-viability score.
"""

import re
import html
import logging
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# Title seniority — hard drop when present in the job TITLE
_SENIOR_TITLE_RE = re.compile(
    r'\b(senior|sr\.?|staff|principal|lead|manager|director|vp|head\s+of)\b',
    re.I,
)

# Early-career boost signals (title or description)
_EARLY_CAREER_RE = re.compile(
    r'\b(new\s*grad(?:uate)?|university\s*grad(?:uate)?|college\s*grad(?:uate)?|'
    r'early[\s\-]?career|entry[\s\-]?level|junior|associate|'
    r'co[\s\-]?op|intern(?:ship)?|grad(?:uate)?\s+program|'
    r'0[\s\-–to]+1\s*years?|0[\s\-–to]+2\s*years?)\b',
    re.I,
)

# Years-required patterns (description + title)
_YEARS_RANGE_RE = re.compile(
    r'(\d+)\s*[-–—]\s*(\d+)\s*\+?\s*years?',
    re.I,
)
_YEARS_TO_RE = re.compile(
    r'(\d+)\s+to\s+(\d+)\s*\+?\s*years?',
    re.I,
)
_YEARS_PLUS_RE = re.compile(
    r'(\d+)\s*\+\s*years?',
    re.I,
)
_MIN_YEARS_RE = re.compile(
    r'(?:minimum|min\.?|at\s+least|requires?|must\s+have)\s+(\d+)\s*\+?\s*years?',
    re.I,
)
_YEARS_EXP_RE = re.compile(
    r'(\d+)\s*\+?\s*years?\s+(?:of\s+)?(?:professional\s+)?(?:relevant\s+)?'
    r'(?:experience|exp\.?)',
    re.I,
)
_YEARS_PREFERRED_RE = re.compile(
    r'(\d+)\s*\+?\s*years?\s+(?:of\s+experience\s+)?(?:preferred|a\s+plus|nice\s+to\s+have)',
    re.I,
)


class ProfileMatcher:
    def __init__(self):
        from config.settings import Config
        
        self.skills = Config.PROFILE_MATCHER_SKILLS
        self.negative_keywords = Config.PROFILE_MATCHER_NEGATIVE_KEYWORDS
        self.max_score = Config.PROFILE_MATCHER_MAX_SCORE
        self.opt_field_match_min = Config.OPT_FIELD_MATCH_MIN

        self.exp_years = float(getattr(Config, 'EXP_YEARS', 0.75))
        self.exp_hard_drop_years = float(getattr(Config, 'EXP_HARD_DROP_YEARS', 3))
        self.exp_soft_penalty = int(getattr(Config, 'EXP_SOFT_PENALTY', 12))
        self.exp_early_boost = int(getattr(Config, 'EXP_EARLY_CAREER_BOOST', 15))
        
        self.sponsorship_patterns = [
            re.compile(p, re.IGNORECASE)
            for p in Config.SPONSORSHIP_SCREEN_PATTERNS
        ]
        
        self.target_locations = [
            'boston', 'ma', 'massachusetts',
            'portland', 'me', 'portland me', 'portland maine', 'maine',
            'new york', 'ny', 'nyc',
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
            'connecticut', 'ct', 'hartford',
            'california', 'ca', 'san francisco', 'los angeles',
            'seattle', 'wa', 'chicago', 'il', 'atlanta', 'ga', 'miami', 'fl',
            'remote', 'hybrid', 'anywhere', 'work from home', 'wfh',
        ]
        
        logger.debug(f"ProfileMatcher initialized with {len(self.skills)} skills")
    
    def _clean_html(self, text: str) -> str:
        if not text:
            return ''
        clean = re.sub(r'<[^>]+>', ' ', text)
        clean = html.unescape(clean)
        clean = re.sub(r'\s+', ' ', clean)
        return clean.strip()

    def parse_required_years(self, title: str, description: str) -> Dict:
        """Extract required/preferred years and early-career / senior signals."""
        title_l = (title or '').strip()
        desc = self._clean_html(description or '')
        text = f"{title_l} {desc}"

        is_senior_title = bool(_SENIOR_TITLE_RE.search(title_l))
        is_early = bool(_EARLY_CAREER_RE.search(text))

        required: Optional[float] = None
        preferred: Optional[float] = None

        for m in _YEARS_PREFERRED_RE.finditer(text):
            y = float(m.group(1))
            preferred = y if preferred is None else min(preferred, y)

        for pat in (_YEARS_RANGE_RE, _YEARS_TO_RE):
            for m in pat.finditer(text):
                lo = float(m.group(1))
                required = lo if required is None else min(required, lo)

        for m in _MIN_YEARS_RE.finditer(text):
            y = float(m.group(1))
            required = y if required is None else min(required, y)

        for m in _YEARS_PLUS_RE.finditer(text):
            y = float(m.group(1))
            required = y if required is None else min(required, y)

        for m in _YEARS_EXP_RE.finditer(text):
            y = float(m.group(1))
            span_start = max(0, m.start() - 20)
            window = text[span_start:m.end() + 20].lower()
            if 'preferred' in window or 'a plus' in window or 'nice to have' in window:
                preferred = y if preferred is None else min(preferred, y)
                continue
            required = y if required is None else min(required, y)

        if is_early and required is None:
            required = 0.0

        hard_drop = bool(
            is_senior_title
            or (required is not None and required >= self.exp_hard_drop_years)
        )

        soft = False
        if not hard_drop:
            if required is not None and required > self.exp_years and required < self.exp_hard_drop_years:
                soft = True
            if preferred is not None and preferred > self.exp_years and preferred < self.exp_hard_drop_years:
                soft = True

        boost = bool(
            is_early and not hard_drop and (
                required is None
                or required <= 1.0
                or bool(re.search(
                    r'\b(new\s*grad|university\s+grad|early[\s\-]?career|entry[\s\-]?level|junior|associate)\b',
                    text, re.I,
                ))
            )
        )

        # Full-time new-grad mode: hard-drop internship / co-op roles
        from config.settings import Config
        if getattr(Config, 'SEEKING_FULL_TIME_NEW_GRAD', True):
            if re.search(
                r'\b(intern(?:ship)?|co[\s\-]?op|coop)\b',
                title_l,
                re.I,
            ):
                hard_drop = True
                boost = False

        return {
            'required_years': required,
            'preferred_years': preferred,
            'is_senior_title': is_senior_title,
            'is_early_career': is_early,
            'hard_drop': hard_drop,
            'soft_penalty': soft,
            'boost': boost,
        }

    def evaluate_experience(self, job: Dict) -> Dict:
        return self.parse_required_years(job.get('title') or '', job.get('description') or '')

    def calculate_match_score(self, job: Dict) -> Tuple[int, List[str]]:
        """Calculate match score. Hard-dropped roles return 0."""
        title = (job.get('title') or '').lower()
        description = (job.get('description') or '').lower()
        location = (job.get('location') or '').lower()
        company = (job.get('company') or '').lower()

        exp = self.evaluate_experience(job)
        job['required_years'] = exp['required_years']
        job['exp_hard_drop'] = exp['hard_drop']
        job['exp_soft_penalty'] = exp['soft_penalty']
        job['exp_boost'] = exp['boost']

        if exp['hard_drop']:
            return 0, ['exp_hard_drop']
        
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
                score += penalty
        
        for loc in self.target_locations:
            if loc in location:
                score += 5
                break
        
        title_keywords = [
            'data', 'machine learning', 'ml', 'ai', 'nlp',
            'analyst', 'engineer', 'scientist', 'bi',
            'business intelligence', 'etl', 'analytics', 'warehouse',
            'power bi', 'new grad', 'university grad', 'junior', 'associate',
            'entry level', 'early career',
        ]
        for kw in title_keywords:
            if kw in title:
                score += 5

        title_role_boosts = [
            ('data engineer', 25),
            ('analytics engineer', 22),
            ('bi engineer', 22),
            ('business intelligence', 20),
            ('etl', 18),
            ('data analyst', 18),
            ('data scientist', 18),
            ('machine learning', 16),
            ('nlp', 16),
            ('power bi', 16),
        ]
        if len(description) < 80:
            for phrase, boost in title_role_boosts:
                if phrase in title:
                    score += boost
                    if phrase not in matched_skills:
                        matched_skills.append(f'title:{phrase}')
                    break

        score = max(0, score)
        percentage = min(100, int((score / self.max_score) * 100))

        if exp['soft_penalty']:
            percentage = max(0, percentage - self.exp_soft_penalty)
            matched_skills.append('exp_soft_penalty')

        if exp['boost']:
            percentage = min(100, percentage + self.exp_early_boost)
            matched_skills.append('exp_early_boost')
        
        return percentage, matched_skills
    
    def _word_match(self, keyword: str, text: str) -> bool:
        if ' ' in keyword or '-' in keyword:
            return keyword in text
        pattern = r'\b' + re.escape(keyword) + r'\b'
        return bool(re.search(pattern, text, re.IGNORECASE))

    def detect_sponsorship_screen(self, title: str, description: str) -> bool:
        text = f"{(title or '').lower()} {self._clean_html((description or '').lower())}"
        for pattern in self.sponsorship_patterns:
            if pattern.search(text):
                return True
        return False

    @staticmethod
    def compute_opt_fit_score(match_score, is_everify, sponsorship_screen, opt_field_related):
        score = match_score or 0
        if is_everify:
            score += 15
        if opt_field_related:
            score += 5
        if sponsorship_screen:
            score = min(score, 20)
        return max(0, min(100, score))

    def filter_jobs_by_match(self, jobs: List[Dict], min_score: int = 40) -> List[Dict]:
        """Filter by min_score. Hard-drop senior / >=3yr regardless of skills."""
        matched_jobs = []
        
        for job in jobs:
            score, skills = self.calculate_match_score(job)
            job['match_score'] = score
            job['matched_skills'] = skills

            if job.get('exp_hard_drop'):
                continue
            
            if score >= min_score:
                matched_jobs.append(job)
        
        matched_jobs.sort(
            key=lambda x: (
                x['match_score'],
                0 if x.get('exp_soft_penalty') else 1,
                1 if x.get('exp_boost') else 0,
            ),
            reverse=True,
        )
        return matched_jobs
    
    def get_match_summary(self, job: Dict) -> str:
        score, skills = self.calculate_match_score(job)
        
        if job.get('exp_hard_drop'):
            return "Hard Drop (0%) — experience/seniority gate"
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
