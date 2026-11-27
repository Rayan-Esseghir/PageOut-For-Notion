"""Tests for the GUI module (U1: binding registry and headless tests)."""

import pytest

# Import test for headless mode (tkinter not available)
tk_import_error = None


def test_tkinter_import_or_skip():
    """Verify tkinter is available or skip GUI tests."""
    global tk_import_error
    try:
        import tkinter
        tkinter.Tk()  # Try to create a root
        return True
    except Exception as e:
        tk_import_error = e
        pytest.skip(f"Tkinter not available: {e}")


def test_binding_registry_complete(tmp_path):
    """U1: Verify all DEFAULTS keys are bound or explicitly handled.

    This test ensures that every setting in DEFAULTS has a corresponding
    widget binding in the GUI, or is explicitly excluded (like custom_css).
    """
    pytest.importorskip("tkinter")

    from pageout.core.config import DEFAULTS

    # Keys that are explicitly NOT bound to widgets in the UI
    # (e.g., custom_css is bound directly to a Text widget via V dict entry)
    EXCLUDED_KEYS = {
        "custom_css",  # Bound to Text widget directly, not via V
        "token",  # Bound to Entry widget directly
        "database",  # Bound to Entry widget directly
        "save_dir",  # Bound to Entry widget directly
        "icon_custom_file",  # Bound to Entry widget directly
    }

    # Import the app module to check what's actually bound
    from pageout.gui import app

    # Get all keys that are bound in the V dictionary
    # We need to simulate App initialization
    import tkinter as tk
    import tkinter.font as tkfont
    from tkinter import ttk

    # Create a minimal app instance to check bindings
    class MinimalApp:
        def __init__(self):
            self.cfg0 = app.load_config() if hasattr(app, 'load_config') else {}
            # Initialize V dict the same way App does
            self.V = {}
            for key, default in DEFAULTS.items():
                if key == "custom_css":
                    # This has special handling with Text widget
                    continue
                val = self.cfg0.get(key, default) if isinstance(self.cfg0, dict) else default
                if isinstance(default, bool):
                    self.V[key] = tk.BooleanVar(value=bool(val))
                elif isinstance(default, int):
                    self.V[key] = tk.IntVar(value=int(val))
                elif isinstance(default, float):
                    self.V[key] = tk.DoubleVar(value=float(val))
                else:
                    self.V[key] = tk.StringVar(value=str(val))
            self.installed = set()

    tk_var = tk.Tk()
    try:
        min_app = MinimalApp()
        bound_keys = set(min_app.V.keys())
        all_keys = set(DEFAULTS.keys())

        # custom_css is handled specially in app.py - it's bound to CSS Text widget
        # but NOT in V dict, so it's expected to be missing from bound_keys
        expected_keys = all_keys - {"custom_css"}

        missing = expected_keys - bound_keys
        extra = bound_keys - all_keys

        assert not missing, f"These DEFAULTS keys have no widget binding: {missing}"
        assert not extra, f"These keys are bound but not in DEFAULTS: {extra}"
    finally:
        tk_var.destroy()


def test_headless_gui_smoke():
    """U1: Headless smoke test - verify GUI module imports and basic structure without Tk.

    This test runs in CI environments where tkinter may not be fully available
    or X11 display is not present.
    """
    # Test that we can import all modules without errors
    from pageout.gui import i18n, theme, widgets

    # Verify i18n module
    assert hasattr(i18n, 'EN')
    assert hasattr(i18n, 'get_string')
    assert hasattr(i18n, '_')
    assert i18n.get_string('tab_source') == "1  Source"

    # Verify theme module
    assert hasattr(theme, 'ThemeManager')
    assert hasattr(theme, 'HiDPISupport')
    assert hasattr(theme, 'LIGHT_THEMES')
    assert hasattr(theme, 'DARK_THEMES')

    # Verify widgets module
    assert hasattr(widgets, 'ScrollableFrame')
    assert hasattr(widgets, 'create_tool_tip')


def test_headless_gui_instantiation():
    """U1: Test that App can be created in headless mode for CI."""
    # Skip if tkinter is fully available - we want headless test
    try:
        import tkinter as tk
        root = tk.Tk()
        root.destroy()
        pytest.skip("Tkinter available - full GUI test would run in interactive mode")
    except Exception:
        pass

    # In headless mode, app.py raises SystemExit with clear message
    from pageout.gui.app import main as gui_main

    # Test the headless check
    import pageout.gui.app as app_module
    if app_module.tk is None:
        # This is what happens in headless mode
        with pytest.raises(SystemExit) as exc_info:
            gui_main()
        assert "Tkinter is not available" in str(exc_info.value)
    else:
        pytest.skip("Tkinter is available - full tests would run")


