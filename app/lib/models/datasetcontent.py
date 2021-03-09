"""
DatasetContent entity that holds information on imported samples.
"""

from sqlalchemy import Column, Integer, String, JSON, ForeignKey
from sqlalchemy.orm import relationship

from app.lib.database_internals import Base


class DatasetContent(Base):
    __tablename__ = "datasetcontent"

    sample_index = Column(Integer, autoincrement=True, primary_key=True)

    dataset_id = Column(Integer, ForeignKey("datasets.dataset_id"), primary_key=True)
    dataset = relationship("Dataset", back_populates="dscontent")

    sample = Column(String, primary_key=True)
    content = Column(String, nullable=False)
    split_id = Column(String, nullable=True)

    annotations = relationship("Annotation", cascade="all, delete-orphan")

    data = Column(JSON)

    def __repr__(self):
        return "<DatasetContent %s/%s (%s)>" % (self.dataset.get_name(), self.sample_index, self.sample)

    def activity_target(self):
        return "SAMPLE:%s" % self.sample_index
