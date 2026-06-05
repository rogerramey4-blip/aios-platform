"""
AIOS — Email OTP Auth
Super-admins: roger@, kevin@, charlene@ aievolutionservices.com
Tenant users: any active email in TenantUser table
"""

import os
import time
import hashlib
import secrets
import logging
from datetime import datetime, timedelta
import pyotp
from functools import wraps
from flask import session, redirect, url_for, request, g, jsonify, abort

log = logging.getLogger(__name__)

ALLOWED_EMAILS = frozenset({
    'roger@aievolutionservices.com',
    'kevin@aievolutionservices.com',
    'charlene@aievolutionservices.com',
})

OTP_TTL          = 600
MAX_ATTEMPTS     = 5
MAX_OTP_REQUESTS = 3
REQUEST_WINDOW   = 900
LOCKOUT_DURATION = 900
SESSION_TTL      = 28800

_otp_store:     dict = {}   # in-memory fallback when DB unavailable
_rate_store:    dict = {}
_lockout_store: dict = {}


def mask_email(email: str) -> str:
    user, domain = email.split('@', 1)
    return user[0] + '***@' + domain


def check_authorized(email: str) -> tuple:
    """Validate email is authorized and not locked out, without sending an OTP."""
    email = email.strip().lower()
    is_admin  = email in ALLOWED_EMAILS
    is_tenant = bool(_lookup_tenant_user(email))
    if not is_admin and not is_tenant:
        return False, 'That email address is not authorized to access this system.'
    locked, secs = _locked_out(email)
    if locked:
        return False, f'Too many failed attempts. Try again in {secs // 60 + 1} minute(s).'
    return True, ''


# ── Per-user login bypass (super-admin controlled) ────────────────────────────
# An email listed here skips ALL login verification — no email OTP, no
# authenticator: entering the email logs the user straight in. Applies to
# super-admins and tenant users alike. Stored as a CSV in SystemConfig (encrypted,
# survives redeploys, no schema change) with an env-var fallback (LOGIN_BYPASS_EMAILS)
# for a redeploy-proof exemption. The email must still be authorized + active —
# bypass only removes the verification step, never the authorization check.
_LOGIN_BYPASS_KEY = 'LOGIN_BYPASS_EMAILS'


def _bypass_set() -> set:
    try:
        from models import get_config
        raw = get_config(_LOGIN_BYPASS_KEY, '')
    except Exception:
        raw = os.getenv(_LOGIN_BYPASS_KEY, '')
    return {e.strip().lower() for e in (raw or '').split(',') if e.strip()}


def login_bypass_enabled(email: str) -> bool:
    """True if this email is exempt from all login verification."""
    return (email or '').strip().lower() in _bypass_set()


def set_login_bypass(email: str, on: bool) -> bool:
    """Add/remove an email from the login-bypass set. Returns the new state."""
    email = (email or '').strip().lower()
    if not email:
        return False
    s = _bypass_set()
    s.add(email) if on else s.discard(email)
    from models import set_config
    set_config(_LOGIN_BYPASS_KEY, ','.join(sorted(s)))
    log.warning('[AIOS Auth] login bypass %s for %s', 'ENABLED' if on else 'disabled', email)
    return on


def _rate_limited(email: str) -> bool:
    now = time.time()
    window = [t for t in _rate_store.get(email, []) if now - t < REQUEST_WINDOW]
    _rate_store[email] = window
    return len(window) >= MAX_OTP_REQUESTS


def _locked_out(email: str) -> tuple:
    until = _lockout_store.get(email, 0)
    if time.time() < until:
        return True, int(until - time.time())
    return False, 0


def _lookup_tenant_user(email: str):
    """Returns TenantUser if the email belongs to an active tenant, else None."""
    try:
        from models import TenantUser
        return TenantUser.query.filter_by(email=email, active=True).first()
    except Exception:
        return None


def request_otp(email: str) -> tuple:
    email = email.strip().lower()
    is_admin  = email in ALLOWED_EMAILS
    is_tenant = bool(_lookup_tenant_user(email))
    if not is_admin and not is_tenant:
        return False, 'That email address is not authorized to access this system.'
    locked, secs = _locked_out(email)
    if locked:
        return False, f'Too many failed attempts. Try again in {secs // 60 + 1} minute(s).'
    if _rate_limited(email):
        return False, 'Too many code requests. Please wait 15 minutes and try again.'
    code = ''.join(str(secrets.randbelow(10)) for _ in range(6))
    _rate_store.setdefault(email, []).append(time.time())

    # DB primary, memory fallback — email is sent regardless
    try:
        from models import OTPCode, db, Base, _engine
        from datetime import datetime, timedelta
        Base.metadata.create_all(_engine)  # idempotent — creates table if missing
        OTPCode.query.filter_by(email=email).delete()
        db.add(OTPCode(email=email, code=code,
                       expires_at=datetime.utcnow() + timedelta(seconds=OTP_TTL)))
        db.commit()
        log.info('[AIOS Auth] OTP stored in DB for %s', email)
    except Exception as exc:
        log.warning('[AIOS Auth] DB store failed, using memory fallback (%s)', exc)
        _otp_store[email] = {'code': code, 'expires': time.time() + OTP_TTL, 'attempts': 0}

    _deliver(email, code)   # always send — never gated on DB success
    return True, code


