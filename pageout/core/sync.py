"""Post-export synchronization to cloud services and Git repositories.

This module provides sync functionality for:
- Local/network folders (copy to network location)
- Google Drive (via Google Drive API)
- Dropbox (via Dropbox API)
- Amazon S3 (via boto3)
- Git repositories (commit + push)

All cloud integrations use optional dependencies and follow the pattern:
- Check for required packages at runtime
- Graceful degradation if not installed
- Credentials from keyring or environment variables
"""

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

# Optional dependency: keyring for credential storage
try:
    import keyring

    KEYRING_AVAILABLE = True
except ImportError:
    keyring = None
    KEYRING_AVAILABLE = False

# Sync target constants
SYNC_TARGETS = ["None", "Local folder", "Google Drive", "Dropbox", "S3", "Git repo"]


@dataclass
class SyncResult:
    """Result of a sync operation."""

    success: bool
    target: str
    message: str = ""
    files_synced: int = 0
    error: str = ""


@dataclass
class SyncReport:
    """Comprehensive sync report for an export."""

    target: str
    success: bool
    message: str = ""
    files_synced: int = 0
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "target": self.target,
            "success": self.success,
            "message": self.message,
            "files_synced": self.files_synced,
            "errors": self.errors,
        }


def _get_secret(service: str, key: str) -> str:
    """Get a secret from the system keyring."""
    try:
        return keyring.get_password(service, key) or ""
    except Exception:
        return ""


def _get_env_secret(env_var: str) -> str:
    """Get a secret from environment variable."""
    return os.environ.get(env_var, "")


def _count_files_in_directory(directory: str) -> int:
    """Count output files in a directory (excluding images folder)."""
    count = 0
    dir_path = Path(directory)
    if not dir_path.exists():
        return 0

    for ext in [".pdf", ".html", ".md", ".txt", ".docx", ".json", ".tex", ".rst", ".adoc", ".epub"]:
        count += len(list(dir_path.rglob(f"*{ext}")))
    return count


# =============================================================================
# Local Folder Sync - copy to network/local shared folder
# =============================================================================


def sync_to_local_folder(source_dir: str, target_path: str, cfg: dict) -> SyncResult:
    """Sync export to a local or network folder via copy.

    Args:
        source_dir: The export output directory
        target_path: The destination folder path (local or network share)
        cfg: Configuration dict (unused but kept for API consistency)

    Returns:
        SyncResult with success status and details
    """
    try:
        if not os.path.exists(source_dir):
            return SyncResult(False, "Local folder", f"Source directory does not exist: {source_dir}")

        if not target_path.strip():
            return SyncResult(False, "Local folder", "No target path specified")

        target_path = os.path.abspath(os.path.expandvars(target_path))

        # Create target directory if it doesn't exist
        os.makedirs(target_path, exist_ok=True)

        # Copy the entire export directory
        # Use a unique folder name to avoid conflicts
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest_dir = os.path.join(target_path, f"export_{timestamp}")

        try:
            shutil.copytree(source_dir, dest_dir)
        except Exception:
            # If destination exists, merge instead
            if os.path.exists(dest_dir):
                for item in os.listdir(source_dir):
                    src_item = os.path.join(source_dir, item)
                    dst_item = os.path.join(dest_dir, item)
                    if os.path.isdir(src_item):
                        shutil.copytree(src_item, dst_item, dirs_exist_ok=True)
                    else:
                        shutil.copy2(src_item, dst_item)
            else:
                raise

        files_synced = _count_files_in_directory(dest_dir)
        return SyncResult(True, "Local folder", f"Synced to {dest_dir}", files_synced=files_synced)
    except PermissionError as e:
        return SyncResult(False, "Local folder", f"Permission denied: {target_path}", error=str(e))
    except Exception as e:
        return SyncResult(False, "Local folder", f"Sync failed: {e}", error=str(e))


# =============================================================================
# Git Repository Sync
# =============================================================================


