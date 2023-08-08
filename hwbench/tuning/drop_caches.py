class SysctlDropCaches:
    def __init__(self, out_dir):
        self.out_dir = out_dir

    def run(self):
        open("/proc/sys/vm/drop_caches", "w").write("3\n")
