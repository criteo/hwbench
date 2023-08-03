import os


class Environment:
    def __init__(self, out_dir):
        self.out_dir = out_dir

    @staticmethod
    def kernel():
        uname = os.uname()
        return {
            "version": uname.version,
            "release": uname.release,
            "machine": uname.machine,
            "nodename": uname.nodename,
            "sysname": uname.sysname,
        }

    def dump(self):
        return {
            "kernel": self.kernel(),
        }
