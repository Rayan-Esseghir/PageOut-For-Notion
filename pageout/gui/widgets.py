"""GUI Widgets for the PageOut application.

Contains reusable widget components used across multiple tabs.
"""

import tkinter as tk
from tkinter import colorchooser, ttk
from typing import Any, Callable, Dict, List, Optional, Tuple

# Import constants from config for font handling
from pageout.core.config import FONT_CATALOG, SAME_AS_BODY


class ScrollFrame(ttk.Frame):
    """A vertically scrollable page. Mouse-wheel routing is done globally by App._on_wheel."""

    def __init__(self, parent):
        super().__init__(parent)
        bg = ttk.Style().lookup("TFrame", "background") or "#f0f0f0"
        self.canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0, bg=bg, yscrollincrement=20)
        sb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas)
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self._win, width=e.width))
        self.canvas.configure(yscrollcommand=sb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.canvas._wheel_canvas = self.canvas


class CheckList(ttk.Frame):
    """A scrollable list with a checkbox in front of every row."""

    def __init__(self, parent, height=190, empty_text="Nothing loaded yet."):
        super().__init__(parent)
        self.empty_text = empty_text
        self.canvas = tk.Canvas(
            self, height=height, highlightthickness=1, highlightbackground="#c4c4c4", bg="white", yscrollincrement=20
        )
        sb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = tk.Frame(self.canvas, bg="white")
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self._win, width=e.width))
        self.canvas.configure(yscrollcommand=sb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.canvas._wheel_canvas = self.canvas
        self.vars, self.labels = [], []
        self.info = tk.StringVar()
        self.set_items([])

    def _update(self, *_):
        n = sum(1 for v in self.vars if v.get())
        self.info.set(f"{n} of {len(self.vars)} selected" if self.vars else "")

    def set_items(self, labels, checked=True):
        for w in self.inner.winfo_children():
            w.destroy()
        self.vars, self.labels = [], list(labels)
        if not labels:
            tk.Label(self.inner, text=self.empty_text, bg="white", fg="#888888", anchor="w").pack(
                fill="x", padx=8, pady=8
            )
        for lab in labels:
            v = tk.BooleanVar(value=checked)
            v.trace_add("write", self._update)
            self.vars.append(v)
            tk.Checkbutton(
                self.inner,
                text=lab,
                variable=v,
                bg="white",
                activebackground="#eaf2ff",
                anchor="w",
                justify="left",
                relief="flat",
                borderwidth=0,
            ).pack(fill="x", padx=4, pady=0)
        self.canvas.yview_moveto(0)
        self._update()

    def select_all(self, flag=True):
        for v in self.vars:
            v.set(flag)

    def selected_indices(self):
        return [i for i, v in enumerate(self.vars) if v.get()]

    def selected_labels(self):
        return [self.labels[i] for i in self.selected_indices()]


# Generic font aliases for font picker
_GENERIC_FONT_ALIAS = {"Sans-serif": "Helvetica", "Serif": "Times", "Monospace": "Courier"}


class FontPicker(tk.Toplevel):
    """Font chooser where every font name is shown in its own typeface.

    Features:
    - Favorites (⭐) and Recently Used sections
    - Search filtering
    - Live preview with Arabic sample text
    - Shows installed status (grey = not installed)
    """

    SAMPLE = "The quick brown fox 0123456789  —  مرحبا بالعالم"
    PREVIEW_TEXT_AR = "مرحبا بالعالم"

    def __init__(self, app, current, allow_same, on_pick, favorites: Optional[List[str]] = None,
                 recent: Optional[List[str]] = None):
        """
        Args:
            app: Reference to the main App
            current: Currently selected font name
            allow_same: Whether to show "Same as body" option
            on_pick: Callback when font is selected
            favorites: List of favorite font names
            recent: List of recently used font names
        """
        super().__init__(app.root)
        self.app, self.on_pick, self.current = app, on_pick, current
        self.favorites = favorites or []
        self.recent = recent or []
        self.allow_same = allow_same
        self.title(_("choose_font"))
        self.geometry("550x650")
        self.transient(app.root)
        self.entries = []  # (name or None, display)

        # Build sections
        self.sections = []
        names = ([SAME_AS_BODY] if allow_same else []) + ["Sans-serif", "Serif", "Monospace"]
        self.sections.append(("Generic", names))

        # Favorites section
        if self.favorites:
            self.sections.append((_("font_favorites"), self.favorites))

        # Recently used section
        if self.recent:
            self.sections.append((_("font_recent"), self.recent))

        cat = [n for n, _, _ in FONT_CATALOG]
        self.sections.append(
            ("Recommended  (grey = not installed on this PC; Google Fonts need the option in the Design tab)", cat)
        )
        self.sections.append(
            ("Installed on this PC", [f for f in app.font_values if f not in cat and f not in _GENERIC_FONT_ALIAS])
        )

        self._build_ui()
        self.chosen = current
        self.fill()
        self.grab_set()

    def _build_ui(self):
        """Build the FontPicker UI."""
        # Search bar
        top = ttk.Frame(self)
        top.pack(fill="x", padx=10, pady=(10, 4))
        ttk.Label(top, text=_("font_search")).pack(side="left")
        self.q = tk.StringVar()
        ent = ttk.Entry(top, textvariable=self.q)
        ent.pack(side="left", fill="x", expand=True, padx=6)
        ent.focus_set()
        self.q.trace_add("write", lambda *_: self.fill())

        # Font list
        mid = ttk.Frame(self)
        mid.pack(fill="both", expand=True, padx=10, pady=4)
        self.txt = tk.Text(
            mid, wrap="none", cursor="arrow", bg="white", relief="solid", borderwidth=1, spacing1=3, spacing3=3
        )
        sb = ttk.Scrollbar(mid, command=self.txt.yview)
        self.txt.config(yscrollcommand=sb.set)
        self.txt.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.txt.tag_configure("head", font=("", 9, "bold"), foreground="#6b7280", spacing1=8)
        self.txt.tag_configure("pick", background="#cfe3ff")
        self.txt.tag_configure("web", foreground="#8a8f98")
        self.txt.tag_configure("fav", foreground="#d97706")
        self.txt.bind("<Button-1>", self.on_click)
        self.txt.bind("<Double-Button-1>", lambda e: (self.on_click(e), self.use()))

        # Preview area
        preview_frame = ttk.Frame(self)
        preview_frame.pack(fill="x", padx=10, pady=4)
        ttk.Label(preview_frame, text=_("font_preview"), font=("", 9, "bold")).pack(anchor="w")

        # Preview with Latin text
        self.preview = tk.Label(
            preview_frame, text=self.SAMPLE, bg="white", relief="solid", borderwidth=1, height=2, wraplength=520
        )
        self.preview.pack(fill="x", pady=2)

        # Preview with Arabic text
        self.preview_ar = tk.Label(
            preview_frame, text=self.PREVIEW_TEXT_AR, bg="white", relief="solid", borderwidth=1, height=1,
            font=("", 16), fg="#6b7280"
        )
        self.preview_ar.pack(fill="x", pady=2)

        # Font size preview
        size_frame = ttk.Frame(preview_frame)
        size_frame.pack(fill="x", pady=2)
        ttk.Label(size_frame, text=_("font_size_label")).pack(side="left")
        self.size_var = tk.IntVar(value=12)
        size_spin = ttk.Spinbox(size_frame, from_=8, to=72, textvariable=self.size_var, width=5,
                                command=self._update_preview_size)
        size_spin.pack(side="left", padx=4)
        self.size_var.trace_add("write", lambda *_: self._update_preview_size())

        # Buttons
        bt = ttk.Frame(self)
        bt.pack(fill="x", padx=10, pady=(2, 10))
        ttk.Button(bt, text=_("use_this_font"), command=self.use).pack(side="right")
        ttk.Button(bt, text=_("cancel_font"), command=self.destroy).pack(side="right", padx=6)

    def _update_preview_size(self):
        """Update preview font size."""
        fam = self.family_for(self.chosen) if self.chosen else None
        size = self.size_var.get()
        self.preview.config(font=(fam, size) if fam else ("", size))
        self.preview_ar.config(font=(fam, size) if fam else ("", size))

    def family_for(self, name):
        fam = _GENERIC_FONT_ALIAS.get(name, name)
        return fam if (fam in self.app.installed or fam in _GENERIC_FONT_ALIAS.values()) else None

    def fill(self):
        q = self.q.get().strip().lower()
        t = self.txt
        t.config(state="normal")
        t.delete("1.0", "end")
        self.lines = {}
        n = 0
        for title, items in self.sections:
            items = [x for x in items if q in x.lower()]
            if not items:
                continue
            t.insert("end", title + "\n", "head")
            for name in items:
                tag = "f%d" % n
                n += 1
                fam = self.family_for(name)
                tags = [tag]
                if name in self.favorites:
                    tags.append("fav")
                if fam:
                    t.tag_configure(tag, font=(fam, 13))
                    t.insert("end", "  " + name + "\n", tuple(tags))
                else:
                    t.tag_configure(tag, font=("", 11))
                    tags.append("web")  # Not installed fonts get grey color
                    t.insert("end", "  " + name + "\n", tuple(tags))
                self.lines[int(t.index("end-2l").split(".")[0])] = name
        t.config(state="disabled")
        self.mark()

    def mark(self):
        self.txt.tag_remove("pick", "1.0", "end")
        for ln, name in self.lines.items():
            if name == self.chosen:
                self.txt.tag_add("pick", f"{ln}.0", f"{ln}.end+1c")
                self.txt.see(f"{ln}.0")
        fam = self.family_for(self.chosen) if self.chosen else None
        size = self.size_var.get()
        self.preview.config(font=(fam, size) if fam else ("", size))
        self.preview_ar.config(font=(fam, size) if fam else ("", size))

    def on_click(self, e):
        ln = int(self.txt.index(f"@{e.x},{e.y}").split(".")[0])
        if ln in self.lines:
            self.chosen = self.lines[ln]
            self.mark()
        return "break"

    def use(self):
        if self.chosen:
            # Update recent fonts (add to front, keep max 10)
            if self.chosen not in self.recent:
                self.recent.insert(0, self.chosen)
                self.recent = self.recent[:10]
            self.on_pick(self.chosen)
        self.destroy()


class Frame(ttk.Frame):
    """Base frame with common styling methods."""

    def __init__(self, parent=None, **kwargs):
        super().__init__(parent, **kwargs)
        self._configure_styles()

    def _configure_styles(self):
        """Apply consistent frame styling."""
        try:
            self.configure(style="TFrame")
        except Exception:
            pass

    def add_label(
        self, row: int, column: int, text: str, **kwargs
    ) -> ttk.Label:
        """Add a labeled widget pair."""
        label = ttk.Label(self, text=text)
        label.grid(row=row, column=column, sticky="ne", padx=(0, 12), pady=kwargs.get("pady", 4))
        return label

    def add_widget(
        self,
        row: int,
        column: int,
        widget: Any,
        sticky: str = "we",
        pady: int = 4,
        padx: int = 8,
        narrow: bool = False,
    ) -> Any:
        """Place a widget in the grid."""
        widget.grid(
            row=row, column=column, sticky=sticky, padx=padx, pady=pady
        )
        if narrow:
            widget._narrow = True
        return widget

    def add_separator(self, row: int, column: int, columnspan: int = 2, **kwargs):
        """Add a horizontal separator."""
        ttk.Separator(self, orient="horizontal").grid(
            row=row, column=0, columnspan=columnspan, sticky="we", padx=kwargs.get("padx", 8), pady=kwargs.get("pady", 8)
        )

    def add_section_label(self, row: int, text: str) -> ttk.Label:
        """Add a bold section header label."""
        label = ttk.Label(
            self, text=text, font=("", 9, "bold"), foreground="#555"
        )
        label.grid(
            row=row, column=0, columnspan=2, sticky="w", padx=8, pady=(10, 2)
        )
        return label


class SidebarNav(ttk.Frame):
    """Sidebar navigation widget replacing horizontal tabs."""

    def __init__(self, parent, items: List[Tuple[str, str]], command: Callable = None, on_select: Callable = None, **kwargs):
        """
        Args:
            parent: Parent widget
            items: List of (key, label) tuples
            command: Callback function(key) when item is selected (alias for on_select)
            on_select: Callback function(key) when item is selected (alias for command)
        """
        super().__init__(parent, **kwargs)
        self.items = items
        self.command = command or on_select
        self.current_key = None
        self.buttons = {}
        self._build()
        self._configure_style()

    def _configure_style(self):
        """Configure sidebar button style."""
        style = ttk.Style()
        try:
            style.configure("Sidebar.TButton", anchor="w", padding=(12, 8), font=("", 10))
            style.map("Sidebar.TButton",
                background=[("pressed", "#dbeafe"), ("active", "#eff6ff")],
                foreground=[("pressed", "#1d4ed8"), ("active", "#2563eb")]
            )
        except Exception:
            pass

    def _build(self):
        """Build the sidebar navigation."""
        for key, label in self.items:
            btn = ttk.Button(
                self,
                text=label,
                style="Sidebar.TButton",
                command=lambda k=key: self._on_select(k),
            )
            btn.pack(fill="x", padx=4, pady=2)
            self.buttons[key] = btn

    def _on_select(self, key: str):
        """Handle item selection."""
        if key == self.current_key:
            return
        self.current_key = key
        self._update_selection()
        if self.command:
            self.command(key)

    def _update_selection(self):
        """Update visual selection state."""
        for key, btn in self.buttons.items():
            if key == self.current_key:
                btn.state(["pressed"])
            else:
                btn.state(["!pressed"])

    def select(self, key: str):
        """Programmatically select an item."""
        if key in self.buttons:
            self._on_select(key)

    def set_active(self, key: str):
        """Alias for select() for compatibility."""
        self.select(key)

    def get_selection(self) -> Optional[str]:
        """Get currently selected key."""
        return self.current_key


class ThemeSelector(ttk.Frame):
    """Theme selector widget (Light/Dark/System) supporting either theme_manager or variable."""

    def __init__(self, parent, theme_manager=None, variable: Optional[tk.Variable] = None, command: Optional[Callable] = None, on_change: Optional[Callable] = None, **kwargs):
        super().__init__(parent, **kwargs)
        self.theme_manager = theme_manager
        self.on_change = command or on_change
        if variable is not None:
            self.variable = variable
        elif theme_manager is not None and hasattr(theme_manager, "current_theme"):
            self.variable = tk.StringVar(value=theme_manager.current_theme)
        else:
            self.variable = tk.StringVar(value="light")
        self._build()

    def _build(self):
        ttk.Label(self, text=_("theme_label")).pack(side="left", padx=(0, 8))
        for value, label in [("light", _("theme_light")), ("dark", _("theme_dark")), ("system", _("theme_system"))]:
            ttk.Radiobutton(
                self,
                text=label,
                variable=self.variable,
                value=value,
                command=self._on_change,
            ).pack(side="left", padx=4)

    def _on_change(self):
        val = self.variable.get()
        if self.theme_manager and hasattr(self.theme_manager, "apply_theme"):
            self.theme_manager.apply_theme(val)
        if self.on_change:
            self.on_change(val)


class UIScaleSelector(ttk.Frame):
    """UI Scale selector widget supporting either theme_manager or variable."""

    def __init__(self, parent, theme_manager=None, variable: Optional[tk.Variable] = None, command: Optional[Callable] = None, on_change: Optional[Callable] = None, **kwargs):
        super().__init__(parent, **kwargs)
        self.theme_manager = theme_manager
        self.on_change = command or on_change
        if variable is not None:
            self.variable = variable
        elif theme_manager is not None and hasattr(theme_manager, "ui_scale"):
            self.variable = tk.DoubleVar(value=theme_manager.ui_scale)
        else:
            self.variable = tk.DoubleVar(value=1.0)
        self._build()

    def _build(self):
        ttk.Label(self, text=_("ui_scale")).pack(side="left", padx=(0, 8))
        scale = ttk.Scale(
            self,
            from_=0.8,
            to=1.5,
            variable=self.variable,
            orient="horizontal",
            length=120,
            command=self._on_scale_change,
        )
        scale.pack(side="left", padx=4)
        self.value_label = ttk.Label(self, text=f"{self.variable.get():.1f}x")
        self.value_label.pack(side="left", padx=4)

    def _on_scale_change(self, value):
        scale_val = float(value)
        self.value_label.config(text=f"{scale_val:.1f}x")
        if self.theme_manager and hasattr(self.theme_manager, "set_ui_scale"):
            self.theme_manager.set_ui_scale(scale_val)
        if self.on_change:
            self.on_change(scale_val)


class ColorPicker(ttk.Frame):
    """Enhanced color picker widget with color history, favorites, and contrast checking."""

    def __init__(self, parent, variable: tk.Variable, on_pick: Optional[Callable] = None,
                 bg_color: str = "#ffffff", **kwargs):
        """
        Args:
            parent: Parent widget
            variable: Tkinter variable for the color value
            on_pick: Callback when color is picked
            bg_color: Background color for contrast checking (default white)
        """
        super().__init__(parent, **kwargs)
        self.variable = variable
        self.on_pick = on_pick
        self.bg_color = bg_color
        self._favorites = ["#37352f", "#2563eb", "#16a34a", "#dc2626", "#d97706", "#7c3aed"]
        self._build()

    @staticmethod
    def _hex_to_rgb(hex_color: str) -> tuple:
        """Convert hex color to RGB tuple."""
        hex_color = hex_color.lstrip('#')
        return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))

    @staticmethod
    def _luminance(rgb: tuple) -> float:
        """Calculate relative luminance of RGB color."""
        def channel(c):
            c = c / 255.0
            return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
        r, g, b = rgb
        return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)

    @classmethod
    def contrast_ratio(cls, fg_color: str, bg_color: str) -> float:
        """Calculate contrast ratio between two colors."""
        fg_rgb = cls._hex_to_rgb(fg_color)
        bg_rgb = cls._hex_to_rgb(bg_color)
        fg_lum = cls._luminance(fg_rgb)
        bg_lum = cls._luminance(bg_rgb)
        lighter = max(fg_lum, bg_lum)
        darker = min(fg_lum, bg_lum)
        return (lighter + 0.05) / (darker + 0.05)

    def _build(self):
        """Build the color picker UI."""
        # Current color display
        ttk.Label(self, text=_("accent_color") + ":").pack(side="left", padx=(0, 8))
        self.color_label = ttk.Label(self, text="", width=4, relief="solid", borderwidth=1, bg=self.variable.get())
        self.color_label.pack(side="left", padx=(0, 8))

        # Pick button
        ttk.Button(self, text="🎨", width=2, command=self._pick_color).pack(side="left", padx=(0, 8))

        # Current value display
        self.value_label = ttk.Label(self, text=self.variable.get(), foreground="#6b7280")
        self.value_label.pack(side="left", padx=(8, 0))

        # Contrast indicator
        self.contrast_label = ttk.Label(self, text="", style="Hint.TLabel")
        self.contrast_label.pack(side="left", padx=(8, 0))

        # Favorites frame (initially hidden, shown on demand)
        self.favorites_frame = ttk.Frame(self)
        self._build_favorites()

        self.variable.trace_add("write", self._update_display)

    def _build_favorites(self):
        """Build the favorites color palette."""
        ttk.Separator(self, orient="horizontal").pack(fill="x", pady=4)
        ttk.Label(self, text=_("color_favorites"), style="Hint.TLabel").pack(anchor="w")
        fav_frame = ttk.Frame(self.favorites_frame)
        fav_frame.pack(fill="x")
        for color in self._favorites:
            btn = tk.Button(
                fav_frame,
                text="  ",
                bg=color,
                width=2,
                height=1,
                relief="solid",
                borderwidth=1,
                command=lambda c=color: self._set_color(c)
            )
            btn.pack(side="left", padx=2)
            # Add tooltip with color value
            ToolTip(btn, color)

    def _update_display(self, *_):
        """Update the color display and contrast check."""
        try:
            color = self.variable.get()
            self.color_label.config(bg=color)
            self.value_label.config(text=color, foreground="#6b7280")

            # Check contrast against background
            ratio = self.contrast_ratio(color, self.bg_color)
            if ratio >= 4.5:
                self.contrast_label.config(
                    text=f"✓ {_('color_contrast_acceptable')} ({ratio:.1f}:1)",
                    foreground="#16a34a"
                )
            elif ratio >= 3.0:
                self.contrast_label.config(
                    text=f"⚠ {_('color_contrast_insufficient')} ({ratio:.1f}:1)",
                    foreground="#d97706"
                )
            else:
                self.contrast_label.config(
                    text=f"✗ {_('color_contrast_insufficient')} ({ratio:.1f}:1)",
                    foreground="#dc2626"
                )
        except Exception:
            pass

    def _pick_color(self):
        """Open color chooser dialog."""
        color = colorchooser.askcolor(self.variable.get(), self.master, _("color_picker_title"))
        if color[1]:
            self._set_color(color[1])

    def _set_color(self, color: str):
        """Set the color and update UI."""
        self.variable.set(color)
        if self.on_pick:
            self.on_pick(color)


