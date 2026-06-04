VERSION    = 'v3.2.31'
BUILD_DATE = '2026-06-04'

CHANGES = [
    'Email: OTP / 2FA emails now actually send via the Gmail API over HTTPS (notify.py) — the OAuth flow at /admin/gmail-auth stored a GMAIL_REFRESH_TOKEN but nothing ever used it; delivery order is now Gmail API → SMTP → console/log. Fixes "email token not received" on Railway where outbound SMTP is blocked',
    'Email: /admin/test-email diagnostics now report Gmail API config + live token-refresh status instead of only SMTP/Resend',
    'Auth fix: ADMIN_TOTP_SECRETS secrets self-heal — parser keeps only valid base32 chars (A-Z, 2-7), so a secret pasted with spaces, an ellipsis from the truncated log line, or other punctuation no longer yields "Non-base32 digit found"',
    # v3.2.30
    'Auth fix: a malformed ADMIN_TOTP_SECRETS env value (e.g. a secret pasted with the space-grouping shown on the setup screen) no longer 500s the authenticator login — all whitespace is stripped from parsed secrets, and verify_totp_code degrades to a clean "use the email-code option" error instead of throwing on invalid base32',
    # v3.2.29
    'Auth fix: super-admins (kevin@) un-bricked — a stored authenticator secret that cannot be decrypted (e.g. after an ENCRYPTION_KEY/SECRET_KEY rotation) is now treated as no-2FA, so login falls back to an email code and re-enrollment instead of failing forever at the authenticator screen',
    'DB: generic auto-migration backfills model columns missing from existing tables (fixes tenant_users.totp_enabled/totp_secret_enc and documents.version/modified_* schema drift that 500-ed the admin panel)',
    'DB: added Flask-SQLAlchemy-style get_or_404/first_or_404 helpers to the plain-SQLAlchemy session — repairs all existing admin routes that relied on them',
    'Admin: new Users & Access panel (/admin/users) — roger@ and kevin@ can list every account, reset/disable 2FA (admins + tenant users), enable/disable accounts, change roles, and email a one-time login code (the OTP-system equivalent of a password reset)',
    'Startup: loud CRITICAL log when SECRET_KEY or ENCRYPTION_KEY is unset, since that is what breaks encrypted 2FA secrets across restarts',
    # v3.2.28
    'Auth: super-admins without TOTP are routed to /totp/setup immediately after email-OTP login — forces authenticator enrollment on first sign-in',
    'Auth: ADMIN_TOTP_SECRETS env var supports multiple admins (format: email1:secret1,email2:secret2) — survives redeploys for all enrolled super-admins; legacy ADMIN_TOTP_SECRET/ADMIN_TOTP_EMAIL still honored',
    'TOTP setup success page displays the full ADMIN_TOTP_SECRETS env line (all enrolled admins) with copy-to-clipboard for one-step Railway/Render persistence',
    'TOTP setup QR code now rendered as inline SVG (no Pillow dependency) — fixes blank-QR symptom on hosts where Pillow native libs fail to install; PNG retained as fallback',
    # v3.2.27
    'Landing page: "Who Should Have an AIOS?" section with 3 pain-point cards (pipeline follow-through, inbox triage, proactive outreach)',
    'Brokerage: Inbox Triage Agent + Referral Outreach Agent replace Market Analyst + CMA Bot in dashboard and agents detail',
    'Brokerage: guide tagline, email intelligence tips, quick-start, and FAQs refined to reflect inbox triage and proactive outreach pain points',
    # v3.2.26
    'Auth fix: ADMIN_TOTP_SECRET env var scoped to owning admin email only — kevin@ and charlene@ no longer forced into TOTP flow when only roger@ has enrolled',
    # v3.2.25
    'User Guide: /<industry>/guide for all 8 industries — quick start, sections, FAQs, print support (guide.html)',
    'Onboarding: guide auto-seeded as Document in new tenant vault on account creation',
    'Onboarding: HVAC, Plumbing, Restaurant added to industry selector',
    'Nav: User Guide link added to SETTINGS section for all industries',
    # v3.2.24
    'New industry templates: HVAC, Plumbing, Restaurant — full BRIEF, PIPELINE, AGENTS, LOGS, USE_CASES, EMAILS data',
    'Integration Connector Agents: 31 platforms (+ServiceTitan, Jobber, Toast POS, OpenTable, Yelp)',
    'Dashboard extra_panes: tech_board (HVAC), job_board (Plumbing), service_timeline (Restaurant)',
    'Pipeline page: hvac/plumbing/restaurant table views with status filters',
    # v3.2.23
    'Integration Connector Agents: 26 platforms, encrypted creds, OAuth2 flows, live test (integration_connectors.py)',
    'TenantIntegration model: per-tenant encrypted credential storage with connection health state',
    'Integrations UI: /<industry>/integrations — card grid, setup wizard, Save & Test, OAuth redirect, disconnect',
    # v3.2.22
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
