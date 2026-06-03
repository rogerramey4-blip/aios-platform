"""
AIOS REST API — /api/v1
Token-authenticated automation surface for the CLI and scripts.

Every route is gated by a scoped Bearer token (auth.require_token / require_scope)
and is HARD-SCOPED to that token's tenant_id — the caller never supplies a tenant
id, so a token can only ever read or mutate its own client's AIOS.

Authentication:
    Authorization: Bearer aios_pat_xxxxxxxx…

This blueprint is Bearer-only. security.py rejects any mutating /api/v1 request
that arrives on a browser cookie instead of a token, so the CSRF-exempt /api/
prefix introduces no CSRF surface here.
"""
import logging
from datetime import datetime

import werkzeug.utils as wz
from flask import Blueprint, request, jsonify, g

from auth import require_token, require_scope
from models import (Tenant, TenantUser, Document, Domain, AuditLog, db)
from security import validate_domain, validate_email

log = logging.getLogger(__name__)
api_bp = Blueprint('api_v1', __name__, url_prefix='/api/v1')


# ── Helpers ───────────────────────────────────────────────────────────────────
def _tid() -> str:
    return g.api_principal['tenant_id']


def _tenant() -> Tenant:
    return Tenant.query.get(_tid())


def _audit(action: str, resource: str = '', result: str = 'success', detail: str = ''):
    """Audit-log an API action against the token's principal."""
    try:
        p = g.api_principal
        db.add(AuditLog(
            user_email=p['email'], tenant_id=p['tenant_id'],
            action=action, resource=resource,
            ip_addr=(request.remote_addr or '')[:50],
            user_agent=('cli:' + (request.user_agent.string or ''))[:500],
            result=result, detail=(f'via_token={p.get("token_id","")} ' + detail)[:2000],
        ))
        db.commit()
    except Exception as exc:
        log.warning('[AIOS API] audit write failed: %s', exc)


def _err(msg, code=400):
    return jsonify({'ok': False, 'error': msg}), code


# ── Identity ──────────────────────────────────────────────────────────────────
@api_bp.route('/whoami')
@require_token
def whoami():
    p = g.api_principal
    t = _tenant()
    return jsonify({
        'ok':        True,
        'email':     p['email'],
        'role':      p['role'],
        'scopes':    sorted(p['scopes']),
        'tenant_id': p['tenant_id'],
        'firm_name': t.firm_name if t else None,
        'industry':  t.industry if t else None,
    })


# ── Integrations ──────────────────────────────────────────────────────────────
@api_bp.route('/integrations')
@require_scope('integrations:read')
def integrations_list():
    from integration_connectors import IntegrationAgent
    t = _tenant()
    industry = request.args.get('industry') or (t.industry if t else None)
    platforms = IntegrationAgent(_tid()).get_status_list(industry=industry)
    return jsonify({'ok': True, 'integrations': platforms})


@api_bp.route('/integrations/<platform_key>/connect', methods=['POST'])
@require_scope('integrations:write')
def integrations_connect(platform_key):
    from integration_connectors import IntegrationAgent
    creds = request.get_json(silent=True) or {}
    if not isinstance(creds, dict) or not creds:
        return _err('JSON body with credential fields required')
    result = IntegrationAgent(_tid()).connect(
        platform_key, creds, connected_by=g.api_principal['email'])
    _audit('integration_connect', f'platform:{platform_key}',
           'success' if result.get('ok') else 'failure', result.get('msg', '')[:200])
    return jsonify({'ok': bool(result.get('ok')), 'result': result})


@api_bp.route('/integrations/<platform_key>/test', methods=['POST'])
@require_scope('integrations:write')
def integrations_test(platform_key):
    from integration_connectors import IntegrationAgent
    result = IntegrationAgent(_tid()).test(platform_key)
    _audit('integration_test', f'platform:{platform_key}',
           'success' if result.get('ok') else 'failure', result.get('msg', '')[:200])
    return jsonify({'ok': bool(result.get('ok')), 'result': result})


@api_bp.route('/integrations/<platform_key>/disconnect', methods=['POST'])
@require_scope('integrations:write')
def integrations_disconnect(platform_key):
    from integration_connectors import IntegrationAgent
    IntegrationAgent(_tid()).disconnect(platform_key)
    _audit('integration_disconnect', f'platform:{platform_key}')
    return jsonify({'ok': True})


# ── Documents ─────────────────────────────────────────────────────────────────
@api_bp.route('/documents')
@require_scope('documents:read')
def documents_list():
    docs = (Document.query.filter_by(tenant_id=_tid())
            .order_by(Document.uploaded_at.desc()).all())
    return jsonify({'ok': True, 'documents': [{
        'id': d.id, 'filename': d.filename, 'classification': d.classification,
        'status': d.status, 'size_bytes': d.size_bytes,
        'uploaded_by': d.uploaded_by,
        'uploaded_at': d.uploaded_at.isoformat() if d.uploaded_at else None,
    } for d in docs]})


@api_bp.route('/documents', methods=['POST'])
@require_scope('documents:write')
def documents_upload():
    from document_processor import process_upload, allowed_file, MAX_UPLOAD_BYTES
    t = _tenant()
    f = request.files.get('file')
    if not f or not f.filename:
        return _err('multipart file field "file" required')
    filename = wz.secure_filename(f.filename)
    if not allowed_file(filename):
        return _err('File type not allowed')
    file_bytes = f.read()
    if len(file_bytes) > MAX_UPLOAD_BYTES:
        return _err('File exceeds 25 MB limit', 413)

    email  = g.api_principal['email']
    result = process_upload(file_bytes, filename, _tid(),
                            t.industry if t else '', email)
    doc = Document(
        tenant_id=_tid(), filename=filename,
        content_type=result['content_type'], encrypted_blob=result['encrypted_blob'],
        size_bytes=result['size_bytes'], classification=result['classification'],
        summary_enc=result['summary_enc'], uploaded_by=email, status='pending',
    )
    db.add(doc)
    db.commit()
    _audit('document_upload', f'doc:{doc.id}', 'success',
           f'file={filename} class={result["classification"]}')
    return jsonify({'ok': True, 'doc_id': doc.id,
                    'classification': result['classification'],
                    'confidence': result['confidence']})


