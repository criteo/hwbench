import os
import json


class Environment:
    def __init__(self, out_dir):
        self.out_dir = out_dir

        (self.out_dir / "kernel-info.json").write_text(
            json.dumps(self.kernel_version())
        )

    @staticmethod
    def kernel_version():
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
            "kernel": self.kernel_version(),
        }
