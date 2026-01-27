"""
package_card.py

Package card widget (foldable card with actions and foldable dependencies section).
"""

from __future__ import annotations

import threading
from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk

import helpers
from backend import build_command_line
from install_indicator_pill import InstallIndicatorPill
from models import PackageNode
from ui_helpers import clear_box_children, is_descendant_of_button


class PackageCard(Gtk.Frame):
    def __init__(
        self,
        node: PackageNode,
        depth: int,
        add_to_primary_callback: Callable[[PackageNode], None],
        remove_from_primary_callback: Callable[["PackageCard"], None] | None,
        ensure_dependencies_callback: Callable[[PackageNode], None],
        run_command_callback: Callable[[str], None],
    ) -> None:
        super().__init__()
        self.node = node
        self.depth = depth
        self.add_to_primary_callback = add_to_primary_callback
        self.remove_from_primary_callback = remove_from_primary_callback
        self.ensure_dependencies_callback = ensure_dependencies_callback
        self.run_command_callback = run_command_callback

        self._deps_loading = False
        self._suppress_version_handler = False

        self.add_css_class("card")

        self.set_margin_start(depth * 18 + 8)
        self.set_margin_end(8)
        self.set_margin_top(6)
        self.set_margin_bottom(6)

        self.grid = Gtk.Grid()
        self.set_child(self.grid)

        # Left indicator spans header + body rows.
        self.install_indicator = InstallIndicatorPill(installed=self.node.installed)
        self.grid.attach(self.install_indicator, 0, 0, 1, 2)

        # Header row (clickable to toggle).
        self.header_area = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.header_area.add_css_class("header-area")
        self.header_area.set_hexpand(True)
        self.grid.attach(self.header_area, 1, 0, 1, 1)

        self.chevron_label = Gtk.Label(label=">", xalign=0.0)
        self.chevron_label.add_css_class("chevron")
        self.header_area.append(self.chevron_label)

        self.name_label = Gtk.Label(label=self.node.name, xalign=0.0)
        self.name_label.set_hexpand(True)
        self.header_area.append(self.name_label)

        self.add_button_folded = Gtk.Button(label="Add")
        self.add_button_folded.set_visible(self.node.is_dependency)
        self.add_button_folded.connect("clicked", self._on_add_to_primary)
        self.header_area.append(self.add_button_folded)

        self.remove_button = Gtk.Button(label="-")
        self.remove_button.set_visible(not self.node.is_dependency)
        self.remove_button.connect("clicked", self._on_remove_from_primary)
        self.header_area.append(self.remove_button)

        # Body (revealer).
        self.body_revealer = Gtk.Revealer()
        self.body_revealer.set_reveal_child(False)
        self.grid.attach(self.body_revealer, 1, 1, 1, 1)

        self.body_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.body_container.add_css_class("body")
        self.body_revealer.set_child(self.body_container)

        self._build_dependencies_section()
        self._build_details_section()

        self._sync_header_text()
        self._sync_versions_dropdown()

        self._install_click_controllers()

    def gather_self_and_descendants(self) -> list["PackageCard"]:
        cards: list[PackageCard] = [self]

        child = self.dependencies_list_container.get_first_child()
        while child is not None:
            next_child = child.get_next_sibling()

            if isinstance(child, PackageCard):
                cards.extend(child.gather_self_and_descendants())

            child = next_child

        return cards

    def apply_installed_status(self, installed_version_value: str) -> None:
        previous_installed_version = self.node.installed_version

        self.node.installed_version = installed_version_value.strip()
        self.node.installed = bool(self.node.installed_version)

        if self.node.installed:
            # Show installed version as the selected dropdown value.
            self.node.selected_version = self.node.installed_version
            if self.node.installed_version and self.node.installed_version not in self.node.versions:
                self.node.versions = self.node.versions + [self.node.installed_version]
        else:
            # If we were previously selecting the old installed version, fall back.
            if previous_installed_version and self.node.selected_version == previous_installed_version:
                self.node.selected_version = "default"

        self._sync_header_text()
        self._sync_versions_dropdown()

    def _install_click_controllers(self) -> None:
        self.header_click = Gtk.GestureClick()
        self.header_click.set_button(0)
        self.header_click.connect("pressed", self._on_header_pressed)
        self.header_area.add_controller(self.header_click)

        self.indicator_click = Gtk.GestureClick()
        self.indicator_click.set_button(0)
        self.indicator_click.connect("pressed", self._on_indicator_pressed)
        self.install_indicator.add_controller(self.indicator_click)

        self.deps_header_click = Gtk.GestureClick()
        self.deps_header_click.set_button(0)
        self.deps_header_click.connect("pressed", self._on_deps_header_pressed)
        self.dependencies_header.add_controller(self.deps_header_click)

    def _build_dependencies_section(self) -> None:
        self.dependencies_section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.dependencies_section.add_css_class("subsection")
        self.body_container.append(self.dependencies_section)

        self.dependencies_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.dependencies_header.add_css_class("subsection-header")
        self.dependencies_section.append(self.dependencies_header)

        self.deps_chevron_label = Gtk.Label(label=">", xalign=0.0)
        self.deps_chevron_label.add_css_class("chevron")
        self.dependencies_header.append(self.deps_chevron_label)

        self.dependencies_label = Gtk.Label(label="Dependencies", xalign=0.0)
        self.dependencies_label.set_hexpand(True)
        self.dependencies_header.append(self.dependencies_label)

        self.dependencies_filter_dropdown = Gtk.DropDown(
            model=Gtk.StringList.new(["all", "installed", "not installed"])
        )
        self.dependencies_filter_dropdown.connect("notify::selected", self._on_dependency_filter_selected)
        self.dependencies_header.append(self.dependencies_filter_dropdown)

        self.add_listed_button = Gtk.Button(label="Add listed")
        self.add_listed_button.connect("clicked", self._on_add_listed_dependencies)
        self.dependencies_header.append(self.add_listed_button)

        self.refresh_dependencies_button = Gtk.Button(label="Refresh")
        self.refresh_dependencies_button.connect("clicked", self._on_refresh_dependencies)
        self.dependencies_header.append(self.refresh_dependencies_button)

        self.deps_revealer = Gtk.Revealer()
        self.deps_revealer.set_reveal_child(False)
        self.dependencies_section.append(self.deps_revealer)

        self.dependencies_list_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.dependencies_list_container.add_css_class("subsection-list")
        self.deps_revealer.set_child(self.dependencies_list_container)

        self._rebuild_dependencies_list()

    def _build_details_section(self) -> None:
        self.details_section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.details_section.add_css_class("subsection")
        self.body_container.append(self.details_section)

        command_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.details_section.append(command_row)

        self.command_entry = Gtk.Entry()
        self.command_entry.set_hexpand(True)
        self.command_entry.set_text(self.node.command_line)
        self.command_entry.connect("changed", self._on_command_changed)
        command_row.append(self.command_entry)

        run_button = Gtk.Button(label="Run")
        run_button.connect("clicked", self._on_run_command)
        command_row.append(run_button)

        self.add_button_unfolded = Gtk.Button(label="Add")
        self.add_button_unfolded.set_visible(self.node.is_dependency)
        self.add_button_unfolded.connect("clicked", self._on_add_to_primary)
        command_row.append(self.add_button_unfolded)

        actions_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.details_section.append(actions_row)

        install_button = Gtk.Button(label="Install")
        install_button.connect("clicked", self._on_install)
        actions_row.append(install_button)

        remove_button = Gtk.Button(label="Remove")
        remove_button.connect("clicked", self._on_remove)
        actions_row.append(remove_button)

        reinstall_button = Gtk.Button(label="Reinstall")
        reinstall_button.connect("clicked", self._on_reinstall)
        actions_row.append(reinstall_button)

        spacer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        spacer.set_hexpand(True)
        actions_row.append(spacer)

        self.versions_dropdown = Gtk.DropDown(model=Gtk.StringList.new(["default", "latest"]))
        self.versions_dropdown.connect("notify::selected", self._on_version_selected)
        actions_row.append(self.versions_dropdown)

    def _rebuild_dependencies_list(self) -> None:
        clear_box_children(self.dependencies_list_container)

        dependencies = self._filtered_dependencies()
        total_count = len(self.node.dependencies)
        count = len(dependencies)
        filter_mode = self._current_dependency_filter()

        if count == 0:
            placeholder_label = "(no dependencies)"
            if total_count and filter_mode != "all":
                placeholder_label = "(no matching dependencies)"
            placeholder = Gtk.Label(label=placeholder_label, xalign=0.0)
            placeholder.add_css_class("muted")
            self.dependencies_list_container.append(placeholder)
        else:
            for dependency_node in dependencies:
                dependency_card = PackageCard(
                    node=dependency_node,
                    depth=self.depth + 1,
                    add_to_primary_callback=self.add_to_primary_callback,
                    remove_from_primary_callback=self.remove_from_primary_callback,
                    ensure_dependencies_callback=self.ensure_dependencies_callback,
                    run_command_callback=self.run_command_callback,
                )
                self.dependencies_list_container.append(dependency_card)

        if self._deps_loading:
            self.dependencies_label.set_label("Dependencies (loading...)")
        elif self.node.dependencies_loaded:
            if filter_mode == "all":
                self.dependencies_label.set_label(f"Dependencies ({count})")
            else:
                self.dependencies_label.set_label(f"Dependencies ({count} of {total_count})")
        else:
            self.dependencies_label.set_label("Dependencies")

    def _current_dependency_filter(self) -> str:
        selected_item = self.dependencies_filter_dropdown.get_selected_item()
        if selected_item is None:
            return "all"
        return selected_item.get_string()

    def _filtered_dependencies(self) -> list[PackageNode]:
        filter_mode = self._current_dependency_filter()
        if filter_mode == "installed":
            return [dependency for dependency in self.node.dependencies if dependency.installed]
        if filter_mode == "not installed":
            return [dependency for dependency in self.node.dependencies if not dependency.installed]
        return list(self.node.dependencies)

    def _sync_header_text(self) -> None:
        text = self.node.name
        if self.node.installed_version:
            text = f"{text} ({self.node.installed_version})"
        self.name_label.set_label(text)
        self.install_indicator.set_installed(self.node.installed)

    def _sync_versions_dropdown(self) -> None:
        if self.node.selected_version not in self.node.versions:
            self.node.versions = self.node.versions + [self.node.selected_version]

        model = Gtk.StringList.new(self.node.versions)

        self._suppress_version_handler = True
        try:
            self.versions_dropdown.set_model(model)

            for index in range(model.get_n_items()):
                item = model.get_item(index)
                if item is None:
                    continue
                if item.get_string() == self.node.selected_version:
                    self.versions_dropdown.set_selected(index)
                    return

            self.versions_dropdown.set_selected(0)
        finally:
            self._suppress_version_handler = False

    def _start_dependencies_load(self, force_reload: bool) -> None:
        if self._deps_loading:
            return

        if not force_reload and self.node.dependencies_loaded:
            return

        self._deps_loading = True
        self.node.dependencies_loaded = False
        self._rebuild_dependencies_list()

        def worker() -> None:
            self.ensure_dependencies_callback(self.node)

            def apply_results() -> bool:
                self._deps_loading = False
                self.node.dependencies_loaded = True
                self._rebuild_dependencies_list()
                return False

            GLib.idle_add(apply_results)

        threading.Thread(target=worker, daemon=True).start()

    def _toggle_body(self) -> None:
        is_open = self.body_revealer.get_reveal_child()
        next_state_open = not is_open
        self.body_revealer.set_reveal_child(next_state_open)
        self.chevron_label.set_label("v" if next_state_open else ">")

        if next_state_open:
            self._start_dependencies_load(force_reload=False)

    def _toggle_dependencies(self) -> None:
        is_open = self.deps_revealer.get_reveal_child()
        next_state_open = not is_open
        self.deps_revealer.set_reveal_child(next_state_open)
        self.deps_chevron_label.set_label("v" if next_state_open else ">")

        if next_state_open:
            self._start_dependencies_load(force_reload=False)

    def _on_header_pressed(self, _gesture: Gtk.GestureClick, _n_press: int, x: float, y: float) -> None:
        picked = self.header_area.pick(x, y, Gtk.PickFlags.DEFAULT)
        if is_descendant_of_button(picked):
            return
        self._toggle_body()

    def _on_indicator_pressed(self, _gesture: Gtk.GestureClick, _n_press: int, _x: float, _y: float) -> None:
        self._toggle_body()

    def _on_deps_header_pressed(self, _gesture: Gtk.GestureClick, _n_press: int, x: float, y: float) -> None:
        picked = self.dependencies_header.pick(x, y, Gtk.PickFlags.DEFAULT)
        if is_descendant_of_button(picked):
            return
        self._toggle_dependencies()

    def _on_dependency_filter_selected(self, _dropdown: Gtk.DropDown, _param_spec) -> None:
        self._rebuild_dependencies_list()

    def _on_add_listed_dependencies(self, _button: Gtk.Button) -> None:
        if self._deps_loading or not self.node.dependencies_loaded:
            self._start_dependencies_load(force_reload=False)
            return

        for dependency_node in self._filtered_dependencies():
            self.add_to_primary_callback(dependency_node)

    def _on_refresh_dependencies(self, _button: Gtk.Button) -> None:
        self._start_dependencies_load(force_reload=True)

    def _on_add_to_primary(self, _button: Gtk.Button) -> None:
        self.add_to_primary_callback(self.node)

    def _on_remove_from_primary(self, _button: Gtk.Button) -> None:
        if self.remove_from_primary_callback is None:
            return
        self.remove_from_primary_callback(self)

    def _on_command_changed(self, entry: Gtk.Entry) -> None:
        self.node.command_line = entry.get_text()

    def _on_run_command(self, _button: Gtk.Button) -> None:
        self.run_command_callback(self.node.command_line)

    def _on_version_selected(self, dropdown: Gtk.DropDown, _param_spec) -> None:
        if self._suppress_version_handler:
            return

        selected_item = dropdown.get_selected_item()
        if selected_item is None:
            return

        self.node.selected_version = selected_item.get_string()
        self.node.command_line = build_command_line(
            self.node.installer,
            self.node.last_action,
            self.node.name,
            self.node.selected_version,
        )
        self.command_entry.set_text(self.node.command_line)

    def _refresh_installed_state(self) -> None:
        self.node.installed_version = helpers.installed_version(self.node.name)
        self.node.installed = bool(self.node.installed_version)

        if self.node.installed:
            self.node.selected_version = self.node.installed_version

        self._sync_header_text()
        self._sync_versions_dropdown()

    def _on_install(self, _button: Gtk.Button) -> None:
        self.node.last_action = "install"
        self.node.command_line = build_command_line(self.node.installer, "install", self.node.name, self.node.selected_version)
        self.command_entry.set_text(self.node.command_line)
        self._refresh_installed_state()

    def _on_remove(self, _button: Gtk.Button) -> None:
        self.node.last_action = "remove"
        self.node.command_line = build_command_line(self.node.installer, "remove", self.node.name, self.node.selected_version)
        self.command_entry.set_text(self.node.command_line)
        self._refresh_installed_state()

    def _on_reinstall(self, _button: Gtk.Button) -> None:
        self.node.last_action = "reinstall"
        self.node.command_line = build_command_line(self.node.installer, "reinstall", self.node.name, self.node.selected_version)
        self.command_entry.set_text(self.node.command_line)
        self._refresh_installed_state()
