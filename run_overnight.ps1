$ErrorActionPreference = "Continue"

$rules = @(
    "Rules for this phase (strictly follow):",
    "- Small context window: NEVER read whole large files (presenter.py, app.py, cli.py, pipeline.py, config.py, sources.py). Always use Grep first to get exact line numbers, then Read with offset and limit <= 60 lines.",
    "- Do NOT spawn subagents or background agents, and do NOT read/write memory files.",
    "- Start PowerShell commands directly with python, pip, or git (already in C:\Projects\Notion-Exporter). Chain with ; (never &&, tail, head, or grep).",
    "- Put new logic in small dedicated files (pageout/core/..., pageout/gui/..., pageout/renderers/...) and wire into app.py/cli.py with targeted Edit calls.",
    "- Keep core/ free of GUI imports, keep secrets in OS keyring with log redaction, preserve old config.json migration, and bind every new DEFAULTS key to a widget or hidden list.",
    "- Test only your new test file while coding (python -m pytest tests/test_<phase>.py -q --tb=line), then run the full suite (python -m pytest -q --tb=line) once right before committing.",
    "- Commit with: git add -A; git commit -m `"<commit message>`" (skip git diff/log/status/config). Keep your final response under 3 lines."
) -join "`n"

$phases = @(
    @{
        Name = "Phase 11"
        Task = 'Complete ONLY Phase 11 (Workspace & database sources): pageout/core/sources.py already exists; wire filter/sort/group_by into the pipeline, support multiple database data sources, add group-by export mode (one file per group), workspace/search multi-page selection in GUI and CLI, and tests in tests/test_phase11.py. Run python -m pytest -q --tb=line and Tk smoke check: python -c "from pageout.gui.app import App; app = App(); app.root.update(); app.root.destroy()". Commit as: "Complete Phase 11: Workspace and database sources".'
    },
    @{
        Name = "Phase 12"
        Task = 'Complete ONLY Phase 12 (Scheduling): add CLI "pageout schedule add/list/remove" (schtasks on Windows without admin rights, crontab on Linux/macOS), GUI Schedule dialog wired into menu/toolbar, scheduled run log file output, and tests in tests/test_phase12.py. Run python -m pytest -q --tb=line and Tk smoke check: python -c "from pageout.gui.app import App; app = App(); app.root.update(); app.root.destroy()". Commit as: "Complete Phase 12: Scheduling".'
    },
    @{
        Name = "Phase 13"
        Task = 'Complete ONLY Phase 13 (Better PDF): add table of contents, running header with page title, watermark, A5 booklet option, improved cover page, and tests in tests/test_phase13.py. Run python -m pytest -q --tb=line. Commit as: "Complete Phase 13: Better PDF".'
    },
    @{
        Name = "Phase 14"
        Task = 'Complete ONLY Phase 14 (Templates & plugins): add safe/sandboxed user HTML templates for pages & index pages, auto-loaded ~/.pageout/plugins for hooks and custom block renderers with error isolation, and tests in tests/test_phase14.py. Run python -m pytest -q --tb=line. Commit as: "Complete Phase 14: Templates and plugins".'
    },
    @{
        Name = "Phase 15"
        Task = 'Complete ONLY Phase 15 (More formats): add EPUB, reStructuredText, AsciiDoc, Obsidian vault mode (folders, attachments, relative links), Hugo/Jekyll front-matter presets, and tests in tests/test_phase15.py. Run python -m pytest -q --tb=line. Commit as: "Complete Phase 15: More formats".'
    },
    @{
        Name = "Phase 16"
        Task = 'Complete ONLY Phase 16 (Cloud & Git targets): add post-export sync to local/network folder, Google Drive, Dropbox, S3, or Git repo (commit + push) behind optional dependencies and keyring/env credentials, plus tests in tests/test_phase16.py. Run python -m pytest -q --tb=line. Commit as: "Complete Phase 16: Cloud and Git targets".'
    },
    @{
        Name = "Phase 17"
        Task = 'Complete ONLY Phase 17 (Fidelity): add comments export, user/date mentions, link previews, resolved synced blocks, Word internal links as bookmarks/relative links, unknown/unsupported block reporting in export report, and tests in tests/test_phase17.py. Run python -m pytest -q --tb=line. Commit as: "Complete Phase 17: Fidelity".'
    },
    @{
        Name = "Phase 18"
        Task = 'Complete ONLY Phase 18 (Polish & distribution): add GitHub release update check, English + Arabic UI strings with RTL layout, PyInstaller build script (--icon=pageout/assets/pageout.ico, bundling pageout/assets), Inno Setup installer script (SetupIconFile), portable zip script, and anonymised fixtures in tests/fixtures/real/. Install pyinstaller if missing, build dist/PageOut.exe and portable .zip, verify .\dist\PageOut.exe --help exits 0. Run python -m pytest -q --tb=line and Tk smoke check: python -c "from pageout.gui.app import App; app = App(); app.root.update(); app.root.destroy()". Commit as: "Complete Phase 18: Polish, distribution, and PageOut.exe build".'
    },
    @{
        Name = "U7"
        Task = 'Complete ONLY U7 (Safety, i18n, accessibility & final build): add confirmations for overwrite, large exports (with time estimate), cloud-synced folders (OneDrive/Dropbox), and long Windows paths; crash/session recovery; complete English + Arabic RTL UI; keyboard-only operation; high-contrast theme; accessible widget names; and tests in tests/test_u7.py. Re-run the PyInstaller build script so dist/PageOut.exe and portable .zip include U7, verify .\dist\PageOut.exe --help exits 0. Run python -m pytest -q --tb=line and Tk smoke check: python -c "from pageout.gui.app import App; app = App(); app.root.update(); app.root.destroy()". Commit as: "Complete U7: Safety, i18n, accessibility, and final exe".'
    }
)

foreach ($p in $phases) {
    $ts = Get-Date -Format "HH:mm:ss"
    Write-Host "`n[$ts] === Starting $($p.Name) ===" -ForegroundColor Cyan
    $prompt = $p.Task + "`n`n" + $rules
    claude -p $prompt --dangerously-skip-permissions --effort low
    $ts2 = Get-Date -Format "HH:mm:ss"
    Write-Host "[$ts2] === Finished $($p.Name) (exit $LASTEXITCODE) ===" -ForegroundColor Green
}

Write-Host "`nALL PHASES COMPLETE!" -ForegroundColor Yellow
git log --oneline -12
