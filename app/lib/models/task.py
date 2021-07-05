"""
Task definition entity
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
from app.lib.npencoder import NpEncoder

import app.lib.iaa as iaa

class DatasetTask(Base):
    __tablename__ = 'tasks'

    task_id = Column(Integer, primary_key=True, autoincrement=True)

    dataset_id = Column(Integer, ForeignKey("datasets.dataset_id"))
    dataset = relationship("Dataset", back_populates="dstasks", lazy="joined")

    taskorder = Column(Integer, nullable=False, default=0)
    taskconfig = Column(JSON, nullable=False)

    def __repr__(self):
        return "<DatasetTask %s (%s)>" % (self.taskconfig.get("title", str(self.task_id)), self.taskorder)

    def activity_target(self):
        return "TASK:%s" % self.task_id

    @property
    def name(self):
        return self.taskconfig.get("title", f"Task #{self.task_id}")

    @property
    def tasktype(self):
        return self.taskconfig.get("type", "tags")

    @staticmethod
    def create(dbsession, dataset, newtaskdef_type):
        new_taskdef = DatasetTask()
        new_taskdef.task_id = None
        new_taskdef.taskconfig = {"type": newtaskdef_type}
        new_taskdef.dataset_id = dataset.dataset_id

        dbsession.add(new_taskdef)
        logging.debug("task definition created for %s", dataset)

        dbsession.commit()
        dbsession.flush()
        return new_taskdef

    def validate(self, errorlist):
        if self.tasktype == "tags":
            if len(self.get_taglist()) == 0:
                errorlist.append("no tags defined")

    @property
    def anno_task_id(self):
        return str(self.task_id)

    def get_taglist(self, include_metadata=False):
        tags = self.taskconfig.get("taglist", None)
        tags = tags or []

        if not include_metadata:
            return tags

        tag_data = {}
        tag_metadata = self.taskconfig.get("tagdetails", {})

        for tag in tags:
            curtag_metadata = tag_metadata.get(tag, {})
            tag_data[tag] = {
                "icon": curtag_metadata.get("icon", None),
                "color": curtag_metadata.get("color", "")
            }

        return tag_data

    def update_tag_metadata(self, tag, newvalues):
        import sys
        print("UPDATE TAG METADATA", tag, newvalues, self.task_id, file=sys.stderr)
        tag_metadata = self.taskconfig.get("tagdetails", {})
        if tag not in tag_metadata:
            tag_metadata[tag] = {}

        for k, v in newvalues.items():
            tag_metadata[tag][k] = v

        self.taskconfig['tagdetails'] = tag_metadata

        print("new taskconfig", self.task_id, self.taskconfig, file=sys.stderr)

    def set_taglist(self, new_tags):
        if self.taskconfig is None:
            self.taskconfig = {}

        new_tags = filter(lambda l: l is not None and l.strip() != '', new_tags)
        new_tags = map(lambda l: l.strip(), new_tags)
        new_tags = list(new_tags)
        self.taskconfig['taglist'] = new_tags

    def dirty(self, dbsession):
        db_state = inspect(self)
        if db_state.deleted:
            return False
        flag_dirty(self)
        flag_modified(self, "taskconfig")
        dbsession.add(self)
        return True

    def annotation_counts(self, dbsession):
        """
        TODO does not respect task yet
        """
        params = {
                "dataset_id": self.dataset_id,
                "taskid": str(self.task_id)
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
            AND anno.task_id == %(taskid)s
        GROUP BY
            users.uid, anno.task_id, anno.data->'value' #>> '{}'
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
        """
        TODO does not respect task yet
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


def prep_sql(sql_raw):
    sql_raw = "\n".join(filter(lambda line: line != "", map(str.strip, sql_raw.strip().split("\n"))))
    return sql_raw.replace("\n\n", "\n").strip()
