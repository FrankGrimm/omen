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
    token_age = (datetime.utcnow() - token_timestamp)
    decoded_data["token_age"] = str(token_age)

    cur_dt = datetime.utcnow()
    if not cur_dt - timedelta(hours=max_age_hours) <= token_timestamp <= cur_dt:
        raise InvalidTokenException("Token age %s exceeds maximum of %sh" % (token_age, max_age_hours))

    return decoded_data


def jwt_encode(payload, private_key):
    if private_key is None or private_key.strip() == "":
        raise InvalidTokenException("private key missing or malformed")
    return jwt.encode(payload, private_key, algorithm="RS256").decode("utf-8")


def jwt_decode(token, public_key):
    if public_key is None or public_key.strip() == "":
        raise InvalidTokenException("public key missing or malformed")
    return jwt.decode(token, public_key, algorithm="RS256")


def system_private_key():
    private_key = config.get("jwt_privkey", None)
    if private_key is None or private_key.strip() == "":
        raise InvalidTokenException("jwt_privkey configuration missing or malformed")
    return private_key


def system_public_key():
    public_key = config.get("jwt_pubkey", None)
    if public_key is None or public_key.strip() == "":
        raise InvalidTokenException("jwt_pubkey configuration missing or malformed")
    return public_key


def initialize():
    if config.get("jwt_privkey", "") != "":
        logging.debug("jwt_privkey is set, not reinitializing crypto")
        return

    logging.info("jwt_privkey not set in config, reinitializing crypto")
    # config.store("testkey", "testval")

    private_key, public_key = generate_keypair()

    config.store("jwt_privkey", private_key)
    config.store("jwt_pubkey", public_key)

    logging.debug("crypto reinitialization done")


def generate_keypair():
    key = rsa.generate_private_key(
            backend=default_backend(),
            public_exponent=65537,
            key_size=2048)

    private_key = key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption())
    public_key = key.public_key().public_bytes(
            serialization.Encoding.OpenSSH,
            serialization.PublicFormat.OpenSSH
            )

    return private_key.decode("utf-8"), public_key.decode("utf-8")
