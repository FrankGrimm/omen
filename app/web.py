import random
from datetime import datetime
from flask import Flask, flash, redirect, render_template, request, url_for, session, Response
from werkzeug.utils import secure_filename
import tempfile
from io import StringIO

BASEURI = "/omen"

app = Flask(__name__, static_url_path=BASEURI + "/static")

app.secret_key = b'rf-2939ou8jm3@O%T'

import app.lib.database as db

@app.before_request
def check_auth():
    if request and request.url_rule and request.url_rule.endpoint == 'login':
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
    if is_authenticated:
        annotation_tasks = db.annotation_tasks(session['user'])

    return dict(product_name="Annotations", is_authenticated=is_authenticated, tasks=annotation_tasks)

@app.errorhandler(404)
def page_not_found(error):
    return render_template("404.html", error=error), 404

@app.route('/')
@app.route(BASEURI + '/')
def index():
    db.dotest()
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
def logout():
    [session.pop(key) for key in list(session.keys())]
    session.clear()

    return redirect(url_for('index'))

@app.route(BASEURI + "/dataset/<dsid>/download")
def download(dsid = None):
    my_datasets = db.my_datasets(session['user'])
    access_datasets = db.accessible_datasets(session['user'])

    dataset = None
    if not dsid is None and dsid in my_datasets:
        dataset = my_datasets[dsid]
    if not dsid is None and dsid in access_datasets:
        dataset = access_datasets[dsid]

    df = dataset.annotations()

    s = StringIO()
    df.to_csv(s)
    csvc = s.getvalue()
    return Response(csvc,
        mimetype="text/csv",
        headers={"Content-disposition":
                 "attachment; filename=dataset.csv"})

@app.route(BASEURI + "/dataset")
@app.route(BASEURI + "/dataset/<dsid>")
def dataset(dsid=None):
    err = None

    my_datasets = db.my_datasets(session['user'])
    access_datasets = db.accessible_datasets(session['user'])

    dataset = None
    if not dsid is None and dsid in my_datasets:
        dataset = my_datasets[dsid]
    if not dsid is None and dsid in access_datasets:
        dataset = access_datasets[dsid]

    return render_template('dataset.html', error=err, my_datasets=my_datasets, access_datasets=access_datasets, dataset=dataset, db = db)

@app.route(BASEURI + "/dataset/<dsid>/annotate", methods=["GET", "POST"])
def annotate(dsid=None, sample_idx=None):
    dataset = None

    my_datasets = db.my_datasets(session['user'])
    access_datasets = db.accessible_datasets(session['user'])

    if not dsid is None and dsid in my_datasets:
        dataset = my_datasets[dsid]
    if not dsid is None and dsid in access_datasets:
        dataset = access_datasets[dsid]

    task = {"id": dsid, "name": dataset.metadata.get("name", dataset.id), "dataset": dataset, "progress": 0, "size": dataset.metadata.get("size", -1) or -1, "annos": dataset.annocount(session['user']) }

    if task['size'] and task['size'] > 0 and task['annos'] and task['annos'] > 0:
        task['progress'] = round(task['annos'] / task['size'] * 100.0)

    df = dataset.as_df()
    sample_content = None
    textcol = dataset.metadata.get("textcol", None)

    if sample_idx is None:
        try:
            sample_idx = int(request.args.get("sample_idx", None))
        except Exception as ignored:
            pass
        if sample_idx is None:
            if dataset.metadata.get("annoorder", "sequential") == 'random':
                sample_idx = random.randint(0, dataset.metadata.get("size", 1))
            else:
                existing = dataset.getannos(session['user'])
                annotated_samples = set(map(lambda e: str(e['sample']), existing))
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
        dataset.setanno(session['user'], set_sample_idx, set_sample_value)

    random_sample = random.randint(0, dataset.metadata.get("size", 1))
    sample_content = df[textcol][sample_idx]

    curanno = dataset.getanno(session['user'], sample_idx)

    return render_template("annotate.html", dataset=dataset, task=task, sample_idx=sample_idx, random_sample=random_sample, sample_content = sample_content, curanno=curanno)

