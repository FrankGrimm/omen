"""
Flask request setup and teardown
"""
from flask import session

from app.web import app, BASEURI, db


@app.before_request
def before_handler():
    req_count = session.get("request_counter", None)
    if not req_count:
        req_count = 0
    req_count += 1
    session['request_counter'] = req_count
