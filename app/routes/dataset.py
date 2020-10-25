"""
Dataset related routes.
"""
import os
import os.path
import tempfile
from datetime import datetime
import string
from io import StringIO

from werkzeug.utils import secure_filename
from flask import flash, redirect, render_template, request, url_for, session, Response, abort
import numpy as np

from app.lib.viewhelpers import login_required, get_session_user
from app.web import app, BASEURI, db
from app.lib.models.comments import Comments
from app.lib.models import datasets


TAGORDER_ACTIONS = ["update_taglist", "rename_tag", "delete_tag", "move_tag_down", "move_tag_up"]


@app.route(BASEURI + "/dataset/<dsid>/download")
@login_required
def download(dsid=None):
    with db.session_scope() as dbsession:
        cur_dataset = datasets.get_accessible_dataset(dbsession, dsid)

        df, _, _ = cur_dataset.annotations(dbsession, foruser=db.User.system_user(dbsession), page_size=-1)

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

        userobj = get_session_user(dbsession)

        my_datasets = db.datasets.my_datasets(dbsession, session['user'])
        access_datasets = db.datasets.accessible_datasets(dbsession, session['user'])

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
        dataset = db.Dataset.by_id(dbsession, dsid, user_id=session['user'])
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

    if set_key == "show_votes":
        set_value = bool(set_value)

    dataset.dsmetadata[set_key] = set_value
    dataset.dirty(dbsession)
    dbsession.commit()
    dbsession.flush()

    db.Activity.create(dbsession, session_user, dataset, "update_option", "%s => %s" % (set_key, set_value))

    return {"action": "update_option",
            "set_key": set_key}


def handle_split_update(dbsession, session_user, dataset):
    splitoptions = request.json.get("options", {})
    targetsplit = splitoptions.get("target", "") or ""
    if targetsplit == "":
        targetsplit = None

    splitaction = splitoptions.get("splitaction", "")
    if splitaction == "rename":
        target_new = splitoptions.get("target_new", "") or ""
        dataset.rename_split(dbsession, session_user, targetsplit, target_new)
    elif splitaction == "merge":
        target_new = splitoptions.get("mergeinto", "") or None
        dataset.rename_split(dbsession, session_user, targetsplit, target_new)
    elif splitaction == "fork":
        dataset.split_dataset(dbsession, session_user, targetsplit, splitoptions)
    elif splitaction == "add_annotator":
        target_user = db.User.by_id(dbsession, splitoptions.get("targetuser", None))
        if target_user is None:
            raise Exception("no target user found for '%s'" % splitoptions.get("targetuser", None))

        if dataset.split_annotator_add(dbsession, targetsplit, target_user):
            db.Activity.create(dbsession,
                               session_user,
                               dataset,
                               "split_add_annotator",
                               "%s => %s" % (targetsplit, target_user.get_name()))
    elif splitaction == "rem_annotator":
        target_user = db.User.by_id(dbsession, splitoptions.get("targetuser", None))
        if target_user is None:
            raise Exception("no target user found for '%s'" % splitoptions.get("targetuser", None))

        if dataset.split_annotator_remove(dbsession, targetsplit, target_user):
            db.Activity.create(dbsession,
                               session_user,
                               dataset,
                               "split_remove_annotator",
                               "%s => %s" % (targetsplit, target_user.get_name()))
    else:
        raise Exception("no implementation found for split action %s" % splitaction)


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


@app.route(BASEURI + "/dataset/<dsid>/field/<fieldid>.json", methods=["GET"])
def dataset_field_overview(dsid, fieldid):
    with db.session_scope() as dbsession:
        field_overview = {}

        dataset = datasets.get_accessible_dataset(dbsession, dsid)
        dataset_overview = dataset.get_overview_statistics(dbsession)['columns']
        for _, column_info in dataset_overview.items():
            column_type = column_info.get("dtype", None)
            if isinstance(column_type, np.dtype):
                column_info['dtype'] = str(column_type)

        field_overview['fields'] = list(dataset_overview.keys())
        if fieldid not in dataset_overview.keys():
            return field_overview

        for k, v in dataset_overview[fieldid].items():
            field_overview[k] = v

        if field_overview['numeric']:
            field_overview['min'], field_overview['max'] = dataset.get_field_minmax(dbsession, fieldid)

        return field_overview


