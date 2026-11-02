#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Load with: source /path/to/zephyr/export.sh (bash or zsh).

if [ -n "${ZSH_VERSION:-}" ]; then
    case "$ZSH_EVAL_CONTEXT" in
        *:file) _f101_export_file="${(%):-%x}" ;;
        *) echo 'Please use: source ./export.sh' >&2; exit 1 ;;
    esac
elif [ -n "${BASH_VERSION:-}" ]; then
    if [ "${BASH_SOURCE[0]}" = "$0" ]; then
        echo 'Please use: source ./export.sh' >&2
        exit 1
    fi
    _f101_export_file="${BASH_SOURCE[0]}"
else
    echo 'export.sh requires bash or zsh.' >&2
    return 1 2>/dev/null || exit 1
fi

_f101_export() {
    local base entry arg
    base=$(cd -- "$(dirname -- "$_f101_export_file")" && pwd -P) || return 1
    bash "$base/scripts/f101/setup.sh" "$@" || return 1
    for arg in "$@"; do
        case "$arg" in --help|-h|--usb-only) return 0 ;; esac
    done

    . "$base/build/venv-f101-4.5/bin/activate" || return 1
    export ZEPHYR_BASE="$base"
    export ZEPHYR_TOOLCHAIN_VARIANT=cross-compile
    export CROSS_COMPILE="$base/build/toolchains/Xuantie-900-gcc-elf-newlib-x86_64-V3.2.0/bin/riscv64-unknown-elf-"
    for entry in "$base/scripts/f101" "${CROSS_COMPILE%/*}" "$base/build/host-tools/xfel" \
                 "$base/build/host-tools/bin" "$base/build/host-tools/uv-venv/bin"; do
        [ -d "$entry" ] || continue
        case ":$PATH:" in *":$entry:"*) ;; *) export PATH="$entry:$PATH" ;; esac
    done
    echo 'F101 environment ready (YuzukiNeko / F101 EVB).'
    echo '  f101.py build flash monitor'
    echo '  f101.py monitor  (exit with Ctrl+])'
}

if _f101_export "$@"; then
    unset -f _f101_export
    unset _f101_export_file
    return 0
else
    unset -f _f101_export
    unset _f101_export_file
    return 1
fi
