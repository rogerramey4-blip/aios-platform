"""
SQLAlchemy multi-tenant models for AIOS.

Data layer is driven by DATABASE_URL:
  • set  → managed Postgres (Railway/Render). Persists across deploys. PRODUCTION.
  • unset → file-backed WAL SQLite (aios_tenants.db). Local dev only — the
            container filesystem is EPHEMERAL on Railway/Render, so SQLite loses
            all tenants/users/documents on every redeploy. Never run prod on it.
"""
import os
import uuid
from datetime import datetime

from sqlalchemy import (
    create_engine, Column, String, Integer, DateTime,
    Boolean, Text, ForeignKey, UniqueConstraint, event
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker, scoped_session, Query as _BaseQuery
from werkzeug.exceptions import NotFound

_DATABASE_URL = os.getenv('DATABASE_URL', '').strip()
if _DATABASE_URL:
    # Managed Postgres. Some providers still emit the legacy 'postgres://' scheme,
    # which SQLAlchemy dropped — normalize it to 'postgresql://'.
    if _DATABASE_URL.startswith('postgres://'):
        _DATABASE_URL = 'postgresql://' + _DATABASE_URL[len('postgres://'):]
    _IS_SQLITE = False
    _engine = create_engine(
        _DATABASE_URL,
        pool_pre_ping=True,   # transparently drop connections killed by idle timeouts
        pool_recycle=280,     # recycle before typical 300s managed-PG idle cutoff
        echo=False,
    )
else:
    # Local-dev fallback only — see module docstring; do NOT use in production.
    DB_PATH = os.getenv('TENANT_DB_PATH', 'aios_tenants.db')
    _IS_SQLITE = True
    _engine = create_engine(
        f'sqlite:///{DB_PATH}',
        connect_args={'check_same_thread': False},
        echo=False,
    )

if _IS_SQLITE:
    @event.listens_for(_engine, 'connect')
    def _set_pragmas(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute('PRAGMA journal_mode=WAL')
        cur.execute('PRAGMA foreign_keys=ON')
        cur.execute('PRAGMA synchronous=NORMAL')
        cur.execute('PRAGMA busy_timeout=10000')
        cur.close()

class _Query(_BaseQuery):
    """Adds Flask-SQLAlchemy-style 404 helpers (this project uses plain SQLAlchemy)."""
    def get_or_404(self, ident):
        rv = self.get(ident)
        if rv is None:
            raise NotFound()
        return rv

    def first_or_404(self):
        rv = self.first()
        if rv is None:
            raise NotFound()
        return rv

_Session = sessionmaker(bind=_engine, query_cls=_Query)
db = scoped_session(_Session)

Base = declarative_base()
Base.query = db.query_property()

INDUSTRIES = ['agency', 'legal', 'construction', 'medical', 'brokerage', 'hvac', 'plumbing', 'restaurant']
PLANS      = ['trial', 'starter', 'growth', 'enterprise']
ROLES      = ['admin', 'member', 'builder']
# 'builder' = an AIE-side implementer assigned to ONE tenant with full config rights
# over that tenant's AIOS (integrations, documents, domains, the client's own users,
# settings) via UI and CLI. Scoped, revocable, never cross-tenant, never super-admin.

# Default scopes granted to a builder's API token unless narrowed at issue time.
API_SCOPES = [
    'integrations:read', 'integrations:write',
    'documents:read',    'documents:write',
    'domains:read',      'domains:write',
    'users:read',        'users:write',
    'settings:read',     'settings:write',
    'agents:read',       'agents:write',
]

AGENT_STATUSES = ['active', 'idle', 'paused', 'draft']


class Tenant(Base):
    __tablename__ = 'tenants'

    id            = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    industry      = Column(String(20),  nullable=False)
    firm_name     = Column(String(200), nullable=False)
    firm_sub      = Column(String(50),  default='')
    contact_name  = Column(String(200), default='')
    contact_email = Column(String(200), default='')
    contact_phone = Column(String(50),  default='')
    plan          = Column(String(20),  default='trial')
    status        = Column(String(20),  default='active')   # active | suspended | trial
    subdomain     = Column(String(100), unique=True, nullable=True)
    notes         = Column(Text,        default='')
    created_at    = Column(DateTime,    default=datetime.utcnow)
    updated_at    = Column(DateTime,    default=datetime.utcnow, onupdate=datetime.utcnow)

    users        = relationship('TenantUser',        back_populates='tenant', cascade='all, delete-orphan')
    documents    = relationship('Document',          back_populates='tenant', cascade='all, delete-orphan')
    domains      = relationship('Domain',            back_populates='tenant', cascade='all, delete-orphan')
    integrations = relationship('TenantIntegration', back_populates='tenant', cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'id': self.id, 'industry': self.industry, 'firm_name': self.firm_name,
            'firm_sub': self.firm_sub, 'contact_name': self.contact_name,
            'contact_email': self.contact_email, 'contact_phone': self.contact_phone,
            'plan': self.plan, 'status': self.status, 'subdomain': self.subdomain,
            'notes': self.notes,
            'created_at': self.created_at.isoformat() if self.created_at else '',
        }


class TenantUser(Base):
    __tablename__ = 'tenant_users'

    id         = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id  = Column(String(36), ForeignKey('tenants.id'), nullable=False)
    email      = Column(String(200), nullable=False, unique=True)
    name       = Column(String(200), default='')
    title      = Column(String(100), default='')
    role       = Column(String(20),  default='member')   # admin | member
    active          = Column(Boolean,     default=True)
    last_login      = Column(DateTime,    nullable=True)
    created_at      = Column(DateTime,    default=datetime.utcnow)
    totp_secret_enc = Column(Text,        default='')
    totp_enabled    = Column(Boolean,     default=False)

    tenant = relationship('Tenant', back_populates='users')


class Document(Base):
    __tablename__ = 'documents'

    id             = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id      = Column(String(36), ForeignKey('tenants.id'), nullable=False)
    filename       = Column(String(500), nullable=False)
    content_type   = Column(String(100), default='')
    encrypted_blob = Column(Text,        default='')   # Fernet token (base64)
    size_bytes     = Column(Integer,     default=0)
    classification = Column(String(100), default='Unclassified')
    assigned_to    = Column(String(200), default='')
    status         = Column(String(50),  default='pending')  # pending|reviewed|archived
    summary_enc    = Column(Text,        default='')   # Fernet-encrypted plain-text summary
    uploaded_by    = Column(String(200), default='')
    uploaded_at    = Column(DateTime,    default=datetime.utcnow)
    # Versioning for offline conflict detection
    version        = Column(Integer,     default=1)
    modified_by    = Column(String(200), default='')
    modified_at    = Column(DateTime,    default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant = relationship('Tenant', back_populates='documents')


class Domain(Base):
    __tablename__ = 'domains'

    id                 = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id          = Column(String(36), ForeignKey('tenants.id'), nullable=False)
    domain             = Column(String(200), nullable=False, unique=True)
    verification_token = Column(String(64),  default=lambda: secrets_token())
    verified           = Column(Boolean,     default=False)
    ssl_status         = Column(String(50),  default='pending')  # pending|active|error
    cname_target       = Column(String(300), default='')
    added_at           = Column(DateTime,    default=datetime.utcnow)
    verified_at        = Column(DateTime,    nullable=True)

    tenant = relationship('Tenant', back_populates='domains')


class AuditLog(Base):
    __tablename__ = 'audit_log'

    id         = Column(Integer,     primary_key=True, autoincrement=True)
    ts         = Column(DateTime,    default=datetime.utcnow)
    user_email = Column(String(200), default='')
    tenant_id  = Column(String(36),  nullable=True)
    action     = Column(String(100), default='')
    resource   = Column(String(300), default='')
    ip_addr    = Column(String(50),  default='')
    user_agent = Column(String(500), default='')
    result     = Column(String(20),  default='success')  # success|failure|warning
    detail     = Column(Text,        default='')


class SyncConflict(Base):
    """
    Tracks conflicts when an offline user's queued change collides with
    a server-side change made by a different user during the offline period.
    Both users are notified via email; either can resolve via the UI.
    """
    __tablename__ = 'sync_conflicts'

    id                  = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id           = Column(String(36), ForeignKey('tenants.id'), nullable=True)
    resource_type       = Column(String(50),  default='')   # 'document', 'tenant', 'domain'
    resource_id         = Column(String(36),  default='')
    field_name          = Column(String(100), default='')
    # Encrypted values (Fernet) so no plaintext leaks at rest
    local_value_enc     = Column(Text,        default='')
    server_value_enc    = Column(Text,        default='')
    # Human-readable display values (truncated, not sensitive)
    local_display       = Column(String(300), default='')
    server_display      = Column(String(300), default='')
    local_user_email    = Column(String(200), default='')
    local_modified_at   = Column(DateTime,    nullable=True)
    local_base_version  = Column(Integer,     default=0)
    server_user_email   = Column(String(200), default='')
    server_modified_at  = Column(DateTime,    nullable=True)
    server_version      = Column(Integer,     default=0)
    status              = Column(String(30),  default='pending')
    # pending | resolved_local | resolved_server | dismissed
    resolution_note     = Column(Text,        default='')
    notifications_sent  = Column(Boolean,     default=False)
    created_at          = Column(DateTime,    default=datetime.utcnow)
    resolved_at         = Column(DateTime,    nullable=True)

    def to_dict(self, include_encrypted=False):
        return {
            'id':                self.id,
            'resource_type':     self.resource_type,
            'resource_id':       self.resource_id,
            'field_name':        self.field_name,
            'local_display':     self.local_display,
            'server_display':    self.server_display,
            'local_user_email':  self.local_user_email,
            'local_modified_at': self.local_modified_at.isoformat() if self.local_modified_at else None,
            'local_base_version':self.local_base_version,
            'server_user_email': self.server_user_email,
            'server_version':    self.server_version,
            'status':            self.status,
            'created_at':        self.created_at.isoformat() if self.created_at else None,
        }


class AdminTOTP(Base):
    """TOTP authenticator secrets for super-admin accounts."""
    __tablename__ = 'admin_totp'
    email           = Column(String(200), primary_key=True)
    totp_secret_enc = Column(Text,    default='')
    totp_enabled    = Column(Boolean, default=False)
    created_at      = Column(DateTime, default=datetime.utcnow)


class SystemConfig(Base):
    """Encrypted system-wide config (SMTP credentials, etc.)."""
    __tablename__ = 'system_config'
    key        = Column(String(100), primary_key=True)
    value_enc  = Column(Text,    default='')
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


def get_config(key: str, default: str = '') -> str:
    """Read an encrypted system config value, falling back to env var."""
    try:
        rec = SystemConfig.query.filter_by(key=key).first()
        if rec and rec.value_enc:
            from encryption import decrypt_str
            val = decrypt_str('_system', rec.value_enc)
            if val:
                return val
    except Exception:
        pass
    return os.getenv(key, default)


def set_config(key: str, value: str):
    """Encrypt and persist a system config value."""
    from encryption import encrypt_str
    rec = SystemConfig.query.filter_by(key=key).first()
    if not rec:
        rec = SystemConfig(key=key)
        db.add(rec)
    rec.value_enc  = encrypt_str('_system', value)
    rec.updated_at = datetime.utcnow()
    db.commit()


def secrets_token():
    import secrets
    return secrets.token_hex(32)


class TenantIntegration(Base):
    """Per-tenant encrypted credentials and connection state for each external platform."""
    __tablename__ = 'tenant_integrations'
    __table_args__ = (UniqueConstraint('tenant_id', 'platform_key', name='uq_tenant_platform'),)

    id               = Column(String(36),  primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id        = Column(String(36),  ForeignKey('tenants.id'), nullable=False)
    platform_key     = Column(String(50),  nullable=False)
    status           = Column(String(20),  default='disconnected')   # disconnected|connected|error
    creds_enc        = Column(Text,        default='')   # encrypted JSON of all credential fields
    token_expires_at = Column(DateTime,    nullable=True)
    last_tested      = Column(DateTime,    nullable=True)
    last_test_ok     = Column(Boolean,     default=False)
    last_test_msg    = Column(String(500), default='')
    connected_at     = Column(DateTime,    nullable=True)
    connected_by     = Column(String(200), default='')

    tenant = relationship('Tenant', back_populates='integrations')


class OTPCode(Base):
    """Persisted OTP codes — survives restarts and works across workers."""
    __tablename__ = 'otp_codes'
    id         = Column(Integer, primary_key=True)
    email      = Column(String(320), nullable=False, index=True)
    code       = Column(String(6),   nullable=False)
    expires_at = Column(DateTime,    nullable=False)
    attempts   = Column(Integer,     default=0)


class ApiToken(Base):
    """
    Scoped personal access token for CLI / REST automation.

    Security model (mirrors GitHub PATs):
      • Only the SHA-256 *hash* of the secret is stored — the plaintext is shown
        once at creation and is never recoverable.
      • Every token is bound to exactly one tenant_id; the API constrains all
        calls to that tenant regardless of what the caller requests.
      • Revocable instantly (revoked flag) and auto-expiring (expires_at).
      • Tied to a TenantUser — deactivating that user disables all their tokens.
    """
    __tablename__ = 'api_tokens'

    id           = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id    = Column(String(36), ForeignKey('tenants.id'),      nullable=False)
    user_id      = Column(String(36), ForeignKey('tenant_users.id'), nullable=False)
    name         = Column(String(120), default='')        # e.g. "Kevin's laptop CLI"
    token_prefix = Column(String(20),  default='')         # display hint, e.g. aios_pat_3f9c
    token_hash   = Column(String(64),  nullable=False, index=True)   # sha256 hex of secret
    scopes       = Column(String(300), default='')         # csv subset of API_SCOPES
    created_by   = Column(String(200), default='')         # super-admin who issued it
    created_at   = Column(DateTime,    default=datetime.utcnow)
    last_used_at = Column(DateTime,    nullable=True)
    last_used_ip = Column(String(50),  default='')
    expires_at   = Column(DateTime,    nullable=True)
    revoked      = Column(Boolean,     default=False)
    revoked_at   = Column(DateTime,    nullable=True)

    def is_valid(self) -> bool:
        if self.revoked:
            return False
        if self.expires_at and datetime.utcnow() > self.expires_at:
            return False
        return True

    def to_dict(self):
        return {
            'id':           self.id,
            'name':         self.name,
            'token_prefix': self.token_prefix,
            'scopes':       [s for s in (self.scopes or '').split(',') if s],
            'created_by':   self.created_by,
            'created_at':   self.created_at.isoformat() if self.created_at else None,
            'last_used_at': self.last_used_at.isoformat() if self.last_used_at else None,
            'last_used_ip': self.last_used_ip,
            'expires_at':   self.expires_at.isoformat() if self.expires_at else None,
            'revoked':      bool(self.revoked),
            'valid':        self.is_valid(),
        }


class TenantAgent(Base):
    """
    A per-tenant agent definition built/configured by a Client Builder.

    Demo agents shipped in app.py (AGENTS_DETAIL) are static templates; this table
    holds the real, editable agents a builder creates for their assigned client.
    Display fields (name/type/status/description) are plain columns so listing
    needs no decryption; the richer config (instructions/prompt, schedule, model,
    integrations, triggers) is stored as a per-tenant Fernet-encrypted JSON blob,
    consistent with documents and integration credentials.
    """
    __tablename__ = 'tenant_agents'
    __table_args__ = (UniqueConstraint('tenant_id', 'key', name='uq_tenant_agent_key'),)

    id          = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id   = Column(String(36), ForeignKey('tenants.id'), nullable=False)
    key         = Column(String(80),  nullable=False)     # slug, unique within tenant
    name        = Column(String(200), nullable=False)
    agent_type  = Column(String(60),  default='Custom')   # Monitor/Generator/Composer/…
    status      = Column(String(20),  default='draft')    # active|idle|paused|draft
    description = Column(Text,         default='')
    config_enc  = Column(Text,         default='')         # Fernet JSON: instructions, schedule, model, integrations, triggers
    created_by  = Column(String(200), default='')
    created_at  = Column(DateTime,    default=datetime.utcnow)
    updated_at  = Column(DateTime,    default=datetime.utcnow, onupdate=datetime.utcnow)

    def set_config(self, cfg: dict):
        from encryption import encrypt_str
        import json as _json
        self.config_enc = encrypt_str(self.tenant_id, _json.dumps(cfg or {}))

    def get_config(self) -> dict:
        if not self.config_enc:
            return {}
        from encryption import decrypt_str
        import json as _json
        try:
            return _json.loads(decrypt_str(self.tenant_id, self.config_enc) or '{}')
        except Exception:
            return {}

    def to_dict(self, include_config: bool = False) -> dict:
        d = {
            'id':          self.id,
            'key':         self.key,
            'name':        self.name,
            'agent_type':  self.agent_type,
            'status':      self.status,
            'description': self.description,
            'created_by':  self.created_by,
            'created_at':  self.created_at.isoformat() if self.created_at else None,
            'updated_at':  self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_config:
            d['config'] = self.get_config()
        return d


def _col_ddl(col) -> str:
    """Build an `<type> [DEFAULT <const>]` clause for ALTER TABLE ADD COLUMN.
    Columns are added nullable (no NOT NULL) so they can backfill existing rows."""
    import logging
    try:
        type_sql = col.type.compile(dialect=_engine.dialect)
    except Exception:
        type_sql = 'TEXT'
    default = ''
    d = col.default
    if d is not None and getattr(d, 'is_scalar', False):
        val = d.arg
        if isinstance(val, bool):
            # Postgres BOOLEAN wants TRUE/FALSE; SQLite stores 1/0.
            default = f' DEFAULT {("TRUE" if val else "FALSE") if not _IS_SQLITE else (1 if val else 0)}'
        elif isinstance(val, (int, float)):
            default = f' DEFAULT {val}'
        elif isinstance(val, str):
            default = " DEFAULT '" + val.replace("'", "''") + "'"
    return type_sql + default


def _migrate():
    """
    Backfill columns introduced after a table was first created. SQLite's
    create_all() makes missing tables but never ALTERs existing ones, so older
    databases drift behind the models (e.g. tenant_users.totp_enabled,
    documents.version). Generic: adds any model column absent from its table.
    Idempotent; each ALTER is isolated so one failure can't block the rest.
    """
    import logging
    from sqlalchemy import inspect, text
    log = logging.getLogger(__name__)
    insp = inspect(_engine)
    for table_name, table in Base.metadata.tables.items():
        if not insp.has_table(table_name):
            continue
        existing = {c['name'] for c in insp.get_columns(table_name)}
        for col in table.columns:
            if col.name in existing:
                continue
            try:
                with _engine.begin() as conn:
                    conn.execute(text(
                        f'ALTER TABLE {table_name} ADD COLUMN {col.name} {_col_ddl(col)}'))
                log.warning('[AIOS] migrated: added %s.%s', table_name, col.name)
            except Exception as exc:
                log.warning('[AIOS] could not add %s.%s: %s', table_name, col.name, exc)


def init_db():
    import logging
    log = logging.getLogger(__name__)
    # Make the active DB backend self-evident in deploy logs (warning level so it
    # surfaces on Railway/Render regardless of log filtering).
    if _IS_SQLITE:
        log.warning('[AIOS] DB backend: sqlite (%s) — EPHEMERAL on Railway/Render; '
                    'set DATABASE_URL to a managed Postgres for persistence', DB_PATH)
    else:
        log.warning('[AIOS] DB backend: %s @ %s', _engine.dialect.name, _engine.url.host)
    Base.metadata.create_all(_engine)
    try:
        _migrate()
    except Exception:
        log.warning('[AIOS] schema migration skipped', exc_info=True)
