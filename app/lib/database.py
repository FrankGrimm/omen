from datetime import datetime
from io import StringIO
import json
import uuid
import sys
import psycopg2
import psycopg2.extras
import os
import pandas as pd
import app.web as web
from passlib.hash import scrypt
import getpass
import atexit
from . import config

PW_MINLEN = 4
conn = None

def shutdown():
    global conn
    print("DB shutdown")
    conn.commit()
    conn.close()

def connect():
    global conn
    conn = psycopg2.connect(config.get("database", raise_missing=True))
    conn.cursor_factory = psycopg2.extras.RealDictCursor
    atexit.register(shutdown)

connect()

class User:
    def __init__(self, uid = None, email = None, pwhash = None):
        self.uid = uid
        self.email = email
        self.pwhash = pwhash

    def verify_password(self, pw):
        return scrypt.verify(pw, self.pwhash)

    def change_password(self, curpw, pw1, pw2):
        if not curpw or not pw1 or not pw2:
            raise Exception("All fields mandatory")

        if not self.verify_password(curpw):
            raise Exception("Invalid credentials")

        if pw1 != pw2:
            raise Exception("Password and confirmation do not match")

        newpwhash = scrypt.hash(pw1)
        cur = conn.cursor()
        cur.execute("UPDATE users SET pwhash = %s WHERE users.id = %s", (newpwhash, self.uid))
        cur.close()
        conn.commit()
        self.pwhash = newpwhash

        return self.verify_password(pw1)

    def __str__(self):
        return "[User #%s, %s]" % (self.uid, self.email)

