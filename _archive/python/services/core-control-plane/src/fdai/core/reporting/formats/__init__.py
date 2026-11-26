"""Format encoders that serialize a :class:`RenderedReport` for delivery.

Six upstream encoders wired by default:

- :class:`~fdai.core.reporting.formats.json_format.JsonFormatEncoder` -
  the canonical FE contract; UTF-8, compact.
- :class:`~fdai.core.reporting.formats.markdown_format.MarkdownFormatEncoder` -
  notebook-style rendering suitable for a Postmortem PR.
- :class:`~fdai.core.reporting.formats.csv_format.CsvFormatEncoder` -
  spreadsheet export; formula-injection safe.
- :class:`~fdai.core.reporting.formats.html_format.HtmlFormatEncoder` -
  self-contained HTML fragment.
- :class:`~fdai.core.reporting.formats.text_format.TextFormatEncoder` -
  stdout-friendly plain text.
- :class:`~fdai.core.reporting.formats.ndjson_format.NdjsonFormatEncoder` -
  one JSON object per line; ideal for `jq` pipelines.

Opt-in specialized encoder (NOT registered by default):

- :class:`~fdai.core.reporting.formats.prometheus_format.PrometheusFormatEncoder` -
  emit KPI widgets as Prometheus text-exposition metrics.

Register your own by implementing
:class:`~fdai.core.reporting.contracts.FormatEncoder` and calling
:meth:`FormatRegistry.register` at the composition root.
"""

from __future__ import annotations

from fdai.core.reporting.formats.csv_format import CsvFormatEncoder
from fdai.core.reporting.formats.defaults import (
    default_format_encoders,
    install_default_formats,
)
from fdai.core.reporting.formats.html_format import HtmlFormatEncoder
from fdai.core.reporting.formats.json_format import JsonFormatEncoder
from fdai.core.reporting.formats.markdown_format import MarkdownFormatEncoder
from fdai.core.reporting.formats.ndjson_format import NdjsonFormatEncoder
from fdai.core.reporting.formats.prometheus_format import PrometheusFormatEncoder
from fdai.core.reporting.formats.text_format import TextFormatEncoder

__all__ = [
    "CsvFormatEncoder",
    "HtmlFormatEncoder",
    "JsonFormatEncoder",
    "MarkdownFormatEncoder",
    "NdjsonFormatEncoder",
    "PrometheusFormatEncoder",
    "TextFormatEncoder",
    "default_format_encoders",
    "install_default_formats",
]
