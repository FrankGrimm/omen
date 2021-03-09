"""
API entity schemas
"""
# pylint: disable=no-self-use,too-many-instance-attributes

import marshmallow as ma


class UserSchema(ma.Schema):
    user_id = ma.fields.Integer(required=True)
    display_name = ma.fields.String(required=True)

    @staticmethod
    def to_api(user):
        inst = UserSchema()
        inst.user_id = user.uid
        inst.display_name = user.get_name()
        return inst


class DatasetSchema(ma.Schema):
    """
    API schema for database entities
    """

    id = ma.fields.Integer(required=True)
    name = ma.fields.String(required=True)
    owner = ma.fields.Nested(UserSchema, required=True)

    @staticmethod
    def to_api(dataset):
        inst = DatasetSchema()
        inst.id = dataset.dataset_id
        inst.name = dataset.get_name()
        inst.owner = UserSchema.to_api(dataset.owner)
        return inst


class APIUserAuth(ma.Schema):
    user_id = ma.fields.Integer(required=True)
    auth_method = ma.fields.String(required=True)


class APIRootResponse(ma.Schema):
    version = ma.fields.String(required=True)
    api_version = ma.fields.String(required=True)
    openapi_descriptor = ma.fields.Url(required=True)
    authenticated = ma.fields.Nested(APIUserAuth)


class AnnotationTask(ma.Schema):
    id = ma.fields.Integer(required=True)
    name = ma.fields.String(required=True)
    dataset = ma.fields.String(required=True)
    progress = ma.fields.Integer()
    progress_today = ma.fields.Integer()
    user_roles = ma.fields.List(ma.fields.String())
    work_packages = ma.fields.List(ma.fields.String())
    size = ma.fields.Integer()

    @staticmethod
    def convert_task(task):
        converted = AnnotationTask()
        converted.id = task.id
        converted.name = task.name
        converted.dataset = task.dataset.get_name() if task.dataset else None
        converted.progress = task.progress
        converted.progress_today = task.progress_today
        converted.user_roles = list(task.user_roles) if task.user_roles is not None else []
        converted.work_packages = list(task.splits) if task.splits is not None else []
        converted.size = task.size
        return converted
