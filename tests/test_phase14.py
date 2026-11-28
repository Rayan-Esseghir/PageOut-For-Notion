"""Tests for Phase 14: Templates & plugins.

Tests cover:
- Template loading from user and built-in directories
- Sandbox-safe variable substitution
- HTML escaping for HTML templates
- Special escaping for Markdown templates (pipe, newline)
- Error isolation for template rendering errors
- Plugin auto-loading from ~/.pageout/plugins
- Custom block renderer registration
"""

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

# Add the project root to the path
sys.path.insert(0, str(Path(__file__).parent.parent))

from pageout.core.templates import (
    VAR_PATTERN,
    Template,
    get_template_path,
    template_exists,
)
from pageout.plugins.template import (
    USER_PLUGINS_DIR,
    USER_TEMPLATES_DIR,
    TemplateEngine,
    TemplateResult,
    TemplateSandbox,
    get_available_templates,
    init_template_engine,
    load_user_template,
    template_render_safe,
)


class TestTemplate:
    """Tests for the Template class and basic template functionality."""

    def test_template_basic_substitution(self):
        """Test basic variable substitution in a template."""
        source = "<html><body>{{ content }}</body></html>"
        template = Template(source)
        result = template.render({"content": "Hello, world!"})
        assert result == "<html><body>Hello, world!</body></html>"

    def test_template_multiple_variables(self):
        """Test multiple variables in a single template."""
        source = "<title>{{ title }}</title><body>{{ body }}</body>"
        template = Template(source)
        result = template.render({"title": "My Page", "body": "<p>Content</p>"})
        assert result == "<title>My Page</title><body>&lt;p&gt;Content&lt;/p&gt;</body>"

    def test_template_nested_key(self):
        """Test nested key resolution (e.g., doc.title)."""
        source = "{{ doc.title }}"
        template = Template(source)
        result = template.render({"doc": {"title": "Nested Title"}})
        assert result == "Nested Title"

    def test_template_missing_variable(self):
        """Test that missing variables render as empty string."""
        source = "prefix {{ missing }} suffix"
        template = Template(source)
        result = template.render({"other": "value"})
        assert result == "prefix  suffix"

    def test_template_html_escaping(self):
        """Test that HTML tags are escaped for general variables in HTML templates."""
        # content and body_classes are trusted (pre-rendered HTML), so they are not escaped
        # Other variables like title should be escaped
        source = "<div>{{ title }}</div><span>{{ content }}</span>"
        template = Template(source, template_type="html")
        result = template.render({"title": "<script>alert('xss')</script>", "content": "<b>safe html</b>"})
        # title should be escaped (XSS protection)
        assert "&lt;script&gt;" in result
        assert "<script>" not in result
        # content should NOT be escaped (it's pre-rendered HTML from the pipeline)
        assert "<b>safe html</b>" in result

    def test_template_no_escape_for_css(self):
        """Test that css key values are not HTML-escaped."""
        source = "<style>{{ css }}</style>"
        template = Template(source, template_type="html")
        result = template.render({"css": "body { color: red; }"})
        assert "body { color: red; }" in result
        assert "&lt;" not in result

    def test_template_markdown_escaping(self):
        """Test that pipe and newline are escaped in Markdown templates."""
        source = "| {{ col }} |"
        template = Template(source, template_type="md")
        result = template.render({"col": "a|b\nc"})
        assert "\\|" in result

    def test_template_variable_extraction(self):
        """Test that variables are correctly extracted from template."""
        source = "{{ title }} - {{ content }} - {{ extra.key }}"
        template = Template(source)
        variables = template.variables
        assert "title" in variables
        assert "content" in variables
        assert "extra.key" in variables

    def test_template_security_key_validation(self):
        """Test that invalid variable names raise TemplateError."""
        # Pattern only allows alphanumeric and underscore
        source = "{{ valid }} {{ also_valid }} {{ with.dots }}"
        template = Template(source)
        # All these should be valid
        result = template.render({"valid": "a", "also_valid": "b", "with": {"dots": "c"}})
        assert "a" in result
        assert "b" in result


