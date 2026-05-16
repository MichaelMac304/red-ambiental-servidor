from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from datetime import datetime

app = FastAPI()

# =========================
# MODELO DE DATOS
# =========================

class TempData(BaseModel):
    nodo: str
    temp: float
    lat: float
    lon: float

# =========================
# MEMORIA DE NODOS
# =========================

nodos = {}

# =========================
# RECIBIR DATOS
# =========================

@app.post("/temperatura")
async def temperatura(data: TempData):

    nodos[data.nodo] = {
        "temp": round(data.temp, 1),
        "lat": data.lat,
        "lon": data.lon,
        "hora": datetime.now().strftime("%H:%M:%S")
    }

    print(nodos)

    return {"ok": True}

# =========================
# API JSON
# =========================

@app.get("/api/datos")
async def api_datos():

    return nodos

# =========================
# MAPA WEB
# =========================

@app.get("/", response_class=HTMLResponse)
async def mapa():

    html = """
<!DOCTYPE html>

<html lang="es">

<head>

<meta charset="UTF-8">

<meta name="viewport"
content="width=device-width, initial-scale=1.0">

<title>Mapa Térmico ESP32</title>

<link rel="stylesheet"
href="https://unpkg.com/leaflet/dist/leaflet.css"/>

<script src="https://unpkg.com/leaflet/dist/leaflet.js"></script>

<style>

body {

    margin: 0;
    background: #0f172a;
    color: white;
    font-family: Arial;
}

#map {

    height: 100vh;
    width: 100%;
}

.panel {

    position: absolute;

    top: 10px;
    left: 10px;

    z-index: 1000;

    background: rgba(15,23,42,0.95);

    padding: 15px;

    border-radius: 15px;

    min-width: 250px;

    box-shadow: 0 0 20px rgba(0,0,0,0.5);
}

.titulo {

    font-size: 22px;
    font-weight: bold;
    margin-bottom: 10px;
}

.estado {

    margin-top: 10px;
    color: #38bdf8;
}

</style>

</head>

<body>

<div class="panel">

<div class="titulo">

🌎 RED AMBIENTAL ESP32

</div>

<div>

Mapa térmico en tiempo real

</div>

<div class="estado" id="estado">

Actualizando...

</div>

</div>

<div id="map"></div>

<script>

const map = L.map('map').setView(
[-33.3913, -56.5192],
17
);

L.tileLayer(
'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
{
    attribution: 'OpenStreetMap'
}
).addTo(map);

let markers = [];
let circles = [];

function colorTemp(temp) {

    if (temp < 20) return '#00bfff';

    if (temp < 30) return '#22c55e';

    if (temp < 40) return '#f59e0b';

    return '#ef4444';
}

async function actualizar() {

    try {

        const response =
        await fetch('/api/datos');

        const datos =
        await response.json();

        markers.forEach(m => map.removeLayer(m));
        circles.forEach(c => map.removeLayer(c));

        markers = [];
        circles = [];

        for (const nodo in datos) {

            const info = datos[nodo];

            const color =
            colorTemp(info.temp);

            const marker = L.marker([
                info.lat,
                info.lon
            ]).addTo(map);

            marker.bindPopup(
                "<b>" + nodo + "</b><br>" +
                "🌡 " + info.temp + " °C<br>" +
                "⏰ " + info.hora
            );

            const circle = L.circle([
                info.lat,
                info.lon
            ], {

                color: color,

                fillColor: color,

                fillOpacity: 0.4,

                radius: 35

            }).addTo(map);

            markers.push(marker);
            circles.push(circle);
        }

        document.getElementById('estado').innerHTML =
        'Última actualización: ' +
        new Date().toLocaleTimeString();

    } catch (error) {

        console.log(error);
    }
}

actualizar();

setInterval(actualizar, 500);

</script>

</body>

</html>
    """

    return HTMLResponse(content=html)
