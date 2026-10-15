"""Issue #259: how the config root is chosen and checked.

The resolver takes the environment as an argument, so its tests never
touch ``os.environ``.
"""

import re

import pytest

from memanga.config import (CONFIG_DIR_ENV, Config, ConfigDirError,
                            default_config_dir, ensure_config_dir,
                            resolve_config_dir)
from memanga.state import State


class TestResolveConfigDir:
    def test_nothing_selected_means_default(self):
        assert resolve_config_dir(None, environ={}) is None

    def test_env_var_selects_root(self, tmp_path):
        env = {CONFIG_DIR_ENV: str(tmp_path / "env")}
        assert resolve_config_dir(None, environ=env) == tmp_path / "env"

    def test_flag_wins_over_env_var(self, tmp_path):
        env = {CONFIG_DIR_ENV: str(tmp_path / "env")}
        assert resolve_config_dir(str(tmp_path / "flag"), environ=env) == tmp_path / "flag"

    def test_empty_env_var_counts_as_unset(self):
        assert resolve_config_dir(None, environ={CONFIG_DIR_ENV: ""}) is None
        assert resolve_config_dir(None, environ={CONFIG_DIR_ENV: "  "}) is None

    @pytest.mark.parametrize("value", ["", "   "])
    def test_empty_flag_is_rejected(self, tmp_path, value):
        env = {CONFIG_DIR_ENV: str(tmp_path / "env")}
        with pytest.raises(ConfigDirError, match="--config-dir"):
            resolve_config_dir(value, environ=env)

    def test_relative_path_is_made_absolute(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert resolve_config_dir("portable", environ={}) == tmp_path / "portable"

    def test_user_home_is_expanded(self, isolated_home):
        assert resolve_config_dir("~/mm", environ={}) == isolated_home / "mm"

    def test_file_is_rejected_naming_the_source(self, tmp_path):
        target = tmp_path / "config.yaml"
        target.write_text("manga: []\n")
        with pytest.raises(ConfigDirError, match="--config-dir.*not a directory"):
            resolve_config_dir(str(target), environ={})
        with pytest.raises(ConfigDirError, match=f"{CONFIG_DIR_ENV}.*not a directory"):
            resolve_config_dir(None, environ={CONFIG_DIR_ENV: str(target)})

    def test_resolving_creates_nothing(self, tmp_path):
        resolve_config_dir(str(tmp_path / "a" / "b"), environ={})
        assert not (tmp_path / "a").exists()


class TestDefaultRoot:
    def test_default_is_home_config(self, isolated_home):
        assert default_config_dir() == isolated_home / ".config" / "memanga"

    def test_config_and_state_share_the_default(self, isolated_home):
        assert Config().config_dir == State().config_dir == default_config_dir()

    def test_config_and_state_share_an_explicit_root(self, tmp_path):
        root = tmp_path / "root"
        config, state = Config(root), State(root)
        assert config.config_path == root / "config.yaml"
        assert state.state_path == root / "state.json"


class TestEnsureConfigDir:
    def test_creates_missing_root_and_leaves_nothing_behind(self, tmp_path):
        root = tmp_path / "a" / "b"
        assert ensure_config_dir(root) == root
        assert root.is_dir()
        assert list(root.iterdir()) == []

    def test_none_means_default(self, isolated_home):
        assert ensure_config_dir(None) == default_config_dir()

    def test_parent_is_a_file(self, tmp_path):
        blocker = tmp_path / "blocker"
        blocker.write_text("")
        with pytest.raises(ConfigDirError, match="cannot use config directory"):
            ensure_config_dir(blocker / "memanga")

    def test_unwritable_root_is_rejected(self, tmp_path, refuse_writes_in):
        root = tmp_path / "ro"
        root.mkdir()
        refuse_writes_in(root)
        message = f"cannot use config directory {root}: Permission denied"
        with pytest.raises(ConfigDirError, match=re.escape(message)):
            ensure_config_dir(root)

    def test_read_only_directory_is_rejected(self, read_only_dir):
        with pytest.raises(ConfigDirError, match="Permission denied"):
            ensure_config_dir(read_only_dir)
        assert list(read_only_dir.iterdir()) == []
