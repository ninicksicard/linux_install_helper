# Linux Install Helper (GTK4)

A small GTK4 desktop app that helps you **search packages**, **inspect dependency trees**, and **run package-manager actions** with a visible, editable command preview.

This is aimed at "I know what I want to install, but I want a clearer view of what is installed, what depends on what, and what command will actually run".

## Screenshots

Search results (left) + primary packages with dependency expansion (right):

![Search and dependency view](misc/Screenshot%20from%202026-01-25%2010-56-21.png)

Searching for a term and adding packages to the primary list:

![Repo search example](misc/Screenshot%20from%202026-01-25%2010-56-34.png)

Pasting a full install command and inspecting dependencies:

![Paste command example](misc/Screenshot%20from%202026-01-25%2011-01-37.png)

## Key features

- Repo search (when supported by the active installer)
- List installed packages with filtering and cancel support
- "Primary packages" list where each primary can expand into a dependency list
- Installed status + installed version indicator
- Version listing (best-effort, depends on the installer)
- Builds an explicit command line you can review before running
- Output log panel for command execution

## Supported package managers

The code includes support for the following installers (behavior varies by installer):

- dnf, dnf5, yum
- apt, apt-get, nala
- pacman, yay, paru
- zypper
- apk
- brew

Important current limitation:
- Automatic default-installer detection is currently Fedora/RHEL-family focused (dnf5/dnf). On other distros, you can still use the app by **pasting a command that includes your installer** (example: `sudo apt install ...` or `sudo pacman -S ...`), which will switch the package context for that added primary.

## How it runs commands (safety + privileges)

- The UI always shows a command line preview for the action you are about to run.
- If a command starts with a simple `sudo ...`, the app strips `sudo` and uses **pkexec** for privilege escalation.
- Commands that do not use `sudo` are run without elevation.

This means you may see a PolicyKit prompt (pkexec) when running install/remove actions.

## How the action buttons work (Install / Reinstall / Remove)

The **Install**, **Reinstall**, and **Remove** buttons do **not** execute anything by themselves.

They only **compose/update the command text** in the command entry field (so you can review or edit it).
To actually run the command, you must click **Run**.
![Screenshot from 2026-01-25 11-22-16.png](misc/Screenshot%20from%202026-01-25%2011-22-16.png)

## Requirements

- Python 3.10+
- GTK4 + PyGObject (installed from your distro packages)
- PolicyKit / pkexec (for privileged install/remove actions)

### Install dependencies (examples)

Fedora:
```bash
sudo dnf install -y python3 python3-gobject gtk4
