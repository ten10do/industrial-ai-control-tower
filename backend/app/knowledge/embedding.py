"""Dependency-free, deterministic local embedding for a small industrial corpus."""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter

DIMENSION = 384
MODEL_VERSION = "local-hash-embedding-v1"
NORMALIZATION = "l2"
TOKEN_RE = re.compile(r"[a-z0-9]+(?:[-_.][a-z0-9]+)*", re.IGNORECASE)


def tokenize(text: str) -> list[str]:
    return [token.lower() for token in TOKEN_RE.findall(text)]


def embed(text: str) -> list[float]:
    """Embed tokens and character trigrams into a stable signed-hash vector."""
    counts = Counter(tokenize(text))
    vector = [0.0] * DIMENSION
    for token, count in counts.items():
        weight = 1.0 + math.log(count)
        features = [f"w:{token}"]
        if len(token) >= 5:
            features.extend(f"c:{token[i : i + 3]}" for i in range(len(token) - 2))
        for feature in features:
            digest = hashlib.sha256(feature.encode()).digest()
            position = int.from_bytes(digest[:4], "big") % DIMENSION
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[position] += sign * weight / len(features)
    norm = math.sqrt(sum(value * value for value in vector))
    return [value / norm for value in vector] if norm else vector


def cosine(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=True))
