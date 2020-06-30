import os
import sys
from datetime import datetime
import tempfile
import random

from werkzeug.utils import secure_filename
from flask import Flask, flash, redirect, render_template, request, url_for, session, Response
from functools import wraps
from io import StringIO

import app.lib.config as config
from app.web import app, BASEURI, db

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session or \
                session.get("user", None) is None:
            return redirect(url_for("login", backto=request.url))
        return f(*args, **kwargs)
    return decorated_function


@app.route('/')
@app.route(BASEURI + '/')
def index():
    return render_template("index.html")

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
    [session.pop(key) for key in list(session.keys())]
    session.clear()

    return redirect(url_for('index'))

@app.route(BASEURI + "/dataset/<dsid>/download")
@login_required
def download(dsid = None):

    with db.session_scope() as dbsession:
        my_datasets = db.my_datasets(dbsession, session['user'])
        access_datasets = db.accessible_datasets(dbsession, session['user'])

        dataset = None
        if not dsid is None and dsid in my_datasets:
            dataset = my_datasets[dsid]
        if not dsid is None and dsid in access_datasets:
            dataset = access_datasets[dsid]
        print("a", my_datasets, file=sys.stderr)
        print("b", access_datasets, file=sys.stderr)
        print("search", dsid, type(dsid), file=sys.stderr)
        df = dataset.annotations(dbsession)

        s = StringIO()
        df.to_csv(s)
        csvc = s.getvalue()
        return Response(csvc,
            mimetype="text/csv",
            headers={"Content-disposition":
                     "attachment; filename=dataset.csv"})

@app.route(BASEURI + "/dataset")
@app.route(BASEURI + "/dataset/<dsid>")
@login_required
def dataset(dsid=None):
    err = None

    with db.session_scope() as dbsession:
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

        for dataset in access_datasets.values():
            if ds in ds_errors:
                continue
            ds_errors[ds] = ds.check_dataset()

        return render_template('dataset.html', error=err, my_datasets=my_datasets, access_datasets=access_datasets, dataset=dataset, ds_errors=ds_errors, db = db)

@app.route(BASEURI + "/user/create", methods=["GET", "POST"])
@login_required
def createuser():
    dataset = None

    with db.session_scope() as dbsession:
        return render_template("createuser.html", dataset=dataset)

@app.route(BASEURI + "/dataset/<dsid>/annotate", methods=["GET", "POST"])
@login_required
def annotate(dsid=None, sample_idx=None):
    dataset = None

    with db.session_scope() as dbsession:
        my_datasets = db.my_datasets(dbsession, session['user'])
        access_datasets = db.accessible_datasets(dbsession, session['user'])

        if not dsid is None and dsid in my_datasets:
            dataset = my_datasets[dsid]
        if not dsid is None and dsid in access_datasets:
            dataset = access_datasets[dsid]

        task = {"id": dsid,
                "name": dataset.dsmetadata.get("name", dataset.dataset_id),
                "dataset": dataset,
                "progress": 0,
                "size": dataset.dsmetadata.get("size", -1) or -1,
                "annos": dataset.annocount(dbsession, session['user'])
                }

        if task['size'] and task['size'] > 0 and task['annos'] and task['annos'] > 0:
            task['progress'] = round(task['annos'] / task['size'] * 100.0)

        df = dataset.as_df()
        sample_content = None
        textcol = dataset.dsmetadata.get("textcol", None)

        if sample_idx is None:
            try:
                sample_idx = int(request.args.get("sample_idx", None))
            except Exception as ignored:
                pass
            if sample_idx is None:
                if dataset.dsmetadata.get("annoorder", "sequential") == 'random':
                    sample_idx = random.randint(0, dataset.dsmetadata.get("size", 1))
                else:
                    existing = dataset.getannos(dbsession, session['user'])
                    annotated_samples = set(map(lambda e: str(e.sample), existing))
                    print(annotated_samples)

                    sample_idx = 0
                    for attempt in range(0, df.shape[0]):
                        if str(attempt) in annotated_samples:
                            continue
                        sample_idx = attempt
                        break

        set_sample_idx = None
        set_sample_value = None
        try:
            set_sample_idx = str(int(request.args.get("set_sample_idx", None)))
        except Exception as ignored:
            pass

        if not set_sample_idx is None:
            set_sample_value = request.args.get("set_value", "")[:500]

        if not set_sample_idx is None and not set_sample_value is None:
            dataset.setanno(dbsession, session['user'], set_sample_idx, set_sample_value)

        random_sample = random.randint(0, dataset.dsmetadata.get("size", 1))
        sample_content = df[textcol][sample_idx]

        curanno_data = dataset.getanno(dbsession, session['user'], sample_idx)
        curanno = None
        if curanno_data and 'data' in curanno_data and \
                'value' in curanno_data['data']:
            curanno = curanno_data['data']['value']
        print("*"*80, curanno_data, file=sys.stderr)

    return render_template("annotate.html", dataset=dataset, task=task, sample_idx=sample_idx, random_sample=random_sample, sample_content = sample_content, curanno=curanno)

