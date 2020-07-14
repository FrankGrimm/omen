"""
Route definitions and business logic.
"""
from datetime import datetime
import os
import os.path
import tempfile
import re
import json
import string
from functools import wraps
from io import StringIO
import math

from markupsafe import Markup
from werkzeug.utils import secure_filename
from flask import flash, redirect, render_template, request, url_for, session, Response, abort

import app.lib.config as config
from app.web import app, BASEURI, db

def login_required(func):
    @wraps(func)
    def decorated_function(*args, **kwargs):
        if not session or \
                session.get("user", None) is None:
            return redirect(url_for("login", backto=request.url))
        return func(*args, **kwargs)
    return decorated_function

@app.template_filter(name="highlight")
def highlight(value, query):
    db.fprint("-" * 20, type(value), type(Markup(value)))
    if not query is None and query.strip() != "":
        query = r"(" + re.escape(query.strip()) + ")"
        value = Markup.escape(value)
        value = re.sub(query, lambda g: '<span class="ds_highlight">%s</span>' % g.group(1),
                       value, flags=re.IGNORECASE)

    return Markup(value)

@app.route('/')
@app.route(BASEURI + '/')
def index():
    with db.session_scope() as dbsession:

        session_user = db.by_id(dbsession, session['user'])
        annotation_tasks = db.annotation_tasks(dbsession, session['user'])

        my_datasets = db.my_datasets(dbsession, session['user'])
        access_datasets = db.accessible_datasets(dbsession, session['user'])

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
                                    tasks=annotation_tasks)

@app.before_request
def before_handler():
    req_count = session.get("request_counter", None)
    if not req_count:
        req_count = 0
    req_count += 1
    session['request_counter'] = req_count
    # print("REQCOUNT", session.get("user", None), req_count)

@app.route(BASEURI + "/logout")
@login_required
def logout():
    _ = [session.pop(key) for key in list(session.keys())]
    session.clear()

    return redirect(url_for('index'))

def get_accessible_dataset(dbsession, dsid, check_role=None):
    session_user = db.by_id(dbsession, session['user'])

    my_datasets = db.my_datasets(dbsession, session_user)
    access_datasets = db.accessible_datasets(dbsession, session_user)

    cur_dataset = None
    if not dsid is None and dsid in my_datasets:
        cur_dataset = my_datasets[dsid]
    if not dsid is None and dsid in access_datasets:
        cur_dataset = access_datasets[dsid]

    if check_role is None:
        return cur_dataset

    if not cur_dataset is None:
        user_roles = cur_dataset.get_roles(dbsession, session_user)
        if not check_role in user_roles:
            return None

    return cur_dataset

def reorder_dataframe(df, cur_dataset, annotation_columns):
    columns = list(df.columns.intersection(["sample_index", cur_dataset.get_id_column(), cur_dataset.get_text_column()])) + \
                list(df.columns.intersection(annotation_columns))

    # drop other columns
    df = df.reset_index()
    df = df[columns]
    # reorder
    df = df[columns]
    return df

