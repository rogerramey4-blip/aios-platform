"""
AIOS TOTP Blueprint — /totp/*
Manages authenticator app (Google / Microsoft Authenticator) enrollment.
Exposes helper functions used by the login flow in app.py.
"""
import io
import base64
import logging
import time

import pyotp
from flask import Blueprint, request, session, redirect, url_for, render_template, jsonify

from auth import require_auth, current_email, ALLOWED_EMAILS
from models import TenantUser, AdminTOTP, db
from encryption import encrypt_str, decrypt_str

log = logging.getLogger(__name__)
totp_bp = Blueprint('totp', __name__, url_prefix='/totp')

ISSUER      = 'AIOS'
TOTP_WINDOW = 1   # ±1 × 30 s window for clock drift

# Simple in-memory TOTP attempt tracker (mirrors OTP lockout in auth.py)
_totp_fails: dict = {}
_TOTP_MAX_FAIL   = 5
_TOTP_LOCKOUT    = 900   # 15 min


# ── Public helpers (used by app.py login routes) ──────────────────────────────
def totp_enabled(email: str) -> bool:
    """Returns True if the user has an active authenticator app registered."""
    try:
        email = email.strip().lower()
        if email in ALLOWED_EMAILS:
            rec = AdminTOTP.query.filter_by(email=email).first()
            return bool(rec and rec.totp_enabled)
        user = TenantUser.query.filter_by(email=email, active=True).first()
        return bool(user and user.totp_enabled)
    except Exception:
        return False


def get_totp_secret(email: str) -> str | None:
    """Decrypt and return the TOTP secret for this email, or None."""
    try:
        email = email.strip().lower()
        if email in ALLOWED_EMAILS:
            rec = AdminTOTP.query.filter_by(email=email).first()
            if rec and rec.totp_secret_enc:
                return decrypt_str('_admin', rec.totp_secret_enc)
            return None
        user = TenantUser.query.filter_by(email=email, active=True).first()
        if user and user.totp_secret_enc:
            return decrypt_str(user.tenant_id, user.totp_secret_enc)
        return None
    except Exception:
        return None


def save_totp(email: str, secret: str, enabled: bool):
    """Encrypt and persist (or clear) a TOTP secret for this email."""
    email = email.strip().lower()
    if email in ALLOWED_EMAILS:
        rec = AdminTOTP.query.filter_by(email=email).first()
        if not rec:
            rec = AdminTOTP(email=email)
            db.add(rec)
        rec.totp_secret_enc = encrypt_str('_admin', secret) if secret else ''
        rec.totp_enabled    = enabled
    else:
        user = TenantUser.query.filter_by(email=email, active=True).first()
        if not user:
            return
        user.totp_secret_enc = encrypt_str(user.tenant_id, secret) if secret else ''
        user.totp_enabled    = enabled
    db.commit()


def verify_totp_code(email: str, code: str) -> tuple:
    """
    Validate a TOTP code. Returns (ok: bool, error_msg: str).
    Applies brute-force lockout after TOTP_MAX_FAIL consecutive failures.
    """
    email = email.strip().lower()
    # Check lockout
    fail_rec = _totp_fails.get(email, {'count': 0, 'until': 0})
    if time.time() < fail_rec['until']:
        secs = int(fail_rec['until'] - time.time())
        return False, f'Too many incorrect attempts. Try again in {secs // 60 + 1} minute(s).'

    secret = get_totp_secret(email)
    if not secret:
        return False, 'Authenticator not configured for this account.'

    if pyotp.TOTP(secret).verify(code.strip(), valid_window=TOTP_WINDOW):
        _totp_fails.pop(email, None)
        return True, 'OK'

    # Record failure
    fail_rec['count'] = fail_rec.get('count', 0) + 1
    if fail_rec['count'] >= _TOTP_MAX_FAIL:
        fail_rec['until'] = time.time() + _TOTP_LOCKOUT
        _totp_fails[email] = fail_rec
        return False, 'Too many incorrect attempts. Authenticator locked for 15 minutes.'
    _totp_fails[email] = fail_rec
    left = _TOTP_MAX_FAIL - fail_rec['count']
    return False, f'Incorrect code. {left} attempt(s) remaining.'


# ── QR code ───────────────────────────────────────────────────────────────────
def _qr_b64(uri: str) -> str:
    """Return a base64-encoded PNG of the QR code for the given URI."""
    try:
        import qrcode
        img = qrcode.make(uri)
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        return base64.b64encode(buf.getvalue()).decode()
    except Exception as exc:
        log.warning('[TOTP] QR generation failed: %s', exc)
        return ''


def _format_secret(s: str) -> str:
    """Format raw base32 secret in groups of 4 for readability."""
    return ' '.join(s[i:i+4] for i in range(0, len(s), 4))


# ── Setup routes (require authenticated session) ──────────────────────────────
@totp_bp.route('/setup', methods=['GET'])
@require_auth
def setup_get():
    email   = current_email()
    secret  = pyotp.random_base32()
    uri     = pyotp.totp.TOTP(secret).provisioning_uri(name=email, issuer_name=ISSUER)
    session['totp_pending_secret'] = secret
    session['totp_pending_uri']    = uri
    return render_template('totp_setup.html',
        qr_b64   = _qr_b64(uri),
        secret   = _format_secret(secret),
        uri      = uri,
        already  = totp_enabled(email),
        error    = None,
        complete = False,
    )


@totp_bp.route('/setup', methods=['POST'])
@require_auth
def setup_post():
    email  = current_email()
    code   = request.form.get('code', '').replace(' ', '').strip()
    secret = session.get('totp_pending_secret', '')
    uri    = session.get('totp_pending_uri', '')

    if not secret:
        return redirect(url_for('totp.setup_get'))

    if pyotp.TOTP(secret).verify(code, valid_window=TOTP_WINDOW):
        save_totp(email, secret, enabled=True)
        session.pop('totp_pending_secret', None)
        session.pop('totp_pending_uri', None)
        log.info('[TOTP] Authenticator enabled for %s', email)
        return render_template('totp_setup.html',
            complete=True, qr_b64='', secret='', uri='', already=False, error=None)

    return render_template('totp_setup.html',
        qr_b64   = _qr_b64(uri),
        secret   = _format_secret(secret),
        uri      = uri,
        already  = totp_enabled(email),
        error    = 'Incorrect code — make sure your authenticator app is synced and try again.',
        complete = False,
    )


@totp_bp.route('/disable', methods=['POST'])
@require_auth
def disable():
    email = current_email()
    code  = (request.form.get('code') or request.get_json(silent=True, force=True) or {}).get('code', '')
    if isinstance(code, dict):
        code = ''
    code = str(code).strip()
    ok, msg = verify_totp_code(email, code)
    if not ok:
        return jsonify({'ok': False, 'error': msg}), 400
    save_totp(email, '', enabled=False)
    log.info('[TOTP] Authenticator disabled for %s', email)
    return jsonify({'ok': True})
