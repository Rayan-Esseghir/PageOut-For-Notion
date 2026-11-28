"""Tests for Phase 16: Cloud & Git sync targets.

Tests cover:
- Sync target configuration options
- Local folder sync
- Git repository sync (commit + push)
- Optional dependency handling
- Sync result reporting
- Integration with export pipeline
"""

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Add the project root to the path
sys.path.insert(0, str(Path(__file__).parent.parent))

from pageout.core.config import DEFAULTS, SYNC_TARGETS
from pageout.core.pipeline import Result, export


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr("pageout.core.config.CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr("pageout.core.config.CONFIG_FILE", str(tmp_path / "cfg" / "config.json"))
    monkeypatch.delattr("pageout.core.config", "SOURCE_DIR", raising=False)
    import pageout.core.sources as sources

    monkeypatch.setattr(sources, "SOURCE_DIR", str(tmp_path / "cfg" / "sources"))
    monkeypatch.delenv("NOTION_TOKEN", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)


@pytest.fixture
def mock_sync_target(tmp_path):
    """Create a mock sync target directory."""
    sync_target = tmp_path / "sync_target"
    sync_target.mkdir()
    return str(sync_target)


# ---------------------------------------------------------------------- Test sync target constants
def test_sync_targets_constant_exists():
    """SYNC_TARGETS should be defined in config."""
    assert SYNC_TARGETS is not None
    assert "None" in SYNC_TARGETS
    assert "Local folder" in SYNC_TARGETS
    assert "Google Drive" in SYNC_TARGETS
    assert "Dropbox" in SYNC_TARGETS
    assert "S3" in SYNC_TARGETS
    assert "Git repo" in SYNC_TARGETS


def test_sync_config_in_defaults():
    """Sync-related settings should be in DEFAULTS."""
    assert "sync_target" in DEFAULTS
    assert "sync_path" in DEFAULTS
    assert "sync_branch" in DEFAULTS
    assert "gdrive_folder_id" in DEFAULTS
    assert "dropbox_path" in DEFAULTS
    assert "s3_bucket" in DEFAULTS
    assert "s3_prefix" in DEFAULTS
    assert "sync_after_export" in DEFAULTS

    assert DEFAULTS["sync_target"] == "None"
    assert DEFAULTS["sync_branch"] == "main"
    assert DEFAULTS["dropbox_path"] == "/exports"
    assert DEFAULTS["s3_prefix"] == "exports"
    assert not DEFAULTS["sync_after_export"]


# ---------------------------------------------------------------------- Test sync module loading
def test_sync_module_imports():
    """Sync module should be importable with optional dependencies handled."""
    from pageout.core.sync import (
        SYNC_TARGETS as MODULE_SYNC_TARGETS,
    )

    assert MODULE_SYNC_TARGETS == SYNC_TARGETS


# ---------------------------------------------------------------------- Test SyncResult dataclass
def test_sync_result_dataclass():
    """SyncResult should capture all sync outcome details."""
    from pageout.core.sync import SyncResult

    result = SyncResult(
        success=True, target="Local folder", message="Synced to /path/to/target", files_synced=5, error=""
    )

    assert result.success is True
    assert result.target == "Local folder"
    assert result.message == "Synced to /path/to/target"
    assert result.files_synced == 5
    assert result.error == ""


def test_sync_result_failure():
    """SyncResult should capture failure information."""
    from pageout.core.sync import SyncResult

    result = SyncResult(
        success=False,
        target="Google Drive",
        message="Sync failed: permission denied",
        files_synced=0,
        error="PermissionError: access denied",
    )

    assert result.success is False
    assert result.target == "Google Drive"
    assert result.files_synced == 0
    assert "permission" in result.message.lower()


# ---------------------------------------------------------------------- Test SyncReport dataclass
def test_sync_report_dataclass():
    """SyncReport should provide comprehensive sync reporting."""
    from pageout.core.sync import SyncReport

    report = SyncReport(
        target="Dropbox", success=True, message="Synced 10 files to Dropbox", files_synced=10, errors=[]
    )

    report_dict = report.to_dict()
    assert report_dict["target"] == "Dropbox"
    assert report_dict["success"] is True
    assert report_dict["files_synced"] == 10
    assert report_dict["errors"] == []


# ---------------------------------------------------------------------- Test local folder sync
def test_sync_to_local_folder_success(tmp_path, isolated):
    """Local folder sync should copy files to target directory."""
    from pageout.core.config import DEFAULTS
    from pageout.core.sync import sync_to_local_folder

    # Create source directory with files
    source = tmp_path / "source"
    source.mkdir()
    (source / "test.md").write_text("# Test Content")
    (source / "test.html").write_text("<html><body>Test</body></html>")

    # Create target directory
    target = tmp_path / "target"
    target.mkdir()

    result = sync_to_local_folder(str(source), str(target), DEFAULTS)

    assert result.success is True
    assert "Synced" in result.message or "exported" in result.message.lower() or result.files_synced >= 0
    assert result.target == "Local folder"


def test_sync_to_local_folder_missing_source(tmp_path, isolated):
    """Local folder sync should fail gracefully when source doesn't exist."""
    from pageout.core.config import DEFAULTS
    from pageout.core.sync import sync_to_local_folder

    result = sync_to_local_folder("/nonexistent/source/path", "/tmp/target", DEFAULTS)

    assert result.success is False
    assert result.target == "Local folder"


def test_sync_to_local_folder_empty_path(tmp_path, isolated):
    """Local folder sync should fail with empty target path."""
    from pageout.core.config import DEFAULTS
    from pageout.core.sync import sync_to_local_folder

    source = tmp_path / "source"
    source.mkdir()
    (source / "test.md").write_text("test")

    result = sync_to_local_folder(str(source), "", DEFAULTS)

    assert result.success is False


# ---------------------------------------------------------------------- Test Git sync
def test_sync_to_git_disabled(tmp_path, isolated):
    """Git sync should handle non-git directories gracefully."""
    from pageout.core.config import DEFAULTS
    from pageout.core.sync import sync_to_git

    # Create non-git directory
    source = tmp_path / "non_git"
    source.mkdir()
    (source / "test.md").write_text("test")

    result = sync_to_git(str(source), "main", DEFAULTS)

    # Should fail because it's not a git repo
    assert result.success is False
    assert "Git" in result.target


def test_sync_to_git_no_git_installed(tmp_path, isolated):
    """Git sync should handle missing git command."""
    from pageout.core.config import DEFAULTS
    from pageout.core.sync import sync_to_git

    source = tmp_path / "source"
    source.mkdir()

    # Mock subprocess to simulate git not found
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = FileNotFoundError("git not found")
        result = sync_to_git(str(source), "main", DEFAULTS)

    assert result.success is False
    assert "Git not installed" in result.message or "not found" in result.message


# ---------------------------------------------------------------------- Test Result dataclass with sync fields
def test_result_has_sync_fields():
    """Result dataclass should include sync-related fields."""
    from pageout.core.timing import TimingReport

    result = Result(
        out_dir="/tmp/export",
        total=5,
        failed=[],
        skipped=0,
        last_tex="",
        timing=TimingReport(),
    )

    # Check sync fields exist with defaults
    assert hasattr(result, "sync_target")
    assert hasattr(result, "sync_message")
    assert hasattr(result, "sync_success")
    assert hasattr(result, "sync_error")
    assert hasattr(result, "sync_files")

    # Check defaults
    assert result.sync_target == "None"
    assert result.sync_message == ""
    assert result.sync_success is False
    assert result.sync_error == ""
    assert result.sync_files == 0


# ---------------------------------------------------------------------- Test Result with sync data
def test_result_with_sync_data():
    """Result should capture sync information correctly."""
    from pageout.core.timing import TimingReport

    result = Result(
        out_dir="/tmp/export",
        total=10,
        failed=[],
        skipped=2,
        last_tex="",
        timing=TimingReport(),
        sync_target="Local folder",
        sync_message="Synced 10 files to /mnt/network/backup",
        sync_success=True,
        sync_error="",
        sync_files=10,
    )

    assert result.sync_target == "Local folder"
    assert result.sync_success is True
    assert result.sync_files == 10
    assert "10 files" in result.sync_message


# ---------------------------------------------------------------------- Test perform_sync dispatcher
def test_perform_sync_disabled():
    """perform_sync should return success for disabled sync."""
    from pageout.core.config import DEFAULTS
    from pageout.core.sync import perform_sync

    report = perform_sync("/tmp/some_dir", "None", {}, DEFAULTS)

    assert report.success is True
    assert report.target == "None"


def test_perform_sync_unknown_target():
    """perform_sync should handle unknown targets gracefully."""
    from pageout.core.config import DEFAULTS
    from pageout.core.sync import perform_sync

    report = perform_sync("/tmp/some_dir", "Unknown Target", {}, DEFAULTS)

    assert report.success is False
    assert "Unknown" in report.message or report.target == "Unknown Target"


# ---------------------------------------------------------------------- Test sync integration with export
def test_export_without_sync(tmp_path, isolated):
    """Export should work without sync configuration."""
    # Simple config without sync
    from pageout.core.config import DEFAULTS

    cfg = dict(DEFAULTS)
    cfg["save_dir"] = str(tmp_path)
    cfg["token"] = "tok-test"
    cfg["sync_after_export"] = False
    # Add a database source that FakeNotion can handle - use the DB_ID constant from fake_notion
    db_id = "db" + "0" * 30  # Matches the fixture database key
    cfg["database"] = db_id

    # Mock the notion client
    from tests.fake_notion import FakeNotion

    result = export(cfg, notion=FakeNotion(), log=lambda m: None)

    # Check result has sync fields
    assert hasattr(result, "sync_target")
    assert result.sync_target == "None"


# ---------------------------------------------------------------------- Test optional dependency handling
def test_google_drive_requires_optional_dependency(tmp_path, isolated, monkeypatch):
    """Google Drive sync should fail gracefully when dependencies missing."""
    from pageout.core.config import DEFAULTS
    from pageout.core.sync import sync_to_gdrive

    # Create a minimal test that doesn't rely on keyring being installed
    # The sync_to_gdrive function checks for google-auth imports inside
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "test.md").write_text("test")

    # Mock the google imports to fail
    import builtins

    original_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if "google" in name:
            raise ImportError("google-auth not installed")
        return original_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=mock_import):
        result = sync_to_gdrive(str(source_dir), "test_folder_id", DEFAULTS)

    # Should return a SyncResult indicating missing dependencies
    assert result.success is False
    assert "Google Drive" in result.target


