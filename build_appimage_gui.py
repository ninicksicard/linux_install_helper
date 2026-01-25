"""
build_appimage_gui.py

GTK4 build navigator for the AppImage pipeline (venv -> pyinstaller -> AppDir -> linuxdeploy).
"""

from __future__ import annotations

import os

# Disable AT-SPI accessibility bridge for this app if the host can't spawn the registry.
# This avoids noisy Gtk-CRITICAL errors like:
# "Failed to execute program org.a11y.atspi.Registry: Permission denied"
os.environ.setdefault("GTK_A11Y", "none")

import base64
import shutil
import subprocess
import threading
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import gi

gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402


@dataclass
class BuildContext:
    project_root_directory: Path
    python_executable: str
    entrypoint_python_file: str
    application_identifier: str
    application_display_name: str

    build_directory: Path
    virtual_environment_directory: Path
    pyinstaller_build_directory: Path
    pyinstaller_dist_directory: Path

    application_directory: Path
    packaging_directory: Path
    tools_directory: Path
    output_directory: Path

    linuxdeploy_appimage_path: Path
    linuxdeploy_gtk_plugin_appimage_path: Path

    desktop_file_path: Path
    icon_file_path: Path

    @property
    def venv_python_path(self) -> Path:
        return self.virtual_environment_directory / "bin" / "python"

    @property
    def venv_pyinstaller_path(self) -> Path:
        return self.virtual_environment_directory / "bin" / "pyinstaller"

    @property
    def pyinstaller_output_program_directory(self) -> Path:
        return self.pyinstaller_dist_directory / self.application_identifier

    @property
    def pyinstaller_output_executable_path(self) -> Path:
        return self.pyinstaller_output_program_directory / self.application_identifier

def make_default_context(project_root_directory: Path) -> BuildContext:
    python_executable = os.environ.get("PYTHON_EXECUTABLE", "python3.14")
    entrypoint_python_file = os.environ.get("ENTRYPOINT_PYTHON_FILE", "main_gtk4.py")
    application_identifier = os.environ.get("APPLICATION_IDENTIFIER", "linux-install-helper")
    application_display_name = os.environ.get("APPLICATION_DISPLAY_NAME", "Linux Install Helper")

    build_directory_env = os.environ.get("BUILD_DIRECTORY", "")
    if build_directory_env.strip():
        build_directory = Path(build_directory_env).expanduser().resolve()
    else:
        build_directory = project_root_directory / "build_appimage"

    virtual_environment_directory = build_directory / "virtual_environment"
    pyinstaller_build_directory = build_directory / "pyinstaller_build"
    pyinstaller_dist_directory = build_directory / "pyinstaller_dist"

    application_directory = build_directory / "AppDir"
    packaging_directory = build_directory / "packaging"
    tools_directory = build_directory / "tools"
    output_directory = build_directory / "out"

    linuxdeploy_appimage_path = tools_directory / "linuxdeploy-x86_64.AppImage"
    linuxdeploy_gtk_plugin_appimage_path = tools_directory / "linuxdeploy-plugin-gtk-x86_64.AppImage"

    desktop_file_path = packaging_directory / f"{application_identifier}.desktop"
    icon_file_path = packaging_directory / f"{application_identifier}.png"

    return BuildContext(
        project_root_directory=project_root_directory,
        python_executable=python_executable,
        entrypoint_python_file=entrypoint_python_file,
        application_identifier=application_identifier,
        application_display_name=application_display_name,
        build_directory=build_directory,
        virtual_environment_directory=virtual_environment_directory,
        pyinstaller_build_directory=pyinstaller_build_directory,
        pyinstaller_dist_directory=pyinstaller_dist_directory,
        application_directory=application_directory,
        packaging_directory=packaging_directory,
        tools_directory=tools_directory,
        output_directory=output_directory,
        linuxdeploy_appimage_path=linuxdeploy_appimage_path,
        linuxdeploy_gtk_plugin_appimage_path=linuxdeploy_gtk_plugin_appimage_path,
        desktop_file_path=desktop_file_path,
        icon_file_path=icon_file_path,
    )