class ModeToggle(ttk.Frame):
    """Simple/Advanced mode toggle widget."""

    def __init__(self, parent, variable: tk.Variable, on_change: Optional[Callable] = None, **kwargs):
        super().__init__(parent, **kwargs)
        self.variable = variable
        self.on_change = on_change
        self._build()

    def _build(self):
        ttk.Label(self, text=_("mode_toggle")).pack(side="left", padx=(0, 8))
        ttk.Radiobutton(
            self,
            text=_("simple_mode"),
            variable=self.variable,
            value="simple",
            command=self._on_change,
        ).pack(side="left", padx=4)
        ttk.Radiobutton(
            self,
            text=_("advanced_mode"),
            variable=self.variable,
            value="advanced",
            command=self._on_change,
        ).pack(side="left")

    def _on_change(self):
        if self.on_change:
            self.on_change(self.variable.get())


class ToolTip:
    """Enhanced tooltip for widgets."""

    def __init__(self, widget: tk.Widget, text: str, delay: int = 500):
        self.widget = widget
        self.text = text
        self.delay = delay
        self.tooltip = None
        self.after_id = None
        self._bind_events()

    def update_delay(self, delay: int):
        """Update the tooltip delay."""
        self.delay = delay

    def _bind_events(self):
        self.widget.bind("<Enter>", self._on_enter)
        self.widget.bind("<Leave>", self._on_leave)
        self.widget.bind("<ButtonPress>", self._on_leave)

    def _on_enter(self, event):
        self.after_id = self.widget.after(self.delay, self._show_tooltip)

    def _on_leave(self, event):
        if self.after_id:
            self.widget.after_cancel(self.after_id)
            self.after_id = None
        self._hide_tooltip()

    def _show_tooltip(self):
        if self.tooltip:
            return
        x = self.widget.winfo_rootx() + 10
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 10
        self.tooltip = tk.Toplevel(self.widget)
        self.tooltip.wm_overrideredirect(True)
        self.tooltip.wm_geometry(f"+{x}+{y}")
        label = tk.Label(self.tooltip, text=self.text, background="#ffffcc", relief="solid", borderwidth=1, padx=4, pady=2)
        label.pack()

    def _hide_tooltip(self):
        if self.tooltip:
            self.tooltip.destroy()
            self.tooltip = None


