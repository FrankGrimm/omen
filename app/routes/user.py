"""
User login/logout and account related routes
"""

import logging

from flask import flash, redirect, render_template, request, url_for, session, abort

import urllib.parse
from passlib.hash import scrypt

from app.lib.viewhelpers import login_required, get_session_user
import app.lib.email as lib_email
import app.lib.config as config
import app.lib.crypto as crypto
from app.web import app, BASEURI, db


@app.route(BASEURI + "/logout")
@login_required
def logout():
    _ = [session.pop(key) for key in list(session.keys())]
    session.clear()

    return redirect(url_for('index'))


@app.route(BASEURI + '/login', methods=['GET', 'POST'])
def login(backto=None):
    if backto is None:
        backto = request.args.get("backto", None)
    loginerror = None

    if request.method == 'POST':
        req_user = request.form.get("username", None)
        req_pw = request.form.get("password", None)

        loginerror = 'Invalid credentials'
        if req_user is not None and req_pw is not None:
            with db.session_scope() as dbsession:
                req_user_obj = db.User.by_email(dbsession, req_user, doraise=False)
                if req_user_obj is not None:
                    if req_user_obj.verify_password(req_pw):
                        flash('You were successfully logged in.', "success")
                        session['user'] = req_user_obj.uid
                        session['user_email'] = req_user_obj.email
                        session['user_displayname'] = req_user_obj.get_name()
                        req_user_obj.purge_invites(dbsession)
                        loginerror = None

                        db.Activity.create(dbsession, req_user_obj, req_user_obj, "event", "login")
                        return redirect(url_for('index'))
        else:
            return redirect(url_for('index'))

    if loginerror is not None:
        flash("%s" % loginerror, "error")

    return render_template('login.html')


def handle_token_settings(dbsession, session_user):
    if request.json is None or request.json.get("action", None) is None:
        return None

    action = request.json.get("action", None)
    if action == "new_api_token":
        new_token_description = request.json.get("api_token_generate_description", "").strip()
        if new_token_description == "":
            return abort("parameter missing: description")
        return session_user.new_api_token(dbsession, new_token_description)

    if action == "revoke_api_token":
        revoke_uuid = request.json.get("api_token_id", None)
        if revoke_uuid is None or revoke_uuid.strip() == "":
            return abort("parameter missing: api_token_id")
        revoke_uuid = revoke_uuid.strip()
        return session_user.revoke_api_token(dbsession, revoke_uuid)

    return None


@app.route(BASEURI + '/settings', methods=['GET', 'POST'])
@login_required
def settings():
    with db.session_scope() as dbsession:
        userobj = db.User.by_id(dbsession, session['user'])
        if request.method == 'POST':
            token_action_result = handle_token_settings(dbsession, userobj)
            if token_action_result is not None:
                return token_action_result

            act = request.form.get("action", None)

            if act == 'change_displayname':
                previous_displayname = userobj.displayname or ""
                userobj.displayname = request.form.get("new_displayname", userobj.displayname) or ""
                dbsession.add(userobj)
                session['user_displayname'] = userobj.get_name()
                flash("Your display name was changed successfully.", "success")
                db.Activity.create(dbsession,
                                   userobj,
                                   userobj,
                                   "event",
                                   "setting_changed:display name '%s' => '%s'"
                                   % (previous_displayname, userobj.get_name()))

            if act == 'change_password':
                req_pwc = request.form.get("curpassword", None)
                req_pw1 = request.form.get("newpw1", None)
                req_pw2 = request.form.get("newpw2", None)

                try:
                    userobj.change_password(dbsession, req_pwc, req_pw1, req_pw2)
                    userobj.invalidate_keys(dbsession)
                    flash("Password successfully changed.", "success")
                    db.Activity.create(dbsession, userobj, userobj, "event", "password_changed")
                except Exception as e:
                    acterror = "%s %s %s" % (e, userobj, session['user'])
                    db.fprint(acterror)
                    flash('%s' % e, "error")

        return render_template('settings.html', session_user=userobj, dbsession=dbsession)


