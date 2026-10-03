---
name: Bug report
about: Report something that does not work on your system
title: "[bug] "
labels: bug, needs-testing
---

## Environment

- Distribution: <!-- Debian 12 / Ubuntu 22.04 / other -->
- GNOME version (`gnome-shell --version`):
- Session type (`echo $XDG_SESSION_TYPE`): <!-- wayland / x11 -->
- `linguafix version`:
- Injector backend (`linguafix status`):
- Layout switcher backend (`linguafix status`):

## What happened

<!-- A clear description of the problem. -->

## Expected behaviour

## Steps to reproduce

1.
2.
3.

## Where it fails

- [ ] gnome-terminal
- [ ] Firefox
- [ ] Chrome / Chromium
- [ ] VS Code
- [ ] Gedit
- [ ] Game / other app (name):

## Logs

<!--
Attach the relevant lines from `~/.local/state/linguafix/linguafix.log` and
`journalctl --user -u linguafix.service`. The log contains only metadata (buffer
length, layouts), never the typed text.
-->

```
```

## Diagnostics

Run the collector and **drag the resulting tarball into this issue**:

```bash
linguafix collect-logs
# -> ~/linguafix-logs-YYYYMMDD-HHMMSS.tar.gz
```

It contains the `doctor` output, your configuration, the log tail, the user
journal, environment details, device permissions and package versions. The
daemon logs only metadata, so it never contains the text you typed.

If you prefer to paste text instead, include the output of:

```
linguafix doctor
linguafix status
groups | grep input
ls -l /dev/input/event*
```
