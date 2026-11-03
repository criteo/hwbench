from __future__ import annotations

import errno
import io
import os
import pathlib
import re
import socket
import tarfile

RESULTS_FILE = "results.json"


def create_tar_from_directory(dir: str, tarfilename: pathlib.Path) -> None:
    """create a tar archive from a directory and its subdirectories without
    following the symlinks."""
    # may raise tarfile.ReadError if tarfilename is not a tar file
    with tarfile.open(tarfilename, "x") as tarfd:
        for rootpath, _dirnames, filenames in os.walk(dir):
            for filename in filenames:
                file = pathlib.Path(rootpath) / filename
                try:
                    content = file.read_bytes()
                except OSError as e:  # ignore files that might not work at the kernel level
                    if e.errno not in [errno.EIO, errno.EINVAL, errno.EACCES]:
                        print(f"{file} is unreadable {e}")
                    continue
                tf = tarfile.TarInfo(str(file))
                tf.size = len(content)
                tarfd.addfile(tf, io.BytesIO(content))
    return None


def extract_file_from_tar(tarfilename: str, filename: str) -> bytes | None:
    """return a specific file in a tar archive as bytes if
    the file exists."""
    # may raise tarfile.ReadError if tarfilename is not a tar file
    try:
        with tarfile.open(tarfilename, "r") as tarfd:
            file = tarfd.extractfile(filename)
            if not file:
                tarfd.close()
                return None
            ret = file.read(-1)
            return ret
    except KeyError:
        return None


def create_output_archive(out_dir: pathlib.Path, serial: str | None, timestamp: str) -> pathlib.Path:
    """compress the output directory, next to it, as hwbench-<serial>-<timestamp>.tar.xz:
    the archive extracts as the output directory itself. The hostname replaces
    a missing serial."""
    # the serial comes from the DMI: it can be missing, or hold spaces or slashes
    name = (serial or "").strip() or socket.gethostname()
    safe_serial = re.sub(r"[^A-Za-z0-9._-]+", "_", name)
    archive = out_dir.parent / f"hwbench-{safe_serial}-{timestamp}.tar.xz"
    with tarfile.open(archive, "x:xz") as tarfd:
        tarfd.add(out_dir, arcname=out_dir.name)
    return archive


def read_results_of_archive(archive: str) -> tuple[str, bytes] | None:
    """return the name of the output directory an archive made by create_output_archive()
    holds and its results.json, or None if it holds no results.json: the archive is read
    once, up to the results.json, a compressed archive not being read backwards."""
    # may raise tarfile.ReadError if archive is not a tar file
    with tarfile.open(archive, "r|*") as tarfd:
        for member in tarfd:
            parts = pathlib.PurePosixPath(member.name).parts
            if member.isfile() and parts[1:] == (RESULTS_FILE,):
                file = tarfd.extractfile(member)
                return parts[0], file.read() if file else b""
    return None


def extract_results_from_archive(archive: str) -> bytes | None:
    """return the results.json of an archive made by create_output_archive(),
    or None if there is none."""
    found = read_results_of_archive(archive)
    return found[1] if found else None


def archive_output_directory(archive: str) -> str | None:
    """return the name of the output directory an archive made by create_output_archive()
    holds, or None if it holds no results.json."""
    found = read_results_of_archive(archive)
    return found[0] if found else None


def copy_file(filename: str, destination_dir: str) -> None:
    """copy a file to a specific destination"""
    source = pathlib.Path(filename)
    destination = pathlib.Path(destination_dir) / source.name
    try:
        content = source.read_bytes()
        destination.write_bytes(content)
        # TODO may need to detect write_size != source.stat().st_size
    except OSError as e:
        print(f"copy_file( {destination_dir} , {filename} )  got: {e}")
    return None
