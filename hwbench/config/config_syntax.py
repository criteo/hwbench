def validate_runtime(config, section_name, value) -> str:
    """Validate the runtime syntax."""
    if not value.isnumeric():
        return f"{value} is not a numeric value"
    return ""


def validate_monitor(config, section_name, value) -> str:
    """Validate the monitor syntax."""
    if value not in ["all", "none"]:
        return f"{value} is not a valid monitoring value"
    return ""


def validate_engine(config, section_name, value) -> str:
    """Validate the engine syntax."""
    try:
        engine = config.load_engine(value)
    except ModuleNotFoundError:
        return f'Unknown "{value}" engine'
    assert engine.get_name() == value
    return ""


def validate_engine_module(config, section_name, value) -> str:
    """Validate the engine module syntax."""
    try:
        engine = config.load_engine(config.get_engine(section_name))
    except ModuleNotFoundError:
        return f'Unknown "{value}" engine'
    if not engine.module_exists(value):
        return f"engine_module {value} does not exist"
    engine_module = engine.get_module(value)
    assert engine_module.get_name() == value
    return ""


def validate_engine_module_parameter(config, section_name, value) -> str:
    """Validate the engine module parameter syntax."""
    try:
        engine = config.load_engine(config.get_engine(section_name))
    except ModuleNotFoundError:
        return f'Unknown "{value}" engine'
    engine_module_name = config.get_engine_module(section_name)
    assert engine.module_exists(engine_module_name)
    engine_module = engine.get_module(engine_module_name)
    for emp in config.parse_range(value):
        if emp not in engine_module.get_module_parameters(special_keywords=True):
            return f"Engine {engine.get_name()}: {emp} module parameter does not exists"
    return ""


def validate_engine_module_parameter_base(config, section_name, value) -> str:
    """Validate the engine module parameter base syntax."""
    return ""


def validate_stressor_range(config, section_name, value) -> str:
    """Validate the stressor range syntax."""
    return ""


def validate_stressor_range_scaling(config, section_name, value) -> str:
    """Validate the stressor range scaling syntax."""
    return ""


def validate_hosting_cpu_cores(config, section_name, value) -> str:
    """Validate the hosting cpu cores syntax."""
    return ""


def validate_hosting_cpu_cores_scaling(config, section_name, value) -> str:
    """Validate the hosting cpu cores scaling syntax."""
    if not value.startswith("plus_") and value != "iterate":
        return f'Unknown hosting_cpu_cores_scaling="{value}"'
    return ""


def validate_thermal_start(config, section_name, value) -> str:
    """Validate the thermal start syntax."""
    return ""


def validate_fans_start(config, section_name, value) -> str:
    """Validate the fans start syntax."""
    return ""
