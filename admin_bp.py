"""
AIOS Admin Blueprint — /admin
Full client management panel for super-admins.
All routes require require_admin (the 3 authorized emails only).
"""
import os
import json
import logging
import secrets
import urllib.request
from datetime import datetime
from flask import (Blueprint, render_template, request, redirect,
                   url_for, session, flash, jsonify)
from datetime import timedelta
from models import (Tenant, TenantUser, Document, Domain, AuditLog, AdminTOTP,
                    ApiToken, API_SCOPES, db)
from auth import (require_admin, request_otp, ALLOWED_EMAILS,
                  generate_token, TOKEN_TTL_DAYS)
from security import validate_domain, validate_email, audit

log = logging.getLogger(__name__)
admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


@admin_bp.context_processor
def _admin_ctx():
    """Inject sidebar data into every admin template."""
    try:
        all_tenants = Tenant.query.order_by(Tenant.firm_name).all()
    except Exception:
        all_tenants = []
    return {
        'all_tenants':    all_tenants,
        'industry_icons': INDUSTRY_ICONS,
        'admin_email':    __import__('flask').session.get('aios_email', ''),
    }

INDUSTRY_ICONS = {
    'agency': '🏢', 'legal': '⚖️', 'construction': '🏗️',
    'medical': '🏥', 'brokerage': '🏠', 'hvac': '❄️',
    'plumbing': '🔧', 'restaurant': '🍽️',
}
PLAN_ORDER = {'trial': 0, 'starter': 1, 'growth': 2, 'enterprise': 3}


# ── Overview ──────────────────────────────────────────────────────────────────
@admin_bp.route('/')
@require_admin
def index():
    tenants   = Tenant.query.order_by(Tenant.created_at.desc()).all()
    all_users = TenantUser.query.all()
    all_docs  = Document.query.all()
    all_doms  = Domain.query.filter_by(verified=True).all()

    by_industry = {}
    for t in tenants:
        by_industry.setdefault(t.industry, 0)
        by_industry[t.industry] += 1

    by_plan = {}
    for t in tenants:
        by_plan.setdefault(t.plan, 0)
        by_plan[t.plan] += 1

    kpis = [
        {'label': 'TOTAL CLIENTS',     'value': str(len(tenants))},
        {'label': 'ACTIVE',            'value': str(sum(1 for t in tenants if t.status == 'active'))},
        {'label': 'TOTAL USERS',       'value': str(len(all_users))},
        {'label': 'DOCUMENTS PARSED',  'value': str(len(all_docs))},
        {'label': 'LIVE DOMAINS',      'value': str(len(all_doms))},
    ]

    recent_audits = (AuditLog.query
                     .order_by(AuditLog.ts.desc())
                     .limit(20).all())

    # Augment tenants with user/doc counts
    tenant_user_counts = {}
    tenant_doc_counts  = {}
    for u in all_users:
        tenant_user_counts[u.tenant_id] = tenant_user_counts.get(u.tenant_id, 0) + 1
    for d in all_docs:
        tenant_doc_counts[d.tenant_id]  = tenant_doc_counts.get(d.tenant_id, 0) + 1

    enriched = []
    for t in tenants:
        enriched.append({
            'tenant':    t,
            'users':     tenant_user_counts.get(t.id, 0),
            'docs':      tenant_doc_counts.get(t.id, 0),
            'icon':      INDUSTRY_ICONS.get(t.industry, '▤'),
        })

    return render_template('admin/index.html',
                           kpis=kpis,
                           tenants=enriched,
                           by_industry=by_industry,
                           by_plan=by_plan,
                           recent_audits=recent_audits,
                           admin_email=session.get('aios_email', ''))


