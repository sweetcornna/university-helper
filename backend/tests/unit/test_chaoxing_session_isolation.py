"""Cross-tenant session isolation tests for the Chaoxing learning client.

Regression guard for the multi-tenant security bug where ``SessionManager`` was
a process-wide singleton holding ONE ``requests.Session`` (one cookie jar). With
uvicorn ``--workers 1`` every user shared that single session, so user B's login
cookies overwrote user A's in-flight session -> cross-account data leak.

The contract these tests enforce: each ``Chaoxing`` instance owns its own
``SessionManager`` / ``requests.Session``, so cookies set on one instance are
never visible on another.
"""

from app.services.course.chaoxing.client import Chaoxing, Account


def test_two_chaoxing_instances_do_not_share_a_session():
    """Cookies set on instance A's session must NOT leak into instance B."""
    cx_a = Chaoxing(Account("user-a", "pass-a"))
    cx_b = Chaoxing(Account("user-b", "pass-b"))

    session_a = cx_a.session_manager.get_session()
    session_b = cx_b.session_manager.get_session()

    # Distinct session objects per instance.
    assert session_a is not session_b

    # Simulate user A logging in: cookies land in A's jar only.
    session_a.cookies.set("_uid", "AAAA")

    # User B's session must stay clean -- no cross-tenant leak.
    assert session_b.cookies.get("_uid") is None


def test_services_share_their_owning_instance_session():
    """All services on one Chaoxing instance route through that instance's session."""
    cx = Chaoxing(Account("user", "pass"))

    instance_session = cx.session_manager.get_session()

    assert cx.auth_service.session_manager.get_session() is instance_session
    assert cx.course_service.session_manager.get_session() is instance_session
    assert cx.quiz_service.session_manager.get_session() is instance_session
    assert cx.video_service.session_manager.get_session() is instance_session
    assert cx.course_data_service.session_manager.get_session() is instance_session
    assert cx.work_legacy_service.session_manager.get_session() is instance_session
