"""
Document upload, parsing, and AI classification for AIOS.
Supports PDF, DOCX, CSV, TXT.  Classifies into tenant-relevant categories.
All document content stored encrypted (encryption.py).
"""
import io
import os
import csv
import logging
import re
from typing import Optional

log = logging.getLogger(__name__)

try:
    import pypdf
    _HAS_PDF = True
except ImportError:
    _HAS_PDF = False
    log.warning('[DocProcessor] pypdf not installed — PDF text extraction unavailable')

try:
    from docx import Document as _DocxDoc
    _HAS_DOCX = True
except ImportError:
    _HAS_DOCX = False
    log.warning('[DocProcessor] python-docx not installed — DOCX extraction unavailable')

ALLOWED_EXTENSIONS = {
    'pdf', 'docx', 'doc', 'txt', 'csv', 'xlsx', 'xls', 'msg', 'eml'
}
MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MB

# ── Per-industry classification keywords ──────────────────────────────────────
_CLASSIFIERS: dict[str, dict[str, list[str]]] = {
    'agency': {
        'Proposal':       ['proposal', 'scope of work', 'sow', 'pricing', 'quote', 'estimate'],
        'Contract':       ['agreement', 'contract', 'terms', 'service agreement', 'msa'],
        'ROI Report':     ['roi', 'return on investment', 'revenue impact', 'savings'],
        'Client Report':  ['monthly report', 'performance', 'kpi', 'metrics', 'dashboard'],
        'Invoice':        ['invoice', 'billing', 'payment due', 'amount owed'],
        'Onboarding':     ['onboard', 'welcome', 'setup', 'access', 'credentials'],
    },
    'legal': {
        'Motion/Brief':   ['motion', 'brief', 'memorandum', 'opposition', 'reply'],
        'Contract':       ['agreement', 'contract', 'terms', 'clause', 'indemnification'],
        'Discovery':      ['interrogatories', 'deposition', 'discovery', 'subpoena', 'exhibit'],
        'Correspondence': ['dear counsel', 'letter', 'notice', 'correspondence'],
        'Court Filing':   ['court', 'filing', 'docket', 'case no', 'plaintiff', 'defendant'],
        'Invoice/Billing':['invoice', 'billing', 'retainer', 'billable', 'time entry'],
    },
    'construction': {
        'RFI':            ['request for information', 'rfi', 'clarification'],
        'Change Order':   ['change order', 'co-', 'scope change', 'modification'],
        'Contract':       ['subcontract', 'prime contract', 'agreement', 'bond'],
        'Permit':         ['permit', 'inspection', 'certificate of occupancy', 'zoning'],
        'Schedule':       ['schedule', 'gantt', 'milestone', 'baseline', 'critical path'],
        'Safety':         ['safety', 'incident', 'osha', 'toolbox', 'hazard', 'ppe'],
        'Submittal':      ['submittal', 'shop drawing', 'material approval', 'specification'],
        'Invoice/Pay App':['pay application', 'invoice', 'billing', 'lien waiver', 'draw'],
    },
    'medical': {
        'Prior Auth':     ['prior authorization', 'prior auth', 'preauthorization', 'medical necessity'],
        'Claim/EOB':      ['claim', 'eob', 'explanation of benefits', 'remittance', 'denial'],
        'Clinical Notes': ['soap', 'progress note', 'assessment', 'diagnosis', 'icd-'],
        'Insurance':      ['insurance', 'payer', 'coverage', 'eligibility', 'copay', 'deductible'],
        'Compliance':     ['hipaa', 'compliance', 'audit', 'credential', 'cms', 'regulation'],
        'Patient Record': ['patient', 'medical record', 'history', 'medication', 'lab result'],
        'Contract':       ['contract', 'agreement', 'payer contract', 'fee schedule'],
    },
    'brokerage': {
        'Listing Agreement':  ['listing agreement', 'exclusive right', 'mls', 'commission'],
        'Purchase Contract':  ['purchase agreement', 'offer to purchase', 'contract of sale'],
        'Disclosure':         ['disclosure', 'seller disclosure', 'property condition'],
        'Inspection Report':  ['inspection', 'inspector', 'deficiency', 'repair'],
        'Appraisal':          ['appraisal', 'appraiser', 'market value', 'comparable'],
        'Title/Closing':      ['title', 'closing', 'hud-1', 'settlement statement', 'deed'],
        'Compliance':         ['nar', 'fair housing', 'regulation', 'compliance', 'license'],
        'Market Report':      ['market report', 'market analysis', 'cma', 'median price'],
    },
}

_DEFAULT_CATEGORIES = {
    'Contract', 'Invoice', 'Report', 'Correspondence', 'Other'
}


