from fastapi import FastAPI

from .database import engine, Base
from . import models

app = FastAPI(
    title="Usage Metering & Billing Engine",
    version="1.0.0",
)

Base.metadata.create_all(bind=engine)

@app.get("/")
def root():
    return {
        "service": "Usage Metering & Billing Engine",
        "status": "ok",
    }