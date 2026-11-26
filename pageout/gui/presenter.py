"""Presenter/Controller module for the PageOut GUI.

This module implements the Model-View-Presenter pattern, where:
- View = the tkinter widgets (app.py)
- Presenter = this module (presenter.py)
- Model = the core pipeline and config logic

The presenter handles:
- User input validation
- Binding UI events to pipeline operations
- State management between tabs
- Error handling and user feedback
"""

import tkinter as tk
from tkinter import messagebox
from typing import Any, Dict, List, Optional, Tuple

from pageout.core.config import load_config, DEFAULTS, save_config
from pageout.core.errors import Cancelled
from pageout.core.pipeline import Exporter, export
from pageout.core.secrets import keyring_available, redact
from pageout.gui.i18n import EN, get_string, _


class Presenter:
    """Presenter class that manages GUI state and coordinates with the pipeline."""

    def __init__(self, root, app_ui):
        self.root = root
        self.app = app_ui  # Reference to the App class
        self.cfg = {}
        self.timing_report = None
        self._unsaved_changes = False
        self._last_config_save = None

        # Bind config changes to track unsaved changes
        self._bind_config_traces()

    def _bind_config_traces(self):
        """Bind traces to all config variables to track changes."""
        for key in DEFAULTS:
            if key in self.app.V:
                self.app.V[key].trace_add(
                    "write",
                    lambda name, index, mode, k=key: self._on_config_changed(k),
                )

    def _on_config_changed(self, key: str):
        """Called when a config variable changes."""
        self._unsaved_changes = True
        # Auto-save logic could go here
        # For now, just track the change

    def save_config(self, force: bool = False) -> Optional[str]:
        """Save current config. Returns warning message or None.

        Args:
            force: If True, saves even if keyring not available and allow_plaintext is off.

        Returns:
            Warning string if secrets couldn't be saved, None on success.
        """
        try:
            # Collect current values from UI
            c = self.app.collect()
            return save_config(c)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save config: {e}")
            return None

    def reset_config_from_file(self):
        """Reset UI config from the current config file."""
        try:
            self.cfg = load_config()
            # Update all UI variables from loaded config
            for key, default in DEFAULTS.items():
                if key in self.app.V:
                    val = self.cfg.get(key, default)
                    if isinstance(default, bool):
                        self.app.V[key].set(bool(val))
                    elif isinstance(default, int):
                        self.app.V[key].set(int(val))
                    elif isinstance(default, float):
                        self.app.V[key].set(float(val))
                    else:
                        self.app.V[key].set(str(val))
            # Update unsaved changes tracking
            self._unsaved_changes = False
            self._last_config_save = tk.datetime.datetime.now()
        except Exception as e:
            # Log but don't crash
            pass

    def validate_basic(self, c: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """Validate basic required fields.

        Returns:
            (is_valid, error_message) tuple.
        """
        if not c.get("token", "").strip():
            return False, EN["missing_info_msg"] if hasattr(EN, "missing_info_msg") else "Enter the Notion token and a database / page ID or URL."
        if not c.get("database", "").strip():
            return False, EN["missing_info_msg"] if hasattr(EN, "missing_info_msg") else "Enter the Notion token and a database / page ID or URL."
        if not c.get("save_dir", "").strip():
            return False, EN["missing_folder_msg"] if hasattr(EN, "missing_folder_msg") else "Choose an output folder on the Output tab."
        return True, None

    def start_export(self):
        """Start the export process with validation."""
        try:
            c = self.app.collect()
        except Exception:
            messagebox.showerror("Invalid value", EN["invalid_value_msg"] if hasattr(EN, "invalid_value_msg") else "Check the numeric fields.")
            return False

        if not self.validate_basic(c)[0]:
            return False

        # Check for missing folder
        if not c["save_dir"].strip():
            messagebox.showerror("Missing folder", EN["missing_folder_msg"] if hasattr(EN, "missing_folder_msg") else "Choose an output folder on the Output tab.")
            return False

        # Check for Gemini math OCR requirements
        if c.get("gemini_math_ocr"):
            if not hasattr(__import__('pageout.ocr.gemini', fromlist=['_GENAI_AVAILABLE']), '_GENAI_AVAILABLE'):
                messagebox.showerror(
                    "Package Missing",
                    EN["genai_required"] if hasattr(EN, "genai_required") else "The 'google-genai' library is required for Gemini Math OCR.\n\nPlease install it with:\n  pip install google-genai",
                )
                return False
            if not c.get("gemini_api_key", "").strip():
                messagebox.showerror(
                    "Gemini API Key Required",
                    EN["gemini_key_required"] if hasattr(EN, "gemini_key_required") else "Math OCR with Gemini Vision is enabled, but no Gemini API Key was entered.\n\nPlease enter your personal Gemini API key in the 'LaTeX & AI' tab.\nYou can get a free key at:\nhttps://aistudio.google.com/",
                )
                return False

        # Show warnings about secrets
        warn = save_config(c)
        if warn:
            messagebox.showwarning("Secrets not saved", warn)

        # Check if pages need loading
        shown = self.app.props_list.selected_labels() if hasattr(self.app, 'props_list') else []
        selected = None
        if self.app.loaded_pages and self.app.loaded_source == c["database"].strip():
            sel = self.app.pages_list.selected_indices() if hasattr(self.app, 'pages_list') else []
            if not sel:
                messagebox.showerror(
                    "No pages ticked",
                    EN["no_pages_selected"] if hasattr(EN, "no_pages_selected") else "Tick at least one page in tab 2, or clear the list by loading pages again.",
                )
                return False
            selected = [self.app.loaded_pages[i] for i in sel]

        # Start export
        self.app.cancel.clear()
        self.app.set_running(True)
        self.app.bar.config(value=0)

        def worker():
            try:
                res = export(
                    c,
                    self.app.progress,
                    self.app.cancel,
                    self.app.log,
                    selected_roots=selected,
                    all_props=self.app.loaded_props,
                    shown_props=shown,
                )
                timing_summary = res.timing.summary() if res.timing else None
                # Use root.after to update UI from thread
                self.root.after(0, lambda: self._export_done(res, timing_summary))
            except Cancelled:
                self.root.after(0, lambda: self._export_done_cancelled())
            except Exception as e:
                redacted = redact(e, [c.get("token", ""), c.get("gemini_api_key", "")])
                self.root.after(0, lambda: self._export_error(redacted))

        import threading
        threading.Thread(target=worker, daemon=True).start()
        return True

    def _export_done(self, res, timing_summary):
        """Handle export completion."""
        self.app.set_running(False)
        count = res.total
        skipped = res.skipped
        text = f"Exported {count - skipped} page(s)."
        if skipped:
            text += f"\n{skipped} unchanged page(s) skipped (tick “Force full re-export” to redo them)."
        if timing_summary:
            text += f"\n\nTiming: {timing_summary}"
        text += f"\n\n{res.out_dir}"

        # Show results
        if res.last_tex:
            self.app.last_latex_text = res.last_tex
            self.app.copy_latex_btn.config(state="normal")
            text += "\n\nLaTeX export ready! Click '📋 Copy LaTeX' to copy."

        if res.failed:
            text += f"\n\n{len(res.failed)} problem(s):\n" + "\n".join(f"- {f}: {r}" for f, r in res.failed[:10])

        messagebox.showinfo("Done", text)
        try:
            self.app.open_folder(res.out_dir)
        except Exception:
            pass

    def _export_done_cancelled(self):
        """Handle export cancellation."""
        self.app.set_running(False)
        self.app.append_log(EN["cancelled"] if hasattr(EN, "cancelled") else "Cancelled. Files exported so far were kept.")

    def _export_error(self, error_msg: str):
        """Handle export error."""
        self.app.set_running(False)
        messagebox.showerror("Export failed", error_msg)

    def cancel_export(self):
        """Cancel the current export."""
        self.app.cancel.set()
        self.app.append_log(EN["cancel"] if hasattr(EN, "cancel") else "Cancelling after the current page...")

    def do_login(self):
        """Handle login button click."""
        self.app.login_btn.config(state="disabled")

        def worker():
            try:
                from pageout.renderers.pdf import login_to_notion
                login_to_notion(self.app.log)
            except Exception as e:
                self.app.log("Login window error: " + str(e))
            self.app.q.put(("loginend",))

        import threading
        threading.Thread(target=worker, daemon=True).start()

    def load_properties(self):
        """Load Notion page properties."""
        c = self.app.collect()
        if not self.validate_basic(c)[0]:
            return

        def work():
            from pageout.sources.notion_api import load_property_names
            from pageout.core.config import load_config

            # Create a client
            from notion_client import Client
            client = Client(auth=c["token"])
            return load_property_names(client, c["database"], c["source_type"])

        def done(names, err):
            if err:
                messagebox.showerror("Could not load properties", str(err))
                return
            self.app.loaded_props = names
            self.app.props_list.set_items(names)
            # Update sort and filter combos
            from pageout.core.config import SORT_BUILTIN
            self.app.sort_combo.config(values=SORT_BUILTIN + names)
            self.app.filter_combo.config(values=[""] + names + ["Title", "Date"])
            # Build hint string
            hint = (
                "Placeholders: {title} {date} {index} {created} {edited} {parent}\n"
                "Your properties: "
                + " ".join("{%s}" % n for n in names)
                + "\nFormats: {date:%d-%m-%Y}   {title:40} (truncate)"
            )
            self.app.hint.set(hint)
            self.app.append_log(f"Loaded {len(names)} properties.")

        import threading
        self.root.bg(work, done)

    def load_pages(self):
        """Load pages from Notion."""
        c = self.app.collect()
        if not self.validate_basic(c)[0]:
            return

        def work():
            from pageout.core.pipeline import Exporter

            return Exporter(c).fetch_roots()

        def done(pages, err):
            if err:
                messagebox.showerror("Could not load pages", str(err))
                return
            self.app.loaded_pages, self.app.loaded_source = pages, c["database"].strip()
            labels = []
            for p in pages:
                from pageout.sources.notion_api import page_fields
                f = page_fields(p, i=0, n=2)  # Simplified
                labels.append(f"{f.get('date', '—')}   {f.get('title', '')}")
            self.app.pages_list.set_items(labels)
            self.app.append_log(f"Loaded {len(pages)} pages. Deselect the ones you don't want.")

        import threading
        self.root.bg(lambda: Exporter(c).fetch_roots(), done)

    def preview_names(self):
        """Preview file names based on current config."""
        try:
            c = self.app.collect()
        except Exception:
            messagebox.showerror("Invalid value", EN["invalid_value_msg"] if hasattr(EN, "invalid_value_msg") else "Check the numeric fields.")
            return

        if not self.validate_basic(c)[0]:
            return

        def work():
            from pageout.core.pipeline import Exporter

            return Exporter(c).fetch_roots()[:8]

        def done(pages, err):
            if err:
                messagebox.showerror("Preview failed", str(err))
                return
            from pageout.core.naming import build_name
            from pageout.sources.notion_api import page_fields

            names = [build_name(c["name_format"], page_fields(p, i, 2)) for i, p in enumerate(pages, 1)]
            img = [
                build_name(
                    c["img_format"], dict(page_fields(p, i, 2), page=n, n="01", caption="caption", original="image")
                )
                for i, (p, n) in enumerate(zip(pages, names), 1)
            ][:3]
            messagebox.showinfo(
                "Name preview",
                "Files:\n" + "\n".join(names) + "\n\nImages:\n" + "\n".join(x + ".png" for x in img),
            )

        import threading
        self.root.bg(work, done)

    def choose_folder(self):
        """Open folder selection dialog."""
        from tkinter import filedialog

        d = filedialog.askdirectory(title="Choose output folder")
        if d:
            self.app.V["save_dir"].set(d)

    def choose_icon_file(self):
        """Choose custom icon file."""
        from tkinter import filedialog

        p = filedialog.askopenfilename(
            title="Choose custom icon image",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.gif *.webp *.svg"), ("All files", "*.*")],
        )
        if p:
            self.app.V["icon_custom_file"].set(p)

    def select_pages(self, all_: bool = False):
        """Select/deselect all pages."""
        if hasattr(self.app, 'pages_list'):
            self.app.pages_list.select_all(all_)

    def on_close(self):
        """Handle window close event."""
        try:
            # Save config on close
            warn = self.save_config()
            if warn:
                if not messagebox.askyes(
                    "Unsaved changes",
                    f"You have unsaved changes.\n{warn}\n\nSave anyway?",
                ):
                    return  # Don't close
            self.root.destroy()
        except Exception:
            self.root.destroy()


def main():
    """Main entry point for the GUI presenter module."""
    import tkinter as tk
    from pageout.gui.app import App

    root = tk.Tk()
    app_ui = App()
    presenter = Presenter(root, app_ui)
    app_ui.presenter = presenter  # Link presenter to UI
    root.protocol("WM_DELETE_WINDOW", presenter.on_close)
    root.mainloop()