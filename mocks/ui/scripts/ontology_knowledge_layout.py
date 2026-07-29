"""Deterministic topology-community layout for the ontology knowledge graph."""

from __future__ import annotations

import math
from typing import Any

EDGE_WEIGHTS = {
    "instance_of": 0.12,
    "link_type": 1.1,
    "rule_dispatch": 1.0,
    "workflow": 1.4,
    "agent": 1.3,
}


def detect_communities(
    nodes: list[dict[str, Any]], edges: list[dict[str, Any]]
) -> list[int]:
    """Return stable weighted-modularity communities for the undirected graph."""

    index = {item["id"]: position for position, item in enumerate(nodes)}
    neighbors: list[dict[int, float]] = [{} for _ in nodes]
    weighted_degree = [0.0] * len(nodes)
    for item in edges:
        source = index[item["source"]]
        target = index[item["target"]]
        weight = EDGE_WEIGHTS[item["kind"]]
        neighbors[source][target] = neighbors[source].get(target, 0.0) + weight
        neighbors[target][source] = neighbors[target].get(source, 0.0) + weight
        weighted_degree[source] += weight
        weighted_degree[target] += weight

    labels = list(range(len(nodes)))
    community_weight = weighted_degree.copy()
    total_weight = max(sum(weighted_degree), 1.0)
    visit_order = sorted(range(len(nodes)), key=lambda item: nodes[item]["id"])
    for _ in range(40):
        moved = False
        for node_index in visit_order:
            current = labels[node_index]
            node_weight = weighted_degree[node_index]
            links: dict[int, float] = {}
            for neighbor, weight in neighbors[node_index].items():
                label = labels[neighbor]
                links[label] = links.get(label, 0.0) + weight
            community_weight[current] -= node_weight
            best = current
            best_gain = links.get(current, 0.0) - (
                community_weight[current] * node_weight / total_weight
            )
            for candidate in sorted(links):
                gain = links[candidate] - community_weight[candidate] * node_weight / total_weight
                if gain > best_gain + 1e-9:
                    best = candidate
                    best_gain = gain
            labels[node_index] = best
            community_weight[best] += node_weight
            moved = moved or best != current
        if not moved:
            break

    groups: dict[int, list[int]] = {}
    for node_index, label in enumerate(labels):
        groups.setdefault(label, []).append(node_index)
    while len(groups) > 12 or min(len(members) for members in groups.values()) < 4:
        source = min(groups, key=lambda label: (len(groups[label]), label))
        connected_weight: dict[int, float] = {}
        for node_index in groups[source]:
            for neighbor, weight in neighbors[node_index].items():
                target = labels[neighbor]
                if target != source:
                    connected_weight[target] = connected_weight.get(target, 0.0) + weight
        if connected_weight:
            target = max(
                connected_weight,
                key=lambda label: (connected_weight[label], len(groups[label]), -label),
            )
        else:
            target = max(
                (label for label in groups if label != source),
                key=lambda label: (len(groups[label]), -label),
            )
        for node_index in groups.pop(source):
            labels[node_index] = target
            groups[target].append(node_index)
    ordered = sorted(
        groups.values(),
        key=lambda members: (-len(members), min(nodes[item]["id"] for item in members)),
    )
    remapped = [0] * len(nodes)
    for community, members in enumerate(ordered, start=1):
        for node_index in members:
            remapped[node_index] = community
    return remapped


