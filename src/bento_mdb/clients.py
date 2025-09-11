"""API clients for Data Hub terms."""

from __future__ import annotations

import csv
import datetime
import io
import logging
import os
import re
import subprocess
import zipfile
from json import JSONDecodeError
from pathlib import Path
from typing import TYPE_CHECKING

import requests
import stamina
import yaml
from tqdm import tqdm

from bento_mdb_updates.constants import NCIM_TSV_NAME

if TYPE_CHECKING:
    from bento_mdb_updates.datatypes import AnnotationSpec, MDBCDESpec, PermissibleValue


RESPONSE_200 = 200
DEFAULT_TIMEOUT = 120
DEFAULT_RETRIES = 3
DEFAULT_RETRY_DELAY = 1.0

SYNC_STATUS_YAML = Path("config/sync_status.yml")

logger = logging.getLogger(__name__)


def get_last_sync_date(
    source: str,
    yaml_path: Path = SYNC_STATUS_YAML,
) -> datetime.datetime:
    """Get last updated date from sync_status.yml."""
    if not yaml_path.exists():
        msg = f"File {yaml_path} does not exist."
        raise FileNotFoundError(msg)
    with yaml_path.open(mode="r", encoding="utf-8") as f:
        sync_status = yaml.safe_load(f)
    return datetime.datetime.strptime(
        sync_status[source]["last_updated"],
        sync_status[source]["date_format"],
    ).replace(tzinfo=datetime.UTC)


class CADSRClient:
    """Client for caDSR II API."""

    def __init__(self) -> None:
        """Initialize client."""

    def get_valueset_from_json(
        self,
        json_response: dict,
    ) -> list[PermissibleValue | None]:
        """Get value set from JSON response."""
        try:
            vs = []
            cde_pvs = json_response["DataElement"]["ValueDomain"].get(
                "PermissibleValues",
                [],
            )
            if not cde_pvs:
                logger.warning(
                    "No permissible values found for CDE %s v%s",
                    json_response["DataElement"]["publicId"],
                    json_response["DataElement"]["version"],
                )
                return vs
            for pv in cde_pvs:
                pv_dict = {
                    "value": pv["value"],
                    "origin_version": pv["ValueMeaning"]["version"],
                    "origin_id": pv["ValueMeaning"]["publicId"],
                    "origin_definition": pv["ValueMeaning"]["definition"],
                    "origin_name": "caDSR",
                    "ncit_concept_codes": [],
                    "synonyms": [],
                }
                vm_concepts = pv["ValueMeaning"].get("Concepts", [])
                for concept in vm_concepts:
                    if concept.get("evsSource") != "NCI_CONCEPT_CODE":
                        continue
                    pv_dict["ncit_concept_codes"].append(concept["conceptCode"])
                    if len(vm_concepts) > 1:
                        msg = "Multiple NCIt concepts found for PV %s: %sv%s"
                        logger.warning(
                            msg,
                            pv["value"],
                            pv["ValueMeaning"]["publicId"],
                            pv["ValueMeaning"]["version"],
                        )
                        continue  # TODO: break out of concepts loop?
                    pv_dict["synonyms"].append(
                        {
                            "value": concept["longName"],
                            "origin_id": concept["conceptCode"],
                            "origin_definition": concept["definition"],
                            "origin_name": "NCIt",
                        },
                    )
                vs.append(pv_dict)
        except Exception as e:
            msg = f"Exception occurred when getting value set from JSON: {e}"
            logger.exception(msg)
            return []
        else:
            return vs

    @stamina.retry(on=requests.RequestException, attempts=DEFAULT_RETRIES)
    def fetch_cde_valueset(
        self,
        cde_id: str,
        cde_version: str | None = None,
        entity_key: str | None = None,
    ) -> list[PermissibleValue | None]:
        """Fetch CDE value set from caDSR II API."""
        ver_str = (
            f"?version={cde_version}"
            if cde_version and re.match(r"^v?\d{1,3}(\.\d{1,3}){0,2}$", cde_version)
            else ""
        )
        cde_id_ver_str = f"{cde_id}{ver_str}"
        url = f"https://cadsrapi.cancer.gov/rad/NCIAPI/1.0/api/DataElement/{cde_id_ver_str}"
        headers = {"accept": "application/json"}

        try:
            response = requests.get(url, timeout=DEFAULT_TIMEOUT, headers=headers)
            response.raise_for_status()
            json_response = response.json()
            value_set = self.get_valueset_from_json(json_response)
        except JSONDecodeError as e:
            msg = (
                f"Failed to parse JSON response for entity{entity_key}: {e}\nurl: {url}"
            )
            logger.exception(msg)
            return []
        except requests.HTTPError:
            msg = (
                f"HTTP error fetching value set for CDE {cde_id}v{cde_version}"
                f" for entity {entity_key}"
            )
            logger.exception(msg)
            return []
        else:
            return value_set

    def check_cdes_against_mdb(
        self,
        mdb_cdes: list[MDBCDESpec],
    ) -> list[AnnotationSpec]:
        """For MDB CDEs with PVs, check caDSR for new PVs."""
        result = []
        for cde_spec in tqdm(mdb_cdes, desc="Checking caDSR for new PVs..."):
            mdb_pvs = [pv["value"] for pv in cde_spec["permissibleValues"]]
            cadsr_pvs = self.fetch_cde_valueset(
                cde_id=cde_spec["CDECode"],
                cde_version=cde_spec.get("CDEVersion"),
            )
            if not cadsr_pvs:
                logger.exception(
                    "Error fetching PVs from caDSR for %sv%s",
                    cde_spec["CDECode"],
                    cde_spec.get("CDEVersion"),
                )
            annotation_spec: AnnotationSpec = {
                "entity": {},
                "annotation": {
                    "key": (cde_spec["CDEFullName"], cde_spec["CDEOrigin"]),
                    "attrs": {
                        "origin_id": cde_spec["CDECode"],
                        "origin_version": cde_spec.get("CDEVersion"),
                        "origin_name": cde_spec["CDEOrigin"],
                        "value": cde_spec["CDEFullName"],
                    },
                },
                "value_set": [],
            }
            update_annotation = False
            for pv in cadsr_pvs:
                if not pv:
                    logger.exception(
                        "PVs from caDSR for %sv%s are null",
                        cde_spec["CDECode"],
                        cde_spec.get("CDEVersion"),
                    )
                    continue
                if pv["value"] in mdb_pvs:
                    continue
                logger.info("New PV found: %s", pv["value"])
                update_annotation = True
                annotation_spec["value_set"].append(pv)
            if not update_annotation:
                continue
            result.append(annotation_spec)
        return result


