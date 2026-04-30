"""
AIOS Notification — sends transactional emails.
Primary:  SendGrid HTTP API (not blocked by Railway).
Fallback: console / Railway logs.
"""
import os
import json
import logging
import urllib.request
import urllib.error

log = logging.getLogger(__name__)


def _cfg(key: str, default: str = '') -> str:
    try:
        from models import get_config
        return get_config(key) or os.getenv(key, default)
    except Exception:
        return os.getenv(key, default)


def _send_sendgrid(recipients: list, subject: str, html: str, text: str = '') -> bool:
    api_key  = _cfg('SENDGRID_API_KEY')
    from_addr = _cfg('SENDGRID_FROM') or _cfg('SMTP_USER') or ''
    if not api_key or not from_addr:
        return False
    payload = {
        'personalizations': [{'to': [{'email': r} for r in recipients]}],
        'from':    {'email': from_addr},
        'subject': subject,
        'content': [],
    }
    if text:
        payload['content'].append({'type': 'text/plain', 'value': text})
    payload['content'].append({'type': 'text/html', 'value': html})
    req = urllib.request.Request(
        'https://api.sendgrid.com/v3/mail/send',
        data=json.dumps(payload).encode(),
        headers={
            'Authorization': f'Bearer {api_key}',
            'Content-Type':  'application/json',
        },
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            ok = resp.status in (200, 202)
            if ok:
                log.warning('[AIOS Notify] SendGrid sent "%s" to %s', subject, recipients)
            return ok
    except urllib.error.HTTPError as exc:
        body = exc.read(512).decode(errors='replace')
        log.error('[AIOS Notify] SendGrid HTTP %s: %s', exc.code, body)
        return False
    except Exception as exc:
        log.error('[AIOS Notify] SendGrid error: %s', exc)
        return False


def send(to: str | list, subject: str, html: str, text: str = ''):
    """Send via SendGrid HTTP API. Falls back to console if unconfigured."""
    recipients = [to] if isinstance(to, str) else to

    if _send_sendgrid(recipients, subject, html, text):
        return

    # Console fallback — always visible in Railway logs
    import re as _re
    codes = _re.findall(r'<div[^>]*font-size:44px[^>]*>(\d{6})<', html)
    print('\n' + '='*54, flush=True)
    print(f'  AIOS EMAIL — TO: {", ".join(recipients)}', flush=True)
    print(f'  SUBJECT: {subject}', flush=True)
    if codes:
        print(f'  CODE: {codes[0]}', flush=True)
    print('='*54 + '\n', flush=True)
    log.warning('[AIOS Notify] Console fallback used for %s', recipients)


def send_conflict_notification(conflict, app_url: str = ''):
    """Email both users involved in a sync conflict."""
    base_url = app_url or os.getenv('APP_URL', 'https://aios-platform.railway.app')
    resolve_url = f"{base_url}/api/sync/conflicts/{conflict.id}"
    params = {
        'resource_type': conflict.resource_type or 'record',
        'resource_id':   (conflict.resource_id or '')[:16],
        'local_user':    conflict.local_user_email or 'offline user',
        'server_user':   conflict.server_user_email or 'server user',
        'local_value':   (conflict.local_display or '')[:120],
        'server_value':  (conflict.server_display or '')[:120],
        'app_url':       resolve_url,
    }
    _CONFLICT_HTML = """<!DOCTYPE html>
<html><body style="margin:0;padding:24px;background:#0a0e14;font-family:'Inter',sans-serif;">
<div style="max-width:520px;margin:0 auto;background:#0d1117;border:1px solid #30363d;border-radius:12px;overflow:hidden;">
  <div style="padding:24px 28px 18px;border-bottom:1px solid #21262d;">
    <div style="font-size:26px;font-weight:900;letter-spacing:4px;color:#e6edf3;">A<span style="color:#e3b341;">IOS</span></div>
    <div style="font-size:11px;color:#484f58;letter-spacing:1px;text-transform:uppercase;margin-top:4px;">Sync Conflict Alert</div>
  </div>
  <div style="padding:24px 28px;">
    <p style="font-size:14px;color:#8b949e;margin:0 0 16px;">Hi {name},</p>
    <p style="font-size:14px;color:#8b949e;margin:0 0 16px;">{message}</p>
    <div style="background:#161b22;border:1px solid #30363d;border-radius:8px;padding:16px;margin-bottom:20px;">
      <div style="margin-bottom:10px;">
        <span style="font-size:11px;color:#484f58;text-transform:uppercase;letter-spacing:1px;">Resource</span>
        <div style="font-size:13px;color:#e6edf3;font-weight:600;margin-top:3px;">{resource_type} — {resource_id}</div>
      </div>
      <div style="display:flex;gap:16px;">
        <div style="flex:1;">
          <span style="font-size:11px;color:#3fb950;text-transform:uppercase;letter-spacing:1px;">Offline change by</span>
          <div style="font-size:12px;color:#e6edf3;margin-top:3px;">{local_user}</div>
          <div style="font-size:12px;color:#8b949e;margin-top:4px;">{local_value}</div>
        </div>
        <div style="flex:1;">
          <span style="font-size:11px;color:#e3b341;text-transform:uppercase;letter-spacing:1px;">Server change by</span>
          <div style="font-size:12px;color:#e6edf3;margin-top:3px;">{server_user}</div>
          <div style="font-size:12px;color:#8b949e;margin-top:4px;">{server_value}</div>
        </div>
      </div>
    </div>
    <a href="{app_url}" style="display:inline-block;background:#e3b341;color:#000;text-decoration:none;padding:10px 24px;border-radius:8px;font-size:13px;font-weight:800;">Review &amp; Resolve Conflict</a>
    <p style="font-size:12px;color:#484f58;margin:16px 0 0;">Contact <a href="mailto:{other_user}" style="color:#e3b341;">{other_user}</a> to coordinate before resolving.</p>
  </div>
  <div style="padding:14px 28px;background:#161b22;border-top:1px solid #21262d;font-size:11px;color:#484f58;text-align:center;">
    Powered by <span style="color:#e3b341;font-weight:700;">AI Evolution Services</span> &nbsp;·&nbsp; AIOS Sync System
  </div>
</div></body></html>"""
    if conflict.local_user_email:
        send(conflict.local_user_email,
             '[AIOS] Sync conflict: your offline change needs review',
             _CONFLICT_HTML.format(
                 name=conflict.local_user_email or 'Team Member',
                 message=(f'Your offline change to <strong>{conflict.resource_type}</strong> '
                          f'could not be automatically merged — <strong>{conflict.server_user_email}</strong> '
                          f'modified the same record while you were offline.'),
                 other_user=conflict.server_user_email or '', **params))
    if conflict.server_user_email and conflict.server_user_email != conflict.local_user_email:
        send(conflict.server_user_email,
             '[AIOS] Sync conflict: a record you edited has a conflicting offline change',
             _CONFLICT_HTML.format(
                 name=conflict.server_user_email or 'Team Member',
                 message=(f'A sync conflict was detected on a <strong>{conflict.resource_type}</strong> '
                          f'record you recently edited. <strong>{conflict.local_user_email}</strong> '
                          f'made a change while offline that conflicts with your update.'),
                 other_user=conflict.local_user_email or '', **params))


def send_sync_complete(email: str, accepted: int, conflicts: int, app_url: str = ''):
    if not email:
        return
    base = app_url or os.getenv('APP_URL', 'https://aios-platform.railway.app')
    status = (f'{accepted} change{"s" if accepted != 1 else ""} synced successfully.' if conflicts == 0
              else f'{accepted} change{"s" if accepted != 1 else ""} synced · '
                   f'<strong style="color:#e3b341">{conflicts} conflict{"s" if conflicts != 1 else ""} need your review</strong>')
    html = f"""<!DOCTYPE html>
<html><body style="margin:0;padding:24px;background:#0a0e14;font-family:'Inter',sans-serif;">
<div style="max-width:480px;margin:0 auto;background:#0d1117;border:1px solid #30363d;border-radius:12px;overflow:hidden;">
  <div style="padding:22px 28px 16px;border-bottom:1px solid #21262d;">
    <div style="font-size:26px;font-weight:900;letter-spacing:4px;color:#e6edf3;">A<span style="color:#e3b341;">IOS</span></div>
    <div style="font-size:11px;color:#484f58;letter-spacing:1px;text-transform:uppercase;margin-top:3px;">Sync Complete</div>
  </div>
  <div style="padding:22px 28px;">
    <p style="font-size:14px;color:#8b949e;margin:0 0 14px;">Your offline changes have been synced:</p>
    <p style="font-size:14px;color:#e6edf3;margin:0 0 20px;">{status}</p>
    {"<a href='"+base+"/api/sync/conflicts' style='display:inline-block;background:#e3b341;color:#000;text-decoration:none;padding:9px 22px;border-radius:8px;font-size:13px;font-weight:800;'>Review Conflicts</a>" if conflicts > 0 else ""}
  </div>
  <div style="padding:12px 28px;background:#161b22;border-top:1px solid #21262d;font-size:11px;color:#484f58;text-align:center;">
    Powered by <span style="color:#e3b341;font-weight:700;">AI Evolution Services</span>
  </div>
</div></body></html>"""
    send(email, '[AIOS] Offline changes synced', html)
