"""Pure-Python ISO9660 writer for VectorDrive PSP packages."""

from __future__ import annotations

import math
import os
import stat
import struct
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from backend.identity import MetadataError

from .builder import BuildResult, build_zip
from .library import LibraryStore
from .package import PackageReader
from .pbp import PbpFile, fake_umd_data


SECTOR = 2048


@dataclass
class _IsoFile:
    name: str
    size: int
    data: Optional[bytes] = None
    archive_name: Optional[str] = None


@dataclass
class _IsoDirectory:
    path: str
    children: List[str]
    files: List[str]
    extent: int = 0
    size: int = 0
    number: int = 0


def _both32(value: int) -> bytes:
    return struct.pack("<I", value) + struct.pack(">I", value)


def _both16(value: int) -> bytes:
    return struct.pack("<H", value) + struct.pack(">H", value)


def _padded(value: str, length: int) -> bytes:
    encoded = value.encode("ascii")[:length]
    return encoded.ljust(length, b" ")


def _date() -> bytes:
    return bytes((80, 1, 1, 0, 0, 0, 0))


def _record(name: bytes, extent: int, size: int, directory: bool) -> bytes:
    if len(name) > 220:
        raise MetadataError("ISO directory identifier is too long")
    length = 33 + len(name) + (len(name) % 2 == 0)
    result = bytearray(length)
    result[0] = length
    result[2:10] = _both32(extent)
    result[10:18] = _both32(size)
    result[18:25] = _date()
    result[25] = 2 if directory else 0
    result[28:32] = _both16(1)
    result[32] = len(name)
    result[33:33 + len(name)] = name
    return bytes(result)


def _path_record(name: bytes, extent: int, parent: int) -> bytes:
    length = len(name) + 8 + (len(name) % 2)
    result = bytearray(length)
    result[0] = len(name)
    result[2:6] = struct.pack("<I", extent)
    result[6:8] = struct.pack("<H", parent)
    result[8:8 + len(name)] = name
    return bytes(result)


