"""
Route definitions and business logic.
"""
from flask import session, render_template


# from app.lib.viewhelpers import login_required

import app.routes.routesetup
import app.routes.templates
import app.routes.user
import app.routes.dataset
import app.routes.dataset_inspect
import app.routes.annotate
import app.routes.api


from app.web import app, BASEURI, db


@app.route('/')
@app.route(BASEURI + '/')
def index():
    with db.session_scope() as dbsession:

        session_user_id = session['user']

        session_user = db.User.by_id(dbsession, session_user_id)
        annotation_tasks = db.datasets.annotation_tasks(dbsession, session_user_id)

        my_datasets = db.datasets.my_datasets(dbsession, session_user_id)
        access_datasets = db.datasets.accessible_datasets(dbsession, session_user_id)

        user_activities = db.Activity.for_user(dbsession, session_user)

        ds_errors = {}
        for cur_dataset in my_datasets.values():
            if cur_dataset in ds_errors:
                continue
            ds_errors[cur_dataset] = cur_dataset.check_dataset()

        for cur_dataset in access_datasets.values():
            if cur_dataset in ds_errors:
                continue
            ds_errors[cur_dataset] = cur_dataset.check_dataset()

        return render_template('index.html', my_datasets=my_datasets,
                               access_datasets=access_datasets,
                               ds_errors=ds_errors,
                               dbsession=dbsession,
                               session_user=session_user,
                               tasks=annotation_tasks,
                               user_activities=user_activities
                               )