def apply_centrality_layout(graph: dict[str, Any]) -> None:
    """Place hubs centrally and pull densely connected communities together."""

    nodes: list[dict[str, Any]] = graph["nodes"]
    edges: list[dict[str, Any]] = graph["edges"]
    index = {item["id"]: position for position, item in enumerate(nodes)}
    degree = [0] * len(nodes)
    indexed_edges: list[tuple[int, int]] = []
    for item in edges:
        source = index[item["source"]]
        target = index[item["target"]]
        degree[source] += 1
        degree[target] += 1
        indexed_edges.append((source, target))

    communities = detect_communities(nodes, edges)
    community_members: dict[int, list[int]] = {}
    for node_index, community in enumerate(communities):
        community_members.setdefault(community, []).append(node_index)
    community_count = len(community_members)
    community_anchors = {
        community: (
            230.0 * math.cos(-math.pi / 2 + 2 * math.pi * (community - 1) / community_count),
            170.0 * math.sin(-math.pi / 2 + 2 * math.pi * (community - 1) / community_count),
        )
        for community in community_members
    }
    local_rank: dict[int, int] = {}
    for members in community_members.values():
        for position, node_index in enumerate(
            sorted(members, key=lambda item: (-degree[item], nodes[item]["id"]))
        ):
            local_rank[node_index] = position

    order = sorted(range(len(nodes)), key=lambda item: (-degree[item], nodes[item]["id"]))
    rank = {node_index: position for position, node_index in enumerate(order)}
    golden_angle = math.pi * (3.0 - math.sqrt(5.0))
    max_degree = max(degree)
    x = [0.0] * len(nodes)
    y = [0.0] * len(nodes)
    target_x = [0.0] * len(nodes)
    target_y = [0.0] * len(nodes)
    for node_index in range(len(nodes)):
        node_rank = rank[node_index]
        radius = 8.0 * math.sqrt(local_rank[node_index])
        angle = node_rank * golden_angle
        centrality = degree[node_index] / max_degree
        community_pull = (1.0 - centrality) ** 0.72
        anchor_x, anchor_y = community_anchors[communities[node_index]]
        target_x[node_index] = anchor_x * community_pull + radius * math.cos(angle)
        target_y[node_index] = anchor_y * community_pull + radius * math.sin(angle) * 0.72
        x[node_index] = target_x[node_index]
        y[node_index] = target_y[node_index]

    velocity_x = [0.0] * len(nodes)
    velocity_y = [0.0] * len(nodes)
    for iteration in range(220):
        force_x = [0.0] * len(nodes)
        force_y = [0.0] * len(nodes)
        for left in range(len(nodes)):
            for right in range(left + 1, len(nodes)):
                delta_x = x[left] - x[right]
                delta_y = y[left] - y[right]
                distance_sq = max(36.0, delta_x * delta_x + delta_y * delta_y)
                distance = math.sqrt(distance_sq)
                magnitude = 520.0 / distance_sq
                push_x = delta_x / distance * magnitude
                push_y = delta_y / distance * magnitude
                force_x[left] += push_x
                force_y[left] += push_y
                force_x[right] -= push_x
                force_y[right] -= push_y
        for source, target in indexed_edges:
            delta_x = x[target] - x[source]
            delta_y = y[target] - y[source]
            distance = max(1.0, math.hypot(delta_x, delta_y))
            desired = 42.0 + 7.0 * math.log1p(max(degree[source], degree[target]))
            magnitude = (distance - desired) * 0.006
            pull_x = delta_x / distance * magnitude
            pull_y = delta_y / distance * magnitude
            force_x[source] += pull_x
            force_y[source] += pull_y
            force_x[target] -= pull_x
            force_y[target] -= pull_y
        temperature = 0.28 * (1.0 - iteration / 260.0)
        for node_index in range(len(nodes)):
            anchor = 0.015 + min(degree[node_index], 70) * 0.00015
            force_x[node_index] += (target_x[node_index] - x[node_index]) * anchor
            force_y[node_index] += (target_y[node_index] - y[node_index]) * anchor
            velocity_x[node_index] = (velocity_x[node_index] + force_x[node_index]) * 0.78
            velocity_y[node_index] = (velocity_y[node_index] + force_y[node_index]) * 0.78
            x[node_index] += max(-8.0, min(8.0, velocity_x[node_index])) * temperature
            y[node_index] += max(-8.0, min(8.0, velocity_y[node_index])) * temperature

    min_x, max_x = min(x), max(x)
    min_y, max_y = min(y), max(y)
    scale = min(1900.0 / max(1.0, max_x - min_x), 1120.0 / max(1.0, max_y - min_y))
    for node_index, item in enumerate(nodes):
        item["community"] = communities[node_index]
        item["degree"] = degree[node_index]
        item["x"] = round((x[node_index] - min_x) * scale + 110.0, 2)
        item["y"] = round((y[node_index] - min_y) * scale + 90.0, 2)
