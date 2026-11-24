"""Diagnostic shortcut audit.

Trains a small multinomial logistic regression on **surface-form** features of the passage text
only: length, sentence count, punctuation density, digit ratio, uppercase ratio. If those features
alone predict the label well above chance, the generator is leaking the answer through surface
form and should be rebalanced.

Deliberately excluded: recipe metadata (genre, tone, structure), edit counts, and whether a
variant was patched. None of those are visible to a model at inference time, and including them
measures the factory's bookkeeping rather than a learnable shortcut. The train/test split is by
*family*, so siblings of a test family cannot leak its style into training.

This is a diagnostic, not a model-selection tool.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

import numpy as np

from .config import Config
from .schema import LABELS, Family
from .util import split_sentences, stable_seed

LABEL_INDEX = {label: i for i, label in enumerate(LABELS)}

NUMERIC_NAMES = [
    "tokens_p100",
    "log_tokens",
    "sentences",
    "tokens_per_sentence_p10",
    "commas_per_sentence",
    "semicolons_per_sentence",
    "exclamations_per_sentence",
    "questions_per_sentence",
    "digit_ratio",
    "uppercase_ratio",
    "apostrophes_per_sentence",
    "bias",
]

GROUPS = {
    "length_only": [0, 1, 2, 3],
    "punctuation_only": [4, 5, 6, 7, 10],
    "casing_digits_only": [8, 9],
    "all": list(range(len(NUMERIC_NAMES))),
}


def _numeric_features(row: dict[str, Any]) -> list[float]:
    text = row["passage"]
    tokens = max(1, row["token_count"])
    sents = max(1, len(split_sentences(text)))
    letters = max(1, sum(c.isalpha() for c in text))
    return [
        tokens / 100.0,
        math.log1p(tokens),
        sents,
        tokens / sents / 10.0,
        text.count(",") / sents,
        text.count(";") / sents,
        text.count("!") / sents,
        text.count("?") / sents,
        sum(c.isdigit() for c in text) / letters * 10,
        sum(c.isupper() for c in text) / letters * 10,
        text.count("'") / sents,
        1.0,
    ]


def feature_matrix(rows: list[dict[str, Any]]) -> tuple[np.ndarray, np.ndarray, list[str]]:
    feats = [_numeric_features(row) for row in rows]
    X = np.asarray(feats, dtype=np.float64)
    y = np.asarray([LABEL_INDEX[row["label"]] for row in rows], dtype=np.int64)
    return X, y, list(NUMERIC_NAMES)


def _standardise(X: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    mean = X.mean(axis=0)
    std = X.std(axis=0)
    std[std < 1e-9] = 1.0
    return (X - mean) / std, mean, std


def _softmax(z: np.ndarray) -> np.ndarray:
    z = z - z.max(axis=1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=1, keepdims=True)


def train_logreg(
    X: np.ndarray,
    y: np.ndarray,
    epochs: int = 800,
    lr: float = 0.25,
    l2: float = 1e-2,
    seed: int = 7,
):
    rng = np.random.default_rng(seed)
    n, d = X.shape
    k = len(LABELS)
    W = rng.normal(scale=0.01, size=(d, k))
    b = np.zeros(k)
    Y = np.zeros((n, k))
    Y[np.arange(n), y] = 1.0
    for _ in range(epochs):
        p = _softmax(X @ W + b)
        grad = (p - Y) / max(1, n)
        W -= lr * (X.T @ grad + l2 * W)
        b -= lr * grad.sum(axis=0)
    return W, b


def predict(X: np.ndarray, W: np.ndarray, b: np.ndarray) -> np.ndarray:
    return np.argmax(X @ W + b, axis=1)


def _metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, Any]:
    acc = float((y_true == y_pred).mean()) if len(y_true) else 0.0
    per_class = {}
    for label, idx in LABEL_INDEX.items():
        tp = int(((y_pred == idx) & (y_true == idx)).sum())
        fp = int(((y_pred == idx) & (y_true != idx)).sum())
        fn = int(((y_pred != idx) & (y_true == idx)).sum())
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_class[label] = {
            "precision": round(precision, 3), "recall": round(recall, 3), "f1": round(f1, 3)
        }
    macro_f1 = sum(v["f1"] for v in per_class.values()) / len(per_class)
    return {"accuracy": round(acc, 4), "macro_f1": round(macro_f1, 4), "per_class": per_class}


def _bootstrap_ci(y_true: np.ndarray, y_pred: np.ndarray, n_boot: int = 200, seed: int = 11):
    if len(y_true) < 5:
        return None
    rng = np.random.default_rng(seed)
    accs = []
    for _ in range(n_boot):
        idx = rng.integers(0, len(y_true), len(y_true))
        accs.append(float((y_true[idx] == y_pred[idx]).mean()))
    return [round(float(np.percentile(accs, 2.5)), 4), round(float(np.percentile(accs, 97.5)), 4)]


def _group_split(rows: list[dict[str, Any]], fraction: float = 0.7) -> tuple[np.ndarray, np.ndarray]:
    """Split by family so all three variants of a family land on the same side."""
    groups: dict[str, list[int]] = defaultdict(list)
    for i, row in enumerate(rows):
        groups[str(row.get("family_id") or row["variant_id"])].append(i)
    keys = sorted(groups, key=lambda k: stable_seed(k))
    cut = max(1, int(len(keys) * fraction))
    if cut >= len(keys):
        cut = max(1, len(keys) - 1)
    train = [i for k in keys[:cut] for i in groups[k]]
    test = [i for k in keys[cut:] for i in groups[k]]
    return np.asarray(train, dtype=int), np.asarray(test, dtype=int)


def audit_shortcuts(families: list[Family], cfg: Config) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for fam in families:
        rows.extend(fam.flattened_rows())
    if len(rows) < 12 or len({r["family_id"] for r in rows}) < 4:
        return {
            "status": "insufficient_data",
            "variants": len(rows),
            "families": len({r["family_id"] for r in rows}),
            "message": "need at least 12 variants from 4 families for a meaningful shortcut probe",
        }

    X, y, names = feature_matrix(rows)
    Xs, _, _ = _standardise(X)
    train_idx, test_idx = _group_split(rows)

    W, b = train_logreg(Xs[train_idx], y[train_idx])
    y_pred = predict(Xs[test_idx], W, b)
    overall = _metrics(y[test_idx], y_pred)
    overall["ci95_accuracy"] = _bootstrap_ci(y[test_idx], y_pred)

    group_results: dict[str, Any] = {}
    for name, cols in GROUPS.items():
        Xg = Xs[:, cols]
        Wg, bg = train_logreg(Xg[train_idx], y[train_idx])
        group_results[name] = _metrics(y[test_idx], predict(Xg[test_idx], Wg, bg))

    flag = overall["accuracy"] > cfg.quality.shortcut_audit_flag_accuracy
    top = np.argsort(-np.abs(W).sum(axis=1))[:6]
    return {
        "status": "ok",
        "variants": len(rows),
        "families": len({r["family_id"] for r in rows}),
        "train_variants": int(len(train_idx)),
        "test_variants": int(len(test_idx)),
        "chance_accuracy": round(1.0 / len(LABELS), 4),
        "overall": overall,
        "by_feature_group": group_results,
        "flagged": flag,
        "threshold": cfg.quality.shortcut_audit_flag_accuracy,
        "top_features": [
            {"feature": names[int(i)], "weight": round(float(np.abs(W[int(i)]).sum()), 4)}
            for i in top
        ],
        "note": (
            "Surface-form features only (length, punctuation, casing, digits); recipe metadata and "
            "edit counts are excluded because they are unavailable at inference. Split is by family. "
            "High accuracy means labels are recoverable from the text's form and the generator "
            "should be rebalanced."
        ),
    }
