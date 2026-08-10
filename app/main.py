from fastapi import FastAPI

app = FastAPI(
    title="Usage Metering & Billing Engine",
    version="1.0.0",
)

@app.get("/")
def root():
    return {
        "service": "Usage Metering & Billing Engine",
        "status": "ok",
    }