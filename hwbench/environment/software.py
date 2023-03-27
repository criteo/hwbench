import os


class Environment:
    @staticmethod
    def kernel():
        uname = os.uname()
        return {
            "version": uname.version,
            "release": uname.release,
            "machine": uname.machine,
        }

    def dump(self):
        return {
            "kernel": self.kernel(),
        }
