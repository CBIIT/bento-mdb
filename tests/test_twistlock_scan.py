from __future__ import annotations

from dataclasses import dataclass
import sys
from types import SimpleNamespace

import pytest

import bento_mdb.flows.twistlock_scan as flow_module
from bento_mdb.flows.twistlock_scan import (
    DEFAULT_COMPUTE_API_VERSION,
    DEFAULT_SCAN_SELECT_COLLECTIONS,
    DEFAULT_SCAN_SELECT_PROJECT,
    DEFAULT_TWISTLOCK_ADDRESS,
    ImageRef,
    PrefectTwistlockSettingsLoader,
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


def test_trigger_scan_select_uses_resolved_collection_and_project(
    monkeypatch,
) -> None:
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
    settings = TwistlockSettings(
        address="https://twistlock.example.test/",
        api_version="v34.02",
        username="user",
        password="pass",
        scan_select_collections="Collection A",
        scan_select_project="Project B",
    )

    flow_module._trigger_scan_select(settings, "token-1", TEST_ECR_REGISTRY)

    assert len(calls) == 1
    assert calls[0]["method"] == "POST"
    assert (
        calls[0]["url"] == "https://twistlock.example.test/api/v1/registry/scan/select"
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


def test_ecr_image_digest_uses_describe_images_without_docker(monkeypatch) -> None:
    calls = []

    class FakeEcrClient:
        def describe_images(self, **kwargs):
            calls.append(kwargs)
            return {"imageDetails": [{"imageDigest": "sha256:abc123"}]}

    def fake_client(service_name, *, region_name):
        calls.append({"service_name": service_name, "region_name": region_name})
        return FakeEcrClient()

    monkeypatch.setitem(sys.modules, "boto3", SimpleNamespace(client=fake_client))

    digest = flow_module._ecr_image_digest(ImageRef.parse(TEST_FAST_API_IMAGE))

    assert digest == "sha256:abc123"
    assert calls == [
        {"service_name": "ecr", "region_name": "us-east-1"},
        {
            "registryId": "123456789012",
            "repositoryName": "crdc-mdb-sts-fast-api",
            "imageIds": [{"imageTag": "main.1"}],
        },
    ]


_NO_EXISTING_ROW = object()


class FakeHttp:
    def __init__(
        self,
        *,
        existing: object = _NO_EXISTING_ROW,
        first_compact_response: dict | list | None = [],
        detailed_payload: dict | None = None,
        compact_result: dict | None = None,
    ):
        self.existing = existing
        self.first_compact_response = first_compact_response
        self.detailed_payload = (
            detailed_payload
            if detailed_payload is not None
            else {"vulnerabilities": []}
        )
        self.compact_result = (
            compact_result
            if compact_result is not None
            else {"vulnerabilityDistribution": {"critical": 0, "high": 0}}
        )
        self.progress = [{"isScanOngoing": False}]
        self.calls = []
        self._compact_calls = 0

    def __call__(self, method, url, *, token=None, body=None, timeout=120):
        self.calls.append(
            {
                "method": method,
                "url": url,
                "token": token,
                "body": body,
                "timeout": timeout,
            }
        )
        if url.endswith("/api/v1/authenticate"):
            return {"token": "token-1"}
        if url.endswith("/registry/scan"):
            return {}
        if "/registry/scan/select?" in url:
            return {}
        if "/registry/progress?" in url:
            return self.progress
        if "/registry?" in url:
            compact = "compact=true" in url
            self._compact_calls += 1
            if compact and self.existing is not _NO_EXISTING_ROW:
                row = self.existing
                self.existing = _NO_EXISTING_ROW
                return row
            if compact and self._compact_calls == 1:
                return self.first_compact_response
            return self.compact_result if compact else self.detailed_payload
        raise AssertionError(f"Unexpected request: {method} {url}")

    def matching_calls(self, text: str) -> list[dict]:
        return [call for call in self.calls if text in call["url"]]


class FakeLogger:
    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass


def _test_settings() -> TwistlockSettings:
    return TwistlockSettings(
        address="https://twistlock.example.test",
        api_version="v34.02",
        username="user",
        password="pass",
    )


def test_registry_scan_orchestrates_gateway_without_existing_row(
    monkeypatch,
) -> None:
    http = FakeHttp()
    monkeypatch.setattr(flow_module, "_http_json_request", http)

    flow_module._run_registry_scan(
        _test_settings(),
        FakeLogger(),
        ImageRef.parse(TEST_FAST_API_IMAGE),
        microservice_report_name=None,
        trigger_registry_scan_select=True,
        poll_timeout_seconds=30,
        poll_interval_seconds=5,
    )

    assert [call["method"] for call in http.calls] == [
        "POST",
        "GET",
        "POST",
        "POST",
        "GET",
        "GET",
        "GET",
    ]
    assert len(http.matching_calls("/registry/scan/select?")) == 1
    scan_body = http.matching_calls("/registry/scan")[0]["body"]
    assert scan_body["tag"] == {
        "registry": TEST_ECR_REGISTRY,
        "repo": "crdc-mdb-sts-fast-api",
        "tag": "main.1",
        "digest": "",
    }


def test_registry_scan_uses_existing_registry_row_when_row_already_exists(
    monkeypatch,
) -> None:
    http = FakeHttp(
        existing={
            "name": "already-indexed",
            "vulnerabilityDistribution": {"critical": 0, "high": 0},
        }
    )
    monkeypatch.setattr(flow_module, "_http_json_request", http)

    flow_module._run_registry_scan(
        _test_settings(),
        FakeLogger(),
        ImageRef.parse(TEST_REPO_IMAGE),
        microservice_report_name=None,
        trigger_registry_scan_select=False,
        poll_timeout_seconds=60,
        poll_interval_seconds=10,
    )

    assert not http.matching_calls("/registry/scan/select?")
    assert not http.matching_calls("/registry/scan")
    assert not http.matching_calls("/registry/progress?")


def test_registry_scan_force_rescan_waits_when_row_already_exists(
    monkeypatch,
) -> None:
    http = FakeHttp(
        existing={
            "name": "already-indexed",
            "vulnerabilityDistribution": {"critical": 0, "high": 0},
        }
    )
    monkeypatch.setattr(flow_module, "_http_json_request", http)

    flow_module._run_registry_scan(
        _test_settings(),
        FakeLogger(),
        ImageRef.parse(TEST_REPO_IMAGE),
        microservice_report_name=None,
        trigger_registry_scan_select=False,
        poll_timeout_seconds=60,
        poll_interval_seconds=10,
        force_rescan=True,
    )

    assert not http.matching_calls("/registry/scan/select?")
    assert http.matching_calls("/registry/scan")
    assert len(http.matching_calls("/registry/progress?")) == 1


def test_registry_scan_uses_compact_fallback_when_existing_row_matches_ecr_digest(
    monkeypatch,
) -> None:
    http = FakeHttp(existing={"name": TEST_REPO_IMAGE, "digest": "sha256:old"})
    http.progress = []
    http.compact_result = {
        "name": TEST_REPO_IMAGE,
        "digest": "sha256:new",
        "vulnerabilityDistribution": {"critical": 0, "high": 0},
    }
    monkeypatch.setattr(flow_module, "_http_json_request", http)

    flow_module._run_registry_scan(
        _test_settings(),
        FakeLogger(),
        ImageRef.parse(TEST_REPO_IMAGE),
        microservice_report_name=None,
        trigger_registry_scan_select=False,
        poll_timeout_seconds=60,
        poll_interval_seconds=10,
        expected_image_digest="sha256:new",
        force_rescan=True,
    )

    assert len(http.matching_calls("compact=true")) >= 3


def test_registry_scan_uses_compact_fallback_when_scan_time_is_fresh(
    monkeypatch,
) -> None:
    http = FakeHttp(
        existing={
            "name": TEST_REPO_IMAGE,
            "id": "sha256:image-id-not-ecr-manifest",
            "scanTime": "2026-06-03T20:48:42.231Z",
        }
    )
    http.progress = []
    http.compact_result = {
        "name": TEST_REPO_IMAGE,
        "id": "sha256:image-id-not-ecr-manifest",
        "scanTime": "2026-06-04T16:30:00.000Z",
        "vulnerabilityDistribution": {"critical": 0, "high": 0},
    }
    monkeypatch.setattr(flow_module, "_http_json_request", http)
    now_values = iter(
        [
            1_780_589_900.0,
            1_780_589_900.0,
            1_780_589_910.0,
            1_780_589_920.0,
            1_780_589_930.0,
            1_780_589_970.0,
        ]
    )
    monkeypatch.setattr(flow_module.time, "time", lambda: next(now_values))
    monkeypatch.setattr(flow_module.time, "sleep", lambda _seconds: None)

    flow_module._run_registry_scan(
        _test_settings(),
        FakeLogger(),
        ImageRef.parse(TEST_REPO_IMAGE),
        microservice_report_name=None,
        trigger_registry_scan_select=False,
        poll_timeout_seconds=60,
        poll_interval_seconds=10,
        expected_image_digest="sha256:ecr-manifest",
        force_rescan=True,
    )

    assert len(http.matching_calls("compact=true")) >= 3


def test_registry_scan_treats_empty_compact_dict_as_existing_row(
    monkeypatch,
) -> None:
    http = FakeHttp(existing={})
    monkeypatch.setattr(flow_module, "_http_json_request", http)

    flow_module._run_registry_scan(
        _test_settings(),
        FakeLogger(),
        ImageRef.parse(TEST_REPO_IMAGE),
        microservice_report_name=None,
        trigger_registry_scan_select=False,
        poll_timeout_seconds=60,
        poll_interval_seconds=10,
        force_rescan=True,
    )

    assert len(http.matching_calls("compact=true")) == 2


def test_registry_scan_verify_treats_empty_compact_dict_as_found(
    monkeypatch,
) -> None:
    http = FakeHttp(existing={})
    monkeypatch.setattr(flow_module, "_http_json_request", http)

    out = flow_module._verify_registry_image(
        _test_settings(),
        FakeLogger(),
        ImageRef.parse(TEST_REPO_IMAGE),
        fail_if_not_found=True,
    )

    assert out == {"found": True, "image_ref": TEST_REPO_IMAGE, "row": {}}


def test_registry_scan_treats_null_compact_lookup_as_missing_row(
    monkeypatch,
) -> None:
    http = FakeHttp(first_compact_response=None)
    monkeypatch.setattr(flow_module, "_http_json_request", http)

    flow_module._run_registry_scan(
        _test_settings(),
        FakeLogger(),
        ImageRef.parse(TEST_REPO_IMAGE),
        microservice_report_name=None,
        trigger_registry_scan_select=False,
        poll_timeout_seconds=60,
        poll_interval_seconds=10,
    )

    assert http.matching_calls("/registry/scan")
