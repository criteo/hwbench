import re


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
        engine.init()
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
        engine.init()
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


def validate_selected_cpus(config, section_name, value) -> str:
    """Validate the selected cpus syntax."""
    # The concept here is to remove from the value string items we know.
    # If one unhandled item is remaining, an error is reported.
    if isinstance(value, str):
        if value.isnumeric():
            return ""
        else:
            value = value.lower()
            # Helpers are removed first (longest-first so 'simple' cannot
            # partially match 'numa-simple') before parsing the resources,
            # otherwise the numa resource regex would eat 'numa-' from 'numa-simple'.
            for helper in ["numa-simple", "simple", "all"]:
                value = value.replace(helper, "", 1)
            resources = re.findall(r"(quadrant|numa|core)([0-9-,]+)", value)
            if resources:
                for resource in resources:
                    value = value.replace(f"{resource[0]}{resource[1]}", "", 1)
            range = config.parse_range(value)
            if range:
                value = value.lower().replace(value, "", 1)
            if len(value):
                return f"Unhandled string '{value}' in selected cpus"
    else:
        return f"Unhandled {value} in selected cpus"
    return ""


def validate_selected_cpus_scaling(config, section_name, value) -> str:
    """Validate the selected cpus scaling syntax."""
    if not value.startswith("plus_") and value not in ["iterate", "none"]:
        return f'Unknown selected_cpus_scaling="{value}"'
    return ""


def validate_thermal_start(config, section_name, value) -> str:
    """Validate the thermal start syntax."""
    return ""


def validate_fans_start(config, section_name, value) -> str:
    """Validate the fans start syntax."""
    return ""


def validate_skip_method(config, section_name, value) -> str:
    """Validate the skip_method syntax."""
    if value not in ["bypass", "wait"]:
        return f"{value} is not a valid skip method"
    return ""


def validate_sync_start(config, section_name, value) -> str:
    """Validate the skip_method syntax."""
    if value not in ["none", "time"]:
        return f"{value} is not a valid sync_start value"
    return ""
