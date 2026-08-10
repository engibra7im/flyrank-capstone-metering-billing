"""Cost calculation for AI token usage.

Money is always an integer number of micro-dollars (1 micro-dollar = 1e-6 USD).
Floating point is never used for money.

The total is computed as:

    cost_micros = input * P_INPUT
                + cached_input * P_CACHED_INPUT
                + output * P_OUTPUT
                + reasoning * P_REASONING

Rules:
    - cached input tokens are cheaper than normal input tokens;
    - reasoning tokens are billed at the output rate (they count as output);
    - each category contributes exactly once (no double counting);
    - all prices are integer micro-dollars per token, so every per-category
      product and the sum are exact integers.
"""

# Price per token, in micro-dollars (1e-6 USD).
# Equivalently: micro-dollars per token == USD per million tokens.
MICROS_PER_DOLLAR = 1_000_000
MICROS_PER_CENT = 10_000

PRICING = {
    "input_tokens": 3,           # $3.00  / 1M tokens
    "cached_input_tokens": 1,    # $1.00  / 1M tokens (cheaper than input)
    "output_tokens": 15,         # $15.00 / 1M tokens
    "reasoning_tokens": 15,      # $15.00 / 1M tokens (billed as output)
}

# Token categories that are added together to form the "quantity" a tenant is
# charged against for quota purposes.
TOKEN_CATEGORIES = ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_tokens")


class CostService:
    def total_tokens(
        self,
        input_tokens: int = 0,
        cached_input_tokens: int = 0,
        output_tokens: int = 0,
        reasoning_tokens: int = 0,
    ) -> int:
        """Sum of every token category consumed by a request."""
        return (
            input_tokens
            + cached_input_tokens
            + output_tokens
            + reasoning_tokens
        )

    def cost_micros(
        self,
        input_tokens: int = 0,
        cached_input_tokens: int = 0,
        output_tokens: int = 0,
        reasoning_tokens: int = 0,
    ) -> int:
        """Total cost in integer micro-dollars (1e-6 USD)."""
        return (
            input_tokens * PRICING["input_tokens"]
            + cached_input_tokens * PRICING["cached_input_tokens"]
            + output_tokens * PRICING["output_tokens"]
            + reasoning_tokens * PRICING["reasoning_tokens"]
        )

    @staticmethod
    def micros_to_cents(micros: int) -> int:
        """Display helper: convert exact micro-dollars to integer cents."""
        return micros // MICROS_PER_CENT

    def cost_from_event_metadata(self, metadata: dict | None) -> int:
        """Recompute the exact cost from an event's stored token breakdown."""
        if not metadata:
            return 0

        return self.cost_micros(
            input_tokens=metadata.get("input_tokens", 0) or 0,
            cached_input_tokens=metadata.get("cached_input_tokens", 0) or 0,
            output_tokens=metadata.get("output_tokens", 0) or 0,
            reasoning_tokens=metadata.get("reasoning_tokens", 0) or 0,
        )
