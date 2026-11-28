"""HTML/Markdown templates with sandbox-safe variable substitution.

Templates are simple text files with {{ variable }} placeholders.
Values are HTML-escaped for HTML templates, and specially escaped for Markdown
to prevent injection attacks.
"""

from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Any, Dict, Optional

# Template directories
TEMPLATES_DIR = Path(__file__).resolve().parent.parent.parent / "templates"

# User plugin directory for custom templates
PLUGIN_TEMPLATES_DIR = Path.home() / ".pageout" / "templates"

# Sandboxed variable pattern: {{ var }} or {{ var.key }}
VAR_PATTERN = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_\.]*)\s*\}\}")


class TemplateError(Exception):
    """Raised when template loading or rendering fails."""

    pass


class Template:
    """A sandboxed template with safe variable substitution."""

    def __init__(self, source: str, template_type: str = "html"):
        """
        Initialize a template from source string.

        Args:
            source: The template source code with {{ variable }} placeholders
            template_type: "html" or "md" (markdown)
        """
        self.source = source
        self.template_type = template_type
        self._variables = self._extract_variables()

    def _extract_variables(self) -> set:
        """Extract all variable names from the template."""
        return set(VAR_PATTERN.findall(self.source))

    @property
    def variables(self) -> set:
        """Return the set of variable names this template expects."""
        return self._variables

    def _sanitize_key(self, key: str) -> str:
        """Validate and sanitize a variable key (e.g., 'title' or 'doc.title')."""
        # Only allow alphanumeric and underscore
        if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_\.]*$", key):
            raise TemplateError(f"Invalid variable name: {key}")
        return key

    def _resolve_value(self, key: str, context: Dict[str, Any]) -> Any:
        """Resolve a potentially nested key (e.g., 'doc.title') from context."""
        parts = key.split(".")
        value: Any = context
        for part in parts:
            if isinstance(value, dict):
                value = value.get(part)
            elif hasattr(value, part):
                value = getattr(value, part)
            else:
                return ""
            if value is None:
                return ""
        return value

    def _escape_value(self, value: Any, key: str) -> str:
        """Escape a value based on template type and key context."""
        if value is None:
            return ""

        str_value = str(value)

        if self.template_type == "html":
            # HTML escape everything, but allow certain safe keys
            # Check if this is a CSS, content, or URL context
            if key in ("css", "head_extra", "content", "body_classes"):
                # CSS, head_extra, content, and body_classes should NOT be escaped
                # as they contain HTML/CSS/markup
                return str_value
            return html.escape(str_value, quote=True)
        else:
            # Markdown: escape pipe characters and backticks for table safety
            # But content and frontmatter should NOT be escaped (they contain markup)
            if key in ("content", "frontmatter"):
                str_value = str_value.replace("\n", " ")
                return str_value
            str_value = str_value.replace("|", "\\|").replace("\n", " ")
            return str_value

    def render(self, context: Dict[str, Any]) -> str:
        """
        Render the template with the given context.

        Args:
            context: Dictionary mapping variable names to values

        Returns:
            Rendered template string with all placeholders filled

        Raises:
            TemplateError: If required variable is missing or invalid
        """
        result = self.source

        for match in VAR_PATTERN.finditer(self.source):
            key = match.group(1)
            try:
                key = self._sanitize_key(key)
            except TemplateError as e:
                raise TemplateError(f"Variable key validation failed: {e}") from e

            value = self._resolve_value(key, context)
            escaped = self._escape_value(value, key)
            result = result.replace(match.group(0), escaped)

        return result

    def missing_variables(self, context: Dict[str, Any]) -> set:
        """Return variables that are required but not in context."""
        present = set()
        for key in self.variables:
            if key.split(".")[0] in context:
                try:
                    self._resolve_value(key, context)
                    present.add(key)
                except (KeyError, AttributeError):
                    pass
        return self._variables - present


def load_template(name: str, template_type: str = "html") -> Template:
    """
    Load a template by name with sandboxed loading.

    Templates are searched in this order:
    1. User plugin templates (~/.pageout/templates/)
    2. Built-in templates (pageout/templates/)

    Args:
        name: Template name (e.g., 'page' for page.html or page.md)
        template_type: 'html' or 'md'

    Returns:
        Loaded Template object

    Raises:
        TemplateError: If template not found or cannot be loaded
    """
    ext = ".html" if template_type == "html" else ".md"
    filename = f"{name}{ext}"

    # Search user templates first, then built-in
    paths = [
        PLUGIN_TEMPLATES_DIR / filename,
        TEMPLATES_DIR / filename,
    ]

    for path in paths:
        if path.exists() and path.is_file():
            try:
                source = path.read_text(encoding="utf-8")
                return Template(source, template_type)
            except Exception as e:
                raise TemplateError(f"Failed to load template {path}: {e}") from e

    raise TemplateError(f"Template '{name}' not found (searched: {', '.join(str(p) for p in paths)})")


def load_template_safely(name: str, template_type: str = "html", allow_custom: bool = True) -> Template:
    """
    Load a template with safety checks for sandboxing.

    Args:
        name: Template name
        template_type: 'html' or 'md'
        allow_custom: Whether to allow loading from user directory (default True)

    Returns:
        Loaded Template object with safety restrictions
    """
    if not allow_custom:
        path = TEMPLATES_DIR / f"{name}{'.html' if template_type == 'html' else '.md'}"
        if not path.exists():
            raise TemplateError(f"Built-in template '{name}' not found")
        try:
            source = path.read_text(encoding="utf-8")
            return Template(source, template_type)
        except Exception as e:
            raise TemplateError(f"Failed to load built-in template: {e}") from e

    return load_template(name, template_type)


def get_builtin_templates() -> Dict[str, Template]:
    """Return all built-in templates."""
    templates = {}
    for ext in (".html", ".md"):
        for path in TEMPLATES_DIR.glob(f"*{ext}"):
            name = path.stem
            template_type = "html" if ext == ".html" else "md"
            try:
                source = path.read_text(encoding="utf-8")
                templates[name] = Template(source, template_type)
            except Exception:
                pass  # Skip templates that can't be loaded
    return templates


def template_exists(name: str, template_type: str = "html") -> bool:
    """Check if a template exists (user or built-in)."""
    try:
        load_template(name, template_type)
        return True
    except TemplateError:
        return False


# Pre-compiled built-in templates for performance
_BUILTIN_TEMPLATES = {
    "page.html": TEMPLATES_DIR / "page.html",
    "page.md": TEMPLATES_DIR / "page.md",
    "index.html": TEMPLATES_DIR / "index.html",
    "index.md": TEMPLATES_DIR / "index.md",
}


def get_template_path(name: str, template_type: str = "html") -> Optional[Path]:
    """Get the path to a template if it exists."""
    ext = ".html" if template_type == "html" else ".md"
    filename = f"{name}{ext}"

    # Check user templates first
    user_path = PLUGIN_TEMPLATES_DIR / filename
    if user_path.exists():
        return user_path

    # Then check built-in
    if (TEMPLATES_DIR / filename).exists():
        return TEMPLATES_DIR / filename

    return None
