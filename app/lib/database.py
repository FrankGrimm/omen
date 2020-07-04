from sqlalchemy import MetaData
from sqlalchemy.ext.declarative import declarative_base
Base = declarative_base()
from sqlalchemy import Column, Integer, String, JSON
from sqlalchemy import ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy_utils import database_exists, create_database
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from sqlalchemy.orm.attributes import flag_dirty, flag_modified

from contextlib import contextmanager

from datetime import datetime
from io import StringIO
import json
import uuid
import sys
import os
import pandas as pd
import numpy as np
import app.web as web
from passlib.hash import scrypt
import getpass
import atexit
from contextlib import contextmanager
from . import config

flask_db = None
migrate = None

def fprint(*args):
    print(*args, file=sys.stderr)

PW_MINLEN = 5

VALID_ROLES = set(['annotator', 'curator'])

@contextmanager
def session_scope():
    session = flask_db.session
    try:
        yield session
        session.commit()
    except:
        session.rollback()
        raise
    finally:
        session.close()

def shutdown():
    print("DB shutdown")
    engine = flask_db.get_engine()
    if not engine is None:
        engine.dispose()

class User(Base):
    __tablename__ = 'users'

    uid = Column(Integer, primary_key=True)
    email = Column(String, nullable=False)
    displayname = Column(String, nullable=True)
    pwhash = Column(String, nullable=False)

    datasets = relationship("Dataset")
    annotations = relationship("Annotation")

    def __init__(self, uid = None, email = None, pwhash = None):
        self.uid = uid
        self.email = email
        self.pwhash = pwhash
        self._cached_df = None

    def get_name(self):
        if not self.displayname is None and not self.displayname.strip() == '':
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

DATASET_CONTENT_CACHE = {}

