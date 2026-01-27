"""
backend.py

Backend utilities (repo search, installed listing, versions, dependencies, parsing).
"""

from __future__ import annotations

import subprocess
import threading

import helpers
from models import PackageNode
from ui_helpers import unique_preserve_order


def normalize_target_name(target: str) -> str:
    if "=" in target:
        return target.split("=", 1)[0]
    return target


def build_target_with_version(installer: str, name: str, selected_version: str) -> str:
    if selected_version in {"default", "latest", ""}:
        return name

    if installer in {"apt", "apt-get", "nala"}:
        return f"{name}={selected_version}"

    return f"{name}-{selected_version}"


def yes_flags_for_action(installer: str, action: str) -> list[str]:
    if installer in {"dnf", "dnf5", "yum"} and action in {"install", "remove", "reinstall", "upgrade", "downgrade"}:
        return ["-y"]

    if installer in {"apt", "apt-get", "nala"} and action in {"install", "remove", "reinstall", "upgrade"}:
        return ["-y"]

    if installer in {"pacman", "yay", "paru"} and action in {"install", "remove", "reinstall", "upgrade"}:
        return ["--noconfirm"]

    return []


def build_command_line(installer: str, action: str, name: str, selected_version: str) -> str:
    target = build_target_with_version(installer, name, selected_version)
    flags = yes_flags_for_action(installer, action)
    flags_text = (" " + " ".join(flags)) if flags else ""
    return f"sudo {installer} {action}{flags_text} {target}"


def run_first_success(commands: list[str]) -> tuple[int, str, str]:
    last_code = 1
    last_out = ""
    last_err = ""
    for command in commands:
        return_code, standard_output, standard_error = helpers.run_bash(command)
        last_code, last_out, last_err = return_code, standard_output, standard_error
        if return_code == 0:
            return return_code, standard_output, standard_error
    return last_code, last_out, last_err


def detect_default_installer() -> str:
    code, _, _ = helpers.run_bash("command -v dnf5 >/dev/null 2>&1")
    if code == 0:
        return "dnf5"

    code, _, _ = helpers.run_bash("command -v dnf >/dev/null 2>&1")
    if code == 0:
        return "dnf"

    return "dnf"


def list_available_installers() -> list[str]:
    installers = [
        "dnf5",
        "dnf",
        "yum",
        "apt",
        "apt-get",
        "nala",
        "pacman",
        "yay",
        "paru",
        "zypper",
        "apk",
        "brew",
    ]
    available: list[str] = []
    for installer in installers:
        code, _, _ = helpers.run_bash(f"command -v {installer} >/dev/null 2>&1")
        if code == 0:
            available.append(installer)

    if available:
        return available

    return ["dnf"]


