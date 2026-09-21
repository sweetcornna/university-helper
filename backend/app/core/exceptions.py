"""Custom exceptions for the application"""


class AppException(Exception):
    """Base exception for application errors"""

    status_code = 400


class UserAlreadyExistsError(AppException):
    """Raised when attempting to register a user that already exists"""

    status_code = 409


class InvalidCredentialsError(AppException):
    """Raised when login credentials are invalid"""

    status_code = 401


class DatabaseError(AppException):
    """Raised when a database operation fails"""

    status_code = 500


class ServiceUnavailableError(AppException):
    """A dependency (usually PostgreSQL) is not ready; the client may retry."""

    status_code = 503


class DatabaseNotInitializedError(ServiceUnavailableError):
    """The main schema or the tenant template database is missing."""


class TenantProvisioningError(ServiceUnavailableError):
    """Creating the per-user tenant database failed for an operational reason."""


class LocalProfileAuthUnavailable(AppException):
    """Register/login were called on the single-user desktop build."""

    status_code = 409