# ── Tenant detail ─────────────────────────────────────────────────────────────
@admin_bp.route('/client/<tenant_id>')
@require_admin
def tenant_detail(tenant_id):
    tenant  = Tenant.query.get_or_404(tenant_id)
    users   = TenantUser.query.filter_by(tenant_id=tenant_id).all()
    docs    = (Document.query.filter_by(tenant_id=tenant_id)
               .order_by(Document.uploaded_at.desc()).all())
    domains = Domain.query.filter_by(tenant_id=tenant_id).all()
    audits  = (AuditLog.query.filter_by(tenant_id=tenant_id)
               .order_by(AuditLog.ts.desc()).limit(30).all())
    icon    = INDUSTRY_ICONS.get(tenant.industry, '▤')

    builders = [u for u in users if u.role == 'builder']
    tokens   = (ApiToken.query.filter_by(tenant_id=tenant_id)
                .order_by(ApiToken.created_at.desc()).all())

    return render_template('admin/tenant.html',
                           tenant=tenant,
                           users=users,
                           builders=builders,
                           tokens=tokens,
                           api_scopes=API_SCOPES,
                           docs=docs,
                           domains=domains,
                           audits=audits,
                           icon=icon)


# ── Update tenant (plan / status / notes) ────────────────────────────────────
@admin_bp.route('/client/<tenant_id>/update', methods=['POST'])
@require_admin
def tenant_update(tenant_id):
    tenant = Tenant.query.get_or_404(tenant_id)
    field  = request.form.get('field', '')
    value  = request.form.get('value', '').strip()

    allowed = {'plan': ['trial','starter','growth','enterprise'],
               'status': ['active','suspended','trial'],
               'notes': None, 'firm_name': None, 'firm_sub': None,
               'contact_name': None, 'contact_email': None, 'contact_phone': None}

    if field not in allowed:
        return jsonify({'ok': False, 'error': 'Invalid field'}), 400
    if allowed[field] and value not in allowed[field]:
        return jsonify({'ok': False, 'error': 'Invalid value'}), 400

    setattr(tenant, field, value)
    db.commit()
    audit('tenant_updated', f'tenant:{tenant_id}', 'success', f'{field}={value}')
    return jsonify({'ok': True})


# ── Suspend / activate tenant ─────────────────────────────────────────────────
@admin_bp.route('/client/<tenant_id>/toggle', methods=['POST'])
@require_admin
def tenant_toggle(tenant_id):
    tenant        = Tenant.query.get_or_404(tenant_id)
    tenant.status = 'suspended' if tenant.status == 'active' else 'active'
    db.commit()
    audit('tenant_toggled', f'tenant:{tenant_id}', 'success', f'status={tenant.status}')
    return jsonify({'ok': True, 'status': tenant.status})


# ── Add user to tenant ────────────────────────────────────────────────────────
@admin_bp.route('/client/<tenant_id>/user/add', methods=['POST'])
@require_admin
def add_user(tenant_id):
    Tenant.query.get_or_404(tenant_id)
    email = request.form.get('email', '').strip().lower()
    name  = request.form.get('name', '').strip()
    role  = request.form.get('role', 'member').strip()

    if not validate_email(email):
        return jsonify({'ok': False, 'error': 'Invalid email'}), 400
    if role not in ('admin', 'member', 'builder'):
        return jsonify({'ok': False, 'error': 'Invalid role'}), 400
    if TenantUser.query.filter_by(email=email).first():
        return jsonify({'ok': False, 'error': f'{email} already registered'}), 400

    user = TenantUser(tenant_id=tenant_id, email=email, name=name, role=role)
    db.add(user)
    db.commit()
    audit('user_added', f'tenant:{tenant_id}', 'success', f'email={email} role={role}')
    if role == 'builder':
        # send the assigned builder a first-login code immediately
        request_otp(email)
        audit('builder_assigned', f'tenant:{tenant_id}', 'success',
              f'email={email} by={session.get("aios_email","")}')
    return jsonify({'ok': True, 'user_id': user.id})


# ── Remove user ───────────────────────────────────────────────────────────────
@admin_bp.route('/client/<tenant_id>/user/<user_id>/remove', methods=['POST'])
@require_admin
def remove_user(tenant_id, user_id):
    user = TenantUser.query.filter_by(id=user_id, tenant_id=tenant_id).first_or_404()
    db.delete(user)
    db.commit()
    audit('user_removed', f'tenant:{tenant_id}', 'success', f'email={user.email}')
    return jsonify({'ok': True})


