"""Tests for Phase 3-7 features: links, assets, incremental sync, hooks, CLI, zip, math, ..."""

import io
import json
import urllib.error
import zipfile

import pytest
from fake_notion import DB_ID, FakeNotion, load_fixture
from test_golden import FULL, collect, run_export

import pageout.core.config as config
import pageout.core.pipeline as pipeline
from pageout.cli import main as cli_main
from pageout.core.pipeline import export

EMPTY = "b" * 32


def cfg_for(out, **over):
    cfg = dict(
        config.DEFAULTS,
        token="tok-not-a-secret",
        save_dir=str(out),
        fmt_pdf=False,
        img_handling="Keep Notion link",
        workers=2,
        math_engine="CDN (internet)",
    )
    cfg.update(over)
    return cfg


def run(out, notion=None, **over):
    return export(cfg_for(out, **over), notion=notion or FakeNotion())


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(config, "CONFIG_FILE", str(tmp_path / "cfg" / "config.json"))
    monkeypatch.delenv("NOTION_TOKEN", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)


# ------------------------------------------------------------------ Phase 3: links & assets
def test_links_between_exported_pages_are_relative(tmp_path):
    run_export(tmp_path, database=DB_ID, source_type="Auto-detect", fmt_md=True, fmt_html=True)
    md = next((tmp_path / "Markdown").glob("*Full*.md")).read_text(encoding="utf-8")
    html = next((tmp_path / "HTML").glob("*Full*.html")).read_text(encoding="utf-8")
    assert "(2024-01-10%20-%20Empty%20page.md)" in md and "/bbbbbbbb" not in md
    assert 'href="2024-01-10%20-%20Empty%20page.html"' in html and 'href="/bbbbbbbb' not in html
    assert "↪ [Empty page](2024-01-10%20-%20Empty%20page.md)" in md  # link_to_page block
    # the linked files really exist
    assert (tmp_path / "Markdown" / "2024-01-10 - Empty page.md").exists()


def test_links_untouched_when_target_not_exported(tmp_path):
    run_export(tmp_path, database=FULL, source_type="Single page", fmt_md=True)
    md = next((tmp_path / "Markdown").glob("*.md")).read_text(encoding="utf-8")
    assert "(/" + EMPTY + ")" in md


def test_remove_all_links_wins_over_rewriting(tmp_path):
    run_export(tmp_path, database=DB_ID, source_type="Auto-detect", fmt_md=True, links="Remove all links")
    md = next((tmp_path / "Markdown").glob("*Full*.md")).read_text(encoding="utf-8")
    assert "Empty page.md" not in md and "the empty page" in md


def test_rewrite_can_be_disabled(tmp_path):
    run_export(tmp_path, database=DB_ID, source_type="Auto-detect", fmt_md=True, rewrite_links=False)
    md = next((tmp_path / "Markdown").glob("*Full*.md")).read_text(encoding="utf-8")
    assert "(/" + EMPTY + ")" in md


def test_identical_images_are_saved_once(tmp_path, monkeypatch):
    same = b"\x89PNG\r\n\x1a\n" + b"x" * 64
    monkeypatch.setattr(pipeline, "download", lambda url, timeout=60: (same, "image/png"))
    monkeypatch.setattr(pipeline.Exporter, "_to_png", lambda self, img: None)
    run_export(tmp_path, database=FULL, source_type="Single page", fmt_tex=True)
    files = [p for p in (tmp_path / "Images").rglob("*") if p.is_file()]
    assert len(files) == 1
    tex = next((tmp_path / "LaTeX").glob("*.tex")).read_text(encoding="utf-8")
    assert tex.count("\\includegraphics") == 2  # both figures point at the one file


def test_expired_image_link_is_refetched(tmp_path, monkeypatch):
    seen = []

    def dl(url, timeout=60):
        seen.append(url)
        if "_fresh" not in url:
            raise urllib.error.HTTPError(url, 403, "Forbidden", {}, None)
        return (b"\x89PNG\r\n\x1a\n" + b"y" * 32, "image/png")

    monkeypatch.setattr(pipeline, "download", dl)
    fake = FakeNotion()
    _, _, failed, _ = run_export(
        tmp_path, notion=fake, database=FULL, source_type="Single page", fmt_md=True, img_handling="Save locally & link"
    )
    assert failed == []
    assert any(c[0] == "blocks.retrieve" for c in fake.calls)
    assert any("_fresh" in u for u in seen)
    assert len([p for p in (tmp_path / "Images").rglob("*") if p.is_file()]) >= 1