class StepStatus:
    PENDING = "pending"
    RUNNING = "running"
    OK = "ok"
    FAIL = "fail"


def run_command_and_stream(
    command: list[str],
    working_directory: Path,
    environment: dict[str, str],
    on_line: Callable[[str], None],
) -> int:
    process = subprocess.Popen(
        command,
        cwd=str(working_directory),
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    if process.stdout is not None:
        for line in process.stdout:
            on_line(line.rstrip("\n"))

    return int(process.wait())


def download_file(url: str, destination_path: Path, minimum_bytes: int) -> None:
    if destination_path.exists():
        if destination_path.stat().st_size >= minimum_bytes:
            return
        destination_path.unlink()

    destination_path.parent.mkdir(parents=True, exist_ok=True)

    with urllib.request.urlopen(url) as response:
        data = response.read()

    destination_path.write_bytes(data)

    if destination_path.stat().st_size < minimum_bytes:
        destination_path.unlink(missing_ok=True)


def ensure_directories(context: BuildContext) -> None:
    context.build_directory.mkdir(parents=True, exist_ok=True)
    context.output_directory.mkdir(parents=True, exist_ok=True)
    context.tools_directory.mkdir(parents=True, exist_ok=True)
    context.packaging_directory.mkdir(parents=True, exist_ok=True)


def step_prepare_directories(context: BuildContext, log: Callable[[str], None]) -> bool:
    log("Preparing build directories...")
    ensure_directories(context)
    return True


def step_create_venv_and_install_deps(context: BuildContext, log: Callable[[str], None]) -> bool:
    log("Recreating virtual environment...")
    shutil.rmtree(context.virtual_environment_directory, ignore_errors=True)

    environment = os.environ.copy()
    environment["APPIMAGE_EXTRACT_AND_RUN"] = "1"

    code = run_command_and_stream(
        [context.python_executable, "-m", "venv", str(context.virtual_environment_directory)],
        context.project_root_directory,
        environment,
        log,
    )
    if code != 0:
        return False

    log("Installing build dependencies (pip/setuptools/wheel + pyinstaller)...")
    code = run_command_and_stream(
        [str(context.venv_python_path), "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"],
        context.project_root_directory,
        environment,
        log,
    )
    if code != 0:
        return False

    code = run_command_and_stream(
        [str(context.venv_python_path), "-m", "pip", "install", "--upgrade", "pyinstaller"],
        context.project_root_directory,
        environment,
        log,
    )
    if code != 0:
        return False

    requirements_path = context.project_root_directory / "requirements.txt"
    if requirements_path.exists():
        log("Installing requirements.txt...")
        code = run_command_and_stream(
            [str(context.venv_python_path), "-m", "pip", "install", "-r", str(requirements_path)],
            context.project_root_directory,
            environment,
            log,
        )
        if code != 0:
            return False

    return True


def step_pyinstaller_build(context: BuildContext, log: Callable[[str], None]) -> bool:
    log("Cleaning pyinstaller build/dist folders...")
    shutil.rmtree(context.pyinstaller_build_directory, ignore_errors=True)
    shutil.rmtree(context.pyinstaller_dist_directory, ignore_errors=True)
    context.pyinstaller_build_directory.mkdir(parents=True, exist_ok=True)
    context.pyinstaller_dist_directory.mkdir(parents=True, exist_ok=True)

    environment = os.environ.copy()
    environment["APPIMAGE_EXTRACT_AND_RUN"] = "1"

    log("Running PyInstaller (onedir, windowed)...")
    command = [
        str(context.venv_pyinstaller_path),
        "--noconfirm",
        "--clean",
        "--onedir",
        "--windowed",
        "--name",
        context.application_identifier,
        "--workpath",
        str(context.pyinstaller_build_directory),
        "--distpath",
        str(context.pyinstaller_dist_directory),
        context.entrypoint_python_file,
    ]
    code = run_command_and_stream(command, context.project_root_directory, environment, log)
    if code != 0:
        return False

    if not context.pyinstaller_output_executable_path.exists():
        log("Expected pyinstaller executable not found.")
        return False

    return True


def step_desktop_and_icon(context: BuildContext, log: Callable[[str], None]) -> bool:
    ensure_directories(context)

    if not context.desktop_file_path.exists():
        log("Creating .desktop file...")
        desktop_text = "\n".join(
            [
                "[Desktop Entry]",
                "Type=Application",
                f"Name={context.application_display_name}",
                f"Exec={context.application_identifier}",
                f"Icon={context.application_identifier}",
                "Terminal=false",
                "Categories=System;Utility;",
                "",
            ]
        )
        context.desktop_file_path.write_text(desktop_text, encoding="utf-8")

    if not context.icon_file_path.exists():
        log("Creating placeholder icon (1x1 png)...")
        png_bytes = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO7+XaoAAAAASUVORK5CYII="
        )
        context.icon_file_path.write_bytes(png_bytes)

    return True


