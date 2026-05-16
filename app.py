from fastapi import FastAPI

app = FastAPI()

nodos = {}

@app.post("/temperatura")
async def temperatura(data: dict):

    nodo = data["nodo"]
    temp = data["temp"]

    nodos[nodo] = temp

    print(nodos)

    return {"ok": True}

@app.get("/")
async def inicio():

    texto = ""

    for nodo, temp in nodos.items():

        texto += f"{nodo}: {temp} °C\n"

    return texto
