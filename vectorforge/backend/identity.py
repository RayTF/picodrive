"""ROM hashing, conservative canonicalization, and system inference."""

from __future__ import annotations

import binascii
import hashlib
import os
import stat
import struct
import zipfile
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Dict, Optional, Tuple

MAX_ZIP_MEMBER_SIZE = 64 * 1024 * 1024
MAX_CARTRIDGE_SIZE = 64 * 1024 * 1024
MAX_ZIP_CONTAINER_SIZE = 256 * 1024 * 1024
MAX_ZIP_ENTRIES = 4096
MAX_ZIP_DIRECTORY_SIZE = 8 * 1024 * 1024
ZIP_ROM_EXTENSIONS = {
    "bin", "gen", "smd", "md", "32x", "pco", "iso", "sms", "gg", "sg", "sc"
}
DISC_EXTENSIONS = {"iso", "cso", "cue", "chd"}
CARTRIDGE_EXTENSIONS = {"bin", "gen", "md", "32x", "pco", "sms", "gg", "sg", "sc"}
SMS_HEADER_OFFSETS = (0x7FF0, 0x3FF0, 0x1FF0)


class MetadataError(Exception):
    """An expected input, validation, or operational error."""


class ProviderOperationalError(MetadataError):
    """A provider failure which must not be cached."""

    def __init__(self, message: str, category: str = "service") -> None:
        super().__init__(message)
        self.category = category


def _new_hashers() -> Dict[str, object]:
    return {
        "md5": hashlib.md5(),
        "sha1": hashlib.sha1(),
        "sha256": hashlib.sha256(),
    }


def hash_stream(stream: BinaryIO) -> Dict[str, object]:
    """Hash a stream without loading it in memory."""
    hashers = _new_hashers()
    crc = 0
    size = 0
    while True:
        chunk = stream.read(1024 * 1024)
        if not chunk:
            break
        size += len(chunk)
        crc = binascii.crc32(chunk, crc)
        for hasher in hashers.values():
            hasher.update(chunk)  # type: ignore[attr-defined]
    return {
        "size": size,
        "crc32": f"{crc & 0xFFFFFFFF:08x}",
        **{name: hasher.hexdigest() for name, hasher in hashers.items()},  # type: ignore[attr-defined]
    }


def hash_file(path: Path) -> Dict[str, object]:
    with path.open("rb") as stream:
        return hash_stream(stream)


def hash_bytes(data: bytes) -> Dict[str, object]:
    from io import BytesIO

    return hash_stream(BytesIO(data))


def _has_cd_signature(data: bytes) -> bool:
    signature = b"SEGADISCSYSTEM"
    return data[:14].upper() == signature or data[0x10:0x1E].upper() == signature


def _sms_header(data: bytes) -> Optional[int]:
    for offset in SMS_HEADER_OFFSETS:
        if data[offset:offset + 8] == b"TMR SEGA":
            return offset
    return None


def _md_header(data: bytes) -> bool:
    header = data[0x100:0x110]
    return header.startswith(b"SEGA") or header.startswith(b" SEG")


def _smd_decode(data: bytes) -> Optional[bytes]:
    size = len(data)
    if size < 0x4200 or size & 0x3FFF != 0x200:
        return None
    if not ((data[0x2280:0x2281] == b"S" and data[0x280:0x281] == b"E") or
            (data[0x280:0x281] == b"S" and data[0x2281:0x2282] == b"E")):
        return None
    output = bytearray(size - 0x200)
    payload = memoryview(data)[0x200:]
    for start in range(0, len(payload), 0x4000):
        block = payload[start:start + 0x4000]
        for index in range(0x2000):
            output[start + index * 2] = block[0x2000 + index]
            output[start + index * 2 + 1] = block[index]
    decoded = bytes(output)
    return decoded if _md_header(decoded) else None


def infer_system(data: bytes, extension: str) -> str:
    """Infer a display system from content first, then the extension."""
    extension = extension.lower().lstrip(".")
    if _has_cd_signature(data) or extension in DISC_EXTENSIONS:
        return "Sega / Mega CD"

    header = data[0x100:0x110].upper()
    if b"PICO" in header:
        return "Sega Pico"
    if b"32X" in header:
        return "32X"
    if _md_header(data):
        return "Mega Drive / Genesis"

    sms_offset = _sms_header(data)
    if sms_offset is not None:
        region = data[sms_offset + 15] >> 4 if len(data) > sms_offset + 15 else 0
        if region in (5, 6, 7):
            return "Game Gear"
        if region in (3, 4):
            return "Master System"

    if extension == "gg":
        return "Game Gear"
    if extension in {"sms", "sg", "sc"}:
        return "Master System"
    if extension == "32x":
        return "32X"
    if extension == "pco":
        return "Sega Pico"
    if extension in {"bin", "gen", "smd", "md"}:
        return "Mega Drive / Genesis"
    return "Unknown System"


