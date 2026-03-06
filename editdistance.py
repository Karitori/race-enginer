"""
Compatibility fallback for environments where the `editdistance` wheel is unavailable.

NeMo imports `editdistance.eval` during ASR module initialization. On Python 3.13
Windows, the upstream `editdistance` package may require local C++ build tools.
This module provides a drop-in `eval` implementation to keep local STT runnable.
"""

from collections.abc import Sequence
from typing import Any


def eval(source: Sequence[Any], target: Sequence[Any]) -> int:
    """Compute Levenshtein distance between two token sequences."""
    if source == target:
        return 0
    if len(source) == 0:
        return len(target)
    if len(target) == 0:
        return len(source)

    if len(source) > len(target):
        source, target = target, source

    previous = list(range(len(source) + 1))
    for i, tgt_item in enumerate(target, start=1):
        current = [i]
        for j, src_item in enumerate(source, start=1):
            insertion = current[j - 1] + 1
            deletion = previous[j] + 1
            substitution = previous[j - 1] + (0 if src_item == tgt_item else 1)
            current.append(min(insertion, deletion, substitution))
        previous = current
    return previous[-1]


def distance(source: Sequence[Any], target: Sequence[Any]) -> int:
    """Alias used by some downstream callers."""
    return eval(source, target)
