"""
Dataset related routes.
"""
import json
import os
import os.path
import tempfile
from datetime import datetime
import string
from io import StringIO
import math
from collections import namedtuple

from werkzeug.utils import secure_filename
from flask import flash, redirect, render_template, request, url_for, session, Response, abort

from app.lib.viewhelpers import login_required, get_session_user
import app.lib.config as config
from app.web import app, BASEURI, db

TAGORDER_ACTIONS = ["update_taglist", "rename_tag", "delete_tag", "move_tag_down", "move_tag_up"]


def reorder_dataframe(df, cur_dataset, annotation_columns):
    columns = list(df.columns.intersection([
                    "sample_index",
                    cur_dataset.get_id_column(),
                    cur_dataset.get_text_column()])) + list(df.columns.intersection(annotation_columns))

    # drop other columns
    df = df.reset_index()
    df = df[columns]
    # reorder
    df = df[columns]
    return df


def request_arg(key, valid_values, default_value=None):
    value = default_value
    req_value = request.args.get(key, None)

    if req_value is not None and req_value.lower() in valid_values:
        value = req_value.lower()
    return value


def get_tagstates(cur_dataset):
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
    return tagstates, restrict_include, restrict_exclude


def get_pagination_elements(pagination, results, pagination_size=5):
    pagination.pages = math.ceil(results / pagination.page_size)
    if pagination.page > pagination.pages:
        pagination.page = pagination.pages

    pagination_elements = list(range(max(1, pagination.page - pagination_size),
                                     min(pagination.page + pagination_size + 1, pagination.pages + 1)))
    pagination_elements.sort()
    return pagination_elements

def inspect_update_sample(req_sample, cur_dataset, ctx_args, df):
    if req_sample is None or req_sample == "":
        return False
    id_column = cur_dataset.get_id_column()

    ctx_args['hide_nan'] = True
    ctx_args['id_column'] = id_column
    ctx_args['text_column'] = cur_dataset.get_text_column()

    for _, row in df.iterrows():
        if str(row["sample_index"]) != str(req_sample):
            continue
        ctx_args['index'] = str(row["sample_index"])
        ctx_args['row'] = row
    return True

def inspect_get_requested_sample():
    req_sample = request.args.get("single_row", "")
    if request.method == "POST":
        request.get_json(force=True)
    if request.json is not None:
        req_sample = request.json.get("single_row", "")
    return req_sample


