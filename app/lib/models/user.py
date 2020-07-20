"""
Implementation of the user model.
"""
from sqlalchemy import Column, Integer, String, JSON, ForeignKey, ForeignKeyConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.orm.attributes import flag_dirty, flag_modified

import logging
from passlib.hash import scrypt
import getpass
import sys

from app.lib.database_internals import Base

PW_MINLEN = 5
VALID_ROLES = set(['annotator', 'curator'])


class User(Base):
    __tablename__ = 'users'

    uid = Column(Integer, primary_key=True)
    email = Column(String, nullable=False)
    displayname = Column(String, nullable=True)
    pwhash = Column(String, nullable=False)

    datasets = relationship("Dataset")
    annotations = relationship("Annotation")

    @staticmethod
    def is_valid_role(annorole):
        return annorole in VALID_ROLES

    @staticmethod
    def userlist(dbsession):
        return dbsession.query(User).all()

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
            logging.error("Passwords need to be at least %s characters long." % PW_MINLEN)
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
    def insert_user(dbsession, email, pwhash):
        existing = User.by_email(dbsession, email, doraise=False)
        if existing is not None:
            return (False, existing)

        newobj = User(email=email, pwhash=pwhash)
        dbsession.add(newobj)

        dbsession.commit()

        newobj = User.by_email(dbsession, email)
        return (True, newobj)

    @staticmethod
    def by_email(dbsession, email, doraise=True):
        qry = dbsession.query(User).filter_by(email=email)

        if doraise:
            return qry.one()

        return qry.one_or_none()

    @staticmethod
    def by_id(dbsession, uid):
        if isinstance(uid, User):
            return uid
        if isinstance(uid, str):
            uid = int(uid)
        return dbsession.query(User).filter_by(uid=uid).one()

    def __init__(self, uid=None, email=None, pwhash=None):
        self.uid = uid
        self.email = email
        self.pwhash = pwhash
        self._cached_df = None

    def get_name(self):
        if self.displayname is not None and self.displayname.strip() != '':
            return self.displayname.strip()
        return self.email

    def verify_password(self, pw):
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

    def __str__(self):
        return "[User #%s, %s]" % (self.uid, self.email)


