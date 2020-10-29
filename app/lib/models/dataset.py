"""
Main dataset entity
"""
from datetime import datetime
import json
import logging
import random
import os
import os.path
import re
from dataclasses import dataclass, field
from typing import List

from sqlalchemy import Column, Integer, JSON, ForeignKey, func, sql, or_, and_, inspect
from sqlalchemy.orm import relationship
from sqlalchemy.orm.attributes import flag_dirty, flag_modified
from flask import flash

import pandas as pd
from pandas.api.types import is_numeric_dtype
import numpy as np

from app.lib.database_internals import Base
from app.lib.models.datasetcontent import DatasetContent
from app.lib.models.user import User
from app.lib.models.activity import Activity
from app.lib.models.annotation import Annotation
import app.lib.iaa as iaa

DATASET_CONTENT_CACHE = {}


class NpEncoder(json.JSONEncoder):
    """
    numpy safe JSON converter
    adapted from https://stackoverflow.com/a/57915246
    """
    def default(self, o):
        if isinstance(o, np.integer):
            return int(o)
        if isinstance(o, np.floating):
            return float(o)
        if isinstance(o, np.ndarray):
            return o.tolist()
        if isinstance(o, np.bool_):
            return bool(o)
        return super(NpEncoder, self).default(o)


def pd_expand_json_column(df, json_column):
    """
    https://stackoverflow.com/a/25512372
    """
    df = pd.concat(
            [df, json_column.apply(lambda content: pd.Series(list(content.values()), index=list(content.keys())))],
            axis=1
            )
    return df.drop(columns=['data'])


def calculate_row_state(row, additional_user_columns):
    annotations = {}
    for annotator_column in additional_user_columns:
        if annotator_column not in row:
            continue
        annotations[annotator_column] = row[annotator_column]
    row_state = set()
    if len(annotations) == 0:
        row_state.add("empty")
    elif len(annotations) == 1:
        row_state.add("single")
    elif len(annotations) > 1:
        row_state.add("multiple")

    uniques = set(annotations.values())
    if len(uniques) == 1:
        row_state.add("undisputed")
    elif len(uniques) > 1:
        row_state.add("disputed")

    return row_state


