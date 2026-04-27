"""Local stub implementation for ``thefuzz.process``.

This lightweight shim mirrors the minimal interface used in the codebase so
Pyright can resolve imports without the third-party package installed.
"""

from __future__ import annotations

from collections import abc
from typing import TypeAlias, TypeVar

KT = TypeVar("KT")
Processor: TypeAlias = abc.Callable[[str], str]
Scorer: TypeAlias = abc.Callable[[str, str], int]


def extract(
    query: str,
    choices: abc.Mapping[KT, str] | abc.Iterable[str],
    processor: Processor | None = None,
    scorer: Scorer | None = None,
    limit: int = 5,
) -> list[tuple[str, int] | tuple[str, int, KT]]:
    """Shim implementation mirroring ``thefuzz.process.extract`` signature."""
    raise NotImplementedError
