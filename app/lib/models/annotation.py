"""
Single annotation entity.
"""
from sqlalchemy import Column, Integer, String, JSON, ForeignKey, and_, ForeignKeyConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.orm.attributes import flag_dirty, flag_modified

import logging

from app.lib.database_internals import Base
from app.lib.models.datasetcontent import DatasetContent


class Annotation(Base):
    __tablename__ = "annotations"

    owner_id = Column(Integer, ForeignKey("users.uid"), primary_key=True)
    owner = relationship("User", back_populates="annotations")

    dataset_id = Column(Integer, ForeignKey("datasets.dataset_id"), primary_key=True)
    dataset = relationship("Dataset", back_populates="dsannotations")

    sample = Column(String, primary_key=True)
    sample_index = Column(Integer, primary_key=True)

    data = Column(JSON)
    __table_args__ = (
        ForeignKeyConstraint(
            [dataset_id, sample, sample_index],
            [DatasetContent.dataset_id, DatasetContent.sample, DatasetContent.sample_index],
        ),
        {},
    )

    def __repr__(self):
        return "<Annotation (dataset: %s, owner: %s, sample: %s, data: %s)>" % (
            self.dataset_id,
            self.owner_id,
            self.sample,
            self.data,
        )
