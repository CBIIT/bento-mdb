"""Discovery and parsing for self-contained EDP packages."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from bento_mdf import MDF


@dataclass(frozen=True)
class EDPPackage:
    directory: Path
    props_file: Path
    terms_file: Path

    @property
    def name(self) -> str:
        return self.directory.name

@dataclass(frozen=True)
class ParsedEDPPackage:
    package: EDPPackage
    property_handle: str
    property_definition: object
    edp_term: object


def discover_edp_packages(edp_root: Path) -> list[EDPPackage]:
    edp_root = Path(edp_root)

    if not edp_root.is_dir():
        raise ValueError(f"EDP root does not exist: {edp_root}")

    packages: list[EDPPackage] = []

    for directory in sorted(
        (path for path in edp_root.iterdir() if path.is_dir()),
        key=lambda path: path.name,
    ):
        props_file = directory / "edp-props.yml"
        terms_file = directory / "terms.yml"

        missing = [
            path.name
            for path in (props_file, terms_file)
            if not path.is_file()
        ]
        if missing:
            raise ValueError(
                f"EDP package '{directory.name}' is missing: "
                f"{', '.join(missing)}"
            )

        packages.append(
            EDPPackage(
                directory=directory,
                props_file=props_file,
                terms_file=terms_file,
            )
        )

    if not packages:
        raise ValueError(f"No EDP packages found under {edp_root}")

    return packages


def parse_edp_package(package: EDPPackage) -> ParsedEDPPackage:
    mdf = MDF(
        package.props_file,
        package.terms_file,
        handle="_EDP",
        raise_error=True,
    )

    definitions = getattr(mdf.model, "edp_definitions", {})

    if len(definitions) != 1:
        raise ValueError(
            f"EDP package '{package.name}' must contain exactly one "
            f"Ext: true PropDefinition; found {len(definitions)}"
        )

    property_handle, prop = next(iter(definitions.items()))

    if property_handle != package.name:
        raise ValueError(
            f"EDP directory '{package.name}' does not match property "
            f"handle '{property_handle}'"
        )

    if not prop.concept or len(prop.concept.terms) != 1:
        raise ValueError(
            f"EDP '{property_handle}' must define exactly one identity Term"
        )

    edp_term = next(iter(prop.concept.terms.values()))

    for attribute, label in (
        ("origin_name", "Origin"),
        ("origin_id", "Code"),
        ("origin_version", "Version"),
    ):
        if not getattr(edp_term, attribute, None):
            raise ValueError(
                f"EDP '{property_handle}' has no Term {label}"
            )

    return ParsedEDPPackage(
        package=package,
        property_handle=property_handle,
        property_definition=prop,
        edp_term=edp_term,
    )


def load_all_edp_packages(edp_root: Path) -> list[ParsedEDPPackage]:
    parsed = [
        parse_edp_package(package)
        for package in discover_edp_packages(edp_root)
    ]

    handles: set[str] = set()
    identities: set[tuple[str, str, str]] = set()

    for item in parsed:
        identity = (
            str(item.edp_term.origin_name),
            str(item.edp_term.origin_id),
            str(item.edp_term.origin_version),
        )

        if item.property_handle in handles:
            raise ValueError(
                f"Duplicate EDP property handle: {item.property_handle}"
            )

        if identity in identities:
            raise ValueError(
                f"Duplicate EDP identity: {'/'.join(identity)}"
            )

        handles.add(item.property_handle)
        identities.add(identity)

    return parsed