"""Checks on the files that ship with the integration."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

COMPONENT = Path(__file__).parent.parent / "custom_components" / "early"


def load_json(name: str) -> dict:
    """Read a JSON file from the integration directory."""
    return json.loads((COMPONENT / name).read_text())


def test_manifest_is_complete() -> None:
    """A custom integration needs a version and a config flow entry point."""
    manifest = load_json("manifest.json")
    assert manifest["domain"] == "early"
    assert manifest["version"]
    assert manifest["config_flow"] is True
    assert manifest["iot_class"] == "cloud_polling"


def test_english_translation_matches_strings() -> None:
    """translations/en.json is the shipped copy of strings.json."""
    assert load_json("translations/en.json") == load_json("strings.json")


def test_translations_cover_the_same_keys() -> None:
    """Every translation file describes the same set of keys."""

    def keys(value, prefix: str = "") -> set[str]:
        if not isinstance(value, dict):
            return {prefix}
        return {key for k, v in value.items() for key in keys(v, f"{prefix}.{k}")}

    english = keys(load_json("strings.json"))
    for path in (COMPONENT / "translations").glob("*.json"):
        assert keys(json.loads(path.read_text())) == english, path.name


def test_services_yaml_matches_strings() -> None:
    """Every service in services.yaml is documented, and vice versa."""
    services = yaml.safe_load((COMPONENT / "services.yaml").read_text())
    documented = load_json("strings.json")["services"]

    assert set(services) == set(documented)
    for name, definition in services.items():
        assert set(definition["fields"]) == set(documented[name]["fields"])
