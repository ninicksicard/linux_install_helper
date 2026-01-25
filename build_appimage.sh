#!/usr/bin/env bash
: <<'DOCSTRING'
build_appimage.sh
DOCSTRING

set -euo pipefail

project_root_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

python_executable="${PYTHON_EXECUTABLE:-python3.14}"
entrypoint_python_file="${ENTRYPOINT_PYTHON_FILE:-main_gtk4.py}"

application_identifier="${APPLICATION_IDENTIFIER:-linux-install-helper}"
application_display_name="${APPLICATION_DISPLAY_NAME:-Linux Install Helper}"

build_directory="${project_root_directory}/build_appimage"
virtual_environment_directory="${build_directory}/virtual_environment"
pyinstaller_build_directory="${build_directory}/pyinstaller_build"
pyinstaller_dist_directory="${build_directory}/pyinstaller_dist"

application_directory="${build_directory}/AppDir"
packaging_directory="${build_directory}/packaging"
tools_directory="${build_directory}/tools"
runtime_tools_directory=""
output_directory="${build_directory}/out"

linuxdeploy_appimage_path="${tools_directory}/linuxdeploy-x86_64.AppImage"
linuxdeploy_gtk_plugin_appimage_path="${tools_directory}/linuxdeploy-plugin-gtk-x86_64.AppImage"

desktop_file_path="${packaging_directory}/${application_identifier}.desktop"
icon_file_path="${packaging_directory}/${application_identifier}.png"

mkdir -p "${build_directory}" "${output_directory}" "${tools_directory}" "${packaging_directory}"

# Ensure AppImages can run even when FUSE is not available
export APPIMAGE_EXTRACT_AND_RUN=1

cd "${project_root_directory}"

# --- Virtual environment + dependencies ---
rm -rf "${virtual_environment_directory}"
"${python_executable}" -m venv "${virtual_environment_directory}"
# shellcheck disable=SC1091
source "${virtual_environment_directory}/bin/activate"

python -m pip install --upgrade pip setuptools wheel
python -m pip install --upgrade pyinstaller

if [[ -f "${project_root_directory}/requirements.txt" ]]; then
  python -m pip install -r "${project_root_directory}/requirements.txt"
fi

# --- PyInstaller build (onedir) ---
rm -rf "${pyinstaller_build_directory}" "${pyinstaller_dist_directory}"
mkdir -p "${pyinstaller_build_directory}" "${pyinstaller_dist_directory}"

# Windowed prevents console popups; remove if you want terminal output.
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

# --- Create minimal .desktop + icon if you don't have real assets yet ---
if [[ ! -f "${desktop_file_path}" ]]; then
  cat > "${desktop_file_path}" <<DESKTOP
[Desktop Entry]
Type=Application
Name=${application_display_name}
Exec=${application_identifier}
Icon=${application_identifier}
Terminal=false
Categories=System;Utility;
DESKTOP
fi

if [[ ! -f "${icon_file_path}" ]]; then
  # 1x1 PNG placeholder (replace later with a real 256x256 png if you want)
  base64 -d > "${icon_file_path}" <<'PNG_BASE64'
iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO7+XaoAAAAASUVORK5CYII=
PNG_BASE64
fi

# --- Assemble AppDir ---
rm -rf "${application_directory}"
mkdir -p "${application_directory}/usr/bin"

# Copy the entire PyInstaller onedir payload so the executable keeps its adjacent files
cp -a "${pyinstaller_output_program_directory}/." "${application_directory}/usr/bin/"

# --- Download linuxdeploy + gtk plugin ---
download_file() {
  local url="$1"
  local destination_path="$2"

  if command -v curl >/dev/null 2>&1; then
    curl -L -o "${destination_path}" "${url}"
    return 0
  fi

  if command -v wget >/dev/null 2>&1; then
    wget -O "${destination_path}" "${url}"
    return 0
  fi

  echo "Missing curl/wget. Install one of them to download linuxdeploy tools."
  exit 1
}

if [[ ! -f "${linuxdeploy_appimage_path}" ]]; then
  download_file \
    "https://github.com/linuxdeploy/linuxdeploy/releases/download/continuous/linuxdeploy-x86_64.AppImage" \
    "${linuxdeploy_appimage_path}"
fi

if [[ ! -f "${linuxdeploy_gtk_plugin_appimage_path}" ]]; then
  download_file \
    "https://github.com/linuxdeploy/linuxdeploy-plugin-gtk/releases/download/continuous/linuxdeploy-plugin-gtk-x86_64.AppImage" \
    "${linuxdeploy_gtk_plugin_appimage_path}"
fi

chmod +x "${linuxdeploy_appimage_path}" "${linuxdeploy_gtk_plugin_appimage_path}"

# linuxdeploy and plugin AppImages cannot execute on noexec mounts, so copy to a runtime directory.
runtime_tools_directory="$(mktemp -d "${TMPDIR:-/tmp}/linux-install-helper-runtime-tools-XXXXXX")"
cp -a "${linuxdeploy_appimage_path}" "${runtime_tools_directory}/linuxdeploy-x86_64.AppImage"
cp -a "${linuxdeploy_gtk_plugin_appimage_path}" "${runtime_tools_directory}/linuxdeploy-plugin-gtk-x86_64.AppImage"
chmod +x "${runtime_tools_directory}/linuxdeploy-x86_64.AppImage" "${runtime_tools_directory}/linuxdeploy-plugin-gtk-x86_64.AppImage"

# linuxdeploy discovers plugins by name (linuxdeploy-plugin-<name>) in PATH when using --plugin <name>
ln -sf "${runtime_tools_directory}/linuxdeploy-plugin-gtk-x86_64.AppImage" "${runtime_tools_directory}/linuxdeploy-plugin-gtk"
chmod +x "${runtime_tools_directory}/linuxdeploy-plugin-gtk"
export PATH="${runtime_tools_directory}:${PATH}"

linuxdeploy_appimage_path="${runtime_tools_directory}/linuxdeploy-x86_64.AppImage"
linuxdeploy_gtk_plugin_appimage_path="${runtime_tools_directory}/linuxdeploy-plugin-gtk-x86_64.AppImage"

# GTK plugin supports GTK4; we set it explicitly to avoid auto-detect surprises
export DEPLOY_GTK_VERSION=4

# --- Build AppImage ---
cd "${build_directory}"
rm -f ./*.AppImage

"${linuxdeploy_appimage_path}" \
  --appdir "${application_directory}" \
  -d "${desktop_file_path}" \
  -i "${icon_file_path}" \
  --plugin gtk \
  --output appimage

generated_appimage_path="$(ls -1 ./*.AppImage | head -n 1)"
final_appimage_path="${output_directory}/$(basename "${generated_appimage_path}")"

mv -f "${generated_appimage_path}" "${final_appimage_path}"

echo "AppImage created:"
echo "${final_appimage_path}"
