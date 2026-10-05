from pathlib import Path

import pytest
import yaml

from scripts.edp_packages import (
    discover_edp_packages,
    load_all_edp_packages,
    parse_edp_package,
)


def write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(data, sort_keys=False),
        encoding="utf-8",
    )


def create_package(
    root: Path,
    handle: str,
    *,
    origin: str = "CRDC",
    code: str = "CRDC0001",
    version: str = "1",
) -> Path:
    package = root / handle

    write_yaml(
        package / "edp-props.yml",
        {
            "Nodes": {},
            "Relationships": {},
            "PropDefinitions": {
                handle: {
                    "Ext": True,
                    "Term": [
                        {
                            "Origin": origin,
                            "Code": code,
                            "Version": version,
                            "Value": f"{handle} reference",
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
                    "Origin": "TEST",
                    "Code": f"{code}-PV1",
                    "Version": "1",
                    "Value": "term_1",
                }
            }
        },
    )

    return package


def test_discovers_packages_in_deterministic_order(
    tmp_path: Path,
) -> None:
    edp_root = tmp_path / "edps"

    create_package(
        edp_root,
        "second_edp",
        code="CRDC0002",
    )
    create_package(
        edp_root,
        "first_edp",
        code="CRDC0001",
    )

    packages = discover_edp_packages(edp_root)

    assert [package.name for package in packages] == [
        "first_edp",
        "second_edp",
    ]


def test_rejects_missing_terms_file(tmp_path: Path) -> None:
    edp_root = tmp_path / "edps"
    package = edp_root / "missing_terms"
    package.mkdir(parents=True)

    write_yaml(
        package / "edp-props.yml",
        {
            "Nodes": {},
            "Relationships": {},
            "PropDefinitions": {},
        },
    )

    with pytest.raises(ValueError, match="terms.yml"):
        discover_edp_packages(edp_root)


def test_rejects_missing_props_file(tmp_path: Path) -> None:
    edp_root = tmp_path / "edps"
    package = edp_root / "missing_props"
    package.mkdir(parents=True)

    write_yaml(package / "terms.yml", {"Terms": {}})

    with pytest.raises(ValueError, match="edp-props.yml"):
        discover_edp_packages(edp_root)


def test_rejects_empty_edp_root(tmp_path: Path) -> None:
    edp_root = tmp_path / "edps"
    edp_root.mkdir()

    with pytest.raises(ValueError, match="No EDP packages"):
        discover_edp_packages(edp_root)


def test_parses_one_edp_definition(tmp_path: Path) -> None:
    edp_root = tmp_path / "edps"
    create_package(edp_root, "test_edp")

    package = discover_edp_packages(edp_root)[0]
    parsed = parse_edp_package(package)

    assert parsed.property_handle == "test_edp"
    assert parsed.edp_term.origin_name == "CRDC"
    assert parsed.edp_term.origin_id == "CRDC0001"
    assert parsed.edp_term.origin_version == "1"


def test_rejects_directory_handle_mismatch(
    tmp_path: Path,
) -> None:
    edp_root = tmp_path / "edps"
    package = create_package(edp_root, "actual_handle")

    data = yaml.safe_load(
        (package / "edp-props.yml").read_text(encoding="utf-8")
    )
    definition = data["PropDefinitions"].pop("actual_handle")
    data["PropDefinitions"]["different_handle"] = definition
    write_yaml(package / "edp-props.yml", data)

    with pytest.raises(ValueError, match="does not match"):
        parse_edp_package(
            discover_edp_packages(edp_root)[0]
        )


def test_rejects_multiple_edps_in_one_package(
    tmp_path: Path,
) -> None:
    edp_root = tmp_path / "edps"
    package = create_package(edp_root, "first_edp")

    data = yaml.safe_load(
        (package / "edp-props.yml").read_text(encoding="utf-8")
    )
    data["PropDefinitions"]["second_edp"] = {
        "Ext": True,
        "Term": [
            {
                "Origin": "CRDC",
                "Code": "CRDC0002",
                "Version": "1",
                "Value": "Second EDP",
            }
        ],
        "Enum": ["term_1"],
    }
    write_yaml(package / "edp-props.yml", data)

    with pytest.raises(
        ValueError,
        match="exactly one",
    ):
        parse_edp_package(
            discover_edp_packages(edp_root)[0]
        )


def test_rejects_duplicate_edp_identity(
    tmp_path: Path,
) -> None:
    edp_root = tmp_path / "edps"

    create_package(
        edp_root,
        "first_edp",
        origin="CRDC",
        code="CRDC0001",
        version="1",
    )
    create_package(
        edp_root,
        "second_edp",
        origin="CRDC",
        code="CRDC0001",
        version="1",
    )

    with pytest.raises(ValueError, match="Duplicate EDP identity"):
        load_all_edp_packages(edp_root)


def test_source_hash_changes_when_props_change(
    tmp_path: Path,
) -> None:
    edp_root = tmp_path / "edps"
    package_dir = create_package(edp_root, "test_edp")

    package = discover_edp_packages(edp_root)[0]
    original_hash = package.source_hash()

    data = yaml.safe_load(
        (package_dir / "edp-props.yml").read_text(
            encoding="utf-8"
        )
    )
    data["PropDefinitions"]["test_edp"]["Desc"] = "Updated"
    write_yaml(package_dir / "edp-props.yml", data)

    assert package.source_hash() != original_hash


def test_source_hash_changes_when_terms_change(
    tmp_path: Path,
) -> None:
    edp_root = tmp_path / "edps"
    package_dir = create_package(edp_root, "test_edp")

    package = discover_edp_packages(edp_root)[0]
    original_hash = package.source_hash()

    data = yaml.safe_load(
        (package_dir / "terms.yml").read_text(
            encoding="utf-8"
        )
    )
    data["Terms"]["term_1"]["Definition"] = "Updated"
    write_yaml(package_dir / "terms.yml", data)

    assert package.source_hash() != original_hash