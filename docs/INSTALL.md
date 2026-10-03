# Installation

LinguaFix targets Debian 12+ / Ubuntu 22.04+ with GNOME 42–45 on either X11 or
Wayland. Python 3.10 or newer is required.

## Zero-config .deb path (recommended)

This is the path for regular users. Nothing has to be configured by hand:

```bash
sudo apt install ./linguafix_0.1.0_all.deb
```

That is the whole procedure. The package:

- installs `/usr/lib/udev/rules.d/99-linguafix.rules`, which grants access to
  `/dev/input/event*` and `/dev/uinput` to the active session user with
  `TAG+="uaccess"` — no `usermod`, no group membership, no relogin;
- loads the `uinput` module so `/dev/uinput` exists;
- enables the systemd user service **globally**
  (`systemctl --user enable --global linguafix.service`), so it starts at the
  next login. It is not started during installation because there may be no
  graphical session yet.

After the next login the daemon is running. Verify with:

```bash
linguafix doctor
systemctl --user is-enabled linguafix.service   # -> enabled
```

`uaccess` grants the ACL when the user logs in at the seat. If the package is
installed while a session is already open, the ACL appears at the next login or
after a reboot; that is expected and needs no manual command. If `doctor` still
reports a permission problem after a relogin, see
[TROUBLESHOOTING: после установки .deb doctor жалуется на права /dev/input или /dev/uinput](TROUBLESHOOTING.md#после-установки-deb-doctor-жалуется-на-права-devinput-или-devuinput).

> Why `uaccess` and not the `input` group: the ACL is granted only to the user
> physically logged in at the seat, is applied dynamically and is revoked when
> the session ends. Permanent membership of the `input` group would give every
> member access to every keyboard, always.

## GNOME version and g3kb-switch

On GNOME Wayland the active layout is changed through `g3kb-switch`, which
talks to a GNOME Shell extension and is tied to the shell's D-Bus API. That API
has changed between GNOME releases, so the supported range is **GNOME 42–45**.
`install.sh` prints a warning when it detects a GNOME version outside that
range. If `g3kb-switch` is missing or incompatible, LinguaFix still replaces the
text but cannot change the active layout.

Check your version with:

```bash
gnome-shell --version
```

## Quick install (developer path)

This path is for contributors who work from a clone. Regular users should use
the `.deb` above.

```bash
git clone https://github.com/Pavel1778/LinguaFix.git
cd LinguaFix
bash install.sh
```

The installer is idempotent and can be re-run safely. Pass `--yes` for a
non-interactive run (useful in scripts):

```bash
bash install.sh --yes
```

## What the installer does

1. Checks that the host looks like Debian/Ubuntu (warns, but continues, if not).
2. Verifies Python 3.10+.
3. Installs system packages with `apt`:
   `python3-evdev python3-uinput python3-gi gir1.2-appindicator3-0.1 wtype
   xdotool libnotify-bin`.
4. Optionally helps you install `g3kb-switch` for GNOME Wayland layout
   switching.
5. Creates a virtual environment in `~/.local/share/linguafix/venv/` and
   installs the package with `pip install -e .`.
6. Installs the udev rule `/etc/udev/rules.d/99-linguafix.rules` (asks for sudo).
   The rule grants access with `TAG+="uaccess"`, so no group change is needed.
7. Loads the `uinput` module.
8. Installs the systemd user service `~/.config/systemd/user/linguafix.service`.
9. Installs the XDG autostart entry
   `~/.config/autostart/linguafix.desktop`.
10. Copies the icon to
    `~/.local/share/icons/hicolor/scalable/apps/linguafix.svg`.
11. Enables and starts the service.
12. Sends a desktop notification.

## After installing (developer path)

The udev rule grants the ACL to the active session user. If the rule was just
installed, reload it so the ACL is applied:

```bash
sudo udevadm control --reload-rules && sudo udevadm trigger
```

A full logout/login also applies it. No `usermod` and no group change is
involved.

## Verifying the install

```bash
linguafix status
systemctl --user status linguafix.service
journalctl --user -u linguafix.service -n 50 --no-pager
```

`linguafix status` should report that the daemon is running, the current layout,
and the active injector backend.

Run the built-in self-diagnosis to check permissions, devices, tools, the GNOME
version and the resolved backends at once:

```bash
linguafix doctor
```

The output is a table with a marker per check (`✅` pass, `⚠️` warning, `❌`
failure) and a hint for every check that did not pass. The command exits
non-zero when a check fails, so `install.sh` runs it as a final self-test.

## Ubuntu notes

Some package names differ between Debian and Ubuntu. `install.sh` installs the
APT packages one by one and skips any name that is not available in the current
repository, so a missing package never aborts the install:

- `python3-uinput` is present in Debian; on some Ubuntu releases it is not
  packaged. In that case the `python-uinput` dependency is installed into the
  bundled virtualenv instead (`pip install -e .` pulls it from PyPI), so the
  `uinput` backend still works.
- `wtype` and `g3kb-switch` may need a third-party repository on older Ubuntu
  releases. Without `wtype`, LinguaFix falls back to `xdotool` (X11) or
  `uinput`.

## Manual install

If you prefer to install by hand:

```bash
python3 -m venv ~/.local/share/linguafix/venv
~/.local/share/linguafix/venv/bin/pip install -e .
mkdir -p ~/.config/systemd/user
cp data/linguafix.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now linguafix.service
```

Then install the udev rule manually (it uses `uaccess`, so no group change is
needed):

```bash
sudo cp data/99-linguafix.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger
```

## Uninstalling

For a `.deb` install:

```bash
sudo apt remove --purge linguafix
```

For a source install:

```bash
bash uninstall.sh
```

Both stop and disable the service, remove the udev rule, the unit, the autostart
entry and the icon, and delete the per-user configuration and logs.