def step_assemble_appdir(context: BuildContext, log: Callable[[str], None]) -> bool:
    log("Assembling AppDir...")
    shutil.rmtree(context.application_directory, ignore_errors=True)
    (context.application_directory / "usr" / "bin").mkdir(parents=True, exist_ok=True)

    shutil.copytree(
        context.pyinstaller_output_program_directory,
        context.application_directory / "usr" / "bin",
        dirs_exist_ok=True,
    )
    return True


def step_download_linuxdeploy(context: BuildContext, log: Callable[[str], None]) -> bool:
    ensure_directories(context)
    log("Downloading linuxdeploy + gtk plugin...")

    download_file(
        "https://github.com/linuxdeploy/linuxdeploy/releases/download/continuous/linuxdeploy-x86_64.AppImage",
        context.linuxdeploy_appimage_path,
        minimum_bytes=1_048_576,
    )
    download_file(
        "https://github.com/linuxdeploy/linuxdeploy-plugin-gtk/releases/download/continuous/linuxdeploy-plugin-gtk-x86_64.AppImage",
        context.linuxdeploy_gtk_plugin_appimage_path,
        minimum_bytes=1_048_576,
    )

    if not context.linuxdeploy_appimage_path.exists():
        log("linuxdeploy download failed or looks incomplete.")
        return False
    if not context.linuxdeploy_gtk_plugin_appimage_path.exists():
        log("linuxdeploy gtk plugin download failed or looks incomplete.")
        return False

    os.chmod(context.linuxdeploy_appimage_path, 0o755)
    os.chmod(context.linuxdeploy_gtk_plugin_appimage_path, 0o755)

    plugin_symlink = context.tools_directory / "linuxdeploy-plugin-gtk"
    if plugin_symlink.exists() or plugin_symlink.is_symlink():
        plugin_symlink.unlink()
    plugin_symlink.symlink_to(context.linuxdeploy_gtk_plugin_appimage_path)
    os.chmod(plugin_symlink, 0o755)

    return True