@app.route(BASEURI + "/dataset/<dsid>/overview.json", methods=["GET"])
def dataset_overview_json(dsid):
    dataset = None

    with db.session_scope() as dbsession:
        session_user = get_session_user(dbsession)
        dataset = datasets.get_accessible_dataset(dbsession, dsid)
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


def editdataset_post_actions(editmode, dbsession, userobj, dataset):
    if request.json is not None and request.json.get("action", "") == "spliteditor":
        editmode = "spliteditor"
        handle_split_update(dbsession, userobj, dataset)

    if request.json is not None and request.json.get("action", "") == "tageditor":
        editmode = "tageditor"
        handle_tag_update(dbsession, userobj, dataset)

    if request.json is not None and request.json.get("action", "") == "update_option":
        editmode = "update_option"
        return handle_option_update(dbsession, userobj, dataset)

    return editmode


def handle_comment_action(dbsession, userobj, dataset):
    targetaction = None
    if request.json is not None and request.json.get("action", "") in ["add_comment", "delete_comment"]:
        targetaction = request.json.get("action", "")

    if targetaction is not None:
        if targetaction == "add_comment":
            comment_text = request.json.get("text", "")

            target = dataset.activity_target()
            if len(comment_text) > 0:
                Comments.comment(dbsession,
                                 owner=userobj,
                                 target=target,
                                 scope=request.json.get("scope", "comment_note"),
                                 text=comment_text)
        elif targetaction == "delete_comment":
            delete_id = int(request.json.get("comment_id", ""))

            comments = Comments.fortarget(dbsession,
                                          dataset.activity_target(),
                                          userobj)

            for comment in comments:
                if comment.entity.event_id == delete_id and comment.owned:
                    comment.delete(dbsession)

        dbsession.commit()
        dbsession.flush()

        comments = Comments.fortarget(dbsession,
                                      dataset.activity_target(),
                                      userobj)

        return render_template("dataset_comments.html",
                               dataset=dataset,
                               session_user=userobj,
                               comments=comments)
    return None


def editdataset_form_action_metadata(dataset, formaction):
    if formaction == 'change_name':
        dsname = request.form.get('dataset_name', None)
        if dsname is not None and dsname.strip() != '':
            dataset.dsmetadata['name'] = dsname.strip()

    if formaction == 'change_description':
        ds_description = request.form.get('setdescription', None)
        if ds_description is not None:
            dataset.dsmetadata['description'] = ds_description.strip()

    if formaction == "change_delimiter":
        newdelim = dataset.dsmetadata.get("sep", ",")
        valid_separators = {"comma": ",", "tab": "\t", "semicolon": ";"}
        for field, separator in valid_separators.items():
            if request.form.get(field, "") != "":
                newdelim = separator
        dataset.dsmetadata["sep"] = newdelim
        dataset.invalidate()

    if formaction == "change_quotechar":
        newquot = dataset.dsmetadata.get("quotechar", '"')
        if request.form.get("double-quote", "") != "":
            newquot = "\""
        elif request.form.get("single-quote", "") != "":
            newquot = "'"
        dataset.dsmetadata["quotechar"] = newquot
        dataset.invalidate()

    for metadatakey in ["textcol", "idcolumn", "annoorder"]:
        if formaction == "change_%s" % metadatakey and not request.form.get(metadatakey, None) is None:
            dataset.dsmetadata[metadatakey] = request.form.get(metadatakey, None)


def editdataset_form_action_delete(dbsession, dataset, userobj, formaction):
    if formaction == 'delete_dataset' and \
            request.form.get("confirmation", "") == "delete_dataset_confirmed" and \
            dataset is not None and dataset.dataset_id is not None:
        db.fprint("User %s triggers delete on dataset %s" % (userobj, dataset))
        db.Activity.create(dbsession, userobj, dataset, "event", "deleted")
        dbsession.delete(dataset)

        dbsession.commit()
        dbsession.flush()
        flash("Dataset was deleted successfully.", "success")
        return redirect(url_for("show_datasets"))
    return None


def editdataset_form_actions(dbsession, dataset, userobj):
    formaction = request.form.get("action", None)

    if formaction is None:
        return None

    editdataset_form_action_metadata(dataset, formaction)
    delete_result = editdataset_form_action_delete(dbsession, dataset, userobj, formaction)
    if delete_result is not None:
        return delete_result

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

    return None


def dataset_create_handle_upload(dbsession, dataset, userobj):
    has_upload_content = False
    preview_df = None
    import_alerts = None
    can_import = False

    if dataset.dsmetadata.get("upload_tempfile") is None:
        return preview_df, import_alerts, has_upload_content, can_import

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

    return preview_df, import_alerts, has_upload_content, can_import


