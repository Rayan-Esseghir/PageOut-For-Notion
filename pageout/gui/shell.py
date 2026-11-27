"""U2: Look & Navigation - Shell components for the PageOut GUI.

This module provides the top-level UI shell including:
- Sidebar navigation (replaces horizontal tabs)
- Menu bar (File / Profiles / Tools / Help)
- Status bar with progress indicator
- Simple/Advanced mode toggle
- Keyboard shortcuts
- Theme selector integration
"""

import os
import sys
import tkinter as tk
from tkinter import messagebox, ttk

from pageout.core.config import DEFAULTS
from pageout.gui.i18n import EN, _, set_language
from pageout.gui.widgets import CheckList, FontPicker, SidebarNav, ThemeSelector, UIScaleSelector, ModeToggle
from pageout.gui.theme import ThemeManager, HiDPISupport


class ShellUI:
    """Top-level UI shell for the PageOut application.

    This class manages:
    - Main window layout with sidebar navigation
    - Menu bar
    - Status bar
    - Simple/Advanced mode
    - Keyboard shortcuts
    - Theme switching
    """

    def __init__(self, root, app_ui, presenter):
        self.root = root
        self.app = app_ui
        self.presenter = presenter
        self.theme_manager = ThemeManager(root)
        self._sidebar = None
        self._menu_bar = None
        self._status_bar = None
        self._mode_toggle_var = tk.StringVar(value=DEFAULTS.get("ui_mode", "advanced"))

        # Initialize theme from config
        saved_theme = self.app.V.get("theme", tk.StringVar(value="light")).get()
        self.theme_manager.apply_theme(saved_theme)

        # Initialize UI scale from config
        saved_scale = self.app.V.get("ui_scale", tk.DoubleVar(value=1.0)).get()
        self.theme_manager.set_ui_scale(saved_scale)

    def build_shell(self):
        """Build the complete shell UI."""
        self._build_menu_bar()
        self._build_main_layout()
        self._build_status_bar()
        self._setup_keyboard_shortcuts()
        self._apply_window_geometry()

    def _build_menu_bar(self):
        """Build the application menu bar."""
        self._menu_bar = tk.Menu(self.root)
        self.root.config(menu=self._menu_bar)

        # File menu
        file_menu = tk.Menu(self._menu_bar, tearoff=0)
        self._menu_bar.add_cascade(label=_("menu_file"), menu=file_menu)
        file_menu.add_command(label=_("menu_new"), accelerator="Ctrl+N", command=self.presenter.new_config)
        file_menu.add_command(label=_("menu_open_config"), command=self.presenter.open_config_folder)
        file_menu.add_separator()
        file_menu.add_command(label=_("menu_save_profile"), command=self.presenter.save_profile)
        file_menu.add_command(label=_("menu_load_profile"), command=self.presenter.load_profile)
        file_menu.add_command(label=_("menu_manage_profiles"), command=self.presenter.manage_profiles)
        file_menu.add_separator()
        file_menu.add_command(label=_("menu_export_settings"), command=self.presenter.export_settings)
        file_menu.add_command(label=_("menu_import_settings"), command=self.presenter.import_settings)
        file_menu.add_separator()
        file_menu.add_command(label=_("menu_preferences"), accelerator="Ctrl+,", command=self.presenter.show_preferences)
        file_menu.add_separator()
        file_menu.add_command(label=_("menu_exit"), accelerator="Alt+F4", command=self.presenter.on_close)

        # Profiles menu (shortcuts)
        profiles_menu = tk.Menu(self._menu_bar, tearoff=0)
        self._menu_bar.add_cascade(label=_("menu_profiles"), menu=profiles_menu)
        profiles_menu.add_command(label=_("menu_save_profile"), command=self.presenter.save_profile)
        profiles_menu.add_command(label=_("menu_load_profile"), command=self.presenter.load_profile)
        profiles_menu.add_command(label=_("menu_manage_profiles"), command=self.presenter.manage_profiles)

        # Tools menu
        tools_menu = tk.Menu(self._menu_bar, tearoff=0)
        self._menu_bar.add_cascade(label=_("menu_tools"), menu=tools_menu)
        tools_menu.add_command(label=_("menu_load_props"), accelerator="Ctrl+L", command=self.presenter.load_properties)
        tools_menu.add_command(label=_("menu_load_pages"), accelerator="F5", command=self.presenter.load_pages)
        tools_menu.add_command(label=_("menu_preview_names"), command=self.presenter.preview_names)
        tools_menu.add_separator()
        tools_menu.add_command(label=_("menu_validate"), command=self.presenter.validate_settings)
        tools_menu.add_command(label=_("menu_clear_cache"), command=self.presenter.clear_cache)
        tools_menu.add_separator()
        tools_menu.add_command(label=_("menu_export_queue"), accelerator="Ctrl+Q", command=self.presenter.show_queue)
        tools_menu.add_command(label=_("menu_view_timing_report"), command=self.presenter.show_timing_report)

        # Help menu
        help_menu = tk.Menu(self._menu_bar, tearoff=0)
        self._menu_bar.add_cascade(label=_("menu_help"), menu=help_menu)
        help_menu.add_command(label=_("check_my_setup"), command=self.presenter.check_my_setup)
        help_menu.add_command(label=_("menu_shortcuts"), command=self.presenter.show_shortcuts)
        help_menu.add_command(label=_("menu_about"), command=self.presenter.show_about)

    def _build_main_layout(self):
        """Build the main window layout with sidebar and content area."""
        # Main container
        self.main_container = ttk.Frame(self.root)
        self.main_container.pack(fill="both", expand=True)

        # Sidebar navigation (left side)
        self._build_sidebar()

        # Content area (right side)
        self._build_content_area()

    def _build_sidebar(self):
        """Build the sidebar navigation."""
        sidebar_frame = ttk.Frame(self.main_container, width=200)
        sidebar_frame.pack(side="left", fill="y", padx=(8, 4), pady=8)
        sidebar_frame.pack_propagate(False)

        # App title/logo at top of sidebar
        title_frame = ttk.Frame(sidebar_frame)
        title_frame.pack(fill="x", pady=(0, 12))

        try:
            from pageout.core.paths import resource_path
            from PIL import Image, ImageTk
            # Icons are in the assets/ subdirectory
            assets_dir = resource_path("").parent / "pageout" / "assets"
            for ext in (".png", ".ico"):
                ip = assets_dir / ("icon" + ext)
                if ip.exists():
                    icon_img = ImageTk.PhotoImage(
                        Image.open(str(ip)).convert("RGBA").resize((32, 32), Image.LANCZOS)
                    )
                    ttk.Label(title_frame, image=icon_img).pack(side="left", padx=(0, 8))
                    self._sidebar_icon = icon_img  # Keep reference
                    break
        except Exception:
            pass

        ttk.Label(title_frame, text="PageOut", style="Head.TLabel").pack(side="left")

        # Mode toggle (Simple/Advanced)
        self._build_mode_toggle(sidebar_frame)

        # Sidebar navigation items
        nav_items = [
            ("1  Source", "1  Source"),
            ("2  Pages", "2  Pages"),
            ("3  Formats", "3  Formats"),
            ("4  Design", "4  Design"),
            ("5  Images", "5  Images"),
            ("6  PDF", "6  PDF"),
            ("7  LaTeX & AI", "7  LaTeX & AI"),
            ("8  Output", "8  Output"),
        ]

        self._sidebar = SidebarNav(
            sidebar_frame,
            items=nav_items,
            command=self._on_sidebar_select,
        )
        self._sidebar.pack(fill="both", expand=True, pady=(8, 0))

        # Theme selector at bottom of sidebar
        self._build_sidebar_footer(sidebar_frame)

    def _build_mode_toggle(self, parent):
        """Build the Simple/Advanced mode toggle."""
        self.mode_toggle = ModeToggle(
            parent,
            variable=self._mode_toggle_var,
            on_change=self._on_mode_change,
        )
        self.mode_toggle.pack(fill="x", pady=(0, 8))

    def _build_sidebar_footer(self, parent):
        """Build the footer area of sidebar with theme/UI scale selectors."""
        footer = ttk.Frame(parent)
        footer.pack(side="bottom", fill="x", pady=(8, 0))

        # Separator
        ttk.Separator(footer, orient="horizontal").pack(fill="x", pady=(0, 8))

        # Theme selector
        self.theme_selector = ThemeSelector(
            footer,
            variable=self.app.V.get("theme", tk.StringVar(value="light")),
            command=self._on_theme_change,
        )
        self.theme_selector.pack(fill="x", pady=2)

        # UI Scale selector
        self.scale_selector = UIScaleSelector(
            footer,
            variable=self.app.V.get("ui_scale", tk.DoubleVar(value=1.0)),
            command=self._on_scale_change,
        )
        self.scale_selector.pack(fill="x", pady=2)

    def _build_content_area(self):
        """Build the main content area (replaces ttk.Notebook)."""
        self.content_frame = ttk.Frame(self.main_container)
        self.content_frame.pack(side="left", fill="both", expand=True, padx=(4, 8), pady=8)

        # This will hold the individual page frames
        self.page_frames = {}
        self.current_page = None

        # Create all page frames (lazily or eagerly)
        self._create_page_frames()

        # Show the first page by default
        self._show_page("1  Source")

    def _create_page_frames(self):
        """Create all page frames for the sidebar navigation."""
        # Import the page builders from app
        page_builders = {
            "1  Source": self.app.build_source_page,
            "2  Pages": self.app.build_pages_page,
            "3  Formats": self.app.build_formats_page,
            "4  Design": self.app.build_design_page,
            "5  Images": self.app.build_images_page,
            "6  PDF": self.app.build_pdf_page,
            "7  LaTeX & AI": self.app.build_latex_page,
            "8  Output": self.app.build_output_page,
        }

        for page_name, builder in page_builders.items():
            # Create a frame for each page
            frame = ttk.Frame(self.content_frame)
            self.page_frames[page_name] = frame
            # Build the page content
            builder(frame)

    def _show_page(self, page_name):
        """Show a specific page by name."""
        if page_name not in self.page_frames:
            return

        # Hide current page
        if self.current_page and self.current_page in self.page_frames:
            self.page_frames[self.current_page].pack_forget()

        # Show new page
        self.page_frames[page_name].pack(fill="both", expand=True)
        self.current_page = page_name

        # Update sidebar selection
        if self._sidebar:
            self._sidebar.set_active(page_name)

        # Update last_page in config
        if "last_page" in self.app.V:
            self.app.V["last_page"].set(page_name)

    def _switch_page(self, page_name):
        """Switch to a specific page (called from sidebar)."""
        self._show_page(page_name)

    def _on_sidebar_select(self, page_name):
        """Handle sidebar selection."""
        self._show_page(page_name)

    def _on_mode_change(self, event=None):
        """Handle Simple/Advanced mode change."""
        mode = self._mode_toggle_var.get()
        if "ui_mode" in self.app.V:
            self.app.V["ui_mode"].set(mode)

        # Show/hide advanced tabs based on mode
        if mode == "simple":
            # In simple mode, only show Source, Formats, Output
            simple_pages = ["1  Source", "3  Formats", "8  Output"]
            for page_name, frame in self.page_frames.items():
                if page_name not in simple_pages:
                    frame.pack_forget()
            # Ensure we're on a simple page
            if self.current_page not in simple_pages:
                self._show_page("1  Source")
        else:
            # Advanced mode - show all pages
            pass  # All pages are available

    def _on_theme_change(self, theme_name):
        """Handle theme change."""
        self.theme_manager.apply_theme(theme_name)
        if "theme" in self.app.V:
            self.app.V["theme"].set(theme_name)

        # Update dark/light specific UI
        self._update_theme_ui()

    def _on_scale_change(self, scale):
        """Handle UI scale change."""
        self.theme_manager.set_ui_scale(scale)
        if "ui_scale" in self.app.V:
            self.app.V["ui_scale"].set(scale)

    def _update_theme_ui(self):
        """Update UI elements that depend on theme."""
        # Update log box background
        if hasattr(self.app, 'log_box'):
            if self.theme_manager.is_dark():
                self.app.log_box.config(bg="#2d2d2d", fg="#f3f4f6", insertbackground="#f3f4f6")
            else:
                self.app.log_box.config(bg="#f7f7f7", fg="#000000", insertbackground="#000000")

    def _build_status_bar(self):
        """Build the status bar at the bottom."""
        self._status_bar = ttk.Frame(self.root)
        self._status_bar.pack(side="bottom", fill="x", padx=8, pady=(0, 8))

        # Left side: status message
        self.status_var = tk.StringVar(value=_("status_ready"))
        ttk.Label(self._status_bar, textvariable=self.status_var, style="Hint.TLabel").pack(side="left")

        # Right side: progress bar and cancel button
        self.progress_frame = ttk.Frame(self._status_bar)
        self.progress_frame.pack(side="right")

        self.progress_bar = ttk.Progressbar(self.progress_frame, mode="determinate", length=200)
        self.progress_bar.pack(side="left", padx=(0, 8))

        self.cancel_btn = ttk.Button(
            self.progress_frame,
            text=_("cancel"),
            command=self.presenter.cancel_export,
            state="disabled"
        )
        self.cancel_btn.pack(side="left")

    def set_status(self, message: str):
        """Update status bar message."""
        self.status_var.set(message)

    def set_progress(self, current: int, total: int):
        """Update progress bar."""
        self.progress_bar.config(maximum=max(total, 1), value=current)

    def set_running(self, running: bool):
        """Update UI for running state."""
        if hasattr(self.app, 'export_btn'):
            self.app.export_btn.config(state="disabled" if running else "normal")
        self.cancel_btn.config(state="normal" if running else "disabled")
        self.set_status(_("status_exporting") if running else _("status_ready"))

    def _setup_keyboard_shortcuts(self):
        """Set up keyboard shortcuts."""
        shortcuts = {
            "<Control-e>": lambda e: self.presenter.start_export(),
            "<Control-s>": lambda e: self.presenter.save_config(),
            "<Control-l>": lambda e: self.presenter.load_properties(),
            "<F5>": lambda e: self.presenter.load_pages(),
            "<Escape>": lambda e: self.presenter.cancel_export(),
            "<Control-f>": lambda e: self._show_find_dialog(),
            "<Control-comma>": lambda e: self.presenter.show_preferences(),
            "<Control-1>": lambda e: self._switch_page("1  Source"),
            "<Control-2>": lambda e: self._switch_page("2  Pages"),
            "<Control-3>": lambda e: self._switch_page("3  Formats"),
            "<Control-4>": lambda e: self._switch_page("4  Design"),
            "<Control-5>": lambda e: self._switch_page("5  Images"),
            "<Control-6>": lambda e: self._switch_page("6  PDF"),
            "<Control-7>": lambda e: self._switch_page("7  LaTeX & AI"),
            "<Control-8>": lambda e: self._switch_page("8  Output"),
            "<Control-Tab>": lambda e: self._next_tab(),
            "<Control-Shift-Tab>": lambda e: self._prev_tab(),
        }

        for key, cmd in shortcuts.items():
            self.root.bind_all(key, cmd)

    def _show_find_dialog(self):
        """Show find in log dialog."""
        if not hasattr(self.app, 'log_box'):
            return

        dialog = tk.Toplevel(self.root)
        dialog.title("Find in Log")
        dialog.geometry("350x120")
        dialog.transient(self.root)
        dialog.grab_set()

        ttk.Label(dialog, text="Search:").pack(anchor="w", padx=10, pady=(10, 0))

        search_var = tk.StringVar()
        search_entry = ttk.Entry(dialog, textvariable=search_var, width=40)
        search_entry.pack(fill="x", padx=10, pady=5)
        search_entry.focus_set()

        def do_find():
            text = search_var.get()
            if not text:
                return
            log_box = self.app.log_box
            log_box.tag_remove("find_highlight", "1.0", "end")
            idx = "1.0"
            while True:
                idx = log_box.search(text, idx, "end", nocase=True)
                if not idx:
                    break
                end_idx = f"{idx}+{len(text)}c"
                log_box.tag_add("find_highlight", idx, end_idx)
                idx = end_idx
            log_box.tag_config("find_highlight", background="yellow", foreground="black")
            if log_box.tag_ranges("find_highlight"):
                log_box.see(log_box.tag_ranges("find_highlight")[0])

        def do_close():
            self.app.log_box.tag_remove("find_highlight", "1.0", "end")
            dialog.destroy()

        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(fill="x", padx=10, pady=10)
        ttk.Button(btn_frame, text="Find", command=do_find).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="Close", command=do_close).pack(side="left")

        dialog.protocol("WM_DELETE_WINDOW", do_close)

    def _next_tab(self):
        """Switch to next tab."""
        pages = [
            "1  Source", "2  Pages", "3  Formats", "4  Design",
            "5  Images", "6  PDF", "7  LaTeX & AI", "8  Output"
        ]
        if self.current_page in pages:
            idx = pages.index(self.current_page)
            next_idx = (idx + 1) % len(pages)
            # Skip hidden pages in simple mode
            mode = self._mode_toggle_var.get()
            if mode == "simple" and pages[next_idx] not in ["1  Source", "3  Formats", "8  Output"]:
                next_idx = (next_idx + 1) % len(pages)
            self._switch_page(pages[next_idx])

    def _prev_tab(self):
        """Switch to previous tab."""
        pages = [
            "1  Source", "2  Pages", "3  Formats", "4  Design",
            "5  Images", "6  PDF", "7  LaTeX & AI", "8  Output"
        ]
        if self.current_page in pages:
            idx = pages.index(self.current_page)
            prev_idx = (idx - 1) % len(pages)
            # Skip hidden pages in simple mode
            mode = self._mode_toggle_var.get()
            if mode == "simple" and pages[prev_idx] not in ["1  Source", "3  Formats", "8  Output"]:
                prev_idx = (prev_idx - 1) % len(pages)
            self._switch_page(pages[prev_idx])

    def _apply_window_geometry(self):
        """Apply saved window geometry."""
        geom = self.app.V.get("window_geometry", tk.StringVar(value="")).get()
        state = self.app.V.get("window_state", tk.StringVar(value="normal")).get()

        if geom:
            try:
                self.root.geometry(geom)
            except Exception:
                pass

        if state == "zoomed":
            try:
                self.root.state("zoomed")
            except Exception:
                pass

        # Apply saved last_page
        last_page = self.app.V.get("last_page", tk.StringVar(value="1  Source")).get()
        if last_page in self.page_frames:
            self._show_page(last_page)

    def save_window_geometry(self):
        """Save current window geometry."""
        if "window_geometry" in self.app.V:
            self.app.V["window_geometry"].set(self.root.geometry())
        if "window_state" in self.app.V:
            self.app.V["window_state"].set(self.root.state())


def create_shell(root, app_ui, presenter):
    """Factory function to create and build the shell UI."""
    shell = ShellUI(root, app_ui, presenter)
    shell.build_shell()
    return shell