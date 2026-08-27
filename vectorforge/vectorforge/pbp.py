"""Minimal, strict PBP and PARAM.SFO readers for PSP ISO generation."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Dict, Optional

from backend.identity import MetadataError


SECTION_NAMES = (
    "PARAM.SFO", "ICON0.PNG", "ICON1.PMF", "PIC0.PNG",
    "PIC1.PNG", "SND0.AT3", "DATA.PSP", "DATA.PSAR",
)


@dataclass(frozen=True)
class PbpFile:
    sections: Dict[str, bytes]

    @classmethod
    def parse(cls, data: bytes) -> "PbpFile":
        if len(data) < 40 or data[:4] != b"\x00PBP":
            raise MetadataError("EBOOT.PBP has an invalid PBP header")
        offsets = struct.unpack_from("<8I", data, 8)
        previous = 40
        for offset in offsets:
            if offset < 40 or offset < previous or offset > len(data):
                raise MetadataError("EBOOT.PBP contains invalid section offsets")
            previous = offset
        sections = {
            name: data[offsets[index]:offsets[index + 1] if index + 1 < len(offsets) else len(data)]
            for index, name in enumerate(SECTION_NAMES)
        }
        if not sections["PARAM.SFO"] or not sections["DATA.PSP"]:
            raise MetadataError("EBOOT.PBP is missing PARAM.SFO or DATA.PSP")
        return cls(sections)

    def sfo(self) -> Dict[str, object]:
        return parse_sfo(self.sections["PARAM.SFO"])

    def disc_id(self) -> str:
        value = self.sfo().get("DISC_ID")
        return str(value).strip() if value is not None else ""


def parse_sfo(data: bytes) -> Dict[str, object]:
    if len(data) < 20 or data[:4] != b"\x00PSF":
        raise MetadataError("PARAM.SFO has an invalid SFO header")
    key_offset, value_offset, count = struct.unpack_from("<3I", data, 8)
    if count > 1024 or key_offset > len(data) or value_offset > len(data):
        raise MetadataError("PARAM.SFO contains invalid table offsets")
    table_end = 20 + count * 16
    if table_end > len(data):
        raise MetadataError("PARAM.SFO entry table is truncated")
    result: Dict[str, object] = {}
    for index in range(count):
        entry = 20 + index * 16
        key_rel, data_format, data_len, data_max, data_rel = struct.unpack_from("<HHIII", data, entry)
        key_start = key_offset + key_rel
        key_end = data.find(b"\x00", key_start)
        if key_start >= len(data) or key_end < 0 or key_end > len(data):
            raise MetadataError("PARAM.SFO contains an invalid key")
        value_start = value_offset + data_rel
        if value_start > len(data) or data_len > len(data) - value_start:
            raise MetadataError("PARAM.SFO contains an invalid value")
        key = data[key_start:key_end].decode("ascii", errors="strict")
        raw = data[value_start:value_start + data_len]
        if data_format in (0x0004, 0x0204):
            value: object = raw.rstrip(b"\x00").decode("utf-8", errors="replace")
        elif data_format == 0x0404 and len(raw) >= 4:
            value = struct.unpack_from("<I", raw, 0)[0]
        else:
            value = raw
        result[key] = value
    return result


def fake_umd_data(disc_id: str) -> bytes:
    """Create the conventional 48-byte PSP UMD_DATA.BIN record."""

    disc = disc_id.encode("ascii", errors="ignore")[:10].ljust(10, b" ")
    return disc + b"|7707CDAC64C04411|0001|G" + bytes(13) + b"|"
