from pathlib import Path

from hwbench.utils.hwlogging import tunninglog


class SysctlDropCaches:
    def __init__(self, out_dir):
        self.out_dir = out_dir

    def run(self):
        file = Path("/proc/sys/vm/drop_caches")
        # please read https://www.kernel.org/doc/Documentation/sysctl/vm.txt
        # for further explanation.
        #
        # reading this value is meaning less and the file is write only,
        # so no previous value.
        value = 3
        tunninglog().info(
            "free slab objects and pagecache",
            extra={
                "value": value,
                "file": str(file),
                "type": "procfs",
            },
        )
        file.write_text(f"{value}\n")
