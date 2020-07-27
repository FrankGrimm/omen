"""
Global view helpers
"""

from functools import wraps

from flask import redirect, request, url_for, session

from app.web import app, BASEURI, db


def login_required(func):
    @wraps(func)
    def decorated_function(*args, **kwargs):
        if not session or session.get("user", None) is None:
            return redirect(url_for("login", backto=request.url))
        return func(*args, **kwargs)
    return decorated_function


def get_session_user(dbsession):
    session_user = None
    if 'user' in session and session.get("user", None) is not None:
        session_user = db.User.by_id(dbsession, session['user'])
    return session_user
