from typing import TypeVar

T = TypeVar("T")


def first_or_none(items: list[T]) -> T | None:
    return items[0] if items else None
