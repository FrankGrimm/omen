"""
Utility functions to query datasets
"""

from flask import session

from app.lib.models.dataset import Dataset
from app.lib.models.user import User


def dataset_roles(dbsession, user_id):
    res = {}

    user_obj = User.by_id(dbsession, user_id)

    all_user_datasets = accessible_datasets(dbsession, user_id, include_owned=True)

    for dataset_id, dataset in all_user_datasets.items():
        res[dataset_id] = dataset.get_roles(dbsession, user_obj)

    return res


def my_datasets(dbsession, user_id):
    res = {}

    user_obj = User.by_id(dbsession, user_id)

    for ds in dbsession.query(Dataset).filter_by(owner=user_obj).all():
        if not ds or not ds.dataset_id:
            continue
        res[str(ds.dataset_id)] = ds

    return res


def get_accessible_dataset(dbsession, dsid, check_role=None):
    session_user = User.by_id(dbsession, session["user"])

    access_datasets = accessible_datasets(dbsession, session_user, include_owned=True)

    cur_dataset = None
    if dsid is not None and dsid in access_datasets:
        cur_dataset = access_datasets[dsid]

    if check_role is None:
        return cur_dataset

    if cur_dataset is not None:
        user_roles = cur_dataset.get_roles(dbsession, session_user)
        if check_role not in user_roles:
            return None

    return cur_dataset


def accessible_datasets(dbsession, user_id, include_owned=False, has_role=None):
    res = {}

    if isinstance(user_id, int):
        user_obj = User.by_id(dbsession, user_id)
    elif isinstance(user_id, User):
        user_obj = user_id
    else:
        raise Exception("invalid type for parameter user_id")

    if include_owned:
        res = my_datasets(dbsession, user_id)

    if has_role is not None and isinstance(has_role, str):
        has_role = [has_role]

    for ds in dbsession.query(Dataset).all():
        dsacl = ds.get_roles(dbsession, user_obj)

        if dsacl is None or len(dsacl) == 0:
            continue
        if has_role is not None:
            matches_role = False
            for target_role in has_role:
                if target_role in dsacl:
                    matches_role = True
                    break
            if not matches_role:
                continue

        res[str(ds.dataset_id)] = ds

    return res


def annotation_tasks(dbsession, for_user):
    datasets = accessible_datasets(dbsession, for_user, include_owned=True)
    tasks = []

    for _, dataset in datasets.items():
        check_result = dataset.check_dataset()
        if check_result is not None and len(check_result) > 0:
            continue

        dsroles = dataset.get_roles(dbsession, for_user)
        if "annotator" in dsroles:
            task = dataset.get_task(dbsession, for_user)
            tasks.append(task)

    # make sure completed tasks are pushed to the bottom of the list
    tasks.sort(key=lambda task: (task.progress >= 100.0, task.name))

    return tasks
