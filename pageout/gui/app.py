"""Tkinter GUI (thin layer over core.pipeline)."""

import os
import queue
import subprocess
import sys
import threading
import webbrowser

from notion_client import Client

try:
    import tkinter as tk
    import tkinter.font as tkfont
    from tkinter import colorchooser, filedialog, messagebox, ttk
except ImportError:  # headless use / tests
    tk = None
from pageout.core.config import (
    APP_NAME,
    APP_STAGE,
    APP_VERSION,
    CAPTION_FMTS,
    CONFIG_FILE,
    DATE_PRESETS,
    DB_EXPORT_MODES,
    DEFAULTS,
    ENGINES,
    FONT_CATALOG,
    FORMAT_LABELS,
    FORMATS,
    GEMINI_MODELS,
    HEAD_ALIGNS,
    ICON_MODES,
    IMG_MODES,
    IMG_PRESETS,
    LATEX_IMG_MODES,
    LINK_MODES,
    MATH_ENGINES,
    MD_PRESETS,
    NAME_PRESETS,
    OUTPUT_MODES,
    PAGE_SIZES,
    PAGENUM_FMT,
    PAGENUM_POS,
    PROP_LAYOUTS,
    SAME_AS_BODY,
    SORT_BUILTIN,
    SOURCE_TYPES,
    STYLE_PRESETS,
    SUB_MODES,
    TEXT_ALIGNS,
    load_config,
    save_config,
)
from pageout.core.errors import Cancelled
from pageout.core.naming import build_name
from pageout.core.paths import resource_path
from pageout.core.pipeline import Exporter, export
from pageout.core.secrets import keyring_available, redact
from pageout.ocr.gemini import _GENAI_AVAILABLE
from pageout.renderers.html import _HEX_RE
from pageout.renderers.pdf import login_to_notion
from pageout.sources.notion_api import load_property_names, page_fields
from pageout.gui.i18n import EN, get_string, _
from pageout.gui.widgets import ScrollFrame, CheckList, FontPicker
from pageout.gui.theme import ThemeManager, HiDPISupport


