"""
Data curation related routes.
"""
import json
import math
from collections import namedtuple, defaultdict

from flask import flash, render_template, request

from app.lib.viewhelpers import login_required, get_session_user
import app.lib.config as config
from app.web import app, BASEURI, db

from app.routes.dataset import handle_comment_action
from app.lib.models.comments import Comments

VALID_INSPECT_FILTERS = {
        "curated": "Curated",
        "uncurated": "Uncurated",
        "disputed": "Disputed",
        "undisputed": "Undisputed",
        "disputed,uncurated": "Disputed, Uncurated",
        "undisputed,uncurated": "Undisputed, Uncurated",
    }


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


def json_param(val):
    if val is None:
        return None
    if isinstance(val, str):
        if val == "":
            return None
        return json.loads(val)

    return None


def get_tagstates(cur_dataset):
    tagstates = {}
    restrict_include = json_param(request.args.get("restrict_taglist_include", "[]"))
    restrict_exclude = json_param(request.args.get("restrict_taglist_exclude", "[]"))

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


def request_arg(key, valid_values, default_value=None):
    value = default_value
    req_value = request.args.get(key, None)

    if req_value is not None and req_value.lower() in valid_values:
        value = req_value.lower()
    return value


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


def inspect_filters():
    ds_filters = namedtuple("InspectFilters", ["query", "split", "viewfilter"])

    ds_filters.query = request.args.get("query", "").strip()

    ds_filters.viewfilter = request_arg("viewfilter", VALID_INSPECT_FILTERS.keys(), None)
    if ds_filters.viewfilter is not None:
        # pylint: disable=no-member
        ds_filters.viewfilter = list(map(lambda vf: vf.strip(), ds_filters.viewfilter.strip().split(",")))

    # pylint: disable=comparison-with-callable
    ds_filters.split = request.args.get("split", request.args.get("restrict_split", None))
    if ds_filters.split == "*":
        ds_filters.split = None
    if ds_filters.split is not None:
        ds_filters.split = [ds_filters.split]

    return ds_filters


def inspect_handle_action(dbsession, cur_dataset, session_user, ds_filters):
    if request.method != "POST" or request.json is None:
        return None

    bulk_action = request.json.get("bulk_action", None)
    if bulk_action not in ["accept_majority", "accept_undisputed"]:
        return None

    # only apply bulk actions to samples that have not been curated yet
    ds_filters.viewfilter = ["uncurated"]

    if bulk_action == "accept_undisputed":
        ds_filters.viewfilter.append("undisputed")
    if bulk_action == "accept_majority":
        ds_filters.viewfilter.append("disputed")

    system_user = db.User.system_user(dbsession)

    # retrieve all samples that match the current criteria, up to 10000 per default
    df, annotation_columns, results = cur_dataset.annotations(dbsession,
                                                              foruser=system_user,
                                                              page=1,
                                                              page_size=config.get_int("bulk_action_max", 10000),
                                                              restrict_view=ds_filters.viewfilter,
                                                              user_column="annotations",
                                                              query=ds_filters.query,
                                                              splits=ds_filters.split)
    bulk_action_result = {
            "action": bulk_action
            }
    bulk_action_result['affected'] = results
    bulk_action_result['applied'] = 0

    for bulk_sample in df['sample_index']:
        new_value = None

        anno_votes = defaultdict(int)

        for anno_col in annotation_columns:
            if anno_col not in df.columns:
                continue
            anno_val = df.loc[df.sample_index == bulk_sample][anno_col].values[0]
            if anno_val is None:
                continue
            anno_votes[anno_val] += 1

        bulk_action_result['lastrow'] = anno_votes

        if bulk_action == "accept_undisputed" and len(anno_votes) == 1:
            new_value = list(anno_votes.keys())[0]
        elif bulk_action == "accept_majority" and len(anno_votes) > 1:
            vote_counts = list(anno_votes.values())
            if vote_counts.count(max(vote_counts)) == 1:
                # maximum only occurs once in a list of n>1 elements and is thus a majority vote
                for anno, votes in anno_votes.items():
                    if votes == max(vote_counts):
                        new_value = anno
                        break

        if new_value is not None:
            cur_dataset.setanno(dbsession, system_user, bulk_sample, new_value)
            bulk_action_result['applied'] += 1

    db.Activity.create(dbsession,
                       session_user,
                       cur_dataset,
                       "bulk_action",
                       "%s => %s affected" % (bulk_action, results))

    return bulk_action_result


@app.route(BASEURI + "/dataset/<dsid>/inspect", methods=["GET", "POST"])
@login_required
def inspect_dataset(dsid=None):
    with db.session_scope() as dbsession:
        ds_filters = inspect_filters()

        cur_dataset = db.datasets.get_accessible_dataset(dbsession, dsid)
        session_user = get_session_user(dbsession)

        # tagstates, restrict_include, restrict_exclude = get_tagstates(cur_dataset)

        template_name = "dataset_inspect.html"
        ctx_args = {}

        req_sample = inspect_get_requested_sample()
        if req_sample is not None and not req_sample == "":
            if request.json is not None and "set_tag" in request.json:
                cur_dataset.setanno(dbsession, db.User.system_user(dbsession), req_sample, request.json.get("set_tag", None))

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
        except ValueError as _:  # noqa: F841
            # flash("Invalid value for param 'page': %s" % e, "error")
            pagination.page = 1

        inspect_action_result = inspect_handle_action(dbsession, cur_dataset, session_user, ds_filters)
        if inspect_action_result is not None:
            return inspect_action_result

        new_comment_result = handle_comment_action(dbsession, session_user, cur_dataset)
        if new_comment_result is not None:
            return new_comment_result

        df, annotation_columns, results = cur_dataset.annotations(dbsession,
                                                                  foruser=db.User.system_user(dbsession),
                                                                  page=pagination.page,
                                                                  page_size=pagination.page_size,
                                                                  restrict_view=ds_filters.viewfilter,
                                                                  user_column="annotations",
                                                                  query=ds_filters.query,
                                                                  splits=ds_filters.split)

        df = reorder_dataframe(df, cur_dataset, annotation_columns)

        pagination_elements = get_pagination_elements(pagination, results, pagination_size=5)

        comments = Comments.fortarget(dbsession,
                                      cur_dataset.activity_target(),
                                      session_user)
        if inspect_update_sample(req_sample, cur_dataset, ctx_args, df):
            template_name = "dataset_inspect_row.html"

        return render_template(template_name, dataset=cur_dataset,
                               df=df,
                               dbsession=dbsession,
                               pagination=pagination,
                               results=results,
                               comments=comments,
                               # tagstates=tagstates,
                               annotation_columns=annotation_columns,
                               pagination_elements=pagination_elements,
                               ds_splits=cur_dataset.defined_splits(dbsession),
                               ds_filters=ds_filters,
                               valid_filters=VALID_INSPECT_FILTERS,
                               userroles=cur_dataset.get_roles(dbsession, session_user),
                               **ctx_args
                               )
