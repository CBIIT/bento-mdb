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


def current_source_hash(repo: Path) -> str:
    packages = discover_edp_packages(
        repo / "model-desc" / "edps"
    )
    return packages[0].source_hash()


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
            "source_hash": current_source_hash(repo),
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
    assert spec["source_hash"] == current_source_hash(repo)


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


def test_detects_props_change_with_same_version(
    tmp_path: Path,
) -> None:
    repo = make_edp_repo(tmp_path, "1")
    config = base_config(repo, "1")
    previous_hash = config["OBIB"]["source_hash"]

    props_file = (
        repo
        / "model-desc"
        / "edps"
        / "obib_terms_valueset"
        / "edp-props.yml"
    )
    data = yaml.safe_load(
        props_file.read_text(encoding="utf-8")
    )
    data["PropDefinitions"]["obib_terms_valueset"][
        "Desc"
    ] = "Updated description"
    write_yaml(props_file, data)

    updated = update_edp_versions(config, repo)

    assert updated is True
    assert config["OBIB"]["source_hash"] != previous_hash


def test_detects_terms_change_with_same_version(
    tmp_path: Path,
) -> None:
    repo = make_edp_repo(tmp_path, "1")
    config = base_config(repo, "1")
    previous_hash = config["OBIB"]["source_hash"]

    terms_file = (
        repo
        / "model-desc"
        / "edps"
        / "obib_terms_valueset"
        / "terms.yml"
    )
    data = yaml.safe_load(
        terms_file.read_text(encoding="utf-8")
    )
    data["Terms"]["term_1"]["Definition"] = (
        "Updated definition"
    )
    write_yaml(terms_file, data)

    updated = update_edp_versions(config, repo)

    assert updated is True
    assert config["OBIB"]["source_hash"] != previous_hash


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