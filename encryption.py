"""
Per-tenant AES encryption (Fernet / AES-128-CBC + HMAC-SHA256) for data at rest.
Master key from ENCRYPTION_KEY env var (base64url-encoded 32 bytes).
If absent, derived from SECRET_KEY via SHA-256 — set ENCRYPTION_KEY in production.
Per-tenant key derived via HKDF so each tenant's data cannot decrypt another's.
"""
import os
import base64
import hashlib
import logging
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.backends import default_backend

log = logging.getLogger(__name__)
_MASTER: bytes | None = None


def _master() -> bytes:
    global _MASTER
    if _MASTER is None:
        raw = os.getenv('ENCRYPTION_KEY', '')
        if raw:
            try:
                padded = raw + '=' * (-len(raw) % 4)
                decoded = base64.urlsafe_b64decode(padded)
                _MASTER = decoded[:32].ljust(32, b'\x00')
            except Exception:
                _MASTER = hashlib.sha256(raw.encode()).digest()
        else:
            sk = (os.getenv('SECRET_KEY', 'aios-insecure-dev-key')).encode()
            _MASTER = hashlib.sha256(sk).digest()
            log.warning('[AIOS Enc] ENCRYPTION_KEY not set — using SECRET_KEY derivation. Set ENCRYPTION_KEY in production.')
    return _MASTER


def _fernet(tenant_id: str) -> Fernet:
    """Derive a unique Fernet key per tenant via HKDF-SHA256."""
    info = f'aios-tenant-v1:{tenant_id}'.encode()
    kdf  = HKDF(algorithm=hashes.SHA256(), length=32, salt=None,
                info=info, backend=default_backend())
    key_bytes = kdf.derive(_master())
    return Fernet(base64.urlsafe_b64encode(key_bytes))


def encrypt(tenant_id: str, data: bytes) -> bytes:
    return _fernet(tenant_id).encrypt(data)


def decrypt(tenant_id: str, token: bytes) -> bytes:
    return _fernet(tenant_id).decrypt(token)


def encrypt_str(tenant_id: str, text: str) -> str:
    return encrypt(tenant_id, text.encode()).decode()


def decrypt_str(tenant_id: str, token: str) -> str:
    try:
        return decrypt(tenant_id, token.encode()).decode()
    except (InvalidToken, Exception) as exc:
        log.error('[AIOS Enc] Decryption failed for tenant %s: %s', tenant_id, exc)
        return ''
