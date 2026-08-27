"""Application preparation: drafts materials, never submits anything.

Everything generated here is built from stored profile data and the job's own
text. No skill, employer or accomplishment is invented. Sensitive questions
(authorization, demographics, legal) are always marked for user review with no
pre-filled answer.
"""

from services.matching import evaluate_job
from services.text_utils import clean_html

# Questions the system must never answer on the user's behalf.
SENSITIVE_TOPICS = {
    'work_authorization': [
        'Are you legally authorized to work in the United States?',
        'Will you now or in the future require visa sponsorship?',
    ],
    'citizenship': ['Are you a US citizen or permanent resident?'],
    'clearance': ['Do you currently hold an active security clearance?'],
    'demographics': [
        'Gender / race / ethnicity (voluntary self-identification)',
        'Veteran status',
        'Disability status',
    ],
    'legal': [
        'Have you ever been convicted of a crime?',
        'Are you subject to any non-compete agreement?',
    ],
    'compensation': ['What are your salary expectations?'],
}


def _skill_sentence(skills, limit=6):
    picked = skills[:limit]
    if not picked:
        return ''
    if len(picked) == 1:
        return picked[0]
    return ', '.join(picked[:-1]) + f' and {picked[-1]}'


def build_prep(job, profile=None, education=None, experiences=None,
               projects=None, profile_skills=None):
    """Return a review-ready application package for one job.

    All arguments are plain dicts/lists so this is unit-testable.
    """
    get = job.get if isinstance(job, dict) else lambda k, d=None: getattr(job, k, d)
    title = get('title') or 'this role'
    company = get('company') or 'the company'
    description = clean_html(get('description') or '')

    analysis = evaluate_job(job, profile_skills=profile_skills)
    matched = analysis['skills']['matched']
    missing = analysis['skills']['missing']
    duties = analysis['responsibilities']['covered']

    highest_degree = None
    school = None
    for entry in education or []:
        if entry.get('degree') in ('MS', 'PhD', 'MBA'):
            highest_degree, school = entry.get('degree'), entry.get('school')
            break
    if not highest_degree and education:
        highest_degree = education[0].get('degree')
        school = education[0].get('school')

    resume_recommendation = _resume_recommendation(analysis, matched)
    bullets = _resume_bullets(matched, duties, experiences, projects)
    summary = _professional_summary(
        title, matched, highest_degree, school, analysis,
    )
    cover_letter = _cover_letter(
        title, company, matched, duties, highest_degree, school, profile,
    )
    questions = _screening_questions(description, analysis, matched, missing)

    return {
        'job_id': get('id'),
        'resume_recommendation': resume_recommendation,
        'resume_bullets': bullets,
        'professional_summary': summary,
        'cover_letter': cover_letter,
        'screening_questions': questions,
        'highlight_skills': matched[:10],
        'gaps_to_address': missing[:6],
        'match_score': analysis['score'],
        'breakdown': analysis['breakdown'],
        'reasons': analysis['reasons'],
        'risks': analysis['risks'],
        'sponsorship': {
            'status': analysis['authorization']['status'],
            'reason': analysis['authorization']['reason'],
            'evidence': analysis['authorization']['evidence'],
        },
        'apply_url': get('application_url'),
        'apply_url_status': get('application_url_status') or 'unknown',
        'disclaimer': (
            'Drafted from your stored profile and this posting. Review every '
            'line before submitting; nothing is sent automatically.'
        ),
    }


def _resume_recommendation(analysis, matched):
    role = analysis['role']
    tier = role.get('tier')
    if tier == 1:
        variant = 'Analytics / BI resume'
        reason = 'the posting is an analytics-leaning role'
    elif tier == 2:
        variant = 'Data Engineering resume'
        reason = 'the posting is a core data-engineering role'
    elif tier == 3:
        variant = 'ML / Data Science resume'
        reason = 'the posting leans toward modelling work'
    else:
        variant = 'General Data resume'
        reason = 'the role family could not be classified confidently'
    lead = _skill_sentence(matched[:3]) or 'your strongest data skills'
    return f'Use your {variant} because {reason}. Lead with {lead}.'


