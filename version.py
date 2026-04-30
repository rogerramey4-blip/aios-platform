VERSION    = 'v3.0.0'
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
]
