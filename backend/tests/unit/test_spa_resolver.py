import sys
from pathlib import Path

import app.main as main_mod


def test_resolver_explicit_existing_dir(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    dist.mkdir()
    monkeypatch.setattr(main_mod.settings, "FRONTEND_DIST", str(dist))
    assert main_mod.resolve_frontend_dist() == dist


def test_resolver_explicit_missing_dir_returns_none(tmp_path, monkeypatch):
    # Authoritative override pointing at a non-existent path -> None (no fallback),
    # which is how the "server / no SPA" state is forced deterministically.
    monkeypatch.setattr(main_mod.settings, "FRONTEND_DIST", str(tmp_path / "nope"))
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    assert main_mod.resolve_frontend_dist() is None


def test_resolver_meipass_bundle(tmp_path, monkeypatch):
    bundle = tmp_path / "frontend" / "dist"
    bundle.mkdir(parents=True)
    monkeypatch.setattr(main_mod.settings, "FRONTEND_DIST", "")
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert main_mod.resolve_frontend_dist() == bundle


def test_resolver_repo_dev_path(monkeypatch):
    # Empty override, not frozen -> <repo-root>/frontend/dist, which exists in the checkout.
    monkeypatch.setattr(main_mod.settings, "FRONTEND_DIST", "")
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    expected = Path(main_mod.__file__).resolve().parents[2] / "frontend" / "dist"
    result = main_mod.resolve_frontend_dist()
    assert result == expected
    assert result.is_dir()
