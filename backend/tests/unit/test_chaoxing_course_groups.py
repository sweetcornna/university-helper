"""Folder-grouped Chaoxing course listing.

The client already walked every course folder but threw the attribution away
when merging. These tests pin the folder tagging, the folder-name extraction
(including the fallback for ids that only appear inside script blobs), the
grouping with its trailing ungrouped bucket, and that the flat /courses payload
keeps its shape. Network is monkeypatched — no live Chaoxing.
"""

from unittest.mock import Mock, patch

import app.services.course.chaoxing.signin as signin_mod
from app.services.course.chaoxing.signin import (
    ROOT_COURSE_FOLDER_ID,
    ROOT_COURSE_FOLDER_NAME,
    ChaoxingSigninClient,
    _extract_course_folders,
    group_courses_by_folder,
)

INTERACTION_HTML = """
<ul class="file-list">
  <li fileid="10"><input class="rename-input" value="大二上" /></li>
  <li fileid="20" title="选修课"><span>选修课</span></li>
  <li fileid="30"><input class="rename-input" value="" /></li>
</ul>
<script>var cfg = {"courseFolderId": "40"};</script>
"""

ROOT_HTML = """
<div id="course_100_200"><a href="/p?cpi=300" title="Root Course">Root Course</a></div>
"""
FOLDER_10_HTML = """
<div id="course_101_201"><a href="/p?cpi=301" title="Folder 10 Course">Folder 10 Course</a></div>
"""
FOLDER_20_HTML = """
<div id="course_101_201"><a href="/p?cpi=301" title="Folder 10 Course">Folder 10 Course</a></div>
<div id="course_102_202"><a href="/p?cpi=302" title="Folder 20 Course">Folder 20 Course</a></div>
"""


def _client_with_folders():
    client = ChaoxingSigninClient()

    def _post(*args, **kwargs):
        folder_id = str((kwargs.get("data") or {}).get("courseFolderId", "0"))
        resp = Mock()
        resp.text = {"10": FOLDER_10_HTML, "20": FOLDER_20_HTML}.get(folder_id, ROOT_HTML)
        return resp

    return client, _post


# ---------------------------------------------------------------------------
# Folder names
# ---------------------------------------------------------------------------


def test_folder_names_come_from_the_markup_with_a_fallback():
    folders = _extract_course_folders(INTERACTION_HTML)
    names = {folder["id"]: folder["name"] for folder in folders}

    assert names["10"] == "大二上"  # rename input value
    assert names["20"] == "选修课"  # title attribute
    # No usable label in the markup / id only present in a script blob: use the
    # generic name rather than fabricate one.
    assert names["30"] == "文件夹 30"
    assert names["40"] == "文件夹 40"


def test_folder_extraction_survives_markup_without_folders():
    assert _extract_course_folders("<html><body>no folders here</body></html>") == []


# ---------------------------------------------------------------------------
# Folder tagging on the flat list
# ---------------------------------------------------------------------------


def test_get_courses_tags_each_course_with_its_source_folder():
    client, _post = _client_with_folders()

    with (
        patch.object(client.session, "post", side_effect=_post),
        patch.object(client.session, "get", return_value=Mock(text=INTERACTION_HTML)),
    ):
        courses = client.get_courses()

    tagged = {course["courseId"]: (course["folderId"], course["folderName"]) for course in courses}
    assert tagged["100"] == (ROOT_COURSE_FOLDER_ID, ROOT_COURSE_FOLDER_NAME)
    assert tagged["101"] == ("10", "大二上")
    assert tagged["102"] == ("20", "选修课")


def test_get_courses_keeps_its_existing_shape_and_dedupe():
    client, _post = _client_with_folders()

    with (
        patch.object(client.session, "post", side_effect=_post),
        patch.object(client.session, "get", return_value=Mock(text=INTERACTION_HTML)),
    ):
        courses = client.get_courses()

    # Duplicated course (folder 10 + folder 20) collapses to its first folder.
    assert len({(course["courseId"], course["classId"]) for course in courses}) == len(courses) == 3
    for course in courses:
        assert {"id", "courseId", "classId", "cpi", "name", "courseName"} <= set(course)
    first = next(course for course in courses if course["courseId"] == "100")
    assert first["id"] == "100_200_300"
    assert first["cpi"] == "300"
    assert first["name"] == first["courseName"] == "Root Course"


