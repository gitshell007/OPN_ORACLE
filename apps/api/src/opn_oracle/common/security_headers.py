"""Environment-aware security headers for API responses."""

from __future__ import annotations

from flask import Flask, Response, request

API_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"


def init_security_headers(app: Flask) -> None:
    @app.after_request
    def attach_security_headers(response: Response) -> Response:
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Permissions-Policy", "accelerometer=(), camera=(), geolocation=(), microphone=()"
        )
        # The API never renders active application content. Swagger stays usable in local/test.
        if app.config["APP_ENV"] == "production":
            response.headers.setdefault("Content-Security-Policy", API_CSP)
        if request.path.startswith(("/api/", "/internal/")):
            response.headers.setdefault("Cache-Control", "private, no-store, max-age=0")
        # HSTS is an explicit infrastructure gate and is emitted only after HTTPS is confirmed.
        if app.config["HSTS_ENABLED"] and request.is_secure:
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response
