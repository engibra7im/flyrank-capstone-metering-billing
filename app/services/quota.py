class QuotaExceededError(Exception):
    def __init__(self, used: int, requested: int, limit: int):
        self.used = used
        self.requested = requested
        self.limit = limit

        super().__init__(
            f"Quota exceeded: used={used}, "
            f"requested={requested}, limit={limit}"
        )


def check_quota(
    current_usage: int,
    requested_quantity: int,
    limit: int,
    usage_type: str,
):
    if current_usage + requested_quantity > limit:
        raise QuotaExceededError(
            used=current_usage,
            requested=requested_quantity,
            limit=limit,
        )