def verify_otp(email: str, submitted: str) -> tuple:
    email = email.strip().lower()

    # ── DB path ───────────────────────────────────────────────────────────────
    try:
        from models import OTPCode, db
        from datetime import datetime
        rec = OTPCode.query.filter_by(email=email).first()
        if rec:
            if datetime.utcnow() > rec.expires_at:
                db.delete(rec); db.commit()
                return False, 'Code has expired. Please request a new one.'
            rec.attempts += 1
            if rec.attempts > MAX_ATTEMPTS:
                db.delete(rec); db.commit()
                _lockout_store[email] = time.time() + LOCKOUT_DURATION
                return False, 'Too many incorrect attempts. Account locked for 15 minutes.'
            if submitted.strip() != rec.code:
                db.commit()
                left = max(MAX_ATTEMPTS - rec.attempts, 0)
                return False, f'Incorrect code. {left} attempt(s) remaining.'
            db.delete(rec); db.commit()
            return True, 'OK'
    except Exception as exc:
        log.warning('[AIOS Auth] DB verify failed, trying memory fallback (%s)', exc)

    # ── Memory fallback (single-worker, or when DB unavailable) ──────────────
    rec = _otp_store.get(email)
    if not rec:
        return False, 'No active code found. Please request a new one.'
    if time.time() > rec['expires']:
        del _otp_store[email]
        return False, 'Code has expired. Please request a new one.'
    rec['attempts'] = rec.get('attempts', 0) + 1
    if rec['attempts'] > MAX_ATTEMPTS:
        del _otp_store[email]
        _lockout_store[email] = time.time() + LOCKOUT_DURATION
        return False, 'Too many incorrect attempts. Account locked for 15 minutes.'
    if submitted.strip() != rec['code']:
        left = max(MAX_ATTEMPTS - rec['attempts'], 0)
        return False, f'Incorrect code. {left} attempt(s) remaining.'
    del _otp_store[email]
    return True, 'OK'


def require_auth(f):
    """Allows both super-admins and active tenant users."""
    @wraps(f)
    def decorated(*args, **kwargs):
        now = time.time()
        is_admin  = (session.get('aios_auth') and
                     now - session.get('aios_login_ts', 0) <= SESSION_TTL)
        is_tenant = (session.get('tenant_auth') and
                     now - session.get('tenant_login_ts', 0) <= SESSION_TTL)
        if not is_admin and not is_tenant:
            session.clear()
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


def require_admin(f):
    """Restricts to super-admins only (the 3 authorized emails)."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('aios_auth'):
            return redirect(url_for('login'))
        if time.time() - session.get('aios_login_ts', 0) > SESSION_TTL:
            session.clear()
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


def current_tenant_id() -> str | None:
    p = getattr(g, 'api_principal', None)
    if p:
        return p['tenant_id']
    return session.get('tenant_id')


def current_email() -> str:
    p = getattr(g, 'api_principal', None)
    if p:
        return p['email']
    return session.get('aios_email') or session.get('tenant_email', '')


def is_super_admin() -> bool:
    return bool(session.get('aios_auth'))


# ── Scoped API tokens (CLI / REST) ────────────────────────────────────────────
TOKEN_PREFIX  = 'aios_pat_'
TOKEN_BYTES   = 32          # 256-bit secret
TOKEN_TTL_DAYS = 90         # default expiry when issued


def hash_token(secret: str) -> str:
    """SHA-256 hex of the full token secret — only this is ever stored."""
    return hashlib.sha256(secret.encode()).hexdigest()


def generate_token() -> tuple:
    """
    Mint a new token. Returns (full_secret, token_hash, token_prefix).
    full_secret is shown to the operator exactly once and never persisted.
    """
    body   = secrets.token_urlsafe(TOKEN_BYTES)
    secret = TOKEN_PREFIX + body
    return secret, hash_token(secret), secret[:len(TOKEN_PREFIX) + 6]


def authenticate_api_token():
    """
    Resolve `Authorization: Bearer aios_pat_…` into g.api_principal.
    Returns the principal dict on success, else None. Side-effect free except
    for updating last_used metadata on a valid token.
    """
    hdr = request.headers.get('Authorization', '')
    if not hdr.startswith('Bearer '):
        return None
    secret = hdr[len('Bearer '):].strip()
    if not secret.startswith(TOKEN_PREFIX):
        return None
    try:
        from models import ApiToken, TenantUser, db
        rec = ApiToken.query.filter_by(token_hash=hash_token(secret)).first()
        if not rec or not rec.is_valid():
            return None
        user = TenantUser.query.filter_by(id=rec.user_id, active=True).first()
        if not user:                       # deactivating the user kills every token
            return None
        rec.last_used_at = datetime.utcnow()
        rec.last_used_ip = (request.remote_addr or '')[:50]
        db.commit()
        g.api_principal = {
            'tenant_id': rec.tenant_id,
            'user_id':   user.id,
            'email':     user.email,
            'role':      user.role,
            'scopes':    {s for s in (rec.scopes or '').split(',') if s},
            'token_id':  rec.id,
        }
        return g.api_principal
    except Exception as exc:
        log.warning('[AIOS Auth] token auth error: %s', exc)
        return None


def _api_error(msg: str, code: int):
    resp = jsonify({'ok': False, 'error': msg})
    resp.status_code = code
    if code == 401:
        resp.headers['WWW-Authenticate'] = 'Bearer realm="AIOS API"'
    return resp


def require_token(f):
    """API gate: a valid Bearer token is mandatory. Sets g.api_principal."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not getattr(g, 'api_principal', None):
            if not authenticate_api_token():
                return _api_error('Missing or invalid API token.', 401)
        return f(*args, **kwargs)
    return decorated


