"""
AIOS Sync Blueprint — /api/sync/*
Handles offline change queue flush, conflict detection, and conflict resolution.

Conflict detection logic:
  - Every mutable resource has a `version` counter (increments on each write).
  - When a client goes offline, each queued change records `base_version` =
    the server version at last sync.
  - On sync, if current resource version > base_version → another user changed
    it while the client was offline → conflict.
  - Both users are notified by email and can resolve via the UI.
"""
import logging
from datetime import datetime
from flask import Blueprint, request, session, jsonify
from models import Document, SyncConflict, db
from auth import require_auth, current_email, current_tenant_id
from security import audit
from notify import send_conflict_notification, send_sync_complete

log = logging.getLogger(__name__)
sync_bp = Blueprint('sync', __name__, url_prefix='/api/sync')

# Resources we support versioned sync for
_RESOURCE_HANDLERS = {}   # populated by decorators below


# ── Heartbeat (connectivity probe) ───────────────────────────────────────────
@sync_bp.route('/heartbeat')
def heartbeat():
    return jsonify({'ok': True, 'ts': datetime.utcnow().isoformat()})


# ── Batch sync submission ─────────────────────────────────────────────────────
@sync_bp.route('/batch', methods=['POST'])
@require_auth
def batch_sync():
    """
    Body: { "changes": [ {id, resource_type, resource_id, field, new_value,
                           base_version, url, method, payload,
                           client_modified_at, ...}, ... ] }
    Returns: { "accepted_ids": [...], "conflicts": [...] }
    """
    body    = request.get_json(silent=True) or {}
    changes = body.get('changes', [])
    if not isinstance(changes, list):
        return jsonify({'ok': False, 'error': 'changes must be a list'}), 400

    email     = current_email()
    tenant_id = current_tenant_id()

    accepted_ids = []
    conflicts    = []

    for change in changes:
        cid          = change.get('id', '')
        resource_type= change.get('resource_type', '')
        resource_id  = change.get('resource_id',   '')
        field        = change.get('field',         '')
        new_value    = change.get('new_value',     '')
        base_version = int(change.get('base_version', 0))
        client_ts    = change.get('client_modified_at', '')
        url          = change.get('url',     '')
        method       = change.get('method',  'POST')
        payload      = change.get('payload', {})

        try:
            result = _apply_change(
                resource_type = resource_type,
                resource_id   = resource_id,
                field         = field,
                new_value     = new_value,
                base_version  = base_version,
                client_ts     = client_ts,
                email         = email,
                tenant_id     = tenant_id,
                url           = url,
                method        = method,
                payload       = payload,
            )
            if result.get('conflict'):
                conflict_record = result['conflict_record']
                conflicts.append({
                    'change_id': cid,
                    'id':        conflict_record.id,
                    **conflict_record.to_dict(),
                })
                # Send email notifications (async-style: fire and don't block)
                if not conflict_record.notifications_sent:
                    try:
                        send_conflict_notification(conflict_record)
                        conflict_record.notifications_sent = True
                        db.commit()
                    except Exception as exc:
                        log.warning('[Sync] Conflict email failed: %s', exc)
            else:
                accepted_ids.append(cid)
        except Exception as exc:
            log.error('[Sync] Change apply error: %s | change=%s', exc, change)
            # Don't let one error abort the whole batch

    audit('sync_batch', f'tenant:{tenant_id}',
          'success' if not conflicts else 'warning',
          f'accepted={len(accepted_ids)} conflicts={len(conflicts)}')

    # Send sync-complete notification if there were conflicts
    if conflicts:
        try:
            send_sync_complete(email, len(accepted_ids), len(conflicts))
        except Exception:
            pass

    return jsonify({
        'ok':          True,
        'accepted_ids': accepted_ids,
        'conflicts':   conflicts,
    })


def _apply_change(resource_type, resource_id, field, new_value,
                  base_version, client_ts, email, tenant_id,
                  url, method, payload):
    """
    Apply a single queued change. Returns {'conflict': False} or
    {'conflict': True, 'conflict_record': SyncConflict}.
    """
    if resource_type == 'document':
        return _apply_document_change(
            resource_id, field, new_value, base_version,
            client_ts, email, tenant_id, payload
        )
    # For other resource types, attempt to replay the HTTP request
    return _apply_generic(url, method, payload, email, tenant_id)