# ── Scoped API tokens (CLI access for builders) ───────────────────────────────
@admin_bp.route('/client/<tenant_id>/token/issue', methods=['POST'])
@require_admin
def token_issue(tenant_id):
    """
    Mint a scoped CLI token for a builder of this tenant. The plaintext secret is
    returned ONCE and never stored — only its SHA-256 hash is persisted.
    """
    Tenant.query.get_or_404(tenant_id)
    user_id = request.form.get('user_id', '').strip()
    name    = request.form.get('name', '').strip()[:120] or 'CLI token'
    raw_scopes = request.form.getlist('scopes') or \
        [s.strip() for s in request.form.get('scopes', '').split(',') if s.strip()]
    scopes = [s for s in raw_scopes if s in API_SCOPES] or list(API_SCOPES)

    user = TenantUser.query.filter_by(id=user_id, tenant_id=tenant_id).first()
    if not user:
        return jsonify({'ok': False, 'error': 'Select a user in this client'}), 400
    if user.role != 'builder':
        return jsonify({'ok': False, 'error': 'Tokens may only be issued to builders'}), 400

    no_expiry = request.form.get('no_expiry') in ('1', 'true', 'on')
    days_raw  = request.form.get('expires_days', '').strip()
    days      = int(days_raw) if days_raw.isdigit() else TOKEN_TTL_DAYS
    expires_at = None if no_expiry else datetime.utcnow() + timedelta(days=days)

    secret, token_hash, prefix = generate_token()
    tok = ApiToken(
        tenant_id=tenant_id, user_id=user.id, name=name,
        token_prefix=prefix, token_hash=token_hash, scopes=','.join(scopes),
        created_by=session.get('aios_email', ''), expires_at=expires_at,
    )
    db.add(tok)
    db.commit()
    audit('api_token_issued', f'tenant:{tenant_id}', 'success',
          f'user={user.email} scopes={len(scopes)} expires={expires_at} by={session.get("aios_email","")}')
    # secret returned exactly once
    return jsonify({'ok': True, 'token': secret, 'prefix': prefix,
                    'expires_at': expires_at.isoformat() if expires_at else None})


@admin_bp.route('/client/<tenant_id>/token/<token_id>/revoke', methods=['POST'])
@require_admin
def token_revoke(tenant_id, token_id):
    tok = ApiToken.query.filter_by(id=token_id, tenant_id=tenant_id).first_or_404()
    tok.revoked    = True
    tok.revoked_at = datetime.utcnow()
    db.commit()
    audit('api_token_revoked', f'tenant:{tenant_id}', 'success',
          f'token={tok.token_prefix} by={session.get("aios_email","")}')
    return jsonify({'ok': True})


# ── Domain management ─────────────────────────────────────────────────────────
@admin_bp.route('/client/<tenant_id>/domain/add', methods=['POST'])
@require_admin
def domain_add(tenant_id):
    Tenant.query.get_or_404(tenant_id)
    domain_str = request.form.get('domain', '').strip().lower().lstrip('www.')

    if not validate_domain(domain_str):
        return jsonify({'ok': False, 'error': 'Invalid domain name'}), 400
    if Domain.query.filter_by(domain=domain_str).first():
        return jsonify({'ok': False, 'error': 'Domain already registered'}), 400

    # CNAME target — the Railway/hosting URL for this app
    cname_target = os.getenv('APP_HOSTNAME', 'aios-platform.railway.app')

    dom = Domain(
        tenant_id          = tenant_id,
        domain             = domain_str,
        verification_token = secrets.token_hex(24),
        cname_target       = cname_target,
    )
    db.add(dom)
    db.commit()
    audit('domain_added', f'tenant:{tenant_id}', 'success', f'domain={domain_str}')
    return jsonify({
        'ok':                True,
        'domain_id':         dom.id,
        'verification_token': dom.verification_token,
        'cname_target':      cname_target,
    })


