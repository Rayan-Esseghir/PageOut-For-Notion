"""Fast unit tests for pure helpers (naming, ids, dates, escaping, config, rate limiting)."""

import json
import time

import pytest

import pageout.core.config as config
import pageout.core.naming as naming
import pageout.renderers.base as base
import pageout.renderers.latex as latex
import pageout.sources.notion_api as notion_api


# ---- ids / names ----
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("a" * 32, "a" * 32),
        ("https://www.notion.so/My-Page-" + "0123456789abcdef" * 2, "0123456789abcdef" * 2),
        ("https://www.notion.so/ws/" + "0123456789abcdef" * 2 + "?v=1", "0123456789abcdef" * 2),
        ("01234567-89ab-cdef-0123-456789abcdef", "0123456789abcdef0123456789abcdef"),
    ],
)
def test_parse_database_id(raw, expected):
    assert notion_api.parse_database_id(raw) == expected


def test_clean_filename():
    assert naming.clean_filename('a/b\\c:d*e?"f<g>h|i') == "abcdefghi"
    assert naming.clean_filename("  many   spaces ") == "many spaces"


F = {
    "title": "Hello World",
    "date": "2024-03-05",
    "index": "007",
    "created": "2024-01-01",
    "edited": "2024-02-02",
    "parent": "",
    "status": "Open",
}


@pytest.mark.parametrize(
    "tpl,expected",
    [
        ("{date} - {title}", "2024-03-05 - Hello World"),
        ("{title:5}", "Hello"),
        ("{date:%d-%m-%Y} {title}", "05-03-2024 Hello World"),
        ("{index} {Status}", "007 Open"),
        ("{parent} - {title}", "Hello World"),  # empty parts are trimmed
        ("", "Untitled"),
        ("{missing}", "Untitled"),
    ],
)
def test_build_name(tpl, expected):
    assert naming.build_name(tpl, F) == expected


def test_build_name_length_cap():
    assert len(naming.build_name("{title}", {"title": "x" * 500})) <= 150


# ---- dates ----
@pytest.mark.parametrize(
    "preset,expected",
    [
        ("YYYY-MM-DD", "2024-03-05"),
        ("DD/MM/YYYY", "05/03/2024"),
        ("MM/DD/YYYY", "03/05/2024"),
        ("MMM DD, YYYY", "Mar 05, 2024"),
        ("%d.%m.%Y", "05.03.2024"),
        ("ISO 8601", "2024-03-05T00:00:00Z"),
    ],
)
def test_format_date(preset, expected):
    assert naming.format_date("2024-03-05", preset) == expected


def test_format_date_empty_and_bad():
    assert naming.format_date("", "YYYY-MM-DD") == ""
    assert naming.format_date("garbage!!!", "DD/MM/YYYY") == "garbage!!!"[:10]


# ---- LaTeX escaping ----
def test_escape_tex_single_pass():
    assert latex.escape_tex("a\\b") == "a\\textbackslash{}b"
    assert (
        latex.escape_tex("100% & $5 #1 _x_ {y} ~ ^")
        == "100\\% \\& \\$5 \\#1 \\_x\\_ \\{y\\} \\textasciitilde{} \\textasciicircum{}"
    )
    assert latex.escape_tex("hi 😀") == "hi "
    assert latex.escape_tex("") == ""


# ---- filter / sort ----
def _page(title, date):
    return {
        "properties": {
            "Name": {"type": "title", "title": [{"plain_text": title}]},
            "Date": {"type": "date", "date": {"start": date}},
        },
        "created_time": "",
        "last_edited_time": "",
    }


def test_filter_and_sort():
    a, b = _page("Beta", "2024-02-01"), _page("Alpha", "2024-01-01")
    assert [notion_api.page_title(p) for p in notion_api.sort_pages([a, b], "Date", False)] == ["Alpha", "Beta"]
    assert [notion_api.page_title(p) for p in notion_api.sort_pages([a, b], "Title", True)] == ["Beta", "Alpha"]
    assert notion_api.passes_filter(a, "title", "contains", "bet")
    assert not notion_api.passes_filter(a, "title", "does not contain", "bet")
    assert notion_api.passes_filter(a, "title", "equals", "BETA")
    assert notion_api.passes_filter(a, "", "contains", "x")  # no filter -> pass


# ---- links ----
def test_link_modes():
    r = base.R(dict(config.DEFAULTS, links=config.LINK_MODES[2]), "html")
    assert r.keep_link("https://example.com") and not r.keep_link("/abc") and not r.keep_link("https://www.notion.so/x")
    assert not base.R(dict(config.DEFAULTS, links=config.LINK_MODES[1]), "html").keep_link("https://x.y")


