"""Public, non-sensitive API metadata."""

from apiflask import APIBlueprint, Schema
from apiflask.fields import Boolean
from flask import current_app

from opn_oracle.common.responses import MetaSchema

bp = APIBlueprint("meta", __name__, url_prefix="/api/v1", tag="Meta")


class MetaQuerySchema(Schema):
    verbose = Boolean(load_default=False)


@bp.get("/meta")
@bp.input(MetaQuerySchema, location="query")
@bp.output(MetaSchema)
def meta(query_data: dict[str, bool]) -> dict[str, object]:
    capabilities = ["health"]
    if current_app.config["OPENAPI_ENABLED"]:
        capabilities.append("openapi")
    return {
        "name": "OPN Oracle API",
        "version": current_app.config["APP_VERSION"],
        "release": current_app.config["RELEASE"],
        "environment": current_app.config["APP_ENV"],
        "capabilities": capabilities,
    }
