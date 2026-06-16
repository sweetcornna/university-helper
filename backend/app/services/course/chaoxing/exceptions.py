class ChaoxingException(Exception):
    """Base exception for Chaoxing service errors"""


class LoginError(ChaoxingException):
    """Raised when login fails"""


class InputFormatError(ChaoxingException):
    """Raised when input format is invalid"""


class MaxRollBackExceeded(ChaoxingException):
    """Raised when maximum rollback attempts exceeded"""


class MaxRetryExceeded(ChaoxingException):
    """Raised when maximum retry attempts exceeded"""


class FontDecodeError(ChaoxingException):
    """Raised when font decoding fails"""


class AuthenticationError(ChaoxingException):
    """Raised when authentication fails"""


class TokenExpiredError(ChaoxingException):
    """Raised when token has expired"""


class InvalidTokenError(ChaoxingException):
    """Raised when token is invalid"""
