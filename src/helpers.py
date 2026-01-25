"""
helpers.py
"""

import re
import shlex
import subprocess


def run_bash(command: str) -> tuple[int, str, str]:
    completed_process = subprocess.run(
        command,
        shell=True,
        executable="/bin/bash",
        capture_output=True,
        text=True,
    )
    return completed_process.returncode, completed_process.stdout, completed_process.stderr


def find_installer(command: str) -> str:
    tokens = shlex.split(command)

    # drop sudo/env prefixes commonly used before the installer
    while tokens and tokens[0] in {"sudo", "env"}:
        tokens = tokens[1:]

    for token in tokens:
        if token in {"dnf", "dnf5", "yum", "apt", "apt-get", "nala", "pacman", "yay", "paru", "zypper", "apk", "brew"}:
            return token

    return ""


def find_flags(command: str) -> list[str]:
    tokens = shlex.split(command)

    # flags are typically tokens starting with '-' (e.g. -y, --assumeyes, --reinstall)
    return [token for token in tokens if token.startswith("-")]


def find_target(command: str) -> str:
    tokens = shlex.split(command)

    # remove sudo/env so indexing is simpler
    while tokens and tokens[0] in {"sudo", "env"}:
        tokens = tokens[1:]

    installer = ""
    installer_index = -1
    for index, token in enumerate(tokens):
        if token in {"dnf", "dnf5", "yum", "apt", "apt-get", "nala", "pacman", "yay", "paru", "zypper", "apk", "brew"}:
            installer = token
            installer_index = index
            break

    if installer_index < 0:
        return ""

    after_installer = tokens[installer_index + 1 :]

    # skip common action words (install/reinstall/remove/etc.)
    while after_installer and after_installer[0] in {
        "install",
        "reinstall",
        "remove",
        "uninstall",
        "upgrade",
        "update",
        "search",
        "info",
    }:
        after_installer = after_installer[1:]

    # the target is usually the first non-flag token
    for token in after_installer:
        if token.startswith("-"):
            continue
        return token

    return ""


def version_from_target(target: str) -> str:
    # apt-style: package=1.2.3 or package=1.2.3-1
    if "=" in target:
        return target.split("=", 1)[1]

    # pacman-style: package=1.2.3 can also happen (AUR helpers)
    # rpm-style on CLI is less standard; keep simple: name-1.2.3 (best-effort)
    match = re.search(r"-(\d+(?:\.\d+)+[A-Za-z0-9_.:+~-]*)$", target)
    if match:
        return match.group(1)

    return ""


def search_repo(installer: str, target: str) -> list[str]:
    if installer in {"dnf", "dnf5", "yum"}:
        # repoquery is the cleanest way to list available package names if present
        command = f"dnf -q repoquery --available --qf '%{{name}}' '*{target}*' | sort -u"
        _, stdout, _ = run_bash(command)
        return [line.strip() for line in stdout.splitlines() if line.strip()]

    if installer in {"apt", "apt-get", "nala"}:
        # apt-cache search prints: "name - description"
        command = f"apt-cache search {shlex.quote(target)}"
        _, stdout, _ = run_bash(command)
        results = []
        for line in stdout.splitlines():
            # first token is the package name
            name = line.split(" ", 1)[0].strip()
            if name:
                results.append(name)
        return sorted(set(results))

    if installer in {"pacman", "yay", "paru"}:
        # pacman -Ss prints: repo/name version ...
        command = f"pacman -Ss {shlex.quote(target)}"
        _, stdout, _ = run_bash(command)
        results = []
        for line in stdout.splitlines():
            if "/" not in line:
                continue
            # keep the "name" part from "repo/name"
            first_field = line.split(" ", 1)[0].strip()
            name = first_field.split("/", 1)[1].strip()
            if name:
                results.append(name)
        return sorted(set(results))

    if installer == "zypper":
        # zypper search prints a table; extract "Name" column best-effort by matching words
        command = f"zypper -q search {shlex.quote(target)}"
        _, stdout, _ = run_bash(command)
        results = []
        for line in stdout.splitlines():
            if "|" not in line:
                continue
            parts = [part.strip() for part in line.split("|")]
            if len(parts) >= 2:
                name = parts[1]
                if name and name != "Name":
                    results.append(name)
        return sorted(set(results))

    if installer == "apk":
        command = f"apk search {shlex.quote(target)}"
        _, stdout, _ = run_bash(command)
        return sorted(set([line.strip() for line in stdout.splitlines() if line.strip()]))

    if installer == "brew":
        command = f"brew search {shlex.quote(target)}"
        _, stdout, _ = run_bash(command)
        return sorted(set([line.strip() for line in stdout.splitlines() if line.strip()]))

    return []


def installed_version(target: str) -> str:
    # try rpm first (Fedora/RHEL family)
    rpm_command = f"rpm -q --qf '%{{VERSION}}-%{{RELEASE}}' {shlex.quote(target)}"
    rpm_code, rpm_out, _ = run_bash(rpm_command)
    if rpm_code == 0:
        return rpm_out.strip()

    # try dpkg next (Debian/Ubuntu family)
    dpkg_command = f"dpkg-query -W -f='${{Version}}' {shlex.quote(target)}"
    dpkg_code, dpkg_out, _ = run_bash(dpkg_command)
    if dpkg_code == 0:
        return dpkg_out.strip()

    # try pacman (Arch family)
    pacman_command = f"pacman -Q {shlex.quote(target)}"
    pacman_code, pacman_out, _ = run_bash(pacman_command)
    if pacman_code == 0:
        # output: "name version"
        fields = pacman_out.strip().split()
        if len(fields) >= 2:
            return fields[1].strip()

    return ""
