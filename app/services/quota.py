class QuotaExceededError(Exception):
    def __init__(self, usage_type: str, used: int, limit: int):
        self.usage_type = usage_type
        self.used = used
        self.limit = limit

        super().__init__(
            f"{usage_type} quota exceeded: {used}/{limit}"
        )


def check_quota(
    current_usage: int,
    requested_quantity: int,
    limit: int,
    usage_type: str,
) -> None:

    if current_usage + requested_quantity > limit:
        raise QuotaExceededError(
            usage_type=usage_type,
            used=current_usage,
            limit=limit,
        )