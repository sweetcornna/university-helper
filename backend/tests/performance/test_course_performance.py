import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from app.main import app

    return TestClient(app, base_url="http://localhost")


@pytest.fixture
def mock_learning_manager():
    manager = MagicMock()
    manager.start_task.return_value = "task123"
    manager.get_task.return_value = {
        "status": "running",
        "message": "Task is running",
        "progress": {"total": 1, "completed": 0, "failed": 0, "current": 0},
        "current_task": "preparing",
    }
    with patch("app.api.v1.course._get_learning_manager", return_value=manager):
        yield manager


class TestCoursePerformance:
    def test_course_start_response_time(self, client, auth_headers, mock_learning_manager):
        """Course start should complete within acceptable time."""
        start = time.perf_counter()
        response = client.post(
            "/api/v1/course/start",
            headers=auth_headers,
            json={
                "platform": "chaoxing",
                "username": "testuser",
                "password": "testpass",
            },
        )
        duration = time.perf_counter() - start

        assert response.status_code == 200
        assert response.json()["task_id"] == "task123"
        assert duration < 3.0

    def test_concurrent_course_requests(self, client, auth_headers, mock_learning_manager):
        """Handle concurrent course start requests."""
        def start_course():
            return client.post(
                "/api/v1/course/start",
                headers=auth_headers,
                json={
                    "platform": "chaoxing",
                    "username": "testuser",
                    "password": "testpass",
                },
            )

        with ThreadPoolExecutor(max_workers=5) as executor:
            results = list(executor.map(lambda _: start_course(), range(5)))

        assert all(response.status_code == 200 for response in results)

    def test_status_check_response_time(self, client, auth_headers, mock_learning_manager):
        """Status check should be fast."""
        start = time.perf_counter()
        response = client.get(
            "/api/v1/course/status/task123",
            headers=auth_headers,
        )
        duration = time.perf_counter() - start

        assert response.status_code == 200
        assert response.json()["task_id"] == "task123"
        assert duration < 0.5
