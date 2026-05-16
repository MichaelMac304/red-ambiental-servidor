from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

nodes = {}

@app.post("/data")
async def data(payload: dict):
    nodes[payload["id"]] = payload
    return {"status": "ok"}

@app.get("/nodes")
def get_nodes():
    return nodes
