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

@app.post("/data")
async def data(payload: dict):

    print("==== RECIBIDO EN SERVER ====")
    print(payload)

    nodes[payload["id"]] = payload

    print("TOTAL NODOS:", len(nodes))

    return {"ok": True, "nodes": len(nodes)}

@app.get("/nodes")
def get_nodes():
    return nodes
