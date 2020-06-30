import app.lib.database as db

with db.session_scope() as dbsession:
    db.create_user(dbsession)
