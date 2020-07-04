import app.lib.database as db

def run_script():
    with db.session_scope() as dbsession:
        db.create_user(dbsession)
