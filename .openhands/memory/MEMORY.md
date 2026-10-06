# LinguaFix — project memory

## Build / test
- venv `.venv`; run `.venv/bin/python -m pytest`. GUI tests need `xvfb-run -a` + `PYTHONPATH=/usr/lib/python3/dist-packages` (GTK in this dev container).
- Coverage: local gate 85 %, CI gate 80 %. Baseline **807 passed, 88 %** (GUI job); core job 758 passed / 48 skipped, 87 %.
- `[tool.coverage.run] omit = ["src/linguafix/gui/*"]` — CI has no PyGObject, so GUI tests skip and their ~800 lines would report 0 % (CI total ~66 %, gate fails). Re-add only if CI installs GTK.
- CI: Python 3.10/3.11/3.12, all green.
- **Repo formatter is `black`, not `ruff format`.** `ruff format` rewrites an assert in `tests/test_data_sync.py` into a style `black --check` rejects → CI lint fails. Use `ruff check --fix` only; run `black src tests` to reformat.
- CI has two test jobs: core (`--cov-fail-under=80`, `gui/*` omitted) and a GUI job under `xvfb-run` with `--cov-config=coverage-gui.rc --cov-fail-under=85`. Both runnable locally now.
- **CI triggers are `push: [main]` and `pull_request: [main]` only.** The deploy branch `feat/linguafix-v0.2.0` gets no push CI; verify via `main` (identical tree after the merge) or open a PR.
- **Tooling trap**: `file_editor` corrupts non-ASCII on save for some files (double-encodes UTF-8: em-dash, box-drawing, Cyrillic). Restore with `git checkout HEAD -- <file>`, re-apply edits via a Python heredoc (`encoding="utf-8"`); detect by scanning `git ls-files` for mojibake lead-char runs.

