#!/usr/bin/env bash
: <<'DOCSTRING'
build_appimage_verbose.sh

Build a GTK4-based Python application into an AppImage using:
- A fresh Python virtual environment (per-build)
- PyInstaller (onedir) to produce a self-contained runtime directory
- linuxdeploy + linuxdeploy-plugin-gtk to turn an AppDir into an AppImage

This script is intentionally verbose:
- More variables with clearer names
- Extra checks and readable helper functions
- More logs explaining what is happening and where files go
- Defensive behavior around downloads and missing inputs

Environment variables you can override:
- PYTHON_EXECUTABLE:          Python interpreter to use (default: python3.14)
- ENTRYPOINT_PYTHON_FILE:     The Python file PyInstaller should start from (default: main_gtk4.py)
- APPLICATION_IDENTIFIER:     Stable, machine-friendly app name (default: linux-install-helper)
- APPLICATION_DISPLAY_NAME:   Human-friendly name shown in menus (default: Linux Install Helper)

Outputs:
- Build artifacts go under: <project_root>/build_appimage
- Final AppImage goes to:    <project_root>/build_appimage/out

Notes:
- AppImage execution may require FUSE on some systems. We export APPIMAGE_EXTRACT_AND_RUN=1
  so the tools can run by extracting themselves when FUSE is unavailable.

DOCSTRING

set -euo pipefail

# ----------------------------
# Logging helpers
# ----------------------------
log_info() {
  local message="$1"
  echo "[INFO] ${message}"
}

log_warn() {
  local message="$1"
  echo "[WARN] ${message}" >&2
}

log_error() {
  local message="$1"
  echo "[ERROR] ${message}" >&2
}

die() {
  local message="$1"
  log_error "${message}"
  exit 1
}

# ----------------------------
# Basic environment discovery
# ----------------------------
script_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project_root_directory="${script_directory}"

python_executable="${PYTHON_EXECUTABLE:-python3.14}"
entrypoint_python_file="${ENTRYPOINT_PYTHON_FILE:-main_gtk4.py}"

application_identifier="${APPLICATION_IDENTIFIER:-linux-install-helper}"
application_display_name="${APPLICATION_DISPLAY_NAME:-Linux Install Helper}"

# ----------------------------
# Build directory layout
# ----------------------------
build_directory="${project_root_directory}/build_appimage"

virtual_environment_directory="${build_directory}/virtual_environment"

pyinstaller_build_directory="${build_directory}/pyinstaller_build"
pyinstaller_dist_directory="${build_directory}/pyinstaller_dist"

application_directory="${build_directory}/AppDir"
packaging_directory="${build_directory}/packaging"
tools_directory="${build_directory}/tools"
output_directory="${build_directory}/out"

linuxdeploy_appimage_path="${tools_directory}/linuxdeploy-x86_64.AppImage"
linuxdeploy_gtk_plugin_appimage_path="${tools_directory}/linuxdeploy-plugin-gtk-x86_64.AppImage"

desktop_file_path="${packaging_directory}/${application_identifier}.desktop"
icon_file_path="${packaging_directory}/${application_identifier}.png"

# ----------------------------
# Preflight checks
# ----------------------------
log_info "Project root directory: ${project_root_directory}"
log_info "Python executable:      ${python_executable}"
log_info "Entrypoint file:        ${entrypoint_python_file}"
log_info "App identifier:         ${application_identifier}"
log_info "App display name:       ${application_display_name}"
log_info "Build directory:        ${build_directory}"

if ! command -v "${python_executable}" >/dev/null 2>&1; then
  die "Python executable not found in PATH: ${python_executable}"
fi

if [[ ! -f "${project_root_directory}/${entrypoint_python_file}" ]]; then
  die "Entrypoint file not found: ${project_root_directory}/${entrypoint_python_file}"
fi

mkdir -p \
  "${build_directory}" \
  "${output_directory}" \
  "${tools_directory}" \
  "${packaging_directory}"