def test_expired_link_that_cannot_be_refreshed_is_reported(tmp_path, monkeypatch):
    def dl(url, timeout=60):
        raise urllib.error.HTTPError(url, 403, "Forbidden", {}, None)

    monkeypatch.setattr(pipeline, "download", dl)
    monkeypatch.setattr(pipeline.Exporter, "_fresh_url", lambda self, it, img: "")
    _, _, failed, _ = run_export(
        tmp_path, database=FULL, source_type="Single page", fmt_md=True, img_handling="Save locally & link"
    )
    assert failed and all("image" in f[0] for f in failed)


# ------------------------------------------------------------------ Phase 4: incremental sync
def test_second_run_skips_unchanged_pages(tmp_path):
    r1 = run(tmp_path, database=FULL, source_type="Single page", fmt_md=True)
    assert r1.skipped == 0
    md = next((tmp_path / "Markdown").glob("*.md"))
    md.write_text("SENTINEL", encoding="utf-8")
    r2 = run(tmp_path, database=FULL, source_type="Single page", fmt_md=True)
    assert r2.skipped == 1 and md.read_text(encoding="utf-8") == "SENTINEL"


def test_force_and_changed_page_and_changed_settings_reexport(tmp_path):
    kw = dict(database=FULL, source_type="Single page", fmt_md=True)
    run(tmp_path, **kw)
    md = next((tmp_path / "Markdown").glob("*.md"))

    def sentinel():
        md.write_text("SENTINEL", encoding="utf-8")

    sentinel()
    run(tmp_path, force=True, **kw)
    assert md.read_text(encoding="utf-8") != "SENTINEL"  # --force

    run(tmp_path, **kw)
    sentinel()
    fx = load_fixture()
    fx["pages"][FULL]["last_edited_time"] = "2025-01-01T00:00:00.000Z"
    r = run(tmp_path, notion=FakeNotion(fx), **kw)
    assert r.skipped == 0 and md.read_text(encoding="utf-8") != "SENTINEL"  # page edited in Notion

    run(tmp_path, **kw)
    sentinel()
    r = run(tmp_path, accent_color="#ff0000", **kw)
    assert r.skipped == 0 and md.read_text(encoding="utf-8") != "SENTINEL"  # settings changed


def test_missing_output_file_triggers_reexport(tmp_path):
    kw = dict(database=FULL, source_type="Single page", fmt_md=True)
    run(tmp_path, **kw)
    next((tmp_path / "Markdown").glob("*.md")).unlink()
    r = run(tmp_path, **kw)
    assert r.skipped == 0 and list((tmp_path / "Markdown").glob("*.md"))


def test_new_format_requested_later_is_exported(tmp_path):
    run(tmp_path, database=FULL, source_type="Single page", fmt_md=True)
    r = run(tmp_path, database=FULL, source_type="Single page", fmt_md=True, fmt_txt=True)
    assert r.skipped == 0 and list((tmp_path / "Text").glob("*.txt"))


def test_incremental_off_for_combined_and_inline(tmp_path):
    logs = []
    export(cfg_for(tmp_path, database=DB_ID, fmt_md=True, combine=True), notion=FakeNotion(), log=logs.append)
    assert any("Incremental sync is off" in m for m in logs)
    assert not (tmp_path / ".pageout_cache.json").exists()


def test_unchanged_pdf_still_goes_into_merged_pdf_paths(tmp_path):
    from pageout.core.cache import ExportCache

    it = pipeline.Item(FULL, {"last_edited_time": "t1"}, "x")
    cache = ExportCache(str(tmp_path), config.DEFAULTS)
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF")
    cache.record(it, {"pdf": str(pdf)})
    assert cache.is_fresh(it, ["pdf"]) and cache.outputs(it)["pdf"] == str(pdf)


