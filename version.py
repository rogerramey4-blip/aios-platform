VERSION    = 'v3.1.0'
BUILD_DATE = '2026-04-30'

CHANGES = [
    'Enterprise security: OWASP Top 10 hardening (security.py)',
    'AES-256 per-tenant encryption at rest (encryption.py)',
    'Multi-tenant SQLAlchemy models: Tenant, TenantUser, Document, Domain, AuditLog',
    'Multi-step account onboarding wizard with industry templates (/onboard)',
    'Super-admin management panel: client health, users, documents, domains (/admin)',
    'Document upload + parsing: PDF, DOCX, CSV, TXT with AI classification',
    'Custom domain registration with DNS TXT verification + SSL status',
    'Tenant user OTP login with session isolation',
    'CSRF protection on all state-changing forms',
    'Rate limiting: 180 req/min global, 20 req/min on auth endpoints',
    'Full security audit log (AuditLog table)',
    'CSP, HSTS, X-Frame-Options, Permissions-Policy headers',
    # v3.1.0 — Offline redundancy + conflict sync
    'PWA Service Worker: cache-first for static, network-first for pages, offline fallback',
    'IndexedDB offline change queue (offline-db.js): queues edits when disconnected',
    'Sync manager (sync-manager.js): auto-syncs on reconnect, fetch/form interceptors',
    'Sync API blueprint (sync_bp): /api/sync/batch, /heartbeat, /conflicts, /resolve',
    'SyncConflict model: version-based conflict detection with encrypted value storage',
    'Conflict UI panel: side-by-side comparison, keep-local/keep-server/dismiss actions',
    'Email notifications: both users emailed on conflict detection (notify.py)',
    'Offline banner + conflict banner in base template',
    '/offline fallback page for full connectivity loss',
]
