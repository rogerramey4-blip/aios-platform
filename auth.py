"""
AIOS — Email OTP Auth
Super-admins: roger@, kevin@, charlene@ aievolutionservices.com
Tenant users: any active email in TenantUser table
"""

import os
import time
import secrets
import smtplib
import logging
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from functools import wraps
from flask import session, redirect, url_for, request

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

_otp_store:     dict = {}
_rate_store:    dict = {}
_lockout_store: dict = {}


def mask_email(email: str) -> str:
    user, domain = email.split('@', 1)
    return user[0] + '***@' + domain


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
    _otp_store[email] = {'code': code, 'expires': time.time() + OTP_TTL, 'attempts': 0}
    _rate_store.setdefault(email, []).append(time.time())
    _deliver(email, code)
    return True, code


def verify_otp(email: str, submitted: str) -> tuple:
    email = email.strip().lower()
    rec   = _otp_store.get(email)
    if not rec:
        return False, 'No active code found. Please request a new one.'
    if time.time() > rec['expires']:
        del _otp_store[email]
        return False, 'Code has expired. Please request a new one.'
    rec['attempts'] += 1
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
    return session.get('tenant_id')


def current_email() -> str:
    return session.get('aios_email') or session.get('tenant_email', '')


def is_super_admin() -> bool:
    return bool(session.get('aios_auth'))


def _deliver(to: str, code: str):
    host     = os.getenv('SMTP_HOST', '')
    port     = int(os.getenv('SMTP_PORT', '587'))
    user     = os.getenv('SMTP_USER', '')
    password = os.getenv('SMTP_PASS', '')
    from_    = user or 'aios@aievolutionservices.com'

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

    if not host or not user or not password:
        print('\n  ============================================')
        print(f'  AIOS OTP  >>  {to}')
        print(f'  Code: {code}   (expires in 10 minutes)')
        print('  ============================================\n')
        log.warning('[AIOS Auth] SMTP not configured — OTP for %s: %s', to, code)
        return

    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = f'Your AIOS Access Code: {code}'
        msg['From']    = f'AIOS Command Center <{from_}>'
        msg['To']      = to
        msg.attach(MIMEText(html, 'html'))
        with smtplib.SMTP(host, port, timeout=15) as srv:
            srv.ehlo(); srv.starttls(); srv.login(user, password)
            srv.sendmail(from_, [to], msg.as_string())
        log.info('[AIOS Auth] OTP sent to %s', to)
    except Exception as exc:
        log.error('[AIOS Auth] SMTP failed (%s) — printing OTP to console', exc)
        print(f'\n  [AIOS] OTP for {to}: {code}\n')
