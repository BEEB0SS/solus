import os
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '..', '.env'))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .database import init_db
from .routes import router

# Without a WS protocol library uvicorn serves upgrade requests as plain
# HTTP 404s, which kills Live Bench telemetry with no error on our side.
try:
    import websockets  # noqa: F401
except ImportError:
    try:
        import wsproto  # noqa: F401
    except ImportError:
        print("[warn] Neither 'websockets' nor 'wsproto' is installed — "
              "WebSocket telemetry will 404. Run via .venv/bin/uvicorn or "
              "pip install -r requirements.txt")

app = FastAPI(title="Solus", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup():
    init_db()


app.include_router(router)
