"""
Comment data model. This functionality is built on top of the `Activity` entity and does not require its own table.
"""
import logging
from enum import Enum
from typing import List

import app.lib.database as db
from app.lib.models.activity import Activity


class CommentScope(Enum):
    NOTE = "comment_note"
    PUBLIC = "comment_public"

class Comments:
    @staticmethod
    def comment(dbsession, owner: db.User, target, scope: CommentScope, text: str):
        if isinstance(scope, str):
            scope = CommentScope(scope)

        newactivity = Activity.create(dbsession, owner, target, scope.value, text)

        return Comment(newactivity, owner)

    @staticmethod
    def fortarget(dbsession, target, userobj: db.User, scopes: List[CommentScope] = None):
        if scopes is None:
            scopes = [CommentScope.NOTE, CommentScope.PUBLIC]

        scopes = [scope.value for scope in scopes]
        result_comments = Activity.by_target(dbsession, target, scope_in=scopes, like_target=False)
        result_comments = reversed([Comment(activity, userobj) for activity in result_comments])

        result_comments = [comment for comment in result_comments if comment.visible_to(userobj)]

        return result_comments

class Comment:
    def __init__(self, activity_entity, session_user=None):
        self.entity = activity_entity
        self.owned = False
        if session_user is not None and activity_entity.owner is not None \
                and activity_entity.owner.uid == session_user.uid:
            self.owned = True

    def visible_to(self, userobj):
        if self.scope == CommentScope.NOTE and not self.entity.owner is userobj:
            return False
        return True

    @property
    def scope(self):
        try:
            return CommentScope(self.entity.scope)
        except ValueError:
            return None

    @scope.setter
    def scope(self, newscope: CommentScope):
        if isinstance(newscope, CommentScope):
            newscope = newscope.value
        self.entity.scope = newscope

    @property
    def content(self):
        return self.entity.content

    @content.setter
    def content(self, text: str):
        self.entity.content = text

    def delete(self, dbsession):
        if not self.owned:
            raise Exception("tried to delete comment not owned by current user")
        dbsession.delete(self.entity)

    def to_json(self):
        return {
                "id": self.entity.event_id,
                "owner": self.entity.owner.get_name(),
                "isowned": self.owned,
                "created": self.entity.created.strftime("%b %d %Y %H:%M") if self.entity.created is not None else "",
                "scope": self.scope.value if self.scope is not None else None,
                "text": self.entity.content,
                }