@admin_bp.route('/client/<tenant_id>/domain/<domain_id>/verify', methods=['POST'])
@require_admin
def domain_verify(tenant_id, domain_id):
    dom = Domain.query.filter_by(id=domain_id, tenant_id=tenant_id).first_or_404()
    verified = _check_dns_txt(dom.domain, dom.verification_token)
    if verified:
        dom.verified    = True
        dom.ssl_status  = 'active'
        dom.verified_at = datetime.utcnow()
        db.commit()
        audit('domain_verified', f'tenant:{tenant_id}', 'success', f'domain={dom.domain}')
        return jsonify({'ok': True, 'verified': True})
    return jsonify({'ok': True, 'verified': False,
                    'message': 'TXT record not yet found — DNS may take up to 24h to propagate'})


@admin_bp.route('/client/<tenant_id>/domain/<domain_id>/remove', methods=['POST'])
@require_admin
def domain_remove(tenant_id, domain_id):
    dom = Domain.query.filter_by(id=domain_id, tenant_id=tenant_id).first_or_404()
    name = dom.domain
    db.delete(dom)
    db.commit()
    audit('domain_removed', f'tenant:{tenant_id}', 'success', f'domain={name}')
    return jsonify({'ok': True})


# ── Audit log ─────────────────────────────────────────────────────────────────
@admin_bp.route('/audit')
@require_admin
def audit_log():
    page    = request.args.get('page', 1, type=int)
    per     = 50
    entries = (AuditLog.query
               .order_by(AuditLog.ts.desc())
               .offset((page - 1) * per)
               .limit(per).all())
    total = AuditLog.query.count()
    return render_template('admin/audit.html',
                           entries=entries,
                           page=page,
                           total=total,
                           per=per)


# ── DNS TXT verification (A10 SSRF-safe) ─────────────────────────────────────
def _check_dns_txt(domain: str, token: str) -> bool:
    try:
        url = f'https://dns.google/resolve?name=_aios-verify.{domain}&type=TXT'
        req = urllib.request.Request(url, headers={'User-Agent': 'AIOS/1.0'})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read())
        for answer in data.get('Answer', []):
            if token in answer.get('data', ''):
                return True
    except Exception as exc:
        log.warning('[AIOS Domain] DNS check failed for %s: %s', domain, exc)
    return False




# ── Gmail API authorization ───────────────────────────────────────────────────
@admin_bp.route('/gmail-auth')
@require_admin
def gmail_auth():
    import os, urllib.parse
    from flask import redirect, url_for
    client_id = os.getenv('GOOGLE_CLIENT_ID', '')
    if not client_id:
        return ('<html><body style="background:#0a0e14;color:#e6edf3;font-family:monospace;padding:32px">'
                '<h2 style="color:#e3b341">Missing GOOGLE_CLIENT_ID</h2>'
                '<p>Add <code>GOOGLE_CLIENT_ID</code> and <code>GOOGLE_CLIENT_SECRET</code> '
                'to Railway environment variables, then redeploy and reload this page.</p>'
                '</body></html>'), 400
    params = urllib.parse.urlencode({
        'client_id':     client_id,
        'redirect_uri':  url_for('admin.gmail_callback', _external=True),
        'scope':         'https://www.googleapis.com/auth/gmail.send',
        'response_type': 'code',
        'access_type':   'offline',
        'prompt':        'consent',
    })
    return redirect(f'https://accounts.google.com/o/oauth2/auth?{params}')


