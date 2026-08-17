"""Auth-aware OpenAPI generation for the Control Plane API (E11-S2 Task 5).

Publishes the three credential mechanisms as OpenAPI security schemes and
derives each protected operation's ``x-autodev-required-scope`` extension
directly from its :func:`~backend.api.authorization.requires_scope`
declaration — there is deliberately no second, hand-maintained scope
registry to drift out of sync with the real enforcement.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from backend.api.authorization import (
    get_authorization_requirement,
    is_public_endpoint,
    iter_api_routes,
)

SECURITY_SCHEMES: dict[str, Any] = {
    "oidcBearer": {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "JWT",
        "description": "OIDC-issued bearer JWT, validated against the configured JWKS.",
    },
    "serviceBearer": {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "adk_live_<key-id>_<secret>",
        "description": "Governed service credential minted via `autodev auth service-key create`.",
    },
    "sessionCookie": {
        "type": "apiKey",
        "in": "cookie",
        "name": "autodev_session",
        "description": "Browser session established by the OIDC PKCE login flow.",
    },
}

_HTTP_METHODS = frozenset({"get", "post", "put", "delete", "patch", "options", "head"})


def install_custom_openapi(app: FastAPI) -> None:
    """Replace ``app.openapi`` with one that adds auth metadata to every operation.

    Args:
        app: The FastAPI application to patch. Idempotent to call more than
            once; the underlying :func:`fastapi.openapi.utils.get_openapi`
            call is still only made once per process thanks to the app's
            own ``openapi_schema`` cache.
        """

    def custom_openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(
            title=app.title,
            version=app.version,
            routes=app.routes,
        )
        schema.setdefault("components", {}).setdefault("securitySchemes", {}).update(
            SECURITY_SCHEMES
        )
        _annotate_operations(app, schema)
        app.openapi_schema = schema
        return schema

    app.openapi = custom_openapi  # type: ignore[method-assign]


def _annotate_operations(app: FastAPI, schema: dict[str, Any]) -> None:
    """Merge each route's public/scope metadata into its OpenAPI operation.

    Args:
        app: The FastAPI application whose routes are the source of truth.
        schema: The in-progress OpenAPI document, mutated in place.
    """
    routes_by_path_method: dict[tuple[str, str], Any] = {}
    for route in iter_api_routes(app.routes):
        # OpenAPI path keys strip converter type hints (`{id:path}` ->
        # `{id}`); `route.path` keeps them, `route.path_format` doesn't.
        schema_path = getattr(route, "path_format", route.path)
        for method in route.methods or set():
            routes_by_path_method[(schema_path, method.lower())] = route

    for path, path_item in schema.get("paths", {}).items():
        for method, operation in path_item.items():
            if method not in _HTTP_METHODS or not isinstance(operation, dict):
                continue
            matched_route = routes_by_path_method.get((path, method))
            if matched_route is None:
                continue
            endpoint = matched_route.endpoint
            if is_public_endpoint(endpoint):
                operation["x-autodev-public"] = True
                continue
            requirement = get_authorization_requirement(endpoint)
            if requirement is None:
                continue
            operation["x-autodev-required-scope"] = requirement.scope
            operation["security"] = [
                {"oidcBearer": []},
                {"serviceBearer": []},
                {"sessionCookie": []},
            ]


def protected_operations_without_scope(schema: dict[str, Any]) -> list[str]:
    """List every ``/v2`` operation lacking a scope or public marker.

    Args:
        schema: An OpenAPI document produced by :func:`install_custom_openapi`
            (typically ``app.openapi()``).

    Returns:
        ``"METHOD path"`` strings for every offending operation.
    """
    missing = []
    for path, path_item in schema.get("paths", {}).items():
        if not path.startswith("/v2") or not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if method not in _HTTP_METHODS or not isinstance(operation, dict):
                continue
            if operation.get("x-autodev-public"):
                continue
            if "x-autodev-required-scope" not in operation:
                missing.append(f"{method.upper()} {path}")
    return sorted(missing)


__all__ = [
    "SECURITY_SCHEMES",
    "install_custom_openapi",
    "protected_operations_without_scope",
]
