from fastapi import FastAPI

app = FastAPI()

datos = []

@app.post("/temperatura")
async def temperatura(data: dict):

    datos.append(data)

    print(data)

    return {"ok": True}

@app.get("/datos")
async def ver():

    return datos
