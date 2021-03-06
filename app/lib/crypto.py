"""
Cryptographic helpers

```python
tk1 = jwt_encode({"foo": "bar", "val": 42}, private_key)
tk2 = jwt_decode(tk1, public_key)
logging.debug("JWTTest\n%s\n%s", tk1,tk2)
```
"""
import logging

from datetime import datetime, timedelta

from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization

import jwt

import app.lib.database as db
import app.lib.config as config


class InvalidTokenException(Exception):
    pass


def validate(token, public_key):
    if public_key is None or public_key.strip() == "":
        raise InvalidTokenException("public key missing or malformed")

    decoded_data = jwt_decode(token, public_key)
    token_created = decoded_data.get("created", None)
    if token_created is None:
        raise InvalidTokenException("token is missing required field: created")
    try:
        token_timestamp = datetime.fromisoformat(token_created)
    except ValueError as ve:
        raise InvalidTokenException("failed to decode created attribute: %s" % ve)

    max_age_hours = config.get_int("invite_max_age", 48)
    token_age = datetime.utcnow() - token_timestamp
    decoded_data["token_age"] = str(token_age)

    cur_dt = datetime.utcnow()
    if not cur_dt - timedelta(hours=max_age_hours) <= token_timestamp <= cur_dt:
        raise InvalidTokenException("Token age %s exceeds maximum of %sh" % (token_age, max_age_hours))

    return decoded_data


def jwt_encode(payload, private_key):
    if private_key is None or private_key.strip() == "":
        raise InvalidTokenException("private key missing or malformed")
    return jwt.encode(payload, private_key, algorithm="RS256")


def jwt_decode(token, public_key):
    if public_key is None or public_key.strip() == "":
        raise InvalidTokenException("public key missing or malformed")
    return jwt.decode(token, public_key, algorithms=["RS256"], verify=True)


def system_private_key(dbsession):
    private_key = db.User.system_user(dbsession).get_private_key(dbsession)

    if private_key is None or private_key.strip() == "":
        raise InvalidTokenException("jwt_privkey configuration missing or malformed")
    return private_key


def jwt_decode_unsafe(token):
    if token is None:
        return None
    token = token.strip()
    return jwt.decode(token, algorithms=["RS256"], verify=False)


def system_public_key(dbsession):
    public_key = db.User.system_user(dbsession).get_public_key(dbsession)
    if public_key is None or public_key.strip() == "":
        raise InvalidTokenException("jwt_pubkey configuration missing or malformed")
    return public_key


def initialize():
    logging.debug("crypto initialization")


def generate_keypair():
    key = rsa.generate_private_key(backend=default_backend(), public_exponent=65537, key_size=2048)

    private_key = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    public_key = key.public_key().public_bytes(serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH)

    return private_key, public_key
