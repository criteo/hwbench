from __future__ import annotations

from hwbench.environment.vendors.cdu import CDU
from hwbench.utils import helpers as h

# A vendor owns a model registry. Each model selects its own driver and OIDs.
VENDORS: dict[str, dict[str, type[CDU]]] = {}


def init(vendor, section: str) -> CDU:
    config = vendor.monitoring_config_file
    manufacturer = config.get(section, "vendor", fallback="").strip().upper()
    model = config.get(section, "model", fallback="").strip()
    if manufacturer not in VENDORS:
        h.fatal(f"CDU {section}: unsupported vendor {manufacturer!r}; supported vendors: {', '.join(VENDORS)}")
    models = VENDORS[manufacturer]
    if model not in models:
        h.fatal(f"CDU {section}: unsupported model {model!r} for {manufacturer}; supported models: {', '.join(models)}")
    return models[model](vendor, section)