## Key invariants (easy to regress)
- Daemon tracks the current word as **scancodes** (`daemon._scancodes`), not just chars. `TextInjector.replace_text(backspace_count: int, new: str, layout: str)`; the daemon passes `len(self._scancodes)`. A string-based count reintroduces the `рhello` truncation bug.
- **Boundary-Space fix (do not regress):** on a Space flush the Space is already on screen, so on-screen text is `buffer + " "`. The daemon deletes one extra char, types `converted + " "` (trailing space), records undo as `buffer + boundary_char`. Only Space is consumed/retyped (`injector.can_type` gates it — layout-invariant, typable by every backend); Enter/Tab stay after the word. The count/boundary mismatch was the real cause, not `trigger_settle_ms`.
- `uinput` replace = two flushes: backspaces (one `syn`), sleep `backspace_settle_ms` (default **80**), replacement (second `syn`). Single-batch raced Chromium/Electron async Backspace.
- **Key buffering during a fix:** the fix sleeps on the event-loop thread. `_handle_event` checks `_processing_buffer` and appends to `_deferred_events` (cap `_MAX_DEFERRED_EVENTS=50`). `_process_buffer`'s `finally` calls `_replay_deferred_events()` with `_replaying_events=True` (saved/restored, not cleared). Without this keys typed during the pause were dropped (`tests/test_input_buffer.py`).
- Boundary flushes (Space/Enter/Tab/punct) sleep `trigger_settle_ms` (50) **before** deleting; only boundary flushes pass `boundary=True`. Idle fallback + hotkey do not.
- Word-boundary triggers (`on_space`/`on_enter` on; `on_tab`/`on_punctuation` off) flush+fix in the same keystroke. `analysis_timeout` 0.8 is only the idle fallback.
- Token with an internal separator (`. @ / \ : _ -`) is never rewritten (URLs, e-mails, paths, versions, hyphenated ids). Guard sits AFTER conversion in `_process_buffer_inner` (the privacy secret contains `_` and needs the convert path to run).
- Config TOML is **flat** (no `[sections]`). `Config.to_dict` has a fixed key set asserted by tests.
- **Default detector corpora are `en`+`ru` only** (`DEFAULT_DETECTOR_LANGUAGES`). Latin layouts `us`/`de`/`fr` share physical positions; loading all makes them compete and shifts borderline results. `uk`/`de`/`fr` opt-in via `Config.languages`; a missing corpus is skipped, never an empty model.
- User dictionary is consulted **both ways**: (1) typed form is an **absolute** override (`target_layout`→`None`); (2) the *converted* form is checked inside the candidate loop and returns the layout outright, before the corpus guard — so `dict add vercel` makes `муксуд`→`vercel` fire even though `vercel` is absent from the corpora. Not a score bonus (n-grams drown it). File `~/.local/share/linguafix/dictionary.txt`; edited explicitly (`linguafix dict list|add|remove`, GUI Dictionary tab), never auto-written from typed text. `reload_config` re-reads it.
- **Default fix hotkey `SHIFT+SHIFT`** (`DEFAULT_FIX_HOTKEY`): double tap of a modifier within `hotkey_double_tap_ms` (default 300). `daemon._double_tap_family`/`_build_double_tap_hotkeys`/`_handle_modifier`; `_parse_hotkey` returns `None` for pure-modifier forms; any non-modifier key clears `_last_modifier_tap`; fires only when no *other* modifier family is held. Legacy `PAUSE` in **both** `hotkey` and `hotkey_fix_last_word` migrates to `SHIFT+SHIFT` (a deliberate single-field `PAUSE` is kept).
- Context analysis (`context_analysis`/`context_weight`) may only *add* to a candidate, never push the current layout below zero.
- **T9 typo correction** opt-in (`typo_correction=false`; `typo_max_distance` 1/2; `typo_min_word_length`>=3). `typo.py` = `bounded_damerau_levenshtein` + `TypoCorrector`. Runs in `_process_buffer_inner` **only** when `detector.target_layout()` is `None`; replaces a word only if absent from the vocabulary and within `max_distance` of **exactly one** word (tie ⇒ no change). Taught + separator tokens skipped. Correctors cached per language, cleared in `reload_config`. GUI: Advanced → «Исправление опечаток (T9)».
- **False-positive guards** (`plausibility_check`, `structural_boundaries`, `identifier_guard`; all default true) in `detector._should_guard`, called in `target_layout` **after** the user-dictionary override. Plausibility = score the buffer in its typed layout; if it reads as real words, veto the conversion. Structural = URL/e-mail/path/version separators. Identifier = `_IDENTIFIER_RE` (snake_case, camelCase, `x86_64`). `should_fix` uses `_should_guard_structure_only` so it stays a superset.
- **`daemon_control.py` is the single GUI control surface** (replaces deleted `gui/systemd_bridge.py`). `is_running` = PID lock alive **or** systemd active; `stop` prefers `systemctl stop` then SIGTERM→SIGKILL; `reload_config` SIGHUP; `undo_last_fix` SIGUSR1; `spawn_detached` prefers the installed `linguafix` launcher (sets PYTHONPATH for `.deb`) over `sys.executable -m`. Daemon writes `~/.cache/linguafix/daemon.lock` with `flock`.
- **Zombie PID was the real "toggle works every other time" root cause.** A daemon that exits but is not reaped (GUI spawns it) stays a zombie; `os.kill(pid,0)` still succeeds, so `pid_alive()` lied. `daemon_control.pid_alive` now reads `/proc/<pid>/stat` (state `Z` ⇒ dead); `read_pid` unlinks a stale lock only when it still names the same dead PID; `cli._read_pid`/`_pid_alive` delegate to it; `start` re-checks liveness ~0.3–0.4 s after the lock appears; `daemon.acquire_lock` takes `flock` **before** truncating.
- GUI HomePage toggle: `_on_toggle_clicked` sets the button busy, starts/stops on a **worker thread**, then `_poll_state`/`_on_polled` re-checks `is_active()` off-thread (12×150 ms) before `refresh()` — do not trust the start/stop return value; systemd can return before `is-active` flips. Never probe the daemon inline on the GTK thread.

