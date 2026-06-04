"""
AIOS TOTP Blueprint — /totp/*
Manages authenticator app (Google / Microsoft Authenticator) enrollment.
Exposes helper functions used by the login flow in app.py.
"""
import io
import os
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
def _admin_totp_env_secrets() -> dict:
    """
    Parse super-admin TOTP secrets from env. Two formats supported:
      ADMIN_TOTP_SECRETS=email1:secret1,email2:secret2,...   (preferred, multi-admin)
      ADMIN_TOTP_SECRET=secret + ADMIN_TOTP_EMAIL=email      (legacy, single-admin)
    Returns lowercase-email → base32-secret dict. Multi-admin entries win on conflict.
    """
    # Secrets are base32; tolerate copy/paste artefacts (the setup screen shows the
    # secret space-grouped as "ABCD EFGH ...", and log/console copies can introduce
    # tabs or newlines). Strip ALL whitespace so a formatted paste can't produce an
    # invalid-base32 secret that 500s the verify path.
    _clean = lambda s: ''.join(s.split())
    out: dict = {}
    legacy_secret = _clean(os.getenv('ADMIN_TOTP_SECRET', ''))
    legacy_email  = os.getenv('ADMIN_TOTP_EMAIL', 'roger@aievolutionservices.com').strip().lower()
    if legacy_secret and legacy_email:
        out[legacy_email] = legacy_secret
    raw = os.getenv('ADMIN_TOTP_SECRETS', '').strip()
    if raw:
        for pair in raw.split(','):
            if ':' not in pair:
                continue
            em, sc = pair.split(':', 1)
            em, sc = em.strip().lower(), _clean(sc)
            if em and sc:
                out[em] = sc
    return out


def totp_enabled(email: str) -> bool:
    """
    Returns True only if the user has an active authenticator AND its secret is
    actually retrievable. A stored-but-undecryptable secret (e.g. after an
    ENCRYPTION_KEY / SECRET_KEY rotation) is treated as NOT enabled so the user
    falls back to email-OTP and can re-enroll, instead of being permanently
    bricked at the authenticator screen with "Authenticator not configured".
    """
    try:
        email = email.strip().lower()
        if email in ALLOWED_EMAILS:
            if email in _admin_totp_env_secrets():
                return True
            rec = AdminTOTP.query.filter_by(email=email).first()
            if not (rec and rec.totp_enabled and rec.totp_secret_enc):
                return False
            return bool(decrypt_str('_admin', rec.totp_secret_enc))
        user = TenantUser.query.filter_by(email=email, active=True).first()
        if not (user and user.totp_enabled and user.totp_secret_enc):
            return False
        return bool(decrypt_str(user.tenant_id, user.totp_secret_enc))
    except Exception:
        return False


def get_totp_secret(email: str) -> str | None:
    """Decrypt and return the TOTP secret for this email, or None."""
    try:
        email = email.strip().lower()
        if email in ALLOWED_EMAILS:
            env_secrets = _admin_totp_env_secrets()
            if email in env_secrets:
                return env_secrets[email]
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


def build_admin_totp_secrets_env(extra_email: str = '', extra_secret: str = '') -> str:
    """
    Build the value for ADMIN_TOTP_SECRETS that captures all currently enrolled admins
    (env + DB) plus an optional just-enrolled (email, secret) pair. Used to surface the
    full env-var line on the /totp/setup success page so the operator can paste it into
    Railway/Render without losing prior admins.
    """
    pairs: dict = dict(_admin_totp_env_secrets())
    try:
        for rec in AdminTOTP.query.filter_by(totp_enabled=True).all():
            em = (rec.email or '').strip().lower()
            if em and em not in pairs and rec.totp_secret_enc:
                try:
                    pairs[em] = decrypt_str('_admin', rec.totp_secret_enc)
                except Exception:
                    continue
    except Exception:
        pass
    if extra_email and extra_secret:
        pairs[extra_email.strip().lower()] = extra_secret.strip()
    return ','.join(f'{e}:{s}' for e, s in pairs.items())


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
        if secret and enabled:
            log.warning('[TOTP] IMPORTANT — add to env vars to survive redeploys: ADMIN_TOTP_SECRETS=%s',
                        build_admin_totp_secrets_env(email, secret))
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

    try:
        verified = pyotp.TOTP(secret).verify(code.strip(), valid_window=TOTP_WINDOW)
    except Exception as exc:
        # A malformed secret (e.g. invalid base32 from a bad ADMIN_TOTP_SECRETS paste)
        # must not 500 the login — fail cleanly so the user can use the email-code fallback.
        log.error('[TOTP] secret for %s is unusable (check ADMIN_TOTP_SECRETS formatting): %s', email, exc)
        return False, 'Authenticator is misconfigured for this account. Use the email-code option to sign in.'

    if verified:
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
def _qr_svg(uri: str) -> str:
    """
    Render a QR code as inline SVG (no Pillow dependency). Returns the <svg>…</svg>
    markup as a string, suitable for {{ qr_svg | safe }} in Jinja.
    """
    try:
        import qrcode
        from qrcode.image.svg import SvgPathImage
        img = qrcode.make(uri, image_factory=SvgPathImage, box_size=10, border=2)
        buf = io.BytesIO()
        img.save(buf)
        svg = buf.getvalue().decode('utf-8')
        # Strip XML declaration so it embeds cleanly mid-page
        if svg.startswith('<?xml'):
            svg = svg.split('?>', 1)[-1].lstrip()
        return svg
    except Exception as exc:
        log.warning('[TOTP] QR SVG generation failed: %s', exc)
        return ''


def _qr_b64(uri: str) -> str:
    """Return a base64-encoded PNG of the QR code (requires Pillow). Used as a fallback."""
    try:
        import qrcode
        img = qrcode.make(uri)
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        return base64.b64encode(buf.getvalue()).decode()
    except Exception as exc:
        log.warning('[TOTP] QR PNG generation failed: %s', exc)
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
        qr_svg   = _qr_svg(uri),
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
        is_admin = email in ALLOWED_EMAILS
        env_line = build_admin_totp_secrets_env(email, secret) if is_admin else ''
        return render_template('totp_setup.html',
            complete=True, qr_b64='', secret='', uri='', already=False, error=None,
            env_line=env_line, enrolled_email=email)

    return render_template('totp_setup.html',
        qr_svg   = _qr_svg(uri),
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
