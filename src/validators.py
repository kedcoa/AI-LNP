from collections.abc import Iterable


def validate_complete_percentage_composition(
    percentages: Iterable[float | None],
    *,
    composition_basis: str | None,
    composition_is_complete: bool,
    minimum_total: float = 98.0,
    maximum_total: float = 102.0,
) -> bool:
    values = list(percentages)

    if composition_basis not in {"mol%", "weight%"}:
        return True

    if not composition_is_complete:
        return True

    if not values or any(value is None for value in values):
        return False

    total = sum(value for value in values if value is not None)
    return minimum_total <= total <= maximum_total