class Dataset(Base):
    __tablename__ = 'datasets'

    dataset_id = Column(Integer, primary_key=True)

    owner_id = Column(Integer, ForeignKey("users.uid"), nullable=False)
    owner = relationship("User", back_populates="datasets", lazy="joined")

    dsannotations = relationship("Annotation")

    dsmetadata = Column(JSON, nullable=False)
    content = Column(String, nullable=True)

    persisted = False
    _cached_df = None

    def __repr__(self):
        return "<Dataset (%s)>" % self.get_name()

    def get_name(self):
        if self.dsmetadata is None:
            return self.dataset_id
        return self.dsmetadata.get("name", self.dataset_id)

    def get_text_column(self):
        textcol = self.dsmetadata.get("textcol", None)
        if textcol is None:
            return None
        return textcol

    def get_id_column(self):
        idcolumn = self.dsmetadata.get("idcolumn", None)
        if idcolumn is None:
            return None
        return idcolumn

    def get_roles(self, dbsession, user_obj):
        if type(user_obj) is str:
            user_obj = int(user_obj)
        if type(user_obj) is int:
            user_obj = by_id(dbsession, user_obj)
        if not user_obj:
            return set()

        roles = []
        if user_obj.uid == self.owner_id:
            # add all roles for owned datasets
            roles.append("owner")
            roles.append("annotator")
            roles.append("curator")
        else:
            curacl = self.get_acl()
            uid = str(user_obj.uid)
            if uid in curacl and not curacl[uid] is None:
                if curacl[uid] == "annotator":
                    roles.append("annotator")
                elif curacl[uid] == "curator":
                    roles.append("curator")
                    roles.append("annotator")

        return set(roles)

    def check_dataset(self):
        errorlist = []

        dsname = self.dsmetadata.get("name", None) if \
                not self.dsmetadata is None else None

        if dsname is None or dsname.strip() == '':
            errorlist.append("unnamed dataset")

        if not self.persisted and self.dataset_id is None:
            errorlist.append("not saved")

        if self.dsmetadata.get("hasdata", None) is None:
            errorlist.append("no data")

        if self.dsmetadata.get("taglist", None) is None or \
                len(self.dsmetadata.get("taglist", [])) == 0:
            errorlist.append("no tags defined")

        dferr = self.as_df(strerrors = True)
        if dferr is None:
            errorlist.append("no data")
        if type(dferr) is str:
            errorlist.append("data error: %s" % dferr)

        textcol = self.dsmetadata.get("textcol", None)
        if textcol is None:
            errorlist.append("no text column")
        if not dferr is None and \
                not type(dferr) is str and \
                not textcol in dferr.columns:
            errorlist.append("text column '%s' not found in data" % textcol)

        idcolumn = self.dsmetadata.get("idcolumn", None)
        if idcolumn is None:
            errorlist.append("no ID column")
        elif not dferr is None and \
                not type(dferr) is str and \
                not idcolumn in dferr.columns:
            errorlist.append("ID column '%s' not found in data" % idcolumn)

        # disabled. would annoy owners of private datasets
        #acl = self.dsmetadata.get("acl", [])
        #if acl is None or len(acl) == 0:
        #    errorlist.append("no annotators")

        if len(errorlist) is 0:
            return None
        return errorlist

    def accessible_by(self, dbsession, for_user):
        if self.dataset_id is None:
            raise Exception("cannot check accessibility. dataset needs to be committed first.")

        for dsid, ds in accessible_datasets(dbsession, for_user, include_owned=True).items():
            if ds is None or ds.dataset_id is None:
                continue
            if ds.dataset_id == self.dataset_id:
                return True
        return False

    def gettask(self, dbsession, for_user):
        if not self.accessible_by(dbsession, for_user):
            return None
        if not type(for_user) is User:
            raise Exception("dataset::gettask - argument for_user needs to be of type User")

        dsid = self.dataset_id
        check_result = self.check_dataset()
        if not check_result is None and len(check_result) > 0:
            return None

        dsname = self.get_name()
        task = {"id": dsid, "name": dsname,
                "dataset": self,
                "progress": 0,
                "size": self.dsmetadata.get("size", -1) or -1,
                "user_roles": self.get_roles(dbsession, for_user),
                "annos": self.annocount(dbsession, for_user),
                "annos_today": self.annocount_today(dbsession, for_user)
                }

        if task['size'] and task['size'] > 0 and task['annos'] and task['annos'] > 0:
            task['progress'] = round(task['annos'] / task['size'] * 100.0)
            task['progress_today'] = round(task['annos_today'] / task['size'] * 100.0)
            task['progress_beforetoday'] = task['progress'] - task['progress_today']

        return task

    def dirty(self, dbsession):
        flag_dirty(self)
        flag_modified(self, "dsmetadata")
        dbsession.add(self)

    def annotations(self, dbsession, foruser=None, user_column=None, hideempty=False, only_user=False):
        # TODO check roles of "foruser" and only expose annotations accordingly

        df = self.as_df()

        if type(foruser) is str:
            foruser = int(foruser)
        if type(foruser) is int:
            foruser = by_id(dbsession, foruser)

        user_roles = self.get_roles(dbsession, foruser)

        if not 'annotator' in user_roles and \
                not 'curator' in user_roles:
            raise Exception("Unauthorized, user %s does not have role 'curator'. Active roles: %s" % (foruser, user_roles))

        id_column = self.get_id_column()
        df = df.set_index(id_column)
        df['idxmerge'] = df.index.astype(str)

        annotation_columns = []
        target_user_column = None

        target_users = [foruser] # if user is annotator, only export and show their own annotations
        if 'curator' in user_roles and not only_user:
            # curator, also implied by owner role
            target_users = userlist(dbsession)

        for userobj in target_users:
            uannos = self.getannos(dbsession, userobj.uid, asdict=True)
            if uannos is None or len(uannos) == 0:
                continue
            uannos = pd.DataFrame.from_dict(uannos)
            uannos = uannos.drop(["uid"], axis=1)
            uannos = uannos.set_index("sample")

            df = pd.merge(df, uannos, left_on='idxmerge', right_index=True, how='left', indicator=False)
            # df = df.drop(["idxmerge"], axis=1)

            cur_user_column = "anno-%s-%s" % \
                    (userobj.uid, userobj.get_name())
            df = df.rename(columns={"annotation": cur_user_column})

            if not cur_user_column in annotation_columns:
                annotation_columns.append(cur_user_column)

            if not user_column is None and not foruser is None \
                    and userobj is foruser:
                target_user_column = cur_user_column

        if not target_user_column is None and not user_column is None and \
                target_user_column != user_column:

            df = df.rename(columns={target_user_column: user_column})
            annotation_columns.remove(target_user_column)
            if not user_column in annotation_columns:
                annotation_columns.append(user_column)

        if hideempty:
            df = df.dropna(axis=0, how="all", subset=annotation_columns)
        df = df.replace(np.nan, '', regex=True)
        return df, annotation_columns

    def get_taglist(self):
        return self.dsmetadata.get("taglist", [])

    def get_anno_votes(self, dbsession, sample_id, exclude_user=None):
        anno_votes = {}
        if not type(sample_id) is str:
            sample_id = str(sample_id)

        for tag in self.get_taglist():
            anno_votes[tag] = []

        for anno in dbsession.query(Annotation).filter_by(dataset_id=self.dataset_id, sample=sample_id).all():
            if not exclude_user is None and exclude_user is anno.owner:
                continue
            if anno.data is None or not 'value' in anno.data or anno.data['value'] is None or \
                    not anno.data['value'] in self.get_taglist():
                        continue
            anno_votes[anno.data['value']].append(anno.owner)

        return anno_votes

    def getannos(self, dbsession, uid, asdict=False):
        user_obj = by_id(dbsession, uid)
        annores = dbsession.query(Annotation).filter_by(owner_id=user_obj.uid, dataset_id=self.dataset_id).all()
        if not asdict:
            return annores

        resdict = {"sample": [], "uid": [], "annotation": []}
        for anno in annores:
            resdict['uid'].append( anno.owner_id )
            resdict['sample'].append( anno.sample )
            resdict['annotation'].append( anno.data['value'] \
                    if 'value' in anno.data and not anno.data['value'] is None \
                    else None)

        return resdict

    def getanno(self, dbsession, uid, sample):
        user_obj = by_id(dbsession, uid)
        sample = str(sample)
        anno_obj_data = {}

        anno_obj = dbsession.query(Annotation).filter_by(owner_id=user_obj.uid, dataset_id=self.dataset_id, sample=sample).one_or_none()
        if not anno_obj is None:
            anno_obj_data = anno_obj.data or {}

        return {
                "sample": sample,
                "data": anno_obj_data
               }

    def setanno(self, dbsession, uid, sample, value):
        user_obj = None
        if type(uid) is User:
            user_obj = uid
        else:
            user_obj = by_id(dbsession, uid)

        if user_obj is None:
            raise Exception("setanno() requires a user object or id")

        anno_data = {"updated": datetime.now().timestamp(), "value": value}

        sample=str(sample)
        existing_anno = dbsession.query(Annotation).filter_by(owner_id=user_obj.uid, dataset_id=self.dataset_id, sample=sample).one_or_none()
        if existing_anno is None:
            newanno = Annotation(owner=user_obj, dataset=self, sample=sample, data=anno_data)
            dbsession.add(newanno)
        else:
            existing_anno.data=anno_data
            dbsession.merge(existing_anno)
        dbsession.flush()

    def annocount_today(self, dbsession, uid):
        if type(uid) is User:
            uid = uid.uid
        allannos = dbsession.query(Annotation).filter_by(\
                dataset_id=self.dataset_id,
                owner_id=uid).all()

        count_today = 0
        for anno in allannos:
            if anno.data is None:
                continue
            anno_upd = anno.data.get("updated", None)
            if anno_upd is None:
                continue
            try:
                anno_upd = datetime.fromtimestamp(anno_upd)
            except Exception as ignored:
                fprint("malformed annotation timestamp %s" % anno_upd)
                continue

            if not anno_upd.date() == datetime.today().date():
                continue

            count_today += 1
        return count_today

    def annocount(self, dbsession, uid):
        if type(uid) is User:
            uid = uid.uid
        val = dbsession.query(Annotation).filter_by(\
                dataset_id=self.dataset_id,
                owner_id=uid).count()
        return val

    def set_role(self, dbsession, uid, role):
        if uid is None:
            return False
        if not type(uid) is str:
            uid = str(uid)
        if uid == self.owner_id:
            return False

        curacl = self.get_acl()
        if not uid in curacl:
            curacl[uid] = None

        fprint("changing role for user %s from %s to %s" % (uid, curacl[uid], role))
        curacl[uid] = role

        self.dsmetadata['acl'] = curacl
        self.dirty(dbsession)
        return True

    def get_acl(self):
        curacl = self.dsmetadata.get("acl", {})
        if not curacl:
            curacl = {}
        return curacl

    def as_df(self, strerrors = False):
        # TODO convert id_column and text_colum to string
        if strerrors:
            try:
                return self.as_df(strerrors = False)
            except Exception as e:
                return str(e)
        else:
            if not self._cached_df is None:
                # print("CACHE HIT(1)", self, self._cached_df.shape, file=sys.stderr)
                return self._cached_df.copy()

            if self.dataset_id in DATASET_CONTENT_CACHE and \
                    not DATASET_CONTENT_CACHE[self.dataset_id] is None:
                # print("CACHE HIT(2)", self, DATASET_CONTENT_CACHE[self.dataset_id].shape, file=sys.stderr)
                return DATASET_CONTENT_CACHE[self.dataset_id].copy()

            # print("CACHE MISS", self, file=sys.stderr)

            content = self.content
            content = StringIO(content)
            sep = self.dsmetadata.get("sep", ",")
            quotechar = self.dsmetadata.get("quotechar", '"')
            df = pd.read_csv(content, sep=sep, header='infer', quotechar=quotechar)
            self._cached_df = df.copy()
            DATASET_CONTENT_CACHE[self.dataset_id] = self._cached_df
            return df

    def invalidate(self):
        self._cached_df = None
        DATASET_CONTENT_CACHE[self.dataset_id] = None

    def update_size(self):
        self.invalidate()
        self.dsmetadata['updated'] = datetime.now().timestamp()

        if self.dsmetadata is None:
            self.dsmetadata = {}

        df = None
        try:
            df = self.as_df()
        except Exception as ignored:
            pass

        if not df is None:
            self.dsmetadata['size'] = df.shape[0]

