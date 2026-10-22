"""Config store, base URL normalization, and XDG path tests."""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from clockify_launchers import constants
from clockify_launchers.domain.models import ManagementMode
from clockify_launchers.infrastructure.clockify_api import normalize_base_url, region_base_url
from clockify_launchers.infrastructure.config_store import (
    AppConfig,
    ConfigStore,
    atomic_write_text,
)
from clockify_launchers.infrastructure.xdg_paths import resolve_paths


class TestConfigStore:
    def test_missing_file_returns_defaults(self, tmp_path: Path) -> None:
        store = ConfigStore(tmp_path / "config.json")
        cfg = store.load()
        assert cfg.management_mode is ManagementMode.ASSISTED
        assert cfg.api_base_url == constants.DEFAULT_API_BASE_URL

    def test_roundtrip(self, tmp_path: Path) -> None:
        store = ConfigStore(tmp_path / "config.json")
        cfg = AppConfig()
        cfg.active_account_id = "acc-1"
        cfg.email = "a@b.c"
        cfg.active_workspace_id = "ws-1"
        cfg.management_mode = ManagementMode.AUTOPILOT
        cfg.onboarding_complete = True
        store.save(cfg)
        loaded = store.load()
        assert loaded.active_account_id == "acc-1"
        assert loaded.email == "a@b.c"
        assert loaded.active_workspace_id == "ws-1"
        assert loaded.management_mode is ManagementMode.AUTOPILOT
        assert loaded.onboarding_complete is True
        assert loaded.policy == cfg.policy
        assert loaded.notifications == cfg.notifications

    def test_malformed_json_preserved_and_defaults(self, tmp_path: Path) -> None:
        path = tmp_path / "config.json"
        path.write_text("{not json!!")
        cfg = ConfigStore(path).load()
        assert cfg.management_mode is ManagementMode.ASSISTED
        assert not path.exists()
        broken = list(tmp_path.glob("config.json.broken.*"))
        assert len(broken) == 1
        assert broken[0].read_text() == "{not json!!"

    def test_non_object_root_preserved(self, tmp_path: Path) -> None:
        path = tmp_path / "config.json"
        path.write_text("[1, 2, 3]")
        cfg = ConfigStore(path).load()
        assert cfg == AppConfig()
        assert list(tmp_path.glob("config.json.broken.*"))

    def test_unknown_mode_falls_back_to_assisted(self, tmp_path: Path) -> None:
        path = tmp_path / "config.json"
        path.write_text(json.dumps({"management_mode": "yolo"}))
        cfg = ConfigStore(path).load()
        assert cfg.management_mode is ManagementMode.ASSISTED

    def test_policy_values_validated_on_load(self, tmp_path: Path) -> None:
        path = tmp_path / "config.json"
        path.write_text(json.dumps({"policy": {"sync_interval_minutes": 1}}))
        cfg = ConfigStore(path).load()
        assert cfg.policy.sync_interval_minutes == 5

    def test_atomic_write_mode_0600(self, tmp_path: Path) -> None:
        path = tmp_path / "sub" / "f.txt"
        atomic_write_text(path, "hello")
        assert path.read_text() == "hello"
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert not list((tmp_path / "sub").glob(".*.tmp.*"))

    def test_indicator_prefs_roundtrip(self, tmp_path: Path) -> None:
        from clockify_launchers.infrastructure.config_store import IndicatorPrefs

        store = ConfigStore(tmp_path / "config.json")
        cfg = AppConfig()
        cfg.indicator = IndicatorPrefs(
            entry_time=False,
            project_day_total=True,
            project_week_total=True,
            day_total=False,
            week_total=True,
        )
        store.save(cfg)
        assert store.load().indicator == cfg.indicator

    def test_indicator_defaults_match_legacy_label(self, tmp_path: Path) -> None:
        """Fresh/absent config: entry time + daily total, like the old toggle on."""
        cfg = ConfigStore(tmp_path / "config.json").load()
        assert cfg.indicator.entry_time is True
        assert cfg.indicator.day_total is True
        assert cfg.indicator.project_day_total is False
        assert cfg.indicator.project_week_total is False
        assert cfg.indicator.week_total is False

    def test_legacy_show_times_false_migrates_to_all_off(self, tmp_path: Path) -> None:
        path = tmp_path / "config.json"
        path.write_text(json.dumps({"indicator_show_times": False}))
        cfg = ConfigStore(path).load()
        assert not cfg.indicator.needs_entries
        assert cfg.indicator.entry_time is False

    def test_legacy_show_times_true_migrates_to_defaults(self, tmp_path: Path) -> None:
        path = tmp_path / "config.json"
        path.write_text(json.dumps({"indicator_show_times": True}))
        cfg = ConfigStore(path).load()
        assert cfg.indicator.entry_time is True
        assert cfg.indicator.day_total is True


