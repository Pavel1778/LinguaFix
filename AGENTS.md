# AGENTS.md

Repository-specific notes for agents working on LinguaFix.

## Layout

- `src/linguafix/` — the Python package (PEP 621, `pyproject.toml`).
- `data/` — system integration files (systemd unit, XDG autostart, udev rule, icon).
- `src/linguafix/data/` — data files **shipped inside the package** (`layouts.json`,
  `ngrams_*.json`, `stop_words.txt`, and copies of the unit/desktop/icon).
- `scripts/` — `build_deb.sh`, `smoke_test.sh`, `dev_setup.sh`.

`linguafix.service`, `linguafix.desktop` and `linguafix.svg` exist in **both**
`data/` and `src/linguafix/data/` and must stay byte-identical — a test enforces
this. `data/` is read by `install.sh`; `src/linguafix/data/` is what an installed
package ships and what the CLI reads.

## Build and verify

```bash
pip install -e ".[dev]"
make check                                  # ruff + black --check + mypy --strict + pytest --cov
make build-deb && make smoke-test           # install the .deb into a clean debian:12
SMOKE_IMAGE=ubuntu:22.04 make smoke-test    # Python 3.10 path (tomli)
```

- Quality bar: `ruff check .`, `black --check .`, `mypy --strict .` clean;
  pytest coverage ≥ 80 %.
- The pytest suite replaces the OS boundary with fakes, so it **cannot** catch
  packaging bugs. `scripts/smoke_test.sh` installs the real `.deb` into a clean
  container and is the only check that proves the package works.

## Invariants that have bitten before

- The `.deb` must be **zero-config**: device access is granted by a udev rule
  with `TAG+="uaccess"`, never `GROUP="input"`/`usermod`. The user unit is
  enabled with `systemctl --user enable --global` from `postinst`, not by the
  user. `make zero-config` asserts all of this.
- Keep the apt `Depends:` in `scripts/build_deb.sh` in sync with the runtime
  imports. `tomli` is required on Python < 3.11; `tomli_w` on all versions.
- `data/*.service` and `data/*.desktop` contain a `@BIN@` placeholder. It is
  rendered by `install.sh` (venv launcher), `build_deb.sh` (`/usr/bin/linguafix`)
  and the CLI (`shutil.which("linguafix")`). Never ship an unrendered file.
- `subprocess.run(..., check=False)` still raises `FileNotFoundError` when the
  binary is missing. Guard calls with `OSError`.
- `install.sh` runs under `set -u`; do not reference `USER` directly (it is unset
  in cron/su/containers) — use the `CURRENT_USER` fallback.
- Inside `docker run ... bash -c '...'` single-quoted blocks, do not put an
  apostrophe in a comment: it ends the block early. The smoke and zero-config
  scripts both hit this.
- Running the installed CLI as root creates root-owned `__pycache__` under
  `/usr/lib/linguafix`, which dpkg does not track; `postrm` cleans it with
  `py3clean` + `rm -rf`.

## Security / privacy invariants (audited)

- The typed text must never reach disk or a subprocess argv. `_process_buffer`
  and `_handle_event` catch every exception and log a **sanitized** traceback:
  the buffer is replaced with `<redacted>` before logging, because an exception
  message could otherwise embed it. `tests/test_privacy_audit.py` greps the log,
  cache, state, config, journal and argv for a known secret and must stay green.
- The desktop notification is a fixed label, never the corrected text.
- Replacement on the `uinput` backend is **atomic**: all backspaces and the new
  text are written and flushed with a single `syn`. `wtype`/`xdotool` are not
  atomic (documented limitation).
- `_process_buffer` snapshots and clears the buffer under `self._lock`, then
  releases the lock before the slow switch/inject so keys typed during a fix are
  buffered, not dropped. Do not hold the lock across `replace_text`.
- The buffer is bounded by `Config.max_buffer_size` (default 200) and flushed
  early on overflow, so a held key cannot grow it without bound.
- `linguafix stop` escalates to `SIGKILL` after 2 s; `linguafix kill` forces it.
- When the last keyboard disappears the loop re-runs discovery in place (never
  caches a device path); `Restart=always` is the backstop.

## Known limitation

The daemon works on a real GNOME desktop only; the CI and smoke tests do not
exercise the evdev → uinput correction path end to end. See `docs/TESTING.md`.
