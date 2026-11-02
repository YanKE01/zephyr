#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Run in a child shell: never change the caller's shell options or directory.
set -euo pipefail

BASE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)
TOOLS="$BASE/build/host-tools"
VENV="$BASE/build/venv-f101-4.5"
TOOLCHAIN_NAME=Xuantie-900-gcc-elf-newlib-x86_64-V3.2.0
TOOLCHAIN="$BASE/build/toolchains/$TOOLCHAIN_NAME"
ARCHIVE="$TOOLCHAIN_NAME-20250627.tar.gz"
TOOLCHAIN_URL="https://occ-oss-prod.oss-cn-hangzhou.aliyuncs.com/resource//1751370399722/$ARCHIVE"
TOOLCHAIN_SHA256=80c174c6445f7565bc082d328045021862a63beddfad8c393c534e2d9523dc3b
XFEL_REV=445e8aefe6914c85817cc9bd1d201629364b0ec6
RULE="$BASE/scripts/f101/70-f101-fel.rules"
RULE_DEST=/etc/udev/rules.d/70-f101-fel.rules
CHECK=0
USB=1
USB_ONLY=0

die() { echo "F101 setup: $*" >&2; exit 1; }
for arg in "$@"; do
    case "$arg" in
        --check) CHECK=1 ;;
        --no-usb) USB=0 ;;
        --usb-only) USB_ONLY=1 ;;
        --help|-h)
            cat <<'EOF'
Usage: source ./export.sh [--check] [--no-usb]

Default: install missing tools/dependencies, initialize west, and configure
FEL USB access. Supports Linux x86_64; system package installation uses apt.
Tools are stored in build/. The old .venv/ is retained for Zephyr 4.2.

  --check     Check the build environment without downloads or system changes.
  --no-usb    Skip USB permissions (for CI or building without a board).
  --usb-only  Install/reload the USB rule only; may ask for a sudo password.

First-time system packages/USB rules require administrator access. Builds and
FEL downloads run as your normal user afterwards. Do not source with sudo.
EOF
            exit 0 ;;
        *) die "Unknown option: $arg (use --help)" ;;
    esac
done

[[ $(uname -s) == Linux && $(uname -m) == x86_64 ]] ||
    die 'The bundled toolchain requires Linux x86_64 (including WSL2).'

root_command() {
    if (( EUID == 0 )); then
        "$@"
    else
        command -v sudo >/dev/null || die 'sudo is needed for first-time system setup.'
        sudo -- "$@"
    fi
}

setup_usb() {
    if cmp -s "$RULE" "$RULE_DEST"; then
        return
    fi
    if (( CHECK )); then
        echo 'FEL USB rule is not installed (builds are available).'
        return
    fi
    if ! command -v udevadm >/dev/null; then
        echo 'udev is unavailable; configure USB access on the host before downloading.'
        return
    fi
    if (( EUID != 0 )) && ! sudo -n true 2>/dev/null && [[ ! -t 0 ]]; then
        echo 'One-time USB permission setup needs a password in your terminal:'
        printf '  bash %q --usb-only\n' "$BASE/scripts/f101/setup.sh"
        return
    fi
    echo 'Installing the FEL USB rule (one-time administrator access).'
    root_command install -m 0644 "$RULE" "$RULE_DEST"
    root_command udevadm control --reload-rules
    root_command udevadm trigger --action=add --subsystem-match=usb \
        --attr-match=idVendor=1f3a --attr-match=idProduct=efe8
    root_command udevadm settle
    echo 'FEL USB rule installed. Reconnect in FEL mode if access is still denied.'
}

if (( USB_ONLY )); then
    setup_usb
    exit 0
fi

