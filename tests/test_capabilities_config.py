import pytest
import yaml
from pydantic import ValidationError

from command_center.schemas import CapabilityCatalogConfig


def test_capabilities_config_validates():
    data = yaml.safe_load(open("configs/capabilities.yaml", encoding="utf-8"))
    cfg = CapabilityCatalogConfig.model_validate(data)
    assert cfg.entries
    assert {entry.identifier for entry in cfg.entries}


def test_capability_identifier_must_use_ard_namespace():
    data = yaml.safe_load(open("configs/capabilities.yaml", encoding="utf-8"))
    data["entries"][0]["identifier"] = "github"
    with pytest.raises(ValidationError):
        CapabilityCatalogConfig.model_validate(data)


def test_capability_provenance_rejects_local_absolute_paths():
    data = yaml.safe_load(open("configs/capabilities.yaml", encoding="utf-8"))
    data["entries"][0]["provenance"][0]["source_ref"] = r"C:\Users\Operator\.codex\RTK.md"
    with pytest.raises(ValidationError, match="local absolute path"):
        CapabilityCatalogConfig.model_validate(data)


def test_capability_representative_queries_must_be_unique():
    data = yaml.safe_load(open("configs/capabilities.yaml", encoding="utf-8"))
    query = data["entries"][0]["representative_queries"][0]
    data["entries"][0]["representative_queries"][1] = query
    with pytest.raises(ValidationError, match="duplicate representative_queries"):
        CapabilityCatalogConfig.model_validate(data)
