"""Template rendering plugin system with sandboxed template loading.

This module provides:
1. Safe template loading from user directories (~/.pageout/templates/)
2. Sandboxed variable substitution
3. Error isolation for template rendering errors
"""

from __future__ import annotations

import html
import importlib.util
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

# Template directories
USER_TEMPLATES_DIR = Path.home() / ".pageout" / "templates"
USER_PLUGINS_DIR = Path.home() / ".pageout" / "plugins"


class TemplateLoadError(Exception):
    """Raised when a template cannot be loaded."""

    pass


class TemplateRenderError(Exception):
    """Raised when template rendering fails."""

    pass


@dataclass
class TemplateResult:
    """Result of template rendering with error information."""

    content: str
    success: bool
    error: Optional[str] = None
    loaded_from: Optional[str] = None


class TemplateSandbox:
    """Sandboxed template environment with safe variable substitution."""

    # Default safe context
    SAFE_KEYS = {
        "title",
        "content",
        "body",
        "css",
        "head_extra",
        "body_classes",
        "date",
        "date_fmt",
        "item",
        "items",
        "index",
        "total",
        "props",
        "properties",
        "rows",
        "headers",
        "links",
        "toc",
        "bookmarks",
        "frontmatter",
    }

    def __init__(self, template_dir: Optional[Path] = None, template_type: str = "html"):
        """Initialize the sandbox with optional custom template directory and template type."""
        self.template_dir = template_dir or USER_TEMPLATES_DIR
        self._template_type = template_type
        self._template_cache: Dict[str, str] = {}
        self._errors: List[str] = []

    def load_template(self, name: str, ext: str = ".html") -> Optional[str]:
        """
        Load a template from the user templates directory.

        Returns None if template doesn't exist or cannot be loaded.
        """
        path = self.template_dir / f"{name}{ext}"

        if not path.exists():
            return None

        try:
            # Security: check file is within expected directory
            if not path.resolve().is_relative_to(self.template_dir.resolve()):
                self._errors.append(f"Template {name} is outside allowed directory")
                return None

            content = path.read_text(encoding="utf-8")
            self._template_cache[name] = content
            self._errors.clear()
            return content
        except Exception as e:
            self._errors.append(f"Failed to load template {name}: {e}")
            return None

    def render(self, template: str, context: Dict[str, Any], escape: bool = True, sanitize: bool = True) -> str:
        """
        Render a template string with the given context.

        Args:
            template: The template string with {{ variable }} placeholders
            context: Dictionary mapping variable names to values
            escape: Whether to HTML-escape values (default True for HTML templates)
            sanitize: Whether to sanitize context keys (strip dangerous ones)

        Returns:
            Rendered template string

        Raises:
            TemplateRenderError: If rendering fails
        """
        if sanitize:
            # Filter context to only safe keys and keys used in template
            filtered = {}
            for k, v in context.items():
                # Allow safe keys, or keys that start with underscore (internal)
                if k in self.SAFE_KEYS or k.startswith("_"):
                    filtered[k] = v
                elif re.match(r"^[a-zA-Z_][a-zA-Z0-9_\.]*$", k):
                    # Allow valid identifier keys (for nested access like doc.title)
                    # but strip potentially dangerous keys like __import__
                    filtered[k] = v
            context = filtered

        try:
            result = template

            # Find and replace all {{ variable }} patterns
            pattern = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_\.]*)\s*\}\}")

            for match in pattern.finditer(template):
                key = match.group(1)

                # Resolve potentially nested keys (e.g., doc.title)
                parts = key.split(".")
                value = context
                for part in parts:
                    if isinstance(value, dict):
                        value = value.get(part)
                    elif hasattr(value, part):
                        value = getattr(value, part)
                    else:
                        value = ""
                    if value is None:
                        value = ""
                        break

                # Convert to string
                str_value = str(value) if value is not None else ""

                # Apply escaping based on template type
                if escape:
                    if self.template_type == "html":
                        str_value = html.escape(str_value, quote=True)
                    else:
                        # Markdown: escape pipe characters and newlines for table safety
                        str_value = str_value.replace("|", "\\|").replace("\n", " ")

                result = result.replace(match.group(0), str_value)

            return result

        except Exception as e:
            raise TemplateRenderError(f"Template rendering failed: {e}") from e

    @property
    def errors(self) -> List[str]:
        """Return list of template errors."""
        return self._errors.copy()

    @property
    def template_type(self) -> str:
        """The type of templates this sandbox handles."""
        return self._template_type


