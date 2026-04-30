"""
SQLAlchemy multi-tenant models for AIOS.
Single WAL-mode SQLite: aios_tenants.db
"""
import os
import uuid
from datetime import datetime

from sqlalchemy import (
    create_engine, Column, String, Integer, DateTime,
    Boolean, Text, ForeignKey, event
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker, scoped_session

DB_PATH = os.getenv('TENANT_DB_PATH', 'aios_tenants.db')
_engine = create_engine(
    f'sqlite:///{DB_PATH}',
    connect_args={'check_same_thread': False},
    echo=False,
)

@event.listens_for(_engine, 'connect')
def _set_pragmas(dbapi_conn, _):
    cur = dbapi_conn.cursor()
    cur.execute('PRAGMA journal_mode=WAL')
    cur.execute('PRAGMA foreign_keys=ON')
    cur.execute('PRAGMA synchronous=NORMAL')
    cur.close()

_Session = sessionmaker(bind=_engine)
db = scoped_session(_Session)

Base = declarative_base()
Base.query = db.query_property()

INDUSTRIES = ['agency', 'legal', 'construction', 'medical', 'brokerage']
PLANS      = ['trial', 'starter', 'growth', 'enterprise']
ROLES      = ['admin', 'member']


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

    users     = relationship('TenantUser', back_populates='tenant', cascade='all, delete-orphan')
    documents = relationship('Document',   back_populates='tenant', cascade='all, delete-orphan')
    domains   = relationship('Domain',     back_populates='tenant', cascade='all, delete-orphan')

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


def init_db():
    Base.metadata.create_all(_engine)