# ---------------------------------------------------------------------------
# Grouping
# ---------------------------------------------------------------------------


def test_grouping_puts_the_ungrouped_bucket_last():
    groups = group_courses_by_folder(
        [
            {"courseId": "100", "folderId": "0", "folderName": ROOT_COURSE_FOLDER_NAME},
            {"courseId": "101", "folderId": "10", "folderName": "大二上"},
            {"courseId": "102", "folderId": "20", "folderName": "选修课"},
            {"courseId": "103", "folderId": "10", "folderName": "大二上"},
        ]
    )

    assert [(group["id"], group["name"]) for group in groups] == [
        ("10", "大二上"),
        ("20", "选修课"),
        (ROOT_COURSE_FOLDER_ID, ROOT_COURSE_FOLDER_NAME),
    ]
    assert [course["courseId"] for course in groups[0]["courses"]] == ["101", "103"]
    assert [course["courseId"] for course in groups[-1]["courses"]] == ["100"]
    for group in groups:
        assert set(group) == {"id", "name", "courses"}


def test_grouping_defaults_untagged_courses_to_the_ungrouped_bucket():
    groups = group_courses_by_folder([{"courseId": "100"}])

    assert len(groups) == 1
    assert groups[0]["id"] == ROOT_COURSE_FOLDER_ID
    assert groups[0]["name"] == ROOT_COURSE_FOLDER_NAME


def test_grouping_omits_the_ungrouped_bucket_when_every_course_is_filed():
    groups = group_courses_by_folder([{"courseId": "101", "folderId": "10", "folderName": "大二上"}])

    assert [group["id"] for group in groups] == ["10"]


def test_manager_groups_the_courses_it_returns(monkeypatch):
    manager = signin_mod.ChaoxingSigninManager.__new__(signin_mod.ChaoxingSigninManager)
    monkeypatch.setattr(
        signin_mod.ChaoxingSigninManager,
        "get_courses",
        lambda self, user_id: [
            {"courseId": "101", "folderId": "10", "folderName": "大二上"},
            {"courseId": "100", "folderId": "0", "folderName": ROOT_COURSE_FOLDER_NAME},
        ],
    )

    groups = manager.get_grouped_courses("user-1")

    assert [group["id"] for group in groups] == ["10", ROOT_COURSE_FOLDER_ID]


def test_manager_returns_no_groups_without_a_session(monkeypatch):
    manager = signin_mod.ChaoxingSigninManager.__new__(signin_mod.ChaoxingSigninManager)
    monkeypatch.setattr(signin_mod.ChaoxingSigninManager, "get_courses", lambda self, user_id: [])

    assert manager.get_grouped_courses("user-1") == []


# ---------------------------------------------------------------------------
# API contract
# ---------------------------------------------------------------------------


def test_grouped_endpoint_matches_the_contract(monkeypatch):
    from fastapi.testclient import TestClient

    from tests.conftest import build_app

    courses = [
        {
            "id": "101_201_301",
            "courseId": "101",
            "classId": "201",
            "cpi": "301",
            "name": "Folder Course",
            "courseName": "Folder Course",
            "folderId": "10",
            "folderName": "大二上",
        },
        {
            "id": "100_200_300",
            "courseId": "100",
            "classId": "200",
            "cpi": "300",
            "name": "Root Course",
            "courseName": "Root Course",
            "folderId": "0",
            "folderName": ROOT_COURSE_FOLDER_NAME,
        },
    ]

    with build_app("local", ENFORCE_HTTPS="false") as app:
        import app.api.v1.chaoxing as chaoxing_mod

        monkeypatch.setattr(chaoxing_mod.signin_manager, "get_courses", lambda user_id: courses)
        client = TestClient(app, base_url="http://localhost")
        grouped = client.get("/api/v1/chaoxing/courses/grouped")
        flat = client.get("/api/v1/chaoxing/courses")

    assert grouped.status_code == 200
    body = grouped.json()
    assert body["status"] == "success"
    assert [(group["id"], group["name"]) for group in body["groups"]] == [
        ("10", "大二上"),
        ("0", ROOT_COURSE_FOLDER_NAME),
    ]
    assert body["groups"][0]["courses"][0]["courseId"] == "101"

    # The flat endpoint the sign-in page uses keeps its shape.
    assert flat.status_code == 200
    flat_body = flat.json()
    assert flat_body["status"] is True
    assert flat_body["data"] == flat_body["courses"] == courses
