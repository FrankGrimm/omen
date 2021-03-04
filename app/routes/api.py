"""
OMEN API endpoint definition.

## noteworthy URLs:

- The OpenAPI descriptor is exposed as `/omen/api/1.0/openapi.json`.
- The API itself lives under `/omen/api/1.0/`.
- A visual instance of Swagger UI is available under `/omen/api/1.0/ui`.
"""
# pylint: disable=no-self-use,too-many-instance-attributes

import logging

from flask import redirect, request
from flask.views import MethodView
from flask_smorest import Api, Blueprint, abort

from app.lib.viewhelpers import get_session_user
from app.lib import config
from app.lib import crypto
from app.lib import api_schemas as schemas
from app import __version__ as app_version
from app.web import app, BASEURI, db
app.config["API_TITLE"] = config.get("product_name", "Annotations") + " " + app_version + " API"
app.config["API_VERSION"] = "1.0"
app.config["OPENAPI_VERSION"] = "3.0.2"
app.config["OPENAPI_URL_PREFIX"] = BASEURI + "/api/1.0"
app.config["OPENAPI_SWAGGER_UI_PATH"] = "/ui"
app.config["OPENAPI_SWAGGER_UI_VERSION"] = "3.35.2"
app.config["OPENAPI_SWAGGER_UI_URL"] = "https://cdnjs.cloudflare.com/ajax/libs/swagger-ui/3.35.2/"
app.config['API_SPEC_OPTIONS'] = {
        'components': {
            'securitySchemes': {
                "interactive": {
                    "type": "apiKey",
                    "in": "cookie",
                    "description": "You can use this API with any existing interactive user session.",
                    "name": app.config.get("SESSION_COOKIE_NAME", "session"),
                    },
                "token": {
                    "type": "http",
                    "scheme": "bearer",
                    }
                },
            },
        'security': [{"interactive": []}, {"token": []}],
    }
app.config['OPENAPI_SWAGGER_UI_ENABLE_OAUTH'] = True

flask_api = Api(app)

api = Blueprint("api", "api", url_prefix=BASEURI + "/api/1.0",
                description="OMEN API")


def api_get_auth_info(dbsession):
    """
    Tries to establish a user for the current request given one of the
    implemented authorization strategies:

    a) a simple flask user session, established through interactive login, or
    b) a bearer token authorization
    """
    authinfo = schemas.APIUserAuth()
    api_user = get_session_user(dbsession)

    if api_user is not None:
        authinfo.auth_method = "interactive"
    else:
        bearer_token, api_user = api_bearer_authentication(dbsession)
        if bearer_token is not None and bearer_token.get("by", None) is not None:
            logging.debug("received valid bearer token for uid %s, token uuid: %s",
                          bearer_token['by'],
                          bearer_token['uuid'])
        authinfo.auth_method = "bearer"

    if api_user is None:
        return None
    authinfo.user_id = api_user.uid
    return authinfo, api_user


def api_bearer_authentication(dbsession):
    """
    Checks and validates any token authorization headers that might be
    present in the current request.
    """
    authorization_header = request.headers.get("Authorization", None)
    if authorization_header is None or authorization_header.strip() == "":
        return None, None

    authorization_header = authorization_header.strip()

    if not authorization_header.lower().startswith("bearer "):
        return None, None

    authorization_token = authorization_header[len("bearer "):].strip()
    unsafe_token = crypto.jwt_decode_unsafe(authorization_token)
    if unsafe_token is None or not isinstance(unsafe_token, dict) or \
            unsafe_token.get("by", None) is None:
        return None, None

    unsafe_user_id = unsafe_token.get("by", None)
    try:
        unsafe_user_id = int(unsafe_user_id)
    except ValueError:
        return None, None

    target_user = db.User.by_id(dbsession, unsafe_user_id, no_error=False)

    verified_token = target_user.validate_api_token(dbsession, authorization_token)
    if verified_token is None:
        return None, None

    # token and target use are verified at this point
    return verified_token, target_user


@api.before_request
def api_require_login():
    """
    Ensure that all API requests are authenticated.
    """
    with db.session_scope() as dbsession:
        authinfo, _ = api_get_auth_info(dbsession)
        if authinfo is None:
            # unauthorized
            return abort(401, message="Unauthorized")
        return None


@app.route(BASEURI + "/api/")
def api_redirect_to_current():
    """
    Redirect to the root of the most recent API version.
    """
    return redirect(BASEURI + "/api/1.0")


@api.route("/")
class APIRoot(MethodView):

    @api.response(200, schemas.APIRootResponse)
    def get(self):
        with db.session_scope() as dbsession:
            authinfo, _ = api_get_auth_info(dbsession)

            api_root_info = {
                    "version": app_version,
                    "api_version": app.config.get("API_VERSION", "1"),
                    "openapi_descriptor": app.config.get("OPENAPI_URL_PREFIX", "") + "/openapi.json",
                    "authenticated": authinfo
                    }
            return api_root_info


@api.route("/tasks")
class APITasks(MethodView):

    @api.response(200, schemas.AnnotationTask(many=True))
    def get(self):
        with db.session_scope() as dbsession:
            _, session_user = api_get_auth_info(dbsession)
            annotation_tasks = db.datasets.annotation_tasks(dbsession, session_user)
            return [schemas.AnnotationTask.convert_task(task) for task in annotation_tasks]


@api.route("/datasets")
class APIDatasets(MethodView):

    @api.response(200, schemas.DatasetSchema(many=True))
    def get(self):
        with db.session_scope() as dbsession:
            _, session_user = api_get_auth_info(dbsession)

            datasets = db.datasets.accessible_datasets(dbsession,
                                                       session_user,
                                                       include_owned=True)

            return [schemas.DatasetSchema.to_api(dataset) for dataset in datasets.values()]


flask_api.register_blueprint(api)