@app.route(BASEURI + "/dataset/<dsid>/inspect", methods=["GET", "POST"])
@login_required
def inspect_dataset(dsid=None):
    with db.session_scope() as dbsession:

        restrict_view = None
        if not request.args.get("restrict_view", None) is None and \
                request.args.get("restrict_view", None).lower() in ['tagged', 'untagged']:
            restrict_view = request.args.get("restrict_view", None).lower()

        query = request.args.get("query", "").strip()

        cur_dataset = get_accessible_dataset(dbsession, dsid)
        session_user = db.by_id(dbsession, session['user'])

        tagstates = {}
        restrict_include = json.loads(request.args.get("restrict_taglist_include", "[]"))
        restrict_exclude = json.loads(request.args.get("restrict_taglist_exclude", "[]"))
        if not isinstance(restrict_include, list):
            restrict_include = []
        if not isinstance(restrict_exclude, list):
            restrict_exclude = []

        for tag in cur_dataset.get_taglist():
            tagstates[tag] = 0
            if tag in restrict_include:
                tagstates[tag] = 1
            elif tag in restrict_exclude:
                tagstates[tag] = 2

        template_name = "dataset_inspect.html"
        ctx_args = {}
        req_sample = request.args.get("single_row", "")
        if request.method == "POST":
            request.get_json(force=True)
        if request.json is not None:
            req_sample = request.json.get("single_row", "")

        if req_sample is not None and not req_sample == "":
            if request.json is not None and "set_tag" in request.json:
                cur_dataset.setanno(dbsession, session_user, req_sample, request.json.get("set_tag", None))

        # pagination
        page_size = 50
        page = 1
        pages = 1
        try:
            page_size = int(config.get("inspect_page_size", "50"))
        except ValueError as e:
            flash("Invalid config value for 'inspect_page_size': %s" % e, "error")

        try:
            page = int(request.args.get("page", "1"))
        except ValueError as e:
            flash("Invalid value for param 'page': %s" % e, "error")


        df, annotation_columns, results = cur_dataset.annotations(dbsession,
                                                foruser=session_user,
                                                page=page,
                                                page_size=page_size,
                                                user_column="annotations",
                                                query=query,
                                                tags_include=restrict_include,
                                                tags_exclude=restrict_exclude,
                                                restrict_view=restrict_view)

        df = reorder_dataframe(df, cur_dataset, annotation_columns)

        pages = math.ceil(results / page_size)
        if page > pages:
            page = pages

        pagination_size = 5
        pagination_elements = list(range(max(1, page - pagination_size),
                                         min(page + pagination_size + 1, pages + 1)))
        pagination_elements.sort()

        if req_sample != "":
            id_column = cur_dataset.get_id_column()

            template_name = "dataset_inspect_row.html"
            ctx_args['hide_nan'] = True
            ctx_args['id_column'] = id_column
            ctx_args['text_column'] = cur_dataset.get_text_column()

            for index, row in df.iterrows():
                if str(row["sample_index"]) != str(req_sample):
                    continue
                ctx_args['index'] = str(row["sample_index"])
                ctx_args['row'] = row

        return render_template(template_name, dataset=cur_dataset,
                                df=df,
                                restrict_view=restrict_view,
                                query=query,
                                page_size=page_size,
                                page=page,
                                pages=pages,
                                results=results,
                                tagstates=tagstates,
                                annotation_columns=annotation_columns,
                                pagination_elements=pagination_elements,
                                user_roles=cur_dataset.get_roles(dbsession, session_user),
                                **ctx_args
                                )

@app.route(BASEURI + "/dataset/<dsid>/download")
@login_required
def download(dsid=None):

    with db.session_scope() as dbsession:
        cur_dataset = get_accessible_dataset(dbsession, dsid)

        df, _, _ = cur_dataset.annotations(dbsession, foruser=session['user'])

        s = StringIO()
        df.to_csv(s)
        csvc = s.getvalue()

        download_filename = "dataset.csv"
        is_valid_char = lambda c: c in string.ascii_letters or c in string.digits or c in "-_. "
        dataset_name_sanitized = "".join(filter(is_valid_char, cur_dataset.get_name()))
        dataset_name_sanitized = dataset_name_sanitized.strip().replace(' ', '\\ ')

        if len(dataset_name_sanitized) > 0:
            download_filename = "%s.csv" % dataset_name_sanitized

        return Response(csvc,
            mimetype="text/csv",
            headers={"Content-disposition":
                     "attachment; filename=\"%s\"" % download_filename})

