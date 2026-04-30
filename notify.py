"""
AIOS Notification — sends transactional emails.
Priority: Resend API (if RESEND_API_KEY set) → SMTP → console fallback.
"""
import os
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

log = logging.getLogger(__name__)


def _cfg(key: str, default: str = '') -> str:
    """Read from encrypted DB config first, then env var."""
    try:
        from models import get_config
        return get_config(key) or os.getenv(key, default)
    except Exception:
        return os.getenv(key, default)


def send(to: str | list, subject: str, html: str, text: str = ''):
    """
    Send an email with cascading fallback:
      1. Resend API  (if RESEND_API_KEY set)
      2. SMTP        (if SMTP_HOST + SMTP_PASS set)
      3. Console     (always — guarantees OTP codes are never silently lost)
    """
    recipients = [to] if isinstance(to, str) else to

    # ── 1. Resend API ─────────────────────────────────────────────────────────
    resend_key = _cfg('RESEND_API_KEY')
    if resend_key:
        ok, err = _send_resend(recipients, subject, html, text, resend_key)
        if ok:
            log.info('[AIOS Notify] Resend accepted delivery to %s', recipients)
            return
        log.error('[AIOS Notify] Resend FAILED: %s', err)

    # ── 2. SMTP fallback ──────────────────────────────────────────────────────
    host     = _cfg('SMTP_HOST')
    port     = int(_cfg('SMTP_PORT') or 587)
    user     = _cfg('SMTP_USER')
    password = _cfg('SMTP_PASS')

    if host and user and password:
        from_addr = user
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From']    = f'AIOS <{from_addr}>'
        msg['To']      = ', '.join(recipients)
        if text:
            msg.attach(MIMEText(text, 'plain'))
        msg.attach(MIMEText(html, 'html'))
        try:
            if port == 465:
                with smtplib.SMTP_SSL(host, port, timeout=15) as srv:
                    srv.login(user, password)
                    srv.sendmail(from_addr, recipients, msg.as_string())
            else:
                with smtplib.SMTP(host, port, timeout=15) as srv:
                    srv.ehlo(); srv.starttls(); srv.login(user, password)
                    srv.sendmail(from_addr, recipients, msg.as_string())
            log.info('[AIOS Notify] SMTP sent "%s" to %s', subject, recipients)
            return
        except Exception as exc:
            log.warning('[AIOS Notify] SMTP failed (%s) — falling back to console', exc)

    # ── 3. Console fallback (always reaches here if both above fail) ──────────
    print('\n' + '='*54)
    print(f'  AIOS EMAIL — TO: {", ".join(recipients)}')
    print(f'  SUBJECT: {subject}')
    # Extract plain-text OTP code from HTML if present
    import re as _re
    codes = _re.findall(r'<div[^>]*font-size:44px[^>]*>(\d{6})<', html)
    if codes:
        print(f'  CODE: {codes[0]}')
    print('='*54 + '\n')
    log.warning('[AIOS Notify] Console fallback used for %s — check logs for code', recipients)


def _send_resend(recipients: list, subject: str, html: str, text: str, api_key: str) -> tuple:
    """Send via Resend HTTPS API. Returns (success: bool, error: str)."""
    try:
        import resend as _resend
        _resend.api_key = api_key
        custom_from = os.getenv('RESEND_FROM', '').strip()
        if custom_from and '@' in custom_from:
            from_addr = custom_from if '<' in custom_from else f'AIOS <{custom_from}>'
        else:
            from_addr = 'AIOS <onboarding@resend.dev>'
        log.info('[AIOS Notify] Resend from=%s to=%s', from_addr, recipients)
        params = {'from': from_addr, 'to': recipients, 'subject': subject, 'html': html}
        if text:
            params['text'] = text
        _resend.Emails.send(params)
        log.info('[AIOS Notify] Resend delivered "%s" to %s', subject, recipients)
        return True, ''
    except Exception as exc:
        log.error('[AIOS Notify] Resend error: %s', exc)
        return False, str(exc)


_CONFLICT_HTML = """<!DOCTYPE html>
<html><body style="margin:0;padding:24px;background:#0a0e14;font-family:'Inter',sans-serif;">
<div style="max-width:520px;margin:0 auto;background:#0d1117;border:1px solid #30363d;border-radius:12px;overflow:hidden;">
  <div style="padding:24px 28px 18px;border-bottom:1px solid #21262d;">
    <div style="font-size:26px;font-weight:900;letter-spacing:4px;color:#e6edf3;">
      A<span style="color:#e3b341;">IOS</span>
    </div>
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
    <a href="{app_url}" style="display:inline-block;background:#e3b341;color:#000;text-decoration:none;padding:10px 24px;border-radius:8px;font-size:13px;font-weight:800;">
      Review &amp; Resolve Conflict
    </a>
    <p style="font-size:12px;color:#484f58;margin:16px 0 0;">
      You can contact <a href="mailto:{other_user}" style="color:#e3b341;">{other_user}</a> if you need to coordinate before resolving.
    </p>
  </div>
  <div style="padding:14px 28px;background:#161b22;border-top:1px solid #21262d;font-size:11px;color:#484f58;text-align:center;">
    Powered by <span style="color:#e3b341;font-weight:700;">AI Evolution Services</span> &nbsp;·&nbsp; AIOS Sync System
  </div>
</div>
</body></html>"""


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

    # Email the offline user (their change was queued)
    html_local = _CONFLICT_HTML.format(
        name    = conflict.local_user_email or 'Team Member',
        message = (
            f'Your offline change to <strong>{conflict.resource_type}</strong> could not be '
            f'automatically merged — <strong>{conflict.server_user_email}</strong> '
            f'modified the same record while you were offline. Please review and choose which version to keep.'
        ),
        other_user = conflict.server_user_email or '',
        **params
    )
    if conflict.local_user_email:
        send(
            conflict.local_user_email,
            f'[AIOS] Sync conflict: your offline change needs review',
            html_local,
        )

    # Email the server-side user (their change created the conflict)
    html_server = _CONFLICT_HTML.format(
        name    = conflict.server_user_email or 'Team Member',
        message = (
            f'A sync conflict was detected on a <strong>{conflict.resource_type}</strong> record '
            f'you recently edited. <strong>{conflict.local_user_email}</strong> made a change '
            f'while offline that conflicts with your update. Please review together to decide which version to keep.'
        ),
        other_user = conflict.local_user_email or '',
        **params
    )
    if conflict.server_user_email and conflict.server_user_email != conflict.local_user_email:
        send(
            conflict.server_user_email,
            f'[AIOS] Sync conflict: a record you edited has a conflicting offline change',
            html_server,
        )


def send_sync_complete(email: str, accepted: int, conflicts: int, app_url: str = ''):
    """Notify user their offline changes were synced (with optional conflict summary)."""
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
