from __future__ import annotations

from hwbench.environment.vendors.cdu import CDU
from hwbench.environment.vendors.monitoring_device import section_value
from hwbench.utils import helpers as h

from .hpe import MODELS as HPE_MODELS

# A vendor owns a model registry. Each model selects its own driver and OIDs.
VENDORS: dict[str, dict[str, type[CDU]]] = {"HPE": HPE_MODELS}


def init(vendor, section: str) -> CDU:
    config = vendor.monitoring_config_file
    manufacturer = section_value(config, "CDU", section, "vendor", "").upper()
    model = section_value(config, "CDU", section, "model", "")
    if manufacturer not in VENDORS:
        h.fatal(f"CDU {section}: unsupported vendor {manufacturer!r}; supported vendors: {', '.join(VENDORS)}")
    models = VENDORS[manufacturer]
    if model not in models:
        h.fatal(f"CDU {section}: unsupported model {model!r} for {manufacturer}; supported models: {', '.join(models)}")
    return models[model](vendor, section)
