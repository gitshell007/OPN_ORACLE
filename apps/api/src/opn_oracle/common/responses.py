"""Shared response schemas."""

from apiflask import Schema
from apiflask.fields import Dict, Integer, List, Nested, Raw, String


class ProblemSchema(Schema):
    type = String(required=True)
    title = String(required=True)
    status = Integer(required=True)
    detail = String(required=True)
    instance = String(required=True)
    code = String(required=True)
    request_id = String(required=True)
    errors = Raw(required=False)


class DependencySchema(Schema):
    status = String(required=True)


class HealthSchema(Schema):
    status = String(required=True)
    dependencies = Dict(values=Nested(DependencySchema), required=False)


class MetaSchema(Schema):
    name = String(required=True)
    version = String(required=True)
    release = String(required=True)
    environment = String(required=True)
    capabilities = List(String(), required=True)
