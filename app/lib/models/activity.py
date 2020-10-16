"""
Model for generic activities (e.g. change events, comments).
"""
import logging
import json

from sqlalchemy import Column, Integer, String, desc, func, ForeignKey, or_
from sqlalchemy.orm import relationship
from sqlalchemy.types import DateTime

from app.lib.database_internals import Base
import app.lib.database as db


class Activity(Base):
    __tablename__ = 'activity'

    event_id = Column(Integer, primary_key=True)

    owner_id = Column(Integer, ForeignKey("users.uid"))
    owner = relationship("User", lazy="joined")

    created = Column(DateTime(timezone=True), server_default=func.now())
    edited = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # the target column encodes which item (dataset, sample, ...) this activity event refers to
    target = Column(String, nullable=False)
    # the scope may be used to restrict an activitiy, e.g. to switch a comment
    # between public/curator-only visibility
    scope = Column(String, nullable=False, default="")

    content = Column(String, nullable=False)

    def load_target(self, dbsession):
        if self.target is None:
            return None

        if self.target.startswith(db.User.activity_prefix()):
            return db.User.by_id(dbsession, int(self.target[len(db.User.activity_prefix()):]), no_error=True)
        if self.target.startswith(db.Dataset.activity_prefix()):
            return db.Dataset.by_id(dbsession, int(self.target[len(db.Dataset.activity_prefix()):]), no_error=True)
        return "unknown target %s" % self.target

    @staticmethod
    def user_history(dbsession, owner, scope_in=None, limit=None):
        qry = dbsession.query(Activity)

        if owner is None:
            raise Exception("Activity::user_history requires a non-null user object or ID")

        target_filter = db.User.activity_prefix() + str(owner.uid)

        if isinstance(owner, db.User):
            qry = qry.filter(or_(
                                Activity.target == target_filter,
                                Activity.owner == owner,
                                ))
        elif isinstance(owner, int):
            qry = qry.filter(or_(
                                Activity.target == target_filter,
                                Activity.owner_id == owner.uid,
                                ))
        else:
            raise Exception("Activity::user_history requires the owner argument by of type User or int")

        if scope_in is not None and len(scope_in) > 0:
            qry = qry.filter(Activity.scope.in_(scope_in))

        qry = qry.order_by(Activity.event_id.desc())

        if limit is not None:
            qry = qry.limit(limit)

        return qry.all()

    def formatted_create(self):
        if self.created is None:
            return None

        return self.created.strftime("%Y-%m-%d")

    @staticmethod
    def by_owner(dbsession, owner, scope_in=None, limit=None):
        qry = dbsession.query(Activity)

        if owner is None:
            raise Exception("Activity::by_owner requires a non-null user object or ID")

        if isinstance(owner, db.User):
            qry = qry.filter(Activity.owner == owner)
        elif isinstance(owner, int):
            qry = qry.filter(Activity.owner_id == owner.uid)
        else:
            raise Exception("Activity::by_owner requires the owner argument by of type User or int")

        if scope_in is not None and len(scope_in) > 0:
            qry = qry.filter(Activity.scope.in_(scope_in))

        qry = qry.order_by(Activity.event_id.desc())

        if limit is not None:
            qry = qry.limit(limit)

        return qry.all()

    @staticmethod
    def by_target(dbsession, target, scope_in=None, like_target=False):
        qry = dbsession.query(Activity)

        if like_target:
            qry = qry.filter(Activity.target.like(target))
        else:
            qry = qry.filter_by(target=target)

        if scope_in is not None and len(scope_in) > 0:
            qry = qry.filter(Activity.scope.in_(scope_in))

        qry = qry.order_by(desc(Activity.event_id))
        return qry.all()

    @staticmethod
    def to_activity_target(target):
        if target is None:
            raise ValueError("target cannot be null")

        if isinstance(target, str):
            return target

        try:
            return target.activity_target()
        except AttributeError:
            return str(target)

    @staticmethod
    def create(dbsession, owner, target, scope, content):
        target = Activity.to_activity_target(target)
        if not isinstance(content, str):
            content = json.dumps(content)

        log_activity = Activity()
        log_activity.owner = owner
        log_activity.target = target
        log_activity.scope = scope
        log_activity.content = content

        dbsession.add(log_activity)
        logging.debug("activity created for target %s", target)

        dbsession.flush()
        return log_activity

    def __str__(self):
        return "[Activity #%s (%s) %s => %s]" % (self.event_id, self.owner, self.target, self.scope)
