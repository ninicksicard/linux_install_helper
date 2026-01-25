# app.py

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

from ui_helpers import apply_css
from window import InstallHelperWindow


class InstallHelperApplication(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id="local.install.helper.gtk4")

    def do_activate(self) -> None:
        apply_css()
        window = InstallHelperWindow(self)
        window.present()
