#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Build, program F101 SPI NOR, and monitor the UART from one command."""

import argparse
import os
import re
import select
import shlex
import shutil
import subprocess
import sys
import tempfile
import termios
import threading
import time
from pathlib import Path

from f101_nor import FlashError, NorFlasher

BASE = Path(__file__).resolve().parents[2]
LOAD_ADDRESS = 0x40000000
RAM_SIZE = 0x1000000


class ToolError(Exception):
    pass


def message(text):
    print(text, flush=True)


def run(command, *, capture=False, timeout=None):
    command = [str(arg) for arg in command]
    message("+ " + shlex.join(command))
    try:
        result = subprocess.run(
            command,
            cwd=BASE,
            text=True,
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.STDOUT if capture else None,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise ToolError(f"Missing {command[0]}; source ./export.sh first.") from exc
    except subprocess.TimeoutExpired as exc:
        raise ToolError(f"Command timed out: {shlex.join(command)}") from exc
    if capture and result.stdout:
        message(result.stdout.rstrip())
    if result.returncode:
        raise ToolError(f"Command failed (exit {result.returncode}): {shlex.join(command)}")
    return result.stdout or ""


def xfel(*args):
    timeout = 600 if args[0] == "spinor" else 90
    output = run([BASE / "build/host-tools/xfel/xfel", *args], capture=True, timeout=timeout)
    # xfel can report USB errors while returning status 0. Never execute a bad upload.
    if args[0] in ("exec", "reset"):
        remaining = re.sub(r"usb bulk (?:send|recv) error", "", output, flags=re.I)
        if remaining != output:
            message("FEL disconnected during startup; confirm the UART output.")
        output = remaining
    if re.search(r"\berror\b|\bfailed\b|not support|can't", output, re.I):
        raise ToolError("xfel reported an error; the next step was not executed.")
    return output


def fel_devices():
    devices = []
    for device in Path("/sys/bus/usb/devices").glob("*"):
        try:
            if (device / "idVendor").read_text().strip() == "1f3a" and (
                device / "idProduct"
            ).read_text().strip() == "efe8":
                devices.append(device)
        except OSError:
            continue
    return devices


def wait_for_fel(seconds):
    executable = BASE / "build/host-tools/xfel/xfel"
    if not executable.is_file():
        raise ToolError("xfel is missing; source ./export.sh first.")
    deadline = time.monotonic() + seconds
    prompted = False
    while True:
        if len(fel_devices()) > 1:
            raise ToolError(
                "Multiple FEL devices are connected. Leave only the target board connected."
            )
        try:
            result = subprocess.run(
                [str(executable), "version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except subprocess.TimeoutExpired as exc:
            raise ToolError("FEL USB did not respond. Reconnect the board in FEL mode.") from exc
        output = result.stdout + result.stderr
        if "Can't connect to device" in output:
            raise ToolError(
                "FEL USB access denied. Run 'source ./export.sh' in your terminal to "
                "install the USB rule, then reconnect the board."
            )
        if result.returncode == 0 and "AWUSBFEX" in output:
            if "(F101)" not in output:
                raise ToolError(f"Expected an F101, found: {output.strip()}")
            message(output.strip())
            return
        if "No FEL device found" not in output:
            raise ToolError(f"Cannot query FEL: {output.strip()}")
        if not prompted:
            message(
                f"Waiting up to {seconds:g}s for FEL. Hold FEL while powering on/reconnecting "
                "the board, then release it. Ctrl+C cancels."
            )
            prompted = True
        if time.monotonic() >= deadline:
            raise ToolError("No FEL device appeared. Enter FEL mode and retry.")
        time.sleep(min(0.5, max(0, deadline - time.monotonic())))


def select_port(port):
    if port:
        return port
    from serial.tools import list_ports

    # Ignore the many unused /dev/ttyS* ports. Never guess between multiple USB adapters.
    candidates = [p for p in list_ports.comports() if p.vid is not None]
    if len(candidates) == 1:
        return candidates[0].device
    if not candidates:
        raise ToolError("No USB UART found. Connect an adapter or specify -p /dev/ttyUSB0.")
    choices = ", ".join(f"{p.device} ({p.description})" for p in candidates)
    raise ToolError(f"Multiple USB UARTs found: {choices}. Select one with -p.")


class Monitor:
    """Read UART before exec; enable keyboard input only after download completes."""

    def __init__(self, port, baud):
        import serial

        self.stop = threading.Event()
        self.failure = None
        self.thread = None
        self.serial = serial.Serial(
            port=None,
            baudrate=baud,
            timeout=0.1,
            write_timeout=2,
            exclusive=True,
            xonxoff=False,
            rtscts=False,
            dsrdtr=False,
        )
        self.serial.port = port
        self.serial.dtr = False
        self.serial.rts = False

    def __enter__(self):
        import serial

        try:
            self.serial.open()
        except serial.SerialException as exc:
            self.serial.close()
            raise ToolError(
                f"Cannot open {self.serial.port}: {exc}. Close picocom/other monitors first."
            ) from exc
        message(f"Monitor: {self.serial.port}, {self.serial.baudrate} 8N1. Exit: Ctrl+]")
        self.thread = threading.Thread(target=self.receive, daemon=True)
        self.thread.start()
        return self

    def receive(self):
        import serial

        try:
            while not self.stop.is_set():
                data = self.serial.read(self.serial.in_waiting or 1)
                if data:
                    sys.stdout.buffer.write(data)
                    sys.stdout.buffer.flush()
        except (serial.SerialException, OSError) as exc:
            self.failure = exc
            self.stop.set()

    def interact(self):
        fd = sys.stdin.fileno()
        previous = termios.tcgetattr(fd)
        current = termios.tcgetattr(fd)
        current[3] &= ~(termios.ICANON | termios.ECHO | termios.ISIG)
        current[6][termios.VMIN] = 1
        current[6][termios.VTIME] = 0
        try:
            termios.tcsetattr(fd, termios.TCSANOW, current)
            while not self.stop.is_set():
                ready, _, _ = select.select([fd], [], [], 0.1)
                if ready:
                    data = os.read(fd, 1024)
                    if not data:
                        break
                    before, exit_key, _ = data.partition(b"\x1d")
                    if before:
                        self.serial.write(before.replace(b"\n", b"\r"))
                    if exit_key:
                        break
        finally:
            termios.tcsetattr(fd, termios.TCSANOW, previous)
        if self.failure:
            raise ToolError(f"UART disconnected: {self.failure}")

    def __exit__(self, *args):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=1)
        self.serial.close()
        message("\nMonitor closed.")


def validate_image(build_dir):
    from elftools.elf.elffile import ELFFile

    binary = build_dir / "zephyr/zephyr.bin"
    elf = build_dir / "zephyr/zephyr.elf"
    if not binary.is_file() or not elf.is_file():
        raise ToolError(f"Missing zephyr.bin/zephyr.elf in {build_dir}; build first.")
    if not 0 < binary.stat().st_size <= RAM_SIZE:
        raise ToolError("The image is empty or exceeds the 16 MiB F101 PSRAM.")
    with elf.open("rb") as stream:
        image = ELFFile(stream)
        if (
            image.elfclass != 32
            or image.header["e_machine"] != "EM_RISCV"
            or image.header["e_entry"] != LOAD_ADDRESS
        ):
            raise ToolError("Expected an RV32 ELF with entry point 0x40000000.")
    return binary


def upload(binary):
    message("Downloading to PSRAM (lost on power-off; SPI NOR is unchanged).")
    xfel("ddr", "f101-s3")
    xfel("write", hex(LOAD_ADDRESS), binary)
    with tempfile.TemporaryDirectory(prefix=".fel-verify-", dir=binary.parent) as tmp:
        readback = Path(tmp) / "readback.bin"
        xfel("read", hex(LOAD_ADDRESS), str(binary.stat().st_size), readback)
        if not readback.is_file() or readback.read_bytes() != binary.read_bytes():
            raise ToolError("PSRAM readback differs from the firmware; execution was cancelled.")
    message("PSRAM readback verified.")


def clear_build(args):
    allowed = {args.app / "build"}
    if args.app == BASE / "samples/hello_world":
        allowed.update({BASE / "build/neko-hello", BASE / "build/f101-hello"})
    if args.build_dir not in allowed or args.build_dir == BASE / "build":
        raise ToolError(
            "clear only removes the application's build/ or the default Hello World output."
        )
    if args.build_dir.is_symlink():
        raise ToolError("Refusing to clear a build directory that is a symbolic link.")
    if args.build_dir.exists():
        shutil.rmtree(args.build_dir)
        message(f"Removed {args.build_dir}")
    else:
        message(f"Nothing to clear: {args.build_dir}")


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="F101 configure / build / SPI NOR flash / monitor (source export.sh first).",
        epilog="Example: f101.py -p /dev/ttyUSB0 build flash monitor. Exit monitor with Ctrl+].",
    )
    parser.add_argument(
        "actions",
        nargs="*",
        metavar="ACTION",
        help="clear, menuconfig, build, flash, ram, monitor (default: build flash monitor)",
    )
    parser.add_argument("-b", "--board", choices=("yuzukineko", "f101_evb"), default="yuzukineko")
    parser.add_argument(
        "-a",
        "--app",
        type=Path,
        help="Application directory (default: current directory; hello_world at Zephyr root)",
    )
    parser.add_argument(
        "-d", "--build-dir", type=Path, help="Override the application's build directory"
    )
    parser.add_argument("-p", "--port", help="UART device (auto-detect a single USB UART)")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--wait-fel", type=float, default=60, metavar="SECONDS")
    parser.add_argument("--pristine", action="store_true", help="Reconfigure from scratch")
    args = parser.parse_intermixed_args(argv)
    unknown = set(args.actions) - {"clear", "menuconfig", "build", "flash", "ram", "monitor"}
    if unknown:
        parser.error("Unknown action(s): " + ", ".join(sorted(unknown)))
    if args.baud <= 0 or not 0 <= args.wait_fel < float("inf"):
        parser.error("--baud must be positive and --wait-fel must be finite and nonnegative")
    args.actions = set(args.actions or ("build", "flash", "monitor"))
    if {"flash", "ram"} <= args.actions:
        parser.error("Choose flash (persistent) or ram (volatile), not both.")
    if "flash" in args.actions and args.board != "yuzukineko":
        parser.error("Persistent flash currently supports YuzukiNeko; use ram for F101 EVB.")
    if args.actions & {"flash", "ram"}:
        args.actions.add("build")
    root_default = args.app is None and Path.cwd() == BASE
    if args.app is None:
        args.app = BASE / "samples/hello_world" if root_default else Path.cwd()
    args.app = args.app.resolve()
    if (
        args.actions & {"clear", "build", "menuconfig"}
        and not (args.app / "CMakeLists.txt").is_file()
    ):
        parser.error(
            f"No CMakeLists.txt in {args.app}. Enter an application directory or use --app PATH."
        )
    if args.build_dir is None:
        if root_default:
            prefix = "neko" if args.board == "yuzukineko" else "f101"
            args.build_dir = BASE / "build" / f"{prefix}-hello"
        else:
            args.build_dir = args.app / "build"
    # Keep the final symlink visible so clear never follows it into another output.
    args.build_dir = (
        args.build_dir.absolute() if "clear" in args.actions else args.build_dir.resolve()
    )
    if args.build_dir == BASE / "build":
        parser.error("Use a subdirectory such as build/neko-hello; build/ also contains the tools.")
    return args


def main(argv=None):
    args = parse_args(argv)
    try:
        if "clear" in args.actions:
            clear_build(args)
        if "menuconfig" in args.actions and not sys.stdin.isatty():
            raise ToolError("Menuconfig needs an interactive terminal. Run it in your terminal.")
        if "monitor" in args.actions and not sys.stdin.isatty():
            raise ToolError("Monitor needs an interactive terminal. Run it in your terminal.")
        if args.actions & {"menuconfig", "build"}:
            python = BASE / "build/venv-f101-4.5/bin/python"
            if sys.version_info < (3, 12) or not python.is_file():
                raise ToolError(
                    f"Zephyr 4.5 needs its Python 3.12+ environment. Run: source {BASE}/export.sh"
                )
            command = [
                python,
                "-m",
                "west",
                "build",
                "-b",
                args.board,
                "-d",
                args.build_dir,
                args.app,
            ]
            pristine = ["-p", "always"] if args.pristine else []
            if "menuconfig" in args.actions:
                # west configures a new build directory before opening this target.
                run(command + pristine + ["-t", "menuconfig"])
                # Preserve the settings just saved, even with --pristine menuconfig build.
                pristine = []
            if "build" in args.actions:
                run(command + pristine)
        binary = None
        loader = None
        if args.actions & {"flash", "ram"}:
            binary = validate_image(args.build_dir)
            if "flash" in args.actions:
                run(["bash", BASE / "scripts/f101/setup-loader.sh"])
                loader = (
                    BASE
                    / "build/f101-loader/build/yuzukineko/app_sram/flash-boot"
                    / "flash-boot_spi.bin"
                )
            wait_for_fel(args.wait_fel)

        def program():
            if loader:
                NorFlasher(BASE, xfel, message).flash(binary, loader)
                message("Restarting from SPI NOR (release the FEL / PD5 buttons)...")
                xfel("reset")
            else:
                upload(binary)
                xfel("exec", hex(LOAD_ADDRESS))

        if "monitor" in args.actions:
            # Open before upload/exec so even the first Hello World line is retained.
            with Monitor(select_port(args.port), args.baud) as monitor:
                if binary:
                    program()
                monitor.interact()
        elif binary:
            program()
        return 0
    except KeyboardInterrupt:
        message("\nCancelled.")
        return 130
    except (ToolError, FlashError, OSError, ImportError) as exc:
        message(f"Error: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
