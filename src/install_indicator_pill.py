# install_indicator_pill.py

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk


class InstallIndicatorPill(Gtk.DrawingArea):
    def __init__(self, installed: bool) -> None:
        super().__init__()
        self._installed = installed

        self.set_content_width(10)
        self.set_hexpand(False)
        self.set_valign(Gtk.Align.FILL)

        self.set_margin_start(10)
        self.set_margin_top(10)
        self.set_margin_bottom(10)
        self.set_margin_end(0)

        self.set_draw_func(self._draw)

    def set_installed(self, installed: bool) -> None:
        self._installed = installed
        self.queue_draw()

    def _draw(self, _area: Gtk.DrawingArea, cairo_context, width: int, height: int) -> None:
        if self._installed:
            red, green, blue, alpha = 0.0, 0.7, 0.0, 1.0
        else:
            red, green, blue, alpha = 0.45, 0.45, 0.45, 1.0

        # keep some breathing room top/bottom
        padding_y = 4.0
        pill_x = 0.0
        pill_y = padding_y
        pill_width = float(width)
        pill_height = max(2.0, float(height) - 2.0 * padding_y)
        radius = pill_width / 2.0

        cairo_context.set_source_rgba(red, green, blue, alpha)

        cairo_context.new_path()
        cairo_context.arc(pill_x + radius, pill_y + radius, radius, 3.141592653589793, 4.71238898038469)
        cairo_context.arc(pill_x + pill_width - radius, pill_y + radius, radius, 4.71238898038469, 0.0)
        cairo_context.arc(pill_x + pill_width - radius, pill_y + pill_height - radius, radius, 0.0, 1.5707963267948966)
        cairo_context.arc(pill_x + radius, pill_y + pill_height - radius, radius, 1.5707963267948966, 3.141592653589793)
        cairo_context.close_path()
        cairo_context.fill()
