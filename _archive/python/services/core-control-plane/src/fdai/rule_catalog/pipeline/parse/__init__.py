"""Rule-catalog parser plugins.

The collector produces a byte-verbatim snapshot (see
:mod:`fdai.rule_catalog.pipeline.collect`); a *parser* converts
that snapshot into the raw rule mappings the loader
(``rule_catalog/schema/rule.py``) understands. Parser and loader are
kept as two separate stages so the loader can stay format-agnostic and
the collector never needs to know about ActionType / ResourceType
cross-refs.

Ships in this module:

- :class:`Parser` - the Protocol every parser satisfies.
- :class:`ParsedRule` - one rule mapping produced by a parser.
- :class:`ParseReport` - the aggregate a parser returns.
- :class:`ParseError` - raised on structural parse failures (unreadable
  YAML, wrong top-level type). Cross-reference / schema issues are the
  loader's job, so parsers never claim authority they do not own.
- :class:`RuleYamlParser` - the first concrete parser; consumes a
  snapshot whose ``tree/`` is already normalized rule YAML (the seed
  source ``fdai-p1-seed`` is exactly this shape).
- :class:`RegoParser` - the second concrete parser; walks a snapshot
  tree of ``*.rego`` modules (e.g. the gatekeeper-library OSS source)
  and emits partial mappings the normalizer stage completes.
- :func:`build_parser` - dispatcher keyed on the manifest ``parser``
  field.

Other parsers (``azure-policy-json``, ``checkov-yaml``, ``kube-bench``,
``gatekeeper-templates``) are declared on the enum but raise a typed
:class:`ParserNotImplementedError` for now so a manifest that
references them fails at collect time with a clear message rather than
silently no-op.
"""

from __future__ import annotations

from fdai.rule_catalog.pipeline.parse.parser import (
    ParsedRule,
    ParseError,
    Parser,
    ParseReport,
    ParserName,
    ParserNotImplementedError,
    build_parser,
)
from fdai.rule_catalog.pipeline.parse.rego_parser import RegoParser
from fdai.rule_catalog.pipeline.parse.rule_yaml import RuleYamlParser
from fdai.rule_catalog.pipeline.parse.verify import (
    RuleVerificationIssue,
    RuleVerificationReport,
    verify_parsed_rules,
)

__all__ = [
    "ParsedRule",
    "ParseError",
    "ParseReport",
    "Parser",
    "ParserName",
    "ParserNotImplementedError",
    "RegoParser",
    "RuleVerificationIssue",
    "RuleVerificationReport",
    "RuleYamlParser",
    "build_parser",
    "verify_parsed_rules",
]
