"""
Route definitions and business logic.
"""
from datetime import datetime
import tempfile
import re
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
    if not query is None and query.strip() != "":
        query = r"(" + re.escape(query.strip()) + ")"
        value = re.sub(query, r'<span class="ds_highlight">\1</span>', value, \
                flags=re.IGNORECASE)
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

        return render_template('index.html', my_datasets=my_datasets, \
                                    access_datasets=access_datasets, \
                                    ds_errors=ds_errors, \
                                    dbsession=dbsession, \
                                    session_user=session_user, \
                                    tasks=annotation_tasks)

@app.before_request
def before_handler():
    req_count = session.get("request_counter", None)
    if not req_count:
        req_count = 0
    req_count += 1
    session['request_counter'] = req_count
    #print("REQCOUNT", session.get("user", None), req_count)

@app.route(BASEURI + "/logout")
@login_required
def logout():
    _ = [session.pop(key) for key in list(session.keys())]
    session.clear()

    return redirect(url_for('index'))

def get_accessible_dataset(dbsession, dsid):
    my_datasets = db.my_datasets(dbsession, session['user'])
    access_datasets = db.accessible_datasets(dbsession, session['user'])

    cur_dataset = None
    if not dsid is None and dsid in my_datasets:
        cur_dataset = my_datasets[dsid]
    if not dsid is None and dsid in access_datasets:
        cur_dataset = access_datasets[dsid]
    return cur_dataset

def reorder_dataframe(df, cur_dataset, annotation_columns):
    columns = [cur_dataset.get_id_column(), cur_dataset.get_text_column()] + \
                list(df.columns.intersection(annotation_columns))

    # drop other columns
    df = df.reset_index()
    df = df.loc[:, columns]
    df.set_index(cur_dataset.get_id_column())
    # reorder
    df = df[columns]
    return df

def query_dataframe(df, textcol, query):
    # text query filter
    if not query is None and query != '':
        df[textcol] = df[textcol].astype(str)
        df = df[df[textcol].str.contains(query, na=False, regex=False, case=False)]
    return df

@app.route(BASEURI + "/dataset/<dsid>/inspect")
@login_required
def inspect_dataset(dsid=None):
    with db.session_scope() as dbsession:

        hideempty = True
        if not request.args.get("hideempty", None) is None and \
                request.args.get("hideempty", None).lower() == "false":
            hideempty = False

        query = request.args.get("query", "").strip()

        cur_dataset = get_accessible_dataset(dbsession, dsid)

        session_user = db.by_id(dbsession, session['user'])
        df, annotation_columns = cur_dataset.annotations(dbsession, \
                                                foruser=session_user, \
                                                user_column="annotations", \
                                                hideempty=hideempty)

        df = reorder_dataframe(df, cur_dataset, annotation_columns)

        df = query_dataframe(df, textcol=cur_dataset.get_text_column(), query=query)

        # pagination
        results = df.shape[0]
        page_size = 100
        page = 1
        pages = 1
        try:
            page_size = int(config.get("inspect_page_size", "100"))
        except ValueError as e:
            flash("Invalid config value for 'inspect_page_size': %s" % e, "error")

        try:
            page = int(request.args.get("page", "1"))
        except ValueError as e:
            flash("Invalid value for param 'page': %s" % e, "error")

        pages = math.ceil(df.shape[0] / page_size)
        if df.shape[0] > page_size:
            if page > pages:
                page = pages

            onset = max(0, page - 1) * page_size
            offset = onset + page_size

            df = df[onset:offset]

        pagination_size = 5
        pagination_elements = list(range(max(1, page - pagination_size), \
                                         min(page + pagination_size + 1, pages + 1)))
        pagination_elements.sort()

        return render_template("dataset_inspect.html", dataset=cur_dataset,
                                df=df, \
                                hideempty=hideempty, \
                                query=query, \
                                page_size=page_size, \
                                page=page, \
                                pages=pages, \
                                results=results, \
                                pagination_elements=pagination_elements, \
                                user_roles=cur_dataset.get_roles(dbsession, session_user) \
                                )

@app.route(BASEURI + "/dataset/<dsid>/download")
@login_required
def download(dsid=None):

    with db.session_scope() as dbsession:
        cur_dataset = get_accessible_dataset(dbsession, dsid)

        df, _ = cur_dataset.annotations(dbsession, foruser=session['user'])

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
    dataset = None

    with db.session_scope() as dbsession:
        return render_template("createuser.html", dataset=dataset)

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

