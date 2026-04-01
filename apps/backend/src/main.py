import os
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '..', '.env'))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .database import init_db
from .routes import router

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
