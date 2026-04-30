VERSION    = 'v3.2.20'
BUILD_DATE = '2026-04-30'

CHANGES = [
    'Enterprise security: OWASP Top 10 hardening (security.py)',
    'AES-256 per-tenant encryption at rest (encryption.py)',
    'Multi-tenant SQLAlchemy models with versioned sync conflict detection',
    'Multi-step account onboarding wizard with industry templates',
    'Super-admin management panel: clients, users, documents, domains, SMTP',
    'Document upload + parsing: PDF, DOCX, CSV, TXT with AI classification',
    'Custom domain registration with DNS TXT verification + SSL status',
    'Tenant user OTP login with session isolation',
    'CSRF, rate limiting, audit log, security headers',
    # v3.1.0 — Offline sync
    'PWA Service Worker: cache-first static, network-first pages, /offline fallback',
    'IndexedDB change queue + sync manager: auto-sync on reconnect',
    'Sync API: /api/sync/batch with version-based conflict detection',
    'Conflict UI panel with side-by-side comparison and email notifications',
    # v3.2.0 — TOTP 2FA + encrypted SMTP
    'TOTP authenticator app support: Google/Microsoft Authenticator (totp_bp.py)',
    'QR code enrollment with confirmation, brute-force lockout, email fallback',
    'Per-user encrypted TOTP secrets via HKDF — admin in AdminTOTP, tenant in TenantUser',
    'SystemConfig model: encrypted DB storage for SMTP and any system settings',
    'SMTP credentials encrypted with Fernet; admin UI at /admin/settings/smtp',
    'auth._deliver() and notify._smtp_cfg() use DB config with env var fallback',
    'check_authorized() — validates email/lockout without sending OTP (for TOTP flow)',
    # v3.2.6
    'SQLite busy_timeout=10000ms: prevents DB locked error on multi-worker gunicorn startup',
    # v3.2.7
    'Gunicorn: 1 worker + 4 threads — fixes OTP cross-worker memory split (in-memory _otp_store)',
    # v3.2.8
    'Always log OTP code via log.warning() in _deliver() — visible in Railway logs even if email fails',
    'Surface Resend suppression/error at log.error level for immediate diagnosis',
    # v3.2.9
    'OTP storage moved from in-memory dict to SQLite OTPCode table — survives restarts and deployments',
    'Resend auto-unsuppress: detects suppression error, removes address, retries send automatically',
    # v3.2.14
    'Gmail API over HTTPS: replaces SMTP (blocked by cloud IPs) — OAuth2 refresh token flow',
    '/admin/gmail-auth + /admin/gmail-callback: one-time browser authorization stores refresh token',
]