class TestNormalizeBaseUrl:
    def test_default_global(self) -> None:
        assert normalize_base_url("https://api.clockify.me/api") == "https://api.clockify.me/api"

    def test_trailing_slash_and_empty_path(self) -> None:
        assert normalize_base_url("https://api.clockify.me/") == "https://api.clockify.me/api"
        assert normalize_base_url("https://api.clockify.me") == "https://api.clockify.me/api"

    def test_api_v1_collapses_to_api(self) -> None:
        assert normalize_base_url("https://api.clockify.me/api/v1") == "https://api.clockify.me/api"

    def test_https_enforced(self) -> None:
        with pytest.raises(ValueError, match="HTTPS"):
            normalize_base_url("http://api.clockify.me/api")
        assert (
            normalize_base_url("http://localhost:8080/api", allow_http=True)
            == "http://localhost:8080/api"
        )

    def test_rejections(self) -> None:
        for bad in (
            "",
            "ftp://api.clockify.me/api",
            "https://user:pass@api.clockify.me/api",
            "https://api.clockify.me/api?x=1",
            "https://api.clockify.me/api#frag",
            "https://api.clockify.me/weird/path",
            "https:///api",
        ):
            with pytest.raises(ValueError):
                normalize_base_url(bad)

    def test_regional_urls(self) -> None:
        assert (
            normalize_base_url("https://euc1.api.clockify.me/api")
            == "https://euc1.api.clockify.me/api"
        )


class TestRegionBaseUrl:
    def test_none_or_empty_returns_default(self) -> None:
        assert region_base_url(None) == constants.DEFAULT_API_BASE_URL
        assert region_base_url("") == constants.DEFAULT_API_BASE_URL

    def test_known_prefixes(self) -> None:
        for region in constants.KNOWN_REGION_PREFIXES:
            assert region_base_url(region) == f"https://{region}.api.clockify.me/api"
        assert region_base_url(" EUC1 ") == "https://euc1.api.clockify.me/api"

    def test_unknown_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown region"):
            region_base_url("mars1")


class TestXdgPaths:
    def test_env_vars_respected(self, tmp_path: Path) -> None:
        env = {
            "HOME": str(tmp_path / "home"),
            "XDG_CONFIG_HOME": str(tmp_path / "cfg"),
            "XDG_STATE_HOME": str(tmp_path / "state"),
            "XDG_CACHE_HOME": str(tmp_path / "cache"),
            "XDG_DATA_HOME": str(tmp_path / "data"),
            "XDG_RUNTIME_DIR": str(tmp_path / "run"),
        }
        p = resolve_paths(env)
        name = constants.CONFIG_DIR_NAME
        assert p.config_dir == tmp_path / "cfg" / name
        assert p.state_dir == tmp_path / "state" / name
        assert p.cache_dir == tmp_path / "cache" / name
        assert p.runtime_dir == tmp_path / "run" / name
        assert p.applications_dir == tmp_path / "data" / "applications"
        assert p.icons_dir == tmp_path / "data" / constants.DATA_DIR_NAME / "icons"
        assert p.config_file == p.config_dir / "config.json"
        assert p.state_db == p.state_dir / "state.db"
        assert p.sync_lock == p.runtime_dir / "sync.lock"

    def test_defaults_when_unset(self, tmp_path: Path) -> None:
        env = {"HOME": str(tmp_path)}
        p = resolve_paths(env)
        name = constants.CONFIG_DIR_NAME
        assert p.config_dir == tmp_path / ".config" / name
        assert p.state_dir == tmp_path / ".local" / "state" / name
        assert p.cache_dir == tmp_path / ".cache" / name
        assert p.applications_dir == tmp_path / ".local" / "share" / "applications"

    def test_relative_paths_ignored(self, tmp_path: Path) -> None:
        env = {"HOME": str(tmp_path), "XDG_CONFIG_HOME": "relative/dir"}
        p = resolve_paths(env)
        assert p.config_dir == tmp_path / ".config" / constants.CONFIG_DIR_NAME

    def test_runtime_falls_back_to_cache(self, tmp_path: Path) -> None:
        env = {"HOME": str(tmp_path)}
        p = resolve_paths(env)
        assert p.runtime_dir == tmp_path / ".cache" / constants.CONFIG_DIR_NAME

    def test_ensure_private_dirs_mode_0700(self, tmp_path: Path) -> None:
        env = {"HOME": str(tmp_path)}
        p = resolve_paths(env)
        p.ensure_private_dirs()
        for d in (p.config_dir, p.state_dir, p.cache_dir, p.runtime_dir, p.icons_dir):
            assert d.is_dir()
            assert stat.S_IMODE(d.stat().st_mode) == 0o700
        assert p.applications_dir.is_dir()