class Annotation(Base):
    __tablename__ = 'annotations'

    owner_id = Column(Integer, ForeignKey("users.uid"), primary_key=True)
    owner = relationship("User", back_populates="annotations")

    dataset_id = Column(Integer, ForeignKey("datasets.dataset_id"), primary_key=True)
    dataset = relationship("Dataset", back_populates="dsannotations")

    sample = Column(String, primary_key=True)
    data = Column(JSON)

    def __repr__(self):
        return "<Annotation (dataset: %s, owner: %s, sample: %s, data: %s)>" % \
                (self.dataset_id, self.owner_id, self.sample, self.data)

def dataset_by_id(dbsession, dataset_id, user_id=None):
    qry = None
    if user_id is None:
        qry = dbsession.query(Dataset).filter_by(dataset_id=dataset_id)
    else:
        qry = dbsession.query(Dataset).filter_by(owner_id=user_id, dataset_id=dataset_id)
    return qry.one()

def all_datasets(dbsession):
    return dbsession.query(Dataset).all()

def my_datasets(dbsession, user_id):
    res = {}

    user_obj = user_id
    if not type(user_obj) is User:
        user_obj = by_id(dbsession, user_id)

    for ds in dbsession.query(Dataset).filter_by(owner=user_obj).all():
        if not ds or not ds.dataset_id:
            continue
        res[str(ds.dataset_id)] = ds

    return res