@app.route(BASEURI + "/dataset")
@app.route(BASEURI + "/dataset/<dsid>")
@login_required
def show_datasets(dsid=None):
    with db.session_scope() as dbsession:

        userobj = db.by_id(dbsession, session['user'])

        my_datasets = db.my_datasets(dbsession, session['user'])
        access_datasets = db.accessible_datasets(dbsession, session['user'])

        dataset = None
        if not dsid is None and dsid in my_datasets:
            dataset = my_datasets[dsid]
        if not dsid is None and dsid in access_datasets:
            dataset = access_datasets[dsid]

        ds_errors = {}
        for ds in my_datasets.values():
            if ds in ds_errors:
                continue
            ds_errors[ds] = ds.check_dataset()

        for ds in access_datasets.values():
            if ds in ds_errors:
                continue
            ds_errors[ds] = ds.check_dataset()

        return render_template('dataset.html', my_datasets=my_datasets, \
                                access_datasets=access_datasets, \
                                dataset=dataset, \
                                ds_errors=ds_errors, \
                                dbsession=dbsession, \
                                userobj=userobj)

@app.route(BASEURI + "/user/create", methods=["GET", "POST"])
@login_required
def createuser():
    return render_template("createuser.html")

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

def handle_set_annotation(dbsession, dataset, df, id_column):
    set_sample_idx = None
    set_sample_value = None
    try:
        if not request.args.get("set_sample_idx", None) is None:
            set_sample_idx = str(int(request.args.get("set_sample_idx", None)))
    except ValueError:
        pass

    if set_sample_idx is not None:
        set_sample_value = request.args.get("set_value", "")[:500]

    if set_sample_idx is not None and set_sample_value is not None:
        dataset.setanno(dbsession, session['user'], set_sample_idx, set_sample_value)

def get_votes(dbsession, dataset, user_roles, session_user, sample_id):
    anno_votes = None
    if 'curator' in user_roles:
        anno_votes = dataset.get_anno_votes(dbsession, sample_id=sample_id,
                                            exclude_user=session_user)
        for tag in anno_votes.keys():
            anno_votes[tag] = [annouser.get_name() for annouser in anno_votes[tag]]
    return anno_votes

def get_annotation_dataframe(dbsession, dataset, session_user, min_sample_idx=None, random_order=False):
    order_by = "usercol_value, dc.sample_index ASC NULLS LAST"
    if random_order:
        order_by = "random()"

    no_anno_df, annotation_columns, total = dataset.annotations(dbsession, foruser=session_user,
                                        user_column="annotations",
                                        restrict_view="untagged",
                                        page_size=10,
                                        only_user=True,
                                        min_sample_index=min_sample_idx,
                                        order_by=order_by)
    if no_anno_df.empty:
        no_anno_df, annotation_columns, total = dataset.annotations(dbsession, foruser=session_user,
                                    user_column="annotations",
                                    restrict_view="tagged",
                                    page_size=10,
                                    only_user=True,
                                    min_sample_index=min_sample_idx,
                                    order_by=order_by)

    return no_anno_df, annotation_columns, total

def get_sample_index(dbsession, dataset, session_user, random_order=False):
    sample_idx = None
    sample_id = None

    if not random_order:
        try:
            if not request.args.get("sample_idx", None) is None:
                sample_idx = int(request.args.get("sample_idx", None))
        except ValueError:
            pass

        no_anno_df, annotation_columns, total = get_annotation_dataframe(dbsession, dataset,
                session_user, min_sample_idx=sample_idx, random_order=False)
    else:
        no_anno_df, annotation_columns, total = get_annotation_dataframe(dbsession, dataset,
                session_user, random_order=True)

    # note that the random sample currently only gathers a sample from the first/current page
    if sample_idx is None:

        if dataset.dsmetadata.get("annoorder", "sequential") == 'random':
            sample_idx, sample_id = get_random_sample(no_anno_df, dataset.get_id_column())
        else:
           first_row = no_anno_df.iloc[no_anno_df.index[0]]
           sample_idx = first_row['sample_index']
           sample_id = first_row[dataset.get_id_column()]

    return sample_idx, sample_id, no_anno_df, annotation_columns, total