def sync_to_git(source_dir: str, branch: str, cfg: dict) -> SyncResult:
    """Sync export to a Git repository (commit + push).

    Args:
        source_dir: The export output directory
        branch: Git branch to commit to
        cfg: Configuration dict (unused but kept for API consistency)

    Returns:
        SyncResult with success status and details
    """
    try:
        if not os.path.exists(source_dir):
            return SyncResult(False, "Git repo", f"Source directory does not exist: {source_dir}")

        source_path = Path(source_dir).resolve()

        # Check if we're in a git repository
        try:
            # Try to find git repo
            result = subprocess.run(
                ["git", "rev-parse", "--git-dir"], cwd=str(source_path), capture_output=True, text=True, timeout=30
            )

            if result.returncode != 0:
                return SyncResult(False, "Git repo", "Not a Git repository")

            # Get the remote URL for messaging
            remote_result = subprocess.run(
                ["git", "remote", "get-url", "origin"], cwd=str(source_path), capture_output=True, text=True, timeout=30
            )
            remote_url = remote_result.stdout.strip() if remote_result.returncode == 0 else "unknown"

        except FileNotFoundError:
            return SyncResult(False, "Git repo", "Git not installed")
        except subprocess.TimeoutExpired:
            return SyncResult(False, "Git repo", "Git operation timed out")

        # Stage all new/modified files
        try:
            subprocess.run(["git", "add", "."], cwd=str(source_path), capture_output=True, text=True, timeout=60)
        except subprocess.TimeoutExpired:
            return SyncResult(False, "Git repo", "Git add timed out", error="timeout")

        # Check if there's anything to commit
        try:
            status_result = subprocess.run(
                ["git", "status", "--porcelain"], cwd=str(source_path), capture_output=True, text=True, timeout=30
            )
        except subprocess.TimeoutExpired:
            return SyncResult(False, "Git repo", "Git status timed out", error="timeout")

        if not status_result.stdout.strip():
            return SyncResult(True, "Git repo", "No changes to commit", files_synced=0)

        # Create commit message
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        commit_msg = f"Auto-export from PageOut - {timestamp}"

        # Commit
        try:
            commit_result = subprocess.run(
                ["git", "commit", "-m", commit_msg], cwd=str(source_path), capture_output=True, text=True, timeout=60
            )
        except subprocess.TimeoutExpired:
            return SyncResult(False, "Git repo", "Git commit timed out", error="timeout")

        if commit_result.returncode != 0:
            # Check if it's just "nothing to commit"
            if (
                "nothing to commit" in commit_result.stderr.lower()
                or "nothing to commit" in commit_result.stdout.lower()
            ):
                return SyncResult(True, "Git repo", "No changes to commit", files_synced=0)
            return SyncResult(False, "Git repo", f"Git commit failed: {commit_result.stderr}")

        # Push to remote
        try:
            push_result = subprocess.run(
                ["git", "push", "origin", branch], cwd=str(source_path), capture_output=True, text=True, timeout=120
            )
        except subprocess.TimeoutExpired:
            return SyncResult(False, "Git repo", "Git push timed out", error="timeout")

        if push_result.returncode != 0:
            return SyncResult(False, "Git repo", f"Git push failed: {push_result.stderr}")

        # Count changed files
        files_synced = len([l for l in status_result.stdout.splitlines() if l.strip()])

        return SyncResult(
            True, "Git repo", f"Committed and pushed to {branch} ({remote_url})", files_synced=files_synced
        )
    except Exception as e:
        return SyncResult(False, "Git repo", f"Sync failed: {e}", error=str(e))


# =============================================================================
# Google Drive Sync
# =============================================================================


def sync_to_gdrive(source_dir: str, folder_id: str, cfg: dict) -> SyncResult:
    """Sync export to Google Drive using Google Drive API.

    Uses google-auth and google-api-python-client packages (optional dependencies).
    Credentials are retrieved from keyring or GDRIVE_TOKEN environment variable.

    Args:
        source_dir: The export output directory
        folder_id: Google Drive folder ID to sync to
        cfg: Configuration dict

    Returns:
        SyncResult with success status and details
    """
    try:
        # Check for required packages
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
            from googleapiclient.http import MediaFileUpload
        except ImportError:
            return SyncResult(False, "Google Drive", "google-auth and google-api-python-client not installed")
    except Exception as e:
        return SyncResult(False, "Google Drive", f"Import error: {e}", error=str(e))

    try:
        # Get credentials from keyring or environment
        def get_credential(key_name: str) -> str:
            val = _get_secret("PageOut for Notion", key_name) or _get_env_secret(key_name)
            return val

        # For simplicity, we'll use a combined token approach
        # In production, you'd want to do OAuth2 flow for user consent
        token = get_credential("GDRIVE_TOKEN")
        if not token:
            return SyncResult(
                False,
                "Google Drive",
                "Google Drive token not configured (set GDRIVE_TOKEN in environment or store in keyring)",
            )

        # Parse the token (assumes it's a valid access token)
        creds = Credentials(token)

        # Refresh credentials if needed
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                return SyncResult(False, "Google Drive", f"Token refresh failed: {e}")

        # Build the service
        service = build("drive", "v3", credentials=creds)

        if not os.path.exists(source_dir):
            return SyncResult(False, "Google Drive", f"Source directory does not exist: {source_dir}")

        source_path = Path(source_dir)
        files_synced = 0

        # Sync files to Google Drive
        for ext in [".pdf", ".html", ".md", ".txt", ".docx", ".json", ".tex", ".rst", ".adoc", ".epub"]:
            for file_path in source_path.rglob(f"*{ext}"):
                try:
                    # Create file in Google Drive
                    file_metadata = {"name": file_path.name, "parents": [folder_id]}
                    media = MediaFileUpload(str(file_path), resumable=True)

                    service.files().create(body=file_metadata, media_body=media, fields="id").execute()
                    files_synced += 1
                except Exception:
                    # Log error but continue with other files
                    pass

        return SyncResult(
            True,
            "Google Drive",
            f"Synced {files_synced} files to Google Drive folder {folder_id}",
            files_synced=files_synced,
        )
    except Exception as e:
        return SyncResult(False, "Google Drive", f"Sync failed: {e}", error=str(e))