class Dataset:
    def __init__(self, dbrow = {}, owner = None, metadata = None):
        self.id = dbrow.get("id", None)
        self.persisted = True
        if self.id is None:
            self.id = str(uuid.uuid4())
            self.persisted = False
        self.owner = dbrow.get("owner", owner)
        self.metadata = dbrow.get("metadata", metadata)
        if self.metadata is None:
            self.metadata = {}
        if not 'acl' in self.metadata:
            self.metadata['acl'] = {}
        if not 'format' in self.metadata:
            self.metadata['format'] = {}
        if not 'task' in self.metadata:
            self.metadata['task'] = {"type": "document_tagging", "tags": []}
        if not 'size' in self.metadata:
            self.metadata['size'] = None
        if not 'created' in self.metadata:
            self.metadata['created'] = datetime.now().timestamp()
        if not 'updated' in self.metadata:
            self.metadata['updated'] = datetime.now().timestamp()
        if not 'annoorder' in self.metadata:
            self.metadata['annoorder'] = 'sequential'

        self.content = None

    def annotations(self):
        df = self.as_df()
        df['idxmerge'] = df.index.astype(str)

        for userobj in userlist():
            uannos = self.getannos(userobj.uid)
            if uannos is None or len(uannos) == 0:
                continue
            uannos = pd.DataFrame.from_dict(uannos).drop(["uid", "dataset"], axis=1)
            uannos = uannos.set_index("sample")
            df = pd.merge(df, uannos, left_on='idxmerge', right_index=True, how='left', indicator=False)
            df = df.rename(columns={"annotation": "anno-%s" % userobj.uid})

        return df

    def getannos(self, uid):
        val = None

        cur = conn.cursor()
        cur.execute("SELECT * FROM annotations WHERE uid = %s AND dataset = %s", (uid, self.id))
        val = cur.fetchall()

        cur.close()
        conn.commit()
        return val


    def getanno(self, uid, sample):
        val = None
        cur = conn.cursor()
        cur.execute("SELECT * FROM annotations WHERE uid = %s AND dataset = %s AND sample = %s", (uid, self.id, str(sample)))
        val = cur.fetchone()
        if not val is None:
            val = val['annotation']

        cur.close()
        conn.commit()
        return val

    def setanno(self, uid, sample, value):
        # delete in case it exists
        cur = conn.cursor()

        cur.execute("DELETE FROM annotations WHERE uid = %s AND dataset = %s AND sample = %s", (uid, self.id, str(sample)))
        cur.execute("INSERT INTO annotations (uid, dataset, sample, annotation) VALUES (%s, %s, %s, %s)", (uid, self.id, str(sample), value))
        cur.close()
        conn.commit()

    def annocount(self, uid):
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS cnt FROM annotations WHERE uid = %s AND dataset = %s", (uid, self.id))

        obj = cur.fetchone()
        if not obj is None:
            return obj['cnt']

        return 0

    def remannotator(self, uid):
        if uid is None:
            return False

        if not type(uid) is str:
            uid = int(uid)

        if uid == self.owner:
            return True

        curacl = self.metadata.get("acl", {})
        if uid in curacl:
            del curacl[uid]
        else:
            return False

        self.metadata['acl'] = curacl
        print("-" * 20, self.metadata)
        return True

    def addannotator(self, uid):
        if uid is None:
            return False

        if not type(uid) is str:
            uid = int(uid)

        if uid == self.owner:
            return True

        curacl = self.metadata.get("acl", {})
        if not curacl:
            curacl = {}
        if uid in curacl:
            return True
        else:
            curacl[uid] = 'annotate'

        self.metadata['acl'] = curacl
        print("-" * 20, self.metadata)
        return True

    def check(self):
        errorlist = []

        if not self.persisted:
            errorlist.append("not saved")

        if self.metadata.get("hasdata", None) is None:
            errorlist.append("no data")

        if self.metadata.get("taglist", None) is None or \
                len(self.metadata.get("taglist", [])) == 0:
            errorlist.append("no tags defined")

        dferr = self.as_df(strerrors = True)
        if dferr is None:
            errorlist.append("no data")
        if type(dferr) is str:
            errorlist.append("data error: %s" % dferr)

        textcol = self.metadata.get("textcol", None)
        if textcol is None:
            errorlist.append("no text column")
        if not dferr is None and \
                not type(dferr) is str and \
                not textcol in dferr.columns:
            errorlist.append("text column '%s' not found in data" % textcol)

        acl = self.metadata.get("acl", [])
        if acl is None or len(acl) == 0:
            errorlist.append("no annotators")

        if len(errorlist) is 0:
            return None
        return errorlist

    def as_df(self, strerrors = False):
        if strerrors:
            try:
                return self.as_df(strerrors = False)
            except Exception as e:
                return str(e)
        else:
            content = self.get_content()
            content = StringIO(content)
            sep = self.metadata.get("sep", ",")
            quotechar = self.metadata.get("quotechar", '"')
            return pd.read_csv(content, sep=sep, header='infer', quotechar=quotechar)

    def update_content(self, new_content):
        self.content = new_content
        cur = conn.cursor()

        if self.id is None:
            raise Exception("no id")
        if self.owner is None:
            raise Exception("no owner")
        if not self.persisted:
            raise Exception("need to persist instance first")

        cur.execute("UPDATE datasets SET content=%s WHERE owner = %s AND id = %s", (self.content, self.owner, self.id))

        cur.close()
        conn.commit()
        return self.update()

    def update(self):
        self.metadata['updated'] = datetime.now().timestamp()

        cur = conn.cursor()

        if self.id is None:
            raise Exception("no id")
        if self.owner is None:
            raise Exception("no owner")
        if self.metadata is None:
            self.metadata = {}

        df = None
        try:
            df = self.as_df()
        except Exception as ignored:
            pass
        if not df is None:
            self.metadata['size'] = df.shape[0]

        if not self.persisted:
            # initial insert
            self.persisted = True

            cur.execute("INSERT INTO datasets (id, owner, metadata) VALUES(%s, %s, %s)", (self.id, self.owner, json.dumps(self.metadata)))
        else:
            # update existing
            cur.execute("UPDATE datasets SET metadata=%s WHERE owner = %s AND id = %s", (json.dumps(self.metadata), self.owner, self.id))

        cur.close()
        conn.commit()

        return True

    def get_content(self):
        if not self.content is None:
            return self.content

        cur = conn.cursor()

        cur.execute("SELECT content FROM datasets WHERE id = %s", (self.id,))
        res = cur.fetchone()
        if not res is None:
            res = res['content']
            if not res is None:
                self.content = res

        cur.close()

        return self.content

