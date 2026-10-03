# Installation

LinguaFix targets Debian 12+ / Ubuntu 22.04+ with GNOME 42+ on either X11 or
Wayland. Python 3.10 or newer is required.

## Quick install

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
7. Adds your user to the `input` group.
8. Installs the systemd user service `~/.config/systemd/user/linguafix.service`.
9. Installs the XDG autostart entry
   `~/.config/autostart/linguafix.desktop`.
10. Copies the icon to
    `~/.local/share/icons/hicolor/scalable/apps/linguafix.svg`.
11. Enables and starts the service.
12. Sends a desktop notification.

## Log out and back in

Adding your user to the `input` group only takes effect after a **full logout
and login** (a new shell is not enough). Until then the daemon cannot open
`/dev/input/event*` and will report a permission error.

## Verifying the install

```bash
linguafix status
systemctl --user status linguafix.service
journalctl --user -u linguafix.service -n 50 --no-pager
```

`linguafix status` should report that the daemon is running, the current layout,
and the active injector backend.

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

Then install the udev rule and add yourself to the `input` group manually:

```bash
sudo cp data/99-linguafix.rules /etc/udev/rules.d/
sudo usermod -aG input "$USER"
```

## Uninstalling

```bash
bash uninstall.sh
```

This stops and disables the service, removes the autostart entry and the icon,
and (with confirmation) deletes the virtual environment and configuration.
