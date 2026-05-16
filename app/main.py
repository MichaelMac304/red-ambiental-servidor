from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from datetime import datetime, timezone
from threading import Lock

app = FastAPI(title="Red Ambiental - Servidor Central")

# Disable CORS. Do not remove this for full-stack development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

# Almacenamiento en memoria de datos de estaciones
station_data: dict[str, dict] = {}
station_history: dict[str, list[dict]] = {}
data_lock = Lock()

MAX_HISTORY = 1440  # ~24 horas si envían cada minuto


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.post("/api/stations/data")
async def receive_station_data(data: dict):
    """Recibe datos de una estación via HTTP POST (alternativa a MQTT)."""
    station_id = data.get("station_id", "unknown")
    data["received_at"] = datetime.now(timezone.utc).isoformat()

    with data_lock:
        station_data[station_id] = data

        if station_id not in station_history:
            station_history[station_id] = []
        station_history[station_id].append(data)
        if len(station_history[station_id]) > MAX_HISTORY:
            station_history[station_id] = station_history[station_id][-MAX_HISTORY:]

    return {"status": "ok", "station_id": station_id}


@app.get("/api/stations")
async def get_all_stations():
    """Retorna los datos más recientes de todas las estaciones."""
    with data_lock:
        return list(station_data.values())


@app.get("/api/stations/{station_id}")
async def get_station(station_id: str):
    """Retorna los datos más recientes de una estación específica."""
    with data_lock:
        if station_id in station_data:
            return station_data[station_id]
    return {"error": "Estación no encontrada"}


@app.get("/api/stations/{station_id}/history")
async def get_station_history(station_id: str, limit: int = 60):
    """Retorna el historial de una estación."""
    with data_lock:
        if station_id in station_history:
            return station_history[station_id][-limit:]
    return []


@app.get("/api/heatmap")
async def get_heatmap_data():
    """Retorna datos formateados para el mapa de calor."""
    with data_lock:
        return [
            {
                "lat": s.get("lat", 0),
                "lon": s.get("lon", 0),
                "temperature": s.get("temperature", 0),
                "humidity": s.get("humidity"),
                "station_id": s.get("station_id"),
                "sensor_type": s.get("sensor_type"),
                "received_at": s.get("received_at"),
            }
            for s in station_data.values()
        ]


@app.get("/api/summary")
async def get_summary():
    """Resumen general de la red."""
    with data_lock:
        if not station_data:
            return {
                "total_stations": 0,
                "avg_temperature": None,
                "min_temperature": None,
                "max_temperature": None,
            }

        temps = [
            s["temperature"]
            for s in station_data.values()
            if "temperature" in s
        ]

        return {
            "total_stations": len(station_data),
            "avg_temperature": round(sum(temps) / len(temps), 1) if temps else None,
            "min_temperature": round(min(temps), 1) if temps else None,
            "max_temperature": round(max(temps), 1) if temps else None,
            "stations": list(station_data.keys()),
        }


@app.post("/api/demo/load")
async def load_demo_data():
    """Carga datos de demostración para probar el dashboard."""
    demo_stations = [
        {
            "station_id": "MET-001",
            "sensor_type": "ESP32-interno",
            "lat": -33.391898,
            "lon": -56.518949,
            "temperature": 28.5,
            "humidity": None,
        },
        {
            "station_id": "MET-002",
            "sensor_type": "ESP32-interno",
            "lat": -33.391126,
            "lon": -56.518502,
            "temperature": 31.2,
            "humidity": None,
        },
    ]

    with data_lock:
        for s in demo_stations:
            s["received_at"] = datetime.now(timezone.utc).isoformat()
            station_data[s["station_id"]] = s

    return {"status": "ok", "loaded": len(demo_stations)}


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    """Sirve el dashboard principal con mapa de calor."""
    return DASHBOARD_HTML


DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Red Ambiental - Dashboard</title>
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Segoe UI', Arial, sans-serif; background: #1a1a2e; color: #eee; }

        .header {
            background: linear-gradient(135deg, #16213e, #0f3460);
            padding: 15px 25px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            box-shadow: 0 2px 10px rgba(0,0,0,0.3);
        }
        .header h1 { font-size: 1.4em; color: #e94560; }
        .header .stats { display: flex; gap: 20px; }
        .stat-box {
            background: rgba(255,255,255,0.1);
            padding: 8px 15px;
            border-radius: 8px;
            text-align: center;
        }
        .stat-box .value { font-size: 1.5em; font-weight: bold; color: #e94560; }
        .stat-box .label { font-size: 0.75em; color: #aaa; }

        #map { height: calc(100vh - 70px); width: 100%; }

        .control-panel {
            position: absolute;
            top: 80px;
            right: 15px;
            z-index: 1000;
            background: rgba(26, 26, 46, 0.95);
            padding: 15px;
            border-radius: 10px;
            box-shadow: 0 4px 15px rgba(0,0,0,0.4);
            min-width: 200px;
        }
        .control-panel h3 { color: #e94560; margin-bottom: 10px; font-size: 0.95em; }
        .control-panel select {
            width: 100%;
            padding: 8px;
            border-radius: 5px;
            border: 1px solid #333;
            background: #16213e;
            color: #eee;
            margin-bottom: 10px;
        }
        .control-panel button {
            width: 100%;
            padding: 8px;
            border-radius: 5px;
            border: none;
            background: #e94560;
            color: white;
            cursor: pointer;
            font-weight: bold;
            margin-bottom: 5px;
        }
        .control-panel button:hover { background: #c73e54; }
        .control-panel .btn-demo { background: #0f3460; }
        .control-panel .btn-demo:hover { background: #1a4a7a; }

        .station-list {
            margin-top: 10px;
            max-height: 200px;
            overflow-y: auto;
        }
        .station-item {
            background: rgba(255,255,255,0.05);
            padding: 8px;
            border-radius: 5px;
            margin-bottom: 5px;
            font-size: 0.85em;
        }
        .station-item .name { color: #e94560; font-weight: bold; }
        .station-item .temp { color: #4ecca3; font-size: 1.1em; }

        .leaflet-popup-content-wrapper {
            background: #16213e;
            color: #eee;
            border-radius: 8px;
        }
        .leaflet-popup-tip { background: #16213e; }
        .popup-content { font-size: 0.9em; }
        .popup-content b { color: #e94560; }
        .popup-content .temp-big { font-size: 1.8em; color: #4ecca3; }
    </style>
</head>
<body>
    <div class="header">
        <h1>Red Ambiental</h1>
        <div class="stats">
            <div class="stat-box">
                <div class="value" id="station-count">0</div>
                <div class="label">Estaciones</div>
            </div>
            <div class="stat-box">
                <div class="value" id="avg-temp">--</div>
                <div class="label">Temp. Promedio</div>
            </div>
            <div class="stat-box">
                <div class="value" id="min-temp">--</div>
                <div class="label">Min</div>
            </div>
            <div class="stat-box">
                <div class="value" id="max-temp">--</div>
                <div class="label">Max</div>
            </div>
        </div>
    </div>

    <div id="map"></div>

    <div class="control-panel">
        <h3>Controles</h3>
        <label style="font-size:0.8em; color:#aaa;">Variable:</label>
        <select id="variable">
            <option value="temperature">Temperatura</option>
            <option value="humidity">Humedad</option>
        </select>
        <button onclick="updateMap()">Actualizar</button>
        <button class="btn-demo" onclick="loadDemo()">Cargar Demo</button>

        <h3 style="margin-top:15px;">Estaciones</h3>
        <div class="station-list" id="station-list">
            <div style="color:#666; font-size:0.85em;">Sin datos. Carga la demo o conecta tus ESP32.</div>
        </div>
    </div>

    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <script src="https://unpkg.com/leaflet.heat/dist/leaflet-heat.js"></script>
    <script>
        const API_BASE = window.location.origin;

        const map = L.map('map', {
            zoomControl: true
        }).setView([-33.391, -56.519], 16);

        L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
            attribution: '&copy; OpenStreetMap &copy; CARTO',
            maxZoom: 19
        }).addTo(map);

        let heatLayer = null;
        let markers = [];

        function getColorForTemp(temp) {
            if (temp <= 15) return '#3498db';
            if (temp <= 20) return '#2ecc71';
            if (temp <= 25) return '#f1c40f';
            if (temp <= 30) return '#e67e22';
            if (temp <= 35) return '#e74c3c';
            return '#8e44ad';
        }

        async function updateMap() {
            try {
                const variable = document.getElementById('variable').value;

                const [stationsRes, summaryRes] = await Promise.all([
                    fetch(API_BASE + '/api/stations'),
                    fetch(API_BASE + '/api/summary')
                ]);
                const stations = await stationsRes.json();
                const summary = await summaryRes.json();

                document.getElementById('station-count').textContent = summary.total_stations;
                document.getElementById('avg-temp').textContent =
                    summary.avg_temperature !== null ? summary.avg_temperature + '\\u00b0C' : '--';
                document.getElementById('min-temp').textContent =
                    summary.min_temperature !== null ? summary.min_temperature + '\\u00b0C' : '--';
                document.getElementById('max-temp').textContent =
                    summary.max_temperature !== null ? summary.max_temperature + '\\u00b0C' : '--';

                if (heatLayer) map.removeLayer(heatLayer);
                markers.forEach(m => map.removeLayer(m));
                markers = [];

                if (stations.length === 0) return;

                const heatPoints = stations
                    .filter(s => s[variable] !== null && s[variable] !== undefined)
                    .map(s => [s.lat, s.lon, Math.max(0, s[variable]) / 50]);

                if (heatPoints.length > 0) {
                    heatLayer = L.heatLayer(heatPoints, {
                        radius: 60,
                        blur: 40,
                        maxZoom: 17,
                        gradient: {
                            0.0: '#3498db',
                            0.3: '#2ecc71',
                            0.5: '#f1c40f',
                            0.7: '#e67e22',
                            0.85: '#e74c3c',
                            1.0: '#8e44ad'
                        }
                    }).addTo(map);
                }

                stations.forEach(s => {
                    const color = getColorForTemp(s.temperature || 0);
                    const icon = L.divIcon({
                        className: '',
                        html: '<div style="background:' + color + '; width:36px; height:36px; border-radius:50%; display:flex; align-items:center; justify-content:center; color:white; font-weight:bold; font-size:11px; border:3px solid rgba(255,255,255,0.8); box-shadow: 0 2px 8px rgba(0,0,0,0.4);">' +
                              (s.temperature !== null ? s.temperature + '\\u00b0' : '?') + '</div>',
                        iconSize: [36, 36],
                        iconAnchor: [18, 18]
                    });

                    const marker = L.marker([s.lat, s.lon], { icon: icon })
                        .bindPopup(
                            '<div class="popup-content">' +
                            '<b>' + s.station_id + '</b> (' + (s.sensor_type || '?') + ')<br>' +
                            '<div class="temp-big">' + (s.temperature !== null ? s.temperature + '\\u00b0C' : 'N/A') + '</div>' +
                            (s.humidity !== null && s.humidity !== undefined ?
                                'Humedad: ' + s.humidity + '%<br>' : '') +
                            '<span style="color:#666; font-size:0.8em;">Actualizado: ' +
                            (s.received_at ? new Date(s.received_at).toLocaleTimeString() : '?') +
                            '</span></div>'
                        )
                        .addTo(map);
                    markers.push(marker);
                });

                const listEl = document.getElementById('station-list');
                if (stations.length > 0) {
                    listEl.innerHTML = stations.map(s =>
                        '<div class="station-item">' +
                        '<span class="name">' + s.station_id + '</span> ' +
                        '<span style="color:#666;">(' + (s.sensor_type || '?') + ')</span><br>' +
                        '<span class="temp">' + (s.temperature !== null ? s.temperature + '\\u00b0C' : 'N/A') + '</span>' +
                        (s.humidity !== null && s.humidity !== undefined ?
                            ' | Hum: ' + s.humidity + '%' : '') +
                        '</div>'
                    ).join('');
                }

                if (stations.length > 0) {
                    const bounds = L.latLngBounds(stations.map(s => [s.lat, s.lon]));
                    map.fitBounds(bounds.pad(0.5));
                }

            } catch (err) {
                console.error('Error actualizando mapa:', err);
            }
        }

        async function loadDemo() {
            try {
                await fetch(API_BASE + '/api/demo/load', { method: 'POST' });
                await updateMap();
            } catch (err) {
                console.error('Error cargando demo:', err);
            }
        }

        updateMap();
        setInterval(updateMap, 5000);
    </script>
</body>
</html>"""