# ── Domains ───────────────────────────────────────────────────────────────────
@api_bp.route('/domains')
@require_scope('domains:read')
def domains_list():
    doms = Domain.query.filter_by(tenant_id=_tid()).all()
    return jsonify({'ok': True, 'domains': [{
        'id': d.id, 'domain': d.domain, 'verified': bool(d.verified),
        'ssl_status': d.ssl_status, 'cname_target': d.cname_target,
        'verification_token': d.verification_token,
    } for d in doms]})


@api_bp.route('/domains', methods=['POST'])
@require_scope('domains:write')
def domains_add():
    import os, secrets
    body = request.get_json(silent=True) or {}
    domain_str = (body.get('domain') or '').strip().lower().lstrip('www.')
    if not validate_domain(domain_str):
        return _err('Invalid domain name')
    if Domain.query.filter_by(domain=domain_str).first():
        return _err('Domain already registered')
    cname_target = os.getenv('APP_HOSTNAME', 'aios-platform.railway.app')
    dom = Domain(tenant_id=_tid(), domain=domain_str,
                 verification_token=secrets.token_hex(24), cname_target=cname_target)
    db.add(dom)
    db.commit()
    _audit('domain_added', f'domain:{domain_str}')
    return jsonify({'ok': True, 'domain_id': dom.id,
                    'verification_token': dom.verification_token,
                    'cname_target': cname_target})


@api_bp.route('/domains/<domain_id>/verify', methods=['POST'])
@require_scope('domains:write')
def domains_verify(domain_id):
    from admin_bp import _check_dns_txt
    dom = Domain.query.filter_by(id=domain_id, tenant_id=_tid()).first_or_404()
    verified = _check_dns_txt(dom.domain, dom.verification_token)
    if verified:
        dom.verified, dom.ssl_status, dom.verified_at = True, 'active', datetime.utcnow()
        db.commit()
        _audit('domain_verified', f'domain:{dom.domain}')
    return jsonify({'ok': True, 'verified': verified})


# ── Client staff users (member / admin only — never builder or super-admin) ────
@api_bp.route('/users')
@require_scope('users:read')
def users_list():
    users = TenantUser.query.filter_by(tenant_id=_tid()).all()
    return jsonify({'ok': True, 'users': [{
        'id': u.id, 'email': u.email, 'name': u.name, 'role': u.role,
        'active': bool(u.active),
        'last_login': u.last_login.isoformat() if u.last_login else None,
    } for u in users]})


@api_bp.route('/users', methods=['POST'])
@require_scope('users:write')
def users_add():
    body = request.get_json(silent=True) or {}
    email = (body.get('email') or '').strip().lower()
    name  = (body.get('name') or '').strip()
    role  = (body.get('role') or 'member').strip()
    if not validate_email(email):
        return _err('Invalid email')
    if role not in ('member', 'admin'):
        # builders are provisioned by super-admins only, never via a tenant token
        return _err('role must be "member" or "admin"')
    if TenantUser.query.filter_by(email=email).first():
        return _err(f'{email} already registered')
    user = TenantUser(tenant_id=_tid(), email=email, name=name, role=role)
    db.add(user)
    db.commit()
    _audit('user_added', f'user:{email}', 'success', f'role={role}')
    return jsonify({'ok': True, 'user_id': user.id})


@api_bp.route('/users/<user_id>/toggle-active', methods=['POST'])
@require_scope('users:write')
def users_toggle(user_id):
    user = TenantUser.query.filter_by(id=user_id, tenant_id=_tid()).first_or_404()
    if user.role == 'builder':
        return _err('Cannot modify a builder account via the API', 403)
    user.active = not bool(user.active)
    db.commit()
    _audit('user_active_toggled', f'user:{user.email}', 'success', f'active={user.active}')
    return jsonify({'ok': True, 'active': bool(user.active)})


# ── Tenant settings (safe subset — not plan/status, which are commercial) ──────
_SETTINGS_FIELDS = ('firm_name', 'firm_sub', 'contact_name',
                    'contact_email', 'contact_phone', 'notes')


@api_bp.route('/settings')
@require_scope('settings:read')
def settings_get():
    t = _tenant()
    return jsonify({'ok': True, 'settings': t.to_dict() if t else {}})


@api_bp.route('/settings', methods=['PATCH', 'POST'])
@require_scope('settings:write')
def settings_update():
    t = _tenant()
    if not t:
        return _err('Tenant not found', 404)
    body = request.get_json(silent=True) or {}
    changed = []
    for field in _SETTINGS_FIELDS:
        if field in body:
            val = str(body[field]).strip()[:1000]
            if field == 'contact_email' and val and not validate_email(val):
                return _err('Invalid contact_email')
            setattr(t, field, val)
            changed.append(field)
    if not changed:
        return _err('No updatable fields supplied. Allowed: ' + ', '.join(_SETTINGS_FIELDS))
    db.commit()
    _audit('settings_updated', f'tenant:{t.id}', 'success', f'fields={",".join(changed)}')
    return jsonify({'ok': True, 'updated': changed})
