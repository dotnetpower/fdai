# `src/fdai/rule_catalog`

Rule-catalog pipeline: schema validation, source collectors, and the continuous
collect → shadow-eval → regression → promote/rollback pipeline. The catalog data
itself lives in top-level [rule-catalog/](../../../rule-catalog/) as YAML.
