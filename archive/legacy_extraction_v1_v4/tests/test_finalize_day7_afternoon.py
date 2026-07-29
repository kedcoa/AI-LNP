from src.rag.finalize_day7_afternoon import (
    ALL_OUTCOMES,
    BASELINE_RECOVERED,
    DAY7_NEWLY_RECOVERED,
    RESIDUAL,
)


def test_day7_afternoon_partitions_every_gold_outcome_once():
    recovered = BASELINE_RECOVERED | DAY7_NEWLY_RECOVERED
    assert recovered.isdisjoint(RESIDUAL)
    assert recovered | set(RESIDUAL) == ALL_OUTCOMES
    assert len(recovered) == 10