export PATH="$TOOLS/bin:$PATH"
ensure_host_tools() {
    local spec cmd pkg
    local -a packages=()
    for spec in git:git curl:curl gperf:gperf \
                gcc:build-essential g++:build-essential make:build-essential \
                pkg-config:pkg-config python3:python3 tar:tar dtc:device-tree-compiler; do
        cmd=${spec%%:*}
        pkg=${spec#*:}
        command -v "$cmd" >/dev/null || packages+=("$pkg")
    done
    if ! pkg-config --exists libusb-1.0 2>/dev/null; then
        packages+=(libusb-1.0-0-dev)
    fi
    if (( ${#packages[@]} )); then
        (( ! CHECK )) || die "Missing system packages: ${packages[*]}"
        command -v apt-get >/dev/null || die "Install system packages: ${packages[*]}"
        echo "Installing missing system packages: ${packages[*]}"
        root_command apt-get update
        root_command apt-get install -y --no-install-recommends "${packages[@]}"
    fi
}

setup_python() {
    local python uv digest stamp
    python=$(command -v python3)
    # Prefer the system interpreter to an activated Conda/other project environment.
    if [[ -x /usr/bin/python3 ]]; then python=/usr/bin/python3; fi
    if (( CHECK )); then
        [[ -x "$VENV/bin/west" ]] || die 'Missing Zephyr 4.5 environment; source export.sh first.'
        "$VENV/bin/python" -c 'import sys; sys.exit(sys.version_info < (3, 12))' ||
            die 'Zephyr 4.5 requires Python 3.12 or newer; source export.sh first.'
        "$VENV/bin/python" -c 'import west, elftools, yaml, serial'
        "$VENV/bin/python" -c \
            'from importlib.metadata import version; from packaging.version import Version; assert Version(version("cmake")) >= Version("3.28")' ||
            die 'CMake 3.28 or newer is required; source export.sh first.'
        "$VENV/bin/ninja" --version >/dev/null
        return
    fi
    export UV_CACHE_DIR="$BASE/build/.uv-cache"
    uv=$(command -v uv || true)
    if [[ -z "$uv" ]]; then
        uv="$TOOLS/uv-venv/bin/uv"
        if [[ ! -x "$uv" ]]; then
            if ! "$python" -m venv "$TOOLS/uv-venv"; then
                command -v apt-get >/dev/null || die 'Install Python venv support and retry.'
                root_command apt-get install -y python3-venv
                "$python" -m venv "$TOOLS/uv-venv"
            fi
            "$TOOLS/uv-venv/bin/python" -m pip install 'uv==0.9.20'
        fi
    fi
    if [[ ! -x "$VENV/bin/python" ]]; then
        "$uv" venv --python 3.12 "$VENV"
    fi
    "$VENV/bin/python" -c 'import sys; sys.exit(sys.version_info < (3, 12))' ||
        die "Python in $VENV is too old; move that environment aside and source export.sh again."
    digest=$(sha256sum "$BASE"/scripts/requirements*.txt "$BASE/scripts/f101/setup.sh" |
        sha256sum | cut -d ' ' -f 1)
    stamp="$VENV/.f101-requirements.sha256"
    if [[ ! -f "$stamp" || $(cat "$stamp") != "$digest" || ! -x "$VENV/bin/west" ]]; then
        "$uv" pip install --python "$VENV/bin/python" -r "$BASE/scripts/requirements.txt" \
            'cmake>=3.28' ninja
        "$uv" pip check --python "$VENV/bin/python"
        printf '%s\n' "$digest" > "$stamp"
    fi
}

setup_west() {
    local west top manifest states digest stamp relative
    west="$VENV/bin/west"
    cd "$BASE"
    if ! top=$("$west" topdir 2>/dev/null); then
        (( ! CHECK )) || die 'No west workspace; source export.sh first.'
        "$west" init -l "$BASE"
        top=$("$west" topdir)
    fi
    manifest=$("$west" list manifest -f '{abspath}')
    [[ $(realpath "$manifest") == "$BASE" ]] ||
        die "The enclosing west workspace uses another manifest: $manifest"
    states=$("$west" list -f '{cloned}')
    digest=$(sha256sum "$BASE/west.yml" | cut -d ' ' -f 1)
    stamp="$BASE/build/.f101-west.sha256"
    if [[ "$states" == *not-cloned* || ! -f "$stamp" || $(cat "$stamp") != "$digest" ]]; then
        (( ! CHECK )) || die 'west modules need updating; source export.sh first.'
        "$west" update --narrow -o=--depth=1
    fi
    if (( ! CHECK )); then
        # Avoid west modifying this configuration on the first build.
        relative=${BASE#"$top"/}
        if [[ $("$west" config zephyr.base 2>/dev/null || true) != "$relative" ]]; then
            "$west" config zephyr.base "$relative"
        fi
        if [[ ! -f "$stamp" || $(cat "$stamp") != "$digest" ]]; then
            printf '%s\n' "$digest" > "$stamp"
        fi
    fi
}

setup_toolchain() {
    local archive staging
    if [[ ! -x "$TOOLCHAIN/bin/riscv64-unknown-elf-gcc" ]]; then
        (( ! CHECK )) || die 'Missing XuanTie toolchain; source export.sh first.'
        [[ ! -e "$TOOLCHAIN" ]] || die "Incomplete toolchain at $TOOLCHAIN; move it aside and retry."
        mkdir -p "$BASE/build/toolchains"
        archive="$BASE/build/toolchains/$ARCHIVE"
        if [[ ! -f "$archive" ]]; then
            curl -fL --retry 3 --connect-timeout 20 -C - -o "$archive.part" "$TOOLCHAIN_URL"
            mv "$archive.part" "$archive"
        fi
        printf '%s  %s\n' "$TOOLCHAIN_SHA256" "$archive" | sha256sum -c - ||
            die "Toolchain checksum mismatch; remove $archive and retry."
        staging=$(mktemp -d "$BASE/build/toolchains/.unpack.XXXXXX")
        tar --no-same-owner -xzf "$archive" -C "$staging"
        mv "$staging/$TOOLCHAIN_NAME" "$TOOLCHAIN"
        rmdir "$staging"
    fi
    "$TOOLCHAIN/bin/riscv64-unknown-elf-gcc" --version >/dev/null
}

setup_xfel() {
    if [[ ! -x "$TOOLS/xfel/xfel" ]]; then
        (( ! CHECK )) || die 'Missing xfel; source export.sh first.'
        if [[ ! -d "$TOOLS/xfel/.git" ]]; then
            git init "$TOOLS/xfel"
            git -C "$TOOLS/xfel" remote add origin https://github.com/xboot/xfel.git
        fi
        if ! git -C "$TOOLS/xfel" rev-parse --verify HEAD >/dev/null 2>&1; then
            git -C "$TOOLS/xfel" fetch --depth=1 origin "$XFEL_REV"
            git -C "$TOOLS/xfel" checkout --detach FETCH_HEAD
        fi
        make -C "$TOOLS/xfel" -j4
    fi
    "$TOOLS/xfel/xfel" --help >/dev/null
}

if (( ! CHECK )); then mkdir -p "$TOOLS"; fi
ensure_host_tools
setup_python
setup_west
setup_toolchain
if (( CHECK )); then
    bash "$BASE/scripts/f101/setup-loader.sh" --check
else
    bash "$BASE/scripts/f101/setup-loader.sh"
fi
setup_xfel
if (( USB )); then setup_usb; fi