def dataset_roles(dbsession, user_id):
    res = {}

    user_obj = user_id
    if not type(user_obj) is User:
        user_obj = by_id(dbsession, user_id)
    all_datasets = accessible_datasets(dbsession, user_id, include_owned=True)

    for dataset_id, dataset in all_datasets.items():
        res[dataset_id] = dataset.get_roles(dbsession, user_obj)

    return res

def accessible_datasets(dbsession, user_id, include_owned=False):
    res = {}

    user_obj = user_id
    if not type(user_obj) is User:
        user_obj = by_id(dbsession, user_id)

    if include_owned:
        res = my_datasets(dbsession, user_id)

    for ds in all_datasets(dbsession):
        if not ds.dsmetadata:
            continue
        if not 'acl' in ds.dsmetadata:
            continue
        dsacl = ds.dsmetadata['acl']
        uid = str(user_obj.uid)

        if not uid in dsacl:
            continue
        if dsacl[uid] is None or \
                dsacl[uid] == '':
            continue
        res[str(ds.dataset_id)] = ds

    return res

def by_email(dbsession, email, doraise=True):
    qry = dbsession.query(User).filter_by(email=email)
    if doraise:
        return qry.one()
    else:
        try:
            return qry.one()
        except:
            return None

def by_id(dbsession, uid):
    return dbsession.query(User).filter_by(uid=uid).one()