def canonicalize(data: bytes, extension: str) -> Tuple[Optional[bytes], Optional[str], str]:
    """Return canonical bytes, transform name, and inferred system."""
    extension = extension.lower().lstrip(".")
    if _has_cd_signature(data) or extension in DISC_EXTENSIONS:
        return None, None, "Sega / Mega CD"

    decoded = _smd_decode(data)
    if decoded is not None:
        return decoded, "smd-deinterleave", infer_system(decoded, extension)

    if len(data) >= 0x4200 and len(data) & 0x3FFF == 0x200:
        stripped = data[0x200:]
        if _sms_header(stripped) is not None:
            return stripped, "sms-copier-header-strip", infer_system(stripped, extension)

    system = infer_system(data, extension)
    content_is_cartridge = _md_header(data) or _sms_header(data) is not None
    if extension in CARTRIDGE_EXTENSIONS or content_is_cartridge:
        return data, "raw-cartridge", system
    return None, None, system


def _unsafe_member_name(name: str) -> bool:
    if not name or name.startswith(("/", "\\")) or "\\" in name or ":" in name:
        return True
    if any(ord(character) < 0x20 for character in name):
        return True
    return any(part in {"", ".", ".."} for part in name.split("/"))


def _regular_zip_member(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0xFFFF
    kind = stat.S_IFMT(mode)
    return kind in (0, stat.S_IFREG)


def _zip_directory(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0xFFFF
    return info.is_dir() or stat.S_IFMT(mode) == stat.S_IFDIR


def _validate_zip_container(stream: BinaryIO, size: int, name: str) -> None:
    if size > MAX_ZIP_CONTAINER_SIZE:
        raise MetadataError("ZIP container exceeds 256 MiB limit")
    trailer_start = max(0, size - (65535 + 22))
    stream.seek(trailer_start)
    trailer = stream.read(65535 + 22)
    marker = trailer.rfind(b"PK\x05\x06")
    while marker >= 0:
        if marker + 22 <= len(trailer):
            comment = struct.unpack_from("<H", trailer, marker + 20)[0]
            if marker + 22 + comment == len(trailer):
                break
        marker = trailer.rfind(b"PK\x05\x06", 0, marker)
    if marker < 0:
        raise MetadataError(f"invalid ZIP end record: {name}")
    if marker >= 20 and trailer[marker - 20:marker - 16] == b"PK\x06\x07":
        raise MetadataError(f"ZIP64 is unsupported: {name}")
    fields = struct.unpack_from("<4s4H2LH", trailer, marker)
    _, disk, directory_disk, disk_entries, entries, directory_size, directory_offset, _ = fields
    if disk != 0 or directory_disk != 0 or disk_entries != entries:
        raise MetadataError(f"multi-volume ZIP is unsupported: {name}")
    if entries == 0xFFFF or directory_size == 0xFFFFFFFF or directory_offset == 0xFFFFFFFF:
        raise MetadataError(f"ZIP64 is unsupported: {name}")
    if entries > MAX_ZIP_ENTRIES or directory_size > MAX_ZIP_DIRECTORY_SIZE:
        raise MetadataError(f"ZIP central directory exceeds safety limits: {name}")
    end_record_offset = trailer_start + marker
    if directory_offset + directory_size != end_record_offset:
        raise MetadataError(f"invalid ZIP central directory: {name}")

    stream.seek(directory_offset)
    remaining = directory_size
    actual_entries = 0
    while remaining > 0:
        header = stream.read(46)
        if len(header) != 46 or header[:4] != b"PK\x01\x02":
            raise MetadataError(f"invalid ZIP central directory entry: {name}")
        compressed_size, file_size = struct.unpack_from("<LL", header, 20)
        filename_length, extra_length, comment_length, member_disk = struct.unpack_from(
            "<4H", header, 28
        )
        local_offset = struct.unpack_from("<L", header, 42)[0]
        variable_size = filename_length + extra_length + comment_length
        record_size = 46 + variable_size
        if record_size > remaining:
            raise MetadataError(f"invalid ZIP central directory size: {name}")
        if (compressed_size == 0xFFFFFFFF or file_size == 0xFFFFFFFF or
                member_disk == 0xFFFF or local_offset == 0xFFFFFFFF):
            raise MetadataError(f"ZIP64 is unsupported: {name}")
        stream.seek(variable_size, 1)
        remaining -= record_size
        actual_entries += 1
        if actual_entries > MAX_ZIP_ENTRIES:
            raise MetadataError(f"ZIP has more than {MAX_ZIP_ENTRIES} entries: {name}")
    if actual_entries != entries:
        raise MetadataError(f"ZIP entry count does not match its directory: {name}")


def identify_plain(path: Path, extension: str) -> Dict[str, object]:
    extension = extension.lower().lstrip(".")
    if extension in DISC_EXTENSIONS:
        raw = hash_file(path)
        return {
            "id": f"sha1:{raw['sha1']}",
            "system": "Sega / Mega CD",
            "identity_basis": "raw",
            "raw": raw,
            "canonical": None,
            "warnings": [],
        }
    with path.open("rb") as stream:
        size = os.fstat(stream.fileno()).st_size
        prefix = stream.read(512)
        if extension == "bin" and _has_cd_signature(prefix):
            stream.seek(0)
            raw = hash_stream(stream)
            return {
                "id": f"sha1:{raw['sha1']}",
                "system": "Sega / Mega CD",
                "identity_basis": "raw",
                "raw": raw,
                "canonical": None,
                "warnings": [],
            }
        if size > MAX_CARTRIDGE_SIZE:
            raise MetadataError(
                f"cartridge exceeds {MAX_CARTRIDGE_SIZE // (1024 * 1024)} MiB limit: "
                f"{path.name}"
            )
        stream.seek(0)
        data = stream.read(MAX_CARTRIDGE_SIZE + 1)
        if len(data) > MAX_CARTRIDGE_SIZE:
            raise MetadataError(f"cartridge grew while scanning: {path.name}")
    raw = hash_bytes(data)
    canonical, transform, system = canonicalize(data, extension)
    canonical_hashes = None
    if canonical is not None:
        canonical_hashes = {"transform": transform, **hash_bytes(canonical)}
        digest = str(canonical_hashes["sha1"])
        basis = "canonical"
    else:
        digest = str(raw["sha1"])
        basis = "raw"
    return {
        "id": f"sha1:{digest}",
        "system": system,
        "identity_basis": basis,
        "raw": raw,
        "canonical": canonical_hashes,
        "warnings": [],
    }


def identify_zip(path: Path) -> Dict[str, object]:
    try:
        with path.open("rb") as stream:
            size = os.fstat(stream.fileno()).st_size
            _validate_zip_container(stream, size, path.name)
            stream.seek(0)
            raw = hash_stream(stream)
            stream.seek(0)
            with zipfile.ZipFile(stream) as archive:
                selected = None
                selected_extension = ""
                selected_by_size = False
                entries = archive.infolist()
                if len(entries) > MAX_ZIP_ENTRIES:
                    raise MetadataError(f"ZIP has more than {MAX_ZIP_ENTRIES} entries: {path.name}")
                for info in entries:
                    if _zip_directory(info):
                        continue
                    extension = PurePosixPath(info.filename).suffix.lower().lstrip(".")
                    if info.file_size >= 32 * 1024 or extension in ZIP_ROM_EXTENSIONS:
                        selected = info
                        selected_extension = extension
                        selected_by_size = extension not in ZIP_ROM_EXTENSIONS
                        break
                if selected is None:
                    raise MetadataError(f"ZIP has no selectable ROM member: {path.name}")
                if selected.flag_bits & 1:
                    raise MetadataError(f"encrypted ZIP member is unsupported: {selected.filename}")
                if selected.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                    raise MetadataError(f"unsupported ZIP compression for member: {selected.filename}")
                if not _regular_zip_member(selected):
                    raise MetadataError(f"non-regular ZIP member is unsupported: {selected.filename}")
                if selected.file_size > MAX_ZIP_MEMBER_SIZE:
                    raise MetadataError(
                        f"ZIP member exceeds {MAX_ZIP_MEMBER_SIZE // (1024 * 1024)} MiB limit: "
                        f"{selected.filename}"
                    )
                if selected_extension in {"zip", "cue", "cso", "chd"}:
                    raise MetadataError(
                        f"nested archives and disc sets are unsupported: {selected.filename}"
                    )
                with archive.open(selected) as member_stream:
                    member_data = member_stream.read(MAX_ZIP_MEMBER_SIZE + 1)
                if len(member_data) > MAX_ZIP_MEMBER_SIZE:
                    raise MetadataError(f"ZIP member exceeds extraction limit: {selected.filename}")
    except (zipfile.BadZipFile, RuntimeError, OSError) as error:
        if isinstance(error, MetadataError):
            raise
        raise MetadataError(f"invalid ZIP {path.name}: {error}") from error

    warnings = []
    if _unsafe_member_name(selected.filename):
        warnings.append("selected member has an unsafe path; it was processed in memory only")
    if selected_by_size:
        warnings.append("selected first large member despite unrecognized extension")

    member_hashes = hash_bytes(member_data)
    canonical, transform, system = canonicalize(member_data, selected_extension)
    canonical_hashes = None
    if canonical is not None:
        canonical_hashes = {"transform": transform, **hash_bytes(canonical)}
        digest = str(canonical_hashes["sha1"])
        basis = "zip-member-canonical"
    else:
        digest = str(member_hashes["sha1"])
        basis = "zip-member-raw"

    compression = "stored" if selected.compress_type == zipfile.ZIP_STORED else "deflate"
    return {
        "id": f"sha1:{digest}",
        "system": system,
        "identity_basis": basis,
        "raw": raw,
        "canonical": canonical_hashes,
        "archive": {
            "selected_member": selected.filename,
            "compression": compression,
            "member": member_hashes,
        },
        "warnings": warnings,
    }
