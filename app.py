from fastapi import FastAPI

app = FastAPI()

datos = []

@app.post("/temperatura")
async def temperatura(data: dict):

    datos.append(data)

    print(data)

    return {"ok": True}

@app.get("/")
async def inicio():

    return {"servidor": "activo"}

@app.get("/datos")
async def ver_datos():

    return datos
