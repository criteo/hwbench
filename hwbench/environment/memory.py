class KernelMemoryInfo:
    def __init__(self) -> None:
        self._raw: dict[str, int] = {}

    def detect(self):
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    key, value = line.split(":")
                    try:
                        amount, unit = value.strip().split()
                    except ValueError:
                        amount = value.strip()
                        unit = ""
                    self._raw[key] = self._convert_to_bytes(int(amount), unit)
        except FileNotFoundError:
            raise RuntimeError("/proc/meminfo not found. Are you running on Linux?")

    def dump(self):
        return dict(self._raw)

    def _convert_to_bytes(self, value, unit):
        unit = unit.lower()
        if unit == "kb":
            return value * 1024
        elif unit == "mb":
            return value * 1024 * 1024
        elif unit == "gb":
            return value * 1024 * 1024 * 1024
        return value  # assume already in bytes, or another unit
