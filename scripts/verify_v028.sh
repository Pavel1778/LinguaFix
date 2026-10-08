#!/usr/bin/env bash
# Post-install verification for LinguaFix v0.2.8.
#
# Collects, in one file, everything a reviewer needs to confirm the v0.2.8
# fixes on a live GNOME/Wayland box:
#   * whether the daemon journals any SIGUSR2 line at all;
#   * the effective config (config show) after migrations;
#   * the CLI surfaces (top-level help, dict subcommands);
#   * a boundary-Space reproduction through the real uinput injector.
#
# It does not need root for the read-only parts. Run it right after installing
# the .deb and logging back in:
#
#   bash scripts/verify_v028.sh > ~/linguafix-verify.txt 2>&1
#
# The last section (reproduction) needs `ydotool` or `wtype` to type into a
# focused field; if neither is installed the script says so and skips it.
set -u

OUT_HEADER() { printf '\n===== %s =====\n' "$1"; }

OUT_HEADER "linguafix version"
linguafix --version 2>&1 || true

OUT_HEADER "daemon status"
linguafix status 2>&1 || true

OUT_HEADER "config show (effective, after migrations)"
linguafix config show 2>&1 || true

OUT_HEADER "top-level help (dict present?)"
linguafix --help 2>&1 | grep -i dict || true

OUT_HEADER "dict subcommands"
linguafix dict --help 2>&1 || true

# SIGUSR2: the v0.2.5 spam was 2 s apart. Watch the journal for 12 s and count
# every SIGUSR2 line. The handler now logs at DEBUG, so at the default level the
# count must be 0 even if something still signals the daemon.
OUT_HEADER "SIGUSR2 watch (12 s; expected 0 at default level)"
if command -v journalctl >/dev/null 2>&1; then
    timeout 12 journalctl --user -u linguafix.service -f 2>/dev/null \
        | grep -c SIGUSR2 &
    WATCH_PID=$!
    wait "$WATCH_PID" 2>/dev/null || true
    echo "(0 = no SIGUSR2 line surfaced)"
else
    echo "journalctl not available; run: linguafix logs -f | grep -c SIGUSR2"
fi

OUT_HEADER "log tail"
linguafix logs -n 20 2>&1 || true

# Boundary-Space reproduction. The bug was `руддщ` + Space rendering `рhello`.
# We type into whatever window has focus, so this section is interactive: the
# reviewer focuses a text field before it runs. Requires a typing backend.
OUT_HEADER "boundary-Space reproduction (interactive)"
TYPER=""
if command -v ydotool >/dev/null 2>&1; then
    TYPER="ydotool type"
elif command -v wtype >/dev/null 2>&1; then
    TYPER="wtype"
fi
if [ -z "$TYPER" ]; then
    echo "Neither ydotool nor wtype is installed; skipping reproduction."
    echo "Install one and re-run to type the test words automatically."
else
    echo "Focus a text field now; typing the test words in 5 s..."
    sleep 5
    for word in "руддщ " "ghbdtn "; do
        # Clear the field between words.
        $TYPER "$word"
        echo "typed: [$word]"
        sleep 1
    done
    echo "Expected on screen: 'hello ' then 'привет ' (no leading 'р')."
fi

OUT_HEADER "done"
echo "Attach this file to the PR if anything looks wrong."