class Dataset(Base):
    __tablename__ = 'datasets'

    dataset_id = Column(Integer, primary_key=True)

    owner_id = Column(Integer, ForeignKey("users.uid"), nullable=False)
    owner = relationship("User", back_populates="datasets", lazy="joined")

    dsannotations = relationship("Annotation", cascade="all, delete-orphan")
    dscontent = relationship("DatasetContent", cascade="all, delete-orphan")
    dsmetadata = Column(JSON, nullable=False)

    persisted = False
    _cached_df = None
    valid_option_keys = set(["hide_votes", "annotators_can_comment", "allow_restart_annotation", "additional_column"])

    def defined_splits(self, dbsession):
        split_content_counts = dbsession.query(DatasetContent.split_id, func.count(DatasetContent.sample))
        split_content_counts = split_content_counts.filter_by(dataset_id=self.dataset_id)
        split_content_counts = split_content_counts.group_by(DatasetContent.split_id).all()

        split_info = {}
        split_metadata = self.dsmetadata.get("splitdetails", {})
        for ds_split, ds_split_count in split_content_counts:
            split_info[ds_split] = split_metadata.get(ds_split, {}) or {}
            split_info[ds_split]['size'] = ds_split_count
        return split_info

    def split_annotator_list(self, dbsession, split_id, resolve_users=False):
        metadata = self.split_metadata(split_id)
        result_list = metadata[split_id]["acl"]

        if not resolve_users:
            return [str(uid) for uid in result_list]

        result_list = [User.by_id(dbsession, int(uid), True) for uid in result_list]
        return result_list

    def split_annotator_add(self, dbsession, split_id, uid):
        if uid is None:
            return False
        if isinstance(uid, User):
            uid = uid.uid
        if not isinstance(uid, str):
            uid = str(uid)

        annotator_list = self.split_annotator_list(dbsession, split_id, False)
        logging.debug("split_annotator_add %s to split %s (before: %s)", uid, split_id, annotator_list)
        if uid in annotator_list:
            return False

        annotator_list.append(uid)
        split_metadata = self.split_metadata(split_id)
        split_metadata[split_id]['acl'] = annotator_list

        self.dsmetadata['splitdetails'] = split_metadata

        self.dirty(dbsession)
        return True

    def split_annotator_remove(self, dbsession, split_id, uid):
        if uid is None:
            return False
        if isinstance(uid, User):
            uid = uid.uid
        if not isinstance(uid, str):
            uid = str(uid)

        annotator_list = self.split_annotator_list(dbsession, split_id, False)
        logging.debug("split_annotator_remove %s to split %s (before: %s)", uid, split_id, annotator_list)
        if uid not in annotator_list:
            return False

        annotator_list.remove(uid)
        split_metadata = self.split_metadata(split_id)
        split_metadata[split_id]['acl'] = annotator_list

        self.dsmetadata['splitdetails'] = split_metadata

        self.dirty(dbsession)
        return True

    def _split_target(self, target_old):
        target_criterion = "(dc.split_id = '' OR dc.split_id IS NULL)"
        if target_old != "" and target_old is not None:
            target_criterion = "dc.split_id = :targetold"
        return target_criterion

    def split_metadata(self, target_split=None):
        metadata = self.dsmetadata.get("splitdetails", {})
        if target_split not in metadata:
            metadata[target_split] = {}
        if "acl" not in metadata[target_split]:
            metadata[target_split]["acl"] = []
        return metadata

    def rename_split(self, dbsession, session_user, target_old, target_new):
        target_old = "" if target_old is None else target_old
        target_new = "" if target_new is None else target_new

        # move split metadata to new name if it did not exist before
        split_metadata = self.split_metadata(target_old)

        if target_new not in split_metadata:
            split_metadata[target_new] = split_metadata[target_old]
            del split_metadata[target_old]

        self.dsmetadata['splitdetails'] = split_metadata

        # update dataset content to new split

        statement = sql.text("""
        UPDATE datasetcontent AS dc
            SET split_id = :targetnew
        WHERE
            dc.dataset_id = :datasetid
            AND
        """ + self._split_target(target_old) + """
        """)

        params = {
                "datasetid": self.dataset_id,
                "targetnew": target_new
                }
        if target_old != "" and target_old is not None:
            params["targetold"] = target_old

        sqlres = dbsession.execute(statement, params=params)
        affected = sqlres.rowcount

        # create an activity to track this change
        Activity.create(dbsession, session_user, self, "split_edit",
                        "renamed split '%s' to '%s' (affected: %s)" %
                        (target_old, target_new, affected))

        self.dirty(dbsession)
        return affected

    def get_field_minmax(self, dbsession, fieldid):
        """
        Retrieve the minimum and maximum values of a particular additional field in the dataset.
        """
        maxval = minval = None

        sql_raw = prep_sql("""
            SELECT MIN((data->>:targetcolumn)::float) AS minval, MAX((data->>:targetcolumn)::float) AS maxval
            FROM datasetcontent AS dc
            WHERE
                dc.dataset_id = :datasetid
        """.strip())

        params = {
                "datasetid": self.dataset_id,
                "targetcolumn": fieldid
                }

        logging.debug("DB_SQL_LOG %s %s", sql, params)
        statement = sql.text(sql_raw)
        sqlres = dbsession.execute(statement, params=params)
        sqlres = [{column: value for column, value in rowproxy.items()} for rowproxy in sqlres]

        if len(sqlres) > 0:
            minval = sqlres[0]['minval']
            maxval = sqlres[0]['maxval']

        return minval, maxval

    def split_dataset(self, dbsession, session_user, targetsplit, splitoptions):
        splitmethod = splitoptions.get("splitmethod", "")
        if splitmethod == "" or splitmethod is None:
            raise Exception("splitmethod cannot be empty")

        targetsplit = "" if targetsplit is None else targetsplit
        target_criterion = self._split_target(targetsplit)

        params = {
                "datasetid": self.dataset_id,
                "targetold": targetsplit
                }

        affected = 0
        sql_raw = None
        if splitmethod == "attribute":
            splitcolumn = splitoptions.get("splitcolumn", None) or None
            if splitcolumn is None or splitcolumn == "":
                raise Exception("no column specified for split method %s" % (splitmethod))

            params['targetcolumn'] = splitcolumn
            params['trimtargetcolumn'] = (splitcolumn or "").strip()

            sql_raw = """
            UPDATE datasetcontent AS dc
                SET split_id = TRIM(BOTH FROM (split_id || ' / ' || :trimtargetcolumn || '=' || (TRIM(both ' "' FROM data->>:targetcolumn))::TEXT))
            WHERE
                dc.dataset_id = :datasetid
                AND
            """ + target_criterion + """
            """
        elif splitmethod == "value":
            splitcolumn = splitoptions.get("splitcolumn", None) or None
            if splitcolumn is None or splitcolumn == "":
                raise Exception("no column specified for split method %s" % (splitmethod))
            splitvalue = splitoptions.get("splitvalue", None) or None
            if splitvalue is None or splitvalue == "":
                raise Exception("no value specified to split at")
            splitvalue = float(splitvalue)

            params['targetcolumn'] = splitcolumn
            params['splitvalue'] = splitvalue
            params['trimtargetcolumn'] = (splitcolumn or "").strip()

            sql_raw = """
            UPDATE datasetcontent AS dc
                SET split_id = CASE WHEN (data->>:targetcolumn)::float < :splitvalue
                    THEN TRIM(BOTH FROM (split_id || ' / ' || :trimtargetcolumn || '<' || :splitvalue))
                    ELSE TRIM(BOTH FROM (split_id || ' / ' || :trimtargetcolumn || '>=' || :splitvalue))
                    END
            WHERE
                dc.dataset_id = :datasetid
                AND
            """ + target_criterion + """
            """
        elif splitmethod in ["ratio", "evenly"]:

            # gather target IDs
            id_query = dbsession.query(DatasetContent.sample_index).filter_by(dataset_id=self.dataset_id)
            if targetsplit is None or targetsplit == "":
                # pylint: disable=singleton-comparison
                id_query = id_query.filter(or_(DatasetContent.split_id == "", DatasetContent.split_id == None))
            else:
                id_query = id_query.filter_by(split_id=targetsplit)

            all_affected_ids = [t[0] for t in id_query.all()]

            # shuffle affected ID list
            random.shuffle(all_affected_ids)

            newsplits = []

            if splitmethod == "ratio":
                new_ratio = splitoptions.get("splitratio", "").strip()
                if new_ratio == "" or '-' not in new_ratio:
                    raise Exception('missing valid ratio argument')
                new_ratio_a = int(new_ratio.split("-")[0])

                # since the IDs were shuffled, we can just take N elements for the first ratio
                # and treat the rest as the second one

                new_ratio_a_size = max(1, int(len(all_affected_ids) * (new_ratio_a/100.0)))
                newsplits = [
                        all_affected_ids[:new_ratio_a_size],
                        all_affected_ids[new_ratio_a_size:]
                        ]
            elif splitmethod == "evenly":
                num_chunks = int(splitoptions.get("splitcount", "2"))
                newsplits = [[] for _ in range(num_chunks)]
                for idx, sample_id in enumerate(all_affected_ids):
                    target_bucket = newsplits[idx % num_chunks]
                    target_bucket.append(sample_id)

            if len(newsplits) > 0:
                newsplit_identifiers = [("%s / %s" % (targetsplit, chr(ord('A') + idx))).strip(" /") for idx in range(len(newsplits))]
                for newsplit_index, newsplit_ids in enumerate(newsplits):
                    newsplit_label = newsplit_identifiers[newsplit_index]

                    update_query = dbsession.query(DatasetContent).filter_by(dataset_id=self.dataset_id)
                    if targetsplit is None or targetsplit == "":
                        update_query = update_query.filter(or_(DatasetContent.split_id == "", DatasetContent.split_id == None))
                    else:
                        update_query = update_query.filter_by(split_id=targetsplit)
                    update_query = update_query.filter(DatasetContent.sample_index.in_(newsplit_ids))
                    affected += update_query.update({"split_id": newsplit_label}, synchronize_session='fetch')

                Activity.create(dbsession, session_user, self, "split_edit",
                                "forked split '%s' method:'%s' (affected: %s, new splits: %s)" %
                                (targetsplit, splitmethod, affected, len(newsplits)))
        else:
            raise Exception("no implementation found for split method %s" % (splitmethod))

        if sql_raw is not None:
            sql_raw = prep_sql(sql_raw)
            logging.debug("DB_SQL_LOG %s %s", sql, params)
            statement = sql.text(sql_raw)
            sqlres = dbsession.execute(statement, params=params)
            affected = sqlres.rowcount

            Activity.create(dbsession, session_user, self, "split_edit",
                            "forked split '%s' method:'%s' (affected: %s)" %
                            (targetsplit, splitmethod, affected))

            self.dirty(dbsession)

        return affected

    @staticmethod
    def by_id(dbsession, dataset_id, user_id=None, no_error=False):
        qry = None
        if user_id is None:
            qry = dbsession.query(Dataset).filter_by(dataset_id=dataset_id)
        else:
            qry = dbsession.query(Dataset).filter_by(owner_id=user_id, dataset_id=dataset_id)

        if no_error:
            return qry.one_or_none()
        return qry.one()

    def get_option(self, key, default_value=False):
        return bool(self.dsmetadata.get(key, default_value))

    def empty(self):
        return not self.has_content()

    def has_content(self):
        if self.dscontent is None:
            return False
        return len(self.dscontent) > 0

    def size(self, dbsession):
        return self.content_query(dbsession).count()

    def content_query(self, dbsession):
        return dbsession.query(DatasetContent).filter_by(dataset_id=self.dataset_id)

    def __repr__(self):
        return "<Dataset (%s)>" % self.get_name()

    @staticmethod
    def activity_prefix():
        return "DATASET:"

    def activity_target(self):
        return "DATASET:%s" % self.dataset_id

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

    def get_annotator_splits(self, dbsession, uid):
        if isinstance(uid, int):
            uid = str(uid)
        if isinstance(uid, User):
            uid = str(uid.uid)
        if not uid:
            return set()

        split_list = set()
        for split_id in self.defined_splits(dbsession).keys():
            split_annotators = self.split_annotator_list(dbsession, split_id, resolve_users=False)
            if uid in split_annotators:
                split_list.add(split_id)
        return split_list

    def get_split_progress(self, dbsession):
        sql_raw = prep_sql("""
        SELECT
            dc.split_id,
            COUNT(dc.sample_index) as sample_count,
            COUNT(DISTINCT annos.sample_index) AS annotated_sample_count,
            COUNT(DISTINCT annos.owner_id) AS annotators_count
        FROM datasetcontent dc
        LEFT OUTER JOIN annotations annos ON dc.dataset_id = annos.dataset_id AND dc.sample_index = annos.sample_index
        LEFT OUTER JOIN users u ON u.uid = annos.owner_id
        WHERE u.email <> 'SYSTEM'
            AND dc.dataset_id = :datasetid
        GROUP BY dc.split_id;
        """.strip())

        params = {
                "datasetid": self.dataset_id,
                }

        logging.debug("DB_SQL_LOG %s %s", sql, params)
        statement = sql.text(sql_raw)
        sqlres = dbsession.execute(statement, params=params)
        sqlres = [{column: value for column, value in rowproxy.items()} for rowproxy in sqlres]

        return sqlres

    def get_roles(self, dbsession, user_obj, splitroles=True):
        if isinstance(user_obj, str):
            user_obj = int(user_obj)
        if isinstance(user_obj, int):
            user_obj = User.by_id(dbsession, user_obj)
        if not user_obj:
            return set()

        if user_obj.is_system_user():
            return set(["annotator", "curator"])

        roles = []
        if user_obj.uid == self.owner_id:
            # add all roles for owned datasets
            roles.append("owner")

        curacl = self.get_acl()
        uid = str(user_obj.uid)
        if uid in curacl and not curacl[uid] is None:
            if "annotator" in curacl[uid]:
                roles.append("annotator")
            if "curator" in curacl[uid]:
                roles.append("curator")

        # check if user is granted annotation for individual splits
        if splitroles:
            if "annotator" not in roles and len(self.get_annotator_splits(dbsession, user_obj)) > 0:
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

    def validate_owner(self, userobj):
        if self.owner is not userobj:
            raise Exception("You cannot modify datasets you do not own.")

    def ensure_id(self, dbsession):
        """
        Ensure that this dataset was written to the database and was assigned an identifier.
        """
        if self.dataset_id is not None:
            return True

        self.dirty(dbsession)
        dbsession.commit()

        dbsession.flush()
        return False

    def accessible_by(self, dbsession, for_user):
        if self.dataset_id is None:
            raise Exception("cannot check accessibility. dataset needs to be committed first.")

        if isinstance(for_user, int):
            for_user = User.by_id(dbsession, for_user)

            if self.owner == for_user:
                return True

        dsacl = self.get_roles(dbsession, for_user)

        if dsacl is None or len(dsacl) == 0:
            return False
        return True

    def get_task(self, dbsession, for_user):
        if not self.accessible_by(dbsession, for_user):
            return None
        if isinstance(for_user, int):
            for_user = User.by_id(dbsession, for_user)
        if not isinstance(for_user, User):
            raise Exception("dataset::get_task - argument for_user needs to be of type User")

        check_result = self.check_dataset()
        if check_result is not None and len(check_result) > 0:
            return None

        task_size = self.get_size()

        global_roles = self.get_roles(dbsession, for_user, splitroles=False)

        annotation_splits = None
        if "annotator" not in global_roles:
            annotation_splits = self.get_annotator_splits(dbsession, for_user)
            if annotation_splits is not None and len(annotation_splits) == 0:
                annotation_splits = None
            if annotation_splits is not None:
                dataset_splits = self.defined_splits(dbsession)
                task_size = 0

                for split_id in annotation_splits:
                    if split_id not in dataset_splits:
                        continue
                    task_size += dataset_splits[split_id].get("size", 0)

        task = AnnotationTask(id=self.dataset_id,
                              name=self.get_name(),
                              dataset=self,
                              progress=0,
                              user_roles=self.get_roles(dbsession, for_user),
                              size=task_size,
                              splits=annotation_splits,
                              annos=self.annocount(dbsession, for_user, annotation_splits),
                              annos_today=self.annocount_today(dbsession, for_user, annotation_splits)
                              )
        task.calculate_progress()
        task.can_annotate = task.progress < 100.0 or self.dsmetadata.get("allow_restart_annotation", False)
        return task

    def dirty(self, dbsession):
        db_state = inspect(self)
        if db_state.deleted:
            return False
        flag_dirty(self)
        flag_modified(self, "dsmetadata")
        dbsession.add(self)
        return True

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
        sql_raw = """
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

        sql_raw = prep_sql(sql_raw)
        logging.debug("DB_SQL_LOG %s %s", sql_raw, params)

        df = pd.read_sql(sql_raw,
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
        sql_raw = """
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

        sql_raw = prep_sql(sql_raw)
        logging.debug("DB_SQL_LOG %s %s", sql_raw, params)

        df = pd.read_sql(sql_raw,
                         dbsession.bind,
                         params=params)

        if not by_tag:
            # return overall IAA
            return iaa.fleiss_kappa(df, tags, exclude_insufficient=exclude_insufficient)

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
                    splits=None,
                    tags_include=None, tags_exclude=None):

        if restrict_view is not None and not isinstance(restrict_view, list):
            restrict_view = [restrict_view]

        foruser = User.by_id(dbsession, foruser)
        user_roles = self.get_roles(dbsession, foruser)

        if 'annotator' not in user_roles and \
                'curator' not in user_roles:
            raise Exception("Unauthorized, user %s does not have role 'curator'. Active roles: %s"
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

        if query is not None:
            sql_where += "\nAND dc.content ILIKE %(query_pattern)s"
            if not query.startswith("%") and not query.endswith("%"):
                query = "%" + query + "%"
            params['query_pattern'] = query

        join_type = "LEFT" if restrict_view is not None and "curated" in restrict_view else "LEFT OUTER"

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

        # if user is annotator, only export and show their own annotations
        target_users = [foruser]

        if 'curator' in user_roles and not only_user:
            # curator, also implied by owner role
            target_users = list(set(User.userlist(dbsession)) - set([foruser]))

        additional_user_columns = []
        additional_user_columns_raw = []

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
                additional_user_columns_raw.append("anno-{uid}".format(uid=user_obj.uid))
                col_renames["anno-{uid}".format(uid=user_obj.uid)] = "anno-{uid}-{uname}".format(uid=user_obj.uid, uname=user_obj.email)

        if splits is not None and len(splits) > 0:
            sql_where += "\nAND dc.split_id = ANY(%(splitlist)s)"
            params["splitlist"] = list(splits)

        sql_where = """
        WHERE dc.dataset_id = %(dataset_id)s
        """ + sql_where

        restrict_clause = ""

        if restrict_view is not None:
            if "curated" in restrict_view:
                sql_where += "\nAND usercol IS NOT NULL"
            elif "uncurated" in restrict_view:
                sql_where += "\nAND usercol IS NULL"

            if "disputed" in restrict_view:
                restrict_clause = "WHERE aggr.unique_anno_count > 1"
            elif "undisputed" in restrict_view:
                restrict_clause = "WHERE aggr.unique_anno_count = 1"

        if min_sample_index is not None:
            sql_where += "\nAND dc.sample_index >= %(min_sample_index)s"
            params["min_sample_index"] = min_sample_index

        sql_raw = """
        SELECT {field_list} FROM datasetcontent AS dc
        {sql_select}
        {sql_where}
        """.format(field_list=", ".join(field_list),
                   sql_select="\n" + sql_select.strip(),
                   sql_where="\n" + sql_where.strip())

        # wrap in order to gather disputed/undisputed states
        sql_raw = """
        SELECT o.*, aggr.* FROM ({original_sql}) AS o
        LEFT JOIN LATERAL (
            SELECT COUNT(DISTINCT val) AS unique_anno_count FROM (
                SELECT UNNEST(ARRAY[{anno_columns}]::text[]) AS val
            ) AS aggrcnt
            WHERE val IS NOT NULL
        ) AS aggr ON true
        {restrict_clause}
        """.format(
                   original_sql=sql_raw,
                   anno_columns=", ".join(map(lambda col: "o.\"" + col + "\"",
                                              additional_user_columns_raw)),
                   restrict_clause=restrict_clause,
                   ).strip()
        # sql_select += """
        # LEFT JOIN (ARRAY[{anno_columns}] AS unique_annotations
        # {join_type} JOIN annotations AS "anno-{uid}" ON "anno-{uid}".dataset_id = dc.dataset_id AND "anno-{uid}".sample_index = dc.sample_index AND "anno-{uid}".owner_id = %(foruser_{uid})s
        # """.format(anno_columns=)

        sql_count = """
        SELECT COUNT(o.*) AS cnt FROM ({original_sql}) AS o
        """.format(original_sql=sql_raw).strip()

        # ordering and constraints
        if order_by is not None:
            sql_raw += "\nORDER BY %s" % order_by

        if page_size > 0:
            sql_raw += "\nLIMIT %(page_size)s"
            params["page_size"] = page_size

        if page > 0 and page_size > 0:
            sql_raw += "\nOFFSET %(page_onset)s"
            params["page_onset"] = (page - 1) * page_size

        sql_raw = prep_sql(sql_raw)
        logging.debug("DB_SQL_LOG %s %s", sql_raw, params)

        df = pd.read_sql(sql_raw,
                         dbsession.bind,
                         params=params)
        sql_count = prep_sql(sql_count)
        logging.debug("DB_SQL_LOG %s %s", sql_count, params)
        # placeholders for sql.text are :placeholder instead of %(placeholder)s
        sql_count = re.sub(r"%\((.*?)\)s", r":\1", sql_count)
        statement = sql.text(sql_count)
        sqlres = dbsession.execute(statement, params=params)
        sqlres = [{column: value for column, value in rowproxy.items()} for rowproxy in sqlres][0]
        df_count = sqlres['cnt']

        df = df.rename(columns=col_renames)

        # remove additional user columns that do not have annotations yet
        drop_columns = []
        for check_column in df.columns.intersection(additional_user_columns):
            if df[check_column].dropna().empty:
                drop_columns.append(check_column)
        if len(drop_columns) > 0:
            df = df.drop(columns=drop_columns)
            for col in drop_columns:
                annotation_columns.remove(col)

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

        for anno in dbsession.query(Annotation).filter_by(
                dataset_id=self.dataset_id,
                sample=sample_id).all():

            if exclude_user is not None and exclude_user is anno.owner:
                continue
            if anno.data is None or 'value' not in anno.data or anno.data['value'] is None or \
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
            resdict['annotation'].append(anno.data['value']
                                         if 'value' in anno.data and anno.data['value'] is not None else None)

        return resdict

    def getanno(self, dbsession, uid, sample):
        user_obj = User.by_id(dbsession, uid)
        sample = str(sample)
        anno_obj_data = {}

        anno_obj = dbsession.query(Annotation).filter_by(owner_id=user_obj.uid,
                                                         dataset_id=self.dataset_id,
                                                         sample=sample).one_or_none()

        if anno_obj is not None:
            anno_obj_data = anno_obj.data or {}

        return {
                "sample": sample,
                "data": anno_obj_data
               }

    def sample_by_index(self, dbsession, sample_index):
        qry = self.content_query(dbsession).filter_by(sample_index=int(sample_index))
        return qry.one_or_none()

    def get_next_sample(self, dbsession, sample_index, user_obj, splits, exclude_annotated=True):
        if sample_index is None:
            return None, None

        sample_index = int(sample_index)

        sql_raw = ""
        split_where = ""
        if splits is not None and len(splits) > 0:
            split_where += "\nAND dc.split_id = ANY(%(splitlist)s)"

        if exclude_annotated:
            sql_raw = """
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
                {split_where}
            GROUP BY dc.sample_index, dc.sample
            ORDER BY dc.sample_index ASC
            LIMIT 1
            """.format(split_where=split_where).strip()
        else:
            sql_raw = """
            SELECT
                dc.sample_index, dc.sample, COUNT(anno.owner_id) AS annocount
            FROM
                datasetcontent AS dc
            LEFT JOIN annotations AS anno
                ON anno.sample_index = dc.sample_index AND anno.dataset_id = dc.dataset_id
            WHERE 1=1
                AND dc.dataset_id = %(dsid)s
                AND dc.sample_index > %(req_sample_idx)s
                {split_where}
            GROUP BY dc.sample_index, dc.sample
            ORDER BY dc.sample_index ASC
            LIMIT 1
            """.format(split_where=split_where).strip()

        params = {
                "uid": user_obj.uid,
                "dsid": self.dataset_id,
                "req_sample_idx": sample_index
                }
        if splits is not None and len(splits) > 0:
            params["splitlist"] = list(splits)

        logging.debug("DF_SQL_LOG %s\n%s\n%s", "get_next_sample(excl=%s)" % exclude_annotated, sql_raw, params)
        df = pd.read_sql(sql_raw,
                         dbsession.bind,
                         params=params)

        if df.shape[0] == 0 and exclude_annotated and self.dsmetadata.get("allow_restart_annotation", False):
            return self.get_next_sample(dbsession, sample_index, user_obj, splits, exclude_annotated=False)

        if df.shape[0] > 0:
            first_row = df.iloc[df.index[0]]
            return first_row["sample_index"], first_row["sample"]
        # empty dataset
        return None, None

    def _update_overview_statistics(self, overview, df):
        if df is None:
            return

        # drop split, ID, and text columns
        ignore_columns = []
        if 'split' in df.columns:
            ignore_columns.append("split")
        if self.get_id_column() is not None and self.get_id_column() in df.columns:
            ignore_columns.append(self.get_id_column())
        if self.get_text_column() is not None and self.get_text_column() in df.columns:
            ignore_columns.append(self.get_text_column())
        df.drop(columns=ignore_columns)

        cur_dtypes = dict(df.dtypes)
        overview['columns'] = {}

        for colname, coldtype in cur_dtypes.items():
            overview['columns'][colname] = {}
            colinfo = overview['columns'][colname]
            colinfo['dtype'] = coldtype
            colinfo['numeric'] = is_numeric_dtype(coldtype) and not str(coldtype) == 'bool'
            colinfo['nunique'] = df[colname].nunique(dropna=True)

    def get_overview_statistics(self, dbsession):
        overview = {}

        sql_raw = """
        SELECT
            dc.sample_index, dc.sample, dc.data
        FROM
            datasetcontent AS dc
        WHERE 1=1
            AND dc.dataset_id = %(dsid)s
        ORDER BY dc.sample_index DESC
        LIMIT %(page_size)s
        OFFSET %(page_offset)s
        """.format().strip()

        params = {
                "dsid": self.dataset_id,
                }

        result_count = 0
        page_size = 10000
        page_offset = 0
        while result_count > 0 or page_offset == 0:
            logging.debug("DF_SQL_LOG %s\n%s\n%s", "get_overview_statistics()", sql_raw, params)
            params["page_size"] = page_size
            params["page_offset"] = page_offset

            df = pd.read_sql(sql_raw,
                             dbsession.bind,
                             params=params)

            result_count = df.shape[0] if df is not None else 0

            # expand JSON
            df = pd_expand_json_column(df, df['data'])

            page_offset += page_size

            self._update_overview_statistics(overview, df)

            # pagination is currently disabled for improved performance
            # until we figure out if using the first N=10000
            # samples is good enough for most use cases or not
            break

        overview['size'] = self.size(dbsession)
        return overview

    def get_prev_sample(self, dbsession, sample_index, user_obj, splits, exclude_annotated=True):
        if sample_index is None:
            return None, None

        sample_index = int(sample_index)

        sql_raw = ""
        split_where = ""
        if splits is not None and len(splits) > 0:
            split_where += "\nAND dc.split_id = ANY(%(splitlist)s)"
        if exclude_annotated:
            sql_raw = """
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
                {split_where}
            GROUP BY dc.sample_index, dc.sample
            ORDER BY dc.sample_index DESC
            LIMIT 1
            """.format(split_where=split_where).strip()
        else:
            sql_raw = """
            SELECT
                dc.sample_index, dc.sample, COUNT(anno.owner_id) AS annocount
            FROM
                datasetcontent AS dc
            LEFT JOIN annotations AS anno
                ON anno.sample_index = dc.sample_index AND anno.dataset_id = dc.dataset_id
            WHERE 1=1
                AND dc.dataset_id = %(dsid)s
                AND dc.sample_index < %(req_sample_idx)s
                {split_where}
            GROUP BY dc.sample_index, dc.sample
            ORDER BY dc.sample_index DESC
            LIMIT 1
            """.format(split_where=split_where).strip()

        params = {
                "uid": user_obj.uid,
                "dsid": self.dataset_id,
                "req_sample_idx": sample_index
                }
        if splits is not None and len(splits) > 0:
            params["splitlist"] = list(splits)

        logging.debug("DF_SQL_LOG %s\n%s\n%s", "get_prev_sample(excl=%s)" % exclude_annotated, sql_raw, params)
        df = pd.read_sql(sql_raw,
                         dbsession.bind,
                         params=params)

        if df.shape[0] == 0 and exclude_annotated:
            return self.get_prev_sample(dbsession, sample_index, user_obj, splits, exclude_annotated=False)

        if df.shape[0] > 0:
            first_row = df.iloc[df.index[0]]
            return first_row["sample_index"], first_row["sample"]

        # empty dataset
        return None, None

    def setanno(self, dbsession, uid, sample_index, value):
        user_obj = User.by_id(dbsession, uid) if not isinstance(uid, User) else uid

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

    def annocount_today(self, dbsession, uid, splits=None):
        if isinstance(uid, User):
            uid = uid.uid
        query = dbsession.query(Annotation).filter_by(
                dataset_id=self.dataset_id,
                owner_id=uid)
        if splits is not None:
            if not isinstance(splits, list):
                splits = list(splits)
            query = query.join(DatasetContent, and_(DatasetContent.dataset_id == Annotation.dataset_id,
                                                    DatasetContent.sample_index == Annotation.sample_index))
            query = query.filter(DatasetContent.split_id.in_(splits))
        allannos = query.all()

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

    def annocount(self, dbsession, uid, splits=None):
        if isinstance(uid, User):
            uid = uid.uid
        query = dbsession.query(Annotation).filter_by(
                dataset_id=self.dataset_id,
                owner_id=uid)

        if splits is not None:
            if not isinstance(splits, list):
                splits = list(splits)
            query = query.join(DatasetContent, and_(DatasetContent.dataset_id == Annotation.dataset_id,
                                                    DatasetContent.sample_index == Annotation.sample_index))
            query = query.filter(DatasetContent.split_id.in_(splits))

        return query.count()

    def set_role(self, dbsession, uid, role, remove=False):
        if not User.is_valid_role(role):
            return False

        if uid is None:
            return False

        if not isinstance(uid, str):
            uid = str(uid)

        curacl = self.get_acl()
        if uid not in curacl or curacl[uid] is None:
            curacl[uid] = []

        if not remove:
            if role in curacl[uid]:
                logging.debug("skipping role change for user %s, %s already present" % (uid, role))
            else:
                logging.info("changing role for user %s: %s add role %s" % (uid, ", ".join(curacl[uid]), role))
                curacl[uid].append(role)
        else:
            if role not in curacl[uid]:
                logging.debug("skipping role change for user %s, %s not present" % (uid, role))
            else:
                logging.info("changing role for user %s: %s remove role %s" % (uid, ", ".join(curacl[uid]), role))
                curacl[uid].remove(role)

        self.dsmetadata['acl'] = curacl
        self.dirty(dbsession)
        return True

    def get_acl(self):
        curacl = self.dsmetadata.get("acl", {})
        if not curacl:
            curacl = {}
        for uid, useracl in curacl.items():
            if not isinstance(useracl, list):
                if useracl is None:
                    curacl[uid] = []
                else:
                    curacl[uid] = [useracl]
            curacl[uid] = list(filter(lambda n: n is not None, curacl[uid]))
        return curacl

    def import_content(self, dbsession, session_user, filename, dry_run):
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
                errors.append("ID column '%s' not found in dataset columns (%s)." %
                              (self.get_id_column(), ", ".join(map(str, df.columns))))
            if self.get_text_column() is None:
                errors.append("Text column not defined.")
                success = False
            elif not self.get_text_column() in df.columns:
                errors.append("Text column '%s' not found in dataset columns (%s)." %
                              (self.get_text_column(), ", ".join(map(str, df.columns))))

            import_count = 0
            merge_count = 0
            skip_count = 0
            if len(errors) == 0:
                if not dry_run:
                    id_column = self.get_id_column()
                    text_column = self.get_text_column()

                    logging.debug("[import] %s, sample count before: %s", self, len(self.dscontent))
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
                    logging.debug("[import] %s, sample count after: %s", self, len(self.dscontent))

                else:
                    success = True
                    if len(errors) == 0:
                        errors.append("Preview only. Confirm below to import this data with current settings.")

            if import_count > 0 or merge_count > 0:
                flash("Imported %s samples (%s merged)" % (import_count, merge_count), "success")
            if skip_count > 0:
                flash("Skipped %s samples with empty ID or text" % skip_count, "warning")

            Activity.create(dbsession, session_user, self, "import_complete",
                            "total: %s, merged: %s, skipped: %s" %
                            (import_count, merge_count, skip_count))

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


@dataclass
class AnnotationTask:
    id: str
    name: str = None
    dataset: object = None
    progress: int = 0
    progress_beforetoday: int = 0
    progress_today: int = 0
    user_roles: List = field(default_factory=[])
    splits: List = None
    size: int = 0
    annos: int = 0
    annos_today: int = 0
    can_annotate: bool = True

    def calculate_progress(self):
        if self.size and self.size > 0 and self.annos and self.annos > 0:
            self.progress = min(round(self.annos / self.size * 100.0), 100.0)
            self.progress_today = min(round(self.annos_today / self.size * 100.0), 100.0)
            self.progress_beforetoday = self.progress - self.progress_today


def prep_sql(sql_raw):
    sql_raw = "\n".join(filter(lambda line: line != "", map(str.strip, sql_raw.strip().split("\n"))))
    return sql_raw.replace("\n\n", "\n").strip()
