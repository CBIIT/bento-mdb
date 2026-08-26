from pathlib import Path
from shutil import copyfile

import yaml
from click.testing import CliRunner

import scripts.check_new_mdfs as check_new_mdfs


SAMPLE_MODEL_SPECS = Path(__file__).parent / "samples" / "test_mdb_models.yml"


class FakeGitHubClient:
    def get_repo_tags(self, repo: str) -> list[str]:
        if repo == "CBIIT/test-model-4":
            return ["1.1.0", "1.0.0"]
        return []

    def get_prerelease_model_info(self, model: str) -> tuple[str, str] | None:
        if model == "TEST2":
            return "new-test2-commit", "1.2.0"
        if model == "TEST3":
            return "wxyz7894f69bd15672c4c380c562a7f0b40kdn2d", "2.1.0"
        return None


def test_other_model_update_leaves_all_ignored_latest_version_null(
    tmp_path: Path,
    monkeypatch,
) -> None:
    model_specs_path = tmp_path / "mdb_models.yml"
    copyfile(SAMPLE_MODEL_SPECS, model_specs_path)
    monkeypatch.setattr(check_new_mdfs, "GitHubClient", FakeGitHubClient)

    result = CliRunner().invoke(
        check_new_mdfs.main,
        [
            "--model_specs_yaml",
            str(model_specs_path),
            "--no_commit",
            "true",
        ],
    )

    assert result.exit_code == 0, result.output
    saved_specs = yaml.safe_load(model_specs_path.read_text(encoding="utf-8"))
    assert saved_specs["TEST2"]["latest_prerelease_commit"] == "new-test2-commit"
    assert saved_specs["TEST4"]["latest_version"] is None
