"""
Cryptographic helpers

```python
tk1 = jwt_encode({"foo": "bar", "val": 42}, private_key)
tk2 = jwt_decode(tk1, public_key)
logging.debug("JWTTest\n%s\n%s", tk1,tk2)
```
"""
import logging

from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization

import jwt

import app.lib.config as config


def jwt_encode(payload, private_key):
    if private_key is None or private_key.strip() == "":
        raise Exception("private key missing or malformed")
    return jwt.encode(payload, private_key, algorithm="RS256").decode("utf-8")


def jwt_decode(token, public_key):
    if public_key is None or public_key.strip() == "":
        raise Exception("public key missing or malformed")
    return jwt.decode(token, public_key, algorithm="RS256")


def system_private_key():
    private_key = config.get("jwt_privkey", None)
    if private_key is None or private_key.strip() == "":
        raise Exception("jwt_privkey configuration missing or malformed")
    return private_key


def system_public_key():
    public_key = config.get("jwt_pubkey", None)
    if public_key is None or public_key.strip() == "":
        raise Exception("jwt_pubkey configuration missing or malformed")
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