def insert_user(dbsession, email, pwhash):
    existing = by_email(dbsession, email, doraise=False)
    if not existing is None:
        return (False, existing)

    newobj = User(email=email, pwhash=pwhash)
    dbsession.add(newobj)

    dbsession.commit()

    newobj = by_email(dbsession, email)
    return (True, newobj)

def annotation_tasks(dbsession, for_user):
    datasets = accessible_datasets(dbsession, for_user, include_owned = True)
    tasks = []

    for dsid, dataset in datasets.items():
        check_result = dataset.check_dataset()
        if not check_result is None and len(check_result) > 0:
            continue

        dsname = dataset.get_name()
        task = {"id": dsid, "name": dsname,
                "dataset": dataset,
                "progress": 0,
                "size": dataset.dsmetadata.get("size", -1) or -1,
                "user_roles": dataset.get_roles(dbsession, for_user),
                "annos": dataset.annocount(dbsession, for_user),
                "annos_today": dataset.annocount_today(dbsession, for_user)
                }

        if task['size'] and task['size'] > 0 and task['annos'] and task['annos'] > 0:
            task['progress'] = round(task['annos'] / task['size'] * 100.0)
            task['progress_today'] = round(task['annos_today'] / task['size'] * 100.0)
            task['progress_beforetoday'] = task['progress'] - task['progress_today']

        tasks.append(task)

    return tasks

def userlist(dbsession):
    return dbsession.query(User).all()

def create_user(dbsession, email=None):
    fprint("creating user")
    if email is None:
        email = input("E-Mail: ")
    pw1 = getpass.getpass("Password: ")
    pw2 = getpass.getpass("Confirm password: ")
    if not email or not pw1 or not pw2:
        fprint("Missing email or password")
        sys.exit(1)
    if pw1 != pw2:
        fprint("Password and confirmation do not match")
        sys.exit(1)

    if len(pw1) < PW_MINLEN:
        fprint("Passwords need to be at least %s characters long." % PW_MINLEN)
        sys.exit(1)

    pwhash = scrypt.hash(pw1)
    del pw1
    del pw2

    fprint("inserting")
    inserted, obj = insert_user(dbsession, email, pwhash)
    if inserted:
        fprint("created user", obj)
    else:
        fprint("user already exists", obj)

def dotest(dbsession):
    print("db::dotest")
    hashtest(dbsession)

    print("by_email", by_email(dbsession, "admin"))
    print("by_uid", by_id(dbsession, 1))

def connect():
    global flask_db

    print("[database] connect")
    connection_string = config.get("dbconnection", raise_missing = True)
    web.app.config["SQLALCHEMY_DATABASE_URI"] = connection_string
    if not config.get("db_debug", None) is None:
        web.app.config["SQLALCHEMY_ECHO"] = True
    web.app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    flask_db = SQLAlchemy(web.app, session_options={"expire_on_commit": False, "autoflush": False})
    migrate = Migrate(web.app, flask_db)

    masked_connstring = connection_string
    if 'password' in masked_connstring.lower():
        delim = masked_connstring.lower().index("password")
        masked_connstring = masked_connstring[:delim+ len("password")] + ":::" + "*" * len(masked_connstring[delim :])
    print("[database] connection string (masked): %s" % masked_connstring)
    db_pool_size = config.get("dbpool", "10", raise_missing=False)
    if not type(db_pool_size) is int:
        db_pool_size = int(db_pool_size)
    if not db_pool_size:
        db_pool_size = 1

    atexit.register(shutdown)
    print("[database] connected")

def init_db(skip_create=False):
    global flask_db
    connect()

    with web.app.app_context():
        with session_scope() as dbsession:
            if not skip_create:
                fprint("[schema update]")
                Base.metadata.create_all(bind=flask_db.get_engine())
                fprint("[schema update] completed")

            fprint("[users] system contains %s user accounts" % \
                    dbsession.query(User).count())
            fprint("[users] you can create users with the scripts/createuser script")

