"""Outreach preparation (V3 Parts 14-16).

Builds a personalized, review-ready outreach message from stored profile +
job + contact information. It NEVER sends anything and never fabricates
experience. The user must manually approve, copy, and send.

Channels: EMAIL / LINKEDIN / COMPANY_CONTACT_FORM / UNKNOWN.
"""

from config.settings import Config
from services.text_utils import clean_html


def _skill_sentence(skills, limit=4):
    picked = [s for s in skills if s][:limit]
    if not picked:
        return ''
    if len(picked) == 1:
        return picked[0]
    return ', '.join(picked[:-1]) + f' and {picked[-1]}'


def recommended_channel(contact):
    """Choose an outreach channel from evidence, in priority order."""
    email_state = (contact or {}).get('email_state') or 'NOT_FOUND'
    linkedin = (contact or {}).get('linkedin_url')
    if email_state == 'VERIFIED_PUBLIC' and (contact or {}).get('email'):
        return 'EMAIL'
    if email_state in ('PUBLIC_UNVERIFIED',) and (contact or {}).get('email'):
        return 'EMAIL'
    if linkedin:
        return 'LINKEDIN'
    if email_state == 'PATTERN_INFERRED' and (contact or {}).get('email'):
        return 'EMAIL'  # pattern-inferred is still usable as a channel, but never labelled verified
    return 'UNKNOWN'


def build_outreach(job, contact=None, profile=None, education=None,
                   experiences=None, projects=None, profile_skills=None,
                   matched_skills=None, duties=None):
    """Build a personalized outreach message.

    All inputs are plain dicts/lists so this is unit-testable. Every claim is
    drawn from the user's stored profile + the job's own text; nothing is
    fabricated. Returns an object with a recommended channel and both an email
    and a LinkedIn draft the user can review/copy.
    """
    get = job.get if isinstance(job, dict) else lambda k, d=None: getattr(job, k, d)
    contact = contact or {}
    title = get('title') or 'the role'
    company = get('company') or 'your team'
    contact_name = (contact.get('contact_name') or '').strip()
    contact_role = (contact.get('contact_role') or '').strip()
    if contact_name:
        greeting = f'Hi {contact_name},'
    else:
        greeting = f'Hello {company} team,'

    name = (profile or {}).get('name') or 'Your Name'
    degree = school = None
    for entry in education or []:
        if entry.get('degree') in ('MS', 'PhD', 'MBA'):
            degree, school = entry.get('degree'), entry.get('school')
            break
    if not degree and education:
        degree, school = education[0].get('degree'), education[0].get('school')

    skills = _skill_sentence(matched_skills or [])
    duty = (duties or ['building and validating data pipelines'])[0]

    intro = f"I'm {name.split()[-1] if name else 'a data professional'} applying for the {title} role at {company}."
    channel = recommended_channel(contact)

    why_role = (
        f'The role caught my attention because it centers on {duty}, '
        f'which is the work I most want to keep doing.'
    )
    why_relevant = f'My day-to-day toolkit is {skills}.' if skills else \
        'My work centers on SQL, Python, and building reliable data pipelines.'
    experience_line = _concrete_experience(experiences, projects, matched_skills)

    body_parts = [intro, why_role, why_relevant]
    if experience_line:
        body_parts.append(experience_line)
    body_parts.append(_request_line(contact_role, channel))

    email_body = (
        f'{greeting}\n\n'
        + '\n\n'.join(body_parts)
        + '\n\nSincerely,\n'
        + f'{name}'
    )

    linkedin_body = None
    if channel in ('LINKEDIN', 'EMAIL'):
        linkedin_body = (
            (f'Hi {contact_name},' if contact_name else f'Hello {company} team,') + '\n\n'
            + f'I am applying for the {title} role at {company}. {experience_line or why_relevant} '
            f'Would love to chat about the team and how I could contribute.\n'
            f'- {name}'
        )

    return {
        'job_id': get('id'),
        'contact_name': contact_name,
        'contact_role': contact_role,
        'contact_type': contact.get('contact_type'),
        'channel': channel,
        'email': email_body,
        'linkedin_message': linkedin_body,
        'message_draft': email_body if channel == 'EMAIL' else (linkedin_body or email_body),
        'matched_skills': (matched_skills or [])[:10],
        'duties': (duties or [])[:5],
        'evidence': contact.get('evidence') or [],
        'disclaimer': (
            'Drafted from your stored profile and this posting. Review and '
            'personalize before sending. Nothing is sent automatically.'
        ),
        'no_auto_send': True,
    }


def _concrete_experience(experiences, projects, matched_skills=None, limit=2):
    """The one or two concrete matching experiences, from real profile data."""
    lines = []
    matched = set(matched_skills or [])
    for exp in (experiences or [])[:limit]:
        used = [s for s in (exp.get('skills_used') or []) if matched]
        if used:
            lines.append(
                f'In my {exp.get("title") or "role"} at {exp.get("company") or "a past employer"}, '
                f'I worked hands-on with {_skill_sentence(used)}.'
            )
    for proj in (projects or [])[:limit]:
        stack = [s for s in (proj.get('tech_stack') or []) if matched]
        if stack:
            lines.append(
                f'On {proj.get("name") or "a project"}, I used {_skill_sentence(stack)} '
                'to deliver a working result.'
            )
    if not lines:
        lines.append(
            'I have built and maintained data pipelines end to end with SQL and Python, '
            'including validation so reports stay trustworthy.'
        )
    return '\n'.join(lines[:limit])


def _request_line(contact_role, channel):
    if contact_role:
        return f'As {contact_role}, you would know if this is a fit — I would welcome a conversation.'
    return 'I would welcome a conversation about the team and this role.'