def require_scope(scope: str):
    """API gate: the presenting token must carry `scope`."""
    def wrapper(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            p = getattr(g, 'api_principal', None) or authenticate_api_token()
            if not p:
                return _api_error('Missing or invalid API token.', 401)
            if scope not in p['scopes']:
                return _api_error(f'Token lacks required scope: {scope}', 403)
            return f(*args, **kwargs)
        return decorated
    return wrapper


def require_builder(f):
    """
    UI gate: an authenticated builder (or super-admin) for the current tenant.
    Super-admins always pass; tenant users pass only if role == 'builder'.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        now = time.time()
        if (session.get('aios_auth') and
                now - session.get('aios_login_ts', 0) <= SESSION_TTL):
            return f(*args, **kwargs)
        if (session.get('tenant_auth') and
                now - session.get('tenant_login_ts', 0) <= SESSION_TTL and
                session.get('tenant_role') == 'builder'):
            return f(*args, **kwargs)
        if session.get('tenant_auth'):
            abort(403)
        session.clear()
        return redirect(url_for('login'))
    return decorated


def industry_scope_violation(url_industry: str) -> str | None:
    """
    Tenant-scope check for /<industry>/* routes. Returns the user's OWN industry
    when they are reaching for an industry that isn't theirs (caller should then
    redirect there), or None when access is permitted.

    Super-admins (no fixed industry) and unauthenticated requests are permitted
    here — require_auth handles the unauthenticated case downstream. This is the
    single source of truth used by app.py's before_request guard.
    """
    if session.get('aios_auth'):
        return None                               # super-admin: all industries
    own = session.get('tenant_industry')
    if url_industry and own and url_industry != own:
        log.warning('[AIOS Auth] tenant scope block: %s tried /%s',
                    session.get('tenant_email', '?'), url_industry)
        return own
    return None


def _deliver(to: str, code: str):
    # Always emit to logs first — visible in Railway regardless of email outcome
    log.warning('[AIOS OTP] *** CODE for %s: %s (valid 10 min) ***', to, code)
    html = f"""<!DOCTYPE html>
<html><body style="margin:0;padding:24px;background:#0a0e14;font-family:'Inter',sans-serif;">
  <div style="max-width:480px;margin:0 auto;background:#0d1117;border:1px solid #30363d;border-radius:12px;overflow:hidden;">
    <div style="padding:28px 32px 20px;border-bottom:1px solid #21262d;">
      <div style="font-size:30px;font-weight:900;letter-spacing:5px;margin-bottom:4px;color:#e6edf3;">
        A<span style="color:#e3b341;">IOS</span>
      </div>
      <div style="font-size:11px;color:#484f58;letter-spacing:1px;text-transform:uppercase;">AI Operating System &nbsp;·&nbsp; Secure Access</div>
    </div>
    <div style="padding:28px 32px;">
      <p style="font-size:14px;color:#8b949e;margin:0 0 20px;">Your one-time access code:</p>
      <div style="background:#161b22;border:1px solid #30363d;border-radius:8px;padding:22px;text-align:center;margin-bottom:24px;">
        <div style="font-size:44px;font-weight:900;letter-spacing:14px;color:#e3b341;">{code}</div>
      </div>
      <p style="font-size:12px;color:#484f58;margin:0;line-height:1.7;">Valid for <strong style="color:#8b949e;">10 minutes</strong>, single use only.</p>
    </div>
    <div style="padding:14px 32px;background:#161b22;border-top:1px solid #21262d;font-size:11px;color:#484f58;text-align:center;">
      Powered by <span style="color:#e3b341;font-weight:700;">AI Evolution Services</span>
    </div>
  </div>
</body></html>"""

    try:
        from notify import send as _send_email
        _send_email(to, f'Your AIOS Access Code: {code}', html)
    except Exception as exc:
        log.error('[AIOS Auth] Email delivery failed (%s) — printing OTP to console', exc)
        print('\n  ============================================')
        print(f'  AIOS OTP  >>  {to}')
        print(f'  Code: {code}   (expires in 10 minutes)')
        print('  ============================================\n')
        print(f'\n  [AIOS] OTP for {to}: {code}\n')
