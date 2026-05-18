from __future__ import annotations

from dataclasses import dataclass

import pytest

import bento_mdb.flows.twistlock_scan as flow_module
from bento_mdb.flows.twistlock_scan import (
    DEFAULT_COMPUTE_API_VERSION,
    DEFAULT_SCAN_SELECT_COLLECTIONS,
    DEFAULT_SCAN_SELECT_PROJECT,
    DEFAULT_TWISTLOCK_ADDRESS,
    HttpTwistlockRegistryClient,
    ImageRef,
    PrefectTwistlockSettingsLoader,
    TwistlockRegistryClient,
    TwistlockRegistryScanService,
    TwistlockSettings,
)

TEST_ECR_REGISTRY = "123456789012.dkr.ecr.us-east-1.amazonaws.com"
TEST_FAST_API_IMAGE = f"{TEST_ECR_REGISTRY}/crdc-mdb-sts-fast-api:main.1"
TEST_REPO_IMAGE = f"{TEST_ECR_REGISTRY}/repo:tag"


@dataclass
class DictSettingsLoader(PrefectTwistlockSettingsLoader):
    values: dict[str, str | None]

    def get_secret(self, name: str) -> str | None:
        value = self.values.get(name)
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


def test_twistlock_settings_requires_username_and_password() -> None:
    loader = DictSettingsLoader({})

    with pytest.raises(RuntimeError, match="twistlock-username"):
        TwistlockSettings.from_prefect(loader)


def test_twistlock_settings_uses_defaults_for_optional_secret_values() -> None:
    loader = DictSettingsLoader(
        {
            "twistlock-username": " user ",
            "twistlock-password": " pass ",
        }
    )

    settings = TwistlockSettings.from_prefect(loader)

    assert settings.address == DEFAULT_TWISTLOCK_ADDRESS
    assert settings.api_version == DEFAULT_COMPUTE_API_VERSION
    assert settings.username == "user"
    assert settings.password == "pass"
    assert settings.scan_select_collections == DEFAULT_SCAN_SELECT_COLLECTIONS
    assert settings.scan_select_project == DEFAULT_SCAN_SELECT_PROJECT


def test_twistlock_settings_uses_overrides_and_optional_secret_values() -> None:
    loader = DictSettingsLoader(
        {
            "twistlock-address": "https://secret.example.test",
            "twistlock-api-version": "v99.00",
            "twistlock-username": "user",
            "twistlock-password": "pass",
            "twistlock-scan-select-collections": "Collection A",
            "twistlock-scan-select-project": "Project B",
        }
    )

    settings = TwistlockSettings.from_prefect(
        loader, address_override=" https://override.example.test "
    )

    assert settings.address == "https://override.example.test"
    assert settings.api_version == "v99.00"
    assert settings.scan_select_collections == "Collection A"
    assert settings.scan_select_project == "Project B"


def test_http_client_trigger_scan_select_uses_resolved_collection_and_project(monkeypatch) -> None:
    calls = []

    def fake_http_json_request(method, url, *, token=None, body=None, timeout=120):
        calls.append(
            {
                "method": method,
                "url": url,
                "token": token,
                "body": body,
                "timeout": timeout,
            }
        )
        return {}

    monkeypatch.setattr(flow_module, "_http_json_request", fake_http_json_request)
    client = HttpTwistlockRegistryClient(
        TwistlockSettings(
            address="https://twistlock.example.test/",
            api_version="v34.02",
            username="user",
            password="pass",
            scan_select_collections="Collection A",
            scan_select_project="Project B",
        )
    )

    client.trigger_scan_select("token-1", TEST_ECR_REGISTRY)

    assert len(calls) == 1
    assert calls[0]["method"] == "POST"
    assert (
        calls[0]["url"]
        == "https://twistlock.example.test/api/v1/registry/scan/select"
        "?collections=Collection+A&project=Project+B"
    )
    assert calls[0]["token"] == "token-1"
    assert calls[0]["body"] == [
        {
            "tag": {
                "registry": TEST_ECR_REGISTRY,
                "repo": "",
                "tag": "",
            }
        }
    ]


