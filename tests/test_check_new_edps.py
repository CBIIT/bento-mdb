from pathlib import Path

import yaml

from scripts.check_new_edps import update_edp_versions
from pdb import set_trace

def write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def make_edp_repo(tmp_path: Path, version: str) -> Path:
    repo = tmp_path / "edp-repo"
    write_yaml(
        repo / "model-desc" / "edp-props.yml",
        {
            "Nodes": {},
            "Relationships": {},
            "PropDefinitions": {
                "obib_terms_valueset": {
                    "Ext": True,
                    "Term": [
                        {
                            "Origin": "CRDC",
                            "Code": "CRDC0002",
                            "Version": version,
                            "Value": "Obib Value Set Reference",
                        },
                    ],
                    "Enum": ["term_1"],
                },
            },
        },
    )
    write_yaml(
        repo / "model-desc" / "terms" / "obib-terms.yml",
        {
            "Terms": {
                "term_1": {
                    "Origin": "OBIB",
                    "Code": "0001",
                    "Version": "1",
                    "Value": "term_1",
                    "Definition": "Test term",
                },
            },
        },
    )
    return repo


def base_config(latest_version: str = "1") -> dict:
    return {
        "OBIB": {
            "repository": "CBIIT/bento-edps",
            "mdf_directory": "model-desc",
            "mdf_files": ["edp-props.yml", "terms/obib-terms.yml"],
            "latest_version": latest_version,
            "versions": [{"version": latest_version, "tag": latest_version}],
            "origin": "CRDC",
            "code": "CRDC0002",
            "property": "obib_terms_valueset",
        },
    }


def test_adds_new_edp_version(tmp_path: Path) -> None:
    repo = make_edp_repo(tmp_path, "2")
    config = base_config("1")

    updated = update_edp_versions(config, repo)

    assert updated is True
    assert config["OBIB"]["latest_version"] == "2"
    assert {"version": "2", "tag": "2"} in config["OBIB"]["versions"]


def test_does_not_update_matching_version(tmp_path: Path) -> None:
    repo = make_edp_repo(tmp_path, "1")
    config = base_config("1")

    updated = update_edp_versions(config, repo)

    assert updated is False
    assert config["OBIB"]["latest_version"] == "1"
    assert config["OBIB"]["versions"] == [{"version": "1", "tag": "1"}]


def test_does_not_update_lower_version_when_new_only(tmp_path: Path) -> None:
    repo = make_edp_repo(tmp_path, "1")
    config = base_config("2")

    updated = update_edp_versions(config, repo, new_only=True)

    assert updated is False
    assert config["OBIB"]["latest_version"] == "2"


def test_updates_latest_version_and_sorts_versions(tmp_path: Path) -> None:
    repo = make_edp_repo(tmp_path, "10")
    config = base_config("2")

    updated = update_edp_versions(config, repo)

    assert updated is True
    assert config["OBIB"]["latest_version"] == "10"
    assert [v["version"] for v in config["OBIB"]["versions"]] == ["2", "10"]
