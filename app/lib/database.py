"""
Database model and utilities
"""
from contextlib import contextmanager

from datetime import datetime
import json
import os
import os.path
from io import StringIO
import sys
import getpass
import atexit

from passlib.hash import scrypt
from sqlalchemy.ext.declarative import declarative_base
Base = declarative_base()
from sqlalchemy import Column, Integer, String, JSON, ForeignKey, and_, ForeignKeyConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.orm.attributes import flag_dirty, flag_modified
from flask import flash
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate

import pandas as pd
import numpy as np

import app.web as web
from . import config

flask_db = None
migrate = None

PW_MINLEN = 5
VALID_ROLES = set(['annotator', 'curator'])


def fprint(*args):
    print(*args, file=sys.stderr)


@contextmanager
def session_scope():
    session = flask_db.session
    try:
        yield session
        session.commit()
    except Exception as e:
        fprint("rolling back transaction after error (%s)" % e)
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

    def __init__(self, uid=None, email=None, pwhash=None):
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

def prep_sql(sql):
    sql = "\n".join( filter(lambda line: line != "", map(str.strip, sql.strip().split("\n") )))
    return sql.strip()

class DatasetContent(Base):
    __tablename__ = "datasetcontent"

    sample_index = Column(Integer, autoincrement=True, primary_key=True)

    dataset_id = Column(Integer, ForeignKey("datasets.dataset_id"), primary_key=True)
    dataset = relationship("Dataset", back_populates="dscontent")

    sample = Column(String, primary_key=True)
    content = Column(String, nullable=False)

    annotations = relationship("Annotation")

    data = Column(JSON)

    def __repr__(self):
        return "<DatasetContent %s/%s (%s)>" % (
                self.dataset.get_name(),
                self.sample_index,
                self.sample
                )

