from pathlib import Path

import ghost_audit
from evaluation.main import (
    CUSTOM_LABELS_PATH,
    CUSTOM_REQUESTS_PATH,
    SAMPLE_REQUESTS_PATH,
    audit_times,
    evidence_times,
    holdout_case_ids,
    write_suite,
)
from evaluation.validate import csv_rows, data_rows, validation_errors


def _case_ids(path: Path) -> set[str]:
    return {row[0] for row in data_rows(path)}


def test_custom_labels_pass_validation() -> None:
    assert (
        validation_errors(CUSTOM_LABELS_PATH, audit_times(CUSTOM_REQUESTS_PATH), evidence_times())
        == []
    )


def test_suites_split_every_case_by_holdout(tmp_path: Path) -> None:
    all_case_ids = _case_ids(SAMPLE_REQUESTS_PATH) | _case_ids(CUSTOM_REQUESTS_PATH)
    default_dir = tmp_path / "default"
    holdout_dir = tmp_path / "holdout"
    default_dir.mkdir()
    holdout_dir.mkdir()
    default_suite = write_suite(default_dir, is_holdout=False)
    holdout_suite = write_suite(holdout_dir, is_holdout=True)

    assert holdout_case_ids() <= all_case_ids
    for default_path, holdout_path in (
        (default_suite.requests_path, holdout_suite.requests_path),
        (default_suite.labels_path, holdout_suite.labels_path),
    ):
        assert _case_ids(holdout_path) == holdout_case_ids()
        assert _case_ids(default_path) == all_case_ids - holdout_case_ids()


def test_holdout_requests_are_not_prompt_examples() -> None:
    holdout_ids = holdout_case_ids()
    holdout_texts: list[str] = []
    for requests_path in (SAMPLE_REQUESTS_PATH, CUSTOM_REQUESTS_PATH):
        header, *rows = csv_rows(requests_path)
        text_index = header.index("request_text")
        holdout_texts += [row[text_index] for row in rows if row[0] in holdout_ids]
    forbidden = [*holdout_texts, *holdout_ids, "sample_output.csv", CUSTOM_LABELS_PATH.name]
    package_dir = Path(ghost_audit.__file__).parent
    source_texts = [
        path.read_text(encoding="utf-8", errors="ignore")
        for path in package_dir.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    ]

    assert holdout_texts
    assert not [text for text in forbidden if any(text in source for source in source_texts)]
