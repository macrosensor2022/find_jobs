"""Text normalization helpers shared by the scoring services."""

import re
import html as _html

_TAG_RE = re.compile(r'<[^>]+>')
_WS_RE = re.compile(r'\s+')
_SENTENCE_SPLIT_RE = re.compile(r'(?<=[.!?;])\s+|\n+|(?:^|\s)[\u2022\-\*]\s+')


def clean_html(text):
    """Strip tags and entities, collapse whitespace."""
    if not text:
        return ''
    out = _TAG_RE.sub(' ', str(text))
    out = _html.unescape(out)
    return _WS_RE.sub(' ', out).strip()


def normalize(text):
    """Lowercase, de-tagged, whitespace-collapsed text for matching."""
    return clean_html(text).lower()


def sentences(text, min_len=12, max_len=400):
    """Split description text into sentence-ish chunks usable as evidence."""
    cleaned = clean_html(text)
    if not cleaned:
        return []
    parts = _SENTENCE_SPLIT_RE.split(cleaned)
    out = []
    for part in parts:
        if not part:
            continue
        part = part.strip(' \t-*\u2022')
        if min_len <= len(part) <= max_len:
            out.append(part)
        elif len(part) > max_len:
            out.append(part[:max_len].rsplit(' ', 1)[0] + '...')
    return out


def find_evidence(text, pattern):
    """Return the sentence containing the first regex match, or None.

    Used so every classification can quote its own source text rather than
    asserting a conclusion without proof.
    """
    if not text:
        return None
    for sentence in sentences(text):
        if re.search(pattern, sentence, re.I):
            return sentence
    match = re.search(pattern, clean_html(text), re.I)
    if match:
        full = clean_html(text)
        start = max(0, match.start() - 90)
        end = min(len(full), match.end() + 90)
        return full[start:end].strip()
    return None


def word_present(term, text):
    """Whole-word/phrase presence test that avoids substring false positives.

    'ssis' must not match 'assistant'; 'r' must not match every word with r.
    """
    if not term or not text:
        return False
    term_l = term.lower()
    # Tolerate a trailing plural on the last token ("data pipeline" must match
    # "data pipelines") without loosening short/ambiguous terms like "r".
    plural = r's?' if len(term_l) >= 4 and term_l[-1].isalpha() and term_l[-1] != 's' else ''
    if re.search(r'[^a-z0-9]', term_l):
        # Multi-token or punctuated term (c++, power bi, ci/cd): match loosely
        # but anchor the start/end on non-alphanumeric boundaries.
        escaped = re.escape(term_l).replace(r'\ ', r'[\s\-_/]+')
        pattern = rf'(?<![a-z0-9]){escaped}{plural}(?![a-z0-9])'
    else:
        pattern = rf'(?<![a-z0-9]){re.escape(term_l)}{plural}(?![a-z0-9])'
    return bool(re.search(pattern, text, re.I))


def tokens(text):
    return [t for t in re.split(r'[^a-z0-9+#]+', (text or '').lower()) if t]