# Ensure AppImages can run even when FUSE is not available.
export APPIMAGE_EXTRACT_AND_RUN=1

cd "${project_root_directory}"

# ----------------------------
# Virtual environment setup
# ----------------------------
log_info "Resetting virtual environment: ${virtual_environment_directory}"
rm -rf "${virtual_environment_directory}"

log_info "Creating virtual environment..."
"${python_executable}" -m venv "${virtual_environment_directory}"

# shellcheck disable=SC1091
log_info "Activating virtual environment..."
source "${virtual_environment_directory}/bin/activate"

log_info "Upgrading pip/setuptools/wheel..."
python -m pip install --upgrade pip setuptools wheel

log_info "Installing/upgrading PyInstaller..."
python -m pip install --upgrade pyinstaller

if [[ -f "${project_root_directory}/requirements.txt" ]]; then
  log_info "Installing project dependencies from requirements.txt..."
  python -m pip install -r "${project_root_directory}/requirements.txt"
else
  log_warn "No requirements.txt found; skipping dependency install."
fi

# ----------------------------
# PyInstaller build (onedir)
# ----------------------------
log_info "Cleaning PyInstaller build output..."
rm -rf "${pyinstaller_build_directory}" "${pyinstaller_dist_directory}"
mkdir -p "${pyinstaller_build_directory}" "${pyinstaller_dist_directory}"

log_info "Running PyInstaller (onedir, windowed)..."
pyinstaller \
  --noconfirm \
  --clean \
  --onedir \
  --windowed \
  --name "${application_identifier}" \
  --workpath "${pyinstaller_build_directory}" \
  --distpath "${pyinstaller_dist_directory}" \
  "${entrypoint_python_file}"

pyinstaller_output_program_directory="${pyinstaller_dist_directory}/${application_identifier}"
pyinstaller_output_executable_path="${pyinstaller_output_program_directory}/${application_identifier}"

if [[ ! -d "${pyinstaller_output_program_directory}" ]]; then
  die "PyInstaller output directory missing: ${pyinstaller_output_program_directory}"
fi

if [[ ! -x "${pyinstaller_output_executable_path}" ]]; then
  die "PyInstaller executable missing or not executable: ${pyinstaller_output_executable_path}"
fi

log_info "PyInstaller output directory: ${pyinstaller_output_program_directory}"
log_info "PyInstaller executable:       ${pyinstaller_output_executable_path}"

# ----------------------------
# Desktop file + icon assets
# ----------------------------
if [[ ! -f "${desktop_file_path}" ]]; then
  log_warn "Desktop file not found; creating a minimal one: ${desktop_file_path}"
  cat > "${desktop_file_path}" <<DESKTOP
[Desktop Entry]
Type=Application
Name=${application_display_name}
Exec=${application_identifier}
Icon=${application_identifier}
Terminal=false
Categories=System;Utility;
DESKTOP
else
  log_info "Using existing desktop file: ${desktop_file_path}"
fi

if [[ ! -f "${icon_file_path}" ]]; then
  log_warn "Icon not found; creating a 1x1 PNG placeholder: ${icon_file_path}"
  base64 -d > "${icon_file_path}" <<'PNG_BASE64'
iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO7+XaoAAAAASUVORK5CYII=
PNG_BASE64
else
  log_info "Using existing icon file: ${icon_file_path}"
fi

# ----------------------------
# Assemble AppDir
# ----------------------------
log_info "Resetting AppDir: ${application_directory}"
rm -rf "${application_directory}"
mkdir -p "${application_directory}/usr/bin"

log_info "Copying PyInstaller (onedir) payload into AppDir..."
cp -a "${pyinstaller_output_program_directory}/." "${application_directory}/usr/bin/"