def _resume_bullets(matched, duties, experiences, projects):
    """Suggest which existing bullets to surface. Never writes new claims."""
    suggestions = []
    for exp in (experiences or [])[:3]:
        used = [s for s in (exp.get('skills_used') or []) if s in matched]
        if used:
            suggestions.append({
                'source': f"{exp.get('title')} at {exp.get('company')}",
                'why': f"Overlaps with required skills: {_skill_sentence(used)}",
                'action': 'Move this entry above the fold and lead the bullet with the overlapping skill.',
            })
    for project in (projects or [])[:3]:
        stack = [s for s in (project.get('tech_stack') or []) if s in matched]
        if stack:
            suggestions.append({
                'source': project.get('name'),
                'why': f"Uses {_skill_sentence(stack)}, which this posting asks for",
                'action': 'Include this project and name the overlapping tools explicitly.',
            })
    if not suggestions:
        suggestions.append({
            'source': 'Profile experience and projects',
            'why': (
                'No stored experience or project lists the skills this posting '
                'asks for'
            ),
            'action': (
                'Add your experience and projects (with their tech stacks) in '
                'Profile so tailoring can reference real work.'
            ),
        })
    if duties:
        suggestions.append({
            'source': 'Bullet framing',
            'why': 'The posting emphasizes: ' + ', '.join(
                d.replace('_', ' ') for d in duties[:4]
            ),
            'action': 'Mirror this wording in your bullets where it is truthful.',
        })
    return suggestions


def _professional_summary(title, matched, degree, school, analysis):
    degree_part = ''
    if degree and school:
        degree_part = f'{degree} in Computer Science candidate at {school}'
    elif degree:
        degree_part = f'{degree} in Computer Science candidate'
    skill_part = _skill_sentence(matched[:5]) or 'data engineering and analytics'
    duty = (analysis['responsibilities']['covered'] or ['data pipelines'])[0]
    return (
        f'{degree_part} targeting {title}. Hands-on with {skill_part}, with '
        f'direct experience in {duty.replace("_", " ")}. '
        'Comfortable owning work end to end and validating data before it ships.'
    ).strip()


def _cover_letter(title, company, matched, duties, degree, school, profile):
    name = (profile or {}).get('name') or 'Your Name'
    skills = _skill_sentence(matched[:4]) or 'SQL, Python and ETL development'
    duty_text = ', '.join(d.replace('_', ' ') for d in duties[:3]) or 'building and validating data pipelines'
    school_line = f' as an {degree} Computer Science student at {school}' if degree and school else ''

    return (
        f'Dear {company} Hiring Team,\n\n'
        f'I am applying for the {title} position. The responsibilities you '
        f'describe — {duty_text} — line up directly with the work I do{school_line}.\n\n'
        f'My core toolset is {skills}, which matches what this role asks for. '
        f'I have built ETL pipelines end to end, written and tuned SQL against '
        f'production databases, and put validation checks in place so downstream '
        f'reporting can be trusted.\n\n'
        f'I would welcome the chance to talk about how I can contribute to your '
        f'data team.\n\n'
        f'Sincerely,\n{name}\n\n'
        '[REVIEW BEFORE SENDING: confirm every claim above matches your resume, '
        'and replace the bracketed details with specifics from your own work.]'
    )


def _screening_questions(description, analysis, matched, missing):
    """Likely questions, with suggested answers only where it is safe."""
    questions = []

    for topic, prompts in SENSITIVE_TOPICS.items():
        for prompt in prompts:
            questions.append({
                'question': prompt,
                'category': topic,
                'suggested_answer': None,
                'sensitive': True,
                'needs_review': True,
                'note': 'You must answer this yourself. No answer is pre-filled.',
            })

    skill_text = _skill_sentence(matched[:4]) or 'the tools listed in the posting'
    questions.append({
        'question': 'Why are you interested in this role?',
        'category': 'motivation',
        'suggested_answer': (
            f'The role centres on {skill_text}, which is exactly the work I want '
            'to keep doing, and the responsibilities match what I have already built.'
        ),
        'sensitive': False,
        'needs_review': True,
        'note': 'Personalize with something specific about the company.',
    })
    questions.append({
        'question': 'Describe your experience with '
                    f'{matched[0] if matched else "data pipelines"}.',
        'category': 'technical',
        'suggested_answer': (
            'Point to a specific project or role from your profile, state what '
            'you built, and name the outcome you can verify.'
        ),
        'sensitive': False,
        'needs_review': True,
        'note': 'Use a real example only.',
    })

    if missing:
        questions.append({
            'question': f'Do you have experience with {missing[0]}?',
            'category': 'technical_gap',
            'suggested_answer': (
                f'Be honest: you have not used {missing[0]} yet. Bridge to the '
                'closest tool you do know and how quickly you have picked up '
                'similar tools before.'
            ),
            'sensitive': False,
            'needs_review': True,
            'note': 'Do not claim experience you do not have.',
        })

    if analysis['experience']['required_years']:
        questions.append({
            'question': 'How many years of relevant experience do you have?',
            'category': 'experience',
            'suggested_answer': (
                'State your actual total, counting internships and co-ops, and '
                'follow with what you delivered in that time.'
            ),
            'sensitive': False,
            'needs_review': True,
            'note': 'The posting asks for '
                    f'{analysis["experience"]["required_years"]:g} years.',
        })

    return questions
