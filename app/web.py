"""
Main entrypoint.
"""

import os
import sys
import logging
import atexit
from datetime import datetime

from flask import Flask, redirect, render_template, request, url_for, session

import app.lib.config as config
from app import __version__ as app_version

BASEURI = config.get("base_uri", "/omen") or "/omen"
flask_app = app = Flask(__name__, static_url_path=BASEURI + "/static")

app.secret_key = config.get_flask_secret()

logging.basicConfig(level=config.get("log_level", "DEBUG").upper(),
                    format='%(asctime)s %(name)-12s %(levelname)-8s %(message)s',
                    datefmt='%m-%d %H:%M')

import app.lib.database as db  # noqa
import app.lib.crypto as app_crypto  # noqa

try:
    from app.lib.getch import getch
except ImportError as _:  # noqa: F841
    print("failed to import getch implementation supported by current OS", file=sys.stderr)

db_init_okay = False
try:
    db.init_db()
    db_init_okay = True
except Exception as e:  # pylint: disable=broad-except
    print("Failed to initialize database: %s" % e, file=sys.stderr)

    if 'reset_database' not in sys.argv:
        import traceback
        traceback.print_exc()
        sys.exit(1)
    else:
        print("continuing to CLI invocation anyway")


@app.before_request
def check_auth():
    if request and request.url_rule and request.url_rule.endpoint in ['login', 'static', 'accept_invite']:
        return None
    if session and 'user' in session and not session['user'] is None:
        return None
    return redirect(url_for('login'))


@app.context_processor
def inject_globals():
    is_authenticated = False
    if 'user' in session and session['user'] is not None:
        is_authenticated = True

    annotation_tasks = None
    dataset_roles = {}
    with db.session_scope() as dbsession:
        if is_authenticated:
            annotation_tasks = db.datasets.annotation_tasks(dbsession, session['user'])
            dataset_roles = db.datasets.dataset_roles(dbsession, session['user'])

    def calculate_votes(row, anno_columns):
        if row is None or anno_columns is None:
            return None
        vote_count = {}

        for column in anno_columns:
            if "-" not in column or column not in row:
                continue
            row_user = column.split("-", 2)[-1]
            row_tag = row[column]
            if row_tag is None or row_tag == "":
                continue

            if row_tag not in vote_count:
                vote_count[row_tag] = []
            vote_count[row_tag].append(row_user)

        votes = {}
        for k, v in reversed(sorted(vote_count.items(), key=lambda i: i[1])):
            votes[k] = v

        return votes

    return dict(product_name=config.get("product_name", "Annotations"),
                is_authenticated=is_authenticated,
                tasks=annotation_tasks,
                calculate_votes=calculate_votes,
                cur_year=datetime.utcnow().year,
                app_version=app_version,
                dataset_roles=dataset_roles)


@app.errorhandler(404)
def page_not_found(error):
    return render_template("404.html", error=error), 404


@app.errorhandler(400)
def bad_request_error(error):
    return render_template("400.html", error=error), 400


import app.routing


@flask_app.cli.command("reset_database")
def cli_reset_database():
    print("Warning: Database content will be deleted. Is this okay? [y/N]")
    choice = getch()
    print(choice)
    if not choice:
        print("Aborting.")
        sys.exit(1)
    if not choice.lower().startswith("y"):
        print("Aborting.")
        sys.exit(1)

    print("executing db::drop_all()")
    if not db_init_okay:
        print("reinitializing database")
        db.init_db()
    print(db.flask_db.drop_all())
    print("all done")


@flask_app.cli.command("createuser")
def cli_createuser():
    with db.session_scope() as dbsession:
        db.User.create_user(dbsession)


server_status = None


def on_shutdown():
    global server_status
    logging.info("server shutdown received")


def on_starting(_):
    global server_status
    logging.info("server startup received")

    app_crypto.initialize()

    server_status = "started"


# make sure startup/shutdown handlers are called when not
# automatically invoked through the gunicorn events
exec_environment = "gunicorn"
if os.environ.get("FLASK_RUN_FROM_CLI", "").strip() == "true":
    exec_environment = "flask"

if exec_environment == "flask" and server_status is None:
    on_starting(None)
    atexit.register(on_shutdown)

app = flask_app

if __name__ == '__main__':
    app.run()
