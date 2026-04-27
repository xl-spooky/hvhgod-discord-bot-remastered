from collections import abc
from typing import TypeAlias, TypeVar, overload

KT = TypeVar("KT")
Processor: TypeAlias = abc.Callable[[str], str]
Scorer: TypeAlias = abc.Callable[[str, str], int]

@overload
def extract(
    query: str,
    choices: abc.Mapping[KT, str],
    processor: Processor = ...,
    scorer: Scorer = ...,
    limit: int = 5,
) -> list[tuple[str, int, KT]]: ...
@overload
def extract(
    query: str,
    choices: abc.Iterable[str],
    processor: Processor = ...,
    scorer: Scorer = ...,
    limit: int = 5,
) -> list[tuple[str, int]]: ...