@app.route(BASEURI + "/dataset/<dsid>/annotate", methods=["GET", "POST"])
@login_required
def annotate(dsid=None, sample_idx=None):
    dataset = None

    with db.session_scope() as dbsession:
        session_user = db.by_id(dbsession, session['user'])
        dataset = get_accessible_dataset(dbsession, dsid, "annotator")

        if dataset is None:
            return abort(404, description="Forbidden. User does not have annotation access to the requested dataset.")

        user_roles = dataset.get_roles(dbsession, session_user)

        task = dataset.get_task(dbsession, session_user)

        db.task_calculate_progress(task)

        id_column = dataset.get_id_column()

        sample_idx, sample_id, df, annotation_columns, _ = get_sample_index(dbsession, dataset, session_user)

        sample_content = None

        handle_set_annotation(dbsession, dataset, df, id_column)

        random_sample, random_sample_id, _, _, _ = get_sample_index(dbsession, dataset, session_user, random_order=True)

        sample = dataset.sample_by_index(dbsession, sample_idx)
        sample_content = sample.content
        sample_id = sample.sample

        sample_prev, _ = dataset.get_prev_sample(dbsession, sample_idx, session_user)
        sample_next, _ = dataset.get_next_sample(dbsession, sample_idx, session_user)

        curanno_data = dataset.getanno(dbsession, session_user, sample_id)
        curanno = None
        if curanno_data and 'data' in curanno_data and \
                'value' in curanno_data['data']:
            curanno = curanno_data['data']['value']

        anno_votes = get_votes(dbsession, dataset, user_roles, session_user, sample_id)

        return render_template("annotate.html", dataset=dataset,
                               task=task,
                               sample_id=sample_id,
                               sample_idx=sample_idx,
                               sample_content=sample_content,
                               random_sample=random_sample,
                               sample_prev=sample_prev,
                               sample_next=sample_next,
                               curanno=curanno,
                               votes=anno_votes)

def dataset_lookup_or_create(dbsession, dsid, editmode):
    if dsid is None:
        dataset = db.Dataset()
    else:
        dataset = db.dataset_by_id(dbsession, dsid, user_id=session['user'])
        if not dataset is None:
            editmode = 'edit'
        else:
            dataset = db.Dataset()

    if dataset.dsmetadata is None:
        dataset.dsmetadata = {}

    return dataset, editmode


TAGORDER_ACTIONS = ["update_taglist", "rename_tag", "delete_tag", "move_tag_down", "move_tag_up"]


def handle_tag_update(dbsession, request, dataset):
    update_action = request.json.get("tagaction", "")

    if update_action in TAGORDER_ACTIONS:
        new_tags = request.json.get("newtags", [])

        original_tagmetadata = dataset.get_taglist(include_metadata=True)
        dataset.set_taglist(new_tags)

        if update_action == "rename_tag":
            old_name = list(set(original_tagmetadata.keys()) - set(new_tags))
            new_name = list(set(new_tags) - set(original_tagmetadata.keys()))
            if old_name and new_name and len(old_name) and len(new_name):
                old_name = old_name[0]
                new_name = new_name[0]
            else:
                old_name = None
                new_name = None
            if old_name and new_name and old_name in original_tagmetadata:
                if not original_tagmetadata[old_name] is None:
                    dataset.update_tag_metadata(new_name, original_tagmetadata[old_name])
                db.fprint("RENAME_TAG", old_name, "=>", new_name, original_tagmetadata[old_name])
                migrated_annotations = dataset.migrate_annotations(dbsession, old_name, new_name)
                db.fprint("RENAME_TAG", migrated_annotations, "migrated from %s to %s" % (old_name, new_name))
    else:
        update_tag = request.json.get("tag", None)
        update_value = request.json.get("value", None)
        if not update_value is None and update_value == "-":
            update_value = None

        if not update_tag is None:
            if update_action == "change_tag_color":
                dataset.update_tag_metadata(update_tag, {"color": update_value})
            elif update_action == "change_tag_icon":
                dataset.update_tag_metadata(update_tag, {"icon": update_value})


