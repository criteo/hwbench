from __future__ import annotations

import errno
import io
import os
import pathlib
import tarfile


def create_tar_from_directory(dir: str, tarfilename: pathlib.Path) -> None:
    """create a tar archive from a directory and its subdirectories without
    following the symlinks."""
    # may raise tarfile.ReadError if tarfilename is not a tar file
    tarfd = tarfile.open(tarfilename, "x")
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
    tarfd.close()
    return None


def extract_file_from_tar(tarfilename: str, filename: str) -> bytes | None:
    """return a specific file in a tar archive as bytes if
    the file exists."""
    # may raise tarfile.ReadError if tarfilename is not a tar file
    tarfd = tarfile.open(tarfilename, "r")
    try:
        file = tarfd.extractfile(filename)
        if not file:
            tarfd.close()
            return None
        ret = file.read(-1)
        tarfd.close()
        return ret
    except KeyError:
        tarfd.close()
        return None


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