def _make_programmatic_icon():
    """Generate a small Notion-style 'N' icon as a PhotoImage (Tkinter)."""
    try:
        from PIL import Image, ImageDraw, ImageFont, ImageTk

        size = 64
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        # Rounded square background
        margin = 4
        draw.rounded_rectangle([margin, margin, size - margin, size - margin], radius=12, fill="#000000")
        # White "N"
        try:
            font = ImageFont.truetype("arial.ttf", 38)
        except Exception:
            font = ImageFont.load_default()
        bbox = draw.textbbox((0, 0), "N", font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text(((size - tw) / 2 - bbox[0], (size - th) / 2 - bbox[1]), "N", fill="white", font=font)
        return ImageTk.PhotoImage(img)
    except Exception:
        return None


def apply_icon(root):
    """
    Set the window icon.  Search order:
      1. icon.ico  (best on Windows – supports multi-res)
      2. icon.png  (cross-platform)
      3. icon.jpg  (project has this)
      4. Programmatic PIL icon
      5. No icon (silent fallback)
    """
    base = resource_path("icon")
    for ext in (".ico", ".png", ".jpg", ".jpeg"):
        p = base.with_suffix(ext)
        if p.exists():
            try:
                if ext == ".ico":
                    root.iconbitmap(str(p))
                    return
                else:
                    from PIL import Image, ImageTk

                    img = Image.open(str(p)).resize((64, 64), Image.LANCZOS)
                    ph = ImageTk.PhotoImage(img)
                    root.iconphoto(True, ph)
                    root._icon_ref = ph  # keep reference
                    return
            except Exception:
                continue
    # Programmatic fallback
    ph = _make_programmatic_icon()
    if ph:
        root.iconphoto(True, ph)
        root._icon_ref = ph


class App:
    def __init__(self):
        self.cfg0 = load_config()
        self.root = tk.Tk()
        self.root.title(f"{APP_NAME}  —  {APP_STAGE} {APP_VERSION}")
        sh = self.root.winfo_screenheight()
        self.root.geometry(f"860x{min(1000, sh - 80)}")
        self.root.minsize(700, 560)
        self.root.resizable(True, True)

        # Enable HiDPI support
        HiDPISupport.enable(self.root)

        # Apply custom icon (removes default Tkinter feather)
        apply_icon(self.root)

        # Initialize theme manager
        self.theme = ThemeManager(self.root)
        self.theme.apply_theme("light")

        self.V = {}
        for key, default in DEFAULTS.items():
            if key == "custom_css":
                continue
            val = self.cfg0.get(key, default)
            if isinstance(default, bool):
                self.V[key] = tk.BooleanVar(value=bool(val))
            elif isinstance(default, int):
                self.V[key] = tk.IntVar(value=int(val))
            elif isinstance(default, float):
                self.V[key] = tk.DoubleVar(value=float(val))
            else:
                self.V[key] = tk.StringVar(value=str(val))
        try:
            installed = sorted({f for f in tkfont.families(self.root) if not f.startswith("@")})
        except Exception:
            installed = []
        cat = [n for n, _, _ in FONT_CATALOG]
        self.installed = set(installed)
        self.font_values = ["Sans-serif", "Serif", "Monospace"] + cat + [f for f in installed if f not in cat]
        self.loaded_props, self.loaded_pages, self.loaded_source = [], [], ""
        self.q = queue.Queue()
        self.cancel = threading.Event()
        self.last_latex_text = None
        self.build()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(100, self.poll)

    # ---- helpers ----
    def collect(self):
        c = {k: v.get() for k, v in self.V.items()}
        c["custom_css"] = self.css_text.get("1.0", "end").strip()
        c["token"] = c["token"].strip()
        return c

    def log(self, msg):
        self.q.put(("log", msg))

    def progress(self, i, n):
        self.q.put(("progress", i, n))

    def append_log(self, msg):
        self.log_box.config(state="normal")
        self.log_box.insert("end", msg + "\n")
        self.log_box.see("end")
        self.log_box.config(state="disabled")

    @staticmethod
    def open_folder(path):
        try:
            if sys.platform.startswith("win"):
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception:
            pass

    def set_running(self, on):
        self.export_btn.config(state="disabled" if on else "normal")
        self.cancel_btn.config(state="normal" if on else "disabled")

    def need_basic(self, c):
        if not c["token"] or not c["database"].strip():
            messagebox.showerror("Missing info", "Enter the Notion token and a database / page ID or URL.")
            return False
        return True

    def row(self, parent, r, label, widget, pady=4):
        ttk.Label(parent, text=label).grid(row=r, column=0, sticky="ne", padx=8, pady=pady)
        widget.grid(row=r, column=1, sticky="we", padx=8, pady=pady)
        parent.columnconfigure(1, weight=1)

    def tab(self, title):
        f = ttk.Frame(self.nb)
        self.nb.add(f, text=title)
        return f

    def combo(self, parent, key, values, state="readonly", width=None):
        kw = {"width": width} if width else {}
        cb = ttk.Combobox(parent, textvariable=self.V[key], values=values, state=state, **kw)
        cb._narrow = bool(width)
        return cb

    def check(self, parent, key, text):
        return ttk.Checkbutton(parent, text=text, variable=self.V[key])

    def section(self, parent, row, text):
        """Small section header label."""
        ttk.Separator(parent, orient="horizontal").grid(
            row=row, column=0, columnspan=2, sticky="we", padx=8, pady=(10, 2)
        )
        ttk.Label(parent, text=text, font=("", 9, "bold"), foreground="#555").grid(
            row=row + 1, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 2)
        )

    # ---- actions ----
    def poll(self):
        try:
            while True:
                item = self.q.get_nowait()
                kind = item[0]
                if kind == "log":
                    self.append_log(item[1])
                elif kind == "progress":
                    _, i, n = item
                    self.bar.config(maximum=max(n, 1), value=i)
                    self.status.set(f"{i} / {n}")
                elif kind == "done":
                    out = item[1]
                    count = item[2]
                    failed = item[3]
                    last_tex = item[4] if len(item) > 4 else ""
                    skipped = item[5] if len(item) > 5 else 0
                    timing_summary = item[6] if len(item) > 6 else None
                    self.set_running(False)
                    text = f"Exported {count - skipped} page(s)."
                    if skipped:
                        text += f"\n{skipped} unchanged page(s) skipped (tick “Force full re-export” to redo them)."
                    if timing_summary:
                        text += f"\n\nTiming: {timing_summary}"
                    text += f"\n\n{out}"
                    if last_tex:
                        self.last_latex_text = last_tex
                        self.copy_latex_btn.config(state="normal")
                        text += "\n\nLaTeX export ready! Click '📋 Copy LaTeX' to copy."
                    if failed:
                        text += f"\n\n{len(failed)} problem(s):\n" + "\n".join(f"- {f}: {r}" for f, r in failed[:10])
                    messagebox.showinfo("Done", text)
                    self.open_folder(out)
                elif kind == "cancelled":
                    self.set_running(False)
                    self.append_log("Cancelled. Files exported so far were kept.")
                elif kind == "error":
                    self.set_running(False)
                    messagebox.showerror("Export failed", item[1])
                elif kind == "call":
                    _, fn, res, err = item
                    self.root.config(cursor="")
                    fn(res, err)
                elif kind == "loginend":
                    self.login_btn.config(state="normal")
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def save_gemini_key(self):
        c = self.collect()
        warn = save_config(c)
        where = "the OS keyring" if keyring_available() else CONFIG_FILE
        messagebox.showinfo("Key Saved", warn or f"Gemini API key saved to {where}.")

    def copy_latex(self):
        if not getattr(self, "last_latex_text", None):
            messagebox.showinfo(
                "Copy LaTeX", "No LaTeX export is available yet. Run an export with 'LaTeX (.tex)' selected."
            )
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(self.last_latex_text)
        messagebox.showinfo("Copied to Clipboard", "Complete LaTeX document copied to clipboard!")

    def start_export(self):
        try:
            c = self.collect()
        except Exception:
            messagebox.showerror("Invalid value", "Check the numeric fields.")
            return
        if not self.need_basic(c):
            return
        if not c["save_dir"].strip():
            messagebox.showerror("Missing folder", "Choose an output folder on the Output tab.")
            return
        if c.get("gemini_math_ocr"):
            if not _GENAI_AVAILABLE:
                messagebox.showerror(
                    "Package Missing",
                    "The 'google-genai' library is required for Gemini Math OCR.\n\n"
                    "Please install it with:\n  pip install google-genai",
                )
                return
            if not c.get("gemini_api_key", "").strip():
                messagebox.showerror(
                    "Gemini API Key Required",
                    "Math OCR with Gemini Vision is enabled, but no Gemini API Key was entered.\n\n"
                    "Please enter your personal Gemini API key in the 'LaTeX & OCR' tab.\n"
                    "You can get a free key at:\nhttps://aistudio.google.com/",
                )
                return
        warn = save_config(c)
        if warn:
            messagebox.showwarning("Secrets not saved", warn)
        shown = self.props_list.selected_labels()
        selected = None
        if self.loaded_pages and self.loaded_source == c["database"].strip():
            sel = self.pages_list.selected_indices()
            if not sel:
                messagebox.showerror(
                    "No pages ticked", "Tick at least one page in tab 2, or clear the list by loading pages again."
                )
                return
            selected = [self.loaded_pages[i] for i in sel]
        self.cancel.clear()
        self.set_running(True)
        self.bar.config(value=0)

        def worker():
            try:
                res = export(
                    c,
                    self.progress,
                    self.cancel,
                    self.log,
                    selected_roots=selected,
                    all_props=self.loaded_props,
                    shown_props=shown,
                )
                timing_summary = res.timing.summary() if res.timing else None
                self.q.put(("done", res.out_dir, res.total, res.failed, res.last_tex, res.skipped, timing_summary))
            except Cancelled:
                self.q.put(("cancelled",))
            except Exception as e:
                self.q.put(("error", redact(e, [c.get("token", ""), c.get("gemini_api_key", "")])))

        threading.Thread(target=worker, daemon=True).start()

    def cancel_export(self):
        self.cancel.set()
        self.append_log("Cancelling after the current page...")

    def do_login(self):
        self.login_btn.config(state="disabled")

        def worker():
            try:
                login_to_notion(self.log)
            except Exception as e:
                self.log("Login window error: " + str(e))
            self.q.put(("loginend",))

        threading.Thread(target=worker, daemon=True).start()

    def bg(self, work, done):
        """Run `work` in a thread (UI stays responsive); `done(result, error)` runs in the UI thread."""
        self.root.config(cursor="watch")

        def runner():
            try:
                res, err = work(), None
            except Exception as e:
                res, err = None, e
            self.q.put(("call", done, res, err))

        threading.Thread(target=runner, daemon=True).start()

    def load_props(self):
        c = self.collect()
        if not self.need_basic(c):
            return

        def work():
            return load_property_names(Client(auth=c["token"]), c["database"], c["source_type"])

        def done(names, err):
            if err:
                messagebox.showerror("Could not load properties", str(err))
                return
            self.loaded_props = names
            self.props_list.set_items(names)
            self.sort_combo.config(values=SORT_BUILTIN + names)
            self.filter_combo.config(values=[""] + names + ["Title", "Date"])
            self.hint.set(
                "Placeholders: {title} {date} {index} {created} {edited} {parent}\n"
                "Your properties: "
                + " ".join("{%s}" % n for n in names)
                + "\nFormats: {date:%d-%m-%Y}   {title:40} (truncate)"
            )
            self.append_log(f"Loaded {len(names)} properties.")

        self.bg(work, done)

    def load_pages(self):
        c = self.collect()
        if not self.need_basic(c):
            return

        def done(pages, err):
            if err:
                messagebox.showerror("Could not load pages", str(err))
                return
            self.loaded_pages, self.loaded_source = pages, c["database"].strip()
            labels = []
            for p in pages:
                f = page_fields(p)
                labels.append(f"{f['date'] or '—'}   {f['title']}")
            self.pages_list.set_items(labels)
            self.append_log(f"Loaded {len(pages)} pages. Deselect the ones you don't want.")

        self.bg(lambda: Exporter(c).fetch_roots(), done)

    def preview_names(self):
        try:
            c = self.collect()
        except Exception:
            messagebox.showerror("Invalid value", "Check the numeric fields.")
            return
        if not self.need_basic(c):
            return

        def work():
            return Exporter(c).fetch_roots()[:8]

        def done(pages, err):
            if err:
                messagebox.showerror("Preview failed", str(err))
                return
            names = [build_name(c["name_format"], page_fields(p, i, 2)) for i, p in enumerate(pages, 1)]
            img = [
                build_name(
                    c["img_format"], dict(page_fields(p, i, 2), page=n, n="01", caption="caption", original="image")
                )
                for i, (p, n) in enumerate(zip(pages, names), 1)
            ][:3]
            messagebox.showinfo(
                "Name preview", "Files:\n" + "\n".join(names) + "\n\nImages:\n" + "\n".join(x + ".png" for x in img)
            )

        self.bg(work, done)

    def choose_folder(self):
        d = filedialog.askdirectory(title="Choose output folder")
        if d:
            self.V["save_dir"].set(d)

    def choose_icon_file(self):
        p = filedialog.askopenfilename(
            title="Choose custom icon image",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.gif *.webp *.svg"), ("All files", "*.*")],
        )
        if p:
            self.V["icon_custom_file"].set(p)

    def select_pages(self, all_):
        self.pages_list.select_all(all_)

    def on_close(self):
        try:
            save_config(self.collect())
        except Exception:
            pass
        self.root.destroy()

    # ---- layout helpers ----
    def page(self, title):
        sf = ScrollFrame(self.nb)
        self.nb.add(sf, text=title)
        return sf.inner

    def group(self, parent, title):
        g = ttk.LabelFrame(parent, text=" " + title + " ", padding=(12, 8))
        g.pack(fill="x", padx=12, pady=(8, 2))
        g.columnconfigure(1, weight=1)
        g._r = 0
        return g

    def field(self, g, label, widget, hint=None):
        r = g._r
        ttk.Label(g, text=label).grid(row=r, column=0, sticky="ne", padx=(0, 12), pady=4)
        narrow = isinstance(widget, (ttk.Button, ttk.Spinbox)) or getattr(widget, "_narrow", False)
        widget.grid(row=r, column=1, sticky="w" if narrow else "we", pady=4)
        r += 1
        if hint:
            ttk.Label(g, text=hint, style="Hint.TLabel", wraplength=540, justify="left").grid(
                row=r, column=1, sticky="w", pady=(0, 4)
            )
            r += 1
        g._r = r

    def tick(self, g, key, text, hint=None):
        ttk.Checkbutton(g, text=text, variable=self.V[key]).grid(row=g._r, column=0, columnspan=2, sticky="w", pady=2)
        g._r += 1
        if hint:
            ttk.Label(g, text=hint, style="Hint.TLabel", wraplength=540, justify="left").grid(
                row=g._r, column=0, columnspan=2, sticky="w", padx=(24, 0), pady=(0, 4)
            )
            g._r += 1

    def note(self, g, text, var=None):
        lab = ttk.Label(g, text=text, textvariable=var, style="Hint.TLabel", wraplength=560, justify="left")
        lab.grid(row=g._r, column=0, columnspan=2, sticky="w", pady=(0, 4))
        g._r += 1
        return lab

    def spin(self, parent, key, lo, hi, inc=1, w=8):
        return ttk.Spinbox(parent, from_=lo, to=hi, increment=inc, textvariable=self.V[key], width=w)

    def _on_wheel(self, e):
        """One global mouse-wheel handler: scrolls the list under the cursor, else the page."""
        w = e.widget
        if isinstance(w, str):
            return None
        try:
            if w.winfo_toplevel() is not self.root or w.winfo_class() == "Text":
                return None
        except Exception:
            return None
        num = getattr(e, "num", 0)
        if num == 4:
            steps = -1
        elif num == 5:
            steps = 1
        else:
            d = getattr(e, "delta", 0)
            steps = (-d if sys.platform == "darwin" else -int(d / 120)) or (-1 if d > 0 else 1)
        while w is not None:
            cv = getattr(w, "_wheel_canvas", None)
            if cv is not None:
                lo, hi = cv.yview()
                if (steps < 0 and lo > 0.0) or (steps > 0 and hi < 1.0):
                    cv.yview_scroll(steps * 3, "units")
                    return "break"
            w = getattr(w, "master", None)
        return None

    def _wheel_block(self, e):
        self._on_wheel(e)
        return "break"  # comboboxes / spinboxes must not change value while scrolling

    def font_field(self, g, label, key, allow_same=False, hint=None):
        fr = ttk.Frame(g)
        ent = ttk.Entry(fr, textvariable=self.V[key])
        ent.pack(side="left", fill="x", expand=True)

        def refresh(*_):
            name = self.V[key].get()
            fam = _GENERIC_FONT_ALIAS.get(name, name)
            try:
                ent.config(
                    font=(fam, 12) if fam in self.installed or fam in _GENERIC_FONT_ALIAS.values() else "TkDefaultFont"
                )
            except Exception:
                pass

        def choose():
            FontPicker(self, self.V[key].get(), allow_same, lambda n: self.V[key].set(n))

        ttk.Button(fr, text="Choose font…", command=choose).pack(side="left", padx=(6, 0))
        self.V[key].trace_add("write", refresh)
        refresh()
        self.field(g, label, fr, hint)

    def show_about(self):
        messagebox.showinfo(
            f"About {APP_NAME}",
            f"{APP_NAME}\nVersion {APP_VERSION}  ({APP_STAGE})\n\n"
            "This is a BETA release: all main features work, but it is still new and being tested.\n"
            "Bugs are expected. Please keep a copy of important data, and report problems "
            "together with the text from the log box at the bottom of the window.",
        )

    def apply_preset(self, *_):
        preset = STYLE_PRESETS.get(self.V["theme_preset"].get())
        if preset:
            for k, v in preset.items():
                self.V[k].set(v)

    def pick_color(self):
        cur = self.V["accent_color"].get()
        rgb, hexv = colorchooser.askcolor(
            color=cur if _HEX_RE.match(cur or "") else "#37352f", title="Accent color (headings, links, quote bars)"
        )
        if hexv:
            self.V["accent_color"].set(hexv)

    def update_swatch(self, *_):
        try:
            self.swatch.config(bg=self.V["accent_color"].get())
        except Exception:
            pass

    def update_summary(self, *_):
        try:
            fm = [FORMAT_LABELS[k] for k in FORMATS + ["images"] if self.V["fmt_" + k].get()]
            out = self.V["save_dir"].get().strip() or "(choose an output folder in tab 8)"
            self.summary.set("Will export: " + (", ".join(fm) if fm else "nothing selected (tab 3)") + "   →   " + out)
        except Exception:
            pass

    # ---- layout ----
    def build(self):
        V = self.V
        style = ttk.Style()
        try:
            if sys.platform.startswith("win"):
                style.theme_use("vista")
            base = tkfont.nametofont("TkDefaultFont")
            base.configure(size=10, family="Segoe UI" if sys.platform.startswith("win") else base.actual("family"))
            tkfont.nametofont("TkTextFont").configure(size=10)
        except Exception:
            pass
        style.configure("Hint.TLabel", foreground="#6b7280", font=("", 9))
        style.configure("Head.TLabel", font=("", 15, "bold"))
        style.configure("Accent.TButton", font=("", 11, "bold"), padding=(18, 7))
        style.configure("TNotebook.Tab", padding=(11, 6))

        # ---- header ----
        head = ttk.Frame(self.root)
        head.pack(fill="x", padx=14, pady=(10, 0))
        try:
            from PIL import Image, ImageTk

            for ext in (".png", ".ico"):
                ip = resource_path("icon" + ext)
                if ip.exists():
                    self._hdr_icon = ImageTk.PhotoImage(
                        Image.open(str(ip)).convert("RGBA").resize((40, 40), Image.LANCZOS)
                    )
                    ttk.Label(head, image=self._hdr_icon).pack(side="left", padx=(0, 10))
                    break
        except Exception:
            pass
        tf = ttk.Frame(head)
        tf.pack(side="left")
        tr = ttk.Frame(tf)
        tr.pack(anchor="w")
        ttk.Label(tr, text=APP_NAME, style="Head.TLabel").pack(side="left")
        tk.Label(tr, text=f" {APP_STAGE} ", bg="#f59e0b", fg="white", font=("", 8, "bold")).pack(side="left", padx=8)
        ttk.Label(
            tf, text="Follow the tabs 1 → 8, then press Export.  Only tabs 1 and 8 are required.", style="Hint.TLabel"
        ).pack(anchor="w")

        ttk.Button(head, text="About / Beta", command=self.show_about).pack(side="right")
        self.nb = ttk.Notebook(self.root)
        self.root.bind_all("<MouseWheel>", self._on_wheel)
        self.root.bind_all("<Button-4>", self._on_wheel)
        self.root.bind_all("<Button-5>", self._on_wheel)
        for cls in ("TCombobox", "TSpinbox"):
            self.root.bind_class(cls, "<MouseWheel>", self._wheel_block)
            self.root.bind_class(cls, "<Button-4>", self._wheel_block)
            self.root.bind_class(cls, "<Button-5>", self._wheel_block)

        # ═══════════════ 1 · Source ═══════════════
        t = self.page("1  Source")
        g = self.group(t, "Notion connection")
        self.token_entry = ttk.Entry(g, textvariable=V["token"], show="•")
        self.field(
            g,
            "Integration token",
            self.token_entry,
            "Create one at notion.so/my-integrations, then in Notion open your page → ••• → "
            "Connections → add your integration.",
        )
        self.show_token = tk.BooleanVar(value=False)
        o = ttk.Frame(g)
        ttk.Checkbutton(
            o,
            text="Show token",
            variable=self.show_token,
            command=lambda: self.token_entry.config(show="" if self.show_token.get() else "•"),
        ).pack(side="left")
        ttk.Checkbutton(o, text="Remember on this PC (OS keyring)", variable=V["remember_token"]).pack(
            side="left", padx=14
        )
        ttk.Button(
            o, text="Open integrations page ↗", command=lambda: webbrowser.open("https://www.notion.so/my-integrations")
        ).pack(side="left")
        self.field(g, "", o)
        self.tick(
            g,
            "allow_plaintext_secrets",
            "Allow plain-text storage if no OS keyring is available",
            "Keyring found: yes — secrets are stored in the OS credential store."
            if keyring_available()
            else "No OS keyring found (pip install keyring). Without it the token is not remembered "
            "unless you tick the box above.",
        )

        g = self.group(t, "What to export")
        self.field(
            g,
            "Database / page link",
            ttk.Entry(g, textvariable=V["database"]),
            "Paste the Notion link (or ID). To export several, separate links with spaces or commas.",
        )
        self.field(
            g,
            "It is a…",
            self.combo(g, "source_type", SOURCE_TYPES, width=18),
            "Leave on Auto-detect unless the app guesses wrong.",
        )

        g = self.group(t, "Private pages — Browser PDF engine only")
        self.tick(
            g,
            "use_login",
            "Use my saved Notion login",
            "Only needed when the PDF engine is set to “Browser”. The default API engine does not need this.",
        )
        self.login_btn = ttk.Button(g, text="Log in to Notion…", command=self.do_login)
        self.field(g, "", self.login_btn, "A browser window opens: sign in, then close the window.")

        # ═══════════════ 2 · Pages ═══════════════
        t = self.page("2  Pages")
        g = self.group(t, "Choose which pages")
        pr = ttk.Frame(g)
        ttk.Button(pr, text="Load pages", command=self.load_pages).pack(side="left")
        ttk.Button(pr, text="Select all", command=lambda: self.select_pages(True)).pack(side="left", padx=6)
        ttk.Button(pr, text="Clear", command=lambda: self.select_pages(False)).pack(side="left")
        self.field(
            g,
            "Page list",
            pr,
            "Optional. If you never press “Load pages”, every page is exported. "
            "After loading, only ticked pages are exported.",
        )
        self.pages_list = CheckList(g, height=210, empty_text="Press “Load pages” to see your pages here.")
        self.field(g, "", self.pages_list)
        self.field(g, "", ttk.Label(g, textvariable=self.pages_list.info, style="Hint.TLabel"))

        g = self.group(t, "Order & filter")
        sr = ttk.Frame(g)
        self.sort_combo = ttk.Combobox(sr, textvariable=V["sort_by"], values=SORT_BUILTIN, width=22)
        self.sort_combo.pack(side="left")
        ttk.Checkbutton(sr, text="Descending", variable=V["sort_desc"]).pack(side="left", padx=10)
        self.field(g, "Sort by", sr)
        fr = ttk.Frame(g)
        self.filter_combo = ttk.Combobox(fr, textvariable=V["filter_prop"], width=16)
        self.filter_combo.pack(side="left")
        ttk.Combobox(
            fr,
            textvariable=V["filter_op"],
            values=["contains", "does not contain", "equals"],
            state="readonly",
            width=15,
        ).pack(side="left", padx=4)
        ttk.Entry(fr, textvariable=V["filter_value"], width=18).pack(side="left")
        self.field(g, "Only pages where", fr, "Leave empty for no filter.")
        self.field(g, "Max pages", self.spin(g, "max_pages", 0, 100000), "0 = no limit.")

        g = self.group(t, "File names")
        self.field(g, "Name format", ttk.Entry(g, textvariable=V["name_format"]))
        pre = ttk.Combobox(g, values=NAME_PRESETS, state="readonly")
        pre.bind("<<ComboboxSelected>>", lambda e: V["name_format"].set(pre.get()))
        self.field(g, "Examples", pre)
        self.hint = tk.StringVar(
            value="Placeholders: {title} {date} {index} {created} {edited} {parent}\n"
            "Click “Load properties” (tab 4) to list your own.\n"
            "Formats: {date:%d-%m-%Y}   {title:40} (truncate)"
        )
        self.note(g, "", self.hint)
        self.field(g, "", ttk.Button(g, text="Preview names", command=self.preview_names))

        # ═══════════════ 3 · Formats ═══════════════
        t = self.page("3  Formats")
        g = self.group(t, "Export as (tick one or more)")
        ff = ttk.Frame(g)
        for n, k in enumerate(FORMATS + ["images"]):
            ttk.Checkbutton(ff, text=FORMAT_LABELS[k], variable=V["fmt_" + k]).grid(
                row=n // 4, column=n % 4, sticky="w", padx=(0, 22), pady=3
            )
        self.field(g, "Formats", ff)
        g = self.group(t, "PDF engine")
        self.field(
            g,
            "Engine",
            self.combo(g, "engine", ENGINES),
            "API = fast, no login, uses your Design tab settings (fonts, colors…).\n"
            "Browser = prints the real Notion page (slower; needs login for private pages; "
            "ignores Design settings).",
        )
        g = self.group(t, "Sub-pages")
        self.field(
            g,
            "Sub-pages",
            self.combo(g, "sub_mode", SUB_MODES),
            "Skip, put inside the parent page, or export each as its own file.",
        )
        self.field(g, "Depth", self.spin(g, "sub_depth", 1, 10), "How many levels of sub-pages to follow.")
        self.tick(g, "sub_dbs", "Also export rows of databases inside pages (separate files mode)")
        g = self.group(t, "Combined file")
        self.tick(g, "combine", "Also create one combined HTML / Markdown / LaTeX file")
        g = self.group(t, "Markdown & databases")
        self.field(
            g,
            "Markdown flavour",
            self.combo(g, "md_preset", MD_PRESETS, width=18),
            "GFM = tables, task lists, <details>.  Vanilla = no raw HTML.  Obsidian = [[wikilinks]], callouts, tags.",
        )
        self.field(
            g,
            "Database extras",
            self.combo(g, "db_export", DB_EXPORT_MODES, width=22),
            "Index page / table of properties (links to every exported file) or a CSV of all properties.",
        )

        # ═══════════════ 4 · Design ═══════════════
        t = self.page("4  Design")
        g = self.group(t, "Quick style")
        pc = ttk.Combobox(g, textvariable=V["theme_preset"], values=list(STYLE_PRESETS), state="readonly")
        pc.bind("<<ComboboxSelected>>", self.apply_preset)
        self.field(
            g,
            "Style preset",
            pc,
            "Picks fonts, spacing and colors in one click. You can still change every setting below.",
        )

        g = self.group(t, "Fonts")
        self.font_field(
            g,
            "Body font",
            "font_family",
            False,
            "Press “Choose font…” to see every font in its own style. Arabic: Cairo, Tajawal, Amiri…",
        )
        self.font_field(g, "Heading font", "heading_font", True)
        self.tick(
            g,
            "web_fonts",
            "Download fonts from Google Fonts when needed (internet required)",
            "Fonts such as Inter, Lora, Playfair Display or Cairo are not on most PCs. Tick this to use them.",
        )
        self.field(g, "Font size (px)", self.spin(g, "base_font_size", 10, 28))
        self.field(g, "Line spacing", self.spin(g, "line_spacing", 1.0, 3.0, 0.1))
        self.field(g, "Text alignment", self.combo(g, "text_align", TEXT_ALIGNS, width=14))
        self.field(g, "Title alignment", self.combo(g, "heading_align", HEAD_ALIGNS, width=14))

        g = self.group(t, "Color")
        cr = ttk.Frame(g)
        ttk.Entry(cr, textvariable=V["accent_color"], width=10).pack(side="left")
        self.swatch = tk.Label(cr, width=4, relief="solid", borderwidth=1)
        self.swatch.pack(side="left", padx=6)
        ttk.Button(cr, text="Choose…", command=self.pick_color).pack(side="left")
        V["accent_color"].trace_add("write", self.update_swatch)
        self.update_swatch()
        self.field(g, "Accent color", cr, "Used for headings, links, quote bars and the title line.")

        g = self.group(t, "Title area")
        self.tick(g, "title_separator", "Show a colored line under the page title")
        self.field(g, "Page icon", self.combo(g, "icon_mode", ICON_MODES, width=22))
        icon_row = ttk.Frame(g)
        ttk.Entry(icon_row, textvariable=V["icon_custom_file"]).pack(side="left", fill="x", expand=True)
        ttk.Button(icon_row, text="Browse…", command=self.choose_icon_file).pack(side="left", padx=4)
        self.field(g, "Custom icon file", icon_row, "Used only when “Custom icon file” is selected above.")
        self.tick(g, "cover_page", "Cover page: title, icon and properties alone on page 1")

        g = self.group(t, "Properties (database fields)")
        self.field(
            g,
            "Layout",
            self.combo(g, "prop_layout", PROP_LAYOUTS, width=22),
            "Notion Table · Inline Pills · Minimalist List · Hidden",
        )
        self.field(
            g,
            "Date format",
            self.combo(g, "date_format_props", DATE_PRESETS, state="normal", width=22),
            "Or type any pattern, e.g. %d.%m.%Y",
        )
        self.field(
            g,
            "",
            ttk.Button(g, text="Load properties", command=self.load_props),
            "Load the list, then keep selected only the properties you want shown.",
        )
        self.props_list = CheckList(
            g, height=150, empty_text="Press “Load properties” first (all are shown until then)."
        )
        self.field(g, "Show these", self.props_list, "Untick the properties you do not want in the export.")
        pb = ttk.Frame(g)
        ttk.Button(pb, text="Tick all", command=lambda: self.props_list.select_all(True)).pack(side="left")
        ttk.Button(pb, text="Untick all", command=lambda: self.props_list.select_all(False)).pack(side="left", padx=6)
        ttk.Label(pb, textvariable=self.props_list.info, style="Hint.TLabel").pack(side="left", padx=8)
        self.field(g, "", pb)

        g = self.group(t, "Content")
        self.tick(g, "render_math", "Render math equations nicely (KaTeX)")
        self.field(
            g,
            "Math engine",
            self.combo(g, "math_engine", MATH_ENGINES, width=22),
            "Bundled = works offline (adds ~600 KB to each HTML file). CDN = needs internet. None = plain LaTeX text.",
        )
        self.tick(
            g,
            "rewrite_links",
            "Rewrite links between exported pages to local files",
            "Links to pages that are exported too become relative links that work offline (HTML and Markdown).",
        )
        self.tick(g, "expand_toggles", "Expand all toggle blocks")
        self.field(g, "Links", self.combo(g, "links", LINK_MODES))
        self.tick(g, "light_theme", "Force light theme  (Browser engine only)")
        self.tick(g, "clean_layout", "Hide Notion sidebar / top bar  (Browser engine only)")
        self.css_text = tk.Text(g, height=5, width=50)
        self.css_text.insert("1.0", self.cfg0.get("custom_css", ""))
        self.field(g, "Custom CSS", self.css_text, "For experts. Example: h1 { color: #c00; }")

        # ═══════════════ 5 · Images ═══════════════
        t = self.page("5  Images")
        g = self.group(t, "Images inside documents")
        self.field(
            g,
            "Handling",
            self.combo(g, "img_handling", IMG_MODES),
            "Notion image links expire after about an hour, so “Embed” or “Save locally” is safest.",
        )
        self.tick(g, "optimize_images", "Shrink big photos for PDF / Word (faster export, smaller files)")
        self.field(
            g,
            "Max image size (px)",
            self.spin(g, "image_max_px", 600, 4000, 100, 8),
            "Saved image files are never changed — only the copy inside the PDF / Word file.",
        )
        g = self.group(t, "Image layout (PDF / HTML / Word)")
        self.tick(g, "maximize_images", "Maximize images (full page width)")
        self.tick(g, "one_image_per_page", "One image per page")
        self.tick(g, "show_image_names", "Show image file names under images (when Notion has no caption)")
        cf = ttk.Frame(g)
        ttk.Combobox(cf, textvariable=V["caption_format"], values=CAPTION_FMTS, width=28).pack(side="left")
        self.field(g, "Caption format", cf, "Placeholders: {name} {ext} {n} {original} {caption}")
        g = self.group(t, "Saving image files  (tick “Images” in tab 3)")
        self.field(
            g,
            "File name format",
            ttk.Entry(g, textvariable=V["img_format"]),
            "Placeholders: {page} {title} {n} {caption} {original} {date} {index} {parent}",
        )
        ip = ttk.Combobox(g, values=IMG_PRESETS, state="readonly")
        ip.bind("<<ComboboxSelected>>", lambda e: V["img_format"].set(ip.get()))
        self.field(g, "Examples", ip)
        self.tick(g, "img_subfolder", "Put each page's images in its own folder")
        self.tick(g, "img_cover", "Include page cover images ({n} = cover)")

        # ═══════════════ 6 · PDF ═══════════════
        t = self.page("6  PDF")
        g = self.group(t, "Page")
        self.field(g, "Page size", self.combo(g, "page_size", PAGE_SIZES, width=14))
        self.field(g, "Orientation", self.combo(g, "orientation", ["Portrait", "Landscape"], width=14))
        self.field(
            g, "Margin (mm)", self.spin(g, "margin_mm", 0, 50), "20 mm is comfortable for A4. Use 10 for denser pages."
        )
        self.field(g, "Scale (%)", self.spin(g, "scale", 10, 200))
        self.tick(g, "print_background", "Print background colors")
        self.tick(
            g,
            "remove_blank_pages",
            "Automatically remove empty pages",
            "Deletes pages that contain no text, image or drawing (for example after a page break).",
        )
        g = self.group(t, "Page numbers")
        self.tick(g, "page_numbers", "Add page numbers")
        self.field(g, "Position", self.combo(g, "page_num_position", PAGENUM_POS, width=18))
        self.field(g, "Format", self.combo(g, "page_num_format", PAGENUM_FMT, width=18))

        # ═══════════════ 7 · LaTeX & AI ═══════════════
        t = self.page("7  LaTeX & AI")
        g = self.group(t, "LaTeX (.tex)")
        self.tick(g, "fmt_tex", "Export as LaTeX (.tex) document", "Compile with pdflatex (xelatex for Arabic).")
        self.field(
            g,
            "Images in .tex",
            self.combo(g, "latex_images", LATEX_IMG_MODES, width=20),
            "Include = images are saved next to the .tex (webp/gif are converted to PNG).",
        )
        cb = ttk.Frame(g)
        ttk.Button(cb, text="📋 Copy last exported LaTeX", command=self.copy_latex).pack(side="left")
        self.field(g, "Clipboard", cb)
        g = self.group(t, "Gemini Math OCR — whiteboard photos → LaTeX")
        self.note(
            g,
            "Each user enters their own key. It is stored in the OS keyring "
            "(or in ~/.notion_pdf_exporter/config.json only if you allowed plain text).",
        )
        kf = ttk.Frame(g)
        self.gemini_key_entry = ttk.Entry(kf, textvariable=V["gemini_api_key"], show="•")
        self.gemini_key_entry.pack(side="left", fill="x", expand=True)
        self.show_gemini_key = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            kf,
            text="Show",
            variable=self.show_gemini_key,
            command=lambda: self.gemini_key_entry.config(show="" if self.show_gemini_key.get() else "•"),
        ).pack(side="left", padx=6)
        ttk.Button(kf, text="Save", command=self.save_gemini_key).pack(side="left")
        ttk.Button(kf, text="Get free key ↗", command=lambda: webbrowser.open("https://aistudio.google.com/")).pack(
            side="left", padx=6
        )
        self.field(g, "Gemini API key", kf)
        self.tick(g, "gemini_math_ocr", "Scan images with Gemini Math OCR")
        self.field(
            g,
            "Model",
            self.combo(g, "gemini_model", GEMINI_MODELS, state="normal"),
            "You can type any Gemini model name here.",
        )
        self.tick(g, "keep_whiteboard_image", "Keep a note of the original image below the transcription")

        # ═══════════════ 8 · Output ═══════════════
        t = self.page("8  Output")
        g = self.group(t, "Where to save")
        orow = ttk.Frame(g)
        ttk.Entry(orow, textvariable=V["save_dir"]).pack(side="left", fill="x", expand=True)
        ttk.Button(orow, text="Browse…", command=self.choose_folder).pack(side="left", padx=4)
        self.field(g, "Output folder  (required)", orow)
        g = self.group(t, "PDF files")
        self.field(g, "PDF output", self.combo(g, "output_mode", OUTPUT_MODES))
        self.field(g, "Merged file name", ttk.Entry(g, textvariable=V["merged_name"]))
        self.tick(g, "bookmarks", "Add bookmarks to the merged PDF")
        g = self.group(t, "Speed & reliability")
        self.field(
            g,
            "Parallel downloads",
            self.spin(g, "workers", 1, 8),
            "Pages and images are fetched in the background while the previous page is rendered. "
            "Notion limits requests (~3 per second), so more than 4 rarely helps.",
        )
        self.tick(
            g,
            "incremental",
            "Incremental sync: skip pages that did not change since the last export",
            "Uses Notion's last-edited time and your settings. Off automatically for combined files, "
            "inline sub-pages and raw image export.",
        )
        self.tick(g, "force", "Force full re-export (ignore the incremental cache)")
        self.tick(g, "skip_existing", "Skip files already exported (resume an interrupted export)")
        self.field(g, "Retries on failure", self.spin(g, "retries", 0, 5))
        self.field(g, "Extra wait per page (s)", self.spin(g, "extra_wait", 0, 60, 0.5), "Browser engine only.")
        self.tick(g, "profile_timing", "Save timing_report.json with export profiling data")

        # ---- bottom bar ----
        run = ttk.Frame(self.root)
        self.export_btn = ttk.Button(run, text="▶  Export", style="Accent.TButton", command=self.start_export)
        self.export_btn.pack(side="left")
        self.cancel_btn = ttk.Button(run, text="Cancel", command=self.cancel_export, state="disabled")
        self.cancel_btn.pack(side="left", padx=8)
        self.copy_latex_btn = ttk.Button(run, text="📋 Copy LaTeX", command=self.copy_latex, state="disabled")
        self.copy_latex_btn.pack(side="left")
        self.status = tk.StringVar()
        ttk.Label(run, textvariable=self.status).pack(side="right")
        self.summary = tk.StringVar()
        sumlab = ttk.Label(self.root, textvariable=self.summary, style="Hint.TLabel")
        self.bar = ttk.Progressbar(self.root, mode="determinate")
        logf = ttk.Frame(self.root)
        self.log_box = tk.Text(
            logf,
            height=10,
            state="disabled",
            bg="#f7f7f7",
            relief="flat",
            borderwidth=1,
            font=("Consolas" if sys.platform.startswith("win") else "Courier", 9),
            wrap="word",
        )
        lsb = ttk.Scrollbar(logf, command=self.log_box.yview)
        self.log_box.config(yscrollcommand=lsb.set)
        self.log_box.pack(side="left", fill="both", expand=True)
        lsb.pack(side="right", fill="y")
        logf.pack(side="bottom", fill="x", padx=12, pady=(2, 8))
        self.bar.pack(side="bottom", fill="x", padx=12, pady=2)
        run.pack(side="bottom", fill="x", padx=12, pady=4)
        sumlab.pack(side="bottom", fill="x", padx=14)
        self.nb.pack(side="top", fill="both", expand=True, padx=10, pady=(8, 4))
        for k in FORMATS + ["images"]:
            V["fmt_" + k].trace_add("write", self.update_summary)
        V["save_dir"].trace_add("write", self.update_summary)
        self.update_summary()

    def run(self):
        self.root.mainloop()


def main():
    if tk is None:
        raise SystemExit("Tkinter is not available in this Python installation.")
    _windows_integration()
    App().run()
