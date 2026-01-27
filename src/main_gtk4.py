# main_gtk4.py

from __future__ import annotations

import os

# Set early, before importing Gtk, to avoid the at-spi registry warning on some setups.
os.environ.setdefault("NO_AT_BRIDGE", "1")
os.environ.setdefault("GTK_A11Y", "none")

from app import InstallHelperApplication


def main() -> None:
    application = InstallHelperApplication()
    application.run()


if __name__ == "__main__":
    main()