@app.route(BASEURI + "/dataset/<dsid>/annotate", methods=["GET", "POST"])
@login_required
def annotate(dsid=None, sample_idx=None):
    dataset = None

    with db.session_scope() as dbsession:
        session_user = db.by_id(dbsession, session['user'])
        my_datasets = db.my_datasets(dbsession, session['user'])
        access_datasets = db.accessible_datasets(dbsession, session['user'])

        if not dsid is None and dsid in my_datasets:
            dataset = my_datasets[dsid]
        if not dsid is None and dsid in access_datasets:
            dataset = access_datasets[dsid]

        if dataset is None:
            return abort(404, \
                    description="Forbidden. User does not have access to requested dataset.")

        user_roles = dataset.get_roles(dbsession, session_user)
        if not 'annotator' in user_roles:
            return abort(404, \
                    description="Forbidden. Current user roles %s do not allow annotation." \
                                % user_roles)

        task = {"id": dsid,
                "name": dataset.dsmetadata.get("name", dataset.dataset_id),
                "dataset": dataset,
                "progress": 0,
                "size": dataset.dsmetadata.get("size", -1) or -1,
                "annos": dataset.annocount(dbsession, session['user']),
                "annos_today": dataset.annocount_today(dbsession, session['user'])
                }

        if task['size'] and task['size'] > 0 and task['annos'] and task['annos'] > 0:
            task['progress'] = round(task['annos'] / task['size'] * 100.0)
            task['progress_today'] = round(task['annos_today'] / task['size'] * 100.0)
            task['progress_beforetoday'] = task['progress'] - task['progress_today']

        id_column = dataset.get_id_column()

        #df = dataset.as_df()
        df, annotation_columns = dataset.annotations(dbsession, foruser=session_user, \
                                                    user_column="annotations", \
                                                    hideempty=False, only_user=True)
        columns = [id_column, dataset.get_text_column()] + \
                    list(df.columns.intersection(annotation_columns))

        df = df.reset_index()
        df = df.loc[:, columns]
        df = df[columns]
        df = df.reset_index()

        sample_content = None
        textcol = dataset.dsmetadata.get("textcol", None)

        next_sample_idx = None
        next_sample_id = None

        if sample_idx is None:
            try:
                sample_idx = int(request.args.get("sample_idx", None))
            except ValueError as _:
                pass

            if sample_idx is None:
                if dataset.dsmetadata.get("annoorder", "sequential") == 'random':
                    sample_idx, sample_id = get_random_sample(df, id_column)
                else:
                    no_anno = df[~(df.annotations != '')]
                    # make sure to select a sample that has not been annotated yet (if any are left)
                    if no_anno.empty:
                        no_anno = df

                    first_row = no_anno.iloc[no_anno.index[0]]
                    sample_idx = first_row['index']
                    sample_id = first_row[id_column]

                    next_row = no_anno.iloc[no_anno.index[1]]
                    next_sample_idx = next_row['index']
                    next_sample_id = next_row[id_column]

        set_sample_idx = None
        set_sample_value = None
        try:
            set_sample_idx = str(int(request.args.get("set_sample_idx", None)))
        except ValueError as _:
            pass

        if not set_sample_idx is None:
            set_sample_value = request.args.get("set_value", "")[:500]

        if not set_sample_idx is None and not set_sample_value is None:
            set_sample = df.iloc[int(set_sample_idx)][id_column]
            dataset.setanno(dbsession, session['user'], set_sample, set_sample_value)

        random_sample, _ = get_random_sample(df, id_column)
        sample_content = df[textcol][sample_idx]
        sample_id = df[id_column][sample_idx]

        set_sample = df.iloc[int(sample_idx)][id_column]
        curanno_data = dataset.getanno(dbsession, session['user'], set_sample)
        curanno = None
        if curanno_data and 'data' in curanno_data and \
                'value' in curanno_data['data']:
            curanno = curanno_data['data']['value']

        anno_votes = None
        if 'curator' in user_roles:
            anno_votes = dataset.get_anno_votes(dbsession, sample_id=sample_id, \
                                                exclude_user=session_user)
            for tag in anno_votes.keys():
                anno_votes[tag] = [annouser.get_name() for annouser in anno_votes[tag]]

        return render_template("annotate.html", dataset=dataset, \
                                task=task, \
                                sample_idx=sample_idx, \
                                set_sample=set_sample, \
                                random_sample=random_sample, \
                                sample_content=sample_content, \
                                curanno=curanno, \
                                next_sample_idx=next_sample_idx, \
                                next_sample_id=next_sample_id, \
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

@app.route(BASEURI + "/dataset/<dsid>/edit", methods=['GET', 'POST'])
@app.route(BASEURI + "/dataset/create", methods=['GET', 'POST'])
@login_required
def new_dataset(dsid=None):
    dataset = None
    editmode = 'create'

    with db.session_scope() as dbsession:
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

            formaction = request.form.get("action", None)
            #print("--- " * 5)
            #print("action", formaction)
            #print("form", request.form)
            #print("files", request.files)
            #print("--- " * 5)

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
                return redirect(url_for("dataset"))

            if not formaction is None and formaction == 'change_textcol' and not request.form.get("textcol", None) is None:
                dataset.dsmetadata['textcol'] = request.form.get("textcol", None)

            if not formaction is None and formaction == 'change_idcolumn' and not request.form.get("idcolumn", None) is None:
                dataset.dsmetadata['idcolumn'] = request.form.get("idcolumn", None)

            if not formaction is None and formaction == 'change_annoorder' and not request.form.get("annoorder", None) is None:
                dataset.dsmetadata['annoorder'] = request.form.get("annoorder", None)

            if not formaction is None and formaction == 'add_role' and \
                    not request.form.get("annouser", None) is None and \
                    not request.form.get("annorole", None) is None:
                annouser = request.form.get("annouser", None)
                annorole = request.form.get("annorole", None)
                if annorole in db.VALID_ROLES:
                    dataset.set_role(dbsession, annouser, annorole)

            if not formaction is None and formaction == 'rem_role' and \
                    not request.form.get("annouser", None) is None and \
                    not request.form.get("annorole", None) is None:
                annouser = request.form.get("annouser", None)
                annorole = request.form.get("annorole", None)
                if annorole in dataset.get_roles(dbsession, annouser):
                    dataset.set_role(dbsession, annouser, None)
                else:
                    db.fprint("failed to remove role %s from user %s: not in active roles" % (annorole, annouser))

            if not formaction is None and formaction == 'change_taglist' and not request.form.get("settaglist", None) is None:
                newtags = request.form.get("settaglist", None).split("\n")
                newtags = filter(lambda l: not l is None and l.strip() != '', newtags)
                newtags = map(lambda l: l.strip(), newtags)
                newtags = list(newtags)
                dataset.dsmetadata['taglist'] = newtags

            new_content = None
            if not formaction is None and formaction == 'upload_file':
                if not request.files is None and 'upload_file' in request.files:
                    fileobj = request.files['upload_file']
                    if fileobj and fileobj.filename:
                        dataset.dsmetadata['upload_filename'] = secure_filename(fileobj.filename)
                        dataset.dsmetadata['upload_mimetype'] = fileobj.mimetype
                        dataset.dsmetadata['upload_timestamp'] = datetime.now().timestamp()
                        dataset.dsmetadata['hasdata'] = True

                        with tempfile.TemporaryFile(mode='w+b') as tmpfile:
                            fileobj.save(tmpfile)
                            tmpfile.seek(0)
                            new_content = tmpfile.read()
                            if not new_content is None and not len(new_content) == 0:
                                new_content = new_content.decode('utf-8')

            if not new_content is None:
                dataset.content = new_content
                dataset.update_size()

            dataset.dirty(dbsession)
            dbsession.commit()

            dbsession.flush()

        df = None

        if dataset and dataset.content:
            df = dataset.as_df(strerrors=True)

        ds_errors = None
        if not dataset is None:
            ds_errors = dataset.check_dataset()

        if editmode == 'create' and not dataset.dataset_id is None:
            # redirect to edit URI once dataset has been persisted
            return redirect(url_for('new_dataset', dsid=dataset.dataset_id))

        return render_template('dataset_new.html', dataset=dataset, editmode=editmode, previewdf=df, db=db, ds_errors=ds_errors, dbsession=dbsession)

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
