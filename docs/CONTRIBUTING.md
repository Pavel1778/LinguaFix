# Contributing

Thanks for your interest in LinguaFix! This document describes how to set up a
development environment and the standards we follow.

## Development setup

```bash
git clone https://github.com/Pavel1778/LinguaFix.git
cd LinguaFix
bash scripts/dev_setup.sh
```

`dev_setup.sh` creates a virtual environment, installs the package in editable
mode together with the development extras, and installs the git hooks if
`pre-commit` is available.

## Running the tests

```bash
make test          # pytest with coverage
make lint          # ruff + black --check
make typecheck     # mypy --strict
make check         # all of the above
```

Or directly:

```bash
python -m pytest tests/ -q --cov=linguafix --cov-report=term-missing
ruff check .
black --check .
mypy --strict .
```

The test suite must stay above **80 %** coverage. The operating-system boundary
(`evdev` devices, `uinput`, `g3kb-switch`, `setxkbmap`, `wtype`, `xdotool`) is
replaced with lightweight fakes; the tests exercise the real daemon logic.

## Code standards

- Python 3.10+, fully typed. `mypy --strict` must pass.
- Formatting is enforced by `black` (line length 100) and imports by `isort`
  (black profile).
- Linting is enforced by `ruff`. Note that `RUF001`–`RUF003` are disabled
  because the project intentionally contains Cyrillic user-facing strings.
- All public functions and classes have Google-style docstrings.
- No `print()` in production code — use the `logging` module.
- External commands are always invoked as
  `subprocess.run([...], check=False, capture_output=True, timeout=N)`, never
  with `shell=True`.
- The daemon must never crash on a recoverable error: catch, log, continue.

## Adding a language

1. Add the layout map to `src/linguafix/data/layouts.json`.
2. Add `src/linguafix/data/ngrams_<lang>.json` with a `words` list and a
   `bigrams` frequency map.
3. Extend `LanguageDetector` if the new language needs special casing.
4. Add tests under `tests/`.

## Commit messages

Use conventional, atomic commits:

```
feat: add German layout support
fix: avoid crash when no input devices are present
docs: clarify Wayland limitations
```

## Building the .deb

```bash
bash scripts/build_deb.sh
```

This produces `dist/linguafix_<version>_all.deb`. The script builds the package
tree by hand (no `dh_make` required) and runs `dpkg-deb --build`.

Test the package before publishing:

```bash
make smoke-test                      # installs the .deb in a clean debian:12
SMOKE_IMAGE=ubuntu:22.04 make smoke-test   # Python 3.10 path
```

`make smoke-test` installs the real package into a clean container and checks
the entry point, the data files, the systemd unit path and `collect-logs`. It
catches packaging bugs that the pytest suite cannot, because pytest replaces the
operating-system boundary with fakes. When you add a runtime dependency, add it
to the `Depends:` line in `scripts/build_deb.sh` too — the two dependency lists
(apt and pip) must stay in sync.

Two files exist in both `data/` and `src/linguafix/data/`: `linguafix.service`,
`linguafix.desktop` and `linguafix.svg`. Keep them identical — a test enforces
this. `data/` is the source for `install.sh`; `src/linguafix/data/` is what the
installed package ships.

## Pull requests

- Keep the change focused; describe the motivation in the PR body.
- Make sure `make check` is green and CI passes.
- Update the documentation when behaviour or configuration changes.
