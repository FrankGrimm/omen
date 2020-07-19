"""
Main dataset entity
"""
from sqlalchemy import Column, Integer, String, JSON, ForeignKey, ForeignKeyConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.orm.attributes import flag_dirty, flag_modified
from flask import flash

import pandas as pd
import numpy as np

from datetime import datetime
import json
import logging
import os
import os.path
from io import StringIO

from app.lib.database_internals import Base
from app.lib.models.datasetcontent import DatasetContent
from app.lib.models.user import User
from app.lib.models.annotation import Annotation
import app.lib.iaa as iaa

DATASET_CONTENT_CACHE = {}


class NpEncoder(json.JSONEncoder):
    """
    numpy safe JSON converter
    adapted from https://stackoverflow.com/a/57915246
    """
    def default(self, obj):
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, np.bool_):
            return bool(obj)
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
            user_obj = User.by_id(dbsession, user_obj)
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

        dsname = self.dsmetadata.get("name", None) if self.dsmetadata is not None else None

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
        if check_result is not None and len(check_result) > 0:
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

        for anno in dbsession.query(Annotation).filter_by(dataset_id=self.dataset_id).all():

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

    def annotation_counts(self, dbsession):
        params = {
                "dataset_id": self.dataset_id
                }
        sql = """
        SELECT users.uid,
            (CASE WHEN
                (users.displayname IS NULL OR users.displayname = '')
                THEN users.email
                ELSE users.displayname
                END) AS username,
            anno.data->'value' #>> '{}' AS anno_tag,
            COUNT(anno.sample_index) AS cnt
        FROM annotations as anno
        LEFT JOIN users
            ON users.uid = anno.owner_id
        WHERE
            anno.dataset_id = %(dataset_id)s
        GROUP BY
            users.uid, anno.data->'value' #>> '{}'
        """

        sql = prep_sql(sql)
        logging.debug("DB_SQL_LOG %s %s", sql, params)

        df = pd.read_sql(sql,
                         dbsession.bind,
                         params=params)

        result_data = df.replace(np.nan, "", regex=True).to_dict()
        result_data = json.dumps(result_data, cls=NpEncoder)
        result_data = json.loads(result_data)

        annotations_by_user = {}
        all_annotations = {}
        tags = self.get_taglist()

        for tag in tags:
            all_annotations[tag] = 0

        if 'uid' in result_data:
            for rowidx, uid in result_data['uid'].items():
                row_username = result_data['username'].get(rowidx, str(uid))
                row_tag = result_data['anno_tag'].get(rowidx, None)

                if row_tag not in tags:
                    continue

                row_cnt = result_data['cnt'].get(rowidx, 0)

                if row_username not in annotations_by_user:
                    annotations_by_user[row_username] = {}
                annotations_by_user[row_username][row_tag] = row_cnt
                all_annotations[row_tag] += row_cnt

        return annotations_by_user, all_annotations

    def annotation_agreement(self, dbsession, exclude_insufficient=False, by_tag=False):
        """
        calculates Fleiss' Kappa statistic on the annotations
        for this dataset

        if exclude_insufficient is set, rows with annotations by only one user are excluded.
        """

        tags = self.get_taglist()

        params = {
                "dataset_id": self.dataset_id
                }
        sql = """
        SELECT
            anno.sample_index,
            anno.data->'value' #>> '{}' AS anno_tag,
            COUNT(anno.owner_id) AS cnt
        FROM
            annotations as anno
        WHERE
            anno.dataset_id = %(dataset_id)s
        GROUP BY
            anno.sample_index, anno.data->'value' #>> '{}'
        """

        sql = prep_sql(sql)
        logging.debug("DB_SQL_LOG %s %s", sql, params)

        df = pd.read_sql(sql,
                         dbsession.bind,
                         params=params)

        if not by_tag:
            # return overall IAA
            return iaa.fleiss_kappa(df, tags, exclude_insufficient=exclude_insufficient)
        else:
            iaa_result = {}
            iaa_result['__overall'] = iaa.fleiss_kappa(df, tags, exclude_insufficient=False)

            for tag in tags:
                not_tag = "!%s" % tag
                cur_tags = [tag, not_tag]
                cur_df = df.copy()

                cur_df.loc[cur_df.anno_tag != tag, 'anno_tag'] = not_tag

                cur_df = cur_df.groupby(["sample_index", "anno_tag"], as_index=False)[["cnt"]].sum()

                cols = ["sample_index", "anno_tag"]
                midf = pd.MultiIndex.from_product([cur_df.sample_index, [tag, not_tag]], names=cols)
                cur_df = cur_df.reset_index()
                cur_df = cur_df.set_index(cols).reindex(midf, fill_value=0).reset_index().drop(columns=["index"])
                cur_df.drop_duplicates(inplace=True)

                logging.debug("FLEISS %s\n%s\n%s", tag, cur_df, cur_df.shape)
                iaa_result[tag] = iaa.fleiss_kappa(cur_df,
                                                   cur_tags,
                                                   filter_target=tag,
                                                   exclude_insufficient=False)

            return iaa_result

    def annotations(self, dbsession, page=1, page_size=50, foruser=None,
            user_column=None, restrict_view=None, only_user=False, with_content=True,
            query=None, order_by=None, min_sample_index=None,
            tags_include=None, tags_exclude=None):

        foruser = User.by_id(dbsession, foruser)
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

        join_type = "LEFT" if restrict_view is not None and restrict_view == 'tagged' else "LEFT OUTER"

        id_column = self.get_id_column()

        annotation_columns = []
        col_renames = {
                "sample_id": id_column,
                "sample_content": self.get_text_column()
                }

        if foruser is not None:
            sql_select += """
            {join_type} JOIN annotations AS usercol ON usercol.dataset_id = dc.dataset_id AND usercol.sample_index = dc.sample_index AND usercol.owner_id = %(foruser_join)s
            """.format(join_type=join_type)
            col_renames["usercol_value"] = user_column
            params['foruser_join'] = foruser.uid
            field_list.append("usercol.data->'value' #>> '{}' AS usercol_value")
            annotation_columns.append(user_column)

            if tags_include is None:
                tags_include = []
            if tags_exclude is None:
                tags_exclude = []
            condition_include = []
            condition_exclude = []

            for tag_idx, tag in enumerate(self.get_taglist()):
                if tag not in tags_include and tag not in tags_exclude:
                    continue

                params["tag_%s" % tag_idx] = tag
                if tag in tags_include:
                    condition_include.append("tag_%s" % tag_idx)
                if tag in tags_exclude:
                    condition_exclude.append("tag_%s" % tag_idx)

            if len(condition_include) > 0:
                sql_where += "\nAND usercol.data->'value' #>> '{}' IN (%s)" % ", ".join(map(lambda p: "%(" + p + ")s", condition_include))
            if len(condition_exclude) > 0:
                sql_where += "\nAND NOT usercol.data->'value' #>> '{}' IN (%s)" % ", ".join(map(lambda p: "%(" + p + ")s", condition_exclude))

        target_users = [foruser] # if user is annotator, only export and show their own annotations
        if 'curator' in user_roles and not only_user:
            # curator, also implied by owner role
            target_users = list(set(User.userlist(dbsession)) - set([foruser]))

        additional_user_columns = []
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
                additional_user_columns.append("anno-{uid}-{uname}".format(uid=user_obj.uid, uname=user_obj.email))
                col_renames["anno-{uid}".format(uid=user_obj.uid)] = "anno-{uid}-{uname}".format(uid=user_obj.uid, uname=user_obj.email)

        sql_where = """
        WHERE dc.dataset_id = %(dataset_id)s
        """ + sql_where

        if restrict_view is not None and restrict_view == "tagged":
            sql_where += "\nAND usercol IS NOT NULL"
        elif restrict_view is not None and restrict_view == "untagged":
            sql_where += "\nAND usercol IS NULL"

        if min_sample_index is not None:
            sql_where += "\nAND dc.sample_index >= %(min_sample_index)s"
            params["min_sample_index"] = min_sample_index

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

        # ordering and constraints
        if order_by is not None:
            sql += "\nORDER BY %s" % order_by

        if page_size > 0:
            sql += "\nLIMIT %(page_size)s"
            params["page_size"] = page_size

        if page > 0 and page_size > 0:
            sql += "\nOFFSET %(page_onset)s"
            params["page_onset"] = (page - 1) * page_size

        sql = prep_sql(sql)
        logging.debug("DB_SQL_LOG %s %s", sql, params)

        df = pd.read_sql(sql,
                dbsession.bind,
                params=params)
        df_count = pd.read_sql(sql_count,
                dbsession.bind,
                params=params)

        df_count = df_count.loc[0, "cnt"]

        df = df.rename(columns=col_renames)

        # remove additional user columns that do not have annotations yet
        drop_columns = []
        for check_column in df.columns.intersection(additional_user_columns):
            if df[check_column].dropna().empty:
                drop_columns.append(check_column)
        if len(drop_columns) > 0:
            df = df.drop(columns=drop_columns)

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
                    "color": curtag_metadata.get("color", "")
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
        user_obj = User.by_id(dbsession, uid)
        annores = dbsession.query(Annotation).filter_by(
                    owner_id=user_obj.uid, dataset_id=self.dataset_id).all()
        if not asdict:
            return annores

        resdict = {"sample": [], "uid": [], "annotation": []}
        for anno in annores:
            resdict['uid'].append(anno.owner_id)
            resdict['sample'].append(anno.sample)
            resdict['annotation'].append(anno.data['value'] \
                    if 'value' in anno.data and not anno.data['value'] is None
                    else None)

        return resdict

    def getanno(self, dbsession, uid, sample):
        user_obj = User.by_id(dbsession, uid)
        sample = str(sample)
        anno_obj_data = {}

        anno_obj = dbsession.query(Annotation).filter_by(owner_id=user_obj.uid,
                        dataset_id=self.dataset_id, sample=sample).one_or_none()

        if not anno_obj is None:
            anno_obj_data = anno_obj.data or {}

        return {
                "sample": sample,
                "data": anno_obj_data
               }

    def sample_by_index(self, dbsession, sample_index):
        qry = self.content_query(dbsession).filter_by(sample_index=int(sample_index))
        return qry.one_or_none()

    def get_next_sample(self, dbsession, sample_index, user_obj, exclude_annotated=True):
        sample_index = int(sample_index)

        sql = ""
        if exclude_annotated:
            sql = """
            SELECT
                dc.sample_index, dc.sample, COUNT(anno.owner_id) AS annocount
            FROM
                datasetcontent AS dc
            LEFT JOIN annotations AS anno
                ON anno.sample_index = dc.sample_index AND anno.dataset_id = dc.dataset_id
            WHERE 1=1
                AND dc.dataset_id = %(dsid)s
                AND (anno.owner_id != %(uid)s
                OR anno.owner_id IS NULL)
                AND dc.sample_index > %(req_sample_idx)s
            GROUP BY dc.sample_index, dc.sample
            ORDER BY dc.sample_index ASC
            LIMIT 1
            """.format().strip()
        else:
            sql = """
            SELECT
                dc.sample_index, dc.sample, COUNT(anno.owner_id) AS annocount
            FROM
                datasetcontent AS dc
            LEFT JOIN annotations AS anno
                ON anno.sample_index = dc.sample_index AND anno.dataset_id = dc.dataset_id
            WHERE 1=1
                AND dc.dataset_id = %(dsid)s
                AND dc.sample_index > %(req_sample_idx)s
            GROUP BY dc.sample_index, dc.sample
            ORDER BY dc.sample_index ASC
            LIMIT 1
            """.format().strip()

        params = {
                "uid": user_obj.uid,
                "dsid": self.dataset_id,
                "req_sample_idx": sample_index
                }

        logging.debug("DF_SQL_LOG %s\n%s\n%s", "get_next_sample(excl=%s)" % exclude_annotated, sql, params)
        df = pd.read_sql(sql,
                         dbsession.bind,
                         params=params)

        if df.shape[0] == 0 and exclude_annotated:
            return self.get_next_sample(dbsession, sample_index, user_obj, exclude_annotated=False)
        elif df.shape[0] > 0:
            first_row = df.iloc[df.index[0]]
            return first_row["sample_index"], first_row["sample"]
        else:
            # empty dataset
            return None, None

    def get_prev_sample(self, dbsession, sample_index, user_obj, exclude_annotated=True):
        sample_index = int(sample_index)

        sql = ""
        if exclude_annotated:
            sql = """
            SELECT
                dc.sample_index, dc.sample, COUNT(anno.owner_id) AS annocount
            FROM
                datasetcontent AS dc
            LEFT JOIN annotations AS anno
                ON anno.sample_index = dc.sample_index AND anno.dataset_id = dc.dataset_id
            WHERE 1=1
                AND dc.dataset_id = %(dsid)s
                AND (anno.owner_id != %(uid)s
                OR anno.owner_id IS NULL)
                AND dc.sample_index < %(req_sample_idx)s
            GROUP BY dc.sample_index, dc.sample
            ORDER BY dc.sample_index DESC
            LIMIT 1
            """.format().strip()
        else:
            sql = """
            SELECT
                dc.sample_index, dc.sample, COUNT(anno.owner_id) AS annocount
            FROM
                datasetcontent AS dc
            LEFT JOIN annotations AS anno
                ON anno.sample_index = dc.sample_index AND anno.dataset_id = dc.dataset_id
            WHERE 1=1
                AND dc.dataset_id = %(dsid)s
                AND dc.sample_index < %(req_sample_idx)s
            GROUP BY dc.sample_index, dc.sample
            ORDER BY dc.sample_index DESC
            LIMIT 1
            """.format().strip()

        params = {
                "uid": user_obj.uid,
                "dsid": self.dataset_id,
                "req_sample_idx": sample_index
                }

        logging.debug("DF_SQL_LOG %s\n%s\n%s", "get_prev_sample(excl=%s)" % exclude_annotated, sql, params)
        df = pd.read_sql(sql,
                         dbsession.bind,
                         params=params)

        if df.shape[0] == 0 and exclude_annotated:
            return self.get_prev_sample(dbsession, sample_index, user_obj, exclude_annotated=False)
        elif df.shape[0] > 0:
            first_row = df.iloc[df.index[0]]
            return first_row["sample_index"], first_row["sample"]
        else:
            # empty dataset
            return None, None

    def setanno(self, dbsession, uid, sample_index, value):
        user_obj = User.by_id(dbsession, uid)

        if user_obj is None:
            raise Exception("setanno() requires a user object or id")

        anno_data = {"updated": datetime.now().timestamp(), "value": value}

        sample_obj = self.content_query(dbsession).filter_by(
                dataset_id=self.dataset_id,
                sample_index=sample_index,
                ).one()

        existing_anno = dbsession.query(Annotation).filter_by(
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
            logging.debug("created annotation %s for sample %s with value %s" % (newanno, sample_obj, value))
        else:
            existing_anno.data = anno_data
            logging.debug("updated annotation %s for sample %s with value %s" % (existing_anno, sample_obj, value))
            dbsession.merge(existing_anno)

        # ensure this change is reflected in subsequent dataset loads
        dbsession.flush()
        dbsession.commit()

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
                logging.warning("malformed annotation timestamp %s" % anno_upd)
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

        logging.info("changing role for user %s from %s to %s" % (uid, curacl[uid], role))
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
                elif df.shape[1] < 2:
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

                    logging.debug("[import] %s, sample count before: %s" % (self, len(self.dscontent)))
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
                    logging.debug("[import] %s, sample count after: %s" % (self, len(self.dscontent)))
                    # tmpsample = DatasetContent()
                    # tmpds = dataset_by_id(dbsession, 1)
                    # tmpsample.dataset = tmpds
                    # tmpsample.sample = "12345"
                    # tmpsample.content = "DELETETHIS"
                    # dbsession.add(tmpsample)
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
            sample_count += 1

            frame_data["index"].append(sample.sample_index)
            frame_data[id_column].append(sample.sample)
            frame_data[text_column].append(sample.content)

            if not extended:
                continue

            if sample.data is None:
                for key in frame_data:
                    if key in ["index", id_column, text_column]:
                        continue
                    frame_data[key].append(None)
            else:
                for key, value in sample.data.items():
                    if key not in frame_data:
                        frame_data[key] = []
                        if len(frame_data["index"]) > 0:
                            frame_data[key] = [None] * (len(frame_data["index"]) - 1)
                    frame_data[key].append(value)

        df = pd.DataFrame.from_dict(frame_data)
        df.set_index("index")
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


def prep_sql(sql):
    sql = "\n".join(filter(lambda line: line != "", map(str.strip, sql.strip().split("\n"))))
    return sql.strip()


def dataset_roles(dbsession, user_id):
    res = {}

    user_obj = User.by_id(dbsession, user_id)

    all_user_datasets = accessible_datasets(dbsession, user_id, include_owned=True)

    for dataset_id, dataset in all_user_datasets.items():
        res[dataset_id] = dataset.get_roles(dbsession, user_obj)

    return res


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

    user_obj = User.by_id(dbsession, user_id)

    for ds in dbsession.query(Dataset).filter_by(owner=user_obj).all():
        if not ds or not ds.dataset_id:
            continue
        res[str(ds.dataset_id)] = ds

    return res


def accessible_datasets(dbsession, user_id, include_owned=False):
    res = {}

    user_obj = User.by_id(dbsession, user_id)

    if include_owned:
        res = my_datasets(dbsession, user_id)

    for ds in all_datasets(dbsession):
        if not ds.dsmetadata:
            continue
        if 'acl' not in ds.dsmetadata:
            continue
        dsacl = ds.dsmetadata['acl']
        uid = str(user_obj.uid)

        if uid not in dsacl:
            continue
        if dsacl[uid] is None or \
                dsacl[uid] == '':
            continue
        res[str(ds.dataset_id)] = ds

    return res


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
        if check_result is not None and len(check_result) > 0:
            continue

        dsname = dataset.get_name()
        task = {"id": int(dsid), "name": dsname,
                "dataset": dataset,
                "progress": 0,
                "size": dataset.dsmetadata.get("size", -1) or -1,
                "user_roles": dataset.get_roles(dbsession, for_user),
                "annos": dataset.annocount(dbsession, for_user),
                "annos_today": dataset.annocount_today(dbsession, for_user)
                }

        task_calculate_progress(task)

        tasks.append(task)

    # make sure completed tasks are pushed to the bottom of the list
    tasks.sort(key=lambda task: (task["progress"] >= 100.0, task["name"]))

    return tasks
