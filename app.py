from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from datetime import datetime

app = FastAPI()

class TempData(BaseModel):
    nodo: str
    temp: float

nodos = {}

@app.post("/temperatura")
async def temperatura(data: TempData):

    nodos[data.nodo] = {
        "temp": round(data.temp, 1),
        "hora": datetime.now().strftime("%H:%M:%S")
    }

    print(nodos)

    return {"ok": True}

@app.get("/api/datos")
async def api_datos():

    return nodos

@app.get("/", response_class=HTMLResponse)
async def dashboard():

    html = """
<!DOCTYPE html>
<html lang="es">

<head>

<meta charset="UTF-8">

<meta name="viewport"
content="width=device-width, initial-scale=1.0">

<title>Red Ambiental ESP32</title>

<style>

body {

    margin: 0;
    font-family: Arial, sans-serif;
    background: #0f172a;
    color: white;
}

header {

    background: #111827;
    padding: 20px;
    text-align: center;
    font-size: 32px;
    font-weight: bold;
    border-bottom: 2px solid #1e293b;
}

.subtitulo {

    text-align: center;
    color: #94a3b8;
    margin-top: 10px;
    font-size: 14px;
}

.grid {

    display: grid;

    grid-template-columns:
    repeat(auto-fit, minmax(250px, 1fr));

    gap: 20px;

    padding: 20px;
}

.card {

    background: #1e293b;

    border-radius: 20px;

    padding: 20px;

    box-shadow: 0 0 20px rgba(0,0,0,0.3);

    transition: 0.2s;
}

.card:hover {

    transform: scale(1.03);
}

.nodo {

    font-size: 24px;
    font-weight: bold;
    margin-bottom: 15px;
}

.temp {

    font-size: 50px;
    font-weight: bold;
    color: #38bdf8;
}

.hora {

    margin-top: 10px;
    color: #94a3b8;
}

.estado {

    margin-top: 15px;

    display: inline-block;

    padding: 8px 14px;

    border-radius: 12px;

    background: #22c55e;

    color: white;

    font-weight: bold;
}

.gateway {

    border: 2px solid #f59e0b;
}

.footer {

    text-align: center;

    color: #64748b;

    margin-bottom: 20px;
}

</style>

</head>

<body>

<header>

🌎 RED AMBIENTAL ESP32

</header>

<div class="subtitulo">

Monitoreo en tiempo real de temperatura de nodos ESP32

</div>

<div class="grid" id="grid"></div>

<div class="footer">

Actualización automática cada 2 segundos

</div>

<script>

async function cargarDatos() {

    try {

        const response =
        await fetch('/api/datos');

        const datos =
        await response.json();

        const grid =
        document.getElementById('grid');

        grid.innerHTML = '';

        for (const nodo in datos) {

            const info = datos[nodo];

            const esGateway =
            nodo === 'GATEWAY';

            const card =
            document.createElement('div');

            card.className =
            esGateway
            ? 'card gateway'
            : 'card';

            card.innerHTML = `

                <div class="nodo">

                    ${esGateway ? '📡' : '📟'}

                    ${nodo}

                </div>

                <div class="temp">

                    🌡 ${info.temp} °C

                </div>

                <div class="hora">

                    ⏰ ${info.hora}

                </div>

                <div class="estado">

                    ONLINE

                </div>
            `;

            grid.appendChild(card);
        }

    } catch (error) {

        console.log(error);
    }
}

cargarDatos();

setInterval(cargarDatos, 2000);

</script>

</body>

</html>
    """

    return HTMLResponse(content=html)