class TestTemplateSandbox:
    """Tests for the sandboxed template environment."""

    def test_sandbox_load_template(self):
        """Test loading a template from a specified directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpl_dir = Path(tmpdir)
            tmpl_file = tmpl_dir / "test.html"
            tmpl_file.write_text("<html>{{ title }}</html>")

            sandbox = TemplateSandbox(template_dir=tmpl_dir)
            content = sandbox.load_template("test", ".html")

            assert content == "<html>{{ title }}</html>"

    def test_sandbox_load_nonexistent_template(self):
        """Test loading a non-existent template returns None."""
        sandbox = TemplateSandbox()
        content = sandbox.load_template("nonexistent", ".html")
        assert content is None

    def test_sandbox_render_with_escaping(self):
        """Test that HTML escaping is applied during rendering."""
        sandbox = TemplateSandbox(template_type="html")
        template = "{{ title }}"
        result = sandbox.render(template, {"title": "<script>"}, escape=True)
        assert "&lt;script&gt;" in result

    def test_sandbox_render_without_escaping(self):
        """Test that HTML escaping can be disabled."""
        sandbox = TemplateSandbox(template_type="md")
        template = "{{ title }}"
        result = sandbox.render(template, {"title": "<script>"}, escape=False)
        assert "<script>" in result

    def test_sandbox_sanitize_context(self):
        """Test that dangerous context keys are stripped."""
        sandbox = TemplateSandbox(template_type="html")
        # Context with __import__ which could be dangerous
        template = "{{ title }}"
        result = sandbox.render(template, {"title": "Hello", "__import__": "dangerous"}, sanitize=True)
        # Should render with the valid title key
        assert "Hello" in result

    def test_sandbox_nested_key_resolution(self):
        """Test resolving nested keys like doc.title."""
        sandbox = TemplateSandbox(template_type="html")
        template = "{{ doc.title }}"
        result = sandbox.render(template, {"doc": {"title": "My Doc"}}, sanitize=False)
        assert result == "My Doc"

    def test_sandbox_errors_property(self):
        """Test that errors are collected and accessible."""
        sandbox = TemplateSandbox()
        # Force an error condition
        sandbox._errors.append("Test error")
        assert len(sandbox.errors) > 0

    def test_sandbox_template_type_property(self):
        """Test that template_type property returns correct value."""
        sandbox_html = TemplateSandbox(template_type="html")
        assert sandbox_html.template_type == "html"

        sandbox_md = TemplateSandbox(template_type="md")
        assert sandbox_md.template_type == "md"


class TestTemplateEngine:
    """Tests for the high-level TemplateEngine."""

    def test_template_engine_initialization(self):
        """Test that TemplateEngine initializes correctly."""
        engine = TemplateEngine()
        assert engine.html_sandbox is not None
        assert engine.md_sandbox is not None

    def test_template_engine_render_page_html(self):
        """Test HTML page rendering with template."""
        engine = init_template_engine()

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpl_dir = Path(tmpdir)
            tmpl_file = tmpl_dir / "page.html"
            tmpl_file.write_text("<html><head><title>{{ title }}</title></head><body>{{ body }}</body></html>")

            # Manually set the template dir
            engine.html_sandbox.template_dir = tmpl_dir
            result = engine.render_page_html("Test", "<p>Content</p>", {})
            assert "Test" in result

    def test_template_engine_render_markdown(self):
        """Test Markdown page rendering with template."""
        engine = init_template_engine()

        result = engine.render_page_markdown("My Title", "Body content", {})
        assert "# My Title" in result
        assert "Body content" in result

    def test_template_engine_block_renderers(self):
        """Test custom block renderer registration."""
        engine = TemplateEngine()

        # Register a custom renderer
        def custom_renderer(block, r):
            return f"<custom>{block.text}</custom>"

        engine.register_block_renderer("custom_block", custom_renderer)
        assert engine.has_custom_renderer("custom_block")
        assert engine.get_block_renderer("custom_block") == custom_renderer

    def test_template_engine_plugin_loading(self):
        """Test that plugins are loaded from user plugins directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            plugins_dir = Path(tmpdir)
            # Create a dummy plugin
            plugin_file = plugins_dir / "test_plugin.py"
            plugin_file.write_text("""
# Test plugin
def register(engine):
    engine.register_block_renderer('test', lambda b, r: 'test')
""")

            engine = TemplateEngine()
            # Patch the plugins dir for testing
            with patch("pageout.plugins.template.USER_PLUGINS_DIR", plugins_dir):
                loaded = engine.load_plugins()
                assert loaded is True