# =============================================================================
# Dropbox Sync
# =============================================================================


def sync_to_dropbox(source_dir: str, dropbox_path: str, cfg: dict) -> SyncResult:
    """Sync export to Dropbox using Dropbox API.

    Uses dropbox package (optional dependency).
    Credentials are retrieved from keyring or DROPBOX_TOKEN environment variable.

    Args:
        source_dir: The export output directory
        dropbox_path: Path in Dropbox to sync to (e.g., /exports)
        cfg: Configuration dict

    Returns:
        SyncResult with success status and details
    """
    try:
        # Check for required packages
        try:
            import dropbox
        except ImportError:
            return SyncResult(False, "Dropbox", "dropbox package not installed (pip install dropbox)")
    except Exception as e:
        return SyncResult(False, "Dropbox", f"Import error: {e}", error=str(e))

    try:
        # Get credentials from keyring or environment
        def get_credential(key_name: str) -> str:
            val = _get_secret("PageOut for Notion", key_name) or _get_env_secret(key_name)
            return val

        token = get_credential("DROPBOX_TOKEN")
        if not token:
            return SyncResult(
                False, "Dropbox", "Dropbox token not configured (set DROPBOX_TOKEN in environment or store in keyring)"
            )

        # Create Dropbox client
        dbx = dropbox.Dropbox(token)

        # Verify token works
        try:
            dbx.users_get_current_account()
        except dropbox.exceptions.AuthError:
            return SyncResult(False, "Dropbox", "Invalid Dropbox token")

        if not os.path.exists(source_dir):
            return SyncResult(False, "Dropbox", f"Source directory does not exist: {source_dir}")

        source_path = Path(source_dir)
        files_synced = 0

        # Ensure dropbox_path starts with /
        if not dropbox_path.startswith("/"):
            dropbox_path = "/" + dropbox_path

        # Upload files to Dropbox
        for ext in [".pdf", ".html", ".md", ".txt", ".docx", ".json", ".tex", ".rst", ".adoc", ".epub"]:
            for file_path in source_path.rglob(f"*{ext}"):
                try:
                    # Calculate Dropbox path
                    relative = file_path.relative_to(source_path)
                    dbx_path = dropbox_path + "/" + str(relative)

                    # Upload file
                    with open(file_path, "rb") as f:
                        dbx.files_upload(f.read(), dbx_path, mode=dropbox.files.WriteMode.overwrite)
                    files_synced += 1
                except Exception:
                    # Log error but continue
                    pass

        return SyncResult(
            True, "Dropbox", f"Synced {files_synced} files to Dropbox at {dropbox_path}", files_synced=files_synced
        )
    except Exception as e:
        return SyncResult(False, "Dropbox", f"Sync failed: {e}", error=str(e))


# =============================================================================
# Amazon S3 Sync
# =============================================================================


