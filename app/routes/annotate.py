"""
Annotation routes
"""

from flask import request, session, abort, flash, render_template

from app.lib.viewhelpers import login_required, get_session_user
from app.web import app, BASEURI, db


def handle_set_annotation(dbsession, dataset):

    set_sample_idx = None
    set_sample_value = None
    set_task_id = None
    try:
        if request.args.get("set_sample_idx", None) is not None:
            set_sample_idx = str(int(request.args.get("set_sample_idx", None)))
    except ValueError:
        pass
    try:
        if request.args.get("set_taskid", None) is not None:
            set_task_id = int(request.args.get("set_taskid", None))
    except ValueError:
        pass

    if set_sample_idx is not None:
        set_sample_value = request.args.get("set_value", "")[:1000]

    if set_sample_idx is not None and set_sample_value is not None and set_task_id is not None:
        dataset.setanno(dbsession, get_session_user(dbsession), set_sample_idx, set_task_id, set_sample_value)


def get_votes_disabled(dbsession, dataset, user_roles, session_user, sample_id):
    """
    @deprecated
    """
    if sample_id is None:
        return None

    anno_votes = None
    if 'curator' in user_roles:
        anno_votes = dataset.get_anno_votes(dbsession, sample_id=sample_id,
                                            exclude_user=session_user)
        for tag in anno_votes.keys():
            anno_votes[tag] = [annouser.get_name() for annouser in anno_votes[tag]]
    return anno_votes


def get_random_sample(df, id_column):
    no_anno = df[~(df.annotations != '')]
    # make sure to randomly select a sample that has not been annotated yet (if any are left)
    if not no_anno.empty:
        df = no_anno
    if df.empty:
        return None, None

    sample_row = df.sample(n=1)
    sample_idx = sample_row.index.values.astype(int)[0]
    sample_id = sample_row[id_column].values[0]
    return sample_idx, sample_id


def get_annotation_dataframe(dbsession, task, session_user, min_sample_idx=None, random_order=False):
    order_by = "o.sample_index, usercol_value ASC NULLS LAST"
    if random_order:
        order_by = "random()"

    no_anno_df, annotation_columns, total = task.dataset.annotations(dbsession,
                                                                     foruser=session_user,
                                                                     user_column="annotations",
                                                                     restrict_view="untagged",
                                                                     page_size=10,
                                                                     only_user=True,
                                                                     min_sample_index=min_sample_idx,
                                                                     splits=task.splits,
                                                                     order_by=order_by)
    if no_anno_df.empty:
        if task.dataset.dsmetadata.get("allow_restart_annotation", False):
            no_anno_df, annotation_columns, total = task.dataset.annotations(dbsession,
                                                                             foruser=session_user,
                                                                             user_column="annotations",
                                                                             restrict_view="tagged",
                                                                             page_size=10,
                                                                             only_user=True,
                                                                             min_sample_index=min_sample_idx,
                                                                             splits=task.splits,
                                                                             order_by=order_by)
    return no_anno_df, annotation_columns, total


def get_sample_index(dbsession, task, session_user, random_order=False):
    sample_idx = None
    sample_id = None

    if not random_order:
        try:
            if not request.args.get("sample_idx", None) is None:
                sample_idx = int(request.args.get("sample_idx", None))

        except ValueError:
            pass

        no_anno_df, annotation_columns, total = get_annotation_dataframe(dbsession,
                                                                         task,
                                                                         session_user,
                                                                         min_sample_idx=sample_idx,
                                                                         random_order=False)
    else:
        no_anno_df, annotation_columns, total = get_annotation_dataframe(dbsession,
                                                                         task,
                                                                         session_user,
                                                                         random_order=True)

    if no_anno_df.empty:
        return sample_idx, sample_id, no_anno_df, annotation_columns, total

    if sample_idx is None:
        if task.dataset.dsmetadata.get("annoorder", "sequential") == 'random':
            sample_idx, sample_id = get_random_sample(no_anno_df, task.dataset.get_id_column())
        else:
            first_row = no_anno_df.iloc[no_anno_df.index[0]]
            sample_idx = first_row['sample_index']
            sample_id = first_row[task.dataset.get_id_column()]
    return sample_idx, sample_id, no_anno_df, annotation_columns, total