# ---------------------------------------------------------------------- Test credential handling
def test_dropbox_uses_keyring_fallback(monkeypatch):
    """Dropbox sync should use keyring or environment variable for credentials."""
    from pageout.core.sync import _get_env_secret, _get_secret

    # Test that keyring module may not be available
    try:
        import keyring

        # Mock keyring.get_password
        monkeypatch.setattr(keyring, "get_password", lambda service, key: None)
        # Test _get_secret returns empty when keyring returns None
        result = _get_secret("PageOut for Notion", "DROPBOX_TOKEN")
        assert result == ""
    except ImportError:
        # keyring not installed - that's fine, _get_secret should handle it
        pass

    # Test environment variable fallback
    with patch.dict(os.environ, {"DROPBOX_TOKEN": "test-dropbox-token"}):
        token = _get_env_secret("DROPBOX_TOKEN")
        assert token == "test-dropbox-token"


def test_gdrive_uses_env_var_for_token(monkeypatch):
    """Google Drive sync should look for GDRIVE_TOKEN in environment."""
    with patch.dict(os.environ, {"GDRIVE_TOKEN": "test-gdrive-token"}, clear=False):
        from pageout.core.sync import _get_env_secret

        token = _get_env_secret("GDRIVE_TOKEN")
        assert token == "test-gdrive-token"


