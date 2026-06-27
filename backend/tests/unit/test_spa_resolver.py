import sys

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


def test_resolver_repo_dev_path(monkeypatch, tmp_path):
    # Empty override, not frozen -> <repo-root>/frontend/dist when it exists.
    # frontend/dist is a gitignored build artifact (absent in a fresh CI checkout),
    # so point the resolver at a synthetic repo root with a real dist dir to make
    # this deterministic regardless of whether the SPA has been built.
    monkeypatch.setattr(main_mod.settings, "FRONTEND_DIST", "")
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    dist = tmp_path / "frontend" / "dist"
    dist.mkdir(parents=True)
    fake_main = tmp_path / "backend" / "app" / "main.py"
    fake_main.parent.mkdir(parents=True)
    fake_main.touch()
    monkeypatch.setattr(main_mod, "__file__", str(fake_main))
    result = main_mod.resolve_frontend_dist()
    assert result == dist
    assert result.is_dir()