def _stream_command_lines(
    command: str,
    cancel_event: threading.Event,
    substring_filter: str,
) -> tuple[list[str], bool]:
    process = subprocess.Popen(
        command,
        shell=True,
        executable="/bin/bash",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    collected: list[str] = []
    canceled = False
    substring_lower = substring_filter.lower().strip()

    while True:
        if cancel_event.is_set():
            canceled = True
            process.terminate()
            break

        line = process.stdout.readline() if process.stdout is not None else ""
        if not line:
            break

        value = line.strip()
        if not value:
            continue

        if substring_lower and substring_lower not in value.lower():
            continue

        collected.append(value)

    if canceled:
        try:
            process.kill()
        except Exception:
            pass

    return_code = process.wait()
    if return_code != 0 and not canceled:
        return [], False

    return unique_preserve_order(collected), canceled


def list_installed_packages(
    installer: str,
    cancel_event: threading.Event,
    substring_filter: str,
) -> tuple[list[str], bool]:
    if installer in {"dnf", "dnf5", "yum"}:
        command = "rpm -qa --qf '%{NAME}\\n' | sort -u"
        return _stream_command_lines(command, cancel_event, substring_filter)

    if installer in {"apt", "apt-get", "nala"}:
        command = "dpkg-query -W -f='${Package}\\n' | sort -u"
        return _stream_command_lines(command, cancel_event, substring_filter)

    if installer in {"pacman", "yay", "paru"}:
        command = "pacman -Qq | sort -u"
        return _stream_command_lines(command, cancel_event, substring_filter)

    command = "rpm -qa --qf '%{NAME}\\n' | sort -u"
    return _stream_command_lines(command, cancel_event, substring_filter)


def search_repo_online(installer: str, query: str) -> list[str]:
    query_stripped = query.strip()
    if not query_stripped:
        return []

    if installer in {"dnf", "dnf5", "yum"}:
        commands = [
            f"dnf5 repoquery -q --available --qf '%{{name}}\\n' '*{query_stripped}*' | sort -u",
            f"dnf repoquery -q --available --qf '%{{name}}\\n' '*{query_stripped}*' | sort -u",
            f"{installer} repoquery -q --available --qf '%{{name}}\\n' '*{query_stripped}*' | sort -u",
        ]
        code, stdout, _ = run_first_success(commands)
        if code == 0:
            results = [line.strip() for line in stdout.splitlines() if line.strip()]
            return unique_preserve_order(results)

    return helpers.search_repo(installer, query_stripped)


def list_versions(installer: str, package_name: str) -> list[str]:
    if installer in {"dnf", "dnf5", "yum"}:
        commands = [
            f"dnf5 repoquery --available --show-duplicates --qf '%{{version}}-%{{release}}\\n' {package_name} | sort -u",
            f"dnf repoquery --available --show-duplicates --qf '%{{version}}-%{{release}}\\n' {package_name} | sort -u",
            f"{installer} repoquery --available --show-duplicates --qf '%{{version}}-%{{release}}\\n' {package_name} | sort -u",
        ]
        _, standard_output, _ = run_first_success(commands)
        versions = [line.strip() for line in standard_output.splitlines() if line.strip()]
        return unique_preserve_order(["default", "latest"] + versions)

    if installer in {"apt", "apt-get", "nala"}:
        command = f"apt-cache madison {package_name}"
        _, standard_output, _ = helpers.run_bash(command)
        versions: list[str] = []
        for line in standard_output.splitlines():
            parts = [part.strip() for part in line.split("|")]
            if len(parts) >= 2 and parts[1]:
                versions.append(parts[1])
        return unique_preserve_order(["default", "latest"] + versions)

    return ["default", "latest"]


def _strip_dep_token(token: str) -> str:
    token = token.strip()
    if not token:
        return ""

    if "(" in token and token.endswith(")"):
        token = token.split("(", 1)[0].strip()

    token = token.split(" ", 1)[0].strip()

    if token.startswith("<") and token.endswith(">"):
        return ""

    return token


def list_dependencies(installer: str, package_name: str) -> list[str]:
    if installer in {"dnf", "dnf5", "yum"}:
        commands = [
            f"dnf5 repoquery -q --providers-of=depends --qf '%{{name}}\\n' {package_name} | sort -u",
            f"dnf repoquery -q --providers-of=depends --qf '%{{name}}\\n' {package_name} | sort -u",
            f"{installer} repoquery -q --providers-of=depends --qf '%{{name}}\\n' {package_name} | sort -u",
        ]
        code, standard_output, _ = run_first_success(commands)
        if code == 0:
            dependencies = [line.strip() for line in standard_output.splitlines() if line.strip()]
            dependencies = [dep for dep in dependencies if dep != package_name]
            return unique_preserve_order(dependencies)

        commands = [
            f"dnf repoquery -q --requires --resolve --qf '%{{name}}\\n' {package_name} | sort -u",
            f"{installer} repoquery -q --requires --resolve --qf '%{{name}}\\n' {package_name} | sort -u",
            f"repoquery -q --requires --resolve --qf '%{{name}}\\n' {package_name} | sort -u",
        ]
        code, standard_output, _ = run_first_success(commands)
        if code == 0:
            dependencies = [line.strip() for line in standard_output.splitlines() if line.strip()]
            dependencies = [dep for dep in dependencies if dep != package_name]
            return unique_preserve_order(dependencies)

        return []

    if installer in {"apt", "apt-get", "nala"}:
        command = f"apt-cache depends {package_name}"
        _, standard_output, _ = helpers.run_bash(command)

        dependencies: list[str] = []
        for line in standard_output.splitlines():
            line_stripped = line.strip()
            if not line_stripped.startswith("Depends:"):
                continue

            raw = line_stripped.split("Depends:", 1)[1].strip()
            raw = raw.split("|", 1)[0].strip()
            dep = _strip_dep_token(raw)
            if dep:
                dependencies.append(dep)

        return unique_preserve_order(dependencies)

    return []


def parse_add_input(text: str, default_installer: str) -> tuple[str, str, str]:
    candidate = text.strip()
    if not candidate:
        return "", "", ""

    installer = helpers.find_installer(candidate)
    if installer:
        target = helpers.find_target(candidate)
        if target:
            return installer, target, candidate

    return default_installer, candidate, ""


def create_node(installer: str, target: str, is_dependency: bool) -> PackageNode:
    version_spec = helpers.version_from_target(target)
    base_name = normalize_target_name(target)

    installed_version_value = helpers.installed_version(base_name)
    installed = bool(installed_version_value)

    versions = list_versions(installer, base_name)

    selected_version = installed_version_value if installed_version_value else (version_spec if version_spec else "default")

    if installed_version_value:
        versions = unique_preserve_order(["default", "latest", installed_version_value] + versions)

    if selected_version not in versions:
        versions = unique_preserve_order(versions + [selected_version])

    command_line = build_command_line(installer, "install", base_name, selected_version)

    return PackageNode(
        name=base_name,
        installer=installer,
        installed=installed,
        installed_version=installed_version_value,
        command_line=command_line,
        versions=versions,
        selected_version=selected_version,
        dependencies=[],
        is_dependency=is_dependency,
        last_action="install",
        dependencies_loaded=False,
    )