@app.route(BASEURI + "/dataset/<dsid>/edit", methods=['GET', 'POST'])
@app.route(BASEURI + "/dataset/create", methods=['GET', 'POST'])
@login_required
def new_dataset(dsid=None):
    err = None
    dataset = None
    editmode = 'create'

    with db.session_scope() as dbsession:
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

        if dataset.owner is None:
            userobj = db.by_id(dbsession, session['user'])
            dataset.owner = userobj

        dbsession.add(dataset)

        if request.method == 'POST':

            formaction = request.form.get("action", None)
            #print("--- " * 5)
            #print("action", formaction)
            #print("form", request.form)
            #print("files", request.files)
            #print("--- " * 5)

            dsdirty = False
            if not formaction is None and formaction == 'change_name':
                dsname = request.form.get('dataset_name', None)
                if not dsname is None:
                    dsname = dsname.strip()
                    if dsname != '':
                        dataset.dsmetadata['name'] = dsname
                        dsdirty = True

            if not formaction is None and formaction == 'change_textcol' and not request.form.get("textcol", None) is None:
                dataset.dsmetadata['textcol'] = request.form.get("textcol", None)
                dsdirty = True

            if not formaction is None and formaction == 'change_idcolumn' and not request.form.get("idcolumn", None) is None:
                dataset.dsmetadata['idcolumn'] = request.form.get("idcolumn", None)
                dsdirty = True

            if not formaction is None and formaction == 'change_annoorder' and not request.form.get("annoorder", None) is None:
                dataset.dsmetadata['annoorder'] = request.form.get("annoorder", None)
                dsdirty = True

            if not formaction is None and formaction == 'addannotator' and not request.form.get("annouser", None) is None:
                annouser = request.form.get("annouser", None)
                dataset.addannotator(annouser)
                dsdirty = True

            if not formaction is None and formaction == 'remannotator' and not request.form.get("annouser", None) is None:
                annouser = request.form.get("annouser", None)
                dataset.remannotator(annouser)
                dsdirty = True

            if not formaction is None and formaction == 'change_taglist' and not request.form.get("settaglist", None) is None:
                newtags = request.form.get("settaglist", None).split("\n")
                newtags = filter(lambda l: not l is None and l.strip() != '', newtags)
                newtags = map(lambda l: l.strip(), newtags)
                newtags = list(newtags)
                dataset.dsmetadata['taglist'] = newtags
                dsdirty = True

            new_content = None
            if not formaction is None and formaction == 'upload_file':
                if not request.files is None and 'upload_file' in request.files:
                    fileobj = request.files['upload_file']
                    if fileobj and fileobj.filename:
                        dataset.dsmetadata['upload_filename'] = secure_filename(fileobj.filename)
                        dataset.dsmetadata['upload_mimetype'] = fileobj.mimetype
                        dataset.dsmetadata['upload_timestamp'] = datetime.now().timestamp()
                        dataset.dsmetadata['hasdata'] = True
                        dsdirty = True

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

        return render_template('dataset_new.html', error=err, dataset=dataset, editmode=editmode, previewdf=df, db=db, ds_errors=ds_errors, dbsession=dbsession)

@app.route(BASEURI + '/settings', methods=['GET', 'POST'])
@login_required
def settings():
    acterror = None

    with db.session_scope() as dbsession:
        userobj = db.by_id(dbsession, session['user'])
        if request.method == 'POST':
            act = request.form.get("action", None)

            if act == 'change_displayname':
                userobj.displayname = request.form.get("new_displayname", userobj.displayname) or ""
                dbsession.add(userobj)
                session['user_displayname'] = userobj.get_name()

            if act == 'change_password':
                req_pwc = request.form.get("curpassword", None)
                req_pw1 = request.form.get("newpw1", None)
                req_pw2 = request.form.get("newpw2", None)

                try:
                    userobj.change_password(dbsession, req_pwc, req_pw1, req_pw2)
                except Exception as e:
                    acterror = "%s %s %s" % (e, req_user_obj, session['user'])

        return render_template('settings.html', error=acterror, session_user=userobj)

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
                        flash('You were successfully logged in')
                        session['user'] = req_user_obj.uid
                        session['user_email'] = req_user_obj.email
                        session['user_displayname'] = req_user_obj.get_name()
                        loginerror = None

                        return redirect(url_for('index'))
        else:
            return redirect(url_for('index'))

    return render_template('login.html', error=loginerror)