@app.route(BASEURI + "/dataset/<dsid>/inspect", methods=["GET", "POST"])
@login_required
def inspect_dataset(dsid=None):
    with db.session_scope() as dbsession:

        restrict_view = request_arg("restrict_view", ["tagged", "untagged"], None)
        query = request.args.get("query", "").strip()

        cur_dataset = db.get_accessible_dataset(dbsession, dsid)
        session_user = db.User.by_id(dbsession, session['user'])

        tagstates, restrict_include, restrict_exclude = get_tagstates(cur_dataset)

        template_name = "dataset_inspect.html"
        ctx_args = {}

        req_sample = inspect_get_requested_sample()
        if req_sample is not None and not req_sample == "":
            if request.json is not None and "set_tag" in request.json:
                cur_dataset.setanno(dbsession, session_user, req_sample, request.json.get("set_tag", None))

        # pagination
        pagination = namedtuple("Pagination", ["page_size", "page", "pages"])
        pagination.page_size = 50
        pagination.page = 1
        pagination.pages = 1
        try:
            pagination.page_size = int(config.get("inspect_page_size", "50"))
        except ValueError as e:
            flash("Invalid config value for 'inspect_page_size': %s" % e, "error")

        try:
            pagination.page = int(request.args.get("page", "1"))
        except ValueError as e:
            flash("Invalid value for param 'page': %s" % e, "error")

        df, annotation_columns, results = cur_dataset.annotations(dbsession,
                                                                  foruser=session_user,
                                                                  page=pagination.page,
                                                                  page_size=pagination.page_size,
                                                                  user_column="annotations",
                                                                  query=query,
                                                                  tags_include=restrict_include,
                                                                  tags_exclude=restrict_exclude,
                                                                  restrict_view=restrict_view)

        df = reorder_dataframe(df, cur_dataset, annotation_columns)

        pagination_elements = get_pagination_elements(pagination, results, pagination_size=5)

        if inspect_update_sample(req_sample, cur_dataset, ctx_args, df):
            template_name = "dataset_inspect_row.html"

        return render_template(template_name, dataset=cur_dataset,
                               df=df,
                               restrict_view=restrict_view,
                               query=query,
                               page_size=pagination.page_size,
                               page=pagination.page,
                               pages=pagination.pages,
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
        cur_dataset = db.get_accessible_dataset(dbsession, dsid)

        df, _, _ = cur_dataset.annotations(dbsession, foruser=session['user'], page_size=-1)

        s = StringIO()
        df.to_csv(s)
        csvc = s.getvalue()

        download_filename = "dataset.csv"

        def is_valid_char(c):
            return c in string.ascii_letters or c in string.digits or c in "-_. "

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

        userobj = db.User.by_id(dbsession, session['user'])

        my_datasets = db.my_datasets(dbsession, session['user'])
        access_datasets = db.accessible_datasets(dbsession, session['user'])

        dataset = None
        if dsid is not None and dsid in my_datasets:
            dataset = my_datasets[dsid]
        if dsid is not None and dsid in access_datasets:
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

        return render_template('dataset.html', my_datasets=my_datasets,
                               access_datasets=access_datasets,
                               dataset=dataset,
                               ds_errors=ds_errors,
                               dbsession=dbsession,
                               userobj=userobj)


def dataset_lookup_or_create(dbsession, dsid, editmode):
    if dsid is None:
        dataset = db.Dataset()
    else:
        dataset = db.dataset_by_id(dbsession, dsid, user_id=session['user'])
        if dataset is not None:
            editmode = 'edit'
        else:
            dataset = db.Dataset()

    if dataset.dsmetadata is None:
        dataset.dsmetadata = {}

    return dataset, editmode


def handle_option_update(dbsession, session_user, dataset):

    set_key = request.json.get("option_key", "")
    set_value = request.json.get("option_value", None)

    if set_key == "" or set_key not in dataset.valid_option_keys:
        raise Exception("did not recognize option key in JSON data")

    if set_key == "hide_votes":
        set_value = bool(set_value)

    dataset.dsmetadata[set_key] = set_value
    dataset.dirty(dbsession)
    dbsession.commit()
    dbsession.flush()

    db.Activity.create(dbsession, session_user, dataset, "update_option", "%s => %s" % (set_key, set_value))

    return {"action": "update_option",
            "set_key": set_key}


def handle_tag_update(dbsession, session_user, dataset):
    update_action = request.json.get("tagaction", "")

    if update_action in TAGORDER_ACTIONS:
        new_tags = request.json.get("newtags", [])

        original_tagmetadata = dataset.get_taglist(include_metadata=True)
        dataset.set_taglist(new_tags)

        if update_action == "rename_tag":
            old_name = list(set(original_tagmetadata.keys()) - set(new_tags))
            new_name = list(set(new_tags) - set(original_tagmetadata.keys()))
            if old_name and new_name and len(old_name) > 0 and len(new_name) > 0:
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

                db.Activity.create(dbsession,
                                   session_user,
                                   dataset,
                                   "rename_tag",
                                   "%s => %s" % (old_name, new_name))
    else:
        update_tag = request.json.get("tag", None)
        update_value = request.json.get("value", None)
        if update_value is not None and update_value == "-":
            update_value = None

        if update_tag is not None:
            if update_action == "change_tag_color":
                dataset.update_tag_metadata(update_tag, {"color": update_value})
            elif update_action == "change_tag_icon":
                dataset.update_tag_metadata(update_tag, {"icon": update_value})


@app.route(BASEURI + "/dataset/<dsid>/overview.json", methods=["GET"])
def dataset_overview_json(dsid):
    dataset = None

    with db.session_scope() as dbsession:
        session_user = db.User.by_id(dbsession, session['user'])
        dataset = db.get_accessible_dataset(dbsession, dsid)
        user_roles = list(dataset.get_roles(dbsession, session_user))

        tags = dataset.get_taglist()
        tag_metadata = dataset.get_taglist(include_metadata=True)
        ds_total = dataset.get_size()

        annotations_by_user, all_annotations = dataset.annotation_counts(dbsession)

        agreement_fleiss = dataset.annotation_agreement(dbsession, by_tag=False)

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

        userobj = db.User.by_id(dbsession, session['user'])
        if dataset.owner is None:
            dataset.owner = userobj

        dbsession.add(dataset)

        if dataset.owner is not userobj:
            raise Exception("You cannot modify datasets you do not own.")

        if dataset.dataset_id is None:
            dataset.dirty(dbsession)
            dbsession.commit()

            dbsession.flush()

        if request.method == 'POST':

            if request.json is not None and request.json.get("action", "") == "tageditor":
                editmode = "tageditor"
                handle_tag_update(dbsession, userobj, dataset)

            if request.json is not None and request.json.get("action", "") == "update_option":
                editmode = "update_option"
                return handle_option_update(dbsession, userobj, dataset)

            formaction = request.form.get("action", None)

            if formaction is not None and formaction == 'change_name':
                dsname = request.form.get('dataset_name', None)
                if dsname is not None:
                    dsname = dsname.strip()
                    if dsname != '':
                        dataset.dsmetadata['name'] = dsname

            if formaction is not None and formaction == 'change_description':
                ds_description = request.form.get('setdescription', None)
                if ds_description is not None:
                    ds_description = ds_description.strip()
                    dataset.dsmetadata['description'] = ds_description

            if formaction is not None and formaction == 'delete_dataset' and \
                    request.form.get("confirmation", "") == "delete_dataset_confirmed" and \
                    dataset is not None and dataset.dataset_id is not None:
                db.fprint("User %s triggers delete on dataset %s" % (userobj, dataset))
                db.Activity.create(dbsession, userobj, dataset, "event", "deleted")
                dbsession.delete(dataset)

                dbsession.commit()
                dbsession.flush()
                flash("Dataset was deleted successfully.", "success")
                return redirect(url_for("show_datasets"))

            if formaction is not None:
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
                    dataset.set_role(dbsession, annouser, annorole)

                    return {"action": formaction, "new_roles": list(dataset.get_roles(dbsession, annouser))}

                if formaction == 'rem_role' and \
                        not request.form.get("annouser", None) is None and \
                        not request.form.get("annorole", None) is None:
                    annouser = request.form.get("annouser", None)
                    annorole = request.form.get("annorole", None)
                    if annorole in dataset.get_roles(dbsession, annouser):
                        dataset.set_role(dbsession, annouser, annorole, remove=True)
                    return {"action": formaction, "new_roles": list(dataset.get_roles(dbsession, annouser))}

                if formaction == 'change_taglist' and not request.form.get("settaglist", None) is None:
                    newtags = request.form.get("settaglist", None).split("\n")
                    dataset.set_taglist(newtags)

                # move uploaded file content to temporary file and store details in the dataset metadata
                if formaction == 'upload_file':
                    if request.files is not None and 'upload_file' in request.files:
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
                            db.Activity.create(dbsession, userobj, dataset, "uploaded_file",
                                               "%s, %s" % (secure_filename(fileobj.filename), fileobj.mimetype))

            dataset.update_size()
            dataset.dirty(dbsession)
            dbsession.commit()

            dbsession.flush()

        # if uploaded content exists that has not been imported, load the content
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

                import_success, import_errors, preview_df = dataset.import_content(dbsession, userobj, tmp_filename,
                                                                                   dry_run=import_dry_run)
                db.fprint("[info] import dry run status, dataset: %s, tempfile: %s, success: %s" %
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
        if dataset is not None:
            ds_errors = dataset.check_dataset()

        if editmode == 'create' and dataset.dataset_id is not None:
            # redirect to edit URI once dataset has been persisted
            return redirect(url_for('new_dataset', dsid=dataset.dataset_id))

        userroles = dataset.get_roles(dbsession, userobj)

        template = "dataset_new.html"

        if editmode == "tageditor":
            template = "tag_editor.html"

        return render_template(template,
                               dataset=dataset,
                               editmode=editmode,
                               previewdf_alerts=import_alerts,
                               previewdf=preview_df,
                               db=db,
                               ds_errors=ds_errors,
                               dbsession=dbsession,
                               can_import=can_import,
                               has_upload_content=has_upload_content,
                               userroles=userroles)