## GUI invariants (P0: never block the main thread)
- **Never run a daemon probe on the GTK main thread.** `systemctl`/`g3kb-switch`/xprop/D-Bus have multi-second timeouts; running one inline froze the window ("приложение не отвечает"). Use `gui/async_utils.run_in_background(fn, on_done, *args)` (worker thread + `GLib.idle_add`); `on_done` runs on the main thread. `HomePage.refresh`/`_on_toggle_clicked` and `HistoryPage.refresh` are async. `tests/test_gui_nonblocking.py` asserts they return before a slow probe finishes.
- `Gio.BindingFlags` is **not** exposed — use `GObject.BindingFlags`.
- `Adw.ViewSwitcherTitle.set_title` is deprecated; the window title is used automatically.
- Page set is 5 (`home settings dictionary typo history`) + lazy `advanced` = 6. Tab truncation is solved with a header `ViewSwitcherTitle` + bottom `ViewSwitcherBar` (revealed when width < `NARROW_WIDTH`=560), not a fixed wide switcher.
- `daemon_control._systemctl` backs off 10 s after a timeout so a hung user D-Bus does not re-pay the 5 s timeout every refresh.

## Feature: punctuation + T9 tab (opt-in)
- `punctuation.py` is a small **rule** engine (dashes/ellipsis/smart-quotes/spacing), off by default; wired in `_process_buffer_inner` only when layout detection AND T9 both return None. Any replacement whose chars the backend cannot type is refused wholesale — `uinput` has no key for `—`/`…`, so those cleanups only fire under wtype/xdotool.
- Config keys `punctuation_correction|_dashes|_ellipsis|_smart_quotes|_fix_spacing`; added to the fixed config key set in `tests/test_privacy_audit.py` (`_ALLOWED_CONFIG_KEYS`).
- `gui/typo_page.py` is the T9 tab: a big master `BigToggle` (toggles typo+punctuation) plus rows via `BoundPreferencesPage` helpers.

## desktop-ID
- `data/linguafix.desktop` and `src/linguafix/data/linguafix.desktop` must stay byte-identical (`tests/test_data_sync.py`) and carry `StartupWMClass=io.github.pavel1778.LinguaFix` == `gui/app.py` APP_ID, so GNOME associates the window with its launcher.

## SEO / findability
- **Two hosts, one canonical.** Layero `https://linguafix.layero.app` is indexed; the Vercel preview is `noindex`. `site/src/layouts/Base.astro` sets the robots meta from `import.meta.env.VERCEL_URL` (set on every Vercel build). Canonical and og:url always point at `Astro.site` (Layero).
- **robots.txt is a build-time route** `site/src/pages/robots.txt.ts` (there is NO `site/public/robots.txt`): Layero gets `Allow: /` + sitemap URL, Vercel gets `Disallow: /`. A static file would be byte-identical on both hosts.
- **The sitemap is generated only when `VERCEL_URL` is unset** (`astro.config.mjs`): `integrations: [tailwind(), ...(isVercelBuild ? [] : [sitemap()])]`. The preview must not advertise URLs.
- `site/vercel.json` also sends `X-Robots-Tag: noindex, nofollow` for `/(.*)` as an HTTP-level backstop.
- **The Vercel preview is behind Deployment Protection** (302 to `vercel.com/sso-api`), so its deployed robots/meta cannot be curl-verified without a bypass secret. Verify by building both ways locally (`VERCEL_URL=x npm run build` vs plain).
- `site/public/og-image.png` is 1200x630 (the GitHub social-preview image).

## GitHub repo metadata (manual - token cannot)
- The fine-grained `GITHUB_TOKEN` has no admin scope: `PUT /topics` and `PATCH /repos/...` return 403. **Topics, About description, Website and Social preview must be set in the GitHub UI.**
- Topics are currently EMPTY; `homepage` is a STALE `https://linguafix.vercel.app` (should be `https://linguafix.layero.app`).
- Suggested topics: linux, keyboard-layout, layout-switcher, wayland, x11, gnome, kde, sway, evdev, uinput, python, gtk4, libadwaita, productivity, input-method, russian, english, punto-switcher-alternative, caramba-switcher-alternative, auto-switcher.

