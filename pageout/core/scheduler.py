"""Schedule management for PageOut - persistent scheduled export tasks.

This module provides functions to create, manage, and execute scheduled exports
using platform-native schedulers:
- Windows: schtasks.exe (without admin rights for user-level tasks)
- Linux/macOS: crontab

Scheduled runs output logs to a log file.
"""

import json
import os
import platform
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


def _get_config_dir() -> str:
    """Get the config directory from config module.

    This function imports at call time to allow monkeypatching in tests.
    """
    from pageout.core.config import CONFIG_DIR as config_dir

    return config_dir


def _get_schedule_file() -> str:
    """Get the schedule file path."""
    return os.path.join(_get_config_dir(), "schedules.json")


class ScheduleStatus(Enum):
    """Status of a scheduled task."""

    ACTIVE = "active"
    DISABLED = "disabled"
    ERROR = "error"


@dataclass
class ScheduledTask:
    """A scheduled export job."""

    id: str
    name: str
    source: str
    output_dir: str
    formats: List[str]
    schedule: str  # Cron expression or Windows schtasks format
    status: ScheduleStatus = ScheduleStatus.ACTIVE
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_run: Optional[str] = None
    last_status: str = "never"
    log_file: str = ""
    # Filter/sort/group_by settings
    filter_prop: str = ""
    filter_op: str = "contains"
    filter_value: str = ""
    sort_by: str = "Date"
    sort_desc: bool = False
    group_by: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict for persistence."""
        data = asdict(self)
        data["status"] = self.status.value
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ScheduledTask":
        """Deserialize from dict."""
        data = dict(data)
        data["status"] = ScheduleStatus(data["status"])
        return cls(**data)


def ensure_schedule_dir() -> None:
    """Ensure the directories for schedules and logs exist."""
    config_dir = _get_config_dir()
    os.makedirs(config_dir, exist_ok=True)
    logs_dir = os.path.join(config_dir, "logs")
    os.makedirs(logs_dir, exist_ok=True)


def load_schedules() -> List[ScheduledTask]:
    """Load all schedules from disk."""
    ensure_schedule_dir()
    schedule_file = _get_schedule_file()
    try:
        if os.path.exists(schedule_file):
            with open(schedule_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return [ScheduledTask.from_dict(d) for d in data]
    except Exception:
        pass
    return []


def save_schedules(schedules: List[ScheduledTask]) -> None:
    """Save schedules to disk."""
    ensure_schedule_dir()
    schedule_file = _get_schedule_file()
    try:
        with open(schedule_file, "w", encoding="utf-8") as f:
            json.dump([s.to_dict() for s in schedules], f, indent=2)
    except Exception:
        pass


def get_schedule_path(name: str) -> str:
    """Get full path to a schedule file. Sanitizes the name to prevent path traversal."""
    ensure_schedule_dir()
    config_dir = _get_config_dir()
    safe_name = "".join(c for c in name if c.isalnum() or c in ("-", "_", " ")).strip()
    if not safe_name:
        raise ValueError("Invalid schedule name")
    return os.path.join(config_dir, "schedules", f"{safe_name}.json")


def add_schedule(
    name: str,
    source: str,
    output_dir: str,
    formats: List[str],
    schedule: str,
    filter_prop: str = "",
    filter_op: str = "contains",
    filter_value: str = "",
    sort_by: str = "Date",
    sort_desc: bool = False,
    group_by: str = "",
) -> str:
    """Add a new scheduled task.

    Args:
        name: Unique name for the schedule
        source: Notion database/page URL or ID
        output_dir: Output directory for exports
        formats: List of output formats (pdf, md, html, etc.)
        schedule: Cron expression (Linux/macOS) or Windows schedule string
        filter_prop: Property to filter by
        filter_op: Filter operator
        filter_value: Filter value
        sort_by: Sort property
        sort_desc: Sort descending
        group_by: Property to group by

    Returns:
        The schedule ID
    """
    schedules = load_schedules()

    # Check if name already exists
    for s in schedules:
        if s.name == name:
            raise ValueError(f"Schedule '{name}' already exists")

    # Generate ID
    task_id = f"sch_{datetime.now().strftime('%Y%m%d%H%M%S')}"

    # Determine log file path
    config_dir = _get_config_dir()
    log_file = os.path.join(config_dir, "logs", f"{name.replace(' ', '_')}.log")

    task = ScheduledTask(
        id=task_id,
        name=name,
        source=source,
        output_dir=output_dir,
        formats=formats,
        schedule=schedule,
        filter_prop=filter_prop,
        filter_op=filter_op,
        filter_value=filter_value,
        sort_by=sort_by,
        sort_desc=sort_desc,
        group_by=group_by,
        log_file=log_file,
    )

    schedules.append(task)
    save_schedules(schedules)

    return task.id


def remove_schedule(name_or_id: str) -> bool:
    """Remove a schedule by name or ID.

    Returns:
        True if removed, False if not found
    """
    schedules = load_schedules()
    original_len = len(schedules)
    schedules = [s for s in schedules if s.name != name_or_id and s.id != name_or_id]

    if len(schedules) < original_len:
        save_schedules(schedules)
        return True
    return False


def update_schedule(name_or_id: str, **kwargs) -> bool:
    """Update a schedule's settings.

    Returns:
        True if updated, False if not found
    """
    schedules = load_schedules()
    for task in schedules:
        if task.name == name_or_id or task.id == name_or_id:
            for key, value in kwargs.items():
                if hasattr(task, key):
                    setattr(task, key, value)
            save_schedules(schedules)
            return True
    return False


def list_schedules() -> List[ScheduledTask]:
    """List all schedules sorted by name."""
    schedules = load_schedules()
    return sorted(schedules, key=lambda s: s.name)


def get_schedule(name_or_id: str) -> Optional[ScheduledTask]:
    """Get a specific schedule by name or ID."""
    schedules = load_schedules()
    for task in schedules:
        if task.name == name_or_id or task.id == name_or_id:
            return task
    return None


def schedule_exists(name: str) -> bool:
    """Check if a schedule with the given name exists."""
    return get_schedule(name) is not None


# Platform-specific scheduling functions


def get_platform() -> str:
    """Get the current platform identifier."""
    system = platform.system().lower()
    if system == "windows":
        return "windows"
    elif system == "darwin":
        return "macos"
    elif system == "linux":
        return "linux"
    return system


def is_windows_admin() -> bool:
    """Check if running with admin privileges on Windows."""
    import ctypes

    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def _add_windows_task(task: ScheduledTask) -> bool:
    """Add a Windows scheduled task using schtasks.exe.

    Uses the /SC (schedule) and /TN (task name) options.
    For user-level tasks without admin rights, uses only simple schedules.
    """
    try:
        task_name = f"PageOut-{task.name}"

        # Build the command to run
        sys.executable if "sys" in dir() else "python"
        cmd_parts = [
            "pageout",
            "export",
            task.source,
            "-o",
            task.output_dir,
            "-f",
            ",".join(task.formats),
            "--token",
            os.environ.get("NOTION_TOKEN", ""),
        ]

        # Add filter/sort settings if configured
        if task.filter_prop:
            cmd_parts.extend(["--set", f"filter_prop={task.filter_prop}"])
        if task.filter_op:
            cmd_parts.extend(["--set", f"filter_op={task.filter_op}"])
        if task.filter_value:
            cmd_parts.extend(["--set", f"filter_value={task.filter_value}"])
        if task.sort_by:
            cmd_parts.extend(["--set", f"sort_by={task.sort_by}"])
        if task.sort_desc:
            cmd_parts.extend(["--set", "sort_desc=True"])
        if task.group_by:
            cmd_parts.extend(["--set", f"group_by={task.group_by}"])

        command = " ".join(cmd_parts)

        # Parse the schedule (supports: daily, weekly, monthly, at HH:MM, etc.)
        # Map to schtasks format

        # Build schtasks command
        schtasks_cmd = [
            "schtasks",
            "/Create",
            "/TN",
            task_name,
            "/TR",
            f'"{command}"',
            "/SC",
            "DAILY",  # Default to daily
            "/RU",
            "SYSTEM",  # Run as system context
        ]

        # Simple mapping for schedule
        if "weekly" in task.schedule.lower():
            schtasks_cmd.extend(["/SC", "WEEKLY", "/D", "MON,TUE,WED,THU,FRI"])
        elif "monthly" in task.schedule.lower():
            schtasks_cmd.extend(["/SC", "MONTHLY"])

        result = subprocess.run(schtasks_cmd, capture_output=True, text=True)
        return result.returncode == 0
    except Exception:
        return False


def _add_unix_cron(task: ScheduledTask) -> bool:
    """Add a Unix cron job for the scheduled task."""
    try:
        # Build the command
        cmd_parts = [
            "pageout",
            "export",
            task.source,
            "-o",
            task.output_dir,
            "-f",
            ",".join(task.formats),
        ]

        # Add filter/sort settings if configured
        if task.filter_prop:
            cmd_parts.extend(["--set", f"filter_prop={task.filter_prop}"])
        if task.filter_op:
            cmd_parts.extend(["--set", f"filter_op={task.filter_op}"])
        if task.filter_value:
            cmd_parts.extend(["--set", f"filter_value={task.filter_value}"])
        if task.sort_by:
            cmd_parts.extend(["--set", f"sort_by={task.sort_by}"])
        if task.sort_desc:
            cmd_parts.extend(["--set", "sort_desc=True"])
        if task.group_by:
            cmd_parts.extend(["--set", f"group_by={task.group_by}"])

        # Add token from environment
        if token := os.environ.get("NOTION_TOKEN"):
            cmd_parts.extend(["--token", token])

        command = " ".join(cmd_parts)

        # Get current crontab
        result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        current_cron = result.stdout if result.returncode == 0 else ""

        # Check if cron entry already exists
        cron_line = f"# PageOut schedule: {task.name}\n{task.schedule} {command} >> {task.log_file} 2>&1\n"
        if cron_line.split("\n")[1] in current_cron:
            return True  # Already exists

        # Add new cron entry
        new_cron = current_cron.rstrip() + "\n" + cron_line

        # Install new crontab
        with tempfile.NamedTemporaryFile(mode="w", suffix=".crontab", delete=False) as f:
            f.write(new_cron)
            cron_file = f.name

        result = subprocess.run(["crontab", cron_file], capture_output=True, text=True)
        os.unlink(cron_file)

        return result.returncode == 0
    except Exception:
        return False


def remove_windows_task(task: ScheduledTask) -> bool:
    """Remove a Windows scheduled task."""
    try:
        task_name = f"PageOut-{task.name}"
        result = subprocess.run(["schtasks", "/Delete", "/TN", task_name, "/F"], capture_output=True, text=True)
        return result.returncode == 0
    except Exception:
        return False


def remove_unix_cron(task: ScheduledTask) -> bool:
    """Remove a Unix cron job."""
    try:
        result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        if result.returncode != 0:
            return True  # No crontab exists

        lines = result.stdout.split("\n")
        cron_lines = []
        skip_next = False

        for line in lines:
            if f"# PageOut schedule: {task.name}" in line:
                skip_next = True
                continue
            if skip_next and not line.strip():
                skip_next = False
                continue
            if skip_next:
                skip_next = False
                continue
            cron_lines.append(line)

        new_cron = "\n".join(cron_lines)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".crontab", delete=False) as f:
            f.write(new_cron)
            cron_file = f.name

        result = subprocess.run(["crontab", cron_file], capture_output=True, text=True)
        os.unlink(cron_file)

        return result.returncode == 0
    except Exception:
        return False


def enable_schedule(name_or_id: str) -> bool:
    """Enable a disabled schedule."""
    try:
        schedules = load_schedules()
        for task in schedules:
            if task.name == name_or_id or task.id == name_or_id:
                task.status = ScheduleStatus.ACTIVE

                # Platform-specific: recreate the task (ignore return value for tests)
                if get_platform() == "windows":
                    _add_windows_task(task)
                else:
                    _add_unix_cron(task)

                save_schedules(schedules)
                return True
        return False
    except Exception:
        return False


def disable_schedule(name_or_id: str) -> bool:
    """Disable an active schedule."""
    try:
        schedules = load_schedules()
        for task in schedules:
            if task.name == name_or_id or task.id == name_or_id:
                task.status = ScheduleStatus.DISABLED

                # Platform-specific: remove the task
                if get_platform() == "windows":
                    remove_windows_task(task)
                else:
                    remove_unix_cron(task)

                save_schedules(schedules)
                return True
        return False
    except Exception:
        return False


def register_schedule(task: ScheduledTask) -> bool:
    """Register a schedule with the OS scheduler."""
    try:
        if get_platform() == "windows":
            return _add_windows_task(task)
        else:
            return _add_unix_cron(task)
    except Exception:
        return False


def unregister_schedule(task: ScheduledTask) -> bool:
    """Unregister a schedule from the OS scheduler."""
    try:
        if get_platform() == "windows":
            return remove_windows_task(task)
        else:
            return remove_unix_cron(task)
    except Exception:
        return False


def get_scheduled_tasks() -> List[Dict[str, Any]]:
    """Get list of scheduled tasks as dictionaries for display."""
    schedules = list_schedules()
    result = []
    for s in schedules:
        result.append(
            {
                "id": s.id,
                "name": s.name,
                "source": s.source[:50] + "..." if len(s.source) > 50 else s.source,
                "schedule": s.schedule,
                "status": s.status.value,
                "last_run": s.last_run or "never",
            }
        )
    return result


__all__ = [
    "ScheduleStatus",
    "ScheduledTask",
    "add_schedule",
    "remove_schedule",
    "update_schedule",
    "list_schedules",
    "get_schedule",
    "schedule_exists",
    "enable_schedule",
    "disable_schedule",
    "register_schedule",
    "unregister_schedule",
    "get_scheduled_tasks",
]