@app.route(BASEURI + "/dataset/<dsid>/overview.json", methods=["GET"])
def dataset_overview_json(dsid):
    dataset = None

    with db.session_scope() as dbsession:
        session_user = db.by_id(dbsession, session['user'])
        dataset = get_accessible_dataset(dbsession, dsid)
        user_roles = list(dataset.get_roles(dbsession, session_user))

        tags = dataset.get_taglist()
        tag_metadata = dataset.get_taglist(include_metadata=True)
        ds_total = dataset.get_size()

        annotations_by_user, all_annotations = dataset.annotation_counts(dbsession)

        agreement_fleiss = dataset.annotation_agreement(dbsession)

        dsoverview = {
                "dataset": dataset.dataset_id,
                "user_roles": user_roles,
                "annotations": annotations_by_user,
                "all_annotations": all_annotations,
                "total": ds_total,
                "tags": tags,
                "tag_metadata": tag_metadata,
                "fleiss": agreement_fleiss,
                }

        return dsoverview

@app.route(BASEURI + "/dataset/<dsid>/edit", methods=['GET', 'POST'])
@app.route(BASEURI + "/dataset/create", methods=['GET', 'POST'])
@login_required
def new_dataset(dsid=None):
    dataset = None
    editmode = 'create'

    with db.session_scope() as dbsession:

        preview_df = None
        import_alerts = None

        dataset = None
        try:
            dataset, editmode = dataset_lookup_or_create(dbsession, dsid, editmode)
        except Exception as _:
            flash("Dataset not found or access denied", "error")
            return abort(404, description="Dataset not found or access denied")

        userobj = db.by_id(dbsession, session['user'])
        if dataset.owner is None:
            dataset.owner = userobj

        dbsession.add(dataset)

        if not dataset.owner is userobj:
            raise Exception("You cannot modify datasets you do not own.")

        if dataset.dataset_id is None:
            dataset.dirty(dbsession)
            dbsession.commit()

            dbsession.flush()

        if request.method == 'POST':

            if request.json is not None and request.json.get("action", "") == "tageditor":

                editmode = "tageditor"
                handle_tag_update(dbsession, request, dataset)
                # data: JSON.stringify({"action": "tageditor", "action": tag_action, "tag": current_tag, "value": tag_value}),


            formaction = request.form.get("action", None)
            # print("--- " * 5)
            # print("action", formaction)
            # print("form", request.form)
            # print("files", request.files)
            # print("--- " * 5)

            if not formaction is None and formaction == 'change_name':
                dsname = request.form.get('dataset_name', None)
                if not dsname is None:
                    dsname = dsname.strip()
                    if dsname != '':
                        dataset.dsmetadata['name'] = dsname

            if not formaction is None and formaction == 'change_description':
                ds_description = request.form.get('setdescription', None)
                if not ds_description is None:
                    ds_description = ds_description.strip()
                    dataset.dsmetadata['description'] = ds_description

            if not formaction is None and formaction == 'delete_dataset' and \
                    request.form.get("confirmation", "") == "delete_dataset_confirmed" and \
                    not dataset is None and not dataset.dataset_id is None:
                db.fprint("User %s triggers delete on dataset %s" % (userobj, dataset))
                dbsession.delete(dataset)

                dbsession.commit()
                dbsession.flush()
                flash("Dataset was deleted successfully.", "success")
                return redirect(url_for("show_datasets"))

            if not formaction is None:
                if formaction == "change_delimiter":
                    newdelim = dataset.dsmetadata.get("sep", ",")
                    if request.form.get("comma", "") != "":
                        newdelim = ","
                    elif request.form.get("tab", "") != "":
                        newdelim = "\t"
                    elif request.form.get("semicolon", "") != "":
                        newdelim = ";"
                    dataset.dsmetadata["sep"] = newdelim
                    dataset.invalidate()

                if formaction == "change_quotechar":
                    # {% set ds_quotechar = dataset.dsmetadata.quotechar or '"' %}
                    newquot = dataset.dsmetadata.get("quotechar", '"')
                    if request.form.get("double-quote", "") != "":
                        newquot = "\""
                    elif request.form.get("single-quote", "") != "":
                        newquot = "'"
                    dataset.dsmetadata["quotechar"] = newquot
                    dataset.invalidate()

                if formaction == 'change_textcol' and not request.form.get("textcol", None) is None:
                    dataset.dsmetadata['textcol'] = request.form.get("textcol", None)

                if formaction == 'change_idcolumn' and not request.form.get("idcolumn", None) is None:
                    dataset.dsmetadata['idcolumn'] = request.form.get("idcolumn", None)

                if formaction == 'change_annoorder' and not request.form.get("annoorder", None) is None:
                    dataset.dsmetadata['annoorder'] = request.form.get("annoorder", None)

                if formaction == 'add_role' and \
                        not request.form.get("annouser", None) is None and \
                        not request.form.get("annorole", None) is None:
                    annouser = request.form.get("annouser", None)
                    annorole = request.form.get("annorole", None)
                    if annorole in db.VALID_ROLES:
                        dataset.set_role(dbsession, annouser, annorole)

                if formaction == 'rem_role' and \
                        not request.form.get("annouser", None) is None and \
                        not request.form.get("annorole", None) is None:
                    annouser = request.form.get("annouser", None)
                    annorole = request.form.get("annorole", None)
                    if annorole in dataset.get_roles(dbsession, annouser):
                        dataset.set_role(dbsession, annouser, None)
                    else:
                        db.fprint("failed to remove role %s from user %s: not in active roles" % (annorole, annouser))

                if formaction == 'change_taglist' and not request.form.get("settaglist", None) is None:
                    newtags = request.form.get("settaglist", None).split("\n")
                    dataset.set_taglist(newtags)

                # move uploaded file content to temporary file and store details in the dataset metadata
                if formaction == 'upload_file':
                    if not request.files is None and 'upload_file' in request.files:
                        fileobj = request.files['upload_file']
                        if fileobj and fileobj.filename:
                            dataset.dsmetadata['upload_filename'] = secure_filename(fileobj.filename)
                            dataset.dsmetadata['upload_mimetype'] = fileobj.mimetype
                            dataset.dsmetadata['upload_timestamp'] = datetime.now().timestamp()
                            dataset.dsmetadata['hasdata'] = True

                            tmp_handle, tmp_filename = tempfile.mkstemp(".csv")
                            with os.fdopen(tmp_handle, 'wb') as tmpfile:
                                fileobj.save(tmpfile)
                            dataset.dsmetadata["upload_tempfile"] = tmp_filename


            dataset.update_size()
            dataset.dirty(dbsession)
            dbsession.commit()

            dbsession.flush()

        # if uploaded content exists that has not been imported, load the content
        new_content = None
        can_import = False
        if dataset.dsmetadata.get("upload_tempfile") is not None and \
            request.method == "POST" and request.form is not None and \
            request.form.get("action", "") == "do_discard_import":

            tmp_filename = dataset.dsmetadata.get("upload_tempfile")
            # remove temporary file after successful import
            if os.path.exists(tmp_filename):
                db.fprint("[info] removing import file for dataset %s: %s" % (dataset, tmp_filename))
                os.unlink(tmp_filename)
                del dataset.dsmetadata["upload_tempfile"]

        has_upload_content = False
        if dataset.dsmetadata.get("upload_tempfile") is not None:

            tmp_filename = dataset.dsmetadata.get("upload_tempfile")
            if not os.path.exists(tmp_filename):
                del dataset.dsmetadata["upload_tempfile"]
            else:
                db.fprint("[info] import dry run, dataset: %s, tempfile: %s" % (dataset, tmp_filename))
                has_upload_content = True

                import_dry_run = True
                if request.method == "POST" and request.form is not None and \
                        request.form.get("action", "") == "do_import":
                    import_dry_run = False

                import_success, import_errors, preview_df = dataset.import_content(dbsession, tmp_filename, dry_run=import_dry_run)
                db.fprint("[info] import dry run status, dataset: %s, tempfile: %s, success: %s" % \
                        (dataset, tmp_filename, import_success))

                if os.path.exists(tmp_filename) and not import_dry_run:
                    db.fprint("[info] removing import file for dataset %s after import: %s" % (dataset, tmp_filename))
                    os.unlink(tmp_filename)
                    del dataset.dsmetadata["upload_tempfile"]

                can_import = import_success and import_dry_run
                if not import_success:
                    db.fprint("[error] import for dataset %s failed: %s" % (dataset, ", ".join(import_errors)))
                if not import_dry_run:
                    preview_df = None

                # forward import errors to the frontend
                if import_errors is not None and import_alerts is None:
                    import_alerts = import_errors

            dataset.update_size()
            dataset.dirty(dbsession)
            dbsession.commit()

            dbsession.flush()

        if preview_df is None and dataset and dataset.has_content():
            preview_df = dataset.page(dbsession, page_size=10, extended=True)

        ds_errors = None
        if not dataset is None:
            ds_errors = dataset.check_dataset()

        if editmode == 'create' and not dataset.dataset_id is None:
            # redirect to edit URI once dataset has been persisted
            return redirect(url_for('new_dataset', dsid=dataset.dataset_id))

        if editmode == "tageditor":
            return render_template('tag_editor.html', dataset=dataset, editmode=editmode, previewdf_alerts=import_alerts, previewdf=preview_df, db=db, ds_errors=ds_errors, dbsession=dbsession, can_import=can_import, has_upload_content=has_upload_content)

        return render_template('dataset_new.html', dataset=dataset, editmode=editmode, previewdf_alerts=import_alerts, previewdf=preview_df, db=db, ds_errors=ds_errors, dbsession=dbsession, can_import=can_import, has_upload_content=has_upload_content)

