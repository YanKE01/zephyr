#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Build the pinned YuzukiNeko SPI NOR bootloader used by f101.py flash.
set -euo pipefail
BASE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)
SOURCE="$BASE/build/host-tools/SyterKit"
OUTPUT="$BASE/build/f101-loader"
REVISION=6ef3f27abd547439cb2de4e455e40a2cbfbebff8
IMAGE="$OUTPUT/build/yuzukineko/app_sram/flash-boot/flash-boot_spi.bin"
COMPILER="$BASE/build/toolchains/Xuantie-900-gcc-elf-newlib-x86_64-V3.2.0/bin/riscv64-unknown-elf-"

if [[ -s "$IMAGE" && -f "$OUTPUT/.source-revision" &&
      $(cat "$OUTPUT/.source-revision") == "$REVISION" ]]; then
    exit 0
fi
if [[ ${1:-} == --check ]]; then
    echo 'SPI NOR loader is missing; source ./export.sh to build it.' >&2
    exit 1
fi

# Reuse locally unpacked ncurses headers when present (no system install needed).
LOCAL_NCURSES="$BASE/build/host-tools/ncurses-package"
if [[ -d "$LOCAL_NCURSES/usr/lib/x86_64-linux-gnu/pkgconfig" ]]; then
    export PKG_CONFIG_PATH="$LOCAL_NCURSES/usr/lib/x86_64-linux-gnu/pkgconfig"
    export PKG_CONFIG_SYSROOT_DIR="$LOCAL_NCURSES"
fi
packages=()
command -v flex >/dev/null || packages+=(flex)
command -v bison >/dev/null || packages+=(bison)
pkg-config --exists ncursesw || packages+=(libncurses-dev)
if (( ${#packages[@]} )); then
    echo "Installing loader build dependencies: ${packages[*]}"
    sudo apt-get install -y --no-install-recommends "${packages[@]}"
fi
if [[ ! -d "$SOURCE/.git" ]]; then
    git init "$SOURCE"
    git -C "$SOURCE" remote add origin https://github.com/YuzukiHD/SyterKit.git
fi
if ! git -C "$SOURCE" rev-parse --verify HEAD >/dev/null 2>&1; then
    git -C "$SOURCE" fetch --depth=1 origin "$REVISION"
    git -C "$SOURCE" checkout --detach FETCH_HEAD
fi
if [[ $(git -C "$SOURCE" rev-parse HEAD) != "$REVISION" ]]; then
    echo "Unexpected SyterKit revision in $SOURCE; move it aside and retry." >&2
    exit 1
fi
mkdir -p "$OUTPUT"
export KCONFIG_NOSILENTUPDATE=1
echo 'Building the YuzukiNeko SPI NOR bootloader...'
build_loader() {
    make -C "$SOURCE" O="$OUTPUT" CROSS_COMPILE="$COMPILER" yuzukineko_rv32_sram_defconfig &&
    make -C "$SOURCE" O="$OUTPUT" CROSS_COMPILE="$COMPILER" olddefconfig &&
    make -C "$SOURCE" O="$OUTPUT" CROSS_COMPILE="$COMPILER" -j4 flash-boot
}
if ! build_loader > "$OUTPUT/build.log" 2>&1; then
    tail -50 "$OUTPUT/build.log" >&2
    exit 1
fi
test -s "$IMAGE"
printf '%s\n' "$REVISION" > "$OUTPUT/.source-revision"
echo "SPI NOR loader ready: $IMAGE"