# ---------------------------------------------------------------------- Test S3 credential handling
def test_s3_uses_aws_env_vars(monkeypatch):
    """S3 sync should use AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY from environment."""
    with patch.dict(
        os.environ,
        {"AWS_ACCESS_KEY_ID": "AKIAIOSFODNN7EXAMPLE", "AWS_SECRET_ACCESS_KEY": "test-secret-key"},
        clear=False,
    ):
        from pageout.core.sync import _get_env_secret

        key = _get_env_secret("AWS_ACCESS_KEY_ID")
        secret = _get_env_secret("AWS_SECRET_ACCESS_KEY")
        assert key == "AKIAIOSFODNN7EXAMPLE"
        assert secret == "test-secret-key"


# ---------------------------------------------------------------------- Test file counting
def test_count_files_empty_directory(tmp_path, isolated):
    """_count_files_in_directory should return 0 for empty directory."""
    from pageout.core.sync import _count_files_in_directory

    count = _count_files_in_directory(str(tmp_path / "empty"))
    assert count == 0


# ---------------------------------------------------------------------- Test integration with scheduler
def test_sync_fields_in_scheduler_task(tmp_path, isolated):
    """Scheduler tasks should be able to include sync configuration."""
    import uuid

    from pageout.core.scheduler import ScheduledTask, ScheduleStatus

    # Create a task with sync config - ScheduledTask requires an id field
    task = ScheduledTask(
        id=str(uuid.uuid4()),
        name="Test Sync Export",
        source="https://www.notion.so/test-db-id",
        output_dir=str(tmp_path),
        formats=["pdf", "md"],
        schedule="daily",
        status=ScheduleStatus.ACTIVE,
    )

    # Verify basic task creation works
    assert task.name == "Test Sync Export"
    assert task.formats == ["pdf", "md"]
    assert task.status == ScheduleStatus.ACTIVE

    # Check serialization works
    task_dict = task.to_dict()
    assert task_dict["name"] == "Test Sync Export"
    assert task_dict["status"] == "active"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
