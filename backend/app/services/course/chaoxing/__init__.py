"""Chaoxing service package exports."""

from .signin import ChaoxingSigninClient, ChaoxingSigninManager, signin_manager

Chaoxing = None
Account = None
StudyResult = None
CourseProcessor = None

try:  # Optional legacy exports for environments that include full dependencies.
    from .client import Account, Chaoxing, StudyResult  # type: ignore[assignment]
except Exception:
    pass

try:  # Optional legacy export.
    from .learning import CourseProcessor  # type: ignore[assignment]
except Exception:
    pass

__all__ = [
    "ChaoxingSigninClient",
    "ChaoxingSigninManager",
    "signin_manager",
    "Chaoxing",
    "Account",
    "StudyResult",
    "CourseProcessor",
]