@app.route(BASEURI + "/dataset/<dsid>/edit", methods=['GET', 'POST'])
@app.route(BASEURI + "/dataset/create", methods=['GET', 'POST'])
def new_dataset(dsid=None):
    err = None
    dataset = None
    editmode = 'create'
    if dsid is None:
        dataset = db.Dataset()
    else:
        dataset = db.dataset_by_id(session['user'], dsid)
        if not dataset is None:
            editmode = 'edit'
        else:
            dataset = db.Dataset()

    if dataset.owner is None:
        dataset.owner = session['user']

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
                    dataset.metadata['name'] = dsname
                    dsdirty = True

        if not formaction is None and formaction == 'change_textcol' and not request.form.get("textcol", None) is None:
            dataset.metadata['textcol'] = request.form.get("textcol", None)
            dsdirty = True

        if not formaction is None and formaction == 'change_annoorder' and not request.form.get("annoorder", None) is None:
            dataset.metadata['annoorder'] = request.form.get("annoorder", None)
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
            dataset.metadata['taglist'] = newtags
            dsdirty = True

        new_content = None
        if not formaction is None and formaction == 'upload_file':
            if not request.files is None and 'upload_file' in request.files:
                fileobj = request.files['upload_file']
                if fileobj and fileobj.filename:
                    print(fileobj)

                    dataset.metadata['upload_filename'] = secure_filename(fileobj.filename)
                    dataset.metadata['upload_mimetype'] = fileobj.mimetype
                    dataset.metadata['upload_timestamp'] = datetime.now().timestamp()
                    dataset.metadata['hasdata'] = True
                    dsdirty = True

                    with tempfile.TemporaryFile(mode='w+b') as tmpfile:
                        fileobj.save(tmpfile)
                        tmpfile.seek(0)
                        new_content = tmpfile.read()
                        if not new_content is None and not len(new_content) == 0:
                            new_content = new_content.decode('utf-8')

        if dsdirty:
            dataset.update()

        if not new_content is None:
            dataset.update_content(new_content)
            dataset.update()

        if dsdirty and dataset.persisted and editmode == 'create':
            # redirect to edit URI once dataset has been persisted
            return redirect(url_for('new_dataset', dsid=dataset.id))

    df = None

    if dataset and dataset.persisted and dataset.get_content():
        df = dataset.as_df(strerrors=True)

    return render_template('dataset_new.html', error=err, dataset=dataset, editmode=editmode, previewdf=df, db=db)

@app.route(BASEURI + '/settings', methods=['GET', 'POST'])
def settings():
    acterror = None

    if request.method == 'POST':
        act = request.form.get("action", None)
        if act == 'change_password':
            req_user_obj = db.by_id(session['user'])
            req_pwc = request.form.get("curpassword", None)
            req_pw1 = request.form.get("newpw1", None)
            req_pw2 = request.form.get("newpw2", None)

            try:
                req_user_obj.change_password(req_pwc, req_pw1, req_pw2)
            except Exception as e:
                acterror = "%s %s %s" % (e, req_user_obj, session['user'])

    return render_template('settings.html', error=acterror)

@app.route(BASEURI + '/login', methods=['GET', 'POST'])
def login():
    loginerror = None

    if request.method == 'POST':
        req_user = request.form.get("username", None)
        req_pw = request.form.get("password", None)

        loginerror = 'Invalid credentials'
        if not req_user is None and not req_pw is None:
            req_user_obj = db.by_email(req_user)
            if not req_user_obj is None:
                if req_user_obj.verify_password(req_pw):
                    flash('You were successfully logged in')
                    session['user'] = req_user_obj.uid
                    session['user_email'] = req_user_obj.email
                    loginerror = None

                    return redirect(url_for('index'))
        else:
            return redirect(url_for('index'))
    return render_template('login.html', error=loginerror)

