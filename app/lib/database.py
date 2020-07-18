"""
Database model and utilities
"""
from contextlib import contextmanager

import sys
import atexit

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
    session = flask_db.session
    try:
        yield session
        session.commit()
    except Exception as e:
        fprint("rolling back transaction after error (%s)" % e)
        session.rollback()
        raise
    finally:
        session.close()


def shutdown():
    print("DB shutdown")
    engine = flask_db.get_engine()
    if not engine is None:
        engine.dispose()


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

    masked_connstring = connection_string
    if 'password' in masked_connstring.lower():
        delim = masked_connstring.lower().index("password")
        masked_connstring = masked_connstring[:delim+ len("password")] + ":::" + "*" * len(masked_connstring[delim :])
    print("[database] connection string (masked): %s" % masked_connstring)
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
            try:
                fprint("[users] system contains %s user accounts" % dbsession.query(User).count())
                fprint("[users] you can create users with the scripts/createuser script")
            except:
                fprint("[error] could not enumerate users, make sure database is initialized and up to date (./bin/flaskdb upgrade)")