class TemplateEngine:
    """High-level template engine with plugin support."""

    def __init__(self):
        self.html_sandbox = TemplateSandbox(template_type="html")
        self.md_sandbox = TemplateSandbox(template_type="md")
        self._plugin_modules: Dict[str, Any] = {}
        self._block_renderers: Dict[str, Callable] = {}

    def load_plugins(self) -> bool:
        """
        Load plugins from user plugins directory.

        Returns True if any plugins were loaded successfully.
        """
        if not USER_PLUGINS_DIR.exists():
            return False

        loaded = False
        for py_file in USER_PLUGINS_DIR.glob("*.py"):
            try:
                # Security check
                if not py_file.resolve().is_relative_to(USER_PLUGINS_DIR.resolve()):
                    continue

                spec = importlib.util.spec_from_file_location(f"pageout_plugin_{py_file.stem}", str(py_file))
                if spec and spec.loader:
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                    self._plugin_modules[py_file.stem] = mod
                    loaded = True
            except Exception as e:
                # Error isolation: don't let plugin errors crash the app
                print(f"Warning: Failed to load plugin {py_file.name}: {e}")

        return loaded

    def register_block_renderer(self, block_kind: str, renderer: Callable):
        """Register a custom block renderer."""
        self._block_renderers[block_kind] = renderer

    def get_block_renderer(self, block_kind: str) -> Optional[Callable]:
        """Get a custom block renderer for a block kind."""
        return self._block_renderers.get(block_kind)

    def has_custom_renderer(self, block_kind: str) -> bool:
        """Check if a custom block renderer is registered."""
        return block_kind in self._block_renderers

    def render_page_html(self, title: str, body: str, cfg: Dict[str, Any]) -> str:
        """Render an HTML page using the configured template."""
        # Build header
        from pageout.renderers.html import (
            KATEX_HEAD,
            MATH_ENGINES,
            _build_html_css,
            _katex_bundle,
            _web_font_links,
            esc,
        )

        css = _build_html_css(cfg) + (cfg.get("custom_css") or "")
        body_classes = []
        if cfg.get("maximize_images"):
            body_classes.append("maximize-images")
        if cfg.get("one_image_per_page"):
            body_classes.append("one-image-per-page")
        cls_attr = f' class="{" ".join(body_classes)}"' if body_classes else ""

        head_extra = _web_font_links(cfg)
        if cfg.get("render_math", True) and 'class="eq"' in body:
            engine = cfg.get("math_engine", MATH_ENGINES[0])
            if engine == MATH_ENGINES[0]:
                head_extra += _katex_bundle() or KATEX_HEAD
            elif engine == MATH_ENGINES[1]:
                head_extra += KATEX_HEAD

        context = {
            "title": title,
            "body": body,
            "css": css,
            "head_extra": head_extra,
            "body_classes": cls_attr,
        }

        # Try custom template first
        template_name = cfg.get("template", "page")
        ext = ".html"

        tmpl = self.html_sandbox.load_template(template_name, ext)
        if tmpl:
            try:
                return self.html_sandbox.render(tmpl, context)
            except TemplateRenderError as e:
                print(f"Warning: Template rendering error: {e}")

        # Fall back to default inline template
        return (
            f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">'
            f"<title>{esc(title)}</title>{head_extra}<style>{css}</style></head>"
            f"<body{cls_attr}>{body}</body></html>"
        )

    def render_index_html(self, title: str, body: str, cfg: Dict[str, Any]) -> str:
        """Render an index HTML page using the configured template."""
        from pageout.renderers.html import _build_html_css, _web_font_links, esc

        css = _build_html_css(cfg) + (cfg.get("custom_css") or "")
        head_extra = _web_font_links(cfg)

        context = {
            "title": title,
            "content": body,
            "css": css,
            "head_extra": head_extra,
        }

        # Try custom index template
        template_name = cfg.get("index_template", "index")
        ext = ".html"

        tmpl = self.html_sandbox.load_template(template_name, ext)
        if tmpl:
            try:
                return self.html_sandbox.render(tmpl, context)
            except TemplateRenderError as e:
                print(f"Warning: Index template rendering error: {e}")

        # Fall back to default
        return (
            f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">'
            f"<title>{esc(title)}</title>{head_extra}<style>{css}</style></head>"
            f'<body><h1 class="notion-title">{esc(title)}</h1>{body}</body></html>'
        )

    def render_page_markdown(self, title: str, body: str, cfg: Dict[str, Any], frontmatter: str = "") -> str:
        """Render a Markdown page using the configured template."""
        context = {
            "title": title,
            "content": body,
            "frontmatter": frontmatter,
        }

        # Try custom template
        template_name = cfg.get("template", "page")
        ext = ".md"

        tmpl = self.md_sandbox.load_template(template_name, ext)
        if tmpl:
            try:
                return self.md_sandbox.render(tmpl, context, escape=False)
            except TemplateRenderError as e:
                print(f"Warning: Markdown template rendering error: {e}")

        # Fall back to default structure
        result = f"# {title}\n"
        if frontmatter:
            result += f"\n{frontmatter}\n"
        result += f"\n{body}"
        return result + "\n"

    def render_index_markdown(self, title: str, body: str, cfg: Dict[str, Any]) -> str:
        """Render an index Markdown page using the configured template."""
        context = {
            "title": title,
            "content": body,
            "frontmatter": "",
        }

        # Try custom index template
        template_name = cfg.get("index_template", "index")
        ext = ".md"

        tmpl = self.md_sandbox.load_template(template_name, ext)
        if tmpl:
            try:
                return self.md_sandbox.render(tmpl, context, escape=False)
            except TemplateRenderError as e:
                print(f"Warning: Index markdown template rendering error: {e}")

        # Fall back to default
        return f"# {title}\n\n{body}"


