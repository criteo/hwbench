import io
import os
import pathlib
import tarfile
from typing import Optional


def create_tar_from_directory(dir: str, tarfilename: str) -> None:
    """create a tar archive from a directory and its subdirectories without
    following the symlinks."""
    # may raise tarfile.ReadError if tarfilename is not a tar file
    tarfd = tarfile.open(tarfilename, "x")
    for rootpath, dirnames, filenames in os.walk(dir):
        for filename in filenames:
            file = pathlib.Path(rootpath) / filename
            try:
                content = file.read_bytes()
            except IOError:  # ignore files that might not work at the kernel level
                print(f"{file} is unreadable")
                continue
            tf = tarfile.TarInfo(str(file))
            tf.size = len(content)
            tarfd.addfile(tf, io.BytesIO(content))
    tarfd.close()
    return None


def extract_file_from_tar(tarfilename: str, filename: str) -> Optional[bytes]:
    """return a specific file in a tar archive as bytes if
    the file exists."""
    # may raise tarfile.ReadError if tarfilename is not a tar file
    tarfd = tarfile.open(tarfilename, "r")
    try:
        ret = tarfd.extractfile(filename).read(-1)
        tarfd.close()
        return ret
    except KeyError:
        tarfd.close()
        return None