def add_font_field(
    g: Any, key: str, label_text: str, app: Any, allow_same: bool = False, hint: Optional[str] = None
):
    """Add a font picker field to a group frame."""
    import pageout.gui.theme as theme_mod
    from pageout.gui.theme import FONT_CATALOG

    fr = ttk.Frame(g)
    ent = ttk.Entry(fr, textvariable=app.V[key])
    ent.pack(side="left", fill="x", expand=True)

    def refresh(*_):
        name = app.V[key].get()
        try:
            from pageout.gui.theme import FONT_CATALOG, FONT_CATEGORY, GOOGLE_FONTS, SAME_AS_BODY

            # Check if this is "Same as body" or a known font
            if name == SAME_AS_BODY:
                # Will be handled via body font
                fam = None
            elif name in FONT_CATEGORY:
                fam = FONT_CATEGORY[name]
            elif name in GOOGLE_FONTS:
                fam = name
            else:
                # Check installed fonts
                if app.installed and name in app.installed:
                    fam = name
                else:
                    fam = None

            if fam:
                ent.config(font=(fam, 12) if name not in generic_aliases.values() else ("", 12))
            else:
                ent.config(font=("", 12))
        except Exception:
            pass

    # Generic aliases mapping
    generic_aliases = {"Sans-serif": "Helvetica", "Serif": "Times", "Monospace": "Courier"}

    # Determine font family
    from pageout.gui.theme import FONT_CATEGORY, GOOGLE_FONTS, SAME_AS_BODY

    def choose():
        from pageout.gui.i18n import EN

        FontPicker(app, app.V[key].get(), allow_same, lambda n: app.V[key].set(n))

    ttk.Button(fr, text="Choose font…", command=choose).pack(side="left", padx=(6, 0))
    app.V[key].trace_add("write", refresh)
    refresh()
    return fr, ent


