from pathlib import Path

import yaml

from scripts.check_new_edps import update_edp_versions
from scripts.edp_packages import discover_edp_packages


def write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(data, sort_keys=False),
        encoding="utf-8",
    )


def make_edp_repo(tmp_path: Path, version: str) -> Path:
    repo = tmp_path / "edp-repo"
    package = (
        repo
        / "model-desc"
        / "edps"
        / "obib_terms_valueset"
    )

    write_yaml(
        package / "edp-props.yml",
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
                        }
                    ],
                    "Enum": ["term_1"],
                }
            },
        },
    )

    write_yaml(
        package / "terms.yml",
        {
            "Terms": {
                "term_1": {
                    "Origin": "OBIB",
                    "Code": "0001",
                    "Version": "1",
                    "Value": "term_1",
                    "Definition": "Test term",
                }
            }
        },
    )

    return repo

def base_config(repo: Path, latest_version: str = "1") -> dict:
    return {
        "OBIB": {
            "repository": "CBIIT/bento-edps",
            "mdf_directory": "model-desc",
            "package": "edps/obib_terms_valueset",
            "latest_version": latest_version,
            "versions": [
                {
                    "version": latest_version,
                    "tag": latest_version,
                }
            ],
            "origin": "CRDC",
            "code": "CRDC0002",
            "property": "obib_terms_valueset",
            "by_reference_url_patterns": ["obib"],
        }
    }


def test_registers_new_edp(tmp_path: Path) -> None:
    repo = make_edp_repo(tmp_path, "1")
    config: dict = {}

    updated = update_edp_versions(config, repo)

    assert updated is True
    assert len(config) == 1

    spec = next(iter(config.values()))
    assert spec["property"] == "obib_terms_valueset"
    assert spec["origin"] == "CRDC"
    assert spec["code"] == "CRDC0002"
    assert spec["latest_version"] == "1"
    assert spec["package"] == "edps/obib_terms_valueset"

def test_adds_new_edp_version(tmp_path: Path) -> None:
    repo = make_edp_repo(tmp_path, "1")
    config = base_config(repo, "1")

    repo = make_edp_repo(tmp_path, "2")
    updated = update_edp_versions(config, repo)

    assert updated is True
    assert config["OBIB"]["latest_version"] == "2"
    assert {
        "version": "2",
        "tag": "2",
    } in config["OBIB"]["versions"]


def test_does_not_update_matching_version(
    tmp_path: Path,
) -> None:
    repo = make_edp_repo(tmp_path, "1")
    config = base_config(repo, "1")

    updated = update_edp_versions(config, repo)

    assert updated is False
    assert config["OBIB"]["latest_version"] == "1"


def test_does_not_update_lower_version_when_new_only(
    tmp_path: Path,
) -> None:
    repo = make_edp_repo(tmp_path, "1")
    config = base_config(repo, "2")

    updated = update_edp_versions(
        config,
        repo,
        new_only=True,
    )

    assert updated is False
    assert config["OBIB"]["latest_version"] == "2"


def test_updates_latest_version_and_sorts_versions(
    tmp_path: Path,
) -> None:
    repo = make_edp_repo(tmp_path, "2")
    config = base_config(repo, "2")

    repo = make_edp_repo(tmp_path, "10")
    updated = update_edp_versions(config, repo)

    assert updated is True
    assert config["OBIB"]["latest_version"] == "10"
    assert [
        item["version"]
        for item in config["OBIB"]["versions"]
    ] == ["2", "10"]

def test_preserves_manual_config_fields(
    tmp_path: Path,
) -> None:
    repo = make_edp_repo(tmp_path, "1")
    config = base_config(repo, "1")

    repo = make_edp_repo(tmp_path, "2")
    update_edp_versions(config, repo)

    assert config["OBIB"]["by_reference_url_patterns"] == [
        "obib"
    ]