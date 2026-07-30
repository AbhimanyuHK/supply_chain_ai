"""Domain exception hierarchy and FastAPI exception handlers."""

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from loguru import logger


class DomainError(Exception):
    """Base class for all application (non-framework) errors."""

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    error_code: str = "domain_error"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class NotFoundError(DomainError):
    """Raised when a requested entity does not exist."""

    status_code = status.HTTP_404_NOT_FOUND
    error_code = "not_found"


class ValidationError(DomainError):
    """Raised when input fails domain-level validation (beyond schema validation)."""

    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    error_code = "validation_error"


class ConstraintViolationError(DomainError):
    """Raised when a proposed plan/shipment violates a business or physical constraint.

    Reused by the Constraint Validation Agent (a later module) to report violations
    such as insufficient inventory, capacity overruns, or lead-time breaches.
    """

    status_code = status.HTTP_409_CONFLICT
    error_code = "constraint_violation"


class ExternalServiceError(DomainError):
    """Raised when a dependency (Groq, HuggingFace, database) is unavailable or errors."""

    status_code = status.HTTP_502_BAD_GATEWAY
    error_code = "external_service_error"


def _error_response(status_code: int, error_code: str, message: str, details: dict[str, Any]) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error_code": error_code, "message": message, "details": details},
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Register handlers so every error returns a consistent JSON body."""

    @app.exception_handler(DomainError)
    async def handle_domain_error(request: Request, exc: DomainError) -> JSONResponse:
        logger.warning(
            "Domain error on {method} {path}: {code} - {message}",
            method=request.method,
            path=request.url.path,
            code=exc.error_code,
            message=exc.message,
        )
        return _error_response(exc.status_code, exc.error_code, exc.message, exc.details)

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.exception(
            "Unhandled error on {method} {path}", method=request.method, path=request.url.path
        )
        return _error_response(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "internal_server_error",
            "An unexpected error occurred.",
            {},
        )