class NCItClient:
    """Client for NCIt API."""

    DEFAULT_NCIM_TSV = Path().cwd() / "data/source/NCIt" / NCIM_TSV_NAME
    DEFAULT_NCIM_README_URL = (
        "https://evs.nci.nih.gov/ftp1/Mappings/NCIt_Metathesaurus_Mapping.README.txt"
    )
    DEFAULT_NCIM_ZIP_URL = (
        "https://evs.nci.nih.gov/ftp1/Mappings/NCIt_Metathesaurus_Mapping.txt.zip"
    )
    SOURCE_KEY = "NCIt"
    DATE_FMT = "%Y%m"

    def __init__(
        self,
        ncim_tsv: Path | None = None,
        readme_url: str | None = None,
        zip_url: str | None = None,
    ) -> None:
        """Initialize client."""
        self.readme_url = readme_url or self.DEFAULT_NCIM_README_URL
        self.zip_url = zip_url or self.DEFAULT_NCIM_ZIP_URL
        if not ncim_tsv:
            ncim_tsv = self.DEFAULT_NCIM_TSV
        self.ncim_mapping: dict = self.load_ncim_tsv_to_dict(ncim_tsv)

    def get_readme_date(self) -> datetime.datetime | None:
        """Fetch README file at self.readme_url and return the latest update date."""
        if not self.readme_url:
            msg = "readme_url is not set"
            raise ValueError(msg)

        response = requests.get(self.readme_url, timeout=DEFAULT_TIMEOUT)
        response.raise_for_status()

        match = re.search(
            r"NCIm version:\s*(\d{6})",
            response.text.splitlines()[0].strip(),
        )
        return (
            datetime.datetime.strptime(
                match.group(1),
                self.DATE_FMT,
            ).replace(tzinfo=datetime.UTC)
            if match
            else None
        )

    def download_and_extract_tsv(
        self,
        tsv_filename: str = DEFAULT_NCIM_TSV.name,
        save_path: Path | None = None,
    ) -> dict:
        """Download and extract NCIt mappings TSV file from self.zip_url."""
        if not self.zip_url:
            msg = "zip_url is not set"
            raise ValueError(msg)
        response = requests.get(self.zip_url, timeout=DEFAULT_TIMEOUT)
        response.raise_for_status()

        with zipfile.ZipFile(io.BytesIO(response.content), "r") as zip_ref:
            with zip_ref.open(tsv_filename) as f:
                tsv_content = f.read()
                if save_path:
                    with save_path.open("wb") as save_file:
                        save_file.write(tsv_content)
                decoded_content = io.BytesIO(tsv_content)
                return self.load_ncim_tsv_to_dict(decoded_content)

    def load_ncim_tsv_to_dict(
        self,
        ncim_tsv: Path | io.TextIOWrapper | io.BytesIO | None = None,
    ) -> dict:
        """Load NCIm TSV file to dict."""
        if not ncim_tsv:
            logger.warning("No NCIm TSV file provided.")
            return {}
        ncim = {}
        if isinstance(ncim_tsv, Path):
            file = ncim_tsv.open(mode="r", encoding="utf-8")
        elif isinstance(ncim_tsv, io.BytesIO):
            file = io.TextIOWrapper(ncim_tsv, encoding="utf-8")
        else:
            file = ncim_tsv
        with file as f:
            reader = csv.reader(f, delimiter="\t")
            next(reader, None)
            for row in reader:
                if len(row) < 8:
                    logger.warning("NCIm TSV row is missing required fields: %s", row)
                    continue
                nci_code = row[2]
                syn_attrs = {
                    "origin_id": row[4],
                    "origin_name": row[6],
                    "origin_version": row[7],
                    "value": row[5],
                }
                if nci_code in ncim:
                    ncim[nci_code].append(syn_attrs)
                else:
                    ncim[nci_code] = [syn_attrs]
        return ncim

    def check_ncit_for_updated_mappings(self, *, force_update: bool = False) -> bool:
        """Check NCIt for new mappings."""
        latest = self.get_readme_date()
        last = get_last_sync_date(self.SOURCE_KEY)
        if not force_update and (not latest or latest <= last):
            logger.info("No new mappings to sync.")
            return False
        logger.info("New mappings with date %s found. Syncing...", latest)
        self.ncim_mapping = self.download_and_extract_tsv()
        return True

    def check_synonyms_against_mdb(
        self,
        mdb_cdes: list[MDBCDESpec],
    ) -> list[AnnotationSpec]:
        """For MDB CDEs with PVs, check NCIt for new PV synonyms."""
        result = []
        for cde_spec in tqdm(mdb_cdes, desc="Checking NCIt for new synonyms..."):
            annotation_spec: AnnotationSpec = {
                "entity": {},
                "annotation": {
                    "key": (cde_spec["CDEFullName"], cde_spec["CDEOrigin"]),
                    "attrs": {
                        "origin_id": cde_spec["CDECode"],
                        "origin_version": cde_spec.get("CDEVersion"),
                        "origin_name": cde_spec["CDEOrigin"],
                        "value": cde_spec["CDEFullName"],
                    },
                },
                "value_set": [],
            }
            for pv in cde_spec["permissibleValues"]:
                mdb_synonyms = pv.get("synonyms", [])
                logger.debug(mdb_synonyms)
                mdb_synonyms_frozen = {frozenset(syn.items()) for syn in mdb_synonyms}
                pv_ncit_codes = [
                    syn.get("origin_id")
                    for syn in mdb_synonyms
                    if syn.get("origin_name") in ["NCIt", "NCIm"]
                ]
                update_annotation = False
                synonyms_to_add = []
                for code in pv_ncit_codes:
                    if not code or code not in self.ncim_mapping:
                        logger.info("No NCIm mapping for %s", code)
                        continue
                    ncim_synonyms = self.ncim_mapping[code]
                    logger.debug(ncim_synonyms)
                    for ncim_syn in ncim_synonyms:
                        ncim_syn_frozen = frozenset(ncim_syn.items())
                        if ncim_syn_frozen in mdb_synonyms_frozen:
                            logger.info("NCIm synonym already exists: %s", ncim_syn)
                            continue
                        logger.info("New synonym found: %s", ncim_syn["value"])
                        update_annotation = True
                        synonyms_to_add.append(ncim_syn)
                if not update_annotation:
                    continue
                pv["synonyms"].extend(synonyms_to_add)
                annotation_spec["value_set"].append(pv)
            if not annotation_spec["value_set"]:
                continue
            result.append(annotation_spec)
        return result


