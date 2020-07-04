import sys
from flask import Flask, flash, redirect, render_template, request, url_for, session, Response

from datetime import datetime

import app.lib.config as config

BASEURI = config.get("base_uri", "/omen") or "/omen"
flask_app = app = Flask(__name__, static_url_path=BASEURI + "/static")
app.secret_key = config.get("flask_secret", raise_missing = True)

import app.lib.database as db

db_init_okay = False
try:
    db.init_db()
    db_init_okay = True
except Exception as e:
    print("Failed to initialize database: %s" % e, file=sys.stderr)
    if not 'reset_database' in sys.argv:
        sys.exit(1)
    else:
        print("continuing to CLI invocation anyway")

@app.before_request
def check_auth():
    if request and request.url_rule and request.url_rule.endpoint in ['login', 'static']:
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
    with db.session_scope() as dbsession:
        if is_authenticated:
            annotation_tasks = db.annotation_tasks(dbsession, session['user'])

    return dict(product_name=config.get("product_name", "Annotations"), \
                is_authenticated=is_authenticated,
                tasks=annotation_tasks,
                cur_year=datetime.utcnow().year)

@app.errorhandler(404)
def page_not_found(error):
    return render_template("404.html", error=error), 404

import app.views

@flask_app.cli.command("reset_database")
def cli_reset_database():
    from app.lib.getch import getch
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
        db.init_db(skip_create = True)
    print( db.flask_db.drop_all() )
    print("all done")

@flask_app.cli.command("createuser")
def cli_createuser():
    import app.scripts.createuser

app = flask_app

if __name__ == '__main__':
    app.run()