- **CI runs `mypy --strict .` over ALL files (tests too), and `ruff` lints tests.** Run `mypy --strict .` locally, not just `mypy --strict src/linguafix` — an unused `# type: ignore` in a test passes the src-only check but fails CI.
- **Before implementing a "new" feature, `git fetch` and check `origin/main` + recent branches.** A second session re-implemented the GUI non-blocking fix + T9 while `d430485` was already merged into `main` (dedicated T9 tab `gui/typo_page.py`, `gui/async_utils.py`, `punctuation.py` with `PunctuationCorrector.correct`). Duplicate PR #10 was closed; only the `.deb` postinst `gtk-update-icon-cache` fix was still missing (PR #11).

## Environment quirks
- `evdev` has no `__version__`. Target: Debian 13 trixie + GNOME 48 + Wayland (declared GNOME 45+).
- No `/dev/uinput` or real keyboard in dev; tests monkeypatch `evdev.UInput` (recording fake) and `TextInjector._uinput_available`.
- Tray (AppIndicator3) absent in dev; not a blocker.

## Repo / process
- **v0.1.0 and v0.2.0 both released.** `release.yml` builds `.deb`/sdist + `SHA256SUMS.txt` on a tag. **`main` holds the WHOLE project** (merge `66e7698`): v0.2.0 + both fix batches + landing page (`site/`) + logo/screenshots. All feature/fix branches contained in `main`. `site/package-lock.json` is tracked; `site/.astro/`, `site/dist/`, `site/node_modules/` are gitignored — never commit them.
- **Stage work goes on `feat/linguafix-v0.2.0`, never `main`** (that branch is the deploy branch; `main` is kept fast-forwarded to it). If a stage commit lands on `main` by mistake: `git checkout feat/linguafix-v0.2.0 && git merge --ff-only <sha> && git checkout main && git reset --hard <prev>`.
- **`scripts/*_test.sh` quoting trap**: the inner container script is the argument to `bash -c` wrapped in **single quotes**; any single quote inside closes it silently. Use double quotes for grep patterns inside. Both smoke and zero-config pass on `debian:12`.
- PR #1 (draft) was merged `--no-ff` (merge `b3c903f`). Issues #2/#3/#4 closed; #5 kept OPEN, milestone v0.2.0. Use `create_pr` only when asked.

## Landing page / deploy
- **Landing-page assets**: badges are **self-hosted SVGs in `site/public/badges/`** (`ci/license/python/platform.svg`) — shields.io was blocked/slow behind the host, so external badges rendered broken. Footer names **only** `linguafix.layero.app`; the Vercel preview is behind **Deployment Protection** (redirects to a vercel.com login), so never link it publicly. The Vercel build must stay `noindex` — `Base.astro` keys it off `VERCEL_URL`.
- **CI has a `site` job** (`npm ci` + `npm run build` against `site/package-lock.json`) — added because a broken landing build shipped unnoticed. The GUI job runs `test_gui.py`; GTK4+libadwaita+Xvfb are **installed in this dev container now**, so it also runs locally (`xvfb-run -a` + `PYTHONPATH=/usr/lib/python3/dist-packages`). Assert page *names*, not counts.
- **Verifying the live site**: Layero serves **brotli** — `curl` without `--compressed` returns binary garbage. Use `curl -s --compressed https://linguafix.layero.app/`. Layero redeploys from `feat/linguafix-v0.2.0` within ~30 s of a push.
- **Pushing**: the git remote token goes stale; refresh with `git remote set-url origin "https://${GITHUB_TOKEN}@github.com/Pavel1778/LinguaFix.git"` and always `GIT_TERMINAL_PROMPT=0` (a stale token otherwise hangs on a password prompt).
- Hero "window" is inline `WindowMock.astro` (not `<img>`) so its SVG text inherits the self-hosted Inter font. The power glyph is an SVG arc: keep sweep-flag `0` (`A36 36 0 1 0`) — flag `1` bulges the arc over the top of the disc and the icon looks «съехало». Verify by rendering headless and measuring the white-glyph centroid (offset ~0).
- Daemon network I/O (opt-in daily update check) must run off the evdev event-loop thread — 5 s timeout, would freeze typing. It runs on `_update_thread` now.