@app.route(BASEURI + "/user/invite", methods=["GET", "POST"])
def accept_invite():
    if not config.get_bool("feature_user_invite", True):
        return abort(400, description="Invitations are disabled by the server configuration.")

    invite_by = request.args.get("by", "").strip()
    try:
        invite_by = int(invite_by)
    except ValueError:
        return abort(400, description="invalid parameter format")

    invite_token = request.args.get("token", "").strip()
    if invite_token == "":
        return abort(400, description="invalid request, token not found")

    with db.session_scope() as dbsession:
        session_user = get_session_user(dbsession)
        by_user = db.User.by_id(dbsession, invite_by)
        token_data = None

        try:
            token_data = by_user.validate_invite(dbsession, invite_token)
        except crypto.InvalidTokenException as ite:
            return abort(400, description="Invalid token (%s)" % ite)

        if request.method == 'POST' and request.form is not None:
            if request.form.get("action", "") != "docreate":
                return abort(400, description="invalid form action")

            email = request.form.get("newuser_email", None)
            pw1 = request.form.get("newuser_password", None)
            pw2 = request.form.get("newuser_password_confirm", None)
            displayname = request.form.get("newuser_displayname", "")

            if db.User.validate_newuser(email, pw1, pw2):
                pwhash = scrypt.hash(pw1)
                del pw1
                del pw2

                logging.info("inserting new user")
                inserted, created_userobj = db.User.insert_user(dbsession, email, pwhash, displayname=displayname)
                if inserted:
                    by_user.invalidate_invite(dbsession, token_data['uuid'], claimed_by=created_userobj)
                    flash("Account created. Please log in.", "success")
                    return redirect(url_for("login"))
                flash("An account with this e-mail already exists.", "error")

        return render_template("accept_invite.html",
                               session_user=session_user,
                               invite_by=by_user,
                               token_data=token_data)


def get_request_action():
    req_action = ""
    if request.json is not None and "action" in request.json:
        req_action = request.json.get("action", "")
    if request.form is not None and "action" in request.form:
        req_action = request.form.get("action", "")
    return req_action


@app.route(BASEURI + "/user/create", methods=["GET", "POST"])
@login_required
def createuser():
    with db.session_scope() as dbsession:
        session_user = db.User.by_id(dbsession, session['user'])

        allowed_actions = set()
        if config.get_bool("feature_user_invite", True):
            allowed_actions.add("generate_invite")
            allowed_actions.add("generate_invitemail")
        if config.get_bool("feature_user_manualcreate", True):
            allowed_actions.add("docreate")

        if request.method == 'POST' and (request.json is not None or len(request.form) > 0):
            req_action = get_request_action()

            if req_action not in allowed_actions:
                return abort(400, description="invalid action specified")

            if req_action == "generate_invite":
                invite_token = session_user.create_invite(dbsession)
                invite_uri = url_for("accept_invite")
                return {"token": invite_token, "uri": invite_uri, "by": session_user.uid}

            if req_action == "generate_invitemail":
                email = request.form.get("inviteMail", None)
                if email is None or "@" not in email:
                    flash("Could not interpret e-mail address", "error")
                    return redirect(url_for("createuser"))
                email = email.strip().lower()

                userobj = db.User.by_email(dbsession, email, doraise=False)
                if userobj is not None:
                    flash(f"Account {email} already exists.", "warning")
                    return redirect(url_for("createuser"))

                inv_host = request.headers.get("Host", "localhost")[:500].strip()
                inv_schema = "https"
                if request.headers.get("Referer", "").startswith("http://"):
                    inv_schema = "http"

                invite_token = session_user.create_invite(dbsession)
                invite_uri = url_for("accept_invite")

                by_enc = str(session_user.uid)
                token_enc = urllib.parse.quote(invite_token)

                platform_link = inv_schema + "://" + inv_host
                full_link = inv_schema + "://" + inv_host + invite_uri + f"?by={by_enc}&token={token_enc}"

                subject_line = "[omen] Invitation to OMEN annotation platform"

                message_text = f"""Hello,

{session_user.email} has invited you to join the OMEN annotation platform at {platform_link}.

Follow this link (valid for 48h) to create an account:

{full_link}

If you received this e-mail erroneously, please ignore it.
                """

                flash(f"Account invitation sent to {email}", "success")
                lib_email.send(email, subject_line, message_text)
                return redirect(url_for("createuser"))

            if req_action == "docreate":
                email = request.form.get("newuser_email", None)
                pw1 = request.form.get("newuser_password", None)
                pw2 = request.form.get("newuser_password_confirm", None)
                displayname = request.form.get("newuser_displayname", "")

                if db.User.validate_newuser(email, pw1, pw2):
                    pwhash = scrypt.hash(pw1)
                    del pw1
                    del pw2

                    logging.info("inserting new user")
                    inserted, created_userobj = db.User.insert_user(dbsession, email, pwhash, displayname=displayname)
                    if inserted:
                        flash("Account created.", "success")
                        logging.info("%s created new account %s", session_user, created_userobj)
                        return redirect(url_for("createuser"))
                    flash("An account with this e-mail already exists.", "warning")

        session_user.purge_invites(dbsession)
        pending_invites = session_user.get_invites('pending')

        return render_template("createuser.html",
                               pending_invites=pending_invites,
                               feature_email_invite=lib_email.is_available(),
                               feature_user_invite="generate_invite" in allowed_actions,
                               feature_user_manualcreate="docreate" in allowed_actions)
