"""Tests for lens precision labeling against a corpus with independent per-file verdicts."""

from __future__ import annotations

import argparse
import json
import subprocess
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
import yaml
from fdai.core.security.code_findings.lens_evaluation import (
    LensCorpus,
    LensCorpusError,
    label_hypotheses,
    lens_corpus_from_mapping,
    lens_metrics,
    parse_labels,
    select_sample,
)
from fdai.core.security.code_findings.models import Lane, Occurrence, SourceLocation
from fdai.delivery import code_security_lens_eval
from fdai.delivery.code_security_cli import main
from fdai.rule_catalog.code_security_lenses import load_lens_catalog
from fdai.shared.providers.code_security_lens import (
    LensFinding,
    LensModelIdentity,
    LensRequest,
    LensResponse,
)

from ._support import CATALOG_ROOT

SHIPPED = CATALOG_ROOT / "evaluation" / "lens-corpus.yaml"
CLASSES = {
    lens_id: lens.weakness_class for lens_id, lens in load_lens_catalog(CATALOG_ROOT).lenses.items()
}
LABELS = """# test name, category, real vulnerability, cwe
T001,sqli,true,89
T002,sqli,false,89
T003,cmdi,true,78
T004,cmdi,false,78
T005,pathtraver,true,22
T006,pathtraver,false,22
T007,hash,true,328
"""


def _raw(**overrides: Any) -> dict[str, Any]:
    raw: dict[str, Any] = yaml.safe_load(SHIPPED.read_text(encoding="utf-8"))
    raw["source"] = {**raw["source"], "test_root": "src/tests", "file_suffix": ".java"}
    raw["sample_per_label"] = 1
    raw.update(overrides)
    return raw


def _corpus(**overrides: Any) -> LensCorpus:
    return lens_corpus_from_mapping(_raw(**overrides), CLASSES)


def _occurrence(path: str, line: int, lens: str, *, lane: Lane = Lane.LLM_LENS) -> Occurrence:
    return Occurrence(
        occurrence_id=f"{path}:{line}:{lens}",
        producer="fdai-lens",
        producer_version="1",
        lane=lane,
        scan_digest="sha256:x",
        revision="0" * 40,
        rule_id=f"lens.{lens}",
        location=SourceLocation(path=path, start_line=line),
        cwe_ids=(89,),
    )


def test_shipped_lens_corpus_loads_with_the_shipped_lenses() -> None:
    corpus = lens_corpus_from_mapping(yaml.safe_load(SHIPPED.read_text()), CLASSES)
    assert corpus.provenance == "curated"
    assert set(corpus.categories.values()) == {CLASSES[lens] for lens in corpus.lenses}


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"provenance": "synthetic"}, "provenance"),
        ({"lenses": ["sql-injection"]}, "lens classes"),
        ({"lenses": ["no-such-lens", "sql-injection"]}, "unknown lenses"),
        ({"sample_per_label": 0}, "sample_per_label"),
        ({"categories": {"Bad Category": "sql_injection"}}, "categories"),
    ],
)
def test_lens_corpus_rejects_malformed_documents(overrides: dict[str, Any], match: str) -> None:
    with pytest.raises(LensCorpusError, match=match):
        _corpus(**overrides)


def test_lens_corpus_rejects_a_short_commit() -> None:
    raw = _raw()
    raw["source"]["commit"] = "abc123"
    with pytest.raises(LensCorpusError, match="commit"):
        lens_corpus_from_mapping(raw, CLASSES)


def test_labels_keep_mapped_categories_and_sample_is_deterministic() -> None:
    corpus = _corpus()
    files = parse_labels(LABELS, corpus)
    assert {f.category for f in files} == {"sqli", "cmdi", "pathtraver"}
    sample = select_sample(files, corpus)
    assert [f.name for f in sample] == ["T003", "T004", "T005", "T006", "T001", "T002"]
    assert sample[0].path == "src/tests/T003.java"
    with pytest.raises(LensCorpusError, match="too few"):
        select_sample(files, _corpus(sample_per_label=2))


@pytest.mark.parametrize(
    "text",
    [
        "T1,sqli\n",
        "T1,sqli,maybe,89\n",
        "../x,sqli,true,89\n",
        "T1,sqli,true,89\nT1,sqli,true,89\n",
    ],
)
def test_labels_reject_malformed_rows(text: str) -> None:
    with pytest.raises(LensCorpusError):
        parse_labels(text, _corpus())


def test_every_kept_hypothesis_is_labeled_and_metrics_follow() -> None:
    corpus = _corpus()
    sample = select_sample(parse_labels(LABELS, corpus), corpus)
    occurrences = [
        _occurrence("src/tests/T001.java", 10, "sql-injection"),
        _occurrence("src/tests/T002.java", 11, "sql-injection"),
        _occurrence("src/tests/T003.java", 12, "sql-injection"),
        _occurrence("src/tests/T003.java", 13, "command-injection"),
        _occurrence("src/other/X.java", 14, "path-traversal"),
        _occurrence("src/tests/T005.java", 15, "path-traversal", lane=Lane.DETERMINISTIC),
    ]
    labels = label_hypotheses(occurrences, sample, CLASSES)
    assert len(labels) == 5
    verdicts = {(item.path, item.lens_id): item.true_positive for item in labels}
    assert verdicts == {
        ("src/tests/T001.java", "sql-injection"): True,
        ("src/tests/T002.java", "sql-injection"): False,
        ("src/tests/T003.java", "sql-injection"): False,
        ("src/tests/T003.java", "command-injection"): True,
        ("src/other/X.java", "path-traversal"): False,
    }
    metrics = {m.weakness_class: m for m in lens_metrics(labels, sample, list(CLASSES.values()))}
    assert metrics["sql_injection"].precision == round(1 / 3, 4)
    assert metrics["sql_injection"].recall == 1.0
    assert metrics["command_injection"].precision == 1.0
    assert metrics["path_traversal"].true_positives == 0
    assert metrics["path_traversal"].recall == 0.0
    assert metrics["missing_authorization"].precision is None


