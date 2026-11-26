from __future__ import annotations

import importlib
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "service-migrations"))
classification = importlib.import_module("service_migrations.classification")

_HEADER = 'revision = "{revision}"\ndown_revision = None\n'


def _revision(tmp_path: Path, revision: str, upgrade: str, extra: str = "") -> Path:
    body = _HEADER.format(revision=revision) + extra + "\n" + textwrap.dedent(upgrade)
    path = tmp_path / f"{revision}.py"
    path.write_text(body, encoding="utf-8")
    return path


_ADD_TABLE = """
def upgrade():
    op.create_table("t", sa.Column("id", sa.Integer))
    op.add_column("u", sa.Column("x", sa.Text, nullable=True))
    op.execute("CREATE INDEX IF NOT EXISTS i ON t (id)")

def downgrade():
    op.drop_table("t")
    op.execute("DROP TABLE t")
"""


def test_additive_revision_is_expand_even_when_downgrade_drops(tmp_path: Path) -> None:
    analysis = classification.analyze_revision(_revision(tmp_path, "r1", _ADD_TABLE))

    assert analysis.destructive == ()
    assert analysis.computed_class == classification.EXPAND


@pytest.mark.parametrize(
    ("body", "finding"),
    [
        ('op.drop_table("t")', "drop_table"),
        ('op.drop_column("t", "c")', "drop_column"),
        ('op.rename_table("t", "u")', "rename_table"),
        ('op.alter_column("t", "c", new_column_name="d")', "alter_column_rename_or_type"),
        ('op.alter_column("t", "c", type_=sa.Text())', "alter_column_rename_or_type"),
        ('op.execute("DROP TABLE t")', "sql_destructive"),
        ('op.execute("alter table t rename to u")', "sql_destructive"),
        ('op.execute("ALTER TABLE t ALTER COLUMN c TYPE bigint")', "sql_destructive"),
        ('op.execute("TRUNCATE t")', "sql_destructive"),
    ],
)
def test_destructive_operations_make_a_contract_revision(
    tmp_path: Path, body: str, finding: str
) -> None:
    path = _revision(tmp_path, "r2", f"def upgrade():\n    {body}\n\ndef downgrade():\n    pass\n")

    analysis = classification.analyze_revision(path)

    assert analysis.destructive == (finding,)
    assert analysis.computed_class == classification.CONTRACT


def test_helper_functions_and_module_constants_reachable_from_upgrade_are_analyzed(
    tmp_path: Path,
) -> None:
    path = _revision(
        tmp_path,
        "r3",
        """
        def _retire():
            op.execute(_SQL)

        def upgrade():
            _retire()

        def downgrade():
            op.execute(_UNDO)
        """,
        extra='_SQL = "DROP SCHEMA legacy"\n_UNDO = "CREATE SCHEMA legacy"\n',
    )

    assert classification.analyze_revision(path).destructive == ("sql_destructive",)


def test_trigger_that_guards_truncate_is_not_a_truncate(tmp_path: Path) -> None:
    path = _revision(
        tmp_path,
        "r4",
        """
        def upgrade():
            op.execute(
                "CREATE TRIGGER g BEFORE INSERT OR DELETE OR TRUNCATE ON t "
                "FOR EACH STATEMENT EXECUTE FUNCTION f()"
            )

        def downgrade():
            pass
        """,
    )

    assert classification.analyze_revision(path).computed_class == classification.EXPAND


def test_revision_without_upgrade_or_id_is_rejected(tmp_path: Path) -> None:
    no_upgrade = tmp_path / "a.py"
    no_upgrade.write_text('revision = "a"\n', encoding="utf-8")
    no_id = tmp_path / "b.py"
    no_id.write_text("def upgrade():\n    pass\n", encoding="utf-8")

    for path in (no_upgrade, no_id):
        with pytest.raises(classification.MigrationClassificationError) as caught:
            classification.analyze_revision(path)
        assert caught.value.reason_code == "migration_classification_invalid"


def test_release_classification_is_validated() -> None:
    good = {"schema": classification.CLASSIFICATION_SCHEMA, "revisions": {"r1": "expand"}}

    assert classification.load_release_classification(good) == {"r1": "expand"}
    for bad in (
        None,
        {"schema": "other", "revisions": {}},
        {"schema": classification.CLASSIFICATION_SCHEMA},
        {"schema": classification.CLASSIFICATION_SCHEMA, "revisions": {"r1": "maybe"}},
        {"schema": classification.CLASSIFICATION_SCHEMA, "revisions": {"bad id": "expand"}},
        {**good, "extra": 1},
    ):
        with pytest.raises(classification.MigrationClassificationError) as caught:
            classification.load_release_classification(bad)
        assert caught.value.reason_code == "migration_classification_invalid"


def test_plan_runs_only_pending_declared_expand_revisions(tmp_path: Path) -> None:
    old = _revision(tmp_path, "old", "def upgrade():\n    op.drop_table('x')\n")
    new = _revision(tmp_path, "new", _ADD_TABLE)
    image = {"old": old, "new": new}

    pending = classification.pending_revisions(image, applied=["old"])

    assert list(pending) == ["new"]
    assert classification.plan_expand(pending, {"new": "expand"}) == ("new",)
    assert classification.plan_expand({}, {}) == ()


@pytest.mark.parametrize(
    ("declared", "reason"),
    [
        ({}, "migration_unclassified"),
        ({"new": "contract"}, "migration_contract_revision"),
    ],
)
def test_plan_rejects_unclassified_and_contract_revisions(
    tmp_path: Path, declared: dict[str, str], reason: str
) -> None:
    new = _revision(tmp_path, "new", _ADD_TABLE)

    with pytest.raises(classification.MigrationClassificationError) as caught:
        classification.plan_expand({"new": new}, declared)

    assert caught.value.reason_code == reason


def test_plan_rejects_a_dropping_revision_declared_as_expand(tmp_path: Path) -> None:
    dropping = _revision(tmp_path, "drops", "def upgrade():\n    op.drop_column('t', 'c')\n")

    with pytest.raises(classification.MigrationClassificationError) as caught:
        classification.plan_expand({"drops": dropping}, {"drops": "expand"})

    assert caught.value.reason_code == "migration_expand_destructive"


def test_one_rejected_revision_rejects_the_whole_upgrade(tmp_path: Path) -> None:
    fine = _revision(tmp_path, "a_fine", _ADD_TABLE)
    renames = _revision(tmp_path, "b_renames", "def upgrade():\n    op.rename_table('t', 'u')\n")

    with pytest.raises(classification.MigrationClassificationError):
        classification.plan_expand(
            {"a_fine": fine, "b_renames": renames}, {"a_fine": "expand", "b_renames": "expand"}
        )


def test_declared_id_must_match_the_revision_file(tmp_path: Path) -> None:
    path = _revision(tmp_path, "actual", _ADD_TABLE)

    with pytest.raises(classification.MigrationClassificationError) as caught:
        classification.plan_expand({"claimed": path}, {"claimed": "expand"})

    assert caught.value.reason_code == "migration_classification_invalid"


def test_error_reason_never_carries_the_revision_body(tmp_path: Path) -> None:
    path = _revision(tmp_path, "secret", 'def upgrade():\n    op.execute("DROP TABLE hunter2")\n')

    with pytest.raises(classification.MigrationClassificationError) as caught:
        classification.plan_expand({"secret": path}, {"secret": "expand"})

    assert "hunter2" not in str(caught.value) and str(tmp_path) not in str(caught.value)
