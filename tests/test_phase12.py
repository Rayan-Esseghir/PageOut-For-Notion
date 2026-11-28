"""Tests for Phase 12: Scheduling and scheduled exports."""

import pytest

from pageout.core.scheduler import (
    ScheduledTask,
    ScheduleStatus,
    add_schedule,
    disable_schedule,
    enable_schedule,
    get_schedule,
    get_scheduled_tasks,
    list_schedules,
    remove_schedule,
    schedule_exists,
    update_schedule,
)


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """Isolated test environment with temp config directory."""
    import pageout.core.config as config_module
    import pageout.core.scheduler as scheduler_module
    import pageout.core.sources as sources_module

    cfg_dir = str(tmp_path / "cfg")
    monkeypatch.setattr(config_module, "CONFIG_DIR", cfg_dir)
    monkeypatch.setattr(config_module, "CONFIG_FILE", cfg_dir + "/config.json")
    monkeypatch.setattr(sources_module, "SOURCE_DIR", cfg_dir + "/sources")
    # Patch _get_config_dir to return our temp config dir
    monkeypatch.setattr(scheduler_module, "_get_config_dir", lambda: cfg_dir)
    monkeypatch.delenv("NOTION_TOKEN", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)


# ---------------------------------------------------------------------- Test ScheduledTask dataclass
def test_scheduled_task_creation():
    """ScheduledTask should be created with default values."""
    task = ScheduledTask(
        id="sch_test123",
        name="test-schedule",
        source="https://www.notion.so/test-db-1234567890abcdef1234567890abcdef",
        output_dir="/tmp/exports",
        formats=["pdf", "md"],
        schedule="daily",
    )

    assert task.id == "sch_test123"
    assert task.name == "test-schedule"
    assert task.formats == ["pdf", "md"]
    assert task.status == ScheduleStatus.ACTIVE
    assert task.last_run is None
    assert task.last_status == "never"


def test_scheduled_task_to_dict_from_dict():
    """ScheduledTask should serialize and deserialize correctly."""
    task = ScheduledTask(
        id="sch_test456",
        name="serde-test",
        source="db-test-id",
        output_dir="./output",
        formats=["md"],
        schedule="weekly",
        filter_prop="Status",
        filter_value="Done",
        sort_by="Title",
    )

    data = task.to_dict()
    assert data["id"] == "sch_test456"
    assert data["status"] == "active"
    assert data["filter_prop"] == "Status"

    restored = ScheduledTask.from_dict(data)
    assert restored.id == task.id
    assert restored.name == task.name
    assert restored.status == ScheduleStatus.ACTIVE


# ---------------------------------------------------------------------- Test add_schedule
def test_add_schedule_basic(isolated):
    """Add a basic scheduled task."""
    task_id = add_schedule(
        name="my-schedule",
        source="db1234567890abcdef1234567890abcdef",
        output_dir="/tmp/exports",
        formats=["pdf", "md"],
        schedule="daily at 9:00",
    )

    assert task_id is not None
    assert task_id.startswith("sch_")

    task = get_schedule("my-schedule")
    assert task is not None
    assert task.name == "my-schedule"
    assert task.source == "db1234567890abcdef1234567890abcdef"
    assert task.output_dir == "/tmp/exports"
    assert task.formats == ["pdf", "md"]
    assert task.schedule == "daily at 9:00"


def test_add_schedule_with_filters(isolated):
    """Add a scheduled task with filter/sort settings."""
    task_id = add_schedule(
        name="filtered-schedule",
        source="db-test-id",
        output_dir="./exports",
        formats=["md"],
        schedule="weekly",
        filter_prop="Status",
        filter_op="equals",
        filter_value="Done",
        sort_by="Title",
        sort_desc=True,
        group_by="Tag",
    )

    task = get_schedule("filtered-schedule")
    assert task.filter_prop == "Status"
    assert task.filter_op == "equals"
    assert task.filter_value == "Done"
    assert task.sort_by == "Title"
    assert task.sort_desc is True
    assert task.group_by == "Tag"


def test_add_schedule_duplicate_name(isolated):
    """Adding a schedule with duplicate name should raise ValueError."""
    add_schedule("duplicate", "db1", "/out", ["md"], "daily")

    with pytest.raises(ValueError):
        add_schedule("duplicate", "db2", "/out", ["md"], "daily")


# ---------------------------------------------------------------------- Test remove_schedule
def test_remove_schedule(isolated):
    """Remove a schedule by name."""
    add_schedule("to-remove", "db1", "/out", ["md"], "daily")

    assert schedule_exists("to-remove")
    assert remove_schedule("to-remove") is True
    assert not schedule_exists("to-remove")


def test_remove_schedule_nonexistent(isolated):
    """Removing a nonexistent schedule returns False."""
    assert remove_schedule("nonexistent") is False


def test_remove_schedule_by_id(isolated):
    """Remove a schedule by ID."""
    task_id = add_schedule("by-id-test", "db1", "/out", ["md"], "daily")

    task = get_schedule(task_id)
    assert task is not None
    assert task.id == task_id

    assert remove_schedule(task_id) is True
    assert get_schedule(task_id) is None


