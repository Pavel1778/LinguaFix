"""About dialog."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from .. import __version__  # noqa: E402

REPOSITORY = "https://github.com/Pavel1778/LinguaFix"


def build_about_window(parent: Gtk.Window | None = None) -> Adw.AboutDialog:
    """Create the About dialog with version, links and credits."""
    dialog = Adw.AboutDialog(
        application_name="LinguaFix",
        application_icon="linguafix",
        version=__version__,
        developer_name="Pavel1778",
        license_type=Gtk.License.MIT_X11,
        website=REPOSITORY,
        issue_url=f"{REPOSITORY}/issues",
        comments=(
            "Автоматическое исправление текста, набранного не в той раскладке.\n"
            "Всё работает локально: ни одного сетевого запроса."
        ),
    )
    dialog.set_developers(["Pavel1778"])
    dialog.add_credit_section(
        "Идеи и вдохновение",
        ["g3kb-switch", "gswitch", "evdev", "niri-punto", "PolterType"],
    )
    return dialog