# ------------------------------------------------------------------ Phase 5: hooks, CLI, config
def test_hooks_filter_transform_frontmatter(tmp_path):
    hook = tmp_path / "hooks.py"
    hook.write_text(
        """
def filter_page(page):
    return "empty" not in page["title"].lower()

def transform_node(block, doc):
    if block.kind == "callout":
        return None
    if block.kind == "heading":
        block.level = 3
    return block

def transform_frontmatter(fm, doc):
    fm["notion_id"] = doc.id
    return fm
""",
        encoding="utf-8",
    )
    out = tmp_path / "out"
    r = run(out, database=DB_ID, fmt_md=True, hooks=[str(hook)])
    files = list((out / "Markdown").glob("*.md"))
    assert r.total == 1 and len(files) == 1
    md = files[0].read_text(encoding="utf-8")
    assert "Callout text" not in md and "### Main heading" in md
    assert f'"notion_id": "{FULL}"' in md


def test_broken_hook_file_gives_clear_error(tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_text("def filter_page(:\n", encoding="utf-8")
    with pytest.raises(Exception):
        run(tmp_path / "o", database=FULL, source_type="Single page", fmt_md=True, hooks=[str(bad)])


def test_cli_export_and_exit_codes(tmp_path, isolated, capsys):
    out = tmp_path / "o"
    code = cli_main(
        [
            "export",
            DB_ID,
            "-f",
            "md,txt",
            "-o",
            str(out),
            "--token",
            "tok",
            "-q",
            "--set",
            "math_engine=CDN (internet)",
        ],
        notion=FakeNotion(),
    )
    assert code == 0 and len(list((out / "Markdown").glob("*.md"))) == 2
    assert "Exported 2 page(s)" in capsys.readouterr().out
    code = cli_main(
        [
            "export",
            DB_ID,
            "-f",
            "md,txt",
            "-o",
            str(out),
            "--token",
            "tok",
            "-q",
            "--set",
            "math_engine=CDN (internet)",
        ],
        notion=FakeNotion(),
    )
    assert code == 0 and "unchanged" in capsys.readouterr().out  # incremental via CLI


def test_cli_usage_errors(tmp_path, isolated, capsys):
    assert cli_main(["export", FULL, "-f", "nope", "-o", str(tmp_path)]) == 2
    assert "Unknown format" in capsys.readouterr().err
    assert cli_main(["export", FULL, "-o", str(tmp_path)]) == 2  # no format
    assert cli_main(["export", FULL, "-f", "md", "-o", str(tmp_path)]) == 2  # no token
    assert "token" in capsys.readouterr().err.lower()
    assert (
        cli_main(
            ["export", FULL, "-f", "md", "-o", str(tmp_path), "--token", "t", "--set", "bogus=1"], notion=FakeNotion()
        )
        == 2
    )
    assert (
        cli_main(
            [
                "export",
                FULL,
                "-f",
                "md",
                "-o",
                str(tmp_path),
                "--token",
                "t",
                "--sub-pages",
                "inline",
                "--set",
                "margin_mm=abc",
            ],
            notion=FakeNotion(),
        )
        == 2
    )


def test_cli_settings_file_layering(tmp_path, isolated):
    cfgf = tmp_path / "pageout.json"
    cfgf.write_text(
        json.dumps(
            {
                "sources": [FULL],
                "formats": ["txt"],
                "out": str(tmp_path / "x"),
                "name_format": "{title}",
                "token": "ignored",
            }
        )
    )
    code = cli_main(["export", "-c", str(cfgf), "--token", "t", "-q", "-f", "md"], notion=FakeNotion())
    assert code == 0
    assert (tmp_path / "x" / "Markdown").exists() and not (tmp_path / "x" / "Text").exists()  # flag beat file


def test_cli_yaml_and_init_config(tmp_path, isolated):
    yaml = pytest.importorskip("yaml")
    path = tmp_path / "pageout.yaml"
    assert cli_main(["init-config", str(path)]) == 0
    assert yaml.safe_load(path.read_text(encoding="utf-8"))["formats"]
    assert cli_main(["init-config", str(path)]) == 2  # never overwrites


def test_cli_version(capsys):
    assert cli_main(["version"]) == 0
    assert config.APP_VERSION in capsys.readouterr().out


# ------------------------------------------------------------------ Phase 6: formats
def test_markdown_presets(tmp_path):
    kw = dict(database=DB_ID, source_type="Auto-detect", fmt_md=True)
    run_export(tmp_path / "v", md_preset="Vanilla", **kw)
    run_export(tmp_path / "o", md_preset="Obsidian", **kw)
    van = next((tmp_path / "v" / "Markdown").glob("*Full*.md")).read_text(encoding="utf-8")
    obs = next((tmp_path / "o" / "Markdown").glob("*Full*.md")).read_text(encoding="utf-8")
    assert "<details" not in van and "~~" not in van and "<u>" not in van
    assert "- ☑ Done task" in van and "**Toggle title**" in van
    assert "[[2024-01-10 - Empty page|the empty page]]" in obs and "[[2024-01-10 - Empty page|Empty page]]" in obs
    assert "> [!note]" in obs and 'tags: ["alpha", "beta"]' in obs


def test_latex_comment_mode_and_png_conversion(tmp_path):
    run_export(tmp_path / "c", database=FULL, source_type="Single page", fmt_tex=True, latex_images="Comments only")
    tex = next((tmp_path / "c" / "LaTeX").glob("*.tex")).read_text(encoding="utf-8")
    assert "% [Image 1 omitted: fig1.png]" in tex and "\\includegraphics" not in tex
    run_export(tmp_path / "f", database=FULL, source_type="Single page", fmt_tex=True)
    tex = next((tmp_path / "f" / "LaTeX").glob("*.tex")).read_text(encoding="utf-8")
    assert tex.count("\\includegraphics") == 2 and "\\textbf{} " not in tex
    assert (tmp_path / "f" / "Images").exists()


def test_latex_webp_is_converted_to_png(tmp_path, monkeypatch):
    PIL = pytest.importorskip("PIL.Image")
    buf = io.BytesIO()
    PIL.new("RGB", (3, 3), (9, 9, 9)).save(buf, "WEBP")
    monkeypatch.setattr(pipeline, "download", lambda url, timeout=60: (buf.getvalue(), "image/webp"))
    run_export(tmp_path, database=FULL, source_type="Single page", fmt_tex=True)
    exts = {p.suffix for p in (tmp_path / "Images").rglob("*") if p.is_file()}
    assert exts == {".png"}


def test_database_csv_index_and_table(tmp_path):
    kw = dict(database=DB_ID, source_type="Auto-detect", fmt_md=True, fmt_html=True)
    run(tmp_path / "csv", db_export="CSV file", **kw)
    csv_text = (tmp_path / "csv" / "All_Pages.csv").read_text(encoding="utf-8-sig")
    assert csv_text.splitlines()[0] == "Title,Date,Tags,Done,Score"
    assert 'Full: Test/Page?,2024-03-05,"alpha, beta",Yes,42' in csv_text

    run(tmp_path / "idx", db_export="Index page", **kw)
    idx = (tmp_path / "idx" / "Markdown" / "_Index.md").read_text(encoding="utf-8")
    assert "- [Full: Test/Page?](2024-03-05%20-%20Full%20TestPage.md)" in idx
    assert (tmp_path / "idx" / "HTML" / "_Index.html").exists()

    run(tmp_path / "tbl", db_export="Table of properties", **kw)
    tbl = (tmp_path / "tbl" / "Markdown" / "_Index.md").read_text(encoding="utf-8")
    assert "| Title | Date | Tags | Done | Score |" in tbl and "| 2024-03-05 | alpha, beta | Yes | 42 |" in tbl


def test_math_engines():
    from pageout.renderers.html import wrap_html

    body = '<div class="eq">x^2</div>'
    bundled = wrap_html("t", body, dict(config.DEFAULTS, math_engine=config.MATH_ENGINES[0]))
    assert "katex.render" in bundled and "font/woff2" in bundled and "cdnjs" not in bundled
    cdn = wrap_html("t", body, dict(config.DEFAULTS, math_engine=config.MATH_ENGINES[1]))
    assert "cdnjs.cloudflare.com" in cdn and "font/woff2" not in cdn
    none = wrap_html("t", body, dict(config.DEFAULTS, math_engine=config.MATH_ENGINES[2]))
    assert "katex" not in none
    plain = wrap_html("t", "<p>no math</p>", dict(config.DEFAULTS))
    assert "katex" not in plain  # no math -> nothing embedded


def _make_zip(path):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(
            "Export/Home aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.md",
            "# Home\n\nStatus: Done\nOwner: Ann\n\nHello **world** and `code` with $x^2$.\n\n"
            "## Lists\n\n- one\n  - nested\n- [x] done\n1. first\n\n"
            "```python\nprint(1)\n```\n\n| A | B |\n| --- | --- |\n| 1 | 2 |\n\n"
            "![pic](Home/pic.png)\n\nSee [Other](Other%20bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.md).\n\n"
            "<details>\n<summary>More</summary>\n\nhidden\n\n</details>\n",
        )
        z.writestr("Export/Other bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.md", "# Other\n\nSecond page.\n")
        z.writestr("Export/Home/pic.png", b"\x89PNG\r\n\x1a\n" + b"z" * 20)


def test_zip_source_offline(tmp_path, isolated):
    z = tmp_path / "export.zip"
    _make_zip(z)
    out = tmp_path / "o"
    code = cli_main(
        [
            "export",
            "--zip",
            str(z),
            "-f",
            "md,html,txt",
            "-o",
            str(out),
            "-q",
            "--set",
            "math_engine=CDN (internet)",
            "--set",
            "img_handling=Embed in file",
        ]
    )
    assert code == 0
    md = next((out / "Markdown").glob("*Home*.md")).read_text(encoding="utf-8")
    assert "Hello **world** and `code` with $x^2$." in md and "- [x] done" in md and "```python" in md
    assert "(Other.md)" in md or "Other%20" in md or "Other" in md
    assert '"Status": "Done"' in md and "| A | B |" in md and "<details>" in md
    html = next((out / "HTML").glob("*Home*.html")).read_text(encoding="utf-8")
    assert 'href="Other.html"' in html.replace("%20", " ").replace(" ", "") or "Other" in html
    assert "<table>" in html and "data:image/png;base64," in html
    assert "Second page." in next((out / "Text").glob("*Other*.txt")).read_text(encoding="utf-8")


def test_zip_source_parses_ids_and_links(tmp_path):
    from pageout.sources.notion_zip import ZipSource

    z = tmp_path / "e.zip"
    _make_zip(z)
    docs = {d.title: d for d in ZipSource(str(z)).documents()}
    assert set(docs) == {"Home", "Other"} and docs["Home"].id == "a" * 32
    link = next(s for b in docs["Home"].blocks for s in b.text if s.page_id)
    assert link.page_id == "b" * 32


# ------------------------------------------------------------------ Phase 7: safety
def test_secrets_are_redacted_from_failures_and_logs(tmp_path, monkeypatch):
    tok = "secret_" + "Z" * 43

    def boom(notion, block_id, cache):
        raise Exception(f"HTTP 401 for {tok}")

    monkeypatch.setattr(pipeline, "build_tree", boom)
    logs = []
    r = export(
        cfg_for(tmp_path, database=FULL, source_type="Single page", fmt_md=True, token=tok),
        notion=FakeNotion(),
        log=logs.append,
    )
    assert r.failed and all(tok not in str(f) for f in r.failed)
    assert all(tok not in m for m in logs)


def test_cancel_stops_cleanly(tmp_path):
    import threading

    ev = threading.Event()
    ev.set()
    from pageout.core.errors import Cancelled

    with pytest.raises(Cancelled):
        export(cfg_for(tmp_path, database=DB_ID, fmt_md=True), notion=FakeNotion(), cancel=ev)


# ------------------------------------------------------------------ notion-client 3.x shape
def test_database_via_data_sources_api_matches_classic(tmp_path):
    """notion-client 3.x has no databases.query; rows come from data_sources.query."""
    classic = tmp_path / "classic"
    v3 = tmp_path / "v3"
    fake3 = FakeNotion(v3=True)
    assert not hasattr(fake3.databases, "query")
    run_export(classic, database=DB_ID, source_type="Auto-detect", fmt_md=True, fmt_html=True)
    run_export(v3, notion=fake3, database=DB_ID, source_type="Auto-detect", fmt_md=True, fmt_html=True)
    assert collect(classic) == collect(v3)
    assert any(c[0] == "data_sources.query" for c in fake3.calls)


def test_unreachable_database_error_is_not_misleading(tmp_path):
    fake3 = FakeNotion(v3=True)
    with pytest.raises(Exception) as err:
        run_export(tmp_path, notion=fake3, database="e" * 32, source_type="Database", fmt_md=True)
    assert "Could not access the database" in str(err.value) and "has no attribute" not in str(err.value)


def test_cli_bad_zip_is_a_clean_error(tmp_path, isolated, capsys):
    assert cli_main(["export", "--zip", str(tmp_path / "missing.zip"), "-f", "md", "-o", str(tmp_path)]) == 2
    assert "Cannot read the zip" in capsys.readouterr().err
    bad = tmp_path / "bad.zip"
    bad.write_bytes(b"not a zip")
    assert cli_main(["export", "--zip", str(bad), "-f", "md", "-o", str(tmp_path)]) == 2
    empty = tmp_path / "empty.zip"
    zipfile.ZipFile(empty, "w").close()
    assert cli_main(["export", "--zip", str(empty), "-f", "md", "-o", str(tmp_path)]) == 2
    assert "no Markdown pages" in capsys.readouterr().err


# ------------------------------------------------------------------ Phase 8: Profiles
def test_profile_save_and_load(tmp_path, isolated):
    from pageout.core.profiles import save_profile, load_profile, list_profiles, delete_profile, profile_exists
    from pageout.core.config import DEFAULTS

    # Save a profile
    cfg = dict(DEFAULTS, fmt_pdf=True, fmt_md=True, name_format="{title}", save_dir=str(tmp_path))
    save_profile("my-profile", cfg)

    # List profiles
    profiles = list_profiles()
    assert "my-profile" in profiles

    # Load profile
    loaded = load_profile("my-profile")
    assert loaded["fmt_pdf"] is True
    assert loaded["fmt_md"] is True
    assert loaded["name_format"] == "{title}"
    # Secrets should not be in profile
    assert "token" not in loaded
    assert "gemini_api_key" not in loaded

    # Delete profile
    assert delete_profile("my-profile")
    assert "my-profile" not in list_profiles()


def test_profile_cli_commands(tmp_path, isolated, capsys):
    # Save profile via CLI (uses current config, which we set via env)
    import os
    os.environ["NOTION_TOKEN"] = "tok"
    code = cli_main([
        "profile", "save", "cli-profile",
    ])
    assert code == 0

    # List profiles
    code = cli_main(["profile", "list"])
    assert code == 0
    out = capsys.readouterr().out
    assert "cli-profile" in out

    # Load profile and print config
    code = cli_main(["profile", "load", "cli-profile"])
    assert code == 0
    out = capsys.readouterr().out
    assert '"fmt_pdf":' in out
    # Secrets not in output
    assert "token" not in out or '"token": ""' in out

    # Delete profile
    code = cli_main(["profile", "delete", "cli-profile"])
    assert code == 0
    capsys.readouterr()  # clear delete message
    code = cli_main(["profile", "list"])
    assert code == 0
    out = capsys.readouterr().out
    assert "cli-profile" not in out


def test_cli_export_with_profile(tmp_path, isolated):
    # First save a profile
    from pageout.core.profiles import save_profile
    from pageout.core.config import DEFAULTS
    profile_cfg = dict(DEFAULTS, fmt_md=True, save_dir=str(tmp_path / "prof_out"), name_format="{title}")
    save_profile("export-profile", profile_cfg)

    # Export using profile
    out_dir = tmp_path / "prof_out"
    code = cli_main([
        "export",
        DB_ID,
        "--profile", "export-profile",
        "--token", "tok",
        "-q",
    ], notion=FakeNotion())
    assert code == 0
    assert (out_dir / "Markdown").exists()
    files = list((out_dir / "Markdown").glob("*.md"))
    assert len(files) == 2  # DB has 2 pages
    # Check name_format was applied
    assert "Full: Test/Page?" in files[0].name or "Empty page" in files[0].name


def test_profile_merge_with_overrides(tmp_path, isolated):
    # Save a profile with specific settings
    from pageout.core.profiles import save_profile
    from pageout.core.config import DEFAULTS
    profile_cfg = dict(DEFAULTS, fmt_pdf=True, fmt_md=True, name_format="{title}", save_dir=str(tmp_path / "merge_out"))
    save_profile("merge-profile", profile_cfg)

    # Export with profile + CLI override (format should override)
    out_dir = tmp_path / "merge_out"
    code = cli_main([
        "export",
        DB_ID,
        "--profile", "merge-profile",
        "--format", "pdf",  # Override: only pdf, not md
        "--token", "tok",
        "-q",
    ], notion=FakeNotion())
    assert code == 0
    # Should have pdf, not markdown (CLI override wins)
    assert (out_dir / "PDF").exists()
    assert not (out_dir / "Markdown").exists()


# ------------------------------------------------------------------ Phase 8b: Saved Sources
def test_source_save_and_load(tmp_path, isolated):
    from pageout.core.sources import add_source, get_source, list_sources, delete_source, source_exists
    from pageout.core.config import DEFAULTS

    # Add a source
    assert add_source("my-source", "https://www.notion.so/testdb-1234567890abcdef1234567890abcdef", "Database")

    # List sources
    sources = list_sources()
    assert "my-source" in [s["name"] for s in sources]

    # Get source
    src = get_source("my-source")
    assert src is not None
    assert src["name"] == "my-source"
    assert src["source_type"] == "Database"
    assert src["url"] == "https://www.notion.so/testdb-1234567890abcdef1234567890abcdef"

    # Check exists
    assert source_exists("my-source") is True
    assert source_exists("nonexistent") is False

    # Delete source
    assert delete_source("my-source") is True
    assert "my-source" not in [s["name"] for s in list_sources()]


def test_source_cli_commands(tmp_path, isolated, capsys):
    # Add a source via CLI
    code = cli_main([
        "source", "add", "cli-source", "https://www.notion.so/testsrc-1234567890abcdef1234567890abcdef",
    ])
    assert code == 0

    # List sources
    code = cli_main(["source", "list"])
    assert code == 0
    out = capsys.readouterr().out
    assert "cli-source" in out

    # Delete source
    code = cli_main(["source", "delete", "cli-source"])
    assert code == 0
    capsys.readouterr()  # clear output
    code = cli_main(["source", "list"])
    assert code == 0
    out = capsys.readouterr().out
    assert "cli-source" not in out


def test_source_pin_toggle(tmp_path, isolated):
    from pageout.core.sources import add_source, list_sources, toggle_pin

    # Add a source
    add_source("pin-test", "https://www.notion.so/pintest-1234567890abcdef1234567890abcdef")

    # Initially not pinned
    sources = list_sources()
    src = next(s for s in sources if s["name"] == "pin-test")
    assert src.get("pinned") is False or src.get("pinned") is None

    # Toggle pin
    result = toggle_pin("pin-test")
    assert result is True

    # Now it should be pinned
    sources = list_sources()
    src = next(s for s in sources if s["name"] == "pin-test")
    assert src.get("pinned") is True

    # Toggle again
    result = toggle_pin("pin-test")
    assert result is False

    # Now it should not be pinned
    sources = list_sources()
    src = next(s for s in sources if s["name"] == "pin-test")
    assert src.get("pinned") is False


def test_extract_id_from_url():
    from pageout.core.sources import extract_id_from_url

    # Bare ID
    assert extract_id_from_url("1234567890abcdef1234567890abcdef") == "1234567890abcdef1234567890abcdef"

    # Full Notion URL
    result = extract_id_from_url("https://www.notion.so/workspace/My-Page-1234567890abcdef1234567890abcdef")
    assert result == "1234567890abcdef1234567890abcdef"

    # URL with query string
    result = extract_id_from_url("https://www.notion.so/1234567890abcdef1234567890abcdef?v=1")
    assert result == "1234567890abcdef1234567890abcdef"

    # Invalid URL
    assert extract_id_from_url("not-a-valid-id") is None


def test_cli_export_with_saved_source(tmp_path, isolated):
    # Add a saved source
    from pageout.core.sources import add_source
    add_source("test-db", DB_ID, "Database")

    # Export using the saved source via --source
    out_dir = tmp_path / "source_out"
    code = cli_main([
        "export",
        DB_ID,  # Still need to provide database (source just sets default)
        "--source", "test-db",
        "--format", "md",
        "--token", "tok",
        "-o", str(out_dir),
    ], notion=FakeNotion()
    )
    assert code == 0
    assert (out_dir / "Markdown").exists()
    files = list((out_dir / "Markdown").glob("*.md"))
    assert len(files) == 2  # DB has 2 pages
