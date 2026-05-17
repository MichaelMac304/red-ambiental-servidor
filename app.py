from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Dict
import time

app = FastAPI()

# ================= CORS =================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ================= STATIC =================
app.mount("/static", StaticFiles(directory="static"), name="static")

# ================= DATABASE RAM =================
nodes = {}
links = []

# ================= MODEL =================
class NodeData(BaseModel):
    id: str
    lat: float
    lon: float
    temp: float

# ================= ROOT =================
@app.get("/")
def root():
    return FileResponse("static/index.html")

# ================= RECEIVE DATA =================
@app.post("/data")
def receive_data(data: NodeData):

    nodes[data.id] = {
        "id": data.id,
        "lat": data.lat,
        "lon": data.lon,
        "temp": data.temp,
        "last_seen": time.time()
    }

    return {
        "status": "ok"
    }

# ================= GET NODES =================
@app.get("/nodes")
def get_nodes():
    return nodes

# ================= LINKS =================
@app.get("/links")
def get_links():

    ids = list(nodes.keys())

    dynamic_links = []

    for i in range(len(ids)-1):

        a = nodes[ids[i]]
        b = nodes[ids[i+1]]

        dynamic_links.append({
            "from": [a["lat"], a["lon"]],
            "to": [b["lat"], b["lon"]]
        })

    return dynamic_links
