"""
ui_helpers.py

UI helper utilities for GTK4 widgets and app-wide CSS styling.
"""

from __future__ import annotations

from typing import Set

import gi

gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, Gtk


def apply_css() -> None:
    css = """
    .card {
        border: 1px solid rgba(128, 128, 128, 0.35);
        border-radius: 12px;
        background-color: rgba(255, 255, 255, 0.03);
        padding: 0px;
    }

    .header-area {
        padding: 10px;
    }

    .body {
        padding: 10px;
        border-top: 1px solid rgba(128, 128, 128, 0.25);
    }

    .subsection {
        padding: 8px;
        border: 1px solid rgba(128, 128, 128, 0.20);
        border-radius: 10px;
        background-color: rgba(255, 255, 255, 0.02);
    }

    .subsection-header {
        padding: 2px;
    }

    .subsection-list {
        margin-top: 6px;
    }

    .output-card {
        border: 1px solid rgba(128, 128, 128, 0.35);
        border-radius: 12px;
        padding: 10px;
        background-color: rgba(255, 255, 255, 0.03);
    }

    .chevron {
        opacity: 0.75;
    }

    .muted {
        opacity: 0.75;
    }

    .search-row {
        border-bottom: 1px solid rgba(128, 128, 128, 0.20);
        padding: 6px;
    }

    /* Font size normalization: keep folded/unfolded sections visually consistent. */
    .card .header-area label,
    .card .header-area .card-name {
        min-width: 0px;
    }

    .card .header-area label,
    .card .body label,
    .card .body entry,
    .card .body textview,
    .card .body button,
    .card .body dropdown,
    .output-card label,
    .output-card entry,
    .output-card textview,
    .output-card button,
    .output-card dropdown {
        font-size: 12px;
    }

    /* Light radius on controls. */
    button {
        border-radius: 8px;
    }

    entry {
        border-radius: 8px;
    }
    """

    provider = Gtk.CssProvider()
    provider.load_from_data(css.encode("utf-8"))

    display = Gdk.Display.get_default()
    if display is None:
        return

    Gtk.StyleContext.add_provider_for_display(
        display,
        provider,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
    )


def clear_box_children(container: Gtk.Box) -> None:
    child = container.get_first_child()
    while child is not None:
        next_child = child.get_next_sibling()
        container.remove(child)
        child = next_child


def is_descendant_of_button(widget: Gtk.Widget | None) -> bool:
    current = widget
    while current is not None:
        if isinstance(current, Gtk.Button):
            return True
        current = current.get_parent()
    return False


def unique_preserve_order(values: list[str]) -> list[str]:
    seen: Set[str] = set()
    output_values: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        output_values.append(value)
    return output_values