def _directory_bytes(directory: _IsoDirectory, directories: Dict[str, _IsoDirectory], files: Dict[str, _IsoFile]) -> bytes:
    records: List[bytes] = [_record(b"\x00", directory.extent, directory.size, True)]
    parent = directory.path.rsplit("/", 1)[0] if "/" in directory.path else ""
    parent_dir = directories[parent]
    records.append(_record(b"\x01", parent_dir.extent, parent_dir.size, True))
    for child in directory.children:
        child_dir = directories[child]
        records.append(_record(child.rsplit("/", 1)[-1].encode("ascii"), child_dir.extent, child_dir.size, True))
    for child in directory.files:
        file = files[child]
        records.append(_record(file.name.encode("ascii"), file_extent[child], file.size, False))
    result = bytearray(directory.size)
    offset = 0
    for record in records:
        if offset + len(record) > ((offset // SECTOR) + 1) * SECTOR:
            offset = ((offset // SECTOR) + 1) * SECTOR
        if offset + len(record) > len(result):
            raise MetadataError("ISO directory record calculation failed")
        result[offset:offset + len(record)] = record
        offset += len(record)
    return bytes(result)


file_extent: Dict[str, int] = {}


def _prepare_tree(files: Dict[str, _IsoFile]) -> Dict[str, _IsoDirectory]:
    directories: Dict[str, _IsoDirectory] = {"": _IsoDirectory("", [], [])}
    for path in files:
        parts = path.split("/")
        for index in range(1, len(parts)):
            directory = "/".join(parts[:index])
            if directory not in directories:
                parent = "/".join(parts[:index - 1])
                directories[directory] = _IsoDirectory(directory, [], [])
                directories[parent].children.append(directory)
        parent = "/".join(parts[:-1])
        directories[parent].files.append(path)
    for directory in directories.values():
        directory.children.sort()
        directory.files.sort()
    ordered = sorted(directories.values(), key=lambda value: (value.path.count("/"), value.path))
    for index, directory in enumerate(ordered, 1):
        directory.number = index
    return directories


def _ensure_directory(directories: Dict[str, _IsoDirectory], path: str) -> None:
    if path in directories:
        return
    parent = path.rsplit("/", 1)[0] if "/" in path else ""
    _ensure_directory(directories, parent)
    directories[path] = _IsoDirectory(path, [], [])
    directories[parent].children.append(path)


def _path_table(directories: Dict[str, _IsoDirectory], big_endian: bool) -> bytes:
    ordered = sorted(directories.values(), key=lambda value: value.number)
    output = bytearray()
    for directory in ordered:
        if directory.path == "":
            name = b"\x00"
            parent = 1
        else:
            name = directory.path.rsplit("/", 1)[-1].encode("ascii")
            parent_path = directory.path.rsplit("/", 1)[0] if "/" in directory.path else ""
            parent = directories[parent_path].number
        record = _path_record(name, directory.extent, parent)
        if big_endian:
            record = bytearray(record)
            record[2:6] = struct.pack(">I", directory.extent)
            record[6:8] = struct.pack(">H", parent)
            record = bytes(record)
        output.extend(record)
    output.extend(bytes((-len(output)) % SECTOR))
    return bytes(output)


def _write_source(target, source: _IsoFile, archive: zipfile.ZipFile) -> None:
    if source.data is not None:
        target.write(source.data)
        return
    assert source.archive_name is not None
    with archive.open(source.archive_name, "r") as stream:
        while True:
            block = stream.read(1024 * 1024)
            if not block:
                break
            target.write(block)


def _volume_label(root: str) -> str:
    upper = root.upper()
    if "SMDUC" in upper:
        return "SMDUC"
    if "SUGC" in upper:
        return "SUGC"
    return "VECTORDRIVE"


def _write_iso(zip_path: Path, output: Path, root: str) -> None:
    files: Dict[str, _IsoFile] = {}
    with zipfile.ZipFile(zip_path, "r") as archive:
        names = [name for name in archive.namelist() if name.startswith(root + "/") and not name.endswith("/")]
        eboot_name = f"{root}/EBOOT.PBP"
        if eboot_name not in names:
            raise MetadataError("package is missing EBOOT.PBP")
        pbp = PbpFile.parse(archive.read(eboot_name))
        psp_files: Dict[str, _IsoFile] = {
            "UMD_DATA.BIN": _IsoFile("UMD_DATA.BIN", 48, data=fake_umd_data(pbp.disc_id())),
            "PSP_GAME/PARAM.SFO": _IsoFile("PARAM.SFO", len(pbp.sections["PARAM.SFO"]), data=pbp.sections["PARAM.SFO"]),
            "PSP_GAME/SYSDIR/BOOT.BIN": _IsoFile("BOOT.BIN", len(pbp.sections["DATA.PSP"]), data=pbp.sections["DATA.PSP"]),
            "PSP_GAME/SYSDIR/EBOOT.BIN": _IsoFile("EBOOT.BIN", len(pbp.sections["DATA.PSP"]), data=pbp.sections["DATA.PSP"]),
        }
        section_paths = {
            "ICON0.PNG": "PSP_GAME/ICON0.PNG", "ICON1.PMF": "PSP_GAME/ICON1.PMF",
            "PIC0.PNG": "PSP_GAME/PIC0.PNG", "PIC1.PNG": "PSP_GAME/PIC1.PNG",
            "SND0.AT3": "PSP_GAME/SND0.AT3",
        }
        for section, destination in section_paths.items():
            data = pbp.sections[section]
            if data:
                psp_files[destination] = _IsoFile(destination.rsplit("/", 1)[-1], len(data), data=data)
        for name in names:
            relative = name[len(root) + 1:]
            if relative == "EBOOT.PBP" or relative == "COPYING":
                continue
            destination = f"PSP_GAME/SYSDIR/{relative}"
            info = archive.getinfo(name)
            psp_files[destination] = _IsoFile(relative.rsplit("/", 1)[-1], info.file_size, archive_name=name)
        files.update(psp_files)
        directories = _prepare_tree(files)
        _ensure_directory(directories, "PSP_GAME/USRDIR")
        for directory in directories.values():
            directory.children.sort()
            directory.files.sort()
        ordered_dirs = sorted(directories.values(), key=lambda value: (value.path.count("/"), value.path))
        for index, directory in enumerate(ordered_dirs, 1):
            directory.number = index
        path_size = len(_path_table(directories, False))
        path_sectors = path_size // SECTOR
        directory_start = 18 + path_sectors * 2
        current = directory_start
        for directory in ordered_dirs:
            directory.extent = current
            provisional_records = 2 + len(directory.children) + len(directory.files)
            length = 0
            names_for_size = [b"\x00", b"\x01"]
            names_for_size.extend(child.rsplit("/", 1)[-1].encode("ascii") for child in directory.children)
            names_for_size.extend(files[child].name.encode("ascii") for child in directory.files)
            for name in names_for_size:
                record_length = 33 + len(name) + (len(name) % 2 == 0)
                if length + record_length > ((length // SECTOR) + 1) * SECTOR:
                    length = ((length // SECTOR) + 1) * SECTOR
                length += record_length
            directory.size = max(SECTOR, math.ceil(length / SECTOR) * SECTOR)
            current += directory.size // SECTOR
        global file_extent
        file_extent = {}
        for path in sorted(files):
            file_extent[path] = current
            current += math.ceil(files[path].size / SECTOR)
        path_l = _path_table(directories, False)
        path_m = _path_table(directories, True)
        volume_size = current
        pvd = bytearray(SECTOR)
        pvd[0] = 1
        pvd[1:6] = b"CD001"
        pvd[6] = 1
        pvd[8:40] = _padded("PSP GAME", 32)
        pvd[40:72] = _padded(_volume_label(root), 32)
        pvd[80:88] = _both32(volume_size)
        pvd[120:124] = _both16(1)
        pvd[124:128] = _both16(1)
        pvd[128:132] = _both16(SECTOR)
        pvd[132:140] = _both32(path_size)
        pvd[140:144] = struct.pack("<I", 18)
        pvd[148:152] = struct.pack(">I", 18 + path_sectors)
        root_dir = directories[""]
        pvd[156:156 + 34] = _record(b"\x00", root_dir.extent, root_dir.size, True)
        pvd[574:702] = _padded("PSP GAME", 128)
        terminator = bytearray(SECTOR)
        terminator[0] = 255
        terminator[1:6] = b"CD001"
        terminator[6] = 1
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{output.name}.", dir=output.parent)
        os.close(descriptor)
        temporary = Path(temporary_name)
        try:
            with temporary.open("wb") as stream:
                stream.write(bytes(SECTOR * 16))
                stream.write(pvd)
                stream.write(terminator)
                stream.write(path_l)
                stream.write(path_m)
                for directory in ordered_dirs:
                    stream.write(_directory_bytes(directory, directories, files))
                for path in sorted(files):
                    before = stream.tell()
                    _write_source(stream, files[path], archive)
                    written = stream.tell() - before
                    stream.write(bytes((-written) % SECTOR))
            if output.exists():
                output.unlink()
            os.replace(temporary, output)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise


@dataclass(frozen=True)
class IsoResult:
    output: Path
    zip: BuildResult


def build_iso(
    base_zip: Path,
    output: Path,
    library: LibraryStore,
    stable_ids: Optional[Sequence[str]] = None,
    force: bool = False,
) -> IsoResult:
    output = output.expanduser()
    if output.exists() and not force:
        raise MetadataError(f"output already exists (use force to replace): {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix="vectorforge-iso-package-", suffix=".zip", dir=output.parent,
                                     delete=False) as stream:
        temporary_zip = Path(stream.name)
    try:
        result = build_zip(base_zip, temporary_zip, library, stable_ids, force=True)
        reader = PackageReader(temporary_zip)
        _write_iso(temporary_zip, output, reader.root)
        return IsoResult(output, result)
    finally:
        temporary_zip.unlink(missing_ok=True)
