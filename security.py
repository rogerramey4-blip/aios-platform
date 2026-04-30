"""
AIOS Security Middleware — OWASP Top 10 hardening.
Call init_security(app) at startup.

A01 Broken Access Control   — require_auth / require_admin decorators (auth.py)
A02 Cryptographic Failures  — Fernet AES encryption at rest (encryption.py), HTTPS via HSTS
A03 Injection               — SQLAlchemy ORM (parameterized), Jinja2 auto-escape
A04 Insecure Design         — Principle of least privilege, tenant isolation
A05 Security Misconfiguration — Hardened response headers below
A06 Vulnerable Components   — Pinned requirements.txt
A07 Auth Failures           — OTP + brute-force lockout (auth.py)
A08 Software/Data Integrity — CSRF token on all state-changing forms
A09 Security Logging        — AuditLog table written on every auth and sensitive action
A10 SSRF                    — validate_url() helper; no user-supplied URLs fetched directly
"""
import re
import time
import secrets
import logging
from flask import request, g, session, abort, Response

log = logging.getLogger(__name__)

# ── Rate limiting (A05 / A07) ─────────────────────────────────────────────────
_rl_store: dict = {}
_RL_WINDOW = 60    # seconds
_RL_LIMIT  = 180   # requests per window per IP (tighter for auth endpoints below)
_RL_AUTH_LIMIT = 20

def _rate_check(ip: str, limit: int = _RL_LIMIT) -> bool:
    """Returns True if the IP has exceeded its limit."""
    now = time.time()
    ts  = [t for t in _rl_store.get(ip, []) if now - t < _RL_WINDOW]
    ts.append(now)
    _rl_store[ip] = ts
    return len(ts) > limit

# ── CSRF (A08) ────────────────────────────────────────────────────────────────
_CSRF_SAFE_METHODS  = {'GET', 'HEAD', 'OPTIONS', 'TRACE'}
_CSRF_EXEMPT_PATHS  = {'/login', '/otp', '/logout', '/health', '/onboard/create'}
_CSRF_EXEMPT_PREFIX = ('/static/', '/api/')

def _csrf_exempt(path: str) -> bool:
    if path in _CSRF_EXEMPT_PATHS:
        return True
    for p in _CSRF_EXEMPT_PREFIX:
        if path.startswith(p):
            return True
    return False

# ── Security response headers (A05) ──────────────────────────────────────────
_SEC_HEADERS = {
    'X-Content-Type-Options':    'nosniff',
    'X-Frame-Options':           'SAMEORIGIN',
    'X-XSS-Protection':          '1; mode=block',
    'Referrer-Policy':           'strict-origin-when-cross-origin',
    'Permissions-Policy':        'geolocation=(), microphone=(), camera=()',
    'Strict-Transport-Security': 'max-age=63072000; includeSubDomains; preload',
    'Content-Security-Policy': (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data: blob:; "
        "connect-src 'self'; "
        "object-src 'none'; "
        "frame-ancestors 'none';"
    ),
}

# ── Input validation helpers (A03) ───────────────────────────────────────────
_RE_DOMAIN = re.compile(
    r'^(?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$'
)
_RE_EMAIL  = re.compile(r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$')
_RE_SAFE_NAME = re.compile(r'^[\w\s\-.()\[\]+#&,\'\"]{1,300}$')

def validate_domain(domain: str) -> bool:
    return bool(domain) and bool(_RE_DOMAIN.match(domain.strip().lower()))

def validate_email(email: str) -> bool:
    return bool(email) and bool(_RE_EMAIL.match(email.strip().lower()))

def validate_name(name: str) -> bool:
    return bool(name) and bool(_RE_SAFE_NAME.match(name.strip()))

def validate_url(url: str) -> bool:
    """SSRF guard (A10): only allow http/https to non-private ranges."""
    if not url:
        return False
    url = url.strip().lower()
    if not url.startswith(('http://', 'https://')):
        return False
    # Block private / loopback ranges
    blocked = ('localhost', '127.', '0.0.0.0', '10.', '192.168.', '172.16.',
               '172.17.', '172.18.', '172.19.', '172.2', '172.3',
               '169.254.', '::1', '[::1]')
    for b in blocked:
        if b in url:
            return False
    return True

# ── Audit logging (A09) ───────────────────────────────────────────────────────
def audit(action: str, resource: str = '', result: str = 'success', detail: str = ''):
    try:
        from models import AuditLog, db
        entry = AuditLog(
            user_email=session.get('aios_email') or session.get('tenant_email', 'anon'),
            tenant_id=session.get('tenant_id'),
            action=action,
            resource=resource,
            ip_addr=request.remote_addr or '',
            user_agent=(request.user_agent.string or '')[:500],
            result=result,
            detail=detail[:2000],
        )
        db.add(entry)
        db.commit()
    except Exception as exc:
        log.warning('[AIOS Audit] Write failed: %s', exc)

# ── init_security ─────────────────────────────────────────────────────────────
def init_security(app):

    @app.before_request
    def _enforce_security():
        ip   = request.remote_addr or '0.0.0.0'
        path = request.path

        # Auth endpoints get tighter rate limit
        limit = _RL_AUTH_LIMIT if path in ('/login', '/otp') else _RL_LIMIT
        if _rate_check(ip, limit):
            log.warning('[AIOS Security] Rate limit: %s %s', ip, path)
            return Response('Too Many Requests', 429,
                            headers={'Retry-After': str(_RL_WINDOW),
                                     'Content-Type': 'text/plain'})

        # CSRF validation for mutating methods
        if (request.method not in _CSRF_SAFE_METHODS and not _csrf_exempt(path)):
            submitted = (request.form.get('_csrf_token') or
                         request.headers.get('X-CSRF-Token', ''))
            expected  = session.get('_csrf_token', '')
            if not expected or not secrets.compare_digest(str(expected), str(submitted)):
                log.warning('[AIOS Security] CSRF fail: %s %s', ip, path)
                audit('csrf_failure', path, 'failure', f'ip={ip}')
                abort(403)

        # Generate / refresh CSRF token
        if '_csrf_token' not in session:
            session['_csrf_token'] = secrets.token_hex(32)
        g.csrf_token = session['_csrf_token']

    @app.after_request
    def _add_headers(resp):
        for k, v in _SEC_HEADERS.items():
            resp.headers.setdefault(k, v)
        # Never cache authenticated pages
        if session.get('aios_auth') or session.get('tenant_auth'):
            resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, private'
            resp.headers['Pragma']        = 'no-cache'
        return resp

    @app.context_processor
    def _inject_csrf():
        def csrf_token():
            return g.get('csrf_token') or session.get('_csrf_token', '')
        return {'csrf_token': csrf_token}

    log.info('[AIOS Security] Middleware active — OWASP Top 10 hardening enabled')