def step_build_appimage(self) -> None:
    self._append_log("== Step: Build AppImage ==")
    self._append_log("Building AppImage via linuxdeploy...")

    linuxdeploy = self.context.linuxdeploy_appimage_path
    gtk_plugin = self.context.linuxdeploy_gtk_plugin_appimage_path
    appdir = self.context.application_directory
    desktop_file = self.context.desktop_file_path
    icon_file = self.context.icon_file_path
    output_dir = self.context.output_directory

    env = os.environ.copy()
    env["DEPLOY_GTK_VERSION"] = "4"
    env["PATH"] = f"{gtk_plugin.parent}:{env.get('PATH', '')}"

    # --- Diagnostic: test GTK plugin explicitly ---
    self._append_log("")
    self._append_log("[diagnostic] Probing GTK plugin API version...")

    probe = subprocess.run(
        [str(gtk_plugin), "--plugin-api-version"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )

    self._append_log(f"[diagnostic] exit code: {probe.returncode}")

    if probe.stdout.strip():
        self._append_log("[diagnostic] stdout:")
        self._append_log(probe.stdout.rstrip())

    if probe.stderr.strip():
        self._append_log("[diagnostic] stderr:")
        self._append_log(probe.stderr.rstrip())

    if probe.returncode != 0:
        self._append_log("")
        self._append_log("ERROR: linuxdeploy GTK plugin failed to execute.")
        self._append_log("Common causes:")
        self._append_log(" - build directory is on a 'noexec' filesystem")
        self._append_log(" - missing GTK runtime libraries on the host")
        self._append_log(" - corrupted or incomplete plugin download")
        self._append_log("")
        self._append_log("Suggested checks:")
        self._append_log(f"  mount | grep '{gtk_plugin.parent}'")
        self._append_log(f"  ls -l {gtk_plugin}")
        self._append_log(f"  {gtk_plugin} --plugin-api-version")
        raise RuntimeError("GTK plugin execution failed")

    # --- Run linuxdeploy ---
    self._append_log("")
    self._append_log("[build] Running linuxdeploy...")

    command = [
        str(linuxdeploy),
        "--appdir", str(appdir),
        "-d", str(desktop_file),
        "-i", str(icon_file),
        "--plugin", "gtk",
        "--output", "appimage",
    ]

    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        cwd=self.context.build_directory,
    )

    if result.stdout.strip():
        self._append_log("[linuxdeploy stdout]")
        self._append_log(result.stdout.rstrip())

    if result.stderr.strip():
        self._append_log("[linuxdeploy stderr]")
        self._append_log(result.stderr.rstrip())

    if result.returncode != 0:
        self._append_log("")
        self._append_log("ERROR: linuxdeploy failed.")
        self._append_log("If this mentions gtk-plugin, verify:")
        self._append_log(" - build directory is executable (not noexec)")
        self._append_log(" - DEPLOY_GTK_VERSION=4 is supported on this host")
        raise RuntimeError("linuxdeploy failed")

    # --- Move output ---
    generated = next(self.context.build_directory.glob("*.AppImage"))
    final_path = output_dir / generated.name
    generated.replace(final_path)

    self._append_log("")
    self._append_log("== Result: SUCCESS ==")
    self._append_log(f"AppImage created at: {final_path}")



@dataclass
class BuildStep:
    name: str
    action: Callable[[BuildContext, Callable[[str], None]], bool]


class BuildStepRow(Gtk.Box):
    def __init__(self, step: BuildStep, on_run_clicked: Callable[[], None]) -> None:
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.step = step

        self.add_css_class("step-row")
        self.set_margin_start(10)
        self.set_margin_end(10)
        self.set_margin_top(6)
        self.set_margin_bottom(6)

        self.status_label = Gtk.Label(label="Pending", xalign=0.0)
        self.status_label.set_width_chars(10)

        self.name_label = Gtk.Label(label=step.name, xalign=0.0)
        self.name_label.set_hexpand(True)

        self.run_button = Gtk.Button(label="Run")
        self.run_button.connect("clicked", lambda _b: on_run_clicked())

        self.append(self.status_label)
        self.append(self.name_label)
        self.append(self.run_button)

        self.status = StepStatus.PENDING
        self._sync_status()

    def set_status(self, status: str) -> None:
        self.status = status
        self._sync_status()

    def set_sensitive_run(self, enabled: bool) -> None:
        self.run_button.set_sensitive(enabled)

    def _sync_status(self) -> None:
        if self.status == StepStatus.PENDING:
            self.status_label.set_label("Pending")
            self.status_label.remove_css_class("ok")
            self.status_label.remove_css_class("fail")
            self.status_label.remove_css_class("running")
        elif self.status == StepStatus.RUNNING:
            self.status_label.set_label("Running")
            self.status_label.add_css_class("running")
            self.status_label.remove_css_class("ok")
            self.status_label.remove_css_class("fail")
        elif self.status == StepStatus.OK:
            self.status_label.set_label("OK")
            self.status_label.add_css_class("ok")
            self.status_label.remove_css_class("fail")
            self.status_label.remove_css_class("running")
        elif self.status == StepStatus.FAIL:
            self.status_label.set_label("Fail")
            self.status_label.add_css_class("fail")
            self.status_label.remove_css_class("ok")
            self.status_label.remove_css_class("running")