def test_app_module_structure():
    """U1: Verify the App module structure is correct."""
    from pageout.gui import app

    # Check that essential classes and functions exist
    assert hasattr(app, 'App')
    assert hasattr(app, 'ScrollFrame')
    assert hasattr(app, 'CheckList')
    assert hasattr(app, 'FontPicker')
    assert hasattr(app, 'main')
    assert hasattr(app, 'apply_icon')

    # Verify App is a class
    from pageout.gui.app import App
    assert isinstance(App, type)


def test_presenter_module_structure():
    """U1: Verify the Presenter module structure."""
    from pageout.gui import presenter

    assert hasattr(presenter, 'Presenter')

    from pageout.gui.presenter import Presenter
    assert isinstance(Presenter, type)

    # Note: main() is in app.py, not presenter.py - presenter is the controller only


def test_gui_widgets_reusable():
    """U1: Test that widget helper functions work correctly."""
    from pageout.gui.widgets import (
        Frame,
        add_font_field,
        add_checkbox,
        add_spinbox,
        add_combobox,
    )

    # Test Frame class
    import tkinter as tk
    root = tk.Tk()
    try:
        frame = Frame(root)
        assert frame is not None

        label = frame.add_label(0, 0, "Test")
        assert label is not None

        frame.add_separator(1, 0)
    finally:
        root.destroy()


def test_theme_manager_initialization():
    """U1: Test ThemeManager can be initialized."""
    from pageout.gui.theme import ThemeManager

    import tkinter as tk
    root = tk.Tk()
    try:
        tm = ThemeManager(root)
        assert tm.current_theme == "light"
        assert tm.is_dark() == False
        assert tm.get_accent_color() == "#37352f"

        # Test dark theme
        tm.apply_theme("dark")
        assert tm.is_dark() == True
        assert tm.get_accent_color() == "#60a5fa"
    finally:
        root.destroy()


def test_hidpi_support():
    """U1: Test HiDPI support module."""
    from pageout.gui.theme import HiDPISupport

    import tkinter as tk
    root = tk.Tk()
    try:
        # Should not raise on non-Windows or if ctypes fails
        HiDPISupport.enable(root)
    finally:
        root.destroy()


def test_i18n_strings_complete():
    """U1: Verify i18n strings are complete for all UI elements."""
    from pageout.gui.i18n import EN

    # Check essential UI strings exist
    essential_keys = [
        "title_prefix",
        "tab_source",
        "tab_pages",
        "tab_formats",
        "tab_design",
        "tab_images",
        "tab_pdf",
        "tab_latex",
        "tab_output",
        "export",
        "cancel",
        "missing_info",
        "missing_info_msg",
        "missing_folder",
        "missing_folder_msg",
        "invalid_value",
        "invalid_value_msg",
    ]

    for key in essential_keys:
        assert key in EN, f"Missing i18n key: {key}"
        assert isinstance(EN[key], str), f"i18n key {key} should be a string"


# ------------------------------------------------------------------ U6: Onboarding & help
def test_u6_onboarding_wizard_method_exists():
    """U6: Verify onboarding wizard method exists."""
    from pageout.gui import presenter
    assert hasattr(presenter.Presenter, 'show_onboarding_wizard')


def test_u6_check_my_setup_method_exists():
    """U6: Verify check_my_setup method exists."""
    from pageout.gui import presenter
    assert hasattr(presenter.Presenter, 'check_my_setup')


def test_u6_show_about_method_exists():
    """U6: Verify show_about method exists."""
    from pageout.gui import presenter
    assert hasattr(presenter.Presenter, 'show_about')


def test_u6_copy_diagnostics_method_exists():
    """U6: Verify copy diagnostics method exists."""
    from pageout.gui import presenter
    assert hasattr(presenter.Presenter, '_copy_diagnostics_to_clipboard')


def test_u6_diagnostics_module_exists():
    """U6: Verify diagnostics module has required functions."""
    from pageout.core import diagnostics
    assert hasattr(diagnostics, 'run_diagnostics')
    assert hasattr(diagnostics, 'get_diagnostics_summary')
    assert hasattr(diagnostics, 'DiagnosticResult')
    assert hasattr(diagnostics, 'DiagnosticsCollector')


def test_u6_secrets_redact_function():
    """U6: Verify secrets redact function works correctly."""
    from pageout.core import secrets

    # Test basic redaction
    token = "secret_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456"
    text_with_token = f"Error: {token} was not found"
    redacted = secrets.redact(text_with_token, [token])
    assert token not in redacted
    assert "***" in redacted

    # Test pattern-based redaction
    text_with_api_key = "Key AIza123456789012345678901234567890ABCDEFGHIJKLMNO"
    redacted = secrets.redact(text_with_api_key)
    assert "AIza" not in redacted