"""
numpy safe JSON converter
adapted from https://stackoverflow.com/a/57915246
"""
class NpEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, np.integer):
            return int(obj)
        elif isinstance(obj, np.floating):
            return float(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        elif isinstance(obj, np.bool_):
            return bool(obj)
        else:
            return super(NpEncoder, self).default(obj)

class Dataset(Base):
    __tablename__ = 'datasets'

    dataset_id = Column(Integer, primary_key=True)

    owner_id = Column(Integer, ForeignKey("users.uid"), nullable=False)
    owner = relationship("User", back_populates="datasets", lazy="joined")

    dsannotations = relationship("Annotation")
    dscontent = relationship("DatasetContent")

    dsmetadata = Column(JSON, nullable=False)

    persisted = False
    _cached_df = None

    def empty(self):
        return not self.has_content()

    def has_content(self):
        if self.dscontent is None:
            return False
        return len(self.dscontent) > 0

    def content_query(self, dbsession):
        return dbsession.query(DatasetContent).filter_by(dataset_id=self.dataset_id)

    def __repr__(self):
        return "<Dataset (%s)>" % self.get_name()

    def get_name(self):
        if self.dsmetadata is None:
            return self.dataset_id
        return self.dsmetadata.get("name", self.dataset_id)

    def get_description(self):
        if self.dsmetadata is None:
            return ""
        return self.dsmetadata.get("description", "")

    def get_text_column(self):
        textcol = self.dsmetadata.get("textcol", None)
        if textcol is None:
            return None
        return textcol

    def get_size(self):
        return self.dsmetadata.get("size", -1) or -1

    def get_id_column(self):
        idcolumn = self.dsmetadata.get("idcolumn", None)
        if idcolumn is None:
            return None
        return idcolumn

    def get_task(self, dbsession, foruser):
        task = {"id": self.dataset_id,
                "name": self.get_name(),
                "dataset": self,
                "progress": 0,
                "size": self.get_size(),
                "annos": self.annocount(dbsession, foruser),
                "annos_today": self.annocount_today(dbsession, foruser)
                }
        return task

    def get_roles(self, dbsession, user_obj):
        if isinstance(user_obj, str):
            user_obj = int(user_obj)
        if isinstance(user_obj, int):
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

        if len(self.get_taglist()) == 0:
            errorlist.append("no tags defined")

        if self.empty():
            errorlist.append("no data")

        textcol = self.dsmetadata.get("textcol", None)
        if textcol is None:
            errorlist.append("no text column defined")

        idcolumn = self.dsmetadata.get("idcolumn", None)
        if idcolumn is None:
            errorlist.append("no ID column defined")

        if len(errorlist) == 0:
            return None
        return errorlist

    def accessible_by(self, dbsession, for_user):
        if self.dataset_id is None:
            raise Exception("cannot check accessibility. dataset needs to be committed first.")

        for _, ds in accessible_datasets(dbsession, for_user, include_owned=True).items():
            if ds is None or ds.dataset_id is None:
                continue
            if ds.dataset_id == self.dataset_id:
                return True
        return False

    def gettask(self, dbsession, for_user):
        if not self.accessible_by(dbsession, for_user):
            return None
        if not isinstance(for_user, User):
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

    def migrate_annotations(self, dbsession, old_name, new_name):
        migrated_annotations = 0

        for anno in dbsession.query(Annotation).filter_by( \
                dataset_id=self.dataset_id).all():

            if anno.data is None:
                continue
            anno_tag = anno.data.get("value", None)
            if anno_tag is None or not anno_tag == old_name:
                continue

            anno.data["value"] = new_name
            flag_dirty(anno)
            flag_modified(anno, "data")
            dbsession.add(anno)
            migrated_annotations += 1

        dbsession.flush()

        return migrated_annotations

    def annotations(self, dbsession, page=1, page_size=50, foruser=None,
            user_column=None, hideempty=False, only_user=False, with_content=True,
            query=None):

        # TODO query support

        foruser = by_id(dbsession, foruser)
        user_roles = self.get_roles(dbsession, foruser)

        if not 'annotator' in user_roles and \
                not 'curator' in user_roles:
            raise Exception("Unauthorized, user %s does not have role 'curator'. Active roles: %s" \
                                % (foruser, user_roles))

        if user_column is None:
            user_column = "annotation"

        sql_select = ""
        sql_where = ""
        field_list = ["dc.sample_index AS sample_index", "dc.sample AS sample_id"]
        if with_content:
            field_list.append("dc.content AS sample_content")

        params = {
                "dataset_id": self.dataset_id
                }

        if not query is None:
            sql_where += "\nAND dc.content LIKE %(query_pattern)s"
            if not query.startswith("%") and not query.endswith("%"):
                query = "%" + query + "%"
            params['query_pattern'] = query

        join_type = "LEFT " if hideempty else "LEFT OUTER"

        id_column = self.get_id_column()

        annotation_columns = []
        col_renames = {
                "sample_id": id_column,
                "sample_content": self.get_text_column()
                }

        if not foruser is None:
            sql_select += """
            {join_type} JOIN annotations AS usercol ON usercol.dataset_id = dc.dataset_id AND usercol.sample_index = dc.sample_index AND usercol.owner_id = %(foruser_join)s
            """.format(join_type=join_type, usercol=user_column)
            col_renames["usercol"] = user_column
            params['foruser_join'] = foruser.uid
            field_list.append("usercol.data->'value' AS usercol")
            annotation_columns.append(user_column)

        target_users = [foruser] # if user is annotator, only export and show their own annotations
        if 'curator' in user_roles and not only_user:
            # curator, also implied by owner role
            target_users = list(set(userlist(dbsession)) - set([foruser]))

        if not only_user:
            for user_obj in target_users:
                if user_obj is foruser:
                    continue

                sql_select += """
                {join_type} JOIN annotations AS "anno-{uid}" ON "anno-{uid}".dataset_id = dc.dataset_id AND "anno-{uid}".sample_index = dc.sample_index AND "anno-{uid}".owner_id = %(foruser_{uid})s
                """.format(join_type=join_type, uid=user_obj.uid)
                params["foruser_{uid}".format(uid=user_obj.uid)] = user_obj.uid
                field_list.append("\"anno-{uid}\".data->'value' AS \"anno-{uid}\"".format(uid=user_obj.uid))
                annotation_columns.append("anno-{uid}-{uname}".format(uid=user_obj.uid, uname=user_obj.email))
                col_renames["anno-{uid}".format(uid=user_obj.uid)] = "anno-{uid}-{uname}".format(uid=user_obj.uid, uname=user_obj.email)

        sql_where = """
        WHERE dc.dataset_id = %(dataset_id)s
        """ + sql_where

        sql = """
        SELECT {field_list} FROM datasetcontent AS dc
        {sql_select}
        {sql_where}
        """.format(field_list=", ".join(field_list),
                sql_select="\n" + sql_select.strip(),
                sql_where="\n" + sql_where.strip())

        sql_count = """
        SELECT COUNT(*) AS cnt FROM datasetcontent AS dc
        {sql_select}
        {sql_where}
        """.format(field_list=", ".join(field_list),
                sql_select="\n" + sql_select.strip(),
                sql_where="\n" + sql_where.strip())

        if page_size > 0:
            sql += "\nLIMIT %(page_size)s"
            params["page_size"] = page_size

        if page > 0 and page_size > 0:
            sql += "\nOFFSET %(page_onset)s"
            params["page_onset"] = (page - 1) * page_size

        sql = prep_sql(sql)
        fprint("DB_SQL_LOG", sql)

        df = pd.read_sql(sql,
                dbsession.bind,
                params=params)
        df_count = pd.read_sql(sql_count,
                dbsession.bind,
                params=params)

        df_count = df_count.loc[0, "cnt"]

        df = df.rename(columns=col_renames)

        return df, annotation_columns, df_count

    def set_taglist(self, newtags):
        if self.dsmetadata is None:
            self.dsmetadata = {}

        newtags = filter(lambda l: l is not None and l.strip() != '', newtags)
        newtags = map(lambda l: l.strip(), newtags)
        newtags = list(newtags)
        self.dsmetadata['taglist'] = newtags

    def update_tag_metadata(self, tag, newvalues):
        tag_metadata = self.dsmetadata.get("tagdetails", {})
        if tag not in tag_metadata:
            tag_metadata[tag] = {}

        for k, v in newvalues.items():
            tag_metadata[tag][k] = v

        self.dsmetadata['tagdetails'] = tag_metadata

    def get_taglist(self, include_metadata=False):
        tags = self.dsmetadata.get("taglist", None)
        tags = tags or []

        if not include_metadata:
            return tags

        tagdata = {}
        tag_metadata = self.dsmetadata.get("tagdetails", {})

        for tag in tags:
            curtag_metadata = tag_metadata.get(tag, {})
            tagdata[tag] = {
                    "icon": curtag_metadata.get("icon", None),
                    "color": curtag_metadata.get("color", None)
                    }

        return tagdata

    def get_anno_votes(self, dbsession, sample_id, exclude_user=None):
        anno_votes = {}
        if not isinstance(sample_id, str):
            sample_id = str(sample_id)

        for tag in self.get_taglist():
            anno_votes[tag] = []

        for anno in dbsession.query(Annotation).filter_by( \
                dataset_id=self.dataset_id, sample=sample_id).all():

            if not exclude_user is None and exclude_user is anno.owner:
                continue
            if anno.data is None or not 'value' in anno.data or anno.data['value'] is None or \
                    not anno.data['value'] in self.get_taglist():
                continue
            anno_votes[anno.data['value']].append(anno.owner)

        return anno_votes

    def getannos(self, dbsession, uid, asdict=False):
        user_obj = by_id(dbsession, uid)
        annores = dbsession.query(Annotation).filter_by( \
                    owner_id=user_obj.uid, dataset_id=self.dataset_id).all()
        if not asdict:
            return annores

        resdict = {"sample": [], "uid": [], "annotation": []}
        for anno in annores:
            resdict['uid'].append(anno.owner_id)
            resdict['sample'].append(anno.sample)
            resdict['annotation'].append(anno.data['value'] \
                    if 'value' in anno.data and not anno.data['value'] is None \
                    else None)

        return resdict

    def getanno(self, dbsession, uid, sample):
        user_obj = by_id(dbsession, uid)
        sample = str(sample)
        anno_obj_data = {}

        anno_obj = dbsession.query(Annotation).filter_by(owner_id=user_obj.uid, \
                        dataset_id=self.dataset_id, sample=sample).one_or_none()

        if not anno_obj is None:
            anno_obj_data = anno_obj.data or {}

        return {
                "sample": sample,
                "data": anno_obj_data
               }

    def setanno(self, dbsession, uid, sample, value):
        user_obj = by_id(dbsession, uid)

        if user_obj is None:
            raise Exception("setanno() requires a user object or id")

        anno_data = {"updated": datetime.now().timestamp(), "value": value}

        sample_obj = self.content_query(dbsession).filter_by(
                dataset_id = self.dataset_id,
                sample = sample,
                ).one()

        sample = str(sample)
        existing_anno = dbsession.query(Annotation).filter_by( \
                owner_id=user_obj.uid,
                dataset_id=self.dataset_id,
                sample=sample_obj.sample,
                sample_index=sample_obj.sample_index
                ).one_or_none()

        if existing_anno is None:
            newanno = Annotation(owner=user_obj,
                    dataset=self,
                    sample=sample_obj.sample,
                    sample_index=sample_obj.sample_index,
                    data=anno_data)
            dbsession.add(newanno)
        else:
            existing_anno.data = anno_data
            dbsession.merge(existing_anno)
        dbsession.flush()

    def annocount_today(self, dbsession, uid):
        if isinstance(uid, User):
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
            except ValueError as _:
                fprint("malformed annotation timestamp %s" % anno_upd)
                continue

            if anno_upd.date() != datetime.today().date():
                continue

            count_today += 1
        return count_today

    def annocount(self, dbsession, uid):
        if isinstance(uid, User):
            uid = uid.uid
        val = dbsession.query(Annotation).filter_by(\
                dataset_id=self.dataset_id,
                owner_id=uid).count()
        return val

    def set_role(self, dbsession, uid, role):
        if uid is None:
            return False

        if not isinstance(uid, str):
            uid = str(uid)
        if uid == self.owner_id:
            return False

        curacl = self.get_acl()
        if uid not in curacl:
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

    def import_content(self, dbsession, filename, dry_run):
        success = False
        errors = []
        preview_df = None

        sep = self.dsmetadata.get("sep", ",")
        quotechar = self.dsmetadata.get("quotechar", '"')

        if os.path.exists(filename):
            df = None
            try:
                df = pd.read_csv(filename, sep=sep, header='infer', quotechar=quotechar, escapechar="\\")
                if df is not None:
                    preview_df = df.head()
                    success = True
                else:
                    errors.append("could not load data")
            except Exception as pd_error:
                errors.append(str(pd_error))
                success = False

            if df is not None:
                if df.shape[0] < 1:
                    errors.append("did not recognize any content (no rows)")
                    success = False
                elif len(df.shape) <= 1:
                    errors.append("did not recognize any content (invalid shape)")
                    success = False
                elif df.shape[1] <= 2:
                    errors.append("sample file needs at least two columns, found: %s" % df.shape[1])
                    success = False

            if self.get_id_column() is None:
                errors.append("ID column not defined.")
                success = False
            elif not self.get_id_column() in df.columns:
                errors.append("ID column '%s' not found in dataset columns (%s)." % \
                        (self.get_id_column(), ", ".join(map(str, df.columns))))
            if self.get_text_column() is None:
                errors.append("Text column not defined.")
                success = False
            elif not self.get_text_column() in df.columns:
                errors.append("Text column '%s' not found in dataset columns (%s)." % \
                        (self.get_text_column(), ", ".join(map(str, df.columns))))

            import_count = 0
            merge_count = 0
            skip_count = 0
            if len(errors) == 0:
                if not dry_run:
                    id_column = self.get_id_column()
                    text_column = self.get_text_column()

                    fprint("[import] %s, sample count before: %s" % (self, len(self.dscontent)))
                    for index, row in df.iterrows():
                        sample_id = row[id_column]
                        if sample_id is None:
                            skip_count += 1
                            continue
                        sample_id = str(sample_id).strip()
                        if sample_id == "":
                            skip_count += 1
                            continue

                        sample_text = row[text_column]
                        if sample_text is None:
                            skip_count += 1
                            continue
                        sample_text = str(sample_text).strip()
                        if sample_text == "":
                            skip_count += 1
                            continue

                        sample_data = df.loc[index].replace(np.nan, "", regex=True).to_dict()
                        sample_data = json.dumps(sample_data, cls=NpEncoder)
                        sample_data = json.loads(sample_data)
                        if sample_data is not None:
                            if id_column in sample_data:
                                del sample_data[id_column]
                            if text_column in sample_data:
                                del sample_data[text_column]

                        existing = self.content_query(dbsession).filter_by(sample=sample_id).one_or_none()
                        if existing is not None:
                            existing.content = sample_text
                            existing.data = sample_data
                            merge_count += 1
                        else:
                            new_sample = DatasetContent()
                            new_sample.dataset = self
                            new_sample.dataset_id = self.dataset_id
                            new_sample.sample = sample_id
                            new_sample.content = sample_text
                            new_sample.data = sample_data
                            import_count += 1

                    dbsession.flush()
                    fprint("[import] %s, sample count after: %s" % (self, len(self.dscontent)))
                    # tmpsample = DatasetContent()
                    # tmpds = dataset_by_id(dbsession, 1)
                    # fprint(tmpds)
                    # tmpsample.dataset = tmpds
                    # tmpsample.sample = "12345"
                    # tmpsample.content = "DELETETHIS"
                    # fprint("-----------------------------")
                    # dbsession.add(tmpsample)
                    # fprint("-----------------------------")
                    # fprint("-----------------------------")
                    # fprint("smaple", tmpsample)
                    # dbsession.flush()

                else:
                    success = True
                    if len(errors) == 0:
                        errors.append("Preview only. Confirm below to import this data with current settings.")

            if import_count > 0 or merge_count > 0:
                flash("Imported %s samples (%s merged)" % (import_count, merge_count), "success")
            if skip_count > 0:
                flash("Skipped %s samples with empty ID or text" % skip_count, "warning")

        else:
            errors.append("temporary file %s does not exist anymore" % filename)

        return success, errors, preview_df

    """
    Returns the content of the dataset as a `pandas.DataFrame`.

    `page`: int, page onset

    `page_size`: int

    `extended`: If true, full rows will be returned (including the full original sample).
        Otherwise, and by default, the DataFrame will only contain sample identifiers,
        indices, and textual content.
    """
    def page(self, dbsession, page=1, page_size=10, extended=False, query=None):

        if page > 0:
            page -= 1

        samples = query
        if samples is None:
            samples = self.content_query(dbsession)

        if page_size > 0:
            samples = samples.limit(page_size)
        if page > 0 and page_size > 0:
            samples = samples.offset(page*page_size)

        id_column = self.get_id_column()
        text_column = self.get_text_column()
        frame_data = {
                "index": []
                }
        frame_data[id_column] = []
        frame_data[text_column] = []

        sample_count = 0
        for sample in samples.all():
            fprint(sample, type(sample))
            sample_count += 1

            frame_data["index"].append(sample.sample_index)
            frame_data[id_column].append(sample.sample)
            frame_data[text_column].append(sample.content)

            if extended:
                if sample.data is None:
                    for key in frame_data:
                        if key in ["index", id_column, text_column]:
                            continue
                        frame_data[key].append(None)
                else:
                    for key, value in sample.data.items():
                        if not key in frame_data:
                            frame_data[key] = []
                            if len(frame_data["index"]) > 0:
                                frame_data[key] = [None] * (len(frame_data["index"]) - 1)
                        frame_data[key].append(value)

        df = pd.DataFrame.from_dict(frame_data)
        df.set_index("index")
        return df

    """
    Returns the content of the dataset as a `pandas.DataFrame`.

    If strerrors is set to True, any errors while loading are returned instead of raised.

    If extended is set to True, full rows will be returned. Otherwise, and by default,
    the DataFrame will only contain sample identifiers and textual content.
    """
    def as_df_deprecated(self, strerrors=False, extended=False):
        # TODO convert id_column and text_column to string?
        df = None

        if strerrors:
            try:
                df = self.as_df(strerrors=False)
            except Exception as e:
                return str(e)
        else:
            if not self._cached_df is None:
                # print("CACHE HIT(1)", self, self._cached_df.shape, file=sys.stderr)
                return self._cached_df.copy()

            if self.dataset_id in DATASET_CONTENT_CACHE and \
                    not DATASET_CONTENT_CACHE[self.dataset_id] is None:
                return DATASET_CONTENT_CACHE[self.dataset_id].copy()

            # print("CACHE MISS", self, file=sys.stderr)

            content = self.content
            content = StringIO(content)
            self._cached_df = df.copy()
            DATASET_CONTENT_CACHE[self.dataset_id] = self._cached_df

        if not extended:
            columns = list([self.get_id_column(), self.get_text_column()])

            df = df.reset_index()
            df = df[columns]

        return df

    def invalidate(self):
        self._cached_df = None
        DATASET_CONTENT_CACHE[self.dataset_id] = None

    def update_size(self):
        self.invalidate()
        self.dsmetadata['updated'] = datetime.now().timestamp()

        if self.dsmetadata is None:
            self.dsmetadata = {}

        self.dsmetadata['size'] = len(self.dscontent) if self.has_content() else 0

class Annotation(Base):
    __tablename__ = 'annotations'

    owner_id = Column(Integer, ForeignKey("users.uid"), primary_key=True)
    owner = relationship("User", back_populates="annotations")

    dataset_id = Column(Integer, ForeignKey("datasets.dataset_id"), primary_key=True)
    dataset = relationship("Dataset", back_populates="dsannotations")

    sample = Column(String, primary_key=True)
    sample_index = Column(Integer, primary_key=True)

    data = Column(JSON)
    __table_args__ = (ForeignKeyConstraint([dataset_id, sample, sample_index],
                                           [DatasetContent.dataset_id, DatasetContent.sample, DatasetContent.sample_index]),
                      {})

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

    user_obj = by_id(dbsession, user_id)

    for ds in dbsession.query(Dataset).filter_by(owner=user_obj).all():
        if not ds or not ds.dataset_id:
            continue
        res[str(ds.dataset_id)] = ds

    return res

def dataset_roles(dbsession, user_id):
    res = {}

    user_obj = by_id(dbsession, user_id)

    all_user_datasets = accessible_datasets(dbsession, user_id, include_owned=True)

    for dataset_id, dataset in all_user_datasets.items():
        res[dataset_id] = dataset.get_roles(dbsession, user_obj)

    return res

def accessible_datasets(dbsession, user_id, include_owned=False):
    res = {}

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

    return qry.one_or_none()

def by_id(dbsession, uid):
    if isinstance(uid, User):
        return uid
    if isinstance(uid, str):
        uid = int(uid)
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

def task_calculate_progress(task):
    if task is None:
        return

    if task['size'] and task['size'] > 0 and task['annos'] and task['annos'] > 0:
        task['progress'] = round(task['annos'] / task['size'] * 100.0)
        task['progress_today'] = round(task['annos_today'] / task['size'] * 100.0)
        task['progress_beforetoday'] = task['progress'] - task['progress_today']

def annotation_tasks(dbsession, for_user):
    datasets = accessible_datasets(dbsession, for_user, include_owned=True)
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

        task_calculate_progress(task)

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

def connect():
    global flask_db, migrate

    print("[database] connect")
    connection_string = config.get("dbconnection", raise_missing=True)
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
    if not isinstance(db_pool_size, int):
        db_pool_size = int(db_pool_size)
    if not db_pool_size:
        db_pool_size = 1

    atexit.register(shutdown)
    print("[database] connected")

def init_db():
    global flask_db
    connect()

    with web.app.app_context():
        with session_scope() as dbsession:
            try:
                fprint("[users] system contains %s user accounts" % \
                        dbsession.query(User).count())
                fprint("[users] you can create users with the scripts/createuser script")
            except:
                fprint("[error] could not enumerate users, make sure database is initialized and up to date (./bin/flaskdb upgrade)")

            if False:
                tmpsample = DatasetContent()
                tmpds = dataset_by_id(dbsession, 1)
                fprint(tmpds)
                tmpsample.dataset = tmpds
                tmpsample.sample = "12345"
                tmpsample.content = "DELETETHIS"
                fprint("-----------------------------")
                dbsession.add(tmpsample)
                fprint("-----------------------------")
                fprint("-----------------------------")
                fprint("smaple", tmpsample)
                dbsession.flush()

                tmpdel = tmpds.content_query(dbsession)
                fprint(tmpdel.all())
                fprint("-----------------------------")