def add_checkbox(
    parent: Any, text: str, variable: tk.Variable
) -> ttk.Checkbutton:
    """Add a styled checkbox."""
    cb = ttk.Checkbutton(parent, text=text, variable=variable)
    return cb


def add_spinbox(
    parent: Any, key: str, lo: float, hi: float, inc: float = 1, width: int = 8
) -> ttk.Spinbox:
    """Add a spinbox widget."""
    return ttk.Spinbox(parent, from_=lo, to=hi, increment=inc, textvariable=parent.V[key], width=width)


def add_combobox(
    parent: Any, key: str, values: List[str], state: str = "readonly", width: Optional[int] = None
) -> ttk.Combobox:
    """Add a combobox widget."""
    kw = {"width": width} if width else {}
    cb = ttk.Combobox(parent, textvariable=parent.V[key], values=values, state=state, **kw)
    cb._narrow = bool(width)
    return cb


def add_file_browse(
    parent: Any, variable: tk.Variable, button_text: str = "Browse…", title: str = "Choose"
) -> None:
    """Add a file browse button."""
    from tkinter import filedialog

    def browse():
        if title.lower() == "icon":
            p = filedialog.askopenfilename(
                title=title,
                filetypes=[("Images", "*.png *.jpg *.jpeg *.gif *.webp *.svg"), ("All files", "*.*")],
            )
        else:
            p = filedialog.askdirectory(title=title) if "folder" in title.lower() else filedialog.askopenfilename(title=title)
        if p:
            variable.set(p)

    ttk.Button(parent, text=button_text, command=browse).pack(side="left", padx=(6, 0))


