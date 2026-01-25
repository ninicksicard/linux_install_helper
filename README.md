# Linux Install Helper

Linux Install Helper is a graphical user interface for searching, tracking, and running package installations on common Linux distributions. It focuses on package manager workflows such as searching repositories, listing installed packages, viewing versions, and building install or remove commands with explicit confirmations.

## What it does

- Search available packages in configured repositories.
- Show installed packages with optional filtering.
- Add primary packages and inspect their dependencies.
- Show installed and available versions when the package manager supports it.
- Build and run install or remove commands that use the selected package manager.
- Provide a live output log for command execution.

## How it works

The application is written in Python and uses GTK4 for the user interface. The backend shell commands call the active package manager and supporting tools to fetch package lists, available versions, and dependency information. It detects a default installer on startup and uses that installer for actions unless a command input includes another one. Package actions are executed through `sudo` commands constructed from the selected action, installer, and version.

Supported package managers include:

- dnf, dnf5, and yum
- apt, apt-get, and nala
- pacman, yay, and paru
- zypper
- apk
- brew

## How to use it

### Run from source

1. Install Python and GTK4 bindings for Python (PyGObject) using your distribution packages.
2. From the repository root, run:

```
python3 src/main_gtk4.py
```

The window opens with a search panel on the left and a primary package list on the right. Use the search entry to find packages in repositories or select the installed filter to browse installed packages. Use the add entry to add a package name or paste an install command. Use the action buttons on each package card to install, remove, or refresh status.

### Build an AppImage

The repository includes a build script and a graphical build helper. The build script creates a virtual environment, runs PyInstaller, and assembles an AppImage using linuxdeploy.

```
./build_scripts/build_appimage.sh
```

The graphical build helper can be launched with:

```
python3 build_scripts/build_appimage_gui.py
```

Build artifacts are placed under `build_appimage`, and the final AppImage is written to `build_appimage/out`.

## Notes

- Running package actions uses `sudo`, so a terminal prompt or a policy kit prompt may appear depending on system configuration.
- Package search and version availability depend on the capabilities and metadata of the selected installer.
