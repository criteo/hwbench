from __future__ import annotations

from hwbench.environment.vendors.cdu import CDU

from .mcdu_4u_fr_2 import HPEMCDU4UFR2

MODELS: dict[str, type[CDU]] = {"MCDU-4U-FR-2": HPEMCDU4UFR2}
