"""Static guards for the Chaoxing encrypted-font mapping resource."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_server_image_fetches_pinned_font_map_with_checksum():
    dockerfile = (REPO_ROOT / "Dockerfile.server").read_text(encoding="utf-8")
    assert "Samueli924/chaoxing/556ccc1556823ff5c8dc1ac4ad26307217b25795/resource/font_map_table.json" in dockerfile
    assert "792786beba0acc8bdfe4ff7e6f8624bf69e8d4d7d9a72cb6a9453c4ff6cd87e7" in dockerfile
    assert "hashlib.sha256(payload).hexdigest()" in dockerfile
    assert "/srv/backend/resource/font_map_table.json" in dockerfile


def test_font_map_is_not_vendored_in_repository():
    assert not (REPO_ROOT / "backend" / "resource" / "font_map_table.json").exists()