@admin_bp.route('/gmail-callback')
@require_admin
def gmail_callback():
    import os, json as _json, urllib.request, urllib.parse, urllib.error
    from flask import request, url_for
    code = request.args.get('code', '')
    if not code:
        return '<h2>Authorization failed — no code returned.</h2>', 400
    client_id     = os.getenv('GOOGLE_CLIENT_ID', '')
    client_secret = os.getenv('GOOGLE_CLIENT_SECRET', '')
    data = urllib.parse.urlencode({
        'code':          code,
        'client_id':     client_id,
        'client_secret': client_secret,
        'redirect_uri':  url_for('admin.gmail_callback', _external=True),
        'grant_type':    'authorization_code',
    }).encode()
    req = urllib.request.Request(
        'https://oauth2.googleapis.com/token',
        data=data,
        headers={'Content-Type': 'application/x-www-form-urlencoded'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            token = _json.loads(resp.read())
    except Exception as exc:
        return (f'<html><body style="background:#0a0e14;color:#e6edf3;padding:32px">'
                f'<h2 style="color:red">Token exchange failed: {exc}</h2></body></html>'), 500
    refresh_token = token.get('refresh_token', '')
    if not refresh_token:
        return ('<html><body style="background:#0a0e14;color:#e6edf3;padding:32px">'
                '<h2 style="color:red">No refresh_token returned.</h2>'
                '<p>Revoke AIOS access at <a href="https://myaccount.google.com/permissions" '
                'style="color:#e3b341">myaccount.google.com/permissions</a> then try again.</p>'
                '</body></html>'), 400
    from models import set_config
    set_config('GMAIL_REFRESH_TOKEN', refresh_token)
    return (f'<html><body style="background:#0a0e14;color:#e6edf3;font-family:monospace;padding:32px">'
            f'<h2 style="color:#3fb950">Gmail authorized!</h2>'
            f'<p>Emails will now send via the Gmail API.</p>'
            f'<p style="color:#e3b341;font-weight:bold">IMPORTANT: Copy this token into Railway environment variables'
            f' as <code>GMAIL_REFRESH_TOKEN</code> so it survives redeployments:</p>'
            f'<textarea style="width:100%;height:80px;background:#161b22;color:#3fb950;border:1px solid #30363d;'
            f'padding:8px;font-family:monospace;font-size:12px">{refresh_token}</textarea>'
            f'<p>After adding to Railway, test: <a href="/admin/test-email" style="color:#e3b341">/admin/test-email</a></p>'
            f'</body></html>')


# ── Users & Access (global account administration) ────────────────────────────
@admin_bp.route('/users')
@require_admin
def users():
    """Cross-tenant account administration: super-admins + every tenant user."""
    from totp_bp import totp_enabled, _admin_totp_env_secrets

    env_admins = _admin_totp_env_secrets()
    db_admins  = {r.email: r for r in AdminTOTP.query.all()}
    super_admins = []
    for email in sorted(ALLOWED_EMAILS):
        rec = db_admins.get(email)
        super_admins.append({
            'email':        email,
            'has_2fa':      totp_enabled(email),
            'in_env':       email in env_admins,
            'has_db_secret': bool(rec and rec.totp_secret_enc),
            'is_self':      email == session.get('aios_email', ''),
        })

    tenants = {t.id: t for t in Tenant.query.all()}
    tenant_users = []
    for u in TenantUser.query.order_by(TenantUser.created_at.desc()).all():
        t = tenants.get(u.tenant_id)
        tenant_users.append({
            'id':         u.id,
            'email':      u.email,
            'name':       u.name or '',
            'role':       u.role,
            'active':     bool(u.active),
            'has_2fa':    bool(getattr(u, 'totp_enabled', False)),
            'last_login': u.last_login,
            'firm_name':  t.firm_name if t else '—',
            'tenant_id':  u.tenant_id,
            'industry':   t.industry if t else '',
        })

    return render_template('admin/users.html',
                           active='users',
                           super_admins=super_admins,
                           tenant_users=tenant_users,
                           admin_email=session.get('aios_email', ''))


@admin_bp.route('/user/<user_id>/reset-2fa', methods=['POST'])
@require_admin
def user_reset_2fa(user_id):
    """Disable a tenant user's authenticator so they re-enroll on next login."""
    user = TenantUser.query.filter_by(id=user_id).first_or_404()
    user.totp_secret_enc = ''
    user.totp_enabled    = False
    db.commit()
    audit('user_2fa_reset', f'user:{user.email}', 'success',
          f'by={session.get("aios_email", "")}')
    return jsonify({'ok': True})


@admin_bp.route('/user/<user_id>/toggle-active', methods=['POST'])
@require_admin
def user_toggle_active(user_id):
    """Enable / disable (suspend) a tenant user account."""
    user = TenantUser.query.filter_by(id=user_id).first_or_404()
    user.active = not bool(user.active)
    db.commit()
    audit('user_active_toggled', f'user:{user.email}', 'success',
          f'active={user.active} by={session.get("aios_email", "")}')
    return jsonify({'ok': True, 'active': bool(user.active)})


@admin_bp.route('/user/<user_id>/role', methods=['POST'])
@require_admin
def user_set_role(user_id):
    """Change a tenant user's role between admin and member."""
    user = TenantUser.query.filter_by(id=user_id).first_or_404()
    role = request.form.get('role', '').strip()
    if role not in ('admin', 'member', 'builder'):
        return jsonify({'ok': False, 'error': 'Invalid role'}), 400
    user.role = role
    db.commit()
    audit('user_role_changed', f'user:{user.email}', 'success',
          f'role={role} by={session.get("aios_email", "")}')
    return jsonify({'ok': True, 'role': role})


@admin_bp.route('/user/send-login', methods=['POST'])
@require_admin
def user_send_login():
    """
    OTP-system equivalent of a password reset: email the account a fresh
    one-time login code. Works for both tenant users and super-admins.
    """
    email = request.form.get('email', '').strip().lower()
    if not validate_email(email):
        return jsonify({'ok': False, 'error': 'Invalid email'}), 400
    is_admin  = email in ALLOWED_EMAILS
    is_tenant = bool(TenantUser.query.filter_by(email=email, active=True).first())
    if not (is_admin or is_tenant):
        return jsonify({'ok': False, 'error': 'No active account with that email'}), 404
    ok, msg = request_otp(email)
    audit('user_login_code_sent', f'user:{email}', 'success' if ok else 'failure',
          f'by={session.get("aios_email", "")}')
    if not ok:
        return jsonify({'ok': False, 'error': msg}), 400
    return jsonify({'ok': True})


@admin_bp.route('/admin/reset-2fa', methods=['POST'])
@require_admin
def admin_reset_2fa():
    """
    Clear a super-admin's stored (DB) authenticator secret so they re-enroll on
    next login. Used to recover an admin bricked by an undecryptable secret.
    Note: a secret pinned in ADMIN_TOTP_SECRETS / ADMIN_TOTP_SECRET env vars must
    also be removed from the host env — this is reported back to the caller.
    """
    email = request.form.get('email', '').strip().lower()
    if email not in ALLOWED_EMAILS:
        return jsonify({'ok': False, 'error': 'Not a super-admin email'}), 400
    rec = AdminTOTP.query.filter_by(email=email).first()
    if rec:
        rec.totp_secret_enc = ''
        rec.totp_enabled    = False
        db.commit()
    from totp_bp import _admin_totp_env_secrets
    in_env = email in _admin_totp_env_secrets()
    audit('admin_2fa_reset', f'admin:{email}', 'success',
          f'by={session.get("aios_email", "")} in_env={in_env}')
    return jsonify({'ok': True, 'in_env': in_env})


# ── SMTP settings ─────────────────────────────────────────────────────────────
@admin_bp.route('/settings/smtp', methods=['GET', 'POST'])
@require_admin
def smtp_settings():
    from models import get_config, set_config
    saved_msg = None
    error     = None
    if request.method == 'POST':
        host = request.form.get('smtp_host', '').strip()
        port = request.form.get('smtp_port', '587').strip()
        user = request.form.get('smtp_user', '').strip()
        pw   = request.form.get('smtp_pass', '').strip()
        if host: set_config('SMTP_HOST', host)
        if port: set_config('SMTP_PORT', port)
        if user: set_config('SMTP_USER', user)
        if pw:   set_config('SMTP_PASS', pw)
        audit('smtp_updated', '/admin/settings/smtp', 'success',
              f'by={session.get("aios_email", "")} host={host}')
        saved_msg = 'SMTP credentials saved and encrypted in the database.'
    return render_template('admin/smtp.html',
        active     = 'smtp',
        smtp_host  = get_config('SMTP_HOST'),
        smtp_port  = get_config('SMTP_PORT') or '587',
        smtp_user  = get_config('SMTP_USER'),
        smtp_pass_set = bool(get_config('SMTP_PASS')),
        saved_msg  = saved_msg,
        error      = error,
    )