@app.route(BASEURI + '/settings', methods=['GET', 'POST'])
@login_required
def settings():
    with db.session_scope() as dbsession:
        userobj = db.by_id(dbsession, session['user'])
        if request.method == 'POST':
            act = request.form.get("action", None)

            if act == 'change_displayname':
                userobj.displayname = request.form.get("new_displayname", userobj.displayname) or ""
                dbsession.add(userobj)
                session['user_displayname'] = userobj.get_name()
                flash("Your display name was changed successfully.", "success")

            if act == 'change_password':
                req_pwc = request.form.get("curpassword", None)
                req_pw1 = request.form.get("newpw1", None)
                req_pw2 = request.form.get("newpw2", None)

                try:
                    userobj.change_password(dbsession, req_pwc, req_pw1, req_pw2)
                    flash("Password successfully changed.", "success")
                except Exception as e:
                    acterror = "%s %s %s" % (e, userobj, session['user'])
                    db.fprint(acterror)
                    flash('%s' % e, "error")

        return render_template('settings.html', session_user=userobj)

@app.route(BASEURI + '/login', methods=['GET', 'POST'])
def login(backto=None):
    if backto is None:
        backto = request.args.get("backto", None)
    loginerror = None

    if request.method == 'POST':
        req_user = request.form.get("username", None)
        req_pw = request.form.get("password", None)

        loginerror = 'Invalid credentials'
        if not req_user is None and not req_pw is None:
            with db.session_scope() as dbsession:
                req_user_obj = db.by_email(dbsession, req_user, doraise=False)
                if not req_user_obj is None:
                    if req_user_obj.verify_password(req_pw):
                        flash('You were successfully logged in.', "success")
                        session['user'] = req_user_obj.uid
                        session['user_email'] = req_user_obj.email
                        session['user_displayname'] = req_user_obj.get_name()
                        loginerror = None

                        return redirect(url_for('index'))
        else:
            return redirect(url_for('index'))
    if not loginerror is None:
        flash("%s" % loginerror, "error")

    return render_template('login.html')