def increment_task_states(df, task, annotation_tasks):
    if "set_sample_idx" in request.args and df is not None and not df.empty:
        if task.annos < task.size:
            task.annos += 1
        if task.annos_today < task.size:
            task.annos_today += 1

        for atask in annotation_tasks:
            if atask.id != task.id:
                continue
            if atask.annos < atask.size:
                atask.annos += 1
            if atask.annos_today < atask.size:
                atask.annos_today += 1


def generate_task_complete_activity(dbsession, activity_owner, dataset, task):
    # check if event was already recorded
    # this might be the case on page reloads or if re-annotation was allowed

    activity_content = ""
    if task is not None and task.splits is not None and len(task.splits) > 0:
        activity_content = "%s work %s: %s" % (len(task.splits),
                                               "packages" if len(task.splits) > 1 else "package",
                                               ", ".join(list(sorted(task.splits))))

    qry = dbsession.query(db.Activity)
    qry = qry.filter(db.Activity.owner == activity_owner,
                     db.Activity.target == dataset.activity_target(),
                     db.Activity.scope == "task_complete",
                     db.Activity.content == activity_content)
    existing = qry.one_or_none()

    if existing is None:
        db.Activity.create(dbsession,
                           activity_owner,
                           dataset.activity_target(),
                           "task_complete",
                           activity_content)

@app.route(BASEURI + "/dataset/<dsid>/annotate", methods=["GET", "POST"])
@login_required
def annotate(dsid=None, sample_idx=None):
    dataset = None

    with db.session_scope() as dbsession:
        session_user = db.User.by_id(dbsession, session['user'])
        dataset = db.datasets.get_accessible_dataset(dbsession, dsid, "annotator")

        if dataset is None:
            return abort(404, description="Forbidden. User does not have annotation access to the requested dataset.")

        user_roles = dataset.get_roles(dbsession, session_user)

        task = dataset.get_task(dbsession, session_user)

        sample_idx, sample_id, df, _, _ = get_sample_index(dbsession, task, session_user)

        handle_set_annotation(dbsession, dataset)

        sample = dataset.sample_by_index(dbsession, sample_idx) if sample_idx is not None else None
        sample_id = sample.sample if sample is not None else None

        additional_content = None
        additional_content_fields = dataset.dsmetadata.get("additional_column", None)
        if additional_content_fields is not None:
            if isinstance(additional_content_fields, str):
                if additional_content_fields.strip() != "":
                    additional_content_fields = [additional_content_fields]
                else:
                    additional_content_fields = []

            additional_content = {}
            for additional_content_field in additional_content_fields:
                additional_content[additional_content_field] = None

                if sample is None or sample.data is None:
                    continue
                if additional_content_field in sample.data:
                    additional_content[additional_content_field] = str(sample.data[additional_content_field])

        sample_prev, _ = dataset.get_prev_sample(dbsession, sample_idx, session_user, task.splits)
        sample_next, _ = dataset.get_next_sample(dbsession, sample_idx, session_user, task.splits)

        curanno_data = dataset.getanno(dbsession, session_user, "*", sample_id) if sample_id is not None else None
        curanno = None
        if curanno_data and 'data' in curanno_data:
            curanno = curanno_data

        annotation_tasks = db.datasets.annotation_tasks(dbsession, session_user)
        increment_task_states(df, task, annotation_tasks)

        task.calculate_progress()

        all_done = sample_idx is None or df is None or df.empty
        if not all_done:
            all_done = task.progress >= 100.0
        if all_done:
            flash("Task complete! You have annotated all samples in this task", "success")
            generate_task_complete_activity(dbsession, session_user, dataset, task)

        if dataset.dsmetadata.get("allow_restart_annotation", False) or \
           "sample_idx" in request.args:
            all_done = False

        template_name = "annotate.html"
        if request.args.get("contentonly", None) is not None:
            template_name = "annotate_body.html"

        return render_template(template_name, dataset=dataset,
                               task=task,
                               tasks=annotation_tasks,
                               all_done=all_done,
                               sample_id=sample_id,
                               sample_idx=sample_idx,
                               sample=sample,
                               additional_content=additional_content,
                               sample_prev=sample_prev,
                               sample_next=sample_next,
                               curanno=curanno)