def allowed_file(filename: str) -> bool:
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def extract_text(file_bytes: bytes, filename: str) -> str:
    """Extract plain text from uploaded file bytes."""
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    text = ''

    if ext == 'pdf' and _HAS_PDF:
        try:
            reader = pypdf.PdfReader(io.BytesIO(file_bytes))
            parts  = []
            for page in reader.pages[:50]:  # cap at 50 pages
                try:
                    parts.append(page.extract_text() or '')
                except Exception:
                    pass
            text = '\n'.join(parts)
        except Exception as exc:
            log.warning('[DocProcessor] PDF extraction failed: %s', exc)
            text = ''

    elif ext in ('docx', 'doc') and _HAS_DOCX:
        try:
            doc   = _DocxDoc(io.BytesIO(file_bytes))
            parts = [p.text for p in doc.paragraphs if p.text.strip()]
            text  = '\n'.join(parts)
        except Exception as exc:
            log.warning('[DocProcessor] DOCX extraction failed: %s', exc)
            text = ''

    elif ext == 'csv':
        try:
            decoded = file_bytes.decode('utf-8', errors='replace')
            reader  = csv.reader(io.StringIO(decoded))
            rows    = [', '.join(row) for row in reader]
            text    = '\n'.join(rows[:200])  # cap rows
        except Exception as exc:
            log.warning('[DocProcessor] CSV extraction failed: %s', exc)
            text = ''

    elif ext in ('txt', 'eml', 'msg'):
        try:
            text = file_bytes.decode('utf-8', errors='replace')
        except Exception:
            text = ''

    return text[:50_000]  # cap at 50k chars for processing


def classify(text: str, industry: str) -> tuple[str, float]:
    """
    Keyword-based classification.
    Returns (category_name, confidence_0_to_1).
    Falls back to Claude API if ANTHROPIC_API_KEY is set and confidence is low.
    """
    if not text.strip():
        return 'Other', 0.0

    lower   = text.lower()
    cats    = _CLASSIFIERS.get(industry, {})
    scores: dict[str, int] = {}

    for cat, keywords in cats.items():
        hits = sum(1 for kw in keywords if kw in lower)
        if hits:
            scores[cat] = hits

    if not scores:
        return 'Other', 0.1

    best_cat   = max(scores, key=lambda c: scores[c])
    total_kws  = len(cats.get(best_cat, []))
    confidence = min(scores[best_cat] / max(total_kws, 1), 1.0)

    # Try Claude if confidence is low and API key present
    if confidence < 0.4 and os.getenv('ANTHROPIC_API_KEY'):
        ai_cat = _ai_classify(text[:3000], industry, list(cats.keys()))
        if ai_cat:
            return ai_cat, 0.85

    return best_cat, confidence


def _ai_classify(snippet: str, industry: str, categories: list[str]) -> Optional[str]:
    try:
        import anthropic
        client = anthropic.Anthropic()
        cats   = ', '.join(categories)
        msg = client.messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=50,
            messages=[{
                'role': 'user',
                'content': (
                    f'You are classifying a document for a {industry} business. '
                    f'Available categories: {cats}. '
                    f'Reply with ONLY the single best category name, nothing else.\n\n'
                    f'Document excerpt:\n{snippet}'
                )
            }]
        )
        result = msg.content[0].text.strip()
        # Validate the AI response is one of the allowed categories
        for cat in categories:
            if cat.lower() in result.lower():
                return cat
        return None
    except Exception as exc:
        log.warning('[DocProcessor] AI classify failed: %s', exc)
        return None


def summarize(text: str, max_chars: int = 300) -> str:
    """Return a plain-text summary (first meaningful sentences up to max_chars)."""
    if not text.strip():
        return ''
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    summary   = ''
    for s in sentences:
        s = s.strip()
        if len(s) < 10:
            continue
        if len(summary) + len(s) > max_chars:
            break
        summary += s + ' '
    return summary.strip() or text[:max_chars]


def process_upload(file_bytes: bytes, filename: str,
                   tenant_id: str, industry: str, uploader_email: str) -> dict:
    """
    Full pipeline: extract → classify → summarize → encrypt → store.
    Returns a dict with document metadata for the caller to persist.
    """
    from encryption import encrypt_str

    text           = extract_text(file_bytes, filename)
    category, conf = classify(text, industry)
    summary        = summarize(text)
    encrypted_blob = encrypt_str(tenant_id, text or filename)
    summary_enc    = encrypt_str(tenant_id, summary) if summary else ''

    return {
        'filename':       filename,
        'content_type':   _mime(filename),
        'encrypted_blob': encrypted_blob,
        'size_bytes':     len(file_bytes),
        'classification': category,
        'confidence':     round(conf, 2),
        'summary_enc':    summary_enc,
        'summary':        summary,   # plaintext — caller should NOT persist this
        'uploaded_by':    uploader_email,
        'status':         'pending',
    }


def _mime(filename: str) -> str:
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    return {
        'pdf': 'application/pdf',
        'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'doc':  'application/msword',
        'csv':  'text/csv',
        'txt':  'text/plain',
        'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    }.get(ext, 'application/octet-stream')