def add_swatch(
    parent: Any, variable: tk.Variable, label_text: str = "Swatch"
) -> tk.Label:
    """Add a color swatch display."""
    swatch = tk.Label(parent, width=4, relief="solid", borderwidth=1)
    try:
        swatch.config(bg=variable.get())
    except Exception:
        pass
    variable.trace_add("write", lambda *_: swatch.config(bg=variable.get()) if variable.get() else None)
    return swatch


class ScrollableFrame(ttk.Frame):
    """A vertically scrollable frame widget."""

    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        self.canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0)
        self.v_scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas)

        self.inner.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")),
        )
        self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.v_scrollbar.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        self.v_scrollbar.pack(side="right", fill="y")

    def inner_frame(self) -> ttk.Frame:
        """Return the inner frame where widgets should be placed."""
        return self.inner


def create_tool_tip(widget: tk.Widget, text: str, delay: int = 500, app=None):
    """Create a tool tip for a widget."""
    tooltip = ToolTip(widget, text, delay)
    if app is not None:
        if not hasattr(app, '_tooltips'):
            app._tooltips = []
        app._tooltips.append(tooltip)
    return tooltip


def bind_enter_leave(
    widget: tk.Widget,
    enter_text: Optional[str] = None,
    leave_action: Optional[Callable] = None,
):
    """Bind enter/leave events to a widget for tool tips or actions."""
    if enter_text:
        ToolTip(widget, enter_text)
    if leave_action:
        widget.bind("<Leave>", lambda e: leave_action(e))


# Import i18n for widgets that need it
from pageout.gui.i18n import get_string as _