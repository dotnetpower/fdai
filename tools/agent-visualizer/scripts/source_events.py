"""Extract declared pub/sub topology and ARG rate metadata from syntax, not live services."""

import ast

from source_index import BodyVisitor, SourceIndex


def assignment(tree: ast.Module, name: str) -> ast.expr:
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in node.targets
        ):
            return node.value
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == name
            and node.value
        ):
            return node.value
    raise ValueError(f"Required source declaration is missing: {name}")


def event_metadata(index: SourceIndex, records: list[dict], owners: dict) -> list[dict]:
    declared = assignment(index.modules["fdai.agents._framework.topics"], "OWNED_OBJECT_TOPICS")
    if not isinstance(declared, ast.Call):
        raise ValueError("Owned topic declaration must remain an explicit frozenset.")
    topics = sorted(ast.literal_eval(declared.args[0]))
    result = []
    for record in records:
        publishes = []
        for object_type in record["owns"]:
            matches = [
                topic
                for topic in topics
                if topic.removeprefix("object.").replace("-", "") == object_type.lower()
            ]
            if len(matches) != 1:
                raise ValueError(f"Ambiguous declared topic for ObjectType: {object_type}")
            publishes.append(matches[0])
        record["publishes"] = publishes
    for topic in topics:
        publishers = [record["id"] for record in records if topic in record["publishes"]]
        if len(publishers) != 1:
            raise ValueError(f"Topic must have exactly one declared owner: {topic}")
        publisher = publishers[0]
        publish_functions = []
        for identifier in owners:
            if publisher not in owners[identifier]:
                continue
            definition = index.functions[identifier]
            visitor = BodyVisitor()
            for node in definition.node.body:
                visitor.visit(node)
            for call in visitor.calls:
                if not isinstance(call.func, ast.Attribute) or call.func.attr != "publish":
                    continue
                topic_values = [
                    *call.args[:1],
                    *(kw.value for kw in call.keywords if kw.arg == "topic"),
                ]
                if any(
                    isinstance(value, ast.Constant) and value.value == topic
                    for value in topic_values
                ):
                    publish_functions.append(identifier)
        result.append(
            {
                "id": topic,
                "publisher": publisher,
                "subscribers": [
                    record["id"] for record in records if topic in record["subscribes"]
                ],
                "publisher_functions": sorted(set(publish_functions)),
                "basis": "AgentSpec.owns + OWNED_OBJECT_TOPICS + AgentSpec.subscribes",
            }
        )
    return result


def arg_metadata(index: SourceIndex) -> dict:
    module = "fdai.delivery.azure.arg_transport"
    tree = index.modules[module]
    rate = assignment(tree, "DEFAULT_ARG_REQUESTS_PER_SECOND")
    burst = assignment(tree, "DEFAULT_ARG_REQUEST_BURST")
    return {
        "requests_per_second": ast.literal_eval(rate),
        "burst": ast.literal_eval(burst),
        "file": index.paths[module],
        "line": rate.lineno,
        "semantics": (
            "Shared sustained request budget with a burst allowance, not a polling scheduler."
        ),
    }
