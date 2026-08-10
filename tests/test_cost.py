"""Pinned pricing tests. Any change to pricing must update these tests."""

import pytest

from app.services.cost import CostService, PRICING


service = CostService()


def test_pricing_constants_are_pinned():
    assert PRICING == {
        "input_tokens": 3,
        "cached_input_tokens": 1,
        "output_tokens": 15,
        "reasoning_tokens": 15,
    }


def test_cached_input_is_cheaper_than_input():
    normal = service.cost_micros(input_tokens=1_000_000)
    cached = service.cost_micros(cached_input_tokens=1_000_000)

    assert normal == 3_000_000
    assert cached == 1_000_000
    assert cached < normal


def test_million_tokens_are_priced_per_documented_rate():
    assert service.cost_micros(input_tokens=1_000_000) == 3_000_000   # $3.00
    assert service.cost_micros(cached_input_tokens=1_000_000) == 1_000_000  # $1.00
    assert service.cost_micros(output_tokens=1_000_000) == 15_000_000  # $15.00


def test_reasoning_tokens_billed_as_output():
    reasoning = service.cost_micros(reasoning_tokens=1_000_000)
    output = service.cost_micros(output_tokens=1_000_000)

    assert reasoning == output == 15_000_000


def test_token_categories_not_double_counted():
    # input and cached input are separate and each counted exactly once.
    combined = service.cost_micros(input_tokens=100, cached_input_tokens=100)
    separate = service.cost_micros(input_tokens=100) + service.cost_micros(cached_input_tokens=100)

    assert combined == separate == 400


def test_exact_integer_math():
    cost = service.cost_micros(
        input_tokens=1000,
        cached_input_tokens=200,
        output_tokens=500,
        reasoning_tokens=100,
    )

    # 1000*3 + 200*1 + 500*15 + 100*15 = 12200 micro-dollars
    assert cost == 12_200
    assert isinstance(cost, int)
    assert cost == 12200


def test_zero_tokens_cost_zero():
    assert service.cost_micros() == 0


def test_total_tokens_sums_categories():
    total = service.total_tokens(input_tokens=1000, cached_input_tokens=200, output_tokens=500, reasoning_tokens=100)

    assert total == 1800


def test_micros_to_cents_conversion():
    assert service.micros_to_cents(12_200) == 1   # $0.0122 -> 1 cent
    assert service.micros_to_cents(1_000_000) == 100  # $1.00 -> 100 cents
    assert service.micros_to_cents(15_000_000) == 1500  # $15.00


def test_cost_from_event_metadata():
    metadata = {
        "input_tokens": 1000,
        "cached_input_tokens": 200,
        "output_tokens": 500,
        "reasoning_tokens": 100,
        "cost_micros": 12_200,
    }

    assert service.cost_from_event_metadata(metadata) == 12_200


def test_cost_from_empty_metadata_is_zero():
    assert service.cost_from_event_metadata(None) == 0
    assert service.cost_from_event_metadata({}) == 0


@pytest.mark.parametrize(
    "kwargs,expected",
    [
        ({"input_tokens": 1}, 3),
        ({"cached_input_tokens": 1}, 1),
        ({"output_tokens": 1}, 15),
        ({"reasoning_tokens": 1}, 15),
        ({"input_tokens": 1, "reasoning_tokens": 1}, 18),
    ],
)
def test_single_token_costs(kwargs, expected):
    assert service.cost_micros(**kwargs) == expected