# ---------------------------------------------------------------------- Test update_schedule
def test_update_schedule(isolated):
    """Update a schedule's settings."""
    add_schedule("update-test", "db1", "/out", ["md"], "daily")

    result = update_schedule("update-test", output_dir="/new/out", schedule="weekly")
    assert result is True

    task = get_schedule("update-test")
    assert task.output_dir == "/new/out"
    assert task.schedule == "weekly"


def test_update_schedule_nonexistent(isolated):
    """Updating a nonexistent schedule returns False."""
    assert update_schedule("nonexistent", output_dir="/new") is False


# ---------------------------------------------------------------------- Test list_schedules
def test_list_schedules_empty(isolated):
    """List schedules should return empty list when no schedules exist."""
    assert list_schedules() == []


def test_list_schedules_sorted(isolated):
    """List schedules should return them sorted by name."""
    add_schedule("zeta", "db1", "/out", ["md"], "daily")
    add_schedule("alpha", "db2", "/out", ["md"], "daily")
    add_schedule("Beta", "db3", "/out", ["md"], "daily")

    schedules = list_schedules()
    names = [s.name for s in schedules]
    assert names == ["Beta", "alpha", "zeta"]


# ---------------------------------------------------------------------- Test get_schedule
def test_get_schedule_by_name_and_id(isolated):
    """get_schedule should work with name or ID."""
    task_id = add_schedule("named-schedule", "db1", "/out", ["md"], "daily")

    task1 = get_schedule("named-schedule")
    task2 = get_schedule(task_id)

    assert task1 is not None
    assert task2 is not None
    assert task1.id == task2.id


def test_get_schedule_nonexistent(isolated):
    """get_schedule returns None for nonexistent schedule."""
    assert get_schedule("nonexistent") is None
    assert get_schedule("sch_nonexistent") is None


# ---------------------------------------------------------------------- Test enable/disable
def test_enable_schedule(isolated):
    """Enable a disabled schedule."""
    add_schedule("enable-test", "db1", "/out", ["md"], "daily")
    disable_schedule("enable-test")

    task = get_schedule("enable-test")
    assert task.status == ScheduleStatus.DISABLED

    result = enable_schedule("enable-test")
    assert result is True


def test_disable_schedule(isolated):
    """Disable an active schedule."""
    add_schedule("disable-test", "db1", "/out", ["md"], "daily")

    task = get_schedule("disable-test")
    assert task.status == ScheduleStatus.ACTIVE

    result = disable_schedule("disable-test")
    assert result is True

    task = get_schedule("disable-test")
    assert task.status == ScheduleStatus.DISABLED


# ---------------------------------------------------------------------- Test get_scheduled_tasks
def test_get_scheduled_tasks(isolated):
    """get_scheduled_tasks should return list of dicts for display."""
    add_schedule("display-test", "db1", "/out", ["md", "pdf"], "daily")

    tasks = get_scheduled_tasks()
    assert isinstance(tasks, list)
    assert len(tasks) == 1
    assert tasks[0]["name"] == "display-test"
    assert tasks[0]["id"].startswith("sch_")
    assert "source" in tasks[0]
    assert "schedule" in tasks[0]
    assert "status" in tasks[0]


# ---------------------------------------------------------------------- Test Schedule persistence
def test_schedule_persistence(isolated):
    """Schedules should persist across loads."""
    from pageout.core.scheduler import load_schedules

    add_schedule("persist-test", "db1", "/out", ["md"], "daily")

    # Create new instance to force reload
    schedules = load_schedules()
    assert any(s.name == "persist-test" for s in schedules)


# ---------------------------------------------------------------------- Test log file output mechanism
def test_log_file_path_is_set(isolated):
    """Each schedule should have a log file path configured."""
    task_id = add_schedule(
        name="log-test",
        source="db1",
        output_dir="/out",
        formats=["md"],
        schedule="daily",
    )

    task = get_schedule(task_id)
    assert task.log_file is not None
    assert "logs" in task.log_file
    assert "log-test.log" in task.log_file


# ---------------------------------------------------------------------- Test multiple formats
def test_add_schedule_multiple_formats(isolated):
    """Add schedule with multiple output formats."""
    task_id = add_schedule(
        name="multi-format",
        source="db1",
        output_dir="/out",
        formats=["pdf", "md", "html"],
        schedule="daily",
    )

    task = get_schedule(task_id)
    assert task.formats == ["pdf", "md", "html"]


# ---------------------------------------------------------------------- Test schedule with source reference
def test_schedule_with_filter_settings(isolated):
    """Scheduled task should capture all filter/sort/group_by settings."""
    task_id = add_schedule(
        name="complete-schedule",
        source="db-complete",
        output_dir="./complete",
        formats=["md"],
        schedule="0 9 * * 1",  # Weekly Monday 9AM
        filter_prop="Name",
        filter_op="contains",
        filter_value="Important",
        sort_by="Date",
        sort_desc=False,
        group_by="Tag",
    )

    task = get_schedule(task_id)
    assert task.filter_prop == "Name"
    assert task.filter_op == "contains"
    assert task.filter_value == "Important"
    assert task.sort_by == "Date"
    assert task.sort_desc is False
    assert task.group_by == "Tag"
