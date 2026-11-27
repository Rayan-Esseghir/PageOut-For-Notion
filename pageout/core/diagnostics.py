"""U6: System diagnostics for "Check my setup" feature.

Collects system information to help users troubleshoot export issues.
"""

import os
import platform
import sys
import subprocess
import tempfile
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass


@dataclass
class DiagnosticResult:
    """Result of a single diagnostic check."""
    name: str
    status: str  # "OK", "WARNING", "ERROR", "INFO"
    message: str
    detail: Optional[str] = None
    critical: bool = False


class DiagnosticsCollector:
    """Collects system diagnostics for troubleshooting."""

    def __init__(self, cfg: Optional[Dict] = None):
        self.cfg = cfg or {}

    def run_all(self) -> List[DiagnosticResult]:
        """Run all diagnostic checks and return results."""
        results = []

        # Python version check
        results.append(self.check_python_version())

        # Operating System info
        results.append(self.check_os_info())

        # Network connectivity
        results.append(self.check_network())

        # Write access to config folder
        results.append(self.check_write_access())

        # Chromium/Chromium-based browser
        results.append(self.check_chromium())

        # Notion token status
        results.append(self.check_token())

        # Fonts check
        results.append(self.check_fonts())

        # Keyring availability
        results.append(self.check_keyring())

        # Executable version
        results.append(self.check_app_version())

        return results

    def check_python_version(self) -> DiagnosticResult:
        """Check Python version."""
        version = sys.version_info
        version_str = f"Python {version.major}.{version.minor}.{version.micro}"

        # We require Python 3.8+
        if version.major < 3 or (version.major == 3 and version.minor < 8):
            return DiagnosticResult(
                name="Python Version",
                status="ERROR",
                message=f"{version_str} - Too old",
                detail="Python 3.8 or later is required.",
                critical=True
            )

        return DiagnosticResult(
            name="Python Version",
            status="OK",
            message=version_str,
            detail="Required: Python 3.8+"
        )

    def check_os_info(self) -> DiagnosticResult:
        """Get operating system information."""
        os_name = platform.system()
        os_version = platform.version()
        arch = platform.machine()

        details = f"{os_name} {os_version} ({arch})"
        return DiagnosticResult(
            name="Operating System",
            status="OK",
            message=f"{os_name} {arch}",
            detail=details
        )

    def check_network(self) -> DiagnosticResult:
        """Check network connectivity to Notion API."""
        try:
            import urllib.request
            import urllib.error

            url = "https://api.notion.com/v1/databases"
            req = urllib.request.Request(url, method='HEAD')
            req.add_header('Authorization', 'Bearer dummy_token')
            req.add_header('Notion-Version', '2022-06-28')

            with urllib.request.urlopen(req, timeout=5) as response:
                # We're checking if we can reach the API endpoint
                # A 401 is expected with dummy token, which means network is working
                if response.status in (401, 403):
                    return DiagnosticResult(
                        name="Network Connectivity",
                        status="OK",
                        message="Can reach Notion API",
                        detail="Network access to notion.so is working"
                    )
                else:
                    return DiagnosticResult(
                        name="Network Connectivity",
                        status="OK",
                        message=f"HTTP {response.status}",
                        detail="Notion API reachable"
                    )
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                return DiagnosticResult(
                    name="Network Connectivity",
                    status="OK",
                    message="Can reach Notion API",
                    detail="Network access to notion.so is working"
                )
            return DiagnosticResult(
                name="Network Connectivity",
                status="WARNING",
                message=f"HTTP {e.code}",
                detail=f"Network issue: {e.reason}"
            )
        except urllib.error.URLError as e:
            return DiagnosticResult(
                name="Network Connectivity",
                status="ERROR",
                message="Cannot reach Notion API",
                detail=str(e.reason),
                critical=True
            )
        except Exception as e:
            return DiagnosticResult(
                name="Network Connectivity",
                status="WARNING",
                message="Network check inconclusive",
                detail=str(e)
            )

    def check_write_access(self) -> DiagnosticResult:
        """Check write access to config folder."""
        from pageout.core.config import CONFIG_DIR, CONFIG_FILE

        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)

            # Try to write a test file
            test_file = os.path.join(CONFIG_DIR, ".write_test")
            with open(test_file, "w") as f:
                f.write("test")
            os.remove(test_file)

            return DiagnosticResult(
                name="Write Access",
                status="OK",
                message=f"{CONFIG_DIR}",
                detail="Config folder is writable"
            )
        except PermissionError as e:
            return DiagnosticResult(
                name="Write Access",
                status="ERROR",
                message=str(e),
                detail=f"Cannot write to {CONFIG_DIR}",
                critical=True
            )
        except Exception as e:
            return DiagnosticResult(
                name="Write Access",
                status="WARNING",
                message="Write check failed",
                detail=str(e)
            )

    def check_chromium(self) -> DiagnosticResult:
        """Check for Chromium/Chrome browser for Browser engine."""
        # Check common Chromium/Chrome paths on Windows
        chrome_paths = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Users\%s\AppData\Local\Google\Chrome\Application\chrome.exe" % (os.environ.get("USERPROFILE", "").split("\\")[-1] if "\\" in os.environ.get("USERPROFILE", "") else ""),
        ]

        for path in chrome_paths:
            if os.path.exists(path):
                return DiagnosticResult(
                    name="Browser (Chromium)",
                    status="OK",
                    message="Chrome/Chromium found",
                    detail=path
                )

        # Try to find via 'where' command on Windows
        if sys.platform.startswith("win"):
            try:
                result = subprocess.run(["where", "chrome"], capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    return DiagnosticResult(
                        name="Browser (Chromium)",
                        status="OK",
                        message="Chrome found in PATH",
                        detail=result.stdout.split()[0]
                    )
            except Exception:
                pass

        return DiagnosticResult(
            name="Browser (Chromium)",
            status="WARNING",
            message="Browser engine needs Chrome/Chromium",
            detail="Install Google Chrome or Microsoft Edge for Browser engine exports",
            critical=False
        )

    def check_token(self) -> DiagnosticResult:
        """Check Notion token status."""
        token = self.cfg.get("token", "")

        if not token:
            return DiagnosticResult(
                name="Notion Token",
                status="INFO",
                message="No token configured",
                detail="Create integration at notion.so/my-integrations"
            )

        # Check token format (basic validation)
        if len(token) < 20:
            return DiagnosticResult(
                name="Notion Token",
                status="WARNING",
                message="Token looks invalid",
                detail="Token too short - check at notion.so/my-integrations"
            )

        return DiagnosticResult(
            name="Notion Token",
            status="OK",
            message="Token configured",
            detail="Integration token present in config/keyring"
        )

    def check_fonts(self) -> DiagnosticResult:
        """Check for installed fonts."""
        try:
            try:
                import tkinter as tk
                import tkinter.font as tkfont
                root = tk.Tk()
                installed = set(f for f in tkfont.families(root) if not f.startswith("@"))
                root.destroy()
            except Exception:
                installed = set()

            # Check for common fonts
            common_fonts = ["Arial", "Times New Roman", "Calibri", "Segoe UI"]
            missing = [f for f in common_fonts if f not in installed]

            if missing:
                return DiagnosticResult(
                    name="Fonts",
                    status="WARNING",
                    message=f"{len(missing)} common fonts not found",
                    detail=f"Missing: {', '.join(missing)}"
                )

            return DiagnosticResult(
                name="Fonts",
                status="OK",
                message="Common fonts installed",
                detail=f"{len(installed)} fonts available"
            )
        except Exception as e:
            return DiagnosticResult(
                name="Fonts",
                status="INFO",
                message="Font check skipped",
                detail=str(e)
            )

    def check_keyring(self) -> DiagnosticResult:
        """Check OS keyring availability for secret storage."""
        from pageout.core.secrets import keyring_available

        if keyring_available():
            return DiagnosticResult(
                name="OS Keyring",
                status="OK",
                message="Keyring available",
                detail="Secrets will be stored securely in OS credential store"
            )

        allow_plaintext = self.cfg.get("allow_plaintext_secrets", False)

        if allow_plaintext:
            return DiagnosticResult(
                name="OS Keyring",
                status="WARNING",
                message="No keyring - using plain text",
                detail="Install 'pip install keyring' for secure storage, or allow plain-text storage"
            )

        return DiagnosticResult(
            name="OS Keyring",
            status="WARNING",
            message="Keyring not available",
            detail="Install 'pip install keyring' for secure token storage"
        )

    def check_app_version(self) -> DiagnosticResult:
        """Check application version."""
        from pageout.core.config import APP_NAME, APP_VERSION, APP_STAGE

        return DiagnosticResult(
            name="App Version",
            status="INFO",
            message=f"{APP_NAME} {APP_VERSION} ({APP_STAGE})",
            detail="Current running version"
        )


def run_diagnostics(cfg: Optional[Dict] = None) -> List[Dict]:
    """Run all diagnostics and return a list of dicts for serialization.

    This is the main entry point for the "Check my setup" feature.
    """
    collector = DiagnosticsCollector(cfg)
    results = collector.run_all()

    return [
        {
            "name": r.name,
            "status": r.status,
            "message": r.message,
            "detail": r.detail,
            "critical": r.critical
        }
        for r in results
    ]


def get_diagnostics_summary(results: List[Dict]) -> Tuple[str, bool]:
    """Get a summary of diagnostics results.

    Returns:
        (summary_message, has_critical_issues)
    """
    errors = [r for r in results if r["status"] == "ERROR"]
    warnings = [r for r in results if r["status"] == "WARNING"]

    has_critical = any(r.get("critical", False) for r in errors)

    if has_critical:
        return f"Found {len(errors)} critical issue(s). Check diagnostics for details.", True
    elif errors:
        return f"Found {len(errors)} error(s).", False
    elif warnings:
        return f"Found {len(warnings)} warning(s).", False
    else:
        return "No issues found.", False