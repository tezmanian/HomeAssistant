"""Static checks for the blueprints: YAML loads, every !input is defined,
and every Jinja template compiles (Home Assistant filters/tests stubbed)."""
import pathlib
import sys

import jinja2

sys.path.insert(0, str(pathlib.Path(__file__).parent))  # python -I drops it
from blueprint_yaml import Input, load  # noqa: E402

HA_FILTERS = [
    "as_timestamp", "as_datetime", "as_local", "is_number", "regex_replace",
    "regex_findall", "regex_findall_index", "iif", "slugify", "to_json",
    "from_json", "contains", "float_pass", "median", "average", "flatten",
    "expand", "typeof", "is_defined", "timestamp_custom", "timestamp_local",
    "timestamp_utc", "relative_time", "multiply", "add", "log", "sin", "cos",
]
HA_TESTS = ["match", "search", "number", "is_number", "contains", "list", "defined_or_none"]
HA_GLOBALS = [
    "states", "is_state", "state_attr", "is_state_attr", "expand", "area_entities",
    "area_name", "area_id", "device_entities", "now", "utcnow", "iif", "float",
    "int", "has_value", "distance", "closest", "today_at", "as_timestamp",
    "as_datetime", "relative_time", "timedelta", "min", "max", "state_translated",
    "label_entities", "floor_areas", "areas", "device_id", "integration_entities",
]


def make_env():
    env = jinja2.Environment()
    for name in HA_FILTERS:
        env.filters.setdefault(name, lambda *a, **k: None)
    for name in HA_TESTS:
        env.tests.setdefault(name, lambda *a, **k: True)
    for name in HA_GLOBALS:
        env.globals.setdefault(name, lambda *a, **k: None)
    return env


def walk(node, path=""):
    if isinstance(node, dict):
        for k, v in node.items():
            yield from walk(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from walk(v, f"{path}[{i}]")
    else:
        yield path, node


def check(file):
    errors = []
    data = load(file)
    defined = set()

    def collect(node):
        if isinstance(node, dict):
            if "input" in node and isinstance(node["input"], dict):
                defined.update(
                    k for k, v in node["input"].items()
                    if not (isinstance(v, dict) and "input" in v)
                )
            for v in node.values():
                collect(v)
        elif isinstance(node, list):
            for v in node:
                collect(v)

    collect(data.get("blueprint", {}))
    env = make_env()
    used = set()
    for path, value in walk({k: v for k, v in data.items() if k != "blueprint"}):
        if isinstance(value, Input):
            used.add(str(value))
        elif isinstance(value, str) and ("{{" in value or "{%" in value):
            try:
                env.from_string(value)
            except jinja2.TemplateSyntaxError as e:
                errors.append(f"{file}: template error at {path}: {e} (line {e.lineno})")
    for name in sorted(used - defined):
        errors.append(f"{file}: !input '{name}' is not defined")
    for name in sorted(defined - used):
        errors.append(f"{file}: input '{name}' is defined but never used (warning)")
    return errors


def main():
    files = sorted(pathlib.Path("blueprints").rglob("*.yaml"))
    failed = False
    for f in files:
        errs = check(f)
        hard = [e for e in errs if not e.endswith("(warning)")]
        for e in errs:
            print(e)
        print(("FAIL " if hard else "OK   ") + str(f))
        failed |= bool(hard)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
