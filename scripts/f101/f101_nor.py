# SPDX-License-Identifier: Apache-2.0
"""Persistent F101 images, original-flash backup, and verified SPI NOR writes."""

import hashlib
import json
import os
import re
import struct
import tempfile
from datetime import datetime, timezone
from pathlib import Path

FLASH_SIZE = 0x1000000
APP_OFFSET = 0x200000
APP_MAX_SIZE = 0x9F0000
HEADER_SIZE = 0x1000
LOAD_ADDRESS = 0x40000000
LOADER_OFFSETS = (0, 0x10000, 0x20000)
LOADER_LIMIT = 0xF000  # never touch the sample-point sector at 0x2f000
BOOT_MAGIC = 0x44524146
BOOT_VERSION = 2


class FlashError(Exception):
    pass


def app_image(payload):
    if not 0 < len(payload) <= APP_MAX_SIZE:
        raise FlashError(f"Application must contain 1..{APP_MAX_SIZE} bytes.")
    header = struct.pack("<8I", BOOT_MAGIC, BOOT_VERSION, LOAD_ADDRESS, len(payload), 0, 0, 0, 0)
    return header.ljust(HEADER_SIZE, b"\xff") + payload


def validate_loader(data):
    if not 0x40 <= len(data) <= LOADER_LIMIT or data[4:12] != b"eGON.BT0":
        raise FlashError("Invalid or oversized SPI NOR bootloader.")
    checksum, length = struct.unpack_from("<II", data, 12)
    if length != len(data) or length % 4:
        raise FlashError("Invalid bootloader length in eGON header.")
    words = list(struct.unpack(f"<{length // 4}I", data))
    words[3] = 0x5F0A6C39
    if sum(words) & 0xFFFFFFFF != checksum:
        raise FlashError("Bootloader eGON checksum mismatch.")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def save_synced(path, data):
    with path.open("wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


class NorFlasher:
    def __init__(self, base, xfel, message):
        self.base = Path(base)
        self.xfel = xfel
        self.message = message

    def identify(self):
        description = self.xfel("spinor")
        match = re.search(r"Found spi nor flash '([^']+)' with (\d+) bytes", description)
        if not match or int(match[2]) != FLASH_SIZE:
            raise FlashError("This boot layout requires a detected 16 MiB SPI NOR.")
        sid = self.xfel("sid").strip().lower()
        if not re.fullmatch(r"[0-9a-f]{32}", sid):
            raise FlashError("Cannot identify the chip SID; no Flash will be overwritten.")
        return sid

    def read(self, offset, size, destination):
        self.xfel("spinor", "read", hex(offset), hex(size), destination)
        if not destination.is_file() or destination.stat().st_size != size:
            raise FlashError(f"Short SPI NOR read at {offset:#x}; expected {size} bytes.")
        return destination.read_bytes()

    def backup(self, sid):
        folder = self.base / "flash-backups" / sid
        folder.mkdir(parents=True, exist_ok=True)
        original = folder / "original.bin"
        metadata = folder / "original.json"
        if metadata.exists():
            try:
                record = json.loads(metadata.read_text())
                data = original.read_bytes()
                valid = (
                    record["sid"] == sid
                    and record["size"] == len(data) == FLASH_SIZE
                    and record["sha256"] == digest(data)
                )
            except (OSError, ValueError, KeyError):
                valid = False
            if not valid:
                raise FlashError(
                    f"Original backup is incomplete/corrupt: {folder}. No write performed."
                )
            self.message(f"Original Flash backup retained: {original}")
            return original

        self.message("Backing up the original 16 MiB Flash and verifying a second full read...")
        with tempfile.TemporaryDirectory(prefix=".verify-", dir=folder) as tmp:
            if original.exists():
                first = original.read_bytes()
            else:
                first = self.read(0, FLASH_SIZE, Path(tmp) / "first.bin")
            second = self.read(0, FLASH_SIZE, Path(tmp) / "second.bin")
            if len(first) != FLASH_SIZE or first != second:
                raise FlashError("Original Flash backup verification failed. No write performed.")
            if not original.exists():
                temporary = folder / "original.bin.partial"
                save_synced(temporary, first)
                temporary.replace(original)
        record = {
            "sid": sid,
            "size": FLASH_SIZE,
            "sha256": digest(first),
            "created_utc": datetime.now(timezone.utc).isoformat(),
        }
        temporary = folder / "original.json.partial"
        save_synced(temporary, (json.dumps(record, indent=2) + "\n").encode())
        temporary.replace(metadata)
        directory = os.open(folder, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        self.message(f"Original Flash backup verified: {original}")
        return original

    def write_verified(self, offset, image, scratch):
        self.xfel("spinor", "write", hex(offset), image)
        expected = image.read_bytes()
        actual = self.read(offset, len(expected), scratch / "readback.bin")
        if actual != expected:
            raise FlashError(f"SPI NOR verification failed at {offset:#x}; reset cancelled.")
        self.message(f"SPI NOR verified: {offset:#08x}, {len(expected)} bytes")

    def flash(self, binary, loader):
        loader_data = loader.read_bytes()
        validate_loader(loader_data)
        image = app_image(binary.read_bytes())
        packed = binary.with_name("zephyr-flash.bin")
        save_synced(packed, image)
        sid = self.identify()
        self.backup(sid)  # must finish successfully before the first erase/write
        with tempfile.TemporaryDirectory(prefix=".nor-verify-", dir=binary.parent) as tmp:
            scratch = Path(tmp)
            boot_area = self.read(0, 0x30000, scratch / "boot-area.bin")
            self.message("Writing persistent application at SPI NOR 0x200000...")
            self.write_verified(APP_OFFSET, packed, scratch)
            # Install the primary loader last; skip copies already identical to our loader.
            for offset in reversed(LOADER_OFFSETS):
                if boot_area[offset : offset + len(loader_data)] != loader_data:
                    self.message(f"Installing bootloader copy at {offset:#08x}...")
                    # Preserve the rest of this 64 KiB region, including the tuning sector.
                    sector = bytearray(boot_area[offset : offset + 0x10000])
                    sector[: len(loader_data)] = loader_data
                    copy = scratch / f"loader-{offset:x}.bin"
                    save_synced(copy, sector)
                    self.write_verified(offset, copy, scratch)
        self.message("Persistent Flash verified. The application will run after power-on.")
