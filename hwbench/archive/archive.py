import tarfile
import os
from typing import Optional


def create_tar_from_directory(dir: str, tarfilename: str) -> None:
    """create a tar archive from a directory and its subdirectories without
    following the symlinks."""
    # may raise tarfile.ReadError if tarfilename is not a tar file
    tarfd = tarfile.open(tarfilename, "x")
    for rootpath, dirnames, filenames in os.walk(dir):
        for filename in filenames:
            tarfd.add(os.path.join(rootpath, filename))
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