# Global template engine instance
_template_engine: Optional[TemplateEngine] = None


def get_template_engine() -> TemplateEngine:
    """Get or create the global template engine instance."""
    global _template_engine
    if _template_engine is None:
        _template_engine = TemplateEngine()
        _template_engine.load_plugins()
    return _template_engine


def init_template_engine() -> TemplateEngine:
    """Initialize a fresh template engine (for testing)."""
    global _template_engine
    _template_engine = TemplateEngine()
    return _template_engine


def template_render_safe(template: str, context: Dict[str, Any], template_type: str = "html") -> TemplateResult:
    """
    Safely render a template with error isolation.

    Always returns a TemplateResult, never raises exceptions.
    """
    try:
        engine = get_template_engine()

        if template_type == "html":
            sandbox = engine.html_sandbox
        else:
            sandbox = engine.md_sandbox

        content = sandbox.render(template, context, escape=True)
        return TemplateResult(content=content, success=True, loaded_from="inline")

    except Exception as e:
        return TemplateResult(content="", success=False, error=str(e), loaded_from=None)


def load_user_template(name: str, template_type: str = "html") -> Optional[TemplateResult]:
    """Load a template from user templates directory."""
    engine = get_template_engine()

    if template_type == "html":
        path = USER_TEMPLATES_DIR / f"{name}.html"
        tmpl_str = engine.html_sandbox.load_template(name, ".html")
    else:
        path = USER_TEMPLATES_DIR / f"{name}.md"
        tmpl_str = engine.md_sandbox.load_template(name, ".md")

    if tmpl_str is None:
        return None

    return TemplateResult(content=tmpl_str, success=True, loaded_from=str(path))


def get_available_templates(template_type: str = "html") -> List[str]:
    """Get list of available template names."""
    templates = []
    ext = ".html" if template_type == "html" else ".md"

    if USER_TEMPLATES_DIR.exists():
        for p in USER_TEMPLATES_DIR.glob(f"*{ext}"):
            templates.append(p.stem)

    # Include built-in templates
    from pageout.core.templates import TEMPLATES_DIR

    if TEMPLATES_DIR.exists():
        for p in TEMPLATES_DIR.glob(f"*{ext}"):
            if p.stem not in templates:
                templates.append(p.stem)

    return templates