class GitHubClient:  # TODO: replace with GitHub API client
    """Client to interact with GitHub API."""

    BASE_URL = "https://api.github.com"
    DH_MODEL_REPO = "CBIIT/crdc-datahub-models"

    def __init__(self, github_token: str | None = None) -> None:
        """Initialize client."""
        self.github_token = github_token if github_token else os.environ["GITHUB_TOKEN"]
        self.headers = {
            "Authorization": f"token {self.github_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        self.session = requests.Session()
        self.session.headers.update(self.headers)

    def get_repo_tags(self, repo: str) -> list[str] | None:
        """Query GitHub API for tags on a given repository."""
        url = f"{self.BASE_URL}/repos/{repo}/tags"
        response = self.session.get(url, timeout=DEFAULT_TIMEOUT)
        if response.status_code != RESPONSE_200:
            logger.error(
                "Failed to get latest prerelease commit for %s: %s",
                repo,
                response.status_code,
            )
            response.raise_for_status()
        tags = response.json()
        if not tags:
            logger.warning("No tags found for repo %s", repo)
            return []
        return [tag["name"] for tag in tags]

    def commit_and_push_changes(
        self,
        file_to_commit: Path,
        commit_msg: str | None = None,
    ) -> None:
        """Commit and push changes to repo."""
        try:
            subprocess.run(["git", "add", str(file_to_commit)], check=True)
            commit_msg = commit_msg or f"Update {file_to_commit.name}"
            subprocess.run(["git", "commit", "-m", commit_msg], check=True)
            subprocess.run(["git", "push"], check=True)
            logger.info("Changes committed and pushed successfully.")
        except subprocess.CalledProcessError:
            logger.exception("Failed to add %s to git", file_to_commit.name)
            return

    def get_prerelease_model_info(self, model: str) -> tuple[str, str] | None:
        """Get latest commit SHA & version for prerelease model from DH cache."""
        url = f"{self.BASE_URL}/repos/{self.DH_MODEL_REPO}/commits"
        params = {
            "sha": "dev2",
            "path": f"cache/{model}",
            "per_page": 1,
        }
        response = self.session.get(url, params=params, timeout=DEFAULT_TIMEOUT)
        if response.status_code != RESPONSE_200:
            logger.error(
                "Failed to get latest prerelease commit for %s: %s",
                model,
                response.status_code,
            )
            response.raise_for_status()
        commits = response.json()
        if not commits:
            logger.warning("No commits found for path cache/%s on branch dev2", model)
            return None
        commit_sha = commits[0]["sha"]

        commit_url = f"{self.BASE_URL}/repos/{self.DH_MODEL_REPO}/commits/{commit_sha}"
        commit_response = self.session.get(commit_url, timeout=DEFAULT_TIMEOUT)
        if commit_response.status_code != RESPONSE_200:
            logger.error("Failed to get commit details for %s", commit_sha)
            return None
        commit_data = commit_response.json()
        cache_prefix = f"cache/{model}/"
        for file_info in commit_data.get("files", []):
            file_path = file_info["filename"]
            if file_path.startswith(cache_prefix):
                # Extract everything after "cache/{model}/" up to the next "/"
                remainder = file_path[len(cache_prefix) :]
                if "/" in remainder:
                    version = remainder.split("/")[0]
                    logger.info(
                        "Found latest prerelease version %s for model %s",
                        version,
                        model,
                    )
                    return commit_sha, version

        logger.warning("Could not extract version from commit files for %s", model)
        return None