@dataclass
class _Model:
    family: str
    requests: list[LensRequest] = field(default_factory=list)

    @property
    def identity(self) -> LensModelIdentity:
        return LensModelIdentity(self.family, f"{self.family}-deployment")

    async def review(self, request: LensRequest) -> LensResponse:
        self.requests.append(request)
        hit = request.first_line + request.numbered_excerpt.count("\n") // 2
        for raw in request.numbered_excerpt.splitlines():
            number, _, text = raw.partition("|")
            if "executeQuery(" in text:
                hit = int(number.strip())
        return LensResponse(
            findings=(LensFinding(hit, 89, "high", "query built from request text"),),
            model=self.identity,
        )


_JAVA = """public class {name} {{
    void run(javax.servlet.http.HttpServletRequest request, java.sql.Statement st)
            throws Exception {{
        String id = request.getParameter("id");
        st.executeQuery("SELECT * FROM t WHERE id = '" + id + "'");
    }}
}}
"""


def _repository(tmp_path: Path) -> tuple[str, str]:
    repo = tmp_path / "bench"
    tests = repo / "src" / "tests"
    tests.mkdir(parents=True)
    (repo / "labels.csv").write_text(LABELS)
    for name in ("T001", "T002", "T003", "T004", "T005", "T006", "T007"):
        (tests / f"{name}.java").write_text(_JAVA.format(name=name))
    (repo / "src" / "Unlabeled.java").write_text(_JAVA.format(name="Unlabeled"))
    env = {"GIT_CONFIG_NOSYSTEM": "1", "HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}
    for argv in (
        ["init", "-q"],
        ["add", "."],
        ["-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", "init"],
    ):
        subprocess.run(["git", "-C", str(repo), *argv], check=True, env=env)  # noqa: S603, S607
    head = subprocess.run(  # noqa: S603
        ["git", "-C", str(repo), "rev-parse", "HEAD"],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return str(repo), head


def _corpus_file(tmp_path: Path, repository: str, commit: str) -> Path:
    raw = _raw()
    raw["source"] = {
        **raw["source"],
        "repository": repository,
        "commit": commit,
        "labels": "labels.csv",
    }
    path = tmp_path / "lens-corpus.yaml"
    path.write_text(yaml.safe_dump(raw))
    return path


def test_dry_run_counts_candidates_without_models(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repository, commit = _repository(tmp_path)
    corpus = _corpus_file(tmp_path, repository, commit)
    code = main(
        ["evaluate-lens", "--corpus", str(corpus), "--work-root", str(tmp_path / "w"), "--dry-run"]
    )
    receipt = json.loads(capsys.readouterr().out)
    assert code == 0, receipt
    assert receipt["dry_run"] is True
    assert receipt["sample_files"] == 6
    assert receipt["candidates"] >= 2


def test_live_run_labels_every_kept_hypothesis_from_the_staged_sample_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository, commit = _repository(tmp_path)
    corpus = _corpus_file(tmp_path, repository, commit)
    models = [_Model("family-a"), _Model("family-b")]

    @asynccontextmanager
    async def _fake(
        specs: Sequence[str], catalog: object, identity: str
    ) -> AsyncIterator[list[_Model]]:
        assert identity == "azure-cli"
        yield models

    monkeypatch.setattr(code_security_lens_eval, "open_lens_models", _fake)
    out = tmp_path / "receipt.json"
    args = argparse.Namespace(
        corpus=str(corpus),
        work_root=str(tmp_path / "w"),
        lens_model=["family-a=x|y", "family-b=x|z"],
        lens_identity="azure-cli",
        dry_run=False,
        output=str(out),
        catalog_root=str(CATALOG_ROOT),
    )
    receipt = code_security_lens_eval.evaluate_lens(args)
    assert receipt == json.loads(out.read_text())
    assert receipt["ok"] is True
    paths = {request.path for model in models for request in model.requests}
    assert "src/Unlabeled.java" not in paths
    assert {request.lens_id for model in models for request in model.requests} <= {
        "command-injection",
        "path-traversal",
        "sql-injection",
    }
    hypotheses = receipt["hypotheses"]
    assert isinstance(hypotheses, list) and hypotheses
    assert all(item["label"] in {"true_positive", "false_positive"} for item in hypotheses)
    classes = receipt["classes"]
    assert isinstance(classes, list)
    sql = next(item for item in classes if item["weakness_class"] == "sql_injection")
    assert sql["true_positives"] == 1 and sql["false_positives"] >= 1
