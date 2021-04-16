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


class DatasetTask(Base):
    __tablename__ = 'tasks'

    task_id = Column(Integer, primary_key=True)

    dataset_id = Column(Integer, ForeignKey("datasets.dataset_id"), primary_key=True)
    dataset = relationship("Dataset", back_populates="dstasks")

    taskorder = Column(Integer, nullable=False, default=0)
    taskconfig = Column(JSON, nullable=False)

    def __repr__(self):
        return "<DatasetTask %s/%s (%s)>" % (self.dataset.get_name(), self.taskconfig.get("title", ""), self.taskorder)

    def activity_target(self):
        return "SAMPLE:%s" % self.sample_index
