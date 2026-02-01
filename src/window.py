"""
window.py

Main GTK4 window: repo search panel, primary package list panel, and output log.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Set

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Pango", "1.0")
from gi.repository import GLib, Gtk, Pango

import helpers
from backend import (
    build_command_line,
    create_node,
    detect_default_installer,
    list_available_installers,
    list_dependencies,
    list_installed_packages,
    normalize_target_name,
    parse_add_input,
    search_repo_online,
)
from models import PackageNode
from package_card import PackageCard
from ui_helpers import clear_box_children, close_dropdown_popover, unique_preserve_order


def ensure_dependencies_for_node(node: PackageNode) -> None:
    node.dependencies = []

    dependency_names = list_dependencies(node.installer, node.name)
    dependency_names = [name for name in dependency_names if name and name != node.name]
    dependency_names = unique_preserve_order(dependency_names)

    for dependency_name in dependency_names:
        dependency_node = create_node(node.installer, dependency_name, is_dependency=True)
        node.dependencies.append(dependency_node)


class InstallHelperWindow(Gtk.ApplicationWindow):
    def __init__(self, application: Gtk.Application) -> None:
        super().__init__(application=application)
        self.set_title("Linux Install Helper (GTK4)")
        self.set_default_size(1200, 760)

        self.default_installer = detect_default_installer()
        self.available_installers = list_available_installers()
        if self.default_installer not in self.available_installers:
            self.available_installers.insert(0, self.default_installer)
        self.primary_names: Set[str] = set()
        self.search_results: list[str] = []

        self._search_cancel_event: threading.Event | None = None
        self._search_job_id = 0
        self._remove_dependencies_cancel_event: threading.Event | None = None
        self._remove_dependencies_job_id = 0

        self._refresh_status_thread_running = False
        self._add_from_file_dialog: Gtk.FileChooserNative | None = None

        root_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        root_box.set_margin_top(10)
        root_box.set_margin_bottom(10)
        root_box.set_margin_start(10)
        root_box.set_margin_end(10)
        self.set_child(root_box)

        top_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        root_box.append(top_bar)

        title_label = Gtk.Label(label="Install Helper", xalign=0.0)
        title_label.set_hexpand(True)
        top_bar.append(title_label)

        installer_label = Gtk.Label(label="Installer", xalign=1.0)
        installer_label.add_css_class("muted")
        top_bar.append(installer_label)

        installer_model = Gtk.StringList.new(self.available_installers)
        self.installer_dropdown = Gtk.DropDown(model=installer_model)
        self.installer_dropdown.add_css_class("flat")
        self.installer_dropdown.connect("notify::selected", self._on_default_installer_selected)
        top_bar.append(self.installer_dropdown)

        for index, installer in enumerate(self.available_installers):
            if installer == self.default_installer:
                self.installer_dropdown.set_selected(index)
                break

        paned = Gtk.Paned.new(Gtk.Orientation.HORIZONTAL)
        paned.set_wide_handle(True)
        root_box.append(paned)

        left_panel = self._build_search_panel()
        paned.set_start_child(left_panel)

        right_panel = self._build_primary_panel()
        paned.set_end_child(right_panel)

        paned.set_position(380)

        self.queue_add_primary_from_text("copyq")
        self.queue_add_primary_from_text("ripgrep")

    def _build_search_panel(self) -> Gtk.Widget:
        frame = Gtk.Frame()
        frame.add_css_class("output-card")

        container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        frame.set_child(container)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        container.append(header)

        label = Gtk.Label(label="Search", xalign=0.0)
        label.set_hexpand(True)
        header.append(label)

        self.search_status = Gtk.Label(label="", xalign=1.0)
        self.search_status.add_css_class("muted")
        header.append(self.search_status)

        search_menu_button = Gtk.MenuButton()
        search_menu_button.set_icon_name("open-menu-symbolic")
        search_menu_button.add_css_class("flat")
        header.append(search_menu_button)

        search_menu_popover = Gtk.Popover()
        search_menu_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        search_menu_box.add_css_class("menu-popover")
        search_menu_box.set_margin_top(6)
        search_menu_box.set_margin_bottom(6)
        search_menu_box.set_margin_start(6)
        search_menu_box.set_margin_end(6)

        export_search_list_button = Gtk.Button(label="Export list")
        export_search_list_button.connect("clicked", self._on_export_search_list_clicked, search_menu_popover)
        search_menu_box.append(export_search_list_button)

        add_all_button = Gtk.Button(label="Add all")
        add_all_button.connect("clicked", self._on_add_all_search_results_clicked, search_menu_popover)
        search_menu_box.append(add_all_button)

        search_menu_popover.set_child(search_menu_box)
        search_menu_button.set_popover(search_menu_popover)

        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        container.append(controls)

        self.search_entry = Gtk.Entry()
        self.search_entry.set_placeholder_text("Search available packages (repo)")
        self.search_entry.set_hexpand(True)
        self.search_entry.connect("activate", self._on_search_activate)
        controls.append(self.search_entry)

        self.installed_only_check = Gtk.CheckButton(label="Installed")
        controls.append(self.installed_only_check)

        self.search_button = Gtk.Button(label="Search")
        self.search_button.connect("clicked", self._on_search_clicked)
        controls.append(self.search_button)

        self.search_cancel_button = Gtk.Button(label="Cancel")
        self.search_cancel_button.set_visible(False)
        self.search_cancel_button.connect("clicked", self._on_search_cancel_clicked)
        controls.append(self.search_cancel_button)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_overlay_scrolling(True)
        scrolled.set_vexpand(True)
        container.append(scrolled)

        self.search_list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        scrolled.set_child(self.search_list_box)

        return frame

    def _on_default_installer_selected(self, dropdown: Gtk.DropDown, _param_spec) -> None:
        selected_item = dropdown.get_selected_item()
        if selected_item is None:
            return
        self.default_installer = selected_item.get_string()
        self._update_primary_installer()
        close_dropdown_popover(dropdown)

    def _update_primary_installer(self) -> None:
        cards = self._collect_package_cards_in_primary_panel()
        for card in cards:
            card.update_installer(self.default_installer)

    def _build_primary_panel(self) -> Gtk.Widget:
        container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)

        add_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        container.append(add_row)

        self.add_entry = Gtk.Entry()
        self.add_entry.set_placeholder_text("Add package name OR paste install command")
        self.add_entry.set_hexpand(True)
        self.add_entry.connect("activate", self._on_add_primary_activate)
        add_row.append(self.add_entry)

        add_button = Gtk.Button(label="Add")
        add_button.connect("clicked", self._on_add_primary_clicked)
        add_row.append(add_button)

        add_from_file_button = Gtk.Button(label="Add from file")
        add_from_file_button.connect("clicked", self._on_add_primary_from_file_clicked)
        add_row.append(add_from_file_button)

        list_frame = Gtk.Frame()
        list_frame.add_css_class("output-card")
        container.append(list_frame)

        list_root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        list_frame.set_child(list_root)

        list_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        list_root.append(list_header)

        list_title = Gtk.Label(label="Primary Packages", xalign=0.0)
        list_title.set_hexpand(True)
        list_header.append(list_title)

        self.refresh_all_status_button = Gtk.Button(label="Refresh status")
        self.refresh_all_status_button.connect("clicked", self._on_refresh_all_status_clicked)
        list_header.append(self.refresh_all_status_button)

        primary_menu_button = Gtk.MenuButton()
        primary_menu_button.set_icon_name("open-menu-symbolic")
        primary_menu_button.add_css_class("flat")
        list_header.append(primary_menu_button)

        primary_menu_popover = Gtk.Popover()
        primary_menu_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        primary_menu_box.add_css_class("menu-popover")
        primary_menu_box.set_margin_top(6)
        primary_menu_box.set_margin_bottom(6)
        primary_menu_box.set_margin_start(6)
        primary_menu_box.set_margin_end(6)

        self.primary_filter_dropdown = Gtk.DropDown(
            model=Gtk.StringList.new(["all", "installed", "not installed"])
        )
        self.primary_filter_dropdown.connect("notify::selected", self._on_primary_filter_selected)
        primary_menu_box.append(self.primary_filter_dropdown)

        install_all_button = Gtk.Button(label="Install all")
        install_all_button.connect("clicked", self._on_install_all_primary_clicked, primary_menu_popover)
        primary_menu_box.append(install_all_button)

        export_primary_list_button = Gtk.Button(label="Export list")
        export_primary_list_button.connect("clicked", self._on_export_primary_list_clicked, primary_menu_popover)
        primary_menu_box.append(export_primary_list_button)

        remove_all_button = Gtk.Button(label="Remove all")
        remove_all_button.connect("clicked", self._on_remove_all_primary_clicked, primary_menu_popover)
        primary_menu_box.append(remove_all_button)

        remove_dependencies_button = Gtk.Button(label="Remove dependencies")
        remove_dependencies_button.connect("clicked", self._on_remove_dependencies_clicked, primary_menu_popover)
        primary_menu_box.append(remove_dependencies_button)

        primary_menu_popover.set_child(primary_menu_box)
        primary_menu_button.set_popover(primary_menu_popover)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_overlay_scrolling(True)
        scrolled.set_vexpand(True)
        list_root.append(scrolled)

        self.primary_list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        scrolled.set_child(self.primary_list_box)

        self.output_expander = Gtk.Expander(label="Output")
        self.output_expander.set_expanded(False)
        container.append(self.output_expander)

        output_frame = Gtk.Frame()
        output_frame.add_css_class("output-card")
        self.output_expander.set_child(output_frame)

        output_root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        output_frame.set_child(output_root)

        output_controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        output_root.append(output_controls)

        clear_button = Gtk.Button(label="Clear")
        clear_button.connect("clicked", self._on_clear_log)
        output_controls.append(clear_button)

        spacer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        spacer.set_hexpand(True)
        output_controls.append(spacer)

        self.status_label = Gtk.Label(label="0 item(s)", xalign=1.0)
        output_controls.append(self.status_label)

        log_scrolled = Gtk.ScrolledWindow()
        log_scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        log_scrolled.set_min_content_height(140)
        output_root.append(log_scrolled)

        self.log_view = Gtk.TextView()
        self.log_view.set_editable(False)
        self.log_view.set_cursor_visible(False)
        log_scrolled.set_child(self.log_view)

        return container

    def append_log(self, text: str) -> None:
        buffer = self.log_view.get_buffer()
        end_iter = buffer.get_end_iter()
        buffer.insert(end_iter, text)

    def _strip_simple_sudo_prefix(self, command: str) -> tuple[bool, str]:
        command_stripped = command.strip()
        if not command_stripped.startswith("sudo "):
            return False, command_stripped
        return True, command_stripped[len("sudo ") :].strip()

    def _needs_shell(self, command: str) -> bool:
        operators = ["|", ">", "<", "&&", "||", ";", "$(", "`"]
        return any(op in command for op in operators)

    def _maybe_inject_yes_flag_for_dnf(self, tokens: list[str]) -> list[str]:
        if not tokens:
            return tokens

        if tokens[0] not in {"dnf", "dnf5", "yum", "/usr/bin/dnf", "/usr/bin/dnf5", "/usr/bin/yum"}:
            return tokens

        if len(tokens) < 2:
            return tokens

        action = tokens[1]
        if action not in {"install", "remove", "reinstall", "upgrade", "downgrade"}:
            return tokens

        if "-y" in tokens or "--assumeyes" in tokens:
            return tokens

        return tokens[:2] + ["-y"] + tokens[2:]

    def _normalize_program_path(self, tokens: list[str]) -> list[str]:
        if not tokens:
            return tokens

        mapping = {
            "dnf": "/usr/bin/dnf",
            "dnf5": "/usr/bin/dnf5",
            "yum": "/usr/bin/yum",
            "rpm": "/usr/bin/rpm",
            "apt": "/usr/bin/apt",
            "apt-get": "/usr/bin/apt-get",
            "nala": "/usr/bin/nala",
            "pacman": "/usr/bin/pacman",
            "zypper": "/usr/bin/zypper",
        }
        if tokens[0] in mapping:
            tokens = [mapping[tokens[0]]] + tokens[1:]
        return tokens

    def _run_privileged(self, non_sudo_command: str) -> tuple[int, str, str]:
        non_sudo_command_stripped = non_sudo_command.strip()
        if not non_sudo_command_stripped:
            return 1, "", "Empty command"

        if self._needs_shell(non_sudo_command_stripped):
            args = ["pkexec", "/bin/bash", "-lc", non_sudo_command_stripped]
            completed = subprocess.run(args, capture_output=True, text=True)
            return completed.returncode, completed.stdout, completed.stderr

        tokens = shlex.split(non_sudo_command_stripped)
        tokens = self._normalize_program_path(tokens)
        tokens = self._maybe_inject_yes_flag_for_dnf(tokens)

        completed = subprocess.run(["pkexec"] + tokens, capture_output=True, text=True)
        return completed.returncode, completed.stdout, completed.stderr

    def run_and_log(self, command: str) -> None:
        command_stripped = command.strip()
        if not command_stripped:
            return

        self.output_expander.set_expanded(True)
        self.append_log(f"$ {command_stripped}\n")

        def worker() -> None:
            uses_sudo, non_sudo_command = self._strip_simple_sudo_prefix(command_stripped)

            if uses_sudo:
                return_code, standard_output, standard_error = self._run_privileged(non_sudo_command)
            else:
                return_code, standard_output, standard_error = helpers.run_bash(command_stripped)

            def apply_results() -> bool:
                if standard_output:
                    self.append_log(standard_output if standard_output.endswith("\n") else standard_output + "\n")
                if standard_error:
                    self.append_log(standard_error if standard_error.endswith("\n") else standard_error + "\n")
                self.append_log(f"[exit={return_code}]\n\n")
                return False

            GLib.idle_add(apply_results)

        threading.Thread(target=worker, daemon=True).start()

    def _collect_package_cards_in_primary_panel(self) -> list[PackageCard]:
        cards: list[PackageCard] = []

        child = self.primary_list_box.get_first_child()
        while child is not None:
            next_child = child.get_next_sibling()

            if isinstance(child, PackageCard):
                cards.extend(child.gather_self_and_descendants())

            child = next_child

        return cards

    def _collect_primary_list_names(self) -> list[str]:
        names: list[str] = []
        child = self.primary_list_box.get_first_child()
        while child is not None:
            next_child = child.get_next_sibling()

            if isinstance(child, PackageCard):
                names.append(child.node.name)

            child = next_child

        return names

    def _collect_primary_cards(self) -> list[PackageCard]:
        cards: list[PackageCard] = []
        child = self.primary_list_box.get_first_child()
        while child is not None:
            next_child = child.get_next_sibling()

            if isinstance(child, PackageCard):
                cards.append(child)

            child = next_child

        return cards

    def _current_primary_filter(self) -> str:
        selected_item = self.primary_filter_dropdown.get_selected_item()
        if selected_item is None:
            return "all"
        return selected_item.get_string()

    def _apply_primary_filter(self) -> None:
        filter_mode = self._current_primary_filter()
        for card in self._collect_primary_cards():
            visible = True
            if filter_mode == "installed":
                visible = card.node.installed
            elif filter_mode == "not installed":
                visible = not card.node.installed
            card.set_visible(visible)

    def _open_export_dialog(self, items: list[str], suggested_name: str) -> None:
        if not items:
            self.append_log("[export] No items to export.\n")
            return

        dialog = Gtk.FileChooserNative.new(
            "Export list",
            self,
            Gtk.FileChooserAction.SAVE,
            "_Save",
            "_Cancel",
        )
        dialog.set_current_name(suggested_name)
        dialog.connect("response", self._on_export_list_response, items)
        dialog.show()

    def _on_export_list_response(
        self,
        dialog: Gtk.FileChooserNative,
        response: int,
        items: list[str],
    ) -> None:
        if response != Gtk.ResponseType.ACCEPT:
            dialog.destroy()
            return

        selected_file = dialog.get_file()
        dialog.destroy()
        if selected_file is None:
            self.append_log("[export] No file selected.\n")
            return

        file_path = selected_file.get_path()
        if not file_path:
            self.append_log("[export] No file path available.\n")
            return

        parent_directory = os.path.dirname(file_path) or "."
        if not os.path.isdir(parent_directory) or not os.access(parent_directory, os.W_OK):
            self.append_log(f"[export] Cannot write to: {file_path}\n")
            return

        with open(file_path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(items))
            handle.write("\n")
        self.append_log(f"[export] Saved: {file_path}\n")

    def _on_refresh_all_status_clicked(self, _button: Gtk.Button) -> None:
        if self._refresh_status_thread_running:
            return

        cards = self._collect_package_cards_in_primary_panel()
        if not cards:
            return

        self._refresh_status_thread_running = True
        self.refresh_all_status_button.set_sensitive(False)
        self.refresh_all_status_button.set_label("Refreshing...")

        def worker() -> None:
            updates: list[tuple[PackageCard, str]] = []
            for card in cards:
                installed_version_value = helpers.installed_version(card.node.name)
                updates.append((card, installed_version_value))

            def apply_updates() -> bool:
                for card, installed_version_value in updates:
                    card.apply_installed_status(installed_version_value)

                self._apply_primary_filter()
                self._refresh_status_thread_running = False
                self.refresh_all_status_button.set_sensitive(True)
                self.refresh_all_status_button.set_label("Refresh status")
                return False

            GLib.idle_add(apply_updates)

        threading.Thread(target=worker, daemon=True).start()

    def queue_add_primary_from_text(self, text: str) -> None:
        user_text = text.strip()
        if not user_text:
            return

        def worker() -> None:
            installer, target, original_command = parse_add_input(user_text, self.default_installer)
            if not target:
                return

            base_name = normalize_target_name(target)
            node = create_node(installer, target, is_dependency=False)
            if original_command:
                node.command_line = original_command

            def apply_node() -> bool:
                if base_name in self.primary_names:
                    return False

                self.primary_names.add(node.name)

                card = PackageCard(
                    node=node,
                    depth=0,
                    add_to_primary_callback=self.add_dependency_to_primary,
                    remove_from_primary_callback=self.remove_primary_card,
                    ensure_dependencies_callback=ensure_dependencies_for_node,
                    run_command_callback=self.run_and_log,
                )
                self.primary_list_box.append(card)
                self._apply_primary_filter()
                self._update_status()
                return False

            GLib.idle_add(apply_node)

        threading.Thread(target=worker, daemon=True).start()

    def add_dependency_to_primary(self, node: PackageNode) -> None:
        if node.name in self.primary_names:
            return
        self.queue_add_primary_from_text(node.name)

    def remove_primary_card(self, card: PackageCard) -> None:
        if card.node.name not in self.primary_names:
            return
        self.primary_names.remove(card.node.name)
        self.primary_list_box.remove(card)
        self._update_status()

    def _rebuild_search_results(self) -> None:
        clear_box_children(self.search_list_box)

        if not self.search_results:
            placeholder = Gtk.Label(label="(no results)", xalign=0.0)
            placeholder.add_css_class("muted")
            placeholder.set_margin_top(6)
            placeholder.set_margin_start(6)
            self.search_list_box.append(placeholder)
            return

        for package_name in self.search_results:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            row.add_css_class("search-row")
            row.set_hexpand(True)

            label = Gtk.Label(label=package_name, xalign=0.0)
            label.set_ellipsize(Pango.EllipsizeMode.END)
            label.set_single_line_mode(True)
            label.set_hexpand(True)
            row.append(label)

            add_button = Gtk.Button(label="+")
            add_button.connect("clicked", self._on_search_add_clicked, package_name)
            row.append(add_button)

            self.search_list_box.append(row)

    def _cancel_previous_search(self) -> None:
        if self._search_cancel_event is not None:
            self._search_cancel_event.set()
            self._search_cancel_event = None

    def _search_thread_worker(
        self,
        job_id: int,
        query: str,
        installed_only: bool,
        cancel_event: threading.Event | None,
    ) -> None:
        query_stripped = query.strip()

        if installed_only:
            if cancel_event is None:
                cancel_event = threading.Event()

            results, canceled = list_installed_packages(self.default_installer, cancel_event, query_stripped)
            results = unique_preserve_order(results)

            def apply_results() -> bool:
                if job_id != self._search_job_id:
                    return False

                self.search_results = results
                self.search_status.set_label("Canceled" if canceled else f"{len(results)} result(s)")
                self._rebuild_search_results()
                self.search_cancel_button.set_visible(False)
                return False

            GLib.idle_add(apply_results)
            return

        results = search_repo_online(self.default_installer, query_stripped)
        results = unique_preserve_order(results)

        def apply_results() -> bool:
            if job_id != self._search_job_id:
                return False

            self.search_results = results
            self.search_status.set_label(f"{len(results)} result(s)")
            self._rebuild_search_results()
            self.search_cancel_button.set_visible(False)
            return False

        GLib.idle_add(apply_results)

    def _start_search(self) -> None:
        self._cancel_previous_search()
        self._search_job_id += 1
        job_id = self._search_job_id

        query = self.search_entry.get_text()
        installed_only = bool(self.installed_only_check.get_active())

        self.search_status.set_label("Searching...")
        self.search_results = []
        self._rebuild_search_results()

        cancel_event: threading.Event | None = None

        if installed_only and not query.strip():
            cancel_event = threading.Event()
            self._search_cancel_event = cancel_event
            self.search_cancel_button.set_visible(True)
        else:
            self.search_cancel_button.set_visible(False)

        thread = threading.Thread(
            target=self._search_thread_worker,
            args=(job_id, query, installed_only, cancel_event),
            daemon=True,
        )
        thread.start()

    def _on_search_clicked(self, _button: Gtk.Button) -> None:
        self._start_search()

    def _on_search_activate(self, _entry: Gtk.Entry) -> None:
        self._start_search()

    def _on_search_cancel_clicked(self, _button: Gtk.Button) -> None:
        if self._search_cancel_event is not None:
            self._search_cancel_event.set()
        self.search_cancel_button.set_visible(False)
        self.search_status.set_label("Canceling...")

    def _on_search_add_clicked(self, _button: Gtk.Button, package_name: str) -> None:
        self.queue_add_primary_from_text(package_name)

    def _on_add_all_search_results_clicked(self, _button: Gtk.Button, popover: Gtk.Popover) -> None:
        if not self.search_results:
            return
        for package_name in self.search_results:
            self.queue_add_primary_from_text(package_name)
        popover.popdown()

    def _on_export_search_list_clicked(self, _button: Gtk.Button, popover: Gtk.Popover) -> None:
        self._open_export_dialog(self.search_results, "search-results.txt")
        popover.popdown()

    def _on_add_primary_clicked(self, _button: Gtk.Button) -> None:
        text = self.add_entry.get_text().strip()
        if not text:
            return
        self.queue_add_primary_from_text(text)
        self.add_entry.set_text("")

    def _on_add_primary_activate(self, _entry: Gtk.Entry) -> None:
        text = self.add_entry.get_text().strip()
        if not text:
            return
        self.queue_add_primary_from_text(text)
        self.add_entry.set_text("")

    def _on_add_primary_from_file_clicked(self, _button: Gtk.Button) -> None:
        dialog = Gtk.FileChooserNative.new(
            "Add from script or file",
            self,
            Gtk.FileChooserAction.OPEN,
            "_Open",
            "_Cancel",
        )
        dialog.connect("response", self._on_add_primary_from_file_response)
        dialog.show()
        self._add_from_file_dialog = dialog

    def _on_add_primary_from_file_response(self, dialog: Gtk.FileChooserNative, response: int) -> None:
        if response != Gtk.ResponseType.ACCEPT:
            dialog.destroy()
            self._add_from_file_dialog = None
            return

        selected_file = dialog.get_file()
        dialog.destroy()
        self._add_from_file_dialog = None
        if selected_file is None:
            return

        file_path = selected_file.get_path()
        if not file_path or not os.path.isfile(file_path) or not os.access(file_path, os.R_OK):
            self.append_log(f"[file error] Cannot read: {file_path}\n")
            return

        with open(file_path, "r", encoding="utf-8", errors="replace") as handle:
            content = handle.read()

        for line in content.splitlines():
            if not line.strip():
                continue
            for segment in line.replace("&&", "|").split("|"):
                segment_text = segment.strip()
                if segment_text:
                    self.queue_add_primary_from_text(segment_text)

    def _on_export_primary_list_clicked(self, _button: Gtk.Button, popover: Gtk.Popover) -> None:
        self._open_export_dialog(self._collect_primary_list_names(), "primary-packages.txt")
        popover.popdown()

    def _on_primary_filter_selected(self, _dropdown: Gtk.DropDown, _param_spec) -> None:
        self._apply_primary_filter()
        close_dropdown_popover(self.primary_filter_dropdown)

    def _on_install_all_primary_clicked(self, _button: Gtk.Button, popover: Gtk.Popover) -> None:
        filter_mode = self._current_primary_filter()
        for card in self._collect_primary_cards():
            if filter_mode == "installed" and not card.node.installed:
                continue
            if filter_mode == "not installed" and card.node.installed:
                continue
            card.node.last_action = "install"
            card.node.command_line = build_command_line(
                card.node.installer,
                "install",
                card.node.name,
                card.node.selected_version,
            )
            card.set_command_text(card.node.command_line)
            self.run_and_log(card.node.command_line)
        popover.popdown()

    def _on_remove_all_primary_clicked(self, _button: Gtk.Button, popover: Gtk.Popover) -> None:
        if not self.primary_names:
            return
        self.primary_names.clear()
        clear_box_children(self.primary_list_box)
        self._update_status()
        popover.popdown()

    def _on_remove_dependencies_clicked(self, _button: Gtk.Button, popover: Gtk.Popover) -> None:
        dialog = Gtk.Dialog(title="Remove dependencies", transient_for=self, modal=True)
        cancel_button = dialog.add_button("_Cancel", Gtk.ResponseType.CANCEL)
        apply_button = dialog.add_button("_Apply", Gtk.ResponseType.APPLY)

        content_box = dialog.get_content_area()
        content_box.set_margin_top(12)
        content_box.set_margin_bottom(12)
        content_box.set_margin_start(12)
        content_box.set_margin_end(12)
        content_box.set_spacing(8)

        description_label = Gtk.Label(
            label="Dependency depth (number of layers to check):",
            xalign=0.0,
        )
        content_box.append(description_label)

        depth_adjustment = Gtk.Adjustment.new(1, 1, 10, 1, 1, 0)
        depth_input = Gtk.SpinButton(adjustment=depth_adjustment, numeric=True)
        depth_input.set_value(1)
        content_box.append(depth_input)

        progress_bar = Gtk.ProgressBar(show_text=True)
        progress_bar.set_visible(False)
        progress_bar.set_fraction(0.0)
        content_box.append(progress_bar)

        dialog.connect(
            "response",
            self._on_remove_dependencies_response,
            depth_input,
            progress_bar,
            apply_button,
            cancel_button,
        )
        dialog.show()
        popover.popdown()

    def _on_remove_dependencies_response(
        self,
        dialog: Gtk.Dialog,
        response: int,
        depth_input: Gtk.SpinButton,
        progress_bar: Gtk.ProgressBar,
        apply_button: Gtk.Button,
        _cancel_button: Gtk.Button,
    ) -> None:
        if response == Gtk.ResponseType.CANCEL:
            if self._remove_dependencies_cancel_event is not None:
                self._remove_dependencies_cancel_event.set()
            dialog.destroy()
            return
        if response != Gtk.ResponseType.APPLY:
            dialog.destroy()
            return
        if self._remove_dependencies_cancel_event is not None:
            return
        dependency_layers = depth_input.get_value_as_int()
        progress_bar.set_visible(True)
        progress_bar.set_text("Starting dependency checks...")
        progress_bar.set_fraction(0.0)
        apply_button.set_sensitive(False)
        depth_input.set_sensitive(False)
        self._start_remove_dependencies(
            dependency_layers,
            progress_bar,
            apply_button,
            depth_input,
        )

    def _start_remove_dependencies(
        self,
        dependency_layers: int,
        progress_bar: Gtk.ProgressBar,
        apply_button: Gtk.Button,
        depth_input: Gtk.SpinButton,
    ) -> None:
        primary_package_names = self._collect_primary_list_names()
        if not primary_package_names:
            progress_bar.set_text("No packages to check.")
            progress_bar.set_fraction(1.0)
            apply_button.set_sensitive(True)
            depth_input.set_sensitive(True)
            return
        cancel_event = threading.Event()
        self._remove_dependencies_cancel_event = cancel_event

        def collect_dependencies_for_name(package_name: str) -> list[str]:
            return list_dependencies(self.default_installer, package_name)

        def worker() -> None:
            self._remove_dependencies_job_id += 1
            current_job_id = self._remove_dependencies_job_id
            all_dependency_names: set[str] = set()
            current_layer_names: set[str] = set(primary_package_names)
            remaining_primary_names: set[str] = set(primary_package_names)

            def update_progress(text: str | None = None) -> None:
                def apply_update() -> bool:
                    if cancel_event.is_set() or self._remove_dependencies_job_id != current_job_id:
                        return False
                    if progress_bar.get_parent() is None:
                        return False
                    if text is not None:
                        progress_bar.set_text(text)
                    progress_bar.pulse()
                    return False

                GLib.idle_add(apply_update)

            for _ in range(max(dependency_layers, 0)):
                if cancel_event.is_set() or not current_layer_names:
                    break
                current_layer_list = sorted(current_layer_names)
                next_layer_names: set[str] = set()
                for start_index in range(0, len(current_layer_list), 10):
                    if cancel_event.is_set():
                        break
                    batch_names = current_layer_list[start_index : start_index + 10]
                    with ThreadPoolExecutor(max_workers=10) as executor:
                        dependency_lists = list(
                            executor.map(collect_dependencies_for_name, batch_names)
                        )

                    for dependency_list in dependency_lists:
                        for dependency_name in dependency_list:
                            if dependency_name and dependency_name not in all_dependency_names:
                                next_layer_names.add(dependency_name)
                            all_dependency_names.add(dependency_name)

                    names_to_remove = all_dependency_names.intersection(remaining_primary_names)
                    if names_to_remove:
                        remaining_primary_names.difference_update(names_to_remove)

                        def apply_updates() -> bool:
                            if cancel_event.is_set() or self._remove_dependencies_job_id != current_job_id:
                                return False
                            self._remove_primary_cards_by_name(set(names_to_remove))
                            return False

                        GLib.idle_add(apply_updates)
                    update_progress("Checking dependency layers...")

                current_layer_names = next_layer_names

            def finalize() -> bool:
                self._remove_dependencies_cancel_event = None
                if progress_bar.get_parent() is None:
                    return False
                if cancel_event.is_set():
                    progress_bar.set_text("Canceled.")
                    progress_bar.set_fraction(0.0)
                else:
                    progress_bar.set_text("Done.")
                    progress_bar.set_fraction(1.0)
                if apply_button.get_parent() is not None:
                    apply_button.set_sensitive(True)
                if depth_input.get_parent() is not None:
                    depth_input.set_sensitive(True)
                return False

            GLib.idle_add(finalize)

        threading.Thread(target=worker, daemon=True).start()

    def _remove_primary_cards_by_name(self, names_to_remove: set[str]) -> None:
        if not names_to_remove:
            return
        child = self.primary_list_box.get_first_child()
        while child is not None:
            next_child = child.get_next_sibling()
            if isinstance(child, PackageCard) and child.node.name in names_to_remove:
                self.primary_names.discard(child.node.name)
                self.primary_list_box.remove(child)
            child = next_child
        self._update_status()

    def _on_clear_log(self, _button: Gtk.Button) -> None:
        buffer = self.log_view.get_buffer()
        buffer.set_text("")

    def _update_status(self) -> None:
        self.status_label.set_text(f"{len(self.primary_names)} item(s)")
