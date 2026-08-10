from sqlalchemy import select

from .database import Base, SessionLocal, engine
from .models import Plan, Subscription, Tenant


def seed():
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()

    try:
        # -------------------------
        # Plans
        # -------------------------

        free_plan = db.scalar(
            select(Plan).where(Plan.name == "Free")
        )

        if free_plan is None:
            free_plan = Plan(
                name="Free",
                api_call_limit=1000,
                ai_token_limit=100_000,
            )

            db.add(free_plan)

        pro_plan = db.scalar(
            select(Plan).where(Plan.name == "Pro")
        )

        if pro_plan is None:
            pro_plan = Plan(
                name="Pro",
                api_call_limit=10_000,
                ai_token_limit=1_000_000,
            )

            db.add(pro_plan)

        db.commit()

        # -------------------------
        # Demo Tenant
        # -------------------------

        tenant = db.scalar(
            select(Tenant).where(
                Tenant.name == "Demo Tenant"
            )
        )

        if tenant is None:
            tenant = Tenant(
                name="Demo Tenant"
            )

            db.add(tenant)
            db.commit()
            db.refresh(tenant)

        # -------------------------
        # Subscription
        # -------------------------

        subscription = db.scalar(
            select(Subscription).where(
                Subscription.tenant_id == tenant.id
            )
        )

        if subscription is None:
            subscription = Subscription(
                tenant_id=tenant.id,
                plan_id=free_plan.id,
                status="active",
            )

            db.add(subscription)
            db.commit()

        print("Seed completed successfully.")
        print(f"Tenant ID: {tenant.id}")
        print(f"Plan: Free")
        print(f"API call limit: {free_plan.api_call_limit}")
        print(f"AI token limit: {free_plan.ai_token_limit}")

    finally:
        db.close()


if __name__ == "__main__":
    seed()