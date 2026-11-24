"""Topic graph, bounded expansion and coverage-aware selection.

The graph is a JSON document (not a rigid tree): a topic may have several parents and
related topics. Selection is inverse-frequency with an exploration term, and every
selection records its score components so sampling can be audited after the fact.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from .config import REPO_ROOT, Config
from .llm import LlmClient
from .util import read_json, atomic_write_json, short_hash, stable_seed, utcnow


class TopicNode(BaseModel):
    topic_id: str
    name: str
    description: str = ""
    parent_topic_ids: list[str] = Field(default_factory=list)
    child_topic_ids: list[str] = Field(default_factory=list)
    related_topic_ids: list[str] = Field(default_factory=list)
    target_coverage: int = 3
    accepted_family_count: float = 0.0
    candidate_count: int = 0
    last_sampled_at: str | None = None
    source_mix: dict[str, float] = Field(default_factory=dict)
    depth: int = 0
    importance: float = 0.5
    status: str = "open"


class TopicGraph(BaseModel):
    nodes: dict[str, TopicNode] = Field(default_factory=dict)
    version: int = 1
    updated_at: str = Field(default_factory=utcnow)

    # ------------------------------------------------------------------ #
    def add(self, node: TopicNode) -> TopicNode:
        self.nodes[node.topic_id] = node
        for pid in node.parent_topic_ids:
            parent = self.nodes.get(pid)
            if parent and node.topic_id not in parent.child_topic_ids:
                parent.child_topic_ids.append(node.topic_id)
        self.updated_at = utcnow()
        return node

    def leaves(self) -> list[TopicNode]:
        return [n for n in self.nodes.values() if not n.child_topic_ids]

    def path_of(self, topic_id: str) -> list[str]:
        node = self.nodes.get(topic_id)
        if not node:
            return []
        names = [node.name]
        seen = {topic_id}
        cur = node
        while cur.parent_topic_ids:
            pid = cur.parent_topic_ids[0]
            if pid in seen:
                break
            seen.add(pid)
            parent = self.nodes.get(pid)
            if not parent:
                break
            names.append(parent.name)
            cur = parent
        return list(reversed(names))

    def children(self, topic_id: str) -> list[TopicNode]:
        node = self.nodes.get(topic_id)
        return [self.nodes[c] for c in node.child_topic_ids if c in self.nodes] if node else []

    def totals(self) -> dict[str, Any]:
        return {
            "nodes": len(self.nodes),
            "leaves": len(self.leaves()),
            "accepted": sum(n.accepted_family_count for n in self.nodes.values()),
            "candidates": sum(n.candidate_count for n in self.nodes.values()),
            "max_depth": max((n.depth for n in self.nodes.values()), default=0),
        }


@dataclass
class SelectedTopic:
    topic_id: str
    name: str
    topic_path: list[str]
    score: float
    components: dict[str, float] = field(default_factory=dict)


def topic_id_for(name: str, parent_ids: list[str]) -> str:
    return "T_" + short_hash(f"{name.lower()}|{','.join(sorted(parent_ids))}", 8)


def _seed_path() -> Path:
    p = REPO_ROOT / "configs" / "seed_topics.yaml"
    if p.exists():
        return p
    return Path(__file__).with_name("seed_topics.yaml")


def load_graph(data_dir: str | Path) -> TopicGraph:
    path = Path(data_dir) / "topics" / "graph.json"
    raw = read_json(path)
    return TopicGraph.model_validate(raw) if raw else TopicGraph()


def save_graph(graph: TopicGraph, data_dir: str | Path) -> Path:
    path = Path(data_dir) / "topics" / "graph.json"
    graph.updated_at = utcnow()
    atomic_write_json(path, graph.model_dump(mode="json"))
    return path


def seed_graph(data_dir: str | Path, force: bool = False) -> TopicGraph:
    """Create the initial two-level graph if it does not exist yet."""
    graph = load_graph(data_dir)
    if graph.nodes and not force:
        return graph
    graph = TopicGraph()
    p = _seed_path()
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    for entry in raw.get("topics", []):
        root_id = topic_id_for(entry["name"], [])
        root = TopicNode(
            topic_id=root_id,
            name=entry["name"],
            description=entry.get("description", ""),
            depth=0,
            importance=float(entry.get("importance", 0.5)),
            target_coverage=int(entry.get("target_coverage", 6)),
        )
        graph.add(root)
        for child in entry.get("children", []):
            cid = topic_id_for(child["name"], [root_id])
            child_node = TopicNode(
                topic_id=cid,
                name=child["name"],
                description=child.get("description", ""),
                parent_topic_ids=[root_id],
                depth=1,
                importance=float(child.get("importance", root.importance)),
                target_coverage=int(child.get("target_coverage", 4)),
            )
            graph.add(child_node)
            for sib in graph.children(root_id):
                if sib.topic_id != cid:
                    child_node.related_topic_ids.append(sib.topic_id)
    for node in graph.nodes.values():
        for rid in node.related_topic_ids:
            other = graph.nodes.get(rid)
            if other and node.topic_id not in other.related_topic_ids:
                other.related_topic_ids.append(node.topic_id)
    save_graph(graph, data_dir)
    return graph


def expand_topic(
    graph: TopicGraph,
    cfg: Config,
    llm: LlmClient,
    topic_id: str,
) -> list[TopicNode]:
    """Expand one node into bounded children using the LLM planner."""
    node = graph.nodes[topic_id]
    if node.depth >= cfg.corpus.topic_max_depth:
        return []
    if node.child_topic_ids:
        return graph.children(topic_id)
    existing = [graph.nodes[c].name for c in node.child_topic_ids]
    result = llm.structured(
        "topics_expand",
        {
            "topic_name": node.name,
            "topic_description": node.description,
            "existing_children": existing or "(none)",
            "max_children": cfg.corpus.max_children_per_topic,
            "depth": node.depth + 1,
            "max_depth": cfg.corpus.topic_max_depth,
        },
        _ExpandSchema,
        cfg.llm.generator,
        stage="topics_expand",
    )
    created: list[TopicNode] = []
    payload = result.data
    for item in payload.subtopics[: cfg.corpus.max_children_per_topic]:
        name = (item.name or "").strip()
        if not name or len(name.split()) > 6:
            continue
        cid = topic_id_for(name, [topic_id])
        if cid in graph.nodes:
            continue
        child = TopicNode(
            topic_id=cid,
            name=name,
            description=(item.description or "").strip()[:200],
            parent_topic_ids=[topic_id],
            depth=node.depth + 1,
            importance=max(0.05, min(1.0, float(item.importance))),
            target_coverage=3,
        )
        graph.add(child)
        created.append(child)
        for sib in created[:-1]:
            sib.related_topic_ids.append(child.topic_id)
            child.related_topic_ids.append(sib.topic_id)
    save_graph(graph, cfg.data_dir)
    return created


class _ExpandItem(BaseModel):
    name: str
    description: str = ""
    importance: float = 0.5


class _ExpandSchema(BaseModel):
    subtopics: list[_ExpandItem] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Selection
# --------------------------------------------------------------------------- #


def select_topics(
    graph: TopicGraph,
    count: int,
    seed: int,
    exploration: float = 0.15,
    exclude: set[str] | None = None,
) -> list[SelectedTopic]:
    """Inverse-frequency sampling with importance, parent diversity and exploration."""
    exclude = exclude or set()
    candidates = [
        n for n in graph.leaves()
        if n.status == "open" and n.topic_id not in exclude
    ]
    if not candidates:
        candidates = [n for n in graph.nodes.values() if n.topic_id not in exclude]
    if not candidates:
        return []

    rng = random.Random(stable_seed("select", seed, graph.updated_at, len(graph.nodes)))
    scored: list[tuple[float, TopicNode, dict[str, float]]] = []
    for node in candidates:
        scarcity = 1.0 / math.sqrt(1.0 + node.accepted_family_count)
        importance = 0.4 + node.importance
        saturation = max(0.1, 1.0 - node.candidate_count / max(1, node.target_coverage * 3))
        score = scarcity * importance * saturation * (0.9 + 0.2 * rng.random())
        scored.append(
            (
                score,
                node,
                {
                    "scarcity": round(scarcity, 4),
                    "importance": round(importance, 4),
                    "saturation": round(saturation, 4),
                },
            )
        )
    scored.sort(key=lambda x: -x[0])

    selected: list[SelectedTopic] = []
    used_parents: set[str] = set()
    pool = list(scored)
    while pool and len(selected) < count:
        if rng.random() < exploration and len(pool) > 1:
            idx = rng.randrange(len(pool))
        else:
            # prefer a new parent branch before repeating one
            idx = next(
                (i for i, (_, n, _) in enumerate(pool)
                 if not (set(n.parent_topic_ids) & used_parents)),
                0,
            )
        score, node, comps = pool.pop(idx)
        used_parents.update(node.parent_topic_ids)
        selected.append(
            SelectedTopic(
                topic_id=node.topic_id,
                name=node.name,
                topic_path=graph.path_of(node.topic_id),
                score=round(score, 4),
                components=comps,
            )
        )
    return selected


def record_candidate(graph: TopicGraph, topic_id: str) -> None:
    node = graph.nodes.get(topic_id)
    if not node:
        return
    node.candidate_count += 1
    node.last_sampled_at = utcnow()


def record_outcome(graph: TopicGraph, topic_id: str, accepted: bool) -> None:
    node = graph.nodes.get(topic_id)
    if not node:
        return
    if accepted:
        cur: TopicNode | None = node
        weight = 1.0
        seen: set[str] = set()
        while cur and cur.topic_id not in seen:
            seen.add(cur.topic_id)
            cur.accepted_family_count += weight
            weight *= 0.5
            cur = graph.nodes.get(cur.parent_topic_ids[0]) if cur.parent_topic_ids else None


def coverage_report(graph: TopicGraph) -> list[dict[str, Any]]:
    rows = []
    for n in sorted(graph.nodes.values(), key=lambda x: x.topic_id):
        rows.append(
            {
                "topic_id": n.topic_id,
                "name": n.name,
                "path": " > ".join(graph.path_of(n.topic_id)),
                "depth": n.depth,
                "accepted": n.accepted_family_count,
                "candidates": n.candidate_count,
                "target": n.target_coverage,
                "score_gap": round(n.target_coverage - n.accepted_family_count, 2),
                "last_sampled_at": n.last_sampled_at,
            }
        )
    return rows
