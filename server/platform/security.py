"""Password hashing with scrypt and opaque hashed session tokens."""
import base64
import hashlib
import hmac
import os
import secrets


def hash_password(password):
    if not isinstance(password, str) or len(password) < 4 or len(password) > 256:
        raise ValueError('password must be 4..256 characters')
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)
    return 'scrypt$' + base64.b64encode(salt).decode() + '$' + base64.b64encode(digest).decode()


def verify_password(password, stored):
    try:
        algo, salt, digest = stored.split('$')
        if algo != 'scrypt':
            return False
        expected = base64.b64decode(digest, validate=True)
        actual = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt, validate=True), n=16384, r=8, p=1)
        return hmac.compare_digest(expected, actual)
    except (ValueError, TypeError):
        return False


def new_token():
    return secrets.token_urlsafe(32)


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()
