from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

app = FastAPI()

# CORS (ESP32 + web)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# base de datos en memoria
nodes = {}

# ================= API ESP32 =================
@app.post("/data")
async def receive_data(payload: dict):
    print("RECIBIDO:", payload)
    nodes[payload["id"]] = payload
    return {"ok": True}

@app.get("/nodes")
def get_nodes():
    return nodes

# ================= FRONTEND =================
app.mount("/", StaticFiles(directory="static", html=True), name="static")
