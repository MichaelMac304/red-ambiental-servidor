from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

nodes = {}

@app.get("/")
def root():
    return {"status":"OK"}

@app.post("/data")
def receive(payload: dict):

    print(payload)

    nodes[payload["id"]] = payload

    return {"ok":True}

@app.get("/nodes")
def get_nodes():
    return nodes