# ----------------------------
# Download helpers
# ----------------------------
download_file() {
  local url="$1"
  local destination_path="$2"

  # A crude sanity check so we do not treat an HTML error page or truncated file as "good".
  local minimum_bytes=1048576

  if [[ -f "${destination_path}" ]]; then
    local existing_size
    existing_size="$(wc -c < "${destination_path}")"
    if [[ "${existing_size}" -ge "${minimum_bytes}" ]]; then
      log_info "Already downloaded (looks OK): ${destination_path} (${existing_size} bytes)"
      return 0
    fi

    log_warn "Existing file looks too small; re-downloading: ${destination_path} (${existing_size} bytes)"
    rm -f "${destination_path}"
  fi

  log_info "Downloading: ${url}"
  log_info "Destination: ${destination_path}"

  if command -v curl >/dev/null 2>&1; then
    curl -fL -o "${destination_path}" "${url}"
  elif command -v wget >/dev/null 2>&1; then
    wget -O "${destination_path}" "${url}"
  else
    die "Missing curl/wget. Install one of them to download linuxdeploy tools."
  fi

  if [[ ! -s "${destination_path}" ]]; then
    die "Downloaded file is empty: ${destination_path}"
  fi

  local downloaded_size
  downloaded_size="$(wc -c < "${destination_path}")"
  if [[ "${downloaded_size}" -lt "${minimum_bytes}" ]]; then
    die "Downloaded file looks incomplete: ${destination_path} (${downloaded_size} bytes)"
  fi

  log_info "Download OK: ${destination_path} (${downloaded_size} bytes)"
}

# ----------------------------
# Download linuxdeploy + GTK plugin
# ----------------------------
log_info "Ensuring linuxdeploy tools are available..."
download_file \
  "https://github.com/linuxdeploy/linuxdeploy/releases/download/continuous/linuxdeploy-x86_64.AppImage" \
  "${linuxdeploy_appimage_path}"
log_info "downloading linuxdeploy-plugin-gtk-x86_64.AppImage"
download_file \
  "https://raw.githubusercontent.com/linuxdeploy/linuxdeploy-plugin-gtk/master/linuxdeploy-plugin-gtk.sh" \
  "${linuxdeploy_gtk_plugin_appimage_path}"

log_info "Marking linuxdeploy tools executable..."
chmod +x "${linuxdeploy_appimage_path}" "${linuxdeploy_gtk_plugin_appimage_path}"

# linuxdeploy discovers plugins by name (linuxdeploy-plugin-<name>) in PATH when using --plugin <name>
log_info "Creating PATH-visible plugin symlink..."
ln -sf "${linuxdeploy_gtk_plugin_appimage_path}" "${tools_directory}/linuxdeploy-plugin-gtk"
chmod +x "${tools_directory}/linuxdeploy-plugin-gtk"

export PATH="${tools_directory}:${PATH}"

# GTK plugin supports GTK4; we set it explicitly to avoid auto-detect surprises.
export DEPLOY_GTK_VERSION=4

log_info "DEPLOY_GTK_VERSION set to: ${DEPLOY_GTK_VERSION}"

# ----------------------------
# Build the AppImage
# ----------------------------
cd "${build_directory}"

log_info "Cleaning old AppImage outputs from build directory..."
rm -f ./*.AppImage || true

log_info "Running linuxdeploy to generate AppImage..."
"${linuxdeploy_appimage_path}" \
  --appdir "${application_directory}" \
  -d "${desktop_file_path}" \
  -i "${icon_file_path}" \
  --plugin gtk \
  --output appimage

generated_appimage_path="$(ls -1 ./*.AppImage | head -n 1 || true)"
if [[ -z "${generated_appimage_path}" ]]; then
  die "No AppImage was generated in: ${build_directory}"
fi

final_appimage_path="${output_directory}/$(basename "${generated_appimage_path}")"

log_info "Moving AppImage to output directory..."
mv -f "${generated_appimage_path}" "${final_appimage_path}"

log_info "AppImage created successfully:"
echo "${final_appimage_path}"