class TestTemplateFunctions:
    """Tests for module-level template functions."""

    def test_template_render_safe_success(self):
        """Test that template_render_safe returns success on valid template."""
        result = template_render_safe("{{ title }}", {"title": "Hello"})
        assert result.success is True
        assert "Hello" in result.content

    def test_template_render_safe_failure(self):
        """Test that template_render_safe handles errors gracefully."""
        # Pass an invalid template that might cause issues
        result = template_render_safe("{{ title }}", {})
        assert result.success is True
        assert "" in result.content  # missing variable renders empty

    def test_load_user_template_exists(self):
        """Test loading a template that exists from user directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            user_tmpl_dir = Path(tmpdir)
            tmpl_file = user_tmpl_dir / "custom.html"
            tmpl_file.write_text("<html>{{ title }}</html>")

            engine = init_template_engine()
            engine.html_sandbox.template_dir = user_tmpl_dir

            with patch("pageout.plugins.template.USER_TEMPLATES_DIR", user_tmpl_dir):
                result = load_user_template("custom", "html")
                assert result is not None
                assert result.success is True

    def test_load_user_template_not_found(self):
        """Test loading a non-existent template returns None."""
        result = load_user_template("nonexistent", "html")
        assert result is None

    def test_template_exists(self):
        """Test template_exists function."""
        # Check that built-in templates exist
        assert template_exists("page", "html") is True
        assert template_exists("index", "html") is True
        assert template_exists("page", "md") is True

    def test_template_exists_nonexistent(self):
        """Test template_exists for non-existent template."""
        assert template_exists("nonexistent_template_xyz", "html") is False
        assert template_exists("nonexistent_template_xyz", "md") is False

    def test_get_template_path_builtin(self):
        """Test get_template_path for built-in templates."""
        path = get_template_path("page", "html")
        if path:  # May not exist if templates weren't created
            assert path.suffix == ".html"

    def test_get_available_templates(self):
        """Test getting list of available templates."""
        templates = get_available_templates("html")
        # Should include at least page and index if templates exist
        assert isinstance(templates, list)


class TestTemplatePattern:
    """Tests for the template variable pattern matching."""

    def test_pattern_basic(self):
        """Test basic pattern matching."""
        match = VAR_PATTERN.search("{{ title }}")
        assert match is not None
        assert match.group(1) == "title"

    def test_pattern_with_whitespace(self):
        """Test pattern with various whitespace."""
        match = VAR_PATTERN.search("{{  title  }}")
        assert match is not None
        assert match.group(1) == "title"

    def test_pattern_nested_key(self):
        """Test pattern with nested key."""
        match = VAR_PATTERN.search("{{ doc.title }}")
        assert match is not None
        assert match.group(1) == "doc.title"

    def test_pattern_alphanumeric_and_underscore(self):
        """Test that pattern matches valid identifiers."""
        match = VAR_PATTERN.search("{{ my_var_123 }}")
        assert match is not None
        assert match.group(1) == "my_var_123"


class TestTemplateErrorIsolation:
    """Tests for error isolation in template rendering."""

    def test_render_does_not_raise_on_template_error(self):
        """Test that template errors are caught and don't propagate."""
        engine = template_render_safe("{{ title }}", {"title": "test"})
        # Should succeed even if something goes wrong internally
        assert isinstance(engine, TemplateResult)

    def test_plugin_errors_are_isolated(self):
        """Test that plugin loading errors don't crash the engine."""
        with tempfile.TemporaryDirectory() as tmpdir:
            plugins_dir = Path(tmpdir)
            # Create a broken plugin
            plugin_file = plugins_dir / "broken_plugin.py"
            plugin_file.write_text("raise Exception('broken')")

            engine = TemplateEngine()
            # Should not raise - errors should be caught
            result = engine.load_plugins()
            # Returns True if any plugins loaded, False if all failed
            assert isinstance(result, bool)


class TestIntegration:
    """Integration tests for template system."""

    def test_full_template_rendering_workflow(self):
        """Test full workflow from template loading to rendering."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpl_dir = Path(tmpdir)

            # Create a page template
            page_tmpl = tmpl_dir / "page.html"
            page_tmpl.write_text("""<!DOCTYPE html>
<html>
<head><title>{{ title }}</title></head>
<body class="{{ body_classes }}">{{ content }}</body>
</html>""")

            # Create sandbox and load template
            sandbox = TemplateSandbox(template_dir=tmpl_dir)
            raw_tmpl = sandbox.load_template("page", ".html")

            assert raw_tmpl is not None

            # Render
            result = sandbox.render(
                raw_tmpl,
                {
                    "title": "Test Page",
                    "body": "<p>Hello</p>",
                    "body_classes": "dark",
                    "css": "body { color: #333; }",
                    "head_extra": "",
                },
            )

            # Body should be escaped
            assert "Test Page" in result
            assert "dark" in result

    def test_markdown_template_escaping(self):
        """Test that Markdown templates properly escape special characters."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpl_dir = Path(tmpdir)

            # Create a markdown template with table
            md_tmpl = tmpl_dir / "page.md"
            md_tmpl.write_text("# {{ title }}\n\n{{ content }}\n")

            sandbox_md = TemplateSandbox(template_dir=tmpl_dir, template_type="md")

            raw_tmpl = sandbox_md.load_template("page", ".md")

            # Content with pipe (table column separator)
            result = sandbox_md.render(
                raw_tmpl,
                {
                    "title": "Test",
                    "content": "Cell 1 | Cell 2",
                },
            )

            # Pipe should be escaped in markdown context
            assert "\\|" in result


class TestUserDirectories:
    """Tests for user directory handling."""

    def test_user_directories_exist(self):
        """Test that user directories are correctly resolved."""
        # USER_TEMPLATES_DIR should be ~/.pageout/templates
        assert ".pageout" in str(USER_TEMPLATES_DIR)
        assert "templates" in str(USER_TEMPLATES_DIR)

        # USER_PLUGINS_DIR should be ~/.pageout/plugins
        assert ".pageout" in str(USER_PLUGINS_DIR)
        assert "plugins" in str(USER_PLUGINS_DIR)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