def sync_to_s3(source_dir: str, bucket: str, prefix: str, cfg: dict) -> SyncResult:
    """Sync export to Amazon S3 using boto3.

    Uses boto3 package (optional dependency).
    Credentials are retrieved from keyring or AWS environment variables.

    Args:
        source_dir: The export output directory
        bucket: S3 bucket name
        prefix: S3 key prefix (folder path)
        cfg: Configuration dict

    Returns:
        SyncResult with success status and details
    """
    try:
        # Check for required packages
        try:
            import boto3
            from botocore.exceptions import ClientError
        except ImportError:
            return SyncResult(False, "S3", "boto3 package not installed (pip install boto3)")
    except Exception as e:
        return SyncResult(False, "S3", f"Import error: {e}", error=str(e))

    try:
        # Get credentials from keyring or environment
        aws_access_key = _get_secret("PageOut for Notion", "AWS_ACCESS_KEY_ID") or _get_env_secret("AWS_ACCESS_KEY_ID")
        aws_secret_key = _get_secret("PageOut for Notion", "AWS_SECRET_ACCESS_KEY") or _get_env_secret(
            "AWS_SECRET_ACCESS_KEY"
        )

        session_kwargs = {}
        if aws_access_key and aws_secret_key:
            session_kwargs["aws_access_key_id"] = aws_access_key
            session_kwargs["aws_secret_access_key"] = aws_secret_key

        # Create S3 client (uses default credential chain if keys not provided)
        s3 = boto3.client("s3", **session_kwargs)

        if not os.path.exists(source_dir):
            return SyncResult(False, "S3", f"Source directory does not exist: {source_dir}")

        source_path = Path(source_dir)
        files_synced = 0

        # Ensure prefix doesn't end with /
        if prefix and not prefix.endswith("/"):
            prefix = prefix + "/"

        # Upload files to S3
        for ext in [".pdf", ".html", ".md", ".txt", ".docx", ".json", ".tex", ".rst", ".adoc", ".epub"]:
            for file_path in source_path.rglob(f"*{ext}"):
                try:
                    # Calculate S3 key
                    relative = file_path.relative_to(source_path)
                    s3_key = (prefix or "") + str(relative)

                    # Upload file
                    s3.upload_file(str(file_path), bucket, s3_key)
                    files_synced += 1
                except ClientError:
                    # Log error but continue
                    pass
                except Exception:
                    # Continue with other files
                    pass

        return SyncResult(
            True, "S3", f"Synced {files_synced} files to s3://{bucket}/{prefix}", files_synced=files_synced
        )
    except Exception as e:
        return SyncResult(False, "S3", f"Sync failed: {e}", error=str(e))


# =============================================================================
# Main Sync Dispatcher
# =============================================================================


def perform_sync(source_dir: str, sync_target: str, sync_config: dict, cfg: dict) -> SyncReport:
    """Perform sync operation based on target type.

    Args:
        source_dir: The export output directory
        sync_target: Target type from SYNC_TARGETS
        sync_config: Target-specific configuration
        cfg: Full configuration dict

    Returns:
        SyncReport with detailed results
    """
    if not sync_target or sync_target == "None":
        return SyncReport("None", True, "Sync disabled", 0)

    if not os.path.exists(source_dir):
        return SyncReport(
            sync_target, False, "Source directory does not exist", 0, ["Source directory does not exist: " + source_dir]
        )

    datetime.now().isoformat()

    if sync_target == "Local folder":
        result = sync_to_local_folder(source_dir, sync_config.get("sync_path", ""), cfg)
        return SyncReport(
            result.target, result.success, result.message, result.files_synced, [result.error] if result.error else []
        )

    elif sync_target == "Google Drive":
        result = sync_to_gdrive(source_dir, sync_config.get("gdrive_folder_id", ""), cfg)
        return SyncReport(
            result.target, result.success, result.message, result.files_synced, [result.error] if result.error else []
        )

    elif sync_target == "Dropbox":
        result = sync_to_dropbox(source_dir, sync_config.get("dropbox_path", "/exports"), cfg)
        return SyncReport(
            result.target, result.success, result.message, result.files_synced, [result.error] if result.error else []
        )

    elif sync_target == "S3":
        result = sync_to_s3(source_dir, sync_config.get("s3_bucket", ""), sync_config.get("s3_prefix", "exports"), cfg)
        return SyncReport(
            result.target, result.success, result.message, result.files_synced, [result.error] if result.error else []
        )

    elif sync_target == "Git repo":
        result = sync_to_git(source_dir, sync_config.get("sync_branch", "main"), cfg)
        return SyncReport(
            result.target, result.success, result.message, result.files_synced, [result.error] if result.error else []
        )

    else:
        return SyncReport(sync_target, False, f"Unknown sync target: {sync_target}", 0)


__all__ = [
    "SYNC_TARGETS",
    "SyncResult",
    "SyncReport",
    "sync_to_local_folder",
    "sync_to_git",
    "sync_to_gdrive",
    "sync_to_dropbox",
    "sync_to_s3",
    "perform_sync",
]
