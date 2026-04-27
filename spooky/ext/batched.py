"""Batch-processing utilities for iterating in fixed-size chunks.

This module provides :func:`batched`, a lightweight utility for splitting
any iterable into successive lists of a specified size. It is commonly used
when processing large collections in chunks (e.g., bulk database operations,
paged API calls, or rate-limited Discord actions).

Examples
--------
>>> list(batched([1, 2, 3, 4, 5], size=2))
[[1, 2], [3, 4], [5]]

>>> for chunk in batched(range(10), 3):
...     print(chunk)
[0, 1, 2]
[3, 4, 5]
[6, 7, 8]
[9]

Notes
-----
- The function yields batches lazily, making it suitable for streaming input.
- The final batch may contain fewer than ``size`` elements if the iterable is
  not evenly divisible.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import TypeVar

T = TypeVar("T")


def batched(iterable: Iterable[T], size: int) -> Iterator[list[T]]:
    """Yield lists of up to ``size`` items from ``iterable``.

    Parameters
    ----------
    iterable : Iterable[T]
        Source iterable to be split into fixed-size batches.
    size : int
        Maximum number of elements per batch. Must be greater than zero.

    Returns
    -------
    Iterator[list[T]]
        An iterator that yields lists of up to ``size`` items.

    Raises
    ------
    ValueError
        If ``size`` is not greater than zero.
    """
    if size <= 0:
        raise ValueError("batch size must be > 0")

    batch: list[T] = []
    for item in iterable:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch
