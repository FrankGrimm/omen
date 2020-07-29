"""
Database model and utilities
"""
from contextlib import contextmanager

import re
import sys
import atexit
import logging

from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from app.lib.database_internals import Base

import app.web as web
from app.lib import config


from app.lib.models.user import User
from app.lib.models.datasetcontent import DatasetContent
from app.lib.models.annotation import Annotation
from app.lib.models.dataset import *
from app.lib.models.activity import Activity

flask_db = None
migrate = None


def fprint(*args):
    print(*args, file=sys.stderr)


@contextmanager
def session_scope():
    fdb_session = flask_db.session
    try:
        yield fdb_session
        fdb_session.commit()
    except Exception as e:
        fprint("rolling back transaction after error (%s)" % e)
        fdb_session.rollback()
        raise
    finally:
        fdb_session.close()


def shutdown():
    print("DB shutdown")
    engine = flask_db.get_engine()
    if engine is not None:
        engine.dispose()


def masked_connstring(connstring):
    return re.sub(r"(?<=\:\/\/).*(?=@.*)", r"****", connstring)


def connect():
    global flask_db, migrate

    print("[database] connect")
    connection_string = config.get("dbconnection", raise_missing=True)
    web.app.config["SQLALCHEMY_DATABASE_URI"] = connection_string
    if not config.get("db_debug", None) is None:
        web.app.config["SQLALCHEMY_ECHO"] = True
    web.app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    flask_db = SQLAlchemy(web.app, session_options={"expire_on_commit": False, "autoflush": False})
    migrate = Migrate(web.app, flask_db)

    print("[database] connection string (masked): %s" % masked_connstring(connection_string))
    db_pool_size = config.get("dbpool", "10", raise_missing=False)
    if not isinstance(db_pool_size, int):
        db_pool_size = int(db_pool_size)
    if not db_pool_size:
        db_pool_size = 1

    atexit.register(shutdown)
    print("[database] connected")


def init_db():
    global flask_db
    connect()

    with web.app.app_context():
        with session_scope() as dbsession:
            User.ensure_system_user_exists(dbsession)
            try:
                logging.info("[users] system contains %s user accounts", dbsession.query(User).count())
                logging.info("[users] you can create users with the scripts/createuser script")
            except:
                logging.warning("[error] could not enumerate users, " +
                                "make sure database is initialized and up to date (./bin/flaskdb upgrade)")