class FakeClient(TwistlockRegistryClient):
    def __init__(
        self,
        *,
        existing: dict | None = None,
        first_compact_response: dict | list | None = [],
        detailed_payload: dict | None = None,
        compact_result: dict | None = None,
    ):
        self.existing = existing
        self.first_compact_response = first_compact_response
        self.detailed_payload = detailed_payload or {"vulnerabilities": []}
        self.compact_result = compact_result or {"vulnerabilityDistribution": {"critical": 0, "high": 0}}
        self.progress = [{"isScanOngoing": False}]
        self.calls = []
        self._compact_calls = 0

    def authenticate(self) -> str:
        self.calls.append(("authenticate",))
        return "token-1"

    def start_scan(self, token: str, image_ref: ImageRef) -> None:
        self.calls.append(("start_scan", token, image_ref.registry, image_ref.repo, image_ref.tag))

    def trigger_scan_select(self, token: str, registry: str) -> None:
        self.calls.append(("trigger_scan_select", token, registry))

    def registry_result(self, token: str, image_ref: ImageRef, *, compact: bool) -> dict | list | None:
        self.calls.append(("registry_result", token, image_ref.value, compact))
        if compact:
            self._compact_calls += 1
            if self.existing is not None:
                row = self.existing
                self.existing = None
                return row
            if self._compact_calls == 1:
                return self.first_compact_response
            return self.compact_result
        return self.detailed_payload

    def registry_progress(self, token: str, image_ref: ImageRef) -> dict | list:
        self.calls.append(("registry_progress", token, image_ref.value))
        return self.progress


class FakeLogger:
    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass


def test_registry_scan_service_orchestrates_gateway_without_existing_row() -> None:
    client = FakeClient(existing=None)
    service = TwistlockRegistryScanService(client, FakeLogger())

    service.scan(
        ImageRef.parse(TEST_FAST_API_IMAGE),
        microservice_report_name=None,
        trigger_registry_scan_select=True,
        poll_timeout_seconds=30,
        poll_interval_seconds=5,
    )

    assert client.calls == [
        ("authenticate",),
        (
            "registry_result",
            "token-1",
            TEST_FAST_API_IMAGE,
            True,
        ),
        (
            "start_scan",
            "token-1",
            TEST_ECR_REGISTRY,
            "crdc-mdb-sts-fast-api",
            "main.1",
        ),
        ("trigger_scan_select", "token-1", TEST_ECR_REGISTRY),
        (
            "registry_result",
            "token-1",
            TEST_FAST_API_IMAGE,
            True,
        ),
        (
            "registry_result",
            "token-1",
            TEST_FAST_API_IMAGE,
            True,
        ),
        (
            "registry_result",
            "token-1",
            TEST_FAST_API_IMAGE,
            False,
        ),
    ]


def test_registry_scan_service_disables_compact_fallback_when_row_already_exists() -> None:
    client = FakeClient(existing={"name": "already-indexed"})
    service = TwistlockRegistryScanService(client, FakeLogger())

    service.scan(
        ImageRef.parse(TEST_REPO_IMAGE),
        microservice_report_name=None,
        trigger_registry_scan_select=False,
        poll_timeout_seconds=60,
        poll_interval_seconds=10,
    )

    assert ("trigger_scan_select", "token-1", TEST_ECR_REGISTRY) not in client.calls
    assert ("registry_progress", "token-1", TEST_REPO_IMAGE) in client.calls


def test_registry_scan_service_treats_null_compact_lookup_as_missing_row() -> None:
    client = FakeClient(existing=None, first_compact_response=None)
    service = TwistlockRegistryScanService(client, FakeLogger())

    service.scan(
        ImageRef.parse(TEST_REPO_IMAGE),
        microservice_report_name=None,
        trigger_registry_scan_select=False,
        poll_timeout_seconds=60,
        poll_interval_seconds=10,
    )

    assert ("start_scan", "token-1", TEST_ECR_REGISTRY, "repo", "tag") in client.calls