# ---- config ----
@pytest.fixture
def cfgfile(tmp_path, monkeypatch):
    f = tmp_path / "config.json"
    monkeypatch.setattr(config, "CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(config, "CONFIG_FILE", str(f))
    monkeypatch.delenv("NOTION_TOKEN", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    return f


def test_config_migration_of_old_defaults(cfgfile):
    cfgfile.write_text(json.dumps({"_ver": 1, "margin_mm": 10, "line_spacing": 1.2}))
    cfg = config.load_config()
    assert cfg["margin_mm"] == config.DEFAULTS["margin_mm"] and cfg["_ver"] == config.CONFIG_VERSION


def test_secrets_go_to_keyring_not_to_file(cfgfile, _fake_keyring):
    cfg = config.load_config()
    cfg.update(token="tok-123456789", remember_token=True, gemini_api_key="gem-123456789")
    assert config.save_config(cfg) == ""
    on_disk = json.loads(cfgfile.read_text())
    assert on_disk["token"] == "" and on_disk["gemini_api_key"] == ""
    assert _fake_keyring == {"notion_token": "tok-123456789", "gemini_api_key": "gem-123456789"}
    assert config.load_config()["token"] == "tok-123456789"
    cfg["remember_token"] = False  # untick -> forgotten
    config.save_config(cfg)
    assert "notion_token" not in _fake_keyring


def test_plaintext_fallback_needs_opt_in(cfgfile, monkeypatch):
    import pageout.core.secrets as secrets

    monkeypatch.setattr(secrets, "set_secret", lambda n, v: False)  # no keyring available
    cfg = config.load_config()
    cfg.update(token="tok-123456789", remember_token=True)
    warning = config.save_config(cfg)
    assert "NOT saved" in warning and json.loads(cfgfile.read_text())["token"] == ""
    cfg["allow_plaintext_secrets"] = True
    assert config.save_config(cfg) == ""
    assert json.loads(cfgfile.read_text())["token"] == "tok-123456789"


def test_legacy_plaintext_token_is_migrated(cfgfile, _fake_keyring):
    cfgfile.write_text(json.dumps({"_ver": 2, "token": "legacy-token-123", "remember_token": True}))
    assert config.load_config()["token"] == "legacy-token-123"
    assert _fake_keyring["notion_token"] == "legacy-token-123"
    assert json.loads(cfgfile.read_text())["token"] == ""


def test_config_token_from_env(cfgfile, monkeypatch):
    monkeypatch.setenv("NOTION_TOKEN", "envtok")
    assert config.load_config()["token"] == "envtok"


def test_redact():
    import pageout.core.secrets as secrets

    tok = "secret_" + "A" * 43
    out = secrets.redact(f"failed with {tok} and my-own-key-123456", ["my-own-key-123456"])
    assert tok not in out and "my-own-key" not in out and "***" in out
    assert "AIza" not in secrets.redact("key AIza" + "B" * 35)


# ---- rate limiting / retries ----
def test_api_retries_on_429_then_succeeds(monkeypatch):
    sleeps, calls = [], {"n": 0}
    monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))

    def flaky(**kw):
        calls["n"] += 1
        if calls["n"] < 3:
            raise Exception("HTTP 429 rate_limited")
        return {"ok": kw}

    assert notion_api.api(flaky, a=1) == {"ok": {"a": 1}}
    assert calls["n"] == 3 and sleeps == [1.5, 3.0]


def test_api_does_not_retry_permanent_errors(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda s: pytest.fail("must not sleep"))
    with pytest.raises(Exception, match="object_not_found"):
        notion_api.api(lambda **k: (_ for _ in ()).throw(Exception("object_not_found")))


def test_api_gives_up_after_max_retries(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda s: None)
    n = {"c": 0}

    def always(**kw):
        n["c"] += 1
        raise Exception("503 bad gateway")

    with pytest.raises(Exception):
        notion_api.api(always)
    assert n["c"] == 7


# ---- block tree ----
def test_build_tree_nests_children_and_skips_subpages():
    from fake_notion import FakeNotion

    fake = FakeNotion()
    tree = notion_api.build_tree(fake, "a" * 32, {})
    types = [b["type"] for b in tree]
    assert "child_page" in types and "table" in types
    table = next(b for b in tree if b["type"] == "table")
    assert len(table["children"]) == 2
    child = next(b for b in tree if b["type"] == "child_page")
    assert "children" not in child  # sub-pages are never entered by build_tree