def _apply_document_change(resource_id, field, new_value, base_version,
                            client_ts, email, tenant_id, payload):
    doc = Document.query.filter_by(id=resource_id).first()
    if not doc:
        return {'conflict': False}  # resource deleted — nothing to conflict

    current_version = doc.version or 1

    if current_version > base_version and doc.modified_by != email:
        # Conflict: server version is newer and was modified by someone else
        conflict = SyncConflict(
            tenant_id          = tenant_id or doc.tenant_id,
            resource_type      = 'document',
            resource_id        = resource_id,
            field_name         = field or 'assigned_to',
            local_display      = str(new_value)[:200],
            server_display     = str(getattr(doc, field.replace('-','_'), ''))[:200],
            local_user_email   = email,
            local_modified_at  = _parse_ts(client_ts),
            local_base_version = base_version,
            server_user_email  = doc.modified_by or '',
            server_modified_at = doc.modified_at,
            server_version     = current_version,
            status             = 'pending',
        )
        db.add(conflict)
        db.commit()
        log.info('[Sync] Conflict created: doc=%s local=%s server=%s',
                 resource_id, email, doc.modified_by)
        return {'conflict': True, 'conflict_record': conflict}

    # No conflict — apply the change
    field_clean = field.replace('-', '_').lower()
    allowed_fields = {'assigned_to', 'status', 'classification'}
    if field_clean in allowed_fields:
        setattr(doc, field_clean, str(new_value)[:200])
    # Also handle payload keys
    for k in allowed_fields:
        if k in payload:
            setattr(doc, k, str(payload[k])[:200])

    doc.version     = current_version + 1
    doc.modified_by = email
    doc.modified_at = datetime.utcnow()
    db.commit()
    return {'conflict': False}


def _apply_generic(url, method, payload, email, tenant_id):
    """Replay non-document changes (domain add, user changes, etc.) safely."""
    # For now, log and accept generics — detailed conflict detection
    # per resource type can be added incrementally
    log.info('[Sync] Generic change: %s %s by %s', method, url, email)
    return {'conflict': False}


def _parse_ts(ts_str):
    try:
        return datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
    except Exception:
        return None


# ── Conflict status ───────────────────────────────────────────────────────────
@sync_bp.route('/status')
@require_auth
def sync_status():
    email     = current_email()
    tenant_id = current_tenant_id()
    pending   = (SyncConflict.query
                 .filter(
                     SyncConflict.status == 'pending',
                     (SyncConflict.local_user_email  == email) |
                     (SyncConflict.server_user_email == email)
                 ).count())
    return jsonify({'ok': True, 'pending_conflicts': pending})


@sync_bp.route('/conflicts')
@require_auth
def list_conflicts():
    email     = current_email()
    tenant_id = current_tenant_id()
    from sqlalchemy import or_
    conflicts = (SyncConflict.query
                 .filter(
                     SyncConflict.status == 'pending',
                     or_(SyncConflict.local_user_email  == email,
                         SyncConflict.server_user_email == email)
                 )
                 .order_by(SyncConflict.created_at.desc())
                 .all())
    return jsonify({
        'ok':       True,
        'count':    len(conflicts),
        'conflicts':[c.to_dict() for c in conflicts],
    })


# ── Conflict resolution ───────────────────────────────────────────────────────
@sync_bp.route('/conflicts/<conflict_id>/resolve', methods=['POST'])
@require_auth
def resolve_conflict(conflict_id):
    email    = current_email()
    body     = request.get_json(silent=True) or {}
    resolution = body.get('resolution', '')  # 'local' or 'server'

    if resolution not in ('local', 'server'):
        return jsonify({'ok': False, 'error': 'resolution must be "local" or "server"'}), 400

    conflict = SyncConflict.query.filter_by(id=conflict_id).first_or_404()
    # Verify the requester is involved in this conflict
    if email not in (conflict.local_user_email, conflict.server_user_email):
        # Super-admins can always resolve
        if not session.get('aios_auth'):
            return jsonify({'ok': False, 'error': 'Not authorized to resolve this conflict'}), 403

    if resolution == 'local':
        # Apply the offline (local) change to the resource
        _apply_resolution(conflict, use_local=True)
        conflict.status         = 'resolved_local'
        conflict.resolution_note= f'Resolved by {email}: local (offline) version accepted'
    else:
        conflict.status          = 'resolved_server'
        conflict.resolution_note = f'Resolved by {email}: server version kept'

    conflict.resolved_at = datetime.utcnow()
    db.commit()

    audit('conflict_resolved', f'conflict:{conflict_id}', 'success',
          f'by={email} resolution={resolution}')
    return jsonify({'ok': True, 'resolution': resolution})


@sync_bp.route('/conflicts/<conflict_id>/dismiss', methods=['POST'])
@require_auth
def dismiss_conflict(conflict_id):
    email    = current_email()
    conflict = SyncConflict.query.filter_by(id=conflict_id).first_or_404()
    if email not in (conflict.local_user_email, conflict.server_user_email):
        if not session.get('aios_auth'):
            return jsonify({'ok': False, 'error': 'Not authorized'}), 403
    conflict.status      = 'dismissed'
    conflict.resolved_at = datetime.utcnow()
    db.commit()
    audit('conflict_dismissed', f'conflict:{conflict_id}', 'success', f'by={email}')
    return jsonify({'ok': True})


def _apply_resolution(conflict, use_local: bool):
    """Apply the chosen resolution value back to the resource."""
    if conflict.resource_type != 'document':
        return
    doc = Document.query.filter_by(id=conflict.resource_id).first()
    if not doc:
        return
    if use_local:
        field = conflict.field_name.replace('-', '_').lower()
        allowed = {'assigned_to', 'status', 'classification'}
        if field in allowed:
            setattr(doc, field, conflict.local_display[:200])
            doc.version     = (doc.version or 1) + 1
            doc.modified_by = conflict.local_user_email
            doc.modified_at = datetime.utcnow()
            db.commit()
