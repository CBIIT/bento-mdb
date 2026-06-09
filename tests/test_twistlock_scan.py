from __future__ import annotations

from dataclasses import dataclass

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


def test_parse_image_refs_accepts_single_string() -> None:
    refs = flow_module._parse_image_refs(TEST_REPO_IMAGE)

    assert [ref.value for ref in refs] == [TEST_REPO_IMAGE]


def test_parse_image_refs_accepts_list() -> None:
    refs = flow_module._parse_image_refs([TEST_REPO_IMAGE, TEST_FAST_API_IMAGE])

    assert [ref.value for ref in refs] == [TEST_REPO_IMAGE, TEST_FAST_API_IMAGE]


def test_parse_image_refs_rejects_empty_list() -> None:
    with pytest.raises(RuntimeError, match="at least one"):
        flow_module._parse_image_refs([])


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


def test_registry_scan_rescans_when_row_already_exists(
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
    assert http.matching_calls("/registry/scan")
    assert not http.matching_calls("/registry/progress?")


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
    )

    assert len(http.matching_calls("compact=true")) == 3


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


def test_registry_progress_uses_on_demand_repo_and_tag_query(monkeypatch) -> None:
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
        return []

    monkeypatch.setattr(flow_module, "_http_json_request", fake_http_json_request)

    out = flow_module._registry_progress(
        _test_settings(), "token-1", ImageRef.parse(TEST_REPO_IMAGE)
    )

    assert out == []
    assert calls == [
        {
            "method": "GET",
            "url": (
                "https://twistlock.example.test/api/v34.02/registry/progress"
                "?onDemand=true&repo=repo&tag=tag"
            ),
            "token": "token-1",
            "body": None,
            "timeout": 60,
        }
    ]


def test_compact_result_required_raises_when_empty_list_has_no_row(monkeypatch) -> None:
    monkeypatch.setattr(
        flow_module,
        "_registry_result",
        lambda settings, token, image_ref, *, compact: [],
    )

    with pytest.raises(RuntimeError, match="No registry scan result found"):
        flow_module._compact_result(
            _test_settings(), "token-1", ImageRef.parse(TEST_REPO_IMAGE), required=True
        )


def test_compact_result_required_raises_when_null_response_has_no_row(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        flow_module,
        "_registry_result",
        lambda settings, token, image_ref, *, compact: None,
    )

    with pytest.raises(RuntimeError, match="No registry scan result found"):
        flow_module._compact_result(
            _test_settings(), "token-1", ImageRef.parse(TEST_REPO_IMAGE), required=True
        )


def test_compact_result_returns_first_row_from_list(monkeypatch) -> None:
    row = {"vulnerabilityDistribution": {"critical": 0, "high": 0}}
    monkeypatch.setattr(
        flow_module,
        "_registry_result",
        lambda settings, token, image_ref, *, compact: [row],
    )

    out = flow_module._compact_result(
        _test_settings(), "token-1", ImageRef.parse(TEST_REPO_IMAGE), required=True
    )

    assert out == row


def test_compact_result_rejects_unexpected_list_item(monkeypatch) -> None:
    monkeypatch.setattr(
        flow_module,
        "_registry_result",
        lambda settings, token, image_ref, *, compact: ["not-a-row"],
    )

    with pytest.raises(RuntimeError, match="Unexpected registry result item type: str"):
        flow_module._compact_result(
            _test_settings(), "token-1", ImageRef.parse(TEST_REPO_IMAGE), required=False
        )


def test_compact_result_rejects_unexpected_response_type(monkeypatch) -> None:
    monkeypatch.setattr(
        flow_module,
        "_registry_result",
        lambda settings, token, image_ref, *, compact: "not-a-response",
    )

    with pytest.raises(RuntimeError, match="Unexpected registry result type: str"):
        flow_module._compact_result(
            _test_settings(), "token-1", ImageRef.parse(TEST_REPO_IMAGE), required=False
        )


def test_raise_if_critical_high_reports_fails_after_reports_are_collected() -> None:
    reports = [
        {
            "image_ref": TEST_FAST_API_IMAGE,
            "microservice": "crdc-mdb-sts-fast-api",
            "status": "passed",
            "passed": True,
            "critical": 0,
            "high": 0,
            "vulnerabilities": [],
            "message": "ok",
        },
        {
            "image_ref": TEST_REPO_IMAGE,
            "microservice": "repo",
            "status": "failed",
            "passed": False,
            "critical": 22,
            "high": 56,
            "vulnerabilities": [],
            "message": "Scan policy failed: critical=22 high=56",
        },
    ]

    with pytest.raises(RuntimeError, match="critical=22 high=56"):
        flow_module._raise_if_critical_high_reports(reports)
