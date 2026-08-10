from fastapi import Header, HTTPException

from ..constants import DEFAULT_TENANT_ID, TENANT_HEADER


def get_tenant_id(x_tenant_id: str | None = Header(default=None, alias=TENANT_HEADER)) -> int:
    """Resolve the tenant for the demo API.

    The demo uses ``X-Tenant-ID`` to select a tenant (defaults to the seeded
    tenant id 1). This is a capstone stand-in for real authentication.
    """
    raw = x_tenant_id or str(DEFAULT_TENANT_ID)

    try:
        tenant_id = int(raw)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=422,
            detail="X-Tenant-ID must be an integer",
        )

    if tenant_id <= 0:
        raise HTTPException(
            status_code=422,
            detail="X-Tenant-ID must be a positive integer",
        )

    return tenant_id
