"""
Constants for MDB updates.

This module organizes constants by domain for better maintainability.
"""

import logging

# =============================================================================
# MDB Configuration Constants
# =============================================================================

VALID_MDB_IDS = [
    "fnl-mdb-dev",
    "fnl-mdb-qa",
    "cloud-one-mdb-dev",
    "cloud-one-mdb-qa",
    "cloud-one-mdb-stage",
    "cloud-one-mdb-prod",
    "og-mdb-dev",
    "og-mdb-nightly",
    "og-mdb-prod",
]

MDB_IDS_WITH_PRERELEASES = [
    "og-mdb-nightly",
    "fnl-mdb-dev",
    "cloud-one-mdb-dev",
]

# =============================================================================
# Database Schema Constants
# =============================================================================

MDB_REL_TYPES = [
    "has_term",
    "IN_CHANGELOG",
    "represents",
    "has_tag",
    "has_property",
    "has_concept",
    "has_value_set",
    "has_src",
    "has_dst",
]

# =============================================================================
# GitHub Configuration Constants
# =============================================================================

GITHUB_TOKEN_SECRET = "mdb-updates-github-token"  # noqa: S105
GITHUB_TOKEN_SECRET_NWM = "nwm-github-token"  # noqa: S105
MDB_UPDATES_GH_REPO = "nelsonwmoore/bento-mdb-updates"
DH_TERMS_GH_REPO = "CBIIT/crdc-datahub-terms"
VALID_TIERS = {
    "lower": ["dev", "dev2", "qa", "qa2"],
    "upper": ["stage", "prod"],
}

# =============================================================================
# External Data Source Constants
# =============================================================================

NCIM_TSV_NAME = "NCIt_Metathesaurus_Mapping_202508.txt"

# =============================================================================
# AWS/S3 Configuration Constants
# =============================================================================

DEFAULT_S3_ENDPOINT = "s3.us-east-1.amazonaws.com"

# =============================================================================
# Logging Configuration Constants
# =============================================================================

VALID_LOG_LEVELS = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "severe": logging.CRITICAL,
    "off": logging.NOTSET,
}
