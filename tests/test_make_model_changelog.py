from pathlib import Path

import yaml
from click.testing import CliRunner

from scripts.make_model_changelog import main


TEST_SAMPLES = Path(__file__).parent / "samples"
TEST_EDP_MODEL = TEST_SAMPLES / "test_model_edp.yml"
TEST_EDP_PROPS = TEST_SAMPLES / "test_mdf_edp.yml"


def test_missing_edp_warns_without_failing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_path = tmp_path / "mdb_edps.yml"
    output_path = tmp_path / "model_changelog.xml"

    config_path.write_text(
        yaml.safe_dump(
            {
                "OTHER_EDP": {
                    "origin": "CRDC",
                    "code": "CRDC0002",
                    "latest_version": "1",
                    "versions": [
                        {
                            "version": "1",
                            "tag": "1",
                        },
                    ],
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("GITHUB_ACTIONS", "true")

    result = CliRunner().invoke(
        main,
        [
            "--model_handle",
            "TEST",
            "--model_version",
            "1.2.3",
            "--mdf_files",
            str(TEST_EDP_MODEL),
            "--mdf_files",
            str(TEST_EDP_PROPS),
            "--edp_config_file",
            str(config_path),
            "--output_file_path",
            str(output_path),
            "--author",
            "Test",
            "--_commit",
            "test-commit",
            "--latest_version",
            "true",
            "--add_rollback",
            "false",
        ],
    )

    assert result.exit_code == 0, result.output
    assert output_path.exists()
    assert "::warning title=Missing EDP reference::" in result.output
    assert "CRDC/CRDC00005/1" in result.output
    assert "TEST/program/program_name" in result.output