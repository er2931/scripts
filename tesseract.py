"""
tesseract.py
------------

Core implementation of a finite, function-delimited Tesseract substrate.

- 64 x 64 = 4096 nodes in a 2D grid.
- Optional 4D view: 8 x 8 x 8 x 8 (true tesseract indexing).
- Developmental "stage" controls geometric growth (Manhattan radius).
- Optional functional tags constrain which nodes are allowed to connect.
- Hebbian learning with decay.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, List, Tuple, Dict, Optional

import numpy as np


@dataclass
class Tesseract:
    """
    Tesseract learning substrate.

    n           : grid side length (default 64 → 4096 nodes)
    stage       : developmental radius in Manhattan distance
    tags        : optional functional tags per node (shape: [num_nodes])
                  - if None, no functional restriction
                  - if provided, connections are allowed only when:
                        tag[i] == tag[j]  or  tag[i] == -1 or tag[j] == -1
                    (-1 acts as a wildcard / neutral tag)
    """

    n: int = 64
    stage: int = 0
    tags: Optional[np.ndarray] = None

    # internal fields
    weights: np.ndarray = field(init=False, repr=False)
    num_nodes: int = field(init=False, repr=False)

    _xs: np.ndarray = field(init=False, repr=False)
    _ys: np.ndarray = field(init=False, repr=False)
    _manhattan: np.ndarray = field(init=False, repr=False)

    _allowed_mask: np.ndarray = field(init=False, repr=False)
    _allowed_stage: int = field(init=False, repr=False, default=-1)
    _allowed_tags_version: int = field(init=False, repr=False, default=0)
    _tags_version: int = field(init=False, repr=False, default=0)

    def __post_init__(self) -> None:
        # node count
        self.num_nodes = self.n * self.n

        # weight matrix
        self.weights = np.zeros((self.num_nodes, self.num_nodes), dtype=np.float32)

        # coordinates for each node index (0..num_nodes-1)
        self._xs = np.repeat(np.arange(1, self.n + 1, dtype=np.int16), self.n)
        self._ys = np.tile(np.arange(1, self.n + 1, dtype=np.int16), self.n)

        # Manhattan distances between all pairs
        dx = np.abs(self._xs[:, None] - self._xs[None, :])
        dy = np.abs(self._ys[:, None] - self._ys[None, :])
        self._manhattan = (dx + dy).astype(np.int16)

        # init allowed mask cache
        self._allowed_mask = np.eye(self.num_nodes, dtype=bool)
        self._allowed_stage = 0
        self._allowed_tags_version = -1
        self._tags_version = 0

        # normalize tags if provided
        if self.tags is not None:
            self.set_tags(self.tags)

    # ------------------------------------------------------------------
    # Tag / functional delimitation
    # ------------------------------------------------------------------

    def set_tags(self, tags: Iterable[int]) -> None:
        """
        Set per-node functional tags.

        tags: iterable of length num_nodes.
              Use -1 as a wildcard tag that can connect to anything.
        """
        arr = np.asarray(list(tags), dtype=np.int32)
        if arr.shape[0] != self.num_nodes:
            raise ValueError(f"tags must have length {self.num_nodes}")
        self.tags = arr
        self._tags_version += 1  # force mask recompute

    # ------------------------------------------------------------------
    # 2D indexing
    # ------------------------------------------------------------------

    def idx2(self, x: int, y: int) -> int:
        """
        1-based (x,y) → 0-based linear index.
        """
        if not (1 <= x <= self.n and 1 <= y <= self.n):
            raise ValueError(f"coords out of range: ({x}, {y}) for n={self.n}")
        return (x - 1) * self.n + (y - 1)

    def coords2(self, i: int) -> Tuple[int, int]:
        """
        0-based index → 1-based (x,y).
        """
        if not (0 <= i < self.num_nodes):
            raise ValueError(f"index out of range: {i}")
        x = i // self.n + 1
        y = i % self.n + 1
        return int(x), int(y)

    # ------------------------------------------------------------------
    # 4D indexing (true tesseract view when n == 64)
    # ------------------------------------------------------------------

    def idx4(self, a: int, b: int, c: int, d: int) -> int:
        """
        4D (a,b,c,d) in [0,7]^4 → 0-based index [0,4095].

        Only valid when n == 64.
        """
        if self.n != 64:
            raise ValueError("4D indexing requires n == 64")
        for name, v in zip("abcd", (a, b, c, d)):
            if not (0 <= v <= 7):
                raise ValueError(f"{name} out of range: {v}, expected 0..7")

        t = ((a * 8 + b) * 8 + c) * 8 + d  # 0..4095
        x = t // self.n
        y = t % self.n
        return int(x * self.n + y)

    def coords4(self, i: int) -> Tuple[int, int, int, int]:
        """
        0-based index → 4D (a,b,c,d) in [0,7]^4.
        """
        if self.n != 64:
            raise ValueError("4D indexing requires n == 64")
        if not (0 <= i < self.num_nodes):
            raise ValueError(f"index out of range: {i}")

        t = i
        a = t // (8 * 8 * 8)
        t %= 8 * 8 * 8
        b = t // (8 * 8)
        t %= 8 * 8
        c = t // 8
        d = t % 8
        return int(a), int(b), int(c), int(d)

    # ------------------------------------------------------------------
    # Stage & allowed connections
    # ------------------------------------------------------------------

    def set_stage(self, stage: int) -> None:
        """
        Set developmental stage (Manhattan radius).

        stage = 0 → only self-connections allowed
        stage = 1 → neighbors with distance ≤ 1
        ...
        """
        if stage < 0:
            raise ValueError("stage must be >= 0")
        if stage != self.stage:
            self.stage = stage
            self._allowed_stage = -1  # invalidate cache

    def advance_stage(self, steps: int = 1) -> None:
        """
        Increase developmental stage.
        """
        if steps < 0:
            raise ValueError("steps must be >= 0")
        self.set_stage(self.stage + steps)

    def _update_allowed_mask_if_needed(self) -> None:
        """
        Recompute allowed connections if stage or tags changed.
        """
        if (
            self._allowed_stage == self.stage
            and self._allowed_tags_version == self._tags_version
        ):
            return

        # geometric restriction: Manhattan distance <= stage
        M = self._manhattan <= self.stage
        np.fill_diagonal(M, True)

        # functional restriction: tags
        if self.tags is not None:
            tags = self.tags
            # same tag OR wildcard (-1)
            same = tags[:, None] == tags[None, :]
            wildcard = (tags[:, None] == -1) | (tags[None, :] == -1)
            F = same | wildcard
            M &= F

        self._allowed_mask = M
        self._allowed_stage = self.stage
        self._allowed_tags_version = self._tags_version

    @property
    def allowed_mask(self) -> np.ndarray:
        """
        Boolean matrix of allowed connections at current stage & tags.
        """
        self._update_allowed_mask_if_needed()
        return self._allowed_mask

    # ------------------------------------------------------------------
    # Learning
    # ------------------------------------------------------------------

    def hebbian_step(
        self,
        active_indices: Iterable[int],
        lr: float = 0.01,
        decay: float = 0.0,
    ) -> None:
        """
        One Hebbian update step:

        - active_indices: 0-based node indices that are "on"
        - lr: learning rate
        - decay: global decay factor (0..1);
                 if > 0, all weights *= (1 - decay)
        """
        active = np.unique(np.fromiter(active_indices, dtype=np.int32))
        if active.size == 0:
            return

        if decay != 0.0:
            self.weights *= (1.0 - float(decay))

        self._update_allowed_mask_if_needed()

        ix = np.ix_(active, active)
        allowed_sub = self._allowed_mask[ix]

        self.weights[ix] += lr * allowed_sub.astype(self.weights.dtype)

    def train_sequences(
        self,
        sequences: Iterable[Iterable[int]],
        epochs: int = 1,
        lr: float = 0.01,
        decay: float = 0.0,
        stage_growth_per_epoch: int = 0,
    ) -> None:
        """
        Train on sequences of co-activations.

        sequences: iterable of iterables of indices
        epochs   : passes over the data
        lr       : learning rate
        decay    : decay per step
        stage_growth_per_epoch: if >0, stage increases this much each epoch
        """
        if epochs <= 0:
            return

        for _ in range(epochs):
            for seq in sequences:
                self.hebbian_step(seq, lr=lr, decay=decay)
            if stage_growth_per_epoch > 0:
                self.advance_stage(stage_growth_per_epoch)

    # ------------------------------------------------------------------
    # Analysis & utilities
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Reset all weights to zero (keep geometry, tags, and stage)."""
        self.weights.fill(0.0)

    def stats(self) -> Dict[str, float]:
        """Return basic statistics of the weight matrix."""
        w = self.weights
        return {
            "min": float(w.min()),
            "max": float(w.max()),
            "mean": float(w.mean()),
            "std": float(w.std()),
        }

    def top_connections(
        self,
        k: int = 10,
        min_weight: float = 0.0,
    ) -> List[Tuple[int, int, float]]:
        """
        Return the top-k strongest connections as (i, j, weight).
        """
        if k <= 0:
            return []

        flat = self.weights.ravel()
        idxs = np.arange(flat.size)

        if min_weight > 0.0:
            mask = flat >= min_weight
            if not np.any(mask):
                return []
            flat = flat[mask]
            idxs = idxs[mask]

        if idxs.size == 0:
            return []

        k = min(k, idxs.size)
        top_local = np.argpartition(-flat, k - 1)[:k]
        top_vals = flat[top_local]
        top_idxs = idxs[top_local]

        order = np.argsort(-top_vals)
        top_vals = top_vals[order]
        top_idxs = top_idxs[order]

        total = self.num_nodes
        result: List[Tuple[int, int, float]] = []
        for f, v in zip(top_idxs, top_vals):
            i = int(f // total)
            j = int(f % total)
            result.append((i, j, float(v)))
        return result

    def linear_response(
        self,
        active_indices: Iterable[int],
        normalize: bool = False,
    ) -> Tuple[np.ndarray, int, int]:
        """
        Compute y = W @ x for a binary activation pattern x.

        Returns:
            y      : response vector
            argmax : index of maximum y
            argmin : index of minimum y
        """
        active = np.unique(np.fromiter(active_indices, dtype=np.int32))
        x = np.zeros(self.num_nodes, dtype=np.float32)
        x[active] = 1.0

        if normalize:
            norm = np.linalg.norm(x)
            if norm > 0:
                x /= norm

        y = self.weights @ x
        return y, int(np.argmax(y)), int(np.argmin(y))

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, path: str) -> None:
        """Save weights, stage, tags to an .npz file."""
        np.savez_compressed(
            path,
            n=self.n,
            stage=self.stage,
            weights=self.weights,
            tags=self.tags if self.tags is not None else np.array([], dtype=np.int32),
        )

    @classmethod
    def load(cls, path: str) -> "Tesseract":
        """Load a Tesseract from an .npz file."""
        data = np.load(path, allow_pickle=False)
        n = int(data["n"])
        stage = int(data["stage"])
        tags_arr = data["tags"]
        tags = None if tags_arr.size == 0 else tags_arr.astype(np.int32)

        t = cls(n=n, stage=stage, tags=tags)
        t.weights[:] = data["weights"].astype(np.float32)
        return t


# ----------------------------------------------------------------------
# Demo usage
# ----------------------------------------------------------------------

if __name__ == "__main__":
    T = Tesseract()

    # example: set all tags to -1 (wildcard)
    T.set_tags([-1] * T.num_nodes)

    # start with local-only connections
    T.set_stage(0)

    # simple training sequence
    seqs = [
        [T.idx2(10, 10), T.idx2(10, 11), T.idx2(11, 10)],
        [T.idx2(20, 20), T.idx2(21, 20)],
    ]

    T.train_sequences(seqs, epochs=5, lr=0.05, decay=0.01, stage_growth_per_epoch=1)

    print("Stats:", T.stats())
    print("Top connections:", T.top_connections(5))