class BuildNavigatorWindow(Gtk.ApplicationWindow):
    def __init__(self, application: Gtk.Application, context: BuildContext) -> None:
        super().__init__(application=application)
        self.context = context

        self.set_title("AppImage Build Navigator (GTK4)")
        self.set_default_size(980, 680)

        self.is_running = False

        self.steps: list[BuildStep] = [
            BuildStep("Prepare directories", step_prepare_directories),
            BuildStep("Create venv + install deps", step_create_venv_and_install_deps),
            BuildStep("PyInstaller build", step_pyinstaller_build),
            BuildStep("Create .desktop + icon", step_desktop_and_icon),
            BuildStep("Assemble AppDir", step_assemble_appdir),
            BuildStep("Download linuxdeploy tools", step_download_linuxdeploy),
            BuildStep("Build AppImage", step_build_appimage),
        ]

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        root.set_margin_top(10)
        root.set_margin_bottom(10)
        root.set_margin_start(10)
        root.set_margin_end(10)
        self.set_child(root)

        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        root.append(top)

        summary_label = Gtk.Label(label=self._summary_text(), xalign=0.0)
        summary_label.set_hexpand(True)
        summary_label.add_css_class("muted")
        top.append(summary_label)

        self.run_all_button = Gtk.Button(label="Run all")
        self.run_all_button.connect("clicked", self._on_run_all_clicked)
        top.append(self.run_all_button)

        self.reset_button = Gtk.Button(label="Reset statuses")
        self.reset_button.connect("clicked", self._on_reset_clicked)
        top.append(self.reset_button)

        steps_frame = Gtk.Frame()
        steps_frame.add_css_class("card")
        root.append(steps_frame)

        steps_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        steps_frame.set_child(steps_box)

        self.step_rows: list[BuildStepRow] = []
        for index, step in enumerate(self.steps):
            row = BuildStepRow(step=step, on_run_clicked=lambda i=index: self._run_step(i))
            steps_box.append(row)
            self.step_rows.append(row)

        log_frame = Gtk.Frame()
        log_frame.add_css_class("card")
        root.append(log_frame)

        log_root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        log_root.set_margin_top(8)
        log_root.set_margin_bottom(8)
        log_root.set_margin_start(8)
        log_root.set_margin_end(8)
        log_frame.set_child(log_root)

        log_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        log_root.append(log_header)

        log_title = Gtk.Label(label="Output", xalign=0.0)
        log_title.set_hexpand(True)
        log_header.append(log_title)

        clear_button = Gtk.Button(label="Clear")
        clear_button.connect("clicked", self._on_clear_clicked)
        log_header.append(clear_button)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        log_root.append(scrolled)

        self.log_view = Gtk.TextView()
        self.log_view.set_editable(False)
        self.log_view.set_cursor_visible(False)
        scrolled.set_child(self.log_view)

        self._apply_css()

    def _apply_css(self) -> None:
        provider = Gtk.CssProvider()
        provider.load_from_data(
            b"""
            .muted { opacity: 0.75; }
            .card { border-radius: 10px; border: 1px solid alpha(currentColor, 0.14); padding: 6px; }
            .step-row { border-radius: 10px; border: 1px solid alpha(currentColor, 0.10); padding: 6px; }
            .step-row button { border-radius: 8px; }
            .ok { color: #2aa84a; font-weight: 700; }
            .fail { color: #d43d3d; font-weight: 700; }
            .running { color: #2b6cb0; font-weight: 700; }
            """
        )

        display = Gdk.Display.get_default()
        if display is not None:
            Gtk.StyleContext.add_provider_for_display(display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def _summary_text(self) -> str:
        return (
            f"root={self.context.project_root_directory} | "
            f"python={self.context.python_executable} | "
            f"entry={self.context.entrypoint_python_file} | "
            f"out={self.context.output_directory}"
        )

    def _append_log(self, text: str) -> None:
        buffer = self.log_view.get_buffer()
        end_iter = buffer.get_end_iter()
        buffer.insert(end_iter, text + "\n")

        # Auto-scroll to bottom
        mark = buffer.create_mark(None, buffer.get_end_iter(), False)
        self.log_view.scroll_to_mark(mark, 0.0, True, 0.0, 1.0)

    def _set_running(self, running: bool) -> None:
        self.is_running = running
        self.run_all_button.set_sensitive(not running)
        self.reset_button.set_sensitive(not running)
        for row in self.step_rows:
            row.set_sensitive_run(not running)

    def _on_clear_clicked(self, _button: Gtk.Button) -> None:
        buffer = self.log_view.get_buffer()
        buffer.set_text("")

    def _on_reset_clicked(self, _button: Gtk.Button) -> None:
        for row in self.step_rows:
            row.set_status(StepStatus.PENDING)

    def _run_step(self, index: int) -> None:
        if self.is_running:
            return

        row = self.step_rows[index]
        step = self.steps[index]

        self._set_running(True)
        row.set_status(StepStatus.RUNNING)
        self._append_log(f"== Step: {step.name} ==")

        def log(line: str) -> None:
            GLib.idle_add(lambda: (self._append_log(line), False)[1])

        def worker() -> None:
            ok = step.action(self.context, lambda s: log(s))
            GLib.idle_add(lambda: self._finish_single_step(index, ok) or False)

        threading.Thread(target=worker, daemon=True).start()

    def _finish_single_step(self, index: int, ok: bool) -> None:
        self.step_rows[index].set_status(StepStatus.OK if ok else StepStatus.FAIL)
        self._append_log(f"== Result: {'OK' if ok else 'FAIL'} ==")
        self._append_log("")
        self._set_running(False)

    def _on_run_all_clicked(self, _button: Gtk.Button) -> None:
        if self.is_running:
            return

        self._set_running(True)
        self._append_log("== Running all steps ==")

        def log(line: str) -> None:
            GLib.idle_add(lambda: (self._append_log(line), False)[1])

        def worker() -> None:
            overall_ok = True
            for index, step in enumerate(self.steps):
                GLib.idle_add(lambda i=index: (self.step_rows[i].set_status(StepStatus.RUNNING), False)[1])
                log(f"== Step: {step.name} ==")

                ok = step.action(self.context, lambda s: log(s))
                overall_ok = overall_ok and ok

                GLib.idle_add(
                    lambda i=index, result_ok=ok: (self.step_rows[i].set_status(StepStatus.OK if result_ok else StepStatus.FAIL), False)[1]
                )

                log(f"== Result: {'OK' if ok else 'FAIL'} ==")
                log("")

                if not ok:
                    break

            GLib.idle_add(lambda: self._finish_all(overall_ok) or False)

        threading.Thread(target=worker, daemon=True).start()

    def _finish_all(self, overall_ok: bool) -> None:
        self._append_log(f"== Done: {'OK' if overall_ok else 'FAIL'} ==")
        self._append_log(f"Output directory: {self.context.output_directory}")
        self._set_running(False)


class BuildNavigatorApplication(Gtk.Application):
    def __init__(self, context: BuildContext) -> None:
        super().__init__(application_id="com.example.AppImageBuildNavigator")
        self.context = context

    def do_activate(self) -> None:
        window = BuildNavigatorWindow(self, self.context)
        window.present()


def main() -> None:
    project_root_directory = Path(__file__).resolve().parent
    context = make_default_context(project_root_directory)

    application = BuildNavigatorApplication(context=context)
    application.run(None)


if __name__ == "__main__":
    main()