@app.route(BASEURI + "/dataset/<dsid>/comments", methods=['GET', 'POST'])
@login_required
def dataset_comments(dsid=None):
    with db.session_scope() as dbsession:
        dataset = None
        try:
            session_user = get_session_user(dbsession)
            dataset = db.Dataset.by_id(dbsession, dsid, user_id=session_user.uid)

            comments = Comments.fortarget(dbsession,
                                          dataset.activity_target(),
                                          session_user)

            return render_template("dataset_comments.html",
                                   dataset=dataset,
                                   session_user=session_user,
                                   comments=comments)

            # pylint: disable=bare-except
        except:  # noqa: E722
            flash("Dataset not found or access denied", "error")
            return abort(404, description="Dataset not found or access denied")


@app.route(BASEURI + "/dataset/<dsid>/edit", methods=['GET', 'POST'])
@app.route(BASEURI + "/dataset/create", methods=['GET', 'POST'])
@login_required
def dataset_admin(dsid=None):
    dataset = None
    editmode = 'create'

    with db.session_scope() as dbsession:

        preview_df = None
        import_alerts = None

        dataset = None
        try:
            dataset, editmode = dataset_lookup_or_create(dbsession, dsid, editmode)
            # pylint: disable=bare-except
        except:  # noqa: E722
            flash("Dataset not found or access denied", "error")
            return abort(404, description="Dataset not found or access denied")

        userobj = get_session_user(dbsession)
        if dataset.owner is None:
            dataset.owner = userobj

        dbsession.add(dataset)
        dataset.validate_owner(userobj)
        dataset.ensure_id(dbsession)

        if request.method == 'POST':
            editmode = editdataset_post_actions(editmode, dbsession, userobj, dataset)
            formaction_result = editdataset_form_actions(dbsession, dataset, userobj)

            new_comment_result = handle_comment_action(dbsession, userobj, dataset)
            if new_comment_result is not None:
                return new_comment_result

            if formaction_result is not None \
                    and not isinstance(formaction_result, list) \
                    and not isinstance(formaction_result, str) \
                    and not isinstance(formaction_result, dict):
                return formaction_result

            dataset.update_size()
            dataset.dirty(dbsession)
            dbsession.commit()

            dbsession.flush()
            if formaction_result is not None:
                return formaction_result

        # if uploaded content exists that has not been imported, load the content
        if dataset.dsmetadata.get("upload_tempfile") is not None and \
                request.method == "POST" and request.form is not None and \
                request.form.get("action", "") == "do_discard_import":

            tmp_filename = dataset.dsmetadata.get("upload_tempfile")
            # remove temporary file after successful import
            if os.path.exists(tmp_filename):
                db.fprint("[info] removing import file for dataset %s: %s" % (dataset, tmp_filename))
                os.unlink(tmp_filename)
                del dataset.dsmetadata["upload_tempfile"]

        preview_df, import_alerts, has_upload_content, can_import = dataset_create_handle_upload(dbsession,
                                                                                                 dataset,
                                                                                                 userobj)

        if preview_df is None and dataset and dataset.has_content():
            preview_df = dataset.page(dbsession, page_size=10, extended=True)

        ds_errors = dataset.check_dataset() if dataset is not None else None

        if editmode == 'create' and dataset.dataset_id is not None:
            # redirect to edit URI once dataset has been persisted
            return redirect(url_for('dataset_admin', dsid=dataset.dataset_id))

        template = "dataset_admin.html"

        if editmode == "tageditor":
            template = "tag_editor.html"

        if editmode == "spliteditor":
            template = "split_editor.html"

        comments = None
        if editmode not in ['tageditor', 'spliteditor']:
            comments = Comments.fortarget(dbsession,
                                          dataset.activity_target(),
                                          userobj)

        return render_template(template,
                               dataset=dataset,
                               editmode=editmode,
                               previewdf_alerts=import_alerts,
                               ds_splits=dataset.defined_splits(dbsession),
                               previewdf=preview_df,
                               db=db,
                               ds_errors=ds_errors,
                               dbsession=dbsession,
                               can_import=can_import,
                               has_upload_content=has_upload_content,
                               sample_stats=dataset.get_overview_statistics(dbsession),
                               userroles=dataset.get_roles(dbsession, userobj),
                               comments=comments)
