"""Golden-file tests: run the real Exporter end-to-end against recorded fixtures and compare
every produced text file with tests/golden/<scenario>/.

Regenerate goldens ONLY when a change in output is intended:
    UPDATE_GOLDEN=1 pytest tests/test_golden.py     (PowerShell: $env:UPDATE_GOLDEN=1)
then review `git diff tests/golden`."""

import os
from pathlib import Path

import pytest
from fake_notion import DB_ID, FakeNotion

import pageout.core.config as config
import pageout.core.pipeline as pipeline
import pageout.sources.notion_api as notion_api

GOLDEN = Path(__file__).parent / "golden"
TEXT_EXT = {".html", ".md", ".txt", ".json", ".tex"}
FULL = "a" * 32

SCENARIOS = {
    # one page, every block type, sub-page inline, all text formats
    "single_full": dict(
        database=FULL,
        source_type="Single page",
        sub_mode="Inline in parent",
        fmt_html=True,
        fmt_md=True,
        fmt_txt=True,
        fmt_json=True,
        fmt_tex=True,
    ),
    # database of two pages, sorted by date, combined files
    "database_combined": dict(
        database=DB_ID,
        source_type="Auto-detect",
        sub_mode="Skip",
        fmt_html=True,
        fmt_md=True,
        fmt_tex=True,
        combine=True,
        merged_name="All",
    ),
    # design options: cover page, pills, centered titles, no links
    "design_variant": dict(
        database=FULL,
        source_type="Single page",
        sub_mode="Skip",
        fmt_html=True,
        fmt_md=True,
        cover_page=True,
        prop_layout="Inline Pills",
        heading_align="Center",
        title_separator=True,
        links="Remove all links",
        icon_mode="Hide icon",
        show_image_names=True,
        caption_format="Figure {n}: {name}",
        one_image_per_page=True,
        maximize_images=True,
        accent_color="#2563eb",
        font_family="Serif",
        text_align="Justify",
    ),
}


def ne_defaults():
    return dict(config.DEFAULTS)


def run_export(out_dir, notion=None, **over):
    base = dict(
        ne_defaults(),
        token="secret-test-token",
        save_dir=str(out_dir),
        fmt_pdf=False,
        img_handling="Keep Notion link",
        workers=2,
        math_engine="CDN (internet)",
    )  # keeps golden HTML small (bundled KaTeX is ~600 KB)
    base.update(over)
    ex = pipeline.Exporter(base, log=lambda m: None, notion=notion or FakeNotion())
    return ex.run()


def collect(root: Path):
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.suffix.lower() in TEXT_EXT and not p.name.startswith("."):
            out[p.relative_to(root).as_posix()] = p.read_text(encoding="utf-8").replace("\r\n", "\n")
    return out


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_golden(name, tmp_path):
    _, total, failed = run_export(tmp_path, **SCENARIOS[name])
    assert failed == [], failed
    got = collect(tmp_path)
    assert got, "export produced no files"
    gdir = GOLDEN / name
    if os.environ.get("UPDATE_GOLDEN"):
        for rel, txt in got.items():
            f = gdir / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(txt, encoding="utf-8", newline="\n")
        pytest.skip("golden files updated")
    expected = collect(gdir)
    assert set(got) == set(expected), f"file set differs: {sorted(set(got) ^ set(expected))}"
    for rel in expected:
        assert got[rel] == expected[rel], f"{name}/{rel} differs from golden"


def test_docx_smoke(tmp_path):
    docx = pytest.importorskip("docx")
    _, _, failed = run_export(
        tmp_path, database=FULL, source_type="Single page", sub_mode="Inline in parent", fmt_docx=True
    )
    assert failed == []
    files = list((tmp_path / "Word").rglob("*.docx"))
    assert len(files) == 1
    text = "\n".join(p.text for p in docx.Document(str(files[0])).paragraphs)
    for needle in ("Main heading", "Bullet one", "Hidden content", "Sub page", "Left column"):
        assert needle in text


def test_json_is_valid_and_private_keys_stripped(tmp_path):
    import json

    run_export(tmp_path, database=FULL, source_type="Single page", fmt_json=True)
    data = json.loads(next((tmp_path / "JSON").rglob("*.json")).read_text(encoding="utf-8"))
    assert data["title"] == "Full: Test/Page?"
    assert "_img" not in json.dumps(data) and "_sub" not in json.dumps(data)


def test_token_never_written_to_outputs(tmp_path):
    run_export(
        tmp_path,
        database=FULL,
        source_type="Single page",
        fmt_html=True,
        fmt_json=True,
        fmt_md=True,
        fmt_tex=True,
        fmt_txt=True,
    )
    for txt in collect(tmp_path).values():
        assert "secret-test-token" not in txt


def test_skip_existing_does_not_overwrite(tmp_path):
    run_export(tmp_path, database=FULL, source_type="Single page", fmt_md=True)
    f = next((tmp_path / "Markdown").rglob("*.md"))
    f.write_text("SENTINEL", encoding="utf-8")
    run_export(tmp_path, database=FULL, source_type="Single page", fmt_md=True, skip_existing=True)
    assert f.read_text(encoding="utf-8") == "SENTINEL"


def test_failure_in_one_page_does_not_abort(tmp_path, monkeypatch):
    real = notion_api.build_tree

    def flaky(notion, block_id, cache):
        if block_id == "b" * 32:
            raise Exception("boom")
        return real(notion, block_id, cache)

    monkeypatch.setattr(pipeline, "build_tree", flaky)
    _, total, failed = run_export(
        tmp_path, database=__import__("fake_notion").DB_ID, source_type="Auto-detect", fmt_md=True
    )
    assert total == 2 and len(failed) == 1 and "Empty page" in failed[0][0]
    assert len(list((tmp_path / "Markdown").rglob("*.md"))) == 1


def test_separate_subpages_mode(tmp_path):
    """Sub-pages as their own files (raw-tree scan in plan())."""
    _, total, failed = run_export(
        tmp_path, database=FULL, source_type="Single page", sub_mode="Separate files", fmt_md=True
    )
    assert failed == [] and total == 2
    names = sorted(p.name for p in (tmp_path / "Markdown").rglob("*.md"))
    assert len(names) == 2 and any("Sub page" in n for n in names)
