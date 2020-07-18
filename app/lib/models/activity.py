"""
Model for generic activities (e.g. change events, comments).
"""
from sqlalchemy import Column, Integer, String, desc, func, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.types import DateTime

# import logging

from app.lib.database_internals import Base


class Activity(Base):
    __tablename__ = 'activity'

    event_id = Column(Integer, primary_key=True)

    owner_id = Column(Integer, ForeignKey("users.uid"))
    owner = relationship("User")

    created = Column(DateTime(timezone=True), server_default=func.now())
    edited = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # the target column encodes which item (dataset, sample, ...) this activity event refers to
    target = Column(String, nullable=False)
    # the scope may be used to restrict an activitiy, e.g. to switch a comment
    # between public/curator-only visibility
    scope = Column(String, nullable=False, default="")

    content = Column(String, nullable=False)

    @staticmethod
    def by_target(dbsession, target, scope_in=None, like_target=False):
        qry = dbsession.query(Activity)

        if like_target:
            qry = qry.filter(Activity.target.like(target))
        else:
            qry = qry.filter_by(target=target)

        if scope_in is not None and len(scope_in) > 0:
            qry = qry.filter(Activity.scope.in_(scope_in))

        qry = qry.order_by(desc(Activity.created))
        return qry.all()

    def __str__(self):
        return "[Activity #%s (%s) %s => %s]" % (self.event_id, self.owner, self.target, self.scope)
