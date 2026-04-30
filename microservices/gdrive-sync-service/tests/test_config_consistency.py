from pathlib import Path

import pytest
import yaml


@pytest.mark.unit
def test_config_example_matches_k8s_drive_folder_ids() -> None:
    root = Path(__file__).resolve().parents[1]
    example = yaml.safe_load((root / "config" / "config.example.yaml").read_text(encoding="utf-8"))
    configmap = yaml.safe_load((root / "k8s" / "configmap-drives.yaml").read_text(encoding="utf-8"))
    k8s_drives = yaml.safe_load(configmap["data"]["drives.yaml"])

    example_by_name = {item["name"]: item for item in example["drives"]}
    k8s_by_name = {item["name"]: item for item in k8s_drives["drives"]}

    assert {
        name: item["folder_id"] for name, item in k8s_by_name.items()
    } == {
        name: item["folder_id"] for name, item in example_by_name.items()
    }
