"""Codegen scaffolds for the ontology + action-type catalogs.

CLIs that materialize the "new business ObjectType" and "new ActionType"
walkthroughs from
[downstream-fork-example-vertical.md](../../../../docs/roadmap/fork-and-sequencing/downstream-fork-example-vertical.md)
so a fork author does not hand-type six correlated YAML files.

Modules
-------
``new_object_type_cli``
    ``python -m fdai.rule_catalog.codegen.new_object_type_cli \\
        --name GovernanceProposal --key id \\
        --property status:string:required=true``

``new_action_type_cli``
    ``python -m fdai.rule_catalog.codegen.new_action_type_cli \\
        --name governance.assign-reviewers --operation configure``

Every generated file is parsed back through the existing loaders
before being written to disk, so a codegen bug fails-closed instead
of producing broken YAML.
"""
