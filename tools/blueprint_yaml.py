"""Shared helpers: load a blueprint with !input tags and read input defaults."""
import yaml


class Input(str):
    """Value of an !input tag (the name of the input)."""


class Loader(yaml.SafeLoader):
    pass


Loader.add_constructor("!input", lambda l, n: Input(l.construct_scalar(n)))


def load(path):
    return yaml.load(path.read_text(encoding="utf-8"), Loader)


def input_defaults(blueprint):
    """Default value of every input, sections flattened."""
    out = {}

    def collect(node):
        for key, spec in node.items():
            if isinstance(spec, dict) and "input" in spec:
                collect(spec["input"])
            else:
                out[key] = (spec or {}).get("default")

    collect(blueprint["blueprint"]["input"])
    return out
