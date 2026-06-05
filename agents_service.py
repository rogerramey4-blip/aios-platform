"""
Per-tenant agent CRUD — shared by the token API (api_bp) and the session UI
(app.py workspace routes) so both layers enforce identical validation and never
drift. Every function is hard-scoped to the tenant_id passed by the caller.

Return convention: (result, error) — result is a dict (or list) on success and
error is None; on failure result is None and error is a human-readable string.
"""
import re
import uuid
import logging
from datetime import datetime

from models import TenantAgent, AGENT_STATUSES, db

log = logging.getLogger(__name__)

_CONFIG_KEYS = ('instructions', 'schedule', 'model', 'integrations', 'triggers', 'notes')
_MAX_AGENTS_PER_TENANT = 200   # sanity cap


def _slug(text: str) -> str:
    s = re.sub(r'[^a-z0-9]+', '-', (text or '').lower()).strip('-')
    return s[:80] or ('agent-' + uuid.uuid4().hex[:8])


def _unique_key(tenant_id: str, name: str, requested: str = '') -> str:
    base = _slug(requested or name)
    key = base
    n = 2
    while TenantAgent.query.filter_by(tenant_id=tenant_id, key=key).first():
        key = f'{base}-{n}'
        n += 1
    return key


def _clean_config(raw: dict) -> dict:
    cfg = {}
    for k in _CONFIG_KEYS:
        if k not in (raw or {}):
            continue
        v = raw[k]
        if k in ('integrations', 'triggers'):
            cfg[k] = [str(x)[:120] for x in v][:50] if isinstance(v, list) else []
        else:
            cfg[k] = str(v)[:8000]
    return cfg


def list_agents(tenant_id: str):
    rows = (TenantAgent.query.filter_by(tenant_id=tenant_id)
            .order_by(TenantAgent.created_at.desc()).all())
    return [a.to_dict() for a in rows], None


def get_agent(tenant_id: str, agent_id: str):
    a = TenantAgent.query.filter_by(id=agent_id, tenant_id=tenant_id).first()
    if not a:
        return None, 'Agent not found'
    return a.to_dict(include_config=True), None


def create_agent(tenant_id: str, data: dict, created_by: str = ''):
    name = (data.get('name') or '').strip()
    if not name:
        return None, 'name is required'
    if len(name) > 200:
        return None, 'name too long (max 200)'
    status = (data.get('status') or 'draft').strip()
    if status not in AGENT_STATUSES:
        return None, f'status must be one of: {", ".join(AGENT_STATUSES)}'
    if TenantAgent.query.filter_by(tenant_id=tenant_id).count() >= _MAX_AGENTS_PER_TENANT:
        return None, 'agent limit reached for this client'

    a = TenantAgent(
        tenant_id=tenant_id,
        key=_unique_key(tenant_id, name, data.get('key', '')),
        name=name,
        agent_type=(data.get('agent_type') or 'Custom').strip()[:60],
        status=status,
        description=(data.get('description') or '').strip()[:2000],
        created_by=created_by,
    )
    a.set_config(_clean_config(data.get('config') or {}))
    db.add(a)
    db.commit()
    return a.to_dict(include_config=True), None


def update_agent(tenant_id: str, agent_id: str, data: dict):
    a = TenantAgent.query.filter_by(id=agent_id, tenant_id=tenant_id).first()
    if not a:
        return None, 'Agent not found'
    if 'name' in data:
        name = (data.get('name') or '').strip()
        if not name:
            return None, 'name cannot be empty'
        a.name = name[:200]
    if 'agent_type' in data:
        a.agent_type = (data.get('agent_type') or 'Custom').strip()[:60]
    if 'description' in data:
        a.description = (data.get('description') or '').strip()[:2000]
    if 'status' in data:
        status = (data.get('status') or '').strip()
        if status not in AGENT_STATUSES:
            return None, f'status must be one of: {", ".join(AGENT_STATUSES)}'
        a.status = status
    if 'config' in data and isinstance(data['config'], dict):
        merged = a.get_config()
        merged.update(_clean_config(data['config']))
        a.set_config(merged)
    a.updated_at = datetime.utcnow()
    db.commit()
    return a.to_dict(include_config=True), None


def set_status(tenant_id: str, agent_id: str, status: str):
    if status not in AGENT_STATUSES:
        return None, f'status must be one of: {", ".join(AGENT_STATUSES)}'
    return update_agent(tenant_id, agent_id, {'status': status})


def delete_agent(tenant_id: str, agent_id: str):
    a = TenantAgent.query.filter_by(id=agent_id, tenant_id=tenant_id).first()
    if not a:
        return None, 'Agent not found'
    name = a.name
    db.delete(a)
    db.commit()
    return {'deleted': agent_id, 'name': name}, None
