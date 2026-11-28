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
- Menu bar actions
- Keyboard shortcuts
- Window state persistence
"""

import json
import os
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, ttk
from typing import Any, Dict, Optional, Tuple

from pageout.core.config import APP_NAME, APP_STAGE, APP_VERSION, CONFIG_DIR, DEFAULTS, load_config, save_config
from pageout.core.diagnostics import run_diagnostics
from pageout.core.pipeline import Exporter
from pageout.core.profiles import (
    delete_profile,
    list_profiles,
    load_profile,
    merge_profile_into_config,
    save_profile,
)
from pageout.core.queue import ExportJob, ExportQueue, JobPriority, JobStatus
from pageout.core.scheduler import (
    ScheduleStatus,
    add_schedule,
    disable_schedule,
    enable_schedule,
    get_schedule,
    list_schedules,
    remove_schedule,
)
from pageout.core.secrets import redact
from pageout.core.sources import (
    add_source,
    delete_source,
    extract_id_from_url,
    get_recent_sources,
    get_source,
    list_sources,
    toggle_pin,
)
from pageout.gui.i18n import EN, _


class Presenter:
    """Presenter class that manages GUI state and coordinates with the pipeline."""

    def __init__(self, root, app_ui):
        self.root = root
        self.app = app_ui  # Reference to the App class
        self.cfg = {}
        self.timing_report = None
        self._unsaved_changes = False
        self._last_config_save = None
        self._window_geometry = None

        # Export queue
        self.export_queue = ExportQueue(
            progress_callback=self._on_queue_progress,
            log_callback=self._on_queue_log,
            completion_callback=self._on_queue_complete,
        )

        # Bind config changes to track unsaved changes
        self._bind_config_traces()

        # Load window geometry if available
        self._load_window_geometry()

        # Start queue processor
        self.export_queue.start_processing(max_workers=1)

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
        # Auto-save logic - debounced to avoid excessive writes
        if self.app.V.get("prefs_auto_save", tk.BooleanVar(value=True)).get():
            # Cancel any pending auto-save
            if hasattr(self, "_auto_save_after_id"):
                self.root.after_cancel(self._auto_save_after_id)
            # Schedule auto-save with debounce (500ms)
            self._auto_save_after_id = self.root.after(500, self._auto_save_config)

    def _auto_save_config(self):
        """Auto-save config silently (no error dialogs)."""
        try:
            c = self.app.collect()
            save_config(c)
            self._unsaved_changes = False
            self._last_config_save = __import__("datetime").datetime.now()
        except Exception:
            # Silently ignore auto-save failures
            pass

    def _update_tooltip_delays(self, *args):
        """Update tooltip delays when the preference changes."""
        delay = self.prefs_tooltip_delay.get() if hasattr(self, "prefs_tooltip_delay") else 500
        # Update all existing tooltips in the app
        if hasattr(self.app, "_tooltips"):
            for tooltip in self.app._tooltips:
                tooltip.update_delay(delay)

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
        import json as _json

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
                    elif isinstance(default, list):
                        # For list defaults (like 'sources'), store as JSON string
                        if isinstance(val, list):
                            self.app.V[key].set(_json.dumps(val))
                        else:
                            self.app.V[key].set(str(val))
                    else:
                        self.app.V[key].set(str(val))
            # Update unsaved changes tracking
            self._unsaved_changes = False
            self._last_config_save = __import__("datetime").datetime.now()
        except Exception:
            # Log but don't crash
            pass

    def validate_basic(self, c: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """Validate basic required fields.

        Returns:
            (is_valid, error_message) tuple.
        """
        if not c.get("token", "").strip():
            return False, EN.get("missing_info_msg", "Enter the Notion token and a database / page ID or URL.")
        if not c.get("database", "").strip():
            return False, EN.get("missing_info_msg", "Enter the Notion token and a database / page ID or URL.")
        if not c.get("save_dir", "").strip():
            return False, EN.get("missing_folder_msg", "Choose an output folder on the Output tab.")
        return True, None

    def start_export(self):
        """Start the export process with validation - adds job to queue."""
        try:
            c = self.app.collect()
        except Exception:
            messagebox.showerror("Invalid value", EN.get("invalid_value_msg", "Check the numeric fields."))
            return False

        if not self.validate_basic(c)[0]:
            return False

        # Check for missing folder
        if not c["save_dir"].strip():
            messagebox.showerror(
                "Missing folder", EN.get("missing_folder_msg", "Choose an output folder on the Output tab.")
            )
            return False

        # Check for Gemini math OCR requirements
        if c.get("gemini_math_ocr"):
            if not hasattr(__import__("pageout.ocr.gemini", fromlist=["_GENAI_AVAILABLE"]), "_GENAI_AVAILABLE"):
                messagebox.showerror(
                    "Package Missing",
                    EN.get(
                        "genai_required",
                        "The 'google-genai' library is required for Gemini Math OCR.\n\nPlease install it with:\n  pip install google-genai",
                    ),
                )
                return False
            if not c.get("gemini_api_key", "").strip():
                messagebox.showerror(
                    "Gemini API Key Required",
                    EN.get(
                        "gemini_key_required",
                        "Math OCR with Gemini Vision is enabled, but no Gemini API Key was entered.\n\nPlease enter your personal Gemini API key in the 'LaTeX & AI' tab.\nYou can get a free key at:\nhttps://aistudio.google.com/",
                    ),
                )
                return False

        # Save config (including secrets warning)
        warn = save_config(c)
        if warn:
            if not messagebox.askyesno("Secrets not saved", warn + "\n\nAdd to queue anyway?"):
                return False

        # Check if pages need loading
        shown = self.app.props_list.selected_labels() if hasattr(self.app, "props_list") else []
        selected = None
        if self.app.loaded_pages and self.app.loaded_source == c["database"].strip():
            sel = self.app.pages_list.selected_indices() if hasattr(self.app, "pages_list") else []
            if not sel:
                messagebox.showerror(
                    "No pages ticked",
                    EN.get(
                        "no_pages_selected",
                        "Tick at least one page in tab 2, or clear the list by loading pages again.",
                    ),
                )
                return False
            selected = [self.app.loaded_pages[i] for i in sel]
            # Store selected page IDs in config
            c["_selected_page_ids"] = [p["id"] for p in selected]

        # Add to queue instead of running directly
        from datetime import datetime

        name = f"Export {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        job_id = self.export_queue.add_job(name, c, priority=JobPriority.HIGH)
        self.app.append_log(f"Added to queue: {name} (ID: {job_id})")

        # Refresh queue display if open
        if hasattr(self.app, "refresh_queue_display"):
            self.app.refresh_queue_display()

        messagebox.showinfo(
            "Added to Queue",
            f"Job '{name}' added to export queue.\nID: {job_id}\n\nOpen 'Tools > Export Queue' to monitor progress.",
        )
        return True

    def _export_done(self, res, timing_summary):
        """Handle export completion."""
        self.app.set_running(False)
        count = res.total
        skipped = res.skipped
        text = f"Exported {count - skipped} page(s)."
        if skipped:
            text += f'\n{skipped} unchanged page(s) skipped (tick "Force full re-export" to redo them).'
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
        self.app.append_log(EN.get("cancelled", "Cancelled. Files exported so far were kept."))

    def _export_error(self, error_msg: str):
        """Handle export error."""
        self.app.set_running(False)
        messagebox.showerror("Export failed", error_msg)

    def cancel_export(self):
        """Cancel the current export."""
        self.app.cancel.set()
        self.app.append_log(EN.get("cancel", "Cancelling after the current page..."))

    # === Export Queue Methods ===

    def _on_queue_progress(self, job_id: str, progress: float, message: str):
        """Handle progress updates from queue."""
        job = self.export_queue.get_job(job_id)
        if job:
            self.root.after(0, lambda: self._update_queue_ui(job))
            # Update queue status in main window
            self.root.after(0, lambda: self._update_queue_status())

    def _on_queue_log(self, job_id: str, message: str):
        """Handle log messages from queue."""
        self.root.after(0, lambda: self.app.append_log(f"[{job_id}] {message}"))

    def _on_queue_complete(self, job: ExportJob):
        """Handle job completion."""
        self.root.after(0, lambda: self._handle_job_complete(job))
        # Update queue status
        self.root.after(0, lambda: self._update_queue_status())

    def _update_queue_status(self):
        """Update the queue status display in the main window."""
        if hasattr(self.app, "queue_status"):
            stats = self.export_queue.get_stats()
            running = stats.get("running", 0)
            pending = stats.get("pending", 0)
            if running > 0:
                self.app.queue_status.set(f"Queue: {running} running, {pending} pending")
            elif pending > 0:
                self.app.queue_status.set(f"Queue: {pending} pending")
            else:
                self.app.queue_status.set("")

    def _update_queue_ui(self, job: ExportJob):
        """Update UI for a queue job."""
        if hasattr(self.app, "queue_tree"):
            # Update tree item
            for item in self.app.queue_tree.get_children():
                if self.app.queue_tree.item(item, "values")[0] == job.id:
                    status = job.status.value
                    progress_pct = int(job.progress * 100)
                    self.app.queue_tree.item(
                        item,
                        values=(
                            job.id,
                            job.name,
                            status,
                            f"{progress_pct}%",
                            f"{job.current_page}/{job.total_pages}",
                            job.message[:50],
                        ),
                    )
                    break

        # If this is the running job, update progress bar
        running = self.export_queue.get_running_job()
        if running and running.id == job.id:
            self.app.bar.config(value=job.progress * 100)
            self.app.status_var.set(job.message)

    def _handle_job_complete(self, job: ExportJob):
        """Handle job completion - show notification, update UI."""
        self._update_queue_ui(job)

        if job.status == JobStatus.COMPLETED:
            self.app.append_log(f"Job '{job.name}' completed: {job.message}")
            if job.result:
                out_dir = job.result.get("out_dir", "")
                if out_dir:
                    try:
                        self.app.open_folder(out_dir)
                    except Exception:
                        pass
        elif job.status == JobStatus.FAILED:
            self.app.append_log(f"Job '{job.name}' failed: {job.error}")
            messagebox.showerror("Export Failed", f"Job '{job.name}' failed:\n{job.error}")
        elif job.status == JobStatus.CANCELLED:
            self.app.append_log(f"Job '{job.name}' cancelled")

        # Refresh queue display
        if hasattr(self.app, "refresh_queue_display"):
            self.app.refresh_queue_display()

    def add_to_queue(self, name: str = None, priority: JobPriority = JobPriority.NORMAL):
        """Add current settings as a job to the export queue."""
        try:
            c = self.app.collect()
        except Exception:
            messagebox.showerror("Invalid value", EN.get("invalid_value_msg", "Check the numeric fields."))
            return

        if not self.validate_basic(c)[0]:
            return

        # Check for Gemini math OCR requirements
        if c.get("gemini_math_ocr"):
            if not hasattr(__import__("pageout.ocr.gemini", fromlist=["_GENAI_AVAILABLE"]), "_GENAI_AVAILABLE"):
                messagebox.showerror(
                    "Package Missing",
                    EN.get(
                        "genai_required",
                        "The 'google-genai' library is required for Gemini Math OCR.\n\nPlease install it with:\n  pip install google-genai",
                    ),
                )
                return
            if not c.get("gemini_api_key", "").strip():
                messagebox.showerror(
                    "Gemini API Key Required",
                    EN.get(
                        "gemini_key_required",
                        "Math OCR with Gemini Vision is enabled, but no Gemini API Key was entered.\n\nPlease enter your personal Gemini API key in the 'LaTeX & AI' tab.\nYou can get a free key at:\nhttps://aistudio.google.com/",
                    ),
                )
                return

        # Save config (including secrets warning)
        warn = save_config(c)
        if warn:
            if not messagebox.askyesno("Secrets not saved", warn + "\n\nAdd to queue anyway?"):
                return

        # Generate job name
        if not name:
            from datetime import datetime

            name = f"Export {datetime.now().strftime('%Y-%m-%d %H:%M')}"

        # Check if pages need loading
        shown = self.app.props_list.selected_labels() if hasattr(self.app, "props_list") else []
        selected = None
        if self.app.loaded_pages and self.app.loaded_source == c["database"].strip():
            sel = self.app.pages_list.selected_indices() if hasattr(self.app, "pages_list") else []
            if not sel:
                messagebox.showerror(
                    "No pages ticked",
                    EN.get(
                        "no_pages_selected",
                        "Tick at least one page in tab 2, or clear the list by loading pages again.",
                    ),
                )
                return
            selected = [self.app.loaded_pages[i] for i in sel]
            # Store selected page IDs in config
            c["_selected_page_ids"] = [p["id"] for p in selected]

        # Add to queue
        job_id = self.export_queue.add_job(name, c, priority=priority)
        self.app.append_log(f"Added to queue: {name} (ID: {job_id})")

        # Refresh queue display
        if hasattr(self.app, "refresh_queue_display"):
            self.app.refresh_queue_display()

        messagebox.showinfo("Added to Queue", f"Job '{name}' added to export queue.\nID: {job_id}")

    def show_schedule(self):
        """Show the scheduled exports dialog."""
        dialog = tk.Toplevel(self.root)
        dialog.title(_("schedule_title"))
        dialog.geometry("800x500")
        dialog.transient(self.root)
        dialog.grab_set()

        ttk = __import__("tkinter.ttk", fromlist=["*"])

        # Toolbar
        toolbar = ttk.Frame(dialog)
        toolbar.pack(fill="x", padx=10, pady=5)

        ttk.Button(toolbar, text=_("schedule_add_button"), command=lambda: self._show_add_schedule_dialog(dialog)).pack(
            side="left", padx=5
        )
        ttk.Button(toolbar, text=_("schedule_refresh"), command=lambda: self._refresh_schedule_tree()).pack(
            side="left", padx=5
        )
        ttk.Button(toolbar, text=_("schedule_close"), command=dialog.destroy).pack(side="right", padx=5)

        # Treeview for schedules
        columns = ("id", "name", "source", "format", "schedule", "status", "last_run")
        self.app.schedule_tree = ttk.Treeview(dialog, columns=columns, show="headings", height=15)
        self.app.schedule_tree.heading("id", text=_("schedule_column_id"))
        self.app.schedule_tree.heading("name", text=_("schedule_column_name"))
        self.app.schedule_tree.heading("source", text=_("schedule_column_source"))
        self.app.schedule_tree.heading("format", text=_("schedule_column_format"))
        self.app.schedule_tree.heading("schedule", text=_("schedule_column_schedule"))
        self.app.schedule_tree.heading("status", text=_("schedule_column_status"))
        self.app.schedule_tree.heading("last_run", text=_("schedule_column_last_run"))
        self.app.schedule_tree.column("id", width=70)
        self.app.schedule_tree.column("name", width=150)
        self.app.schedule_tree.column("source", width=150)
        self.app.schedule_tree.column("format", width=100)
        self.app.schedule_tree.column("schedule", width=120)
        self.app.schedule_tree.column("status", width=80)
        self.app.schedule_tree.column("last_run", width=100)
        self.app.schedule_tree.pack(fill="both", expand=True, padx=10, pady=5)

        # Scrollbar
        vsb = ttk.Scrollbar(self.app.schedule_tree, orient="vertical", command=self.app.schedule_tree.yview)
        self.app.schedule_tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")

        # Bind double-click to show details
        self.app.schedule_tree.bind("<Double-1>", lambda e: self._show_schedule_details(dialog))

        # Action buttons frame
        action_frame = ttk.Frame(dialog)
        action_frame.pack(fill="x", padx=10, pady=5)

        ttk.Button(
            action_frame, text=_("schedule_action_enable"), command=lambda: self._schedule_toggle_status(dialog)
        ).pack(side="left", padx=5)
        ttk.Button(
            action_frame, text=_("schedule_action_disable"), command=lambda: self._schedule_toggle_status(dialog)
        ).pack(side="left", padx=5)
        ttk.Button(
            action_frame, text=_("schedule_action_edit"), command=lambda: self._show_add_schedule_dialog(dialog)
        ).pack(side="left", padx=5)
        ttk.Button(action_frame, text=_("schedule_action_remove"), command=lambda: self._schedule_remove(dialog)).pack(
            side="left", padx=5
        )

        # Initial load
        self._refresh_schedule_tree()

    def _refresh_schedule_tree(self):
        """Refresh the schedule treeview."""
        tree = getattr(self.app, "schedule_tree", None)
        if not tree:
            return

        # Clear
        for item in tree.get_children():
            tree.delete(item)

        # Populate
        schedules = list_schedules()
        if not schedules:
            # Show message if no schedules
            tree.insert("", "end", values=("", _("no_schedules"), "", "", "", "", ""))
            return

        for s in schedules:
            formats_str = ", ".join(s.formats) if s.formats else "md"
            tree.insert(
                "",
                "end",
                values=(
                    s.id,
                    s.name,
                    s.source[:40] + "..." if len(s.source) > 40 else s.source,
                    formats_str,
                    s.schedule,
                    s.status.value,
                    s.last_run or "never",
                ),
            )

    def _show_add_schedule_dialog(self, parent=None):
        """Show dialog to add or edit a schedule."""
        dialog = tk.Toplevel(self.root)
        dialog.title(
            _("schedule_add_button")
            if not hasattr(self, "_edit_schedule_mode") or not self._edit_schedule_mode
            else _("schedule_action_edit")
        )
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.geometry("500x450")

        ttk = __import__("tkinter.ttk", fromlist=["*"])

        # Form fields
        ttk.Label(dialog, text=_("schedule_name_label")).pack(anchor="w", padx=15, pady=(10, 2))
        name_var = tk.StringVar()
        if hasattr(self, "_edit_schedule_mode") and self._edit_schedule_mode:
            name_var.set(self._edit_schedule_name)
        ttk.Entry(dialog, textvariable=name_var, width=50).pack(fill="x", padx=15, pady=5)

        ttk.Label(dialog, text=_("schedule_source_label")).pack(anchor="w", padx=15, pady=(10, 2))
        source_var = tk.StringVar()
        ttk.Entry(dialog, textvariable=source_var, width=50).pack(fill="x", padx=15, pady=5)

        ttk.Label(dialog, text=_("schedule_output_label")).pack(anchor="w", padx=15, pady=(10, 2))
        output_var = tk.StringVar()
        output_entry = ttk.Entry(dialog, textvariable=output_var, width=50)
        output_entry.pack(fill="x", padx=15, pady=5)
        ttk.Button(dialog, text="Browse…", command=lambda: self._browse_schedule_output(output_var)).pack(
            anchor="w", padx=15, pady=(0, 10)
        )

        ttk.Label(dialog, text=_("schedule_formats_label")).pack(anchor="w", padx=15, pady=(10, 2))
        formats_var = tk.StringVar(value="md,pdf")
        ttk.Entry(dialog, textvariable=formats_var, width=50).pack(fill="x", padx=15, pady=5)

        ttk.Label(dialog, text=_("schedule_schedule_label")).pack(anchor="w", padx=15, pady=(10, 2))
        schedule_var = tk.StringVar(value="daily")
        ttk.Entry(dialog, textvariable=schedule_var, width=50).pack(fill="x", padx=15, pady=5)

        # Preview
        preview_frame = ttk.LabelFrame(dialog, text=" " + _("schedule_preview") + " ", padding=10)
        preview_frame.pack(fill="x", padx=15, pady=10)
        preview_label = ttk.Label(preview_frame, text="", foreground="#6b7280")
        preview_label.pack(anchor="w")

        def update_preview(*args):
            name = name_var.get()
            source = source_var.get()
            out = output_var.get()
            fmt = formats_var.get()
            sched = schedule_var.get()
            preview_label.config(
                text=f"Will export '{fmt}' to '{out}' {sched} from {source[:30]}{'...' if len(source) > 30 else ''} (schedule: {sched})"
            )

        name_var.trace_add("write", update_preview)
        source_var.trace_add("write", update_preview)
        schedule_var.trace_add("write", update_preview)

        # Buttons
        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(pady=15)

        def save_and_close():
            try:
                if hasattr(self, "_edit_schedule_mode") and self._edit_schedule_mode:
                    # Edit mode - use existing ID
                    task_id = add_schedule(
                        name=name_var.get(),
                        source=source_var.get(),
                        output_dir=output_var.get(),
                        formats=[f.strip() for f in formats_var.get().split(",")],
                        schedule=schedule_var.get(),
                    )
                else:
                    # Add mode
                    task_id = add_schedule(
                        name=name_var.get(),
                        source=source_var.get(),
                        output_dir=output_var.get(),
                        formats=[f.strip() for f in formats_var.get().split(",")],
                        schedule=schedule_var.get(),
                    )
                messagebox.showinfo("Schedule Added", _("schedule_added"))
                dialog.destroy()
                self._refresh_schedule_tree()
            except Exception as e:
                messagebox.showerror("Error", str(e))

        ttk.Button(btn_frame, text=_("schedule_save"), command=save_and_close).pack(side="left", padx=5)
        ttk.Button(btn_frame, text=_("schedule_cancel"), command=dialog.destroy).pack(side="left", padx=5)

        dialog.wait_window()

    def _browse_schedule_output(self, var):
        """Browse for output directory."""
        from tkinter import filedialog

        folder = filedialog.askdirectory()
        if folder:
            var.set(folder)

    def _show_schedule_details(self, parent=None):
        """Show details for a selected schedule."""
        tree = getattr(self.app, "schedule_tree", None)
        if not tree:
            return
        selection = tree.selection()
        if not selection:
            return
        item = tree.item(selection[0])
        task_id = item["values"][0]
        if not task_id:
            return
        task = get_schedule(task_id)
        if not task:
            return

        # Show details in messagebox
        details = [
            f"Name: {task.name}",
            f"ID: {task.id}",
            f"Source: {task.source}",
            f"Output: {task.output_dir}",
            f"Formats: {', '.join(task.formats)}",
            f"Schedule: {task.schedule}",
            f"Status: {task.status.value}",
            f"Last Run: {task.last_run or 'never'}",
            f"Log File: {task.log_file}",
        ]
        messagebox.showinfo("Schedule Details", "\n".join(details))

    def _schedule_remove(self, parent=None):
        """Remove a selected schedule."""
        tree = getattr(self.app, "schedule_tree", None)
        if not tree:
            return
        selection = tree.selection()
        if not selection:
            return
        item = tree.item(selection[0])
        task_id = item["values"][0]
        task_name = item["values"][1]
        if messagebox.askyesno("Remove Schedule", f"Remove schedule '{task_name}'?"):
            remove_schedule(task_id or task_name)
            self._refresh_schedule_tree()

    def _schedule_toggle_status(self, parent=None):
        """Enable or disable a selected schedule."""
        tree = getattr(self.app, "schedule_tree", None)
        if not tree:
            return
        selection = tree.selection()
        if not selection:
            return
        item = tree.item(selection[0])
        task_id = item["values"][0]
        task_name = item["values"][1]
        current_status = item["values"][6]

        if current_status == ScheduleStatus.ACTIVE.value:
            result = disable_schedule(task_id or task_name)
            if result:
                messagebox.showinfo("Disabled", _("schedule_disabled"))
            else:
                messagebox.showerror("Error", _("schedule_error"))
        else:
            result = enable_schedule(task_id or task_name)
            if result:
                messagebox.showinfo("Enabled", _("schedule_enabled"))
            else:
                messagebox.showerror("Error", _("schedule_error"))

        self._refresh_schedule_tree()

    def show_queue(self):
        """Show the export queue dialog."""
        dialog = tk.Toplevel(self.root)
        dialog.title("Export Queue")
        dialog.geometry("800x500")
        dialog.transient(self.root)
        dialog.grab_set()

        ttk = __import__("tkinter.ttk", fromlist=["*"])

        # Toolbar
        toolbar = ttk.Frame(dialog)
        toolbar.pack(fill="x", padx=10, pady=5)

        ttk.Button(toolbar, text="Add Current Settings", command=lambda: [self.add_to_queue(), dialog.destroy()]).pack(
            side="left", padx=5
        )
        ttk.Button(toolbar, text="Pause Selected", command=lambda: self._queue_pause_selected(dialog)).pack(
            side="left", padx=5
        )
        ttk.Button(toolbar, text="Resume Selected", command=lambda: self._queue_resume_selected(dialog)).pack(
            side="left", padx=5
        )
        ttk.Button(toolbar, text="Remove Selected", command=lambda: self._queue_remove_selected(dialog)).pack(
            side="left", padx=5
        )
        ttk.Button(toolbar, text="Cancel Selected", command=lambda: self._queue_cancel_selected(dialog)).pack(
            side="left", padx=5
        )
        ttk.Button(toolbar, text="Retry Selected", command=lambda: self._queue_retry_selected(dialog)).pack(
            side="left", padx=5
        )
        ttk.Button(toolbar, text="Clear History", command=lambda: self._queue_clear_history(dialog)).pack(
            side="left", padx=5
        )
        ttk.Button(toolbar, text="Refresh", command=lambda: self.refresh_queue_display(dialog)).pack(
            side="right", padx=5
        )

        # Queue treeview
        columns = ("id", "name", "status", "progress", "pages", "message")
        self.app.queue_tree = ttk.Treeview(dialog, columns=columns, show="headings", height=20)
        self.app.queue_tree.heading("id", text="ID")
        self.app.queue_tree.heading("name", text="Name")
        self.app.queue_tree.heading("status", text="Status")
        self.app.queue_tree.heading("progress", text="Progress")
        self.app.queue_tree.heading("pages", text="Pages")
        self.app.queue_tree.heading("message", text="Message")
        self.app.queue_tree.column("id", width=60)
        self.app.queue_tree.column("name", width=200)
        self.app.queue_tree.column("status", width=100)
        self.app.queue_tree.column("progress", width=80)
        self.app.queue_tree.column("pages", width=80)
        self.app.queue_tree.column("message", width=250)
        self.app.queue_tree.pack(fill="both", expand=True, padx=10, pady=5)

        # Status bar
        status_frame = ttk.Frame(dialog)
        status_frame.pack(fill="x", padx=10, pady=5)
        self.app.queue_status_var = tk.StringVar(value="")
        ttk.Label(status_frame, textvariable=self.app.queue_status_var).pack(side="left")

        # Bind double-click to show details
        self.app.queue_tree.bind("<Double-1>", lambda e: self._show_job_details(dialog))

        # Initial load
        self.refresh_queue_display(dialog)

        # Auto-refresh
        def auto_refresh():
            if dialog.winfo_exists():
                self.refresh_queue_display(dialog)
                dialog.after(1000, auto_refresh)

        dialog.after(1000, auto_refresh)

    def refresh_queue_display(self, dialog=None):
        """Refresh the queue treeview."""
        tree = getattr(self.app, "queue_tree", None)
        if not tree:
            return

        # Save selection
        selection = tree.selection()

        # Clear and repopulate
        for item in tree.get_children():
            tree.delete(item)

        jobs = self.export_queue.get_all_jobs()
        for job in jobs:
            status = job.status.value
            progress_pct = int(job.progress * 100)
            pages = f"{job.current_page}/{job.total_pages}" if job.total_pages > 0 else "—"
            msg = job.message[:80] if job.message else ""
            if job.error:
                msg = f"Error: {job.error[:60]}"

            # Color by status
            tags = ()
            if job.status == JobStatus.RUNNING:
                tags = ("running",)
            elif job.status == JobStatus.COMPLETED:
                tags = ("completed",)
            elif job.status == JobStatus.FAILED:
                tags = ("failed",)
            elif job.status == JobStatus.CANCELLED:
                tags = ("cancelled",)
            elif job.status == JobStatus.PAUSED:
                tags = ("paused",)

            tree.insert(
                "",
                "end",
                values=(
                    job.id,
                    job.name,
                    status,
                    f"{progress_pct}%",
                    pages,
                    msg,
                ),
                tags=tags,
            )

        # Configure tags
        tree.tag_configure("running", background="#e8f5e9")
        tree.tag_configure("completed", background="#e3f2fd")
        tree.tag_configure("failed", background="#ffebee")
        tree.tag_configure("cancelled", background="#f5f5f5")
        tree.tag_configure("paused", background="#fff3e0")

        # Restore selection
        for item_id in selection:
            if tree.exists(item_id):
                tree.selection_add(item_id)

        # Update status bar
        stats = self.export_queue.get_stats()
        status_text = f"Total: {sum(stats.values())}  |  Pending: {stats.get('pending', 0)}  Running: {stats.get('running', 0)}  Completed: {stats.get('completed', 0)}  Failed: {stats.get('failed', 0)}  Cancelled: {stats.get('cancelled', 0)}"
        if hasattr(self.app, "queue_status_var"):
            self.app.queue_status_var.set(status_text)

    def _queue_remove_selected(self, dialog):
        """Remove selected job from queue."""
        tree = getattr(self.app, "queue_tree", None)
        if not tree:
            return
        selection = tree.selection()
        if not selection:
            return
        item = tree.item(selection[0])
        job_id = item["values"][0]
        job = self.export_queue.get_job(job_id)
        if job and job.status == JobStatus.RUNNING:
            messagebox.showwarning("Cannot Remove", "Cannot remove a running job. Cancel it first.")
            return
        if messagebox.askyesno("Remove Job", f"Remove job '{item['values'][1]}' from queue?"):
            self.export_queue.remove_job(job_id)
            self.refresh_queue_display(dialog)

    def _queue_pause_selected(self, dialog):
        """Pause selected job."""
        tree = getattr(self.app, "queue_tree", None)
        if not tree:
            return
        selection = tree.selection()
        if not selection:
            return
        item = tree.item(selection[0])
        job_id = item["values"][0]
        job = self.export_queue.get_job(job_id)
        if job and job.status == JobStatus.PENDING:
            self.export_queue.pause_job(job_id)
            self.refresh_queue_display(dialog)

    def _queue_resume_selected(self, dialog):
        """Resume selected job."""
        tree = getattr(self.app, "queue_tree", None)
        if not tree:
            return
        selection = tree.selection()
        if not selection:
            return
        item = tree.item(selection[0])
        job_id = item["values"][0]
        job = self.export_queue.get_job(job_id)
        if job and job.status == JobStatus.PAUSED:
            self.export_queue.resume_job(job_id)
            self.refresh_queue_display(dialog)

    def _queue_cancel_selected(self, dialog):
        """Cancel selected job."""
        tree = getattr(self.app, "queue_tree", None)
        if not tree:
            return
        selection = tree.selection()
        if not selection:
            return
        item = tree.item(selection[0])
        job_id = item["values"][0]
        job = self.export_queue.get_job(job_id)
        if job and job.status in (JobStatus.RUNNING, JobStatus.PENDING, JobStatus.PAUSED):
            self.export_queue.cancel_job(job_id)
            self.refresh_queue_display(dialog)

    def _queue_retry_selected(self, dialog):
        """Retry selected job."""
        tree = getattr(self.app, "queue_tree", None)
        if not tree:
            return
        selection = tree.selection()
        if not selection:
            return
        item = tree.item(selection[0])
        job_id = item["values"][0]
        job = self.export_queue.get_job(job_id)
        if job and job.status in (JobStatus.FAILED, JobStatus.CANCELLED):
            self.export_queue.retry_job(job_id)
            self.refresh_queue_display(dialog)

    def _queue_clear_history(self, dialog):
        """Clear completed/failed/cancelled jobs from history."""
        if messagebox.askyesno("Clear History", "Remove all completed, failed, and cancelled jobs from the queue?"):
            self.export_queue.clear_history()
            self.refresh_queue_display(dialog)

    def _show_job_details(self, parent):
        """Show detailed job information."""
        tree = getattr(self.app, "queue_tree", None)
        if not tree:
            return
        selection = tree.selection()
        if not selection:
            return
        item = tree.item(selection[0])
        job_id = item["values"][0]
        job = self.export_queue.get_job(job_id)
        if not job:
            return

        detail_dialog = tk.Toplevel(parent)
        detail_dialog.title(f"Job Details: {job.name}")
        detail_dialog.geometry("500x400")
        detail_dialog.transient(parent)
        detail_dialog.grab_set()

        ttk = __import__("tkinter.ttk", fromlist=["*"])

        text = tk.Text(detail_dialog, wrap="word", padx=10, pady=10)
        text.pack(fill="both", expand=True, padx=10, pady=10)

        details = [
            f"ID: {job.id}",
            f"Name: {job.name}",
            f"Status: {job.status.value}",
            f"Priority: {job.priority.name}",
            f"Created: {job.created_at}",
            f"Started: {job.started_at or '—'}",
            f"Completed: {job.completed_at or '—'}",
            f"Progress: {int(job.progress * 100)}%",
            f"Pages: {job.current_page}/{job.total_pages}",
            f"Message: {job.message}",
        ]
        if job.error:
            details.append(f"Error: {job.error}")
        if job.result:
            details.append(f"Output: {job.result.get('out_dir', '—')}")
            details.append(f"Total pages: {job.result.get('total', 0)}")
            details.append(f"Skipped: {job.result.get('skipped', 0)}")
            details.append(f"Failed: {job.result.get('failed', 0)}")
            details.append(f"Timing: {job.result.get('timing', '—')}")

        text.insert("1.0", "\n".join(details))
        text.config(state="disabled")

        ttk.Button(detail_dialog, text="Close", command=detail_dialog.destroy).pack(pady=10)

    def show_timing_report(self):
        """Show the export timing report viewer."""
        dialog = tk.Toplevel(self.root)
        dialog.title(_("timing_report_title", "Export Timing Report"))
        dialog.geometry("700x500")
        dialog.transient(self.root)
        dialog.grab_set()

        ttk = __import__("tkinter.ttk", fromlist=["*"])

        # Toolbar
        toolbar = ttk.Frame(dialog)
        toolbar.pack(fill="x", padx=10, pady=5)

        ttk.Button(
            toolbar, text=_("timing_report_load", "Load Report…"), command=lambda: self._load_timing_report(text_area)
        ).pack(side="left", padx=5)
        ttk.Button(toolbar, text="Close", command=dialog.destroy).pack(side="right", padx=5)

        # Text area for report
        text_area = tk.Text(dialog, wrap="word", padx=10, pady=10, font=("Consolas", 10))
        text_area.pack(fill="both", expand=True, padx=10, pady=5)

        # Scrollbar
        scrollbar = ttk.Scrollbar(text_area, orient="vertical", command=text_area.yview)
        scrollbar.pack(side="right", fill="y")
        text_area.config(yscrollcommand=scrollbar.set)

        # Try to load timing report from last export or from output folder
        self._load_last_timing_report(text_area)

    def _load_timing_report(self, text_area):
        """Load a timing report from a file."""
        import json
        from tkinter import filedialog

        file_path = filedialog.askopenfilename(
            title="Select Timing Report",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            initialdir=self.app.V.get("save_dir", tk.StringVar(value="")).get()
            if hasattr(self.app, "V") and self.app.V.get("save_dir")
            else os.path.expanduser("~"),
            parent=self.root,
        )

        if not file_path:
            return

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._display_timing_report(text_area, data)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load timing report: {e}")

    def _load_last_timing_report(self, text_area):
        """Try to load the timing report from the last export."""
        import json
        import os

        # Try to find timing_report.json in the output folder
        save_dir = (
            self.app.V.get("save_dir", tk.StringVar(value="")).get()
            if hasattr(self.app, "V") and self.app.V.get("save_dir")
            else ""
        )
        if save_dir:
            timing_path = os.path.join(save_dir, "timing_report.json")
            if os.path.exists(timing_path):
                try:
                    with open(timing_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    self._display_timing_report(text_area, data)
                    return
                except Exception:
                    pass

        # No timing report found
        text_area.insert(
            "1.0",
            _(
                "timing_report_no_data",
                "No timing data available.\n\nEnable 'Save timing_report.json with export profiling data' in the Output tab to generate timing reports.",
            ),
        )
        text_area.config(state="disabled")

    def _display_timing_report(self, text_area, data: dict):
        """Display timing report data in the text area."""
        text_area.config(state="normal")
        text_area.delete("1.0", "end")

        lines = []
        lines.append("╔══════════════════════════════════════════════════════════╗")
        lines.append("║           EXPORT TIMING REPORT                           ║")
        lines.append("╚══════════════════════════════════════════════════════════╝")
        lines.append("")

        # Total time
        total_ms = (
            data.get("notion_api", {}).get("total_ms", 0)
            + data.get("images", {}).get("total_ms", 0)
            + data.get("pdf", {}).get("total_ms", 0)
            + data.get("merge", {}).get("total_ms", 0)
            + data.get("other", {}).get("total_ms", 0)
        )
        api_wait = data.get("api_wait_ms", 0)

        lines.append(f"{_('timing_report_total', 'Total Time:')} {total_ms:.0f} ms ({total_ms / 1000:.2f} s)")
        if api_wait:
            lines.append(f"API Rate-limiter Wait: {api_wait:.0f} ms ({api_wait / 1000:.2f} s)")
        lines.append("")

        lines.append(f"{_('timing_report_categories', 'Categories:')}")
        lines.append("")

        categories = [
            ("Notion API", "notion_api", "calls"),
            ("Images", "images", "images"),
            ("PDF Generation", "pdf", "pages"),
            ("PDF Merge", "merge", "merges"),
            ("Other", "other", "ops"),
        ]

        for label, key, unit in categories:
            cat = data.get(key, {})
            count = cat.get("count", 0)
            total = cat.get("total_ms", 0)
            avg = cat.get("avg_ms", 0)
            bytes_dl = cat.get("bytes_downloaded", 0)

            if count > 0:
                lines.append(f"  {label}:")
                lines.append(f"    Count:     {count} {unit}")
                lines.append(f"    Total:     {total:.2f} ms")
                lines.append(f"    Average:   {avg:.2f} ms/op")
                if bytes_dl > 0:
                    mb = bytes_dl / (1024 * 1024)
                    lines.append(f"    Downloaded: {mb:.2f} MB")
                lines.append("")

        # Percentage breakdown
        if total_ms > 0:
            lines.append("Percentage Breakdown:")
            for label, key, _ in categories:
                cat = data.get(key, {})
                ms = cat.get("total_ms", 0)
                if ms > 0:
                    pct = (ms / total_ms) * 100
                    lines.append(f"  {label}: {pct:.1f}%")

        text_area.insert("1.0", "\n".join(lines))
        text_area.config(state="disabled")

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
            # Create a client
            from notion_client import Client

            from pageout.sources.notion_api import load_property_names

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

        self.root.bg(lambda: Exporter(c).fetch_roots(), done)

    def preview_names(self):
        """Preview file names based on current config."""
        try:
            c = self.app.collect()
        except Exception:
            messagebox.showerror("Invalid value", EN.get("invalid_value_msg", "Check the numeric fields."))
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

        self.root.bg(work, done)

    def choose_folder(self):
        """Open folder selection dialog."""
        d = filedialog.askdirectory(title="Choose output folder")
        if d:
            self.app.V["save_dir"].set(d)

    def choose_icon_file(self):
        """Choose custom icon file."""
        p = filedialog.askopenfilename(
            title="Choose custom icon image",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.gif *.webp *.svg"), ("All files", "*.*")],
        )
        if p:
            self.app.V["icon_custom_file"].set(p)

    def select_pages(self, all_: bool = False):
        """Select/deselect all pages."""
        if hasattr(self.app, "pages_list"):
            self.app.pages_list.select_all(all_)

    def on_close(self):
        """Handle window close event."""
        try:
            # Check if we should confirm exit
            if self.prefs_confirm_exit.get() if hasattr(self, "prefs_confirm_exit") else False:
                if not messagebox.askyesno("Confirm Exit", "Are you sure you want to exit?"):
                    return  # Don't close

            # Check for running jobs
            if self.export_queue.is_running():
                if not messagebox.askyesno(
                    "Running Export",
                    "An export job is currently running. Exit anyway? (The job will be cancelled.)",
                ):
                    return  # Don't close
                # Cancel running job
                running_job = self.export_queue.get_running_job()
                if running_job:
                    self.export_queue.cancel_job(running_job.id)

            # Stop queue processor
            self.export_queue.stop_processing(wait=False)

            # Save window geometry
            self._save_window_geometry()

            # Save config on close
            warn = self.save_config()
            if warn:
                if not messagebox.askyesno(
                    "Unsaved changes",
                    f"You have unsaved changes.\n{warn}\n\nSave anyway?",
                ):
                    return  # Don't close
            self.root.destroy()
        except Exception:
            self.root.destroy()

    # === U2: New methods for menu bar and shortcuts ===

    def new_config(self):
        """Create a new configuration (reset to defaults)."""
        if self._unsaved_changes:
            if not messagebox.askyesno("Unsaved changes", "Discard unsaved changes and start fresh?"):
                return
        # Reset all variables to defaults
        for key, default in DEFAULTS.items():
            if key in self.app.V:
                if isinstance(default, bool):
                    self.app.V[key].set(default)
                elif isinstance(default, int):
                    self.app.V[key].set(default)
                elif isinstance(default, float):
                    self.app.V[key].set(default)
                else:
                    self.app.V[key].set(default)
        self._unsaved_changes = False

    def open_config_folder(self):
        """Open the config folder in file explorer."""
        import subprocess
        import sys

        try:
            if sys.platform.startswith("win"):
                os.startfile(CONFIG_DIR)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", CONFIG_DIR])
            else:
                subprocess.Popen(["xdg-open", CONFIG_DIR])
        except Exception as e:
            messagebox.showerror("Error", f"Could not open config folder: {e}")

    def save_profile(self):
        """Save current settings as a named profile."""
        from tkinter import simpledialog

        name = simpledialog.askstring("Save Profile", "Enter profile name:", parent=self.root)
        if not name:
            return

        # Collect current config
        c = self.app.collect()

        # Save profile using the profiles module (filters secrets and runtime keys)
        try:
            save_profile(name, c)
            messagebox.showinfo("Profile Saved", f"Profile '{name}' saved successfully.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save profile: {e}")

    def load_profile(self):
        """Load a saved profile."""
        profiles = list_profiles()
        if not profiles:
            messagebox.showinfo("No Profiles", "No profiles found. Save a profile first.")
            return

        # Show dialog to select profile
        dialog = tk.Toplevel(self.root)
        dialog.title("Load Profile")
        dialog.geometry("300x400")
        dialog.transient(self.root)
        dialog.grab_set()

        ttk = __import__("tkinter.ttk", fromlist=["*"])
        ttk.Label(dialog, text="Select a profile to load:").pack(pady=10)

        listbox = tk.Listbox(dialog)
        for p in profiles:
            listbox.insert(tk.END, p)
        listbox.pack(fill="both", expand=True, padx=10, pady=5)

        def on_load():
            selection = listbox.curselection()
            if selection:
                profile_name = profiles[selection[0]]
                self._load_profile_file(profile_name)
                dialog.destroy()

        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(pady=10)
        ttk.Button(btn_frame, text="Load", command=on_load).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="Cancel", command=dialog.destroy).pack(side="left", padx=5)

        self.root.wait_window(dialog)

    def _load_profile_file(self, profile_name: str):
        """Load a specific profile file."""
        try:
            profile_data = load_profile(profile_name)

            # Merge with defaults using the profiles module
            cfg = load_config()
            merge_profile_into_config(profile_data, cfg)

            # Apply merged config to UI
            _json = __import__("json")
            for key, val in cfg.items():
                if key in self.app.V:
                    default = DEFAULTS.get(key)
                    if isinstance(default, bool):
                        self.app.V[key].set(bool(val))
                    elif isinstance(default, int):
                        self.app.V[key].set(int(val))
                    elif isinstance(default, float):
                        self.app.V[key].set(float(val))
                    elif isinstance(default, list):
                        # For list defaults (like 'sources'), store as JSON string
                        if isinstance(val, list):
                            self.app.V[key].set(_json.dumps(val))
                        else:
                            self.app.V[key].set(str(val))
                    else:
                        self.app.V[key].set(str(val))

            messagebox.showinfo("Profile Loaded", f"Profile '{profile_name}' loaded successfully.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load profile: {e}")

    def manage_profiles(self):
        """Open manage profiles dialog."""
        dialog = tk.Toplevel(self.root)
        dialog.title("Manage Profiles")
        dialog.geometry("400x400")
        dialog.transient(self.root)
        dialog.grab_set()

        ttk = __import__("tkinter.ttk", fromlist=["*"])
        ttk.Label(dialog, text="Saved Profiles:").pack(pady=10)

        listbox = tk.Listbox(dialog)
        profiles = list_profiles()
        for p in profiles:
            listbox.insert(tk.END, p)
        listbox.pack(fill="both", expand=True, padx=10, pady=5)

        def on_delete():
            selection = listbox.curselection()
            if selection:
                profile_name = profiles[selection[0]]
                if messagebox.askyesno("Delete Profile", f"Delete profile '{profile_name}'?"):
                    delete_profile(profile_name)
                    listbox.delete(selection[0])
                    profiles.pop(selection[0])

        def on_duplicate():
            selection = listbox.curselection()
            if selection:
                profile_name = profiles[selection[0]]
                new_name = f"{profile_name}_copy"
                # Load the profile and save with new name
                profile_data = load_profile(profile_name)
                save_profile(new_name, profile_data)
                listbox.insert(tk.END, new_name)
                profiles.append(new_name)

        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(pady=10)
        ttk.Button(btn_frame, text="Delete", command=on_delete).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="Duplicate", command=on_duplicate).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="Close", command=dialog.destroy).pack(side="left", padx=5)

    # === Source Management ===

    def save_source(self):
        """Save current database/page as a named source."""
        from tkinter import simpledialog

        c = self.app.collect()
        url = c.get("database", "").strip()
        if not url:
            messagebox.showinfo("No Source", "Enter a database/page link first.")
            return

        # Try to extract a nice default name
        default_name = extract_id_from_url(url) or "My Source"

        name = simpledialog.askstring("Save Source", "Enter source name:", initialvalue=default_name, parent=self.root)
        if not name:
            return

        source_type = c.get("source_type", "Auto-detect")
        try:
            add_source(name, url, source_type, pinned=False)
            messagebox.showinfo("Source Saved", f"Source '{name}' saved successfully.")
            # Refresh the source dropdown if it exists
            self._refresh_source_dropdown()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save source: {e}")

    def load_source(self):
        """Load a saved source."""
        sources = list_sources()
        if not sources:
            messagebox.showinfo("No Sources", "No sources found. Save a source first.")
            return

        # Show dialog to select source
        dialog = tk.Toplevel(self.root)
        dialog.title("Load Source")
        dialog.geometry("500x400")
        dialog.transient(self.root)
        dialog.grab_set()

        ttk = __import__("tkinter.ttk", fromlist=["*"])
        ttk.Label(dialog, text="Select a source to load:").pack(pady=10)

        # Create a listbox with source details
        listbox = tk.Listbox(dialog)
        for s in sources:
            pin_mark = "📌 " if s.get("pinned") else ""
            src_type = s.get("source_type", "Auto-detect")
            url_preview = s.get("url", "")[:60]
            listbox.insert(tk.END, f"{pin_mark}{s['name']}  ({src_type})  {url_preview}")
        listbox.pack(fill="both", expand=True, padx=10, pady=5)

        def on_load():
            selection = listbox.curselection()
            if selection:
                source_name = sources[selection[0]]["name"]
                self._load_source_file(source_name)
                dialog.destroy()

        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(pady=10)
        ttk.Button(btn_frame, text="Load", command=on_load).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="Cancel", command=dialog.destroy).pack(side="left", padx=5)

        self.root.wait_window(dialog)

    def _load_source_file(self, source_name: str):
        """Load a specific source."""
        try:
            src = get_source(source_name)
            if not src:
                messagebox.showerror("Error", f"Source '{source_name}' not found.")
                return

            self.app.V["database"].set(src.get("url", ""))
            self.app.V["source_type"].set(src.get("source_type", "Auto-detect"))
            messagebox.showinfo("Source Loaded", f"Source '{source_name}' loaded successfully.")
            self._refresh_source_dropdown()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load source: {e}")

    def manage_sources(self):
        """Open manage sources dialog."""
        dialog = tk.Toplevel(self.root)
        dialog.title("Manage Sources")
        dialog.geometry("600x450")
        dialog.transient(self.root)
        dialog.grab_set()

        ttk = __import__("tkinter.ttk", fromlist=["*"])
        ttk.Label(dialog, text="Saved Sources:").pack(pady=10)

        # Create treeview for better display
        columns = ("name", "type", "url", "pinned")
        tree = ttk.Treeview(dialog, columns=columns, show="headings", height=15)
        tree.heading("name", text="Name")
        tree.heading("type", text="Type")
        tree.heading("url", text="URL / ID")
        tree.heading("pinned", text="Pinned")
        tree.column("name", width=150)
        tree.column("type", width=100)
        tree.column("url", width=250)
        tree.column("pinned", width=60)
        tree.pack(fill="both", expand=True, padx=10, pady=5)

        def refresh_tree():
            for item in tree.get_children():
                tree.delete(item)
            sources = list_sources()
            for s in sources:
                pin_mark = "📌" if s.get("pinned") else ""
                tree.insert(
                    "",
                    "end",
                    values=(s.get("name", ""), s.get("source_type", "Auto-detect"), s.get("url", "")[:80], pin_mark),
                )

        refresh_tree()

        def on_add():
            from tkinter import simpledialog

            name = simpledialog.askstring("Add Source", "Enter source name:", parent=dialog)
            if not name:
                return
            url = simpledialog.askstring("Add Source", "Enter Notion URL or ID:", parent=dialog)
            if not url:
                return
            source_type = "Auto-detect"
            try:
                add_source(name, url, source_type, pinned=False)
                refresh_tree()
            except Exception as e:
                messagebox.showerror("Error", f"Failed to add source: {e}")

        def on_delete():
            selection = tree.selection()
            if selection:
                item = tree.item(selection[0])
                source_name = item["values"][0]
                if messagebox.askyesno("Delete Source", f"Delete source '{source_name}'?"):
                    delete_source(source_name)
                    refresh_tree()

        def on_pin():
            selection = tree.selection()
            if selection:
                item = tree.item(selection[0])
                source_name = item["values"][0]
                new_status = toggle_pin(source_name)
                refresh_tree()

        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(pady=10)
        ttk.Button(btn_frame, text="Add", command=on_add).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="Delete", command=on_delete).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="Pin/Unpin", command=on_pin).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="Close", command=dialog.destroy).pack(side="left", padx=5)

    def _refresh_source_dropdown(self):
        """Refresh the source dropdown on the Source page if it exists."""
        if hasattr(self.app, "source_combo"):
            sources = get_recent_sources(limit=20)
            source_names = [s["name"] for s in sources]
            self.app.source_combo.config(values=source_names)

    def export_settings(self):
        """Export settings to a JSON file."""
        file_path = filedialog.asksaveasfilename(
            title="Export Settings",
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if file_path:
            try:
                c = self.app.collect()
                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump(c, f, indent=2)
                messagebox.showinfo("Exported", "Settings exported successfully.")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to export settings: {e}")

    def import_settings(self):
        """Import settings from a JSON file."""
        file_path = filedialog.askopenfilename(
            title="Import Settings",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if file_path:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                for key, val in data.items():
                    if key in self.app.V:
                        default = DEFAULTS.get(key)
                        if isinstance(default, bool):
                            self.app.V[key].set(bool(val))
                        elif isinstance(default, int):
                            self.app.V[key].set(int(val))
                        elif isinstance(default, float):
                            self.app.V[key].set(float(val))
                        elif isinstance(default, list):
                            # For list defaults (like 'sources'), store as JSON string
                            if isinstance(val, list):
                                self.app.V[key].set(json.dumps(val))
                            else:
                                self.app.V[key].set(str(val))
                        else:
                            self.app.V[key].set(str(val))

                messagebox.showinfo("Imported", "Settings imported successfully.")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to import settings: {e}")

    def show_preferences(self):
        """Show preferences dialog with enhanced U5 Settings UX.

        Features:
        - Tooltips/? help on every option
        - Inline validation for numeric/string fields
        - Greyed-out options with reason
        - Per-section reset & modified dot
        - Settings search jump/highlight
        - Upgraded font/color pickers
        """
        from pageout.gui.widgets import ToolTip

        dialog = tk.Toplevel(self.root)
        dialog.title(_("preferences"))
        dialog.geometry("700x600")
        dialog.transient(self.root)
        dialog.grab_set()

        # Store reference to track when dialog opens
        self._preferences_dialog = dialog

        ttk = __import__("tkinter.ttk", fromlist=["*"])

        # Track original values for reset functionality - capture at dialog open
        self._original_values = {}
        self._section_modified = {}

        # Capture original values from V dict
        for key, var in self.app.V.items():
            if key in DEFAULTS:
                default = DEFAULTS[key]
                current = var.get()
                # Convert to appropriate type for comparison
                if isinstance(default, bool):
                    self._original_values[key] = bool(current)
                elif isinstance(default, int):
                    self._original_values[key] = int(current) if current else default
                elif isinstance(default, float):
                    self._original_values[key] = float(current) if current else default
                else:
                    self._original_values[key] = str(current) if current else ""

        # Main container with search bar
        main_frame = ttk.Frame(dialog)
        main_frame.pack(fill="both", expand=True, padx=10, pady=10)

        # Search bar at top
        search_frame = ttk.Frame(main_frame)
        search_frame.pack(fill="x", pady=(0, 5))
        ttk.Label(search_frame, text=_("preferences_search"), font=("", 9, "bold")).pack(side="left", padx=(0, 5))
        self.search_var = tk.StringVar()
        search_entry = ttk.Entry(search_frame, textvariable=self.search_var, width=40)
        search_entry.pack(side="left", fill="x", expand=True)
        search_entry.bind("<<Modified>>", self._on_search_change)
        search_entry.bind("<KeyRelease>", self._on_search_change)
        clear_btn = ttk.Button(search_frame, text="✕", width=2, command=lambda: self._clear_search())
        clear_btn.pack(side="left", padx=(5, 0))

        # Search results indicator
        self.search_status = tk.StringVar()
        ttk.Label(search_frame, textvariable=self.search_status, style="Hint.TLabel").pack(side="left", padx=(5, 0))

        # Notebook for tabs
        notebook = ttk.Notebook(main_frame)
        notebook.pack(fill="both", expand=True, pady=(5, 0))
        self._preferences_notebook = notebook  # Store for search navigation

        # Dictionary to track tabs and sections
        self._tabs = {}
        self._all_settings = []  # For search functionality

        # ============ APPEARANCE TAB ============
        app_tab = ttk.Frame(notebook)
        notebook.add(app_tab, text=_("preferences_appearance"))
        self._tabs["appearance"] = app_tab

        # Section: Theme
        theme_frame = ttk.LabelFrame(app_tab, text=" " + _("preferences_theme") + " ", padding=10)
        theme_frame.pack(fill="x", padx=10, pady=5)
        theme_frame._section_key = "theme"
        theme_frame._section_label = _("preferences_theme")

        self._section_modified["theme"] = False

        # Theme dropdown with live preview
        theme_label = ttk.Label(theme_frame, text=_("theme_label"), anchor="w")
        theme_label.grid(row=0, column=0, sticky="w", pady=2)
        ToolTip(theme_label, _("theme_help"))

        theme_names = [(_("theme_light"), "light"), (_("theme_dark"), "dark"), (_("theme_system"), "system")]
        theme_var = tk.StringVar(value=self.app.theme.current_theme)
        theme_combo = ttk.Combobox(
            theme_frame, textvariable=theme_var, values=[t[0] for t in theme_names], state="readonly", width=15
        )
        theme_combo.grid(row=0, column=1, sticky="w", pady=2, padx=(10, 0))
        theme_combo.bind("<<ComboboxSelected>>", lambda e: self._apply_theme_selected(theme_var.get()))

        # Theme preview swatch
        preview_frame = ttk.Frame(theme_frame)
        preview_frame.grid(row=0, column=2, sticky="w", padx=10)
        ttk.Label(preview_frame, text="○", font=("", 16), foreground="#6b7280").pack()
        self.theme_preview = ttk.Label(preview_frame, text="", width=10, relief="solid", borderwidth=1)
        self.theme_preview.pack(pady=2)

        # Section: UI Scale
        scale_frame = ttk.LabelFrame(app_tab, text=" " + _("preferences_ui_scale") + " ", padding=10)
        scale_frame.pack(fill="x", padx=10, pady=5)
        scale_frame._section_key = "ui_scale"
        scale_frame._section_label = _("preferences_ui_scale")

        self._section_modified["ui_scale"] = False

        scale_label = ttk.Label(scale_frame, text=_("ui_scale"), anchor="w")
        scale_label.grid(row=0, column=0, sticky="w", pady=2)
        ToolTip(scale_label, _("ui_scale_help"))

        scale_var = tk.DoubleVar(value=self.app.theme.ui_scale)
        scale = ttk.Scale(scale_frame, from_=0.8, to=2.0, variable=scale_var, orient="horizontal", length=150)
        scale.grid(row=0, column=1, sticky="w", pady=2, padx=(10, 0))
        self.scale_value = ttk.Label(scale_frame, text=f"{scale_var.get():.1f}x", foreground="#6b7280")
        self.scale_value.grid(row=0, column=2, sticky="w", padx=(5, 0))

        def update_scale_display(*_):
            val = scale_var.get()
            self.scale_value.config(text=f"{val:.1f}x")
            self.app.theme.set_ui_scale(val)
            self._section_modified["ui_scale"] = True
            self._update_modified_indicator()

        scale_var.trace_add("write", update_scale_display)

        # Section: Accent Color
        color_frame = ttk.LabelFrame(app_tab, text=" " + _("preferences_accent") + " ", padding=10)
        color_frame.pack(fill="x", padx=10, pady=5)
        color_frame._section_key = "accent_color"
        color_frame._section_label = _("preferences_accent")

        self._section_modified["accent_color"] = False

        color_label = ttk.Label(color_frame, text=_("accent_color"), anchor="w")
        color_label.grid(row=0, column=0, sticky="w", pady=2)
        ToolTip(color_label, _("accent_color_help"))

        # Custom color picker
        color_var = self.app.V["accent_color"]
        color_entry = ttk.Entry(color_frame, textvariable=color_var, width=12)
        color_entry.grid(row=0, column=1, sticky="w", pady=2, padx=(5, 0))

        # Color swatch
        self.color_swatch = tk.Label(color_frame, width=4, relief="solid", borderwidth=1, bg=color_var.get())
        self.color_swatch.grid(row=0, column=2, sticky="w", padx=(5, 0))

        color_var.trace_add("write", lambda *_: self._update_color_swatch(color_var.get()))
        color_var.trace_add("write", lambda *_: self._mark_modified("accent_color"))

        def pick_color():
            color = colorchooser.askcolor(color_var.get(), dialog, _("color_picker_title"))
            if color[1]:
                color_var.set(color[1])
                self._update_color_swatch(color[1])
                self._mark_modified("accent_color")

        ttk.Button(color_frame, text="🎨", command=pick_color).grid(row=0, column=3, sticky="w", padx=(5, 0))

        # ============ BEHAVIOR TAB ============
        beh_tab = ttk.Frame(notebook)
        notebook.add(beh_tab, text=_("preferences_behavior"))
        self._tabs["behavior"] = beh_tab

        # Section: Auto-save
        auto_save_frame = ttk.LabelFrame(beh_tab, text=" " + _("preferences_auto_save_section") + " ", padding=10)
        auto_save_frame.pack(fill="x", padx=10, pady=5)
        auto_save_frame._section_key = "prefs_auto_save"
        auto_save_frame._section_label = _("preferences_auto_save_section")

        self._section_modified["prefs_auto_save"] = False

        auto_save_var = self.app.V["prefs_auto_save"]
        auto_save_cb = ttk.Checkbutton(auto_save_frame, text=_("prefs_auto_save"), variable=auto_save_var)
        auto_save_cb.pack(anchor="w", pady=2)
        auto_save_var.trace_add("write", lambda *_: self._mark_modified("prefs_auto_save"))

        auto_save_label = ttk.Label(auto_save_frame, text=_("prefs_auto_save_help"), anchor="w", style="Hint.TLabel")
        auto_save_label.pack(anchor="w", pady=(0, 2))

        # Section: Window management
        window_frame = ttk.LabelFrame(beh_tab, text=" " + _("preferences_window_section") + " ", padding=10)
        window_frame.pack(fill="x", padx=10, pady=5)
        window_frame._section_key = "window_management"
        window_frame._section_label = _("preferences_window_section")

        self._section_modified["window_management"] = False

        ttk.Checkbutton(
            window_frame, text=_("prefs_remember_window"), variable=self.app.V["prefs_remember_window"]
        ).pack(anchor="w", pady=2)
        ttk.Checkbutton(window_frame, text=_("prefs_confirm_exit"), variable=self.app.V["prefs_confirm_exit"]).pack(
            anchor="w", pady=2
        )

        ttk.Label(window_frame, text=_("window_management_help"), anchor="w", style="Hint.TLabel").pack(
            anchor="w", pady=(0, 2)
        )

        # Section: Tooltip delay
        tooltip_frame = ttk.Frame(beh_tab)
        tooltip_frame.pack(fill="x", padx=10, pady=(0, 10))

        self._section_modified["tooltip_delay"] = False

        ttk.Label(tooltip_frame, text=_("prefs_tooltip_delay"), anchor="w").pack(anchor="w", pady=2)
        delay_var = self.app.V["prefs_tooltip_delay"]
        delay_spin = ttk.Spinbox(tooltip_frame, from_=100, to=5000, increment=100, textvariable=delay_var, width=8)
        delay_spin.pack(anchor="w", pady=2)
        delay_var.trace_add("write", lambda *_: self._mark_modified("tooltip_delay"))

        ttk.Label(tooltip_frame, text=_("tooltip_delay_help"), anchor="w", style="Hint.TLabel").pack(
            anchor="w", pady=(0, 2)
        )

        # ============ SHORTCUTS TAB ============
        shortcuts_tab = ttk.Frame(notebook)
        notebook.add(shortcuts_tab, text=_("preferences_shortcuts"))
        self._tabs["shortcuts"] = shortcuts_tab

        # Section: Main shortcuts
        main_shortcuts = ttk.LabelFrame(shortcuts_tab, text=" " + _("preferences_main_shortcuts") + " ", padding=10)
        main_shortcuts.pack(fill="x", padx=10, pady=5)

        shortcuts_data = [
            (_("shortcut_export"), "Ctrl+E", _("shortcut_export_help")),
            (_("shortcut_save"), "Ctrl+S", _("shortcut_save_help")),
            (_("shortcut_load_props"), "Ctrl+L", _("shortcut_load_props_help")),
            (_("shortcut_refresh"), "F5", _("shortcut_refresh_help")),
            (_("shortcut_cancel"), "Esc", _("shortcut_cancel_help")),
            (_("shortcut_find"), "Ctrl+F", _("shortcut_find_help")),
            (_("shortcut_preferences"), "Ctrl+,", _("shortcut_preferences_help")),
        ]

        for i, (name, key, help_text) in enumerate(shortcuts_data):
            ttk.Label(main_shortcuts, text=f"{key}").grid(row=i, column=0, sticky="w", padx=10, pady=2)
            ttk.Label(main_shortcuts, text=name, font=("", 9, "bold")).grid(
                row=i, column=1, sticky="w", padx=10, pady=2
            )
            ttk.Label(main_shortcuts, text=help_text, style="Hint.TLabel").grid(
                row=i, column=2, sticky="w", padx=5, pady=2
            )

        # ============ RESET & APPLY BUTTONS ============
        # Reset all sections tracked
        reset_all_btn = ttk.Button(dialog, text=_("preferences_reset_all"), command=self._reset_all_preferences)
        reset_all_btn.pack(side="left", padx=(0, 5))

        # Cancel button (reverts changes)
        cancel_btn = ttk.Button(dialog, text=_("preferences_cancel"), command=lambda: self._cancel_preferences(dialog))
        cancel_btn.pack(side="left", padx=(0, 5))

        # Apply/OK button
        ok_btn = ttk.Button(dialog, text=_("preferences_ok"), command=lambda: self._apply_preferences(dialog))
        ok_btn.pack(side="right", padx=5)

        # Register settings for search
        self._register_settings_for_search()

    def _update_modified_indicator(self):
        """Update modified indicator dots on section headers."""
        if not hasattr(self, "_tabs"):
            return
        for tab_name, tab_frame in self._tabs.items():
            # Find section headers in the tab
            for item in tab_frame.winfo_children():
                if hasattr(item, "_section_key"):
                    is_modified = self._section_modified.get(item._section_key, False)
                    # In LabelFrame, we need to update the text
                    if hasattr(item, "_section_label"):
                        if is_modified:
                            item.config(text=" " + item._section_label + " ● ")
                        else:
                            item.config(text=" " + item._section_label + " ")

    def _mark_modified(self, section_key):
        """Mark a section as modified."""
        self._section_modified[section_key] = True
        self._update_modified_indicator()

    def _on_search_change(self, event):
        """Handle search input and highlight matching results."""
        query = self.search_var.get().strip().lower()
        if query:
            self._highlight_search_results(query)
            count = len([s for s in self._all_settings if query in s["name"].lower() or query in s["tooltip"].lower()])
            self.search_status.config(text=f"Found {count} setting(s)")
        else:
            self.search_status.config(text="")

    def _clear_search(self):
        """Clear the search bar."""
        self.search_var.set("")
        self.search_status.config(text="")
        self._highlight_search_results("")

    def _update_color_swatch(self, color):
        """Update the color swatch display."""
        try:
            self.color_swatch.config(bg=color)
        except Exception:
            pass

    def _highlight_search_results(self, query):
        """Highlight settings matching the search query by updating visibility and scrolling."""
        # Store search query for later use
        self._search_query = query.strip().lower() if query else ""

        if not self._search_query:
            # Show all settings by ensuring all frames are visible
            for section in getattr(self, "_all_settings", []):
                key = section.get("widget_key")
                if key and key in self.app.V:
                    # Reset any search highlighting
                    pass
            return

        # Find matching settings and scroll to first match
        matches = [
            s
            for s in getattr(self, "_all_settings", [])
            if self._search_query in s.get("name", "").lower() or self._search_query in s.get("tooltip", "").lower()
        ]

        if matches:
            # Focus on the first matching setting's widget
            first_match = matches[0]
            widget_key = first_match.get("widget_key")
            tab = first_match.get("tab")

            if widget_key and hasattr(self.app, "V"):
                # The setting exists, ensure its tab is selected
                if tab and tab in self._tabs:
                    notebook = getattr(self, "_preferences_notebook", None)
                    if notebook:
                        notebook.select(self._tabs[tab])

                # Mark as searched in settings dict
                self._search_matches = matches

    def _register_settings_for_search(self):
        """Register all settings for search functionality with proper widget references."""
        self._all_settings = [
            {"name": _("theme_label"), "tab": "appearance", "tooltip": _("theme_help"), "widget_key": "theme"},
            {"name": _("ui_scale"), "tab": "appearance", "tooltip": _("ui_scale_help"), "widget_key": "ui_scale"},
            {
                "name": _("accent_color"),
                "tab": "appearance",
                "tooltip": _("accent_color_help"),
                "widget_key": "accent_color",
            },
            {
                "name": _("prefs_auto_save"),
                "tab": "behavior",
                "tooltip": _("prefs_auto_save_help"),
                "widget_key": "prefs_auto_save",
            },
            {
                "name": _("prefs_remember_window"),
                "tab": "behavior",
                "tooltip": _("window_management_help"),
                "widget_key": "prefs_remember_window",
            },
            {
                "name": _("prefs_confirm_exit"),
                "tab": "behavior",
                "tooltip": _("window_management_help"),
                "widget_key": "prefs_confirm_exit",
            },
            {
                "name": _("prefs_tooltip_delay"),
                "tab": "behavior",
                "tooltip": _("tooltip_delay_help"),
                "widget_key": "prefs_tooltip_delay",
            },
        ]

    def _apply_theme_selected(self, theme_display_name):
        """Apply theme when selected from dropdown."""
        # Map display names to actual theme values
        theme_map = {
            _("theme_light"): "light",
            _("theme_dark"): "dark",
            _("theme_system"): "system",
        }
        theme_value = theme_map.get(theme_display_name, "light")
        self.app.theme.apply_theme(theme_value)
        self._mark_modified("theme")

    def _reset_all_preferences(self):
        """Reset all preferences to defaults."""
        if not messagebox.askyesno(_("preferences_reset"), _("preferences_reset_confirm")):
            return
        import json

        for key, default in DEFAULTS.items():
            if key in self.app.V:
                if isinstance(default, bool):
                    self.app.V[key].set(default)
                elif isinstance(default, int):
                    self.app.V[key].set(default)
                elif isinstance(default, float):
                    self.app.V[key].set(default)
                elif isinstance(default, list):
                    # For list defaults (like 'sources'), store as JSON string
                    self.app.V[key].set(json.dumps(default))
                else:
                    self.app.V[key].set(str(default) if default else "")
        for key in self._section_modified:
            self._section_modified[key] = False
        messagebox.showinfo(_("preferences_reset"), _("preferences_reset_done"))

    def _cancel_preferences(self, dialog):
        """Cancel preferences dialog, reverting all changes."""
        # Revert to original values
        import json

        for key, val in self._original_values.items():
            if key in self.app.V:
                default = DEFAULTS.get(key, "")
                if isinstance(default, bool):
                    self.app.V[key].set(bool(val))
                elif isinstance(default, int):
                    self.app.V[key].set(int(val))
                elif isinstance(default, float):
                    self.app.V[key].set(float(val))
                elif isinstance(default, list):
                    # For list defaults, restore from original values
                    if isinstance(val, list):
                        self.app.V[key].set(json.dumps(val))
                    else:
                        self.app.V[key].set(str(val))
                else:
                    self.app.V[key].set(str(val))
        dialog.destroy()

    def _apply_preferences(self, dialog):
        """Apply preferences and save config."""
        self.save_config()
        messagebox.showinfo(_("preferences_applied"), _("preferences_applied_msg"))
        dialog.destroy()

    def show_shortcuts(self):
        """Show keyboard shortcuts dialog."""
        dialog = tk.Toplevel(self.root)
        dialog.title(_("menu_shortcuts"))
        dialog.geometry("400x350")
        dialog.transient(self.root)
        dialog.grab_set()

        ttk = __import__("tkinter.ttk", fromlist=["*"])

        shortcuts = [
            ("Export", "Ctrl+E", "Start export"),
            ("Save Config", "Ctrl+S", "Save current configuration"),
            ("Load Properties", "Ctrl+L", "Load properties from Notion"),
            ("Refresh / Reload", "F5", "Refresh current view"),
            ("Cancel Export", "Esc", "Cancel running export"),
            ("Find in Log", "Ctrl+F", "Search in log output"),
            ("Preferences", "Ctrl+,", "Open preferences dialog"),
            ("Switch Tab", "Ctrl+1..8", "Jump to tab 1-8"),
            ("Next Tab", "Ctrl+Tab", "Go to next tab"),
            ("Previous Tab", "Ctrl+Shift+Tab", "Go to previous tab"),
        ]

        for i, (name, key, desc) in enumerate(shortcuts):
            ttk.Label(dialog, text=f"{key}").grid(row=i, column=0, sticky="w", padx=15, pady=3)
            ttk.Label(dialog, text=name, font=("", 9, "bold")).grid(row=i, column=1, sticky="w", padx=10, pady=3)
            ttk.Label(dialog, text=desc, style="Hint.TLabel").grid(row=i, column=2, sticky="w", padx=10, pady=3)

        ttk.Button(dialog, text="OK", command=dialog.destroy).pack(pady=15)

    def show_about(self):
        """Show about dialog with app icon."""
        dialog = tk.Toplevel(self.root)
        dialog.title(_("about_title"))
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)

        # Get icon from app's window (already set in App.__init__)
        icon_img = None
        try:
            # Use the app's already-loaded icon
            if hasattr(self.app.root, "_icon_ref") and self.app.root._icon_ref:
                icon_img = self.app.root._icon_ref
        except Exception:
            pass

        # Build content using pack
        icon_frame = ttk.Frame(dialog)
        icon_frame.pack(side="left", padx=15, pady=15)

        if icon_img:
            ttk.Label(icon_frame, image=icon_img).pack()
        else:
            ttk.Label(icon_frame, text="📄", font=("Segoe UI", 32)).pack()

        content = ttk.Frame(dialog)
        content.pack(side="left", fill="both", expand=True, padx=(0, 15), pady=15)

        ttk.Label(content, text=f"{APP_NAME}\n{APP_VERSION} ({APP_STAGE})", font=("", 12, "bold")).pack(
            anchor="w", pady=(0, 10)
        )
        ttk.Label(content, text=_("about_description"), font=("", 10)).pack(anchor="w", pady=(0, 8))
        ttk.Label(content, text=_("about_author"), font=("", 9), foreground="#6b7280").pack(anchor="w", pady=(0, 4))
        ttk.Label(content, text=_("about_license"), font=("", 9), foreground="#6b7280").pack(anchor="w", pady=(0, 4))
        ttk.Label(content, text=_("about_copyright"), font=("", 9), foreground="#6b7280").pack(anchor="w", pady=(0, 4))

        ttk.Button(dialog, text="OK", command=dialog.destroy).pack(pady=(0, 15))

        # Center over parent
        dialog.update_idletasks()
        x = self.root.winfo_rootx() + self.root.winfo_width() // 2 - dialog.winfo_width() // 2
        y = self.root.winfo_rooty() + self.root.winfo_height() // 2 - dialog.winfo_height() // 2
        dialog.geometry(f"+{max(20, x)}+{max(20, y)}")

    def show_onboarding_wizard(self):
        """Show first-run onboarding wizard."""
        if not self.app.cfg0.get("first_run_complete", False):
            dialog = tk.Toplevel(self.root)
            dialog.title(_("onboarding_welcome"))
            dialog.transient(self.root)
            dialog.grab_set()
            dialog.geometry("520x420")
            dialog.resizable(False, False)

            # Step tracking
            self._onboarding_step = tk.IntVar(value=1)
            self._current_dialog = dialog

            # Build content for each step using pack
            self._build_onboarding_content(dialog)

            # Navigation buttons frame (at bottom)
            nav_frame = ttk.Frame(dialog)
            nav_frame.pack(side="bottom", fill="x", padx=20, pady=10)

            self._back_btn = ttk.Button(nav_frame, text=_("onboarding_back"), command=self._onboarding_back)
            self._next_btn = ttk.Button(nav_frame, text=_("onboarding_next"), command=self._onboarding_next)
            self._finish_btn = ttk.Button(nav_frame, text=_("onboarding_finish"), command=self._onboarding_finish)
            self._cancel_btn = ttk.Button(nav_frame, text=_("onboarding_cancel"), command=dialog.destroy)

            # Refresh initial step
            self._refresh_onboarding_step()

            # Center over parent
            dialog.update_idletasks()
            x = self.root.winfo_rootx() + self.root.winfo_width() // 2 - dialog.winfo_width() // 2
            y = self.root.winfo_rooty() + self.root.winfo_height() // 2 - dialog.winfo_height() // 2
            dialog.geometry(f"+{max(20, x)}+{max(20, y)}")
        else:
            messagebox.showinfo(_("first_run_complete"), "✅ " + _("first_run_complete"))

    def _build_onboarding_content(self, dialog):
        """Build the onboarding dialog content using pack geometry."""
        # Content frame that will hold all step frames
        self._content_frame = ttk.Frame(dialog)
        self._content_frame.pack(fill="both", expand=True, padx=20, pady=10)

        # Welcome frame
        self._welcome_frame = ttk.Frame(self._content_frame)
        ttk.Label(self._welcome_frame, text=_("onboarding_welcome"), font=("", 14, "bold")).pack(
            anchor="w", pady=(0, 10)
        )
        ttk.Label(self._welcome_frame, text=_("onboarding_welcome_desc"), style="Hint.TLabel", wraplength=480).pack(
            anchor="w"
        )

        # Step 1: Token
        self._token_frame = ttk.Frame(self._content_frame)
        ttk.Label(self._token_frame, text=_("onboarding_token_label"), font=("", 11, "bold")).pack(
            anchor="w", pady=(0, 5)
        )
        self.token_entry = ttk.Entry(self._token_frame, width=45)
        self.token_entry.pack(fill="x", pady=(0, 10))
        self.token_entry.insert(0, self.app.cfg0.get("token", ""))
        ttk.Label(self._token_frame, text=_("onboarding_token_desc"), style="Hint.TLabel", wraplength=480).pack(
            anchor="w"
        )

        # Step 2: Output folder
        self._folder_frame = ttk.Frame(self._content_frame)
        folder_row = ttk.Frame(self._folder_frame)
        folder_row.pack(fill="x", pady=(0, 10))
        ttk.Label(folder_row, text=_("onboarding_output_folder"), font=("", 11, "bold")).pack(side="left", anchor="w")
        save_dir_var = self.app.V.get("save_dir", tk.StringVar(value=""))
        self.folder_entry = ttk.Entry(folder_row, textvariable=save_dir_var, width=40)
        self.folder_entry.pack(side="left", fill="x", expand=True, padx=(10, 0))
        browse_btn = ttk.Button(folder_row, text=_("onboarding_browse"), command=self._browse_output_folder)
        browse_btn.pack(side="left", padx=(4, 0))
        ttk.Label(
            self._folder_frame, text=_("onboarding_output_folder_desc"), style="Hint.TLabel", wraplength=480
        ).pack(anchor="w")

        # Hide all frames initially
        self._welcome_frame.pack_forget()
        self._token_frame.pack_forget()
        self._folder_frame.pack_forget()

    def _refresh_onboarding_step(self):
        """Refresh the onboarding dialog based on current step using pack."""
        step = self._onboarding_step.get()

        # Hide all frames
        for f in [self._welcome_frame, self._token_frame, self._folder_frame]:
            f.pack_forget()

        # Show current step frame
        if step == 1:
            self._welcome_frame.pack(fill="both", expand=True)
        elif step == 2:
            self._token_frame.pack(fill="both", expand=True)
        elif step == 3:
            self._folder_frame.pack(fill="both", expand=True)

        # Update navigation buttons
        self._update_nav_buttons(step)

    def _update_nav_buttons(self, step=None):
        """Update navigation button visibility."""
        step = step or self._onboarding_step.get()
        # Show/hide buttons based on step
        if step == 1:
            self._back_btn.pack_forget()
            self._next_btn.pack(side="left", padx=5)
            self._finish_btn.pack_forget()
            self._cancel_btn.pack(side="right", padx=5)
        elif step == 2:
            self._back_btn.pack(side="left", padx=5)
            self._next_btn.pack(side="left", padx=5)
            self._finish_btn.pack_forget()
            self._cancel_btn.pack(side="right", padx=5)
        elif step == 3:
            self._back_btn.pack(side="left", padx=5)
            self._next_btn.pack_forget()
            self._finish_btn.pack(side="left", padx=5)
            self._cancel_btn.pack(side="right", padx=5)

    def _browse_output_folder(self):
        """Browse for output folder."""
        folder = filedialog.askdirectory(initialdir=self.app.V.get("save_dir", ""))
        if folder:
            self.app.V.get("save_dir").set(folder) if "save_dir" in self.app.V else None

    def _onboarding_back(self):
        """Go to previous step."""
        current = self._onboarding_step.get()
        if current > 1:
            self._onboarding_step.set(current - 1)
            self._refresh_onboarding_step()

    def _onboarding_next(self):
        """Go to next step."""
        current = self._onboarding_step.get()
        if current < 3:
            self._onboarding_step.set(current + 1)
            self._refresh_onboarding_step()

    def _onboarding_finish(self):
        """Complete onboarding and close dialog."""
        token = self.token_entry.get().strip()
        if token:
            self.app.V["token"].set(token)

        # Update cfg0 and persist token to config
        self.app.cfg0["token"] = token

        # Mark as complete in config
        self.app.V["first_run_complete"].set(True)
        self.app.cfg0["first_run_complete"] = True

        # Save the config to persist the changes
        save_config(self.app.cfg0)

        self._current_dialog.destroy()
        messagebox.showinfo("✅ " + _("first_run_complete"), _("first_run_complete"))

    def check_my_setup(self):
        """Run system diagnostics and show results."""
        dialog = tk.Toplevel(self.root)
        dialog.title(_("check_setup_title"))
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.geometry("560x520")
        dialog.resizable(True, True)

        # Store results for copy function
        self._diagnostics_results = None

        ttk.Label(dialog, text=_("check_setup_desc"), style="Hint.TLabel").pack(anchor="w", padx=15, pady=(10, 5))

        # Results frame
        results_frame = ttk.Frame(dialog)
        results_frame.pack(fill="both", expand=True, padx=15, pady=5)

        # Treeview for results
        tree = ttk.Treeview(results_frame, columns=("status", "message", "detail"), show="tree headings", height=12)
        tree.heading("#0", text=_("Check"))
        tree.heading("#1", text="Status")
        tree.heading("#2", text=_("diag_message"))
        tree.column("#0", width=200, anchor="w")
        tree.column("#1", width=80, anchor="center")
        tree.column("#2", width=300, anchor="w")

        # Status tags
        tree.tag_configure("ok", foreground="#16a34a")
        tree.tag_configure("warning", foreground="#d97706")
        tree.tag_configure("error", foreground="#dc2626")
        tree.tag_configure("info", foreground="#2563eb")

        vsb = ttk.Scrollbar(results_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)

        tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        # Status bar
        status_var = tk.StringVar(value=_("check_setup_running"))
        status_bar = ttk.Label(dialog, textvariable=status_var, style="Hint.TLabel")
        status_bar.pack(side="bottom", fill="x", padx=5, pady=2)

        # Button frame
        btn_frame = ttk.Frame(dialog)

        copy_btn = ttk.Button(btn_frame, text=_("check_setup_copy"), command=self._copy_diagnostics_to_clipboard)
        copy_btn.pack(side="left", padx=5, pady=5)

        ttk.Button(btn_frame, text="OK", command=dialog.destroy).pack(side="right", padx=5, pady=5)
        btn_frame.pack(side="bottom", fill="x", padx=5, pady=5)

        # Run diagnostics in background
        def run_and_populate():
            tree.delete(*tree.get_children())

            results = run_diagnostics(self.app.cfg0)
            self._diagnostics_results = results

            for r in results:
                status = r.get("status", "INFO")
                detail = r.get("detail", "")
                tags = [status.lower()]

                item = tree.insert(
                    "", "end", text=r.get("name", "Check"), values=(status, r.get("message", ""), detail), tags=tags
                )

                # Expand detail for errors/warnings
                if status in ("ERROR", "WARNING"):
                    tree.item(item, open=True)

            dialog.title(f"{_('check_setup_title')} - {_('check_setup_done')}")

        # Start diagnostics
        tree.insert("", "end", text=_("check_setup_running"), values=(_("check_setup_running", "", "")))
        dialog.after(100, run_and_populate)

    def _copy_diagnostics_to_clipboard(self):
        """Copy diagnostics results to clipboard with redaction."""
        results = self._diagnostics_results
        if not results:
            messagebox.showinfo(_("check_setup_copy"), _("check_setup_copy_no_data"))
            return

        # Build the text with redaction
        lines = []
        for r in results:
            name = r.get("name", "Unknown")
            status = r.get("status", "INFO")
            message = r.get("message", "")
            detail = r.get("detail", "")

            # Redact secrets from detail
            detail = redact(detail, self.app.cfg0.get("token", ""))

            lines.append(f"{name}: {status}")
            lines.append(f"  {message}")
            if detail:
                lines.append(f"  Detail: {detail}")
            lines.append("")

        text_to_copy = "\n".join(lines)

        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(text_to_copy)
            self.root.update()  # Required on some platforms
            messagebox.showinfo(_("check_setup_copy"), _("check_setup_copy_success"))
        except Exception as e:
            messagebox.showerror(_("check_setup_copy"), f"{_('check_setup_copy')}: {e}")

    def validate_settings(self):
        """Validate current settings."""
        try:
            c = self.app.collect()
        except Exception:
            messagebox.showerror("Invalid value", "Check the numeric fields.")
            return

        errors = []
        if not c.get("token", "").strip():
            errors.append("• Notion token is required")
        if not c.get("database", "").strip():
            errors.append("• Database/page link is required")
        if not c.get("save_dir", "").strip():
            errors.append("• Output folder is required")

        formats = [k for k in ["pdf", "html", "md", "txt", "docx", "json", "tex", "images"] if c.get(f"fmt_{k}")]
        if not formats:
            errors.append("• At least one export format must be selected")

        if c.get("gemini_math_ocr") and not c.get("gemini_api_key", "").strip():
            errors.append("• Gemini API key required for Math OCR")

        if errors:
            messagebox.showerror("Validation Failed", "The following issues were found:\n\n" + "\n".join(errors))
        else:
            messagebox.showinfo("Validation Passed", "All settings are valid!")

    def clear_cache(self):
        """Clear export cache."""
        cache_file = os.path.join(CONFIG_DIR, "export_cache.json")
        try:
            if os.path.exists(cache_file):
                os.remove(cache_file)
                messagebox.showinfo("Cache Cleared", "Export cache has been cleared.")
            else:
                messagebox.showinfo("Cache Cleared", "No cache file found.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to clear cache: {e}")

    # Window geometry persistence
    def _get_geometry_file(self) -> str:
        """Get path to window geometry file."""
        return os.path.join(CONFIG_DIR, "window_geometry.json")

    def _save_window_geometry(self):
        """Save window geometry to file."""
        if not self.prefs_remember_window.get() if hasattr(self, "prefs_remember_window") else True:
            return
        try:
            geom = {
                "geometry": self.root.geometry(),
                "state": self.root.state(),
            }
            with open(self._get_geometry_file(), "w") as f:
                json.dump(geom, f)
        except Exception:
            pass

    def _load_window_geometry(self):
        """Load window geometry from file."""
        try:
            with open(self._get_geometry_file(), "r") as f:
                geom = json.load(f)
            self._window_geometry = geom
        except Exception:
            self._window_geometry = None

    def apply_window_geometry(self):
        """Apply saved window geometry."""
        if self._window_geometry:
            try:
                self.root.geometry(self._window_geometry.get("geometry", ""))
                state = self._window_geometry.get("state", "normal")
                if state == "zoomed":
                    self.root.state("zoomed")
            except Exception:
                pass