def dataset_by_id(user_id, dataset_id):
    cur = conn.cursor()
    cur.execute("SELECT id, owner, metadata FROM datasets WHERE datasets.owner = %s and datasets.id = %s", (user_id, dataset_id))
    obj = cur.fetchone()
    if not obj is None:
        return Dataset(obj)

    return None

def my_datasets(user_id):
    res = {}

    cur = conn.cursor()
    cur.execute("SELECT id, owner, metadata FROM datasets WHERE owner = %s", (user_id,))
    for obj in cur.fetchall():
        ds = Dataset(obj)
        if not ds or not ds.id:
            continue
        res[ds.id] = ds

    cur.close()

    return res

def accessible_datasets(user_id, include_owned=False):
    res = {}
    cur = conn.cursor()

    if include_owned:
        res = my_datasets(user_id)

    cur.execute("SELECT id, owner, metadata FROM datasets WHERE (metadata->'acl')::jsonb ? %s", (str(user_id),))
    for obj in cur.fetchall():
        ds = Dataset(obj)
        if not ds or not ds.id:
            continue
        res[ds.id] = ds

    cur.close()
    return res

def by_email(email):
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE email LIKE %s", (email,))
    obj = cur.fetchone()
    if not obj is None:
        return User(uid = obj['id'], email = obj['email'], pwhash = obj['pwhash'])

    return None

def by_id(uid):
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE users.id = %s", (uid,))
    obj = cur.fetchone()
    if not obj is None:
        return User(uid = obj['id'], email = obj['email'], pwhash = obj['pwhash'])

    return None

def insert(email, pwhash):
    existing = by_email(email)
    if not existing is None:
        return (False, existing)

    cur = conn.cursor()
    cur.execute("INSERT INTO users (email, pwhash) VALUES (%s, %s)", (email, pwhash))
    conn.commit()
    cur.close()

    newobj = by_email(email)
    return (True, newobj)

def annotation_tasks(for_user):
    datasets = accessible_datasets(for_user, include_owned = True)
    tasks = []

    for dsid, dataset in datasets.items():
        check_result = dataset.check()
        if not check_result is None and len(check_result) > 0:
            continue

        dsname = dataset.metadata.get("name", dsid)

        # TODO calculate progress
        task = {"id": dsid, "name": dsname, "dataset": dataset, "progress": 0, "size": dataset.metadata.get("size", -1) or -1, "annos": dataset.annocount(for_user) }

        if task['size'] and task['size'] > 0 and task['annos'] and task['annos'] > 0:
            task['progress'] = round(task['annos'] / task['size'] * 100.0)

        tasks.append(task)

    return tasks

def userlist():
    allusers = []

    cur = conn.cursor()
    cur.execute("SELECT id, email FROM users")
    for obj in cur.fetchall():
        obj = User(uid = obj['id'], email = obj['email'])
        allusers.append(obj)
    cur.close()

    return allusers

def hashtest():
    h = scrypt.hash("password")
    print("hash", h)
    print(scrypt.verify("password", h))
    print(scrypt.verify("wrong", h))

def create_user():
    print("creating user")
    email = input("E-Mail: ")
    pw1 = getpass.getpass("Password: ")
    pw2 = getpass.getpass("Confirm password: ")
    if not email or not pw1 or not pw2:
        print("Missing email or password")
        sys.exit(1)
    if pw1 != pw2:
        print("Password and confirmation do not match")
        sys.exit(1)

    if len(pw1) < PW_MINLEN:
        print("Passwords need to be at least %s characters long." % PW_MINLEN)
        sys.exit(1)

    pwhash = scrypt.hash(pw1)
    del pw1
    del pw2

    print("inserting")
    inserted, obj = insert(email, pwhash)
    if inserted:
        print("created user", obj)
    else:
        print("user already exists", obj)

def dotest():
    print("db::dotest")
    hashtest()

    print("by_email", by_email("admin"))
    print("by_uid", by_id(1))


