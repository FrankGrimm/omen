"""
Implementation of the user model.
"""
import logging
import uuid
from datetime import datetime, timedelta
import getpass
import sys

from passlib.hash import scrypt

from sqlalchemy import Column, Integer, String, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.orm.attributes import flag_dirty, flag_modified

from flask import flash

from app.lib.database_internals import Base
import app.lib.config as config
import app.lib.crypto as crypto
from app.lib.models.activity import Activity

PW_MINLEN = 5
VALID_ROLES = set(['annotator', 'curator'])
LOGIN_DISABLED = "disabled"


class User(Base):
    __tablename__ = 'users'

    uid = Column(Integer, primary_key=True)
    email = Column(String, nullable=False)
    displayname = Column(String, nullable=True)
    pwhash = Column(String, nullable=False)
    usermetadata = Column(JSON, nullable=True)

    datasets = relationship("Dataset", back_populates="owner")
    annotations = relationship("Annotation")

    @staticmethod
    def minimum_password_length():
        return PW_MINLEN

    @staticmethod
    def is_valid_role(annorole):
        return annorole in VALID_ROLES

    @staticmethod
    def userlist(dbsession, exclude_system_user=True):
        allusers = dbsession.query(User).all()

        if exclude_system_user:
            return [userobj for userobj in allusers if not userobj.is_system_user()]
        return allusers

    @staticmethod
    def validate_newuser(email, pw1, pw2):
        if not email or not pw1 or not pw2:
            flash("Missing email or password", "warning")
            return False
        if pw1 != pw2:
            flash("Password and confirmation do not match", "warning")
            return False
        if len(pw1) < User.minimum_password_length():
            flash("Passwords need to be at least "
                  + str(User.minimum_password_length())
                  + " characters long.", "error")
            return False
        return True

    @staticmethod
    def create_user(dbsession, email=None):
        logging.info("creating user")
        if email is None:
            email = input("E-Mail: ")
        pw1 = getpass.getpass("Password: ")
        pw2 = getpass.getpass("Confirm password: ")
        if not email or not pw1 or not pw2:
            logging.error("Missing email or password")
            sys.exit(1)
        if pw1 != pw2:
            logging.error("Password and confirmation do not match")
            sys.exit(1)

        if len(pw1) < PW_MINLEN:
            logging.error("Passwords need to be at least %s characters long.", PW_MINLEN)
            sys.exit(1)

        pwhash = scrypt.hash(pw1)
        del pw1
        del pw2

        logging.info("inserting new user")
        inserted, obj = User.insert_user(dbsession, email, pwhash)
        if inserted:
            logging.info("created user %s", obj)
        else:
            logging.error("user already exists %s", obj)

    @staticmethod
    def insert_user(dbsession, email, pwhash, displayname=None):
        existing = User.by_email(dbsession, email, doraise=False)
        if existing is not None:
            return (False, existing)

        newobj = User(email=email, pwhash=pwhash, displayname=displayname)
        dbsession.add(newobj)

        dbsession.commit()

        newobj = User.by_email(dbsession, email)
        return (True, newobj)

    @staticmethod
    def system_user(dbsession):
        system_account = User.by_email(dbsession, "SYSTEM", doraise=False)
        if system_account is None:
            logging.debug("System account not found, creating.")
            newobj = User(email="SYSTEM", pwhash=LOGIN_DISABLED, displayname="System")
            dbsession.add(newobj)
            dbsession.commit()
            logging.debug("System account created.")
        else:
            logging.debug("System account found.")
        return system_account

    @staticmethod
    def by_email(dbsession, email, doraise=True):
        qry = dbsession.query(User).filter_by(email=email)

        if doraise:
            return qry.one()

        return qry.one_or_none()

    @staticmethod
    def by_id(dbsession, uid, no_error=False):
        if isinstance(uid, User):
            return uid
        if isinstance(uid, str):
            uid = int(uid)
        if no_error:
            return dbsession.query(User).filter_by(uid=uid).one_or_none()
        return dbsession.query(User).filter_by(uid=uid).one()

    def __init__(self, uid=None, email=None, pwhash=None, displayname=None):
        self.uid = uid
        self.email = email
        self.pwhash = pwhash
        self.displayname = displayname
        self._cached_df = None

    def is_system_user(self):
        return self.email == "SYSTEM"

    def get_name(self):
        if self.displayname is not None and self.displayname.strip() != '':
            return self.displayname.strip()
        return self.email

    def verify_password(self, pw):
        if self.pwhash is None or self.pwhash == LOGIN_DISABLED:
            return False

        return scrypt.verify(pw, self.pwhash)

    def change_password(self, dbsession, curpw, pw1, pw2):
        if not curpw or not pw1 or not pw2:
            raise Exception("All fields mandatory")

        if not self.verify_password(curpw):
            raise Exception("Invalid credentials")

        if pw1 != pw2:
            raise Exception("Password and confirmation do not match")

        newpwhash = scrypt.hash(pw1)
        self.pwhash = newpwhash
        dbsession.merge(self)

        return self.verify_password(pw1)

    def has_keypair(self):
        privkey = self.get_metadata("jwt_privkey", None)
        pubkey = self.get_metadata("jwt_pubkey", None)
        if privkey is None or privkey.strip() == "":
            return False
        if pubkey is None or pubkey.strip() == "":
            return False
        return True

    def get_private_key(self, dbsession):
        if not self.has_keypair():
            self.invalidate_keys(dbsession)
        return self.get_metadata("jwt_privkey", None)

    def get_public_key(self, dbsession):
        if not self.has_keypair():
            self.invalidate_keys(dbsession)
        return self.get_metadata("jwt_pubkey", None)

    def invalidate_invite(self, dbsession, invite_uuid, claimed_by=None):
        user_invites = self.get_invites("all")
        for invite in user_invites:
            if invite.get("uuid", "") != invite_uuid:
                continue
            invite['claimed_by'] = claimed_by.uid
            invite['status'] = 'claimed'

        self.set_metadata(dbsession, "pending_invites", user_invites)

    def invalidate_keys(self, dbsession):
        logging.info("Invalidating user specific key pair for %s", self)
        self.set_metadata(dbsession, "jwt_privkey", None)
        self.set_metadata(dbsession, "jwt_pubkey", None)

        private_key, public_key = crypto.generate_keypair()
        self.set_metadata(dbsession, "jwt_privkey", private_key)
        self.set_metadata(dbsession, "jwt_pubkey", public_key)

    def dirty(self, dbsession):
        flag_dirty(self)
        flag_modified(self, "usermetadata")
        dbsession.add(self)

    def set_metadata(self, dbsession, key, new_value):
        if self.usermetadata is None:
            self.usermetadata = {}
        self.usermetadata[key] = new_value
        self.dirty(dbsession)

    def get_metadata(self, key, default_value=None):
        if self.usermetadata is None:
            self.usermetadata = {}
        return self.usermetadata.get(key, default_value)

    def get_invites(self, query_status="all"):
        if query_status is None:
            query_status = "all"

        matching_invites = []
        for invite in self.get_metadata("pending_invites", []):
            invite_status = invite.get("status", None)
            if invite_status is None:
                invite_status = "pending"
            invite['status'] = invite_status

            if query_status in ("all", invite_status):
                matching_invites.append(invite)

        return matching_invites

    def new_api_token(self, dbsession, description):
        token_uuid = str(uuid.uuid4())
        token_create_timestamp = datetime.utcnow().isoformat()
        token_payload = {
                "by": self.uid,
                "type": "api_token",
                "created": token_create_timestamp,
                "uuid": token_uuid,
                "description": description
        }

        private_key = self.get_private_key(dbsession)
        new_token = crypto.jwt_encode(token_payload, private_key)
        full = {"metadata": token_payload, "token": new_token}
        _tokens = self.get_api_tokens()
        _tokens.append(full)
        self.set_metadata(dbsession, "api_tokens", _tokens)

        return full

    def revoke_api_token(self, dbsession, revoke_uuid):
        _tokens = self.get_api_tokens()

        revoked = None
        for api_token in _tokens:
            api_token_meta = api_token['metadata']
            if api_token_meta['uuid'] == revoke_uuid:
                revoked = api_token

        _tokens.remove(revoked)
        self.set_metadata(dbsession, "api_tokens", _tokens)

        revoked['metadata']['status'] = "REVOKED"
        return {"revoked": revoked['metadata']}

    def validate_api_token(self, dbsession, token):
        public_key = self.get_public_key(dbsession)
        token_data = crypto.jwt_decode(token, public_key)

        if 'uuid' not in token_data:
            raise crypto.InvalidTokenException("token is missing required attribute - uuid")

        _tokens = self.get_api_tokens()

        uuid_matches = False
        for stored in _tokens:
            stored_uuid = stored.get("metadata", {}).get("uuid", None)
            if stored_uuid is None or stored_uuid != token_data['uuid']:
                continue

            uuid_matches = True
            break

        if not uuid_matches:
            raise crypto.InvalidTokenException("Token is invalid, revoked, or contains an unknown UUID.")

        return token_data

    def get_api_tokens(self, metadata_only=False, check_validity=False, dbsession=None):
        _tokens = self.get_metadata("api_tokens", [])
        if check_validity:
            if dbsession is None:
                raise Exception("validity check requires active dbsession")

            for token in _tokens:
                token_metadata = token['metadata']
                token_metadata['valid'] = self.validate_api_token(dbsession, token['token']) is not None
        if metadata_only:
            _tokens = [token['metadata'] for token in _tokens]
        return _tokens

    def validate_invite(self, dbsession, token):
        public_key = self.get_public_key(dbsession)
        invite_data = crypto.validate(token, public_key)

        if 'uuid' not in invite_data:
            raise crypto.InvalidTokenException("token is missing required attribute - uuid")

        pending_invites = self.get_invites("pending")

        uuid_matches = False
        for invite in pending_invites:
            invite_uuid = invite.get("uuid", None)
            if invite_uuid is None or invite_uuid != invite_data['uuid']:
                continue

            uuid_matches = True
            break

        if not uuid_matches:
            raise crypto.InvalidTokenException("Token is invalid, contains an unknown UUID, or was already used.")

        return invite_data

    def create_invite(self, dbsession):
        """
        Generate a signed invitation for the given user object at the current timestamp.
        """

        invite_uuid = str(uuid.uuid4())
        invite_timestamp = datetime.utcnow().isoformat()
        token_payload = {
                "by": self.uid,
                "type": "invite",
                "created": invite_timestamp,
                "uuid": invite_uuid
        }

        private_key = self.get_private_key(dbsession)
        invite_token = crypto.jwt_encode(token_payload, private_key)

        all_invites = self.get_invites("all")
        all_invites.append(token_payload)

        self.set_metadata(dbsession, "pending_invites", all_invites)

        return invite_token

    def purge_invites(self, dbsession):
        max_age_hours = config.get_int("invite_max_age", 48)
        user_invites = self.get_invites("all")

        still_valid = []
        for invite in user_invites:
            token_created = invite.get("created", None)
            if token_created is None:
                continue

            try:
                token_timestamp = datetime.fromisoformat(token_created)
            except ValueError as ve:
                raise crypto.InvalidTokenException("failed to decode created attribute: %s" % ve)

            max_age_hours = config.get_int("invite_max_age", 48)
            token_age = (datetime.utcnow() - token_timestamp)

            cur_dt = datetime.utcnow()
            if not cur_dt - timedelta(hours=max_age_hours) <= token_timestamp <= cur_dt:
                logging.debug("purging expired token, age %s", token_age)
                continue

            still_valid.append(invite)

        if len(still_valid) != len(user_invites):
            logging.debug("Purging %s expired invites, %s remain pending.",
                          len(user_invites) - len(still_valid),
                          len(still_valid))

            self.set_metadata(dbsession, "pending_invites", still_valid)

    def __str__(self):
        return "[User #%s, %s]" % (self.uid, self.email)

    @staticmethod
    def activity_prefix():
        return "USER:"

    def activity_target(self):
        return "USER:%s" % self.uid
