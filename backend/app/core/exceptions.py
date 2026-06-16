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
