from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from datetime import datetime, timezone, timedelta
from typing import Optional
import sqlite3
import csv
import io
import os
import random

app = FastAPI(title="Red Ambiental ESP32")

# Disable CORS. Do not remove this for full-stack development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static files (logos)
import pathlib
STATIC_DIR = pathlib.Path(__file__).parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# =========================
# MODELOS DE DATOS
# =========================

class TempData(BaseModel):
    nodo: str
    temp: float
    lat: float
    lon: float

class StationData(BaseModel):
    station_id: str
    temperature: float
    lat: float
    lon: float
    sensor_type: Optional[str] = "ESP32-interno"
    rssi: Optional[int] = None
    hops: Optional[int] = None

# =========================
# BASE DE DATOS SQLite
# =========================

DB_PATH = os.environ.get("DB_PATH", "red_ambiental.db")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS lecturas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nodo TEXT NOT NULL,
        temp REAL NOT NULL,
        lat REAL,
        lon REAL,
        tipo TEXT,
        rssi INTEGER,
        hops INTEGER,
        timestamp TEXT NOT NULL
    )""")
    c.execute("""CREATE INDEX IF NOT EXISTS idx_lecturas_nodo ON lecturas(nodo)""")
    c.execute("""CREATE INDEX IF NOT EXISTS idx_lecturas_ts ON lecturas(timestamp)""")
    c.execute("""CREATE TABLE IF NOT EXISTS config_alertas (
        id INTEGER PRIMARY KEY CHECK(id=1),
        temp_min REAL DEFAULT 0,
        temp_max REAL DEFAULT 55,
        activa INTEGER DEFAULT 1
    )""")
    c.execute('INSERT OR IGNORE INTO config_alertas (id, temp_min, temp_max, activa) VALUES (1, 0, 55, 1)')
    conn.commit()
    conn.close()

DB_RETENTION_DAYS = int(os.environ.get("DB_RETENTION_DAYS", "30"))

def save_reading(nodo, temp, lat, lon, tipo, rssi, hops, timestamp):
    try:
        conn = get_db()
        conn.execute('INSERT INTO lecturas (nodo, temp, lat, lon, tipo, rssi, hops, timestamp) VALUES (?,?,?,?,?,?,?,?)',
                     (nodo, temp, lat, lon, tipo, rssi, hops, timestamp))
        conn.commit()
        conn.close()
    except Exception:
        pass

def cleanup_old_readings():
    try:
        desde = (datetime.now(timezone.utc) - timedelta(days=DB_RETENTION_DAYS)).isoformat()
        conn = get_db()
        conn.execute('DELETE FROM lecturas WHERE timestamp < ?', (desde,))
        conn.commit()
        conn.close()
    except Exception:
        pass

@app.on_event("startup")
async def startup():
    init_db()
    cleanup_old_readings()

# =========================
# MEMORIA DE NODOS
# =========================

nodos: dict[str, dict] = {}
historial: dict[str, list[dict]] = {}
MAX_HISTORIAL = 300

# =========================
# NODOS FANTASMA (GHOST)
# =========================

ghost_nodes: dict[str, dict] = {}

GHOST_COORDS = [
    {"id": "GHOST-01", "lat": -33.3925, "lon": -56.5200},
    {"id": "GHOST-02", "lat": -33.3930, "lon": -56.5175},
    {"id": "GHOST-03", "lat": -33.3910, "lon": -56.5210},
    {"id": "GHOST-04", "lat": -33.3935, "lon": -56.5160},
    {"id": "GHOST-05", "lat": -33.3905, "lon": -56.5195},
    {"id": "GHOST-06", "lat": -33.3940, "lon": -56.5185},
    {"id": "GHOST-07", "lat": -33.3915, "lon": -56.5170},
    {"id": "GHOST-08", "lat": -33.3900, "lon": -56.5180},
    {"id": "GHOST-09", "lat": -33.3920, "lon": -56.5215},
    {"id": "GHOST-10", "lat": -33.3945, "lon": -56.5195},
    {"id": "GHOST-11", "lat": -33.3908, "lon": -56.5165},
    {"id": "GHOST-12", "lat": -33.3932, "lon": -56.5205},
    {"id": "GHOST-13", "lat": -33.3918, "lon": -56.5155},
    {"id": "GHOST-14", "lat": -33.3928, "lon": -56.5220},
]

# =========================
# ENDPOINTS DE DATOS
# =========================

@app.get("/healthz")
async def healthz():
    return {"status": "ok"}

@app.post("/temperatura")
async def temperatura(data: TempData):
    ahora = datetime.now(timezone.utc)
    nodos[data.nodo] = {
        "id": data.nodo, "temp": round(data.temp, 1),
        "lat": data.lat, "lon": data.lon, "tipo": "ESP32-interno",
        "hora": ahora.strftime("%H:%M:%S"), "timestamp": ahora.isoformat(),
    }
    if data.nodo not in historial:
        historial[data.nodo] = []
    historial[data.nodo].append({"temp": round(data.temp, 1), "hora": ahora.strftime("%H:%M:%S")})
    if len(historial[data.nodo]) > MAX_HISTORIAL:
        historial[data.nodo] = historial[data.nodo][-MAX_HISTORIAL:]
    save_reading(data.nodo, round(data.temp, 1), data.lat, data.lon, "ESP32-interno", None, None, ahora.isoformat())
    return {"ok": True}

@app.post("/api/stations/data")
async def receive_station_data(data: StationData):
    ahora = datetime.now(timezone.utc)
    nodos[data.station_id] = {
        "id": data.station_id, "temp": round(data.temperature, 1),
        "lat": data.lat, "lon": data.lon,
        "tipo": data.sensor_type or "ESP32-interno",
        "hora": ahora.strftime("%H:%M:%S"), "timestamp": ahora.isoformat(),
        "rssi": data.rssi, "hops": data.hops if data.hops is not None else 0,
    }
    if data.station_id not in historial:
        historial[data.station_id] = []
    historial[data.station_id].append({"temp": round(data.temperature, 1), "hora": ahora.strftime("%H:%M:%S")})
    if len(historial[data.station_id]) > MAX_HISTORIAL:
        historial[data.station_id] = historial[data.station_id][-MAX_HISTORIAL:]
    save_reading(data.station_id, round(data.temperature, 1), data.lat, data.lon, data.sensor_type or "ESP32-interno", data.rssi, data.hops, ahora.isoformat())
    return {"status": "ok", "station_id": data.station_id}

@app.get("/api/datos")
async def api_datos():
    ahora = datetime.now(timezone.utc)
    resultado = {}
    for nid, n in nodos.items():
        copia = dict(n)
        try:
            ts = datetime.fromisoformat(n["timestamp"])
            edad = (ahora - ts).total_seconds()
            copia["online"] = edad < 30
        except Exception:
            copia["online"] = False
        resultado[nid] = copia
    for gid, g in ghost_nodes.items():
        if g.get("activo", True):
            temp_base = 32.0 + random.uniform(-2, 2)
            resultado[gid] = {
                "id": gid, "temp": round(temp_base, 1),
                "lat": g["lat"], "lon": g["lon"], "tipo": "ESP32-fantasma",
                "hora": ahora.strftime("%H:%M:%S"), "timestamp": ahora.isoformat(),
                "rssi": random.randint(-75, -45), "hops": random.randint(1, 3),
                "online": True, "ghost": True,
            }
        else:
            resultado[gid] = {
                "id": gid, "temp": g.get("last_temp", 32.0),
                "lat": g["lat"], "lon": g["lon"], "tipo": "ESP32-fantasma",
                "hora": g.get("last_hora", "--"),
                "timestamp": g.get("last_ts", ahora.isoformat()),
                "online": False, "ghost": True,
            }
    return resultado

@app.get("/api/resumen")
async def api_resumen():
    ahora = datetime.now(timezone.utc)
    all_nodes = dict(nodos)
    for gid, g in ghost_nodes.items():
        if g.get("activo", True):
            all_nodes[gid] = {"temp": round(32.0 + random.uniform(-2, 2), 1), "timestamp": ahora.isoformat()}
        else:
            all_nodes[gid] = {"temp": g.get("last_temp", 32.0), "timestamp": g.get("last_ts", ahora.isoformat())}
    if not all_nodes:
        return {"total": 0, "online": 0, "promedio": None, "minima": None, "maxima": None, "nodos": []}
    online_count = 0
    for nid, n in all_nodes.items():
        try:
            ts = datetime.fromisoformat(n["timestamp"])
            if (ahora - ts).total_seconds() < 30:
                online_count += 1
        except Exception:
            pass
    temps = [n["temp"] for n in all_nodes.values()]
    return {
        "total": len(all_nodes), "online": online_count,
        "promedio": round(sum(temps) / len(temps), 1),
        "minima": round(min(temps), 1), "maxima": round(max(temps), 1),
        "nodos": list(all_nodes.keys()),
    }

@app.get("/api/historial/{nodo_id}")
async def api_historial(nodo_id: str, limit: int = 60):
    return historial.get(nodo_id, [])[-limit:]

@app.post("/api/demo")
async def cargar_demo():
    ahora = datetime.now(timezone.utc)
    demos = [
        {"id": "MET-001", "temp": 44.4, "lat": -33.391898, "lon": -56.518949, "tipo": "ESP32-interno (ROOT)", "rssi": -45, "hops": 0},
        {"id": "MET-002", "temp": 51.1, "lat": -33.391126, "lon": -56.518502, "tipo": "ESP32-interno (NODO)", "rssi": -62, "hops": 1},
    ]
    for d in demos:
        d["hora"] = ahora.strftime("%H:%M:%S")
        d["timestamp"] = ahora.isoformat()
        nodos[d["id"]] = d
        if d["id"] not in historial:
            historial[d["id"]] = []
        historial[d["id"]].append({"temp": d["temp"], "hora": d["hora"]})
        save_reading(d["id"], d["temp"], d["lat"], d["lon"], d["tipo"], d.get("rssi"), d.get("hops"), ahora.isoformat())
    return {"ok": True, "cargados": len(demos)}

# =========================
# GHOST NODE ENDPOINTS
# =========================

@app.post("/api/ghost/activar")
async def activar_ghosts():
    ahora = datetime.now(timezone.utc)
    for gc in GHOST_COORDS:
        ghost_nodes[gc["id"]] = {
            "lat": gc["lat"], "lon": gc["lon"], "activo": True,
            "last_temp": round(32.0 + random.uniform(-2, 2), 1),
            "last_hora": ahora.strftime("%H:%M:%S"), "last_ts": ahora.isoformat(),
        }
    return {"ok": True, "total": len(ghost_nodes)}

@app.post("/api/ghost/toggle/{ghost_id}")
async def toggle_ghost(ghost_id: str):
    if ghost_id in ghost_nodes:
        ghost_nodes[ghost_id]["activo"] = not ghost_nodes[ghost_id]["activo"]
        return {"ok": True, "id": ghost_id, "activo": ghost_nodes[ghost_id]["activo"]}
    return {"ok": False, "error": "Ghost node not found"}

@app.post("/api/ghost/crear")
async def crear_ghost(data: dict):
    gid = data.get("id", "")
    lat = data.get("lat")
    lon = data.get("lon")
    if not gid or lat is None or lon is None:
        return {"ok": False, "error": "Se requiere id, lat y lon"}
    ahora = datetime.now(timezone.utc)
    ghost_nodes[gid] = {
        "lat": float(lat), "lon": float(lon), "activo": True,
        "last_temp": round(32.0 + random.uniform(-2, 2), 1),
        "last_hora": ahora.strftime("%H:%M:%S"), "last_ts": ahora.isoformat(),
    }
    return {"ok": True, "id": gid, "total": len(ghost_nodes)}

@app.post("/api/ghost/desactivar")
async def desactivar_ghosts():
    ghost_nodes.clear()
    return {"ok": True}

# =========================
# NUEVOS ENDPOINTS
# =========================

class AlertConfig(BaseModel):
    temp_min: float = 0
    temp_max: float = 55
    activa: bool = True

@app.get("/api/historial/db/{nodo_id}")
async def api_historial_db(nodo_id: str, horas: int = 24):
    desde = (datetime.now(timezone.utc) - timedelta(hours=horas)).isoformat()
    conn = get_db()
    rows = conn.execute(
        'SELECT temp, timestamp FROM lecturas WHERE nodo=? AND timestamp>=? ORDER BY timestamp',
        (nodo_id, desde)
    ).fetchall()
    conn.close()
    return [{"temp": r["temp"], "timestamp": r["timestamp"]} for r in rows]

@app.get("/api/exportar/csv")
async def exportar_csv(horas: int = 24):
    desde = (datetime.now(timezone.utc) - timedelta(hours=horas)).isoformat()
    conn = get_db()
    rows = conn.execute(
        'SELECT nodo, temp, timestamp, tipo, hops FROM lecturas WHERE timestamp>=? ORDER BY timestamp',
        (desde,)
    ).fetchall()
    conn.close()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Nodo', 'Temperatura', 'H:M:S', 'Tipo de sensor', 'Saltos'])
    for r in rows:
        try:
            ts = datetime.fromisoformat(r['timestamp'])
            hms = ts.strftime("%H:%M:%S")
        except Exception:
            hms = r['timestamp']
        writer.writerow([r['nodo'], r['temp'], hms, r['tipo'] or 'ESP32-interno', r['hops'] or 0])
    output.seek(0)
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode('utf-8')),
        media_type='text/csv',
        headers={'Content-Disposition': f'attachment; filename=red_ambiental_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'}
    )

@app.get("/api/alertas")
async def get_alertas():
    conn = get_db()
    row = conn.execute('SELECT temp_min, temp_max, activa FROM config_alertas WHERE id=1').fetchone()
    conn.close()
    if row:
        return {"temp_min": row["temp_min"], "temp_max": row["temp_max"], "activa": bool(row["activa"])}
    return {"temp_min": 0, "temp_max": 55, "activa": True}

@app.post("/api/alertas")
async def set_alertas(config: AlertConfig):
    conn = get_db()
    conn.execute('UPDATE config_alertas SET temp_min=?, temp_max=?, activa=? WHERE id=1',
                 (config.temp_min, config.temp_max, 1 if config.activa else 0))
    conn.commit()
    conn.close()
    return {"ok": True}

@app.get("/api/promedios")
async def api_promedios(horas: int = 24):
    desde = (datetime.now(timezone.utc) - timedelta(hours=horas)).isoformat()
    conn = get_db()
    rows = conn.execute(
        """SELECT nodo,
           strftime('%Y-%m-%dT%H:00:00', timestamp) as hora,
           ROUND(AVG(temp),1) as prom,
           ROUND(MIN(temp),1) as min_t,
           ROUND(MAX(temp),1) as max_t,
           COUNT(*) as cnt
        FROM lecturas WHERE timestamp >= ?
        GROUP BY nodo, strftime('%Y-%m-%dT%H:00:00', timestamp)
        ORDER BY hora""",
        (desde,)
    ).fetchall()
    conn.close()
    result = {}
    for r in rows:
        nid = r['nodo']
        if nid not in result:
            result[nid] = []
        result[nid].append({'hora': r['hora'], 'prom': r['prom'], 'min': r['min_t'], 'max': r['max_t'], 'lecturas': r['cnt']})
    return result

@app.get("/api/salud")
async def salud_red():
    ahora = datetime.now(timezone.utc)
    salud = []
    for nid, n in nodos.items():
        try:
            ts = datetime.fromisoformat(n["timestamp"])
            edad = (ahora - ts).total_seconds()
            online = edad < 30
        except Exception:
            edad = 9999
            online = False
        conn = get_db()
        total = conn.execute('SELECT COUNT(*) as c FROM lecturas WHERE nodo=?', (nid,)).fetchone()["c"]
        ultima_hora = conn.execute(
            'SELECT COUNT(*) as c FROM lecturas WHERE nodo=? AND timestamp>=?',
            (nid, (ahora - timedelta(hours=1)).isoformat())
        ).fetchone()["c"]
        conn.close()
        salud.append({
            "id": nid, "online": online, "rssi": n.get("rssi"),
            "hops": n.get("hops", 0), "edad_seg": round(edad, 1),
            "lecturas_total": total, "lecturas_1h": ultima_hora,
            "tipo": n.get("tipo", "ESP32-interno"),
        })
    for gid, g in ghost_nodes.items():
        salud.append({
            "id": gid, "online": g.get("activo", True),
            "rssi": random.randint(-75, -45) if g.get("activo") else None,
            "hops": random.randint(1, 3) if g.get("activo") else 0,
            "edad_seg": 0 if g.get("activo") else 9999,
            "lecturas_total": 0, "lecturas_1h": 0,
            "tipo": "ESP32-fantasma", "ghost": True,
        })
    return salud

# =========================
# DASHBOARD
# =========================

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return DASHBOARD_HTML

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>MET. Red de Estaciones Meteorologicas</title>
<link rel="icon" type="image/png" href="/static/logo_header.png">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.css"/>
<link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.Default.css"/>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{
    --bg:#0a0e1a;--card:#111827;--card2:#1a2236;--border:#1e293b;
    --accent:#06d6a0;--accent2:#118ab2;
    --hot:#ef476f;--warm:#ffd166;--cool:#06d6a0;--cold:#118ab2;
    --text:#e2e8f0;--text2:#94a3b8;
    --glow:rgba(6,214,160,0.15);
}
body{font-family:'Inter',sans-serif;background:var(--bg);color:var(--text);overflow:hidden;height:100vh}

/* SPLASH SCREEN */
.splash{position:fixed;inset:0;background:linear-gradient(135deg,#0a0e1a 0%,#1a2236 50%,#0f172a 100%);z-index:9999;display:flex;align-items:center;justify-content:center;flex-direction:column;transition:opacity 0.8s ease,visibility 0.8s ease}
.splash.hidden{opacity:0;visibility:hidden;pointer-events:none}
.splash img{width:320px;max-width:80vw;animation:splashPulse 2s ease-in-out infinite;filter:drop-shadow(0 0 40px rgba(6,214,160,0.3))}
.splash-text{color:var(--text2);font-size:0.85em;margin-top:24px;letter-spacing:2px;text-transform:uppercase;animation:splashFade 1.5s ease-in-out infinite alternate}
.splash-loader{width:200px;height:3px;background:var(--border);border-radius:3px;margin-top:16px;overflow:hidden}
.splash-loader-bar{width:0%;height:100%;background:linear-gradient(90deg,var(--accent),var(--accent2));border-radius:3px;animation:splashLoad 1.3s ease-in-out forwards}
@keyframes splashPulse{0%,100%{transform:scale(1)}50%{transform:scale(1.03)}}
@keyframes splashFade{from{opacity:0.5}to{opacity:1}}
@keyframes splashLoad{0%{width:0%}60%{width:80%}100%{width:100%}}

.header{
    background:linear-gradient(135deg,#0f172a 0%,#1e293b 100%);
    padding:12px 24px;display:flex;align-items:center;justify-content:space-between;
    border-bottom:1px solid var(--border);position:relative;z-index:1001;
}
.logo{display:flex;align-items:center;gap:12px}
.logo-img{width:42px;height:42px;border-radius:10px;object-fit:contain;box-shadow:0 0 20px var(--glow)}
.logo h1{font-size:1.15em;font-weight:700;letter-spacing:-0.5px}
.logo h1 span{color:var(--accent);font-weight:800}
.logo-sub{font-size:0.7em;color:var(--text2);font-weight:400;letter-spacing:0.5px}

.stats{display:flex;gap:8px}
.stat{
    background:var(--card);border:1px solid var(--border);border-radius:10px;
    padding:8px 16px;min-width:90px;text-align:center;transition:all 0.3s ease;
}
.stat:hover{border-color:var(--accent);box-shadow:0 0 15px var(--glow)}
.stat .val{font-size:1.4em;font-weight:700;line-height:1.2}
.stat .lbl{font-size:0.65em;color:var(--text2);text-transform:uppercase;letter-spacing:1px;font-weight:500}
.stat.estaciones .val{color:var(--accent)}
.stat.promedio .val{color:var(--warm)}
.stat.minima .val{color:var(--cool)}
.stat.maxima .val{color:var(--hot)}

.status{display:flex;align-items:center;gap:6px;font-size:0.75em;color:var(--text2)}
.dot{width:8px;height:8px;border-radius:50%;background:#22c55e;animation:pulse 2s infinite}
@keyframes pulse{0%,100%{opacity:1;box-shadow:0 0 0 0 rgba(34,197,94,0.5)}50%{opacity:0.7;box-shadow:0 0 0 6px rgba(34,197,94,0)}}

.main{display:flex;height:calc(100vh - 62px)}
#map{flex:1;z-index:1}

.sidebar{
    width:340px;background:var(--card);border-left:1px solid var(--border);
    display:flex;flex-direction:column;z-index:1000;overflow:hidden;
}
.sidebar-header{
    padding:16px 20px 12px;border-bottom:1px solid var(--border);
    display:flex;align-items:center;justify-content:space-between;
}
.sidebar-header h2{font-size:0.9em;font-weight:600;letter-spacing:-0.3px}
.badge{background:var(--accent);color:#000;font-size:0.65em;font-weight:700;padding:2px 8px;border-radius:20px}

.stations{flex:1;overflow-y:auto;padding:12px 16px}
.stations::-webkit-scrollbar{width:4px}
.stations::-webkit-scrollbar-thumb{background:var(--border);border-radius:4px}

.scard{
    background:var(--card2);border:1px solid var(--border);border-radius:12px;
    padding:14px 16px;margin-bottom:10px;transition:all 0.3s ease;
    cursor:pointer;position:relative;overflow:hidden;
}
.scard::before{content:'';position:absolute;top:0;left:0;width:4px;height:100%;border-radius:4px 0 0 4px}
.scard.root::before{background:var(--accent)}
.scard.nodo::before{background:var(--accent2)}
.scard.ghost::before{background:#8b5cf6}
.scard.offline{opacity:0.5;filter:grayscale(0.8)}
.scard.offline::before{background:#64748b}
.scard.offline .scard-temp{color:#64748b}
.scard.offline .tdot{background:#64748b;animation:none}
.scard:hover{border-color:var(--accent);transform:translateX(-2px);box-shadow:0 4px 20px rgba(0,0,0,0.3)}
.scard-top{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:8px}
.scard-name{font-weight:600;font-size:0.9em}
.scard-type{font-size:0.65em;color:var(--text2);margin-top:2px}
.scard-temp{font-size:1.6em;font-weight:800;letter-spacing:-1px}
.scard-bottom{display:flex;justify-content:space-between;align-items:center;margin-top:6px}
.scard-coord{font-size:0.65em;color:var(--text2);font-family:monospace}
.scard-time{font-size:0.65em;color:var(--text2);display:flex;align-items:center;gap:4px}
.scard-time .tdot{width:5px;height:5px;border-radius:50%;background:#22c55e}
.offline-badge{font-size:0.6em;color:#64748b;background:#1e293b;padding:1px 6px;border-radius:4px;margin-left:6px}
.ghost-badge{font-size:0.6em;color:#8b5cf6;background:rgba(139,92,246,0.15);padding:1px 6px;border-radius:4px;margin-left:6px}
.toggle-row{padding:8px 16px;border-bottom:1px solid var(--border);display:flex;align-items:center;gap:8px}
.toggle-label{font-size:0.72em;color:var(--text2);flex:1}
.toggle{position:relative;width:34px;height:18px;cursor:pointer}
.toggle input{opacity:0;width:0;height:0}
.toggle .slider{position:absolute;inset:0;background:var(--border);border-radius:18px;transition:0.3s}
.toggle .slider::before{content:'';position:absolute;width:14px;height:14px;left:2px;bottom:2px;background:var(--text2);border-radius:50%;transition:0.3s}
.toggle input:checked+.slider{background:var(--accent)}
.toggle input:checked+.slider::before{transform:translateX(16px);background:#fff}
.scard-signal{display:flex;align-items:center;gap:6px;margin-top:6px;padding-top:6px;border-top:1px solid var(--border)}
.signal-bars{display:flex;align-items:flex-end;gap:1px;height:14px}
.signal-bars .bar{width:3px;border-radius:1px;background:var(--border);transition:background 0.3s}
.signal-bars .bar.active{background:var(--accent)}
.signal-bars .bar.warn{background:var(--warm)}
.signal-bars .bar.bad{background:var(--hot)}
.signal-val{font-size:0.65em;color:var(--text2);font-family:monospace}
.signal-hops{font-size:0.6em;color:var(--text2);margin-left:auto;background:var(--bg);padding:1px 6px;border-radius:4px}

.sidebar-footer{padding:12px 16px;border-top:1px solid var(--border);display:flex;gap:8px}
.btn{
    flex:1;padding:10px;border:none;border-radius:8px;font-family:'Inter',sans-serif;
    font-size:0.78em;font-weight:600;cursor:pointer;transition:all 0.2s ease;letter-spacing:0.3px;
}
.btn-primary{background:linear-gradient(135deg,var(--accent),var(--accent2));color:#000}
.btn-primary:hover{transform:translateY(-1px);box-shadow:0 4px 15px var(--glow)}
.btn-secondary{background:var(--card2);color:var(--text);border:1px solid var(--border)}
.btn-secondary:hover{border-color:var(--accent)}

.empty{text-align:center;padding:40px 20px;color:var(--text2)}
.empty-icon{font-size:3em;margin-bottom:12px;opacity:0.3}
.empty h3{font-size:0.95em;margin-bottom:6px;color:var(--text)}
.empty p{font-size:0.78em;line-height:1.5}

.leaflet-popup-content-wrapper{background:var(--card);color:var(--text);border-radius:12px;border:1px solid var(--border);box-shadow:0 8px 30px rgba(0,0,0,0.5)}
.leaflet-popup-tip{background:var(--card)}
.popup{padding:4px}
.popup-id{font-weight:700;font-size:1em;margin-bottom:2px}
.popup-type{font-size:0.75em;color:var(--text2);margin-bottom:8px}
.popup-temp{font-size:2.2em;font-weight:800;letter-spacing:-1px;margin-bottom:4px}
.popup-time{font-size:0.7em;color:var(--text2)}

.minichart{display:flex;align-items:flex-end;gap:1px;height:30px;margin-top:8px}
.minibar{flex:1;min-width:2px;max-width:4px;border-radius:1px 1px 0 0;transition:height 0.3s ease}

.sidebar-tabs{display:flex;border-bottom:1px solid var(--border)}
.sidebar-tab{flex:1;padding:8px 4px;text-align:center;font-size:0.7em;font-weight:600;color:var(--text2);cursor:pointer;border-bottom:2px solid transparent;transition:all 0.2s}
.sidebar-tab.active{color:var(--accent);border-bottom-color:var(--accent)}
.sidebar-tab:hover{color:var(--text)}
.tab-content{display:none;flex:1;overflow-y:auto;padding:12px 16px}
.tab-content.active{display:block}

.alert-banner{padding:10px 16px;background:rgba(239,71,111,0.1);border-bottom:1px solid rgba(239,71,111,0.3);display:none;align-items:center;gap:8px;font-size:0.75em;color:var(--hot);animation:alertPulse 2s infinite}
@keyframes alertPulse{0%,100%{opacity:1}50%{opacity:0.7}}
.alert-banner .alert-close{margin-left:auto;cursor:pointer;opacity:0.7;font-size:1em}

.alert-config{background:var(--card2);border:1px solid var(--border);border-radius:10px;padding:14px;margin-bottom:10px}
.alert-config label{font-size:0.72em;color:var(--text2);display:block;margin-bottom:4px}
.alert-config input[type=number]{width:100%;padding:6px 10px;background:var(--bg);border:1px solid var(--border);border-radius:6px;color:var(--text);font-family:Inter,sans-serif;font-size:0.85em;margin-bottom:8px}
.alert-config input[type=number]:focus{outline:none;border-color:var(--accent)}
.alert-row{display:flex;gap:8px}
.alert-row>div{flex:1}

.health-card{background:var(--card2);border:1px solid var(--border);border-radius:10px;padding:12px 14px;margin-bottom:8px}
.health-card-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px}
.health-card-name{font-weight:600;font-size:0.85em}
.health-status{font-size:0.65em;padding:2px 8px;border-radius:10px;font-weight:600}
.health-status.on{background:rgba(6,214,160,0.15);color:var(--accent)}
.health-status.off{background:rgba(100,116,139,0.15);color:#64748b}
.health-grid{display:grid;grid-template-columns:1fr 1fr;gap:6px}
.health-item{font-size:0.7em;color:var(--text2)}
.health-item .hval{color:var(--text);font-weight:600;font-family:monospace}

.chart-modal{display:none;position:fixed;inset:0;background:rgba(0,0,0,0.7);z-index:2000;align-items:center;justify-content:center}
.chart-modal.active{display:flex}
.chart-box{background:var(--card);border:1px solid var(--border);border-radius:14px;padding:20px;width:90%;max-width:700px;max-height:80vh}
.chart-box canvas{width:100%!important;height:300px!important}
.chart-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:16px}
.chart-header h3{font-size:1em;font-weight:600}
.chart-close{background:none;border:none;color:var(--text2);font-size:1.2em;cursor:pointer}
.chart-time-range{display:flex;gap:4px;margin-bottom:12px;flex-wrap:wrap}
.chart-time-btn{padding:4px 10px;border:1px solid var(--border);border-radius:6px;background:var(--card2);color:var(--text2);font-family:Inter,sans-serif;font-size:0.7em;cursor:pointer;transition:all 0.2s}
.chart-time-btn.active{border-color:var(--accent);color:var(--accent);background:rgba(6,214,160,0.1)}
.chart-time-btn:hover{border-color:var(--accent)}

.export-row{padding:8px 16px;border-bottom:1px solid var(--border)}
.btn-export{width:100%;padding:8px;border:1px solid var(--border);border-radius:8px;background:var(--card2);color:var(--text);font-family:Inter,sans-serif;font-size:0.72em;font-weight:500;cursor:pointer;display:flex;align-items:center;justify-content:center;gap:6px;transition:all 0.2s}
.btn-export:hover{border-color:var(--accent);color:var(--accent)}

.leaflet-control-layers{background:var(--card)!important;color:var(--text)!important;border:1px solid var(--border)!important;border-radius:8px!important}
.leaflet-control-layers label{color:var(--text)!important;font-size:0.8em}
.leaflet-control-layers-separator{border-top-color:var(--border)!important}

.mobile-toggle{display:none;position:fixed;bottom:20px;right:20px;z-index:1100;width:50px;height:50px;border-radius:50%;background:linear-gradient(135deg,var(--accent),var(--accent2));border:none;color:#000;font-size:1.4em;cursor:pointer;box-shadow:0 4px 20px var(--glow);transition:transform 0.2s}
.mobile-toggle:active{transform:scale(0.9)}
.mobile-close{display:none;position:absolute;top:12px;right:12px;background:none;border:none;color:var(--text2);font-size:1.3em;cursor:pointer;z-index:1101}

.avg-section{margin-top:10px}
.avg-card{background:var(--card2);border:1px solid var(--border);border-radius:10px;padding:12px 14px;margin-bottom:8px;cursor:pointer;transition:all 0.2s}
.avg-card:hover{border-color:var(--accent)}
.avg-card-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:6px}
.avg-card-name{font-weight:600;font-size:0.85em}
.avg-card-val{font-size:1.1em;font-weight:700}
.avg-grid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:4px}
.avg-item{font-size:0.68em;color:var(--text2);text-align:center}
.avg-item .av{display:block;font-weight:600;font-family:monospace;font-size:1.1em}
.avg-item .av.cool{color:var(--cool)}
.avg-item .av.warm{color:var(--warm)}
.avg-item .av.hot{color:var(--hot)}

.notif-row{padding:8px 16px;border-bottom:1px solid var(--border)}
.btn-notif{width:100%;padding:8px;border:1px solid var(--border);border-radius:8px;background:var(--card2);color:var(--text);font-family:Inter,sans-serif;font-size:0.72em;font-weight:500;cursor:pointer;display:flex;align-items:center;justify-content:center;gap:6px;transition:all 0.2s}
.btn-notif:hover{border-color:var(--accent);color:var(--accent)}
.btn-notif.active{border-color:var(--accent);color:var(--accent);background:rgba(6,214,160,0.08)}

.config-section{margin-bottom:16px}
.config-section-title{font-size:0.8em;font-weight:600;color:var(--accent);margin-bottom:10px;padding-bottom:6px;border-bottom:1px solid var(--border)}
.config-row{display:flex;align-items:center;justify-content:space-between;margin-bottom:10px}
.config-label{font-size:0.72em;color:var(--text2)}
.config-value{font-size:0.72em;color:var(--text);font-weight:600;min-width:40px;text-align:right}
.config-slider{width:120px;accent-color:var(--accent);cursor:pointer}
.config-btn{width:100%;padding:8px;border:1px solid var(--border);border-radius:8px;background:var(--card2);color:var(--text);font-family:Inter,sans-serif;font-size:0.72em;font-weight:500;cursor:pointer;display:flex;align-items:center;justify-content:center;gap:6px;transition:all 0.2s;margin-bottom:6px}
.config-btn:hover{border-color:var(--accent);color:var(--accent)}
.config-btn.active{border-color:#8b5cf6;color:#8b5cf6;background:rgba(139,92,246,0.1)}
.config-btn.danger{border-color:var(--hot);color:var(--hot)}
.config-btn.danger:hover{background:rgba(239,71,111,0.1)}

.ghost-list{margin-top:8px}
.ghost-item{display:flex;align-items:center;justify-content:space-between;padding:6px 10px;background:var(--bg);border-radius:6px;margin-bottom:4px;font-size:0.7em;cursor:pointer;transition:all 0.2s}
.ghost-item:hover{background:var(--card2)}
.ghost-item-name{color:var(--text);font-weight:500}
.ghost-item-status{font-size:0.85em;padding:1px 6px;border-radius:4px;font-weight:600}
.ghost-item-status.on{color:#8b5cf6;background:rgba(139,92,246,0.15)}
.ghost-item-status.off{color:#64748b;background:rgba(100,116,139,0.15)}

@keyframes dashFlow{to{stroke-dashoffset:-20}}
.animated-line{animation:dashFlow 1s linear infinite}

.marker-cluster-custom{background:rgba(6,214,160,0.3);border-radius:50%}
.marker-cluster-custom div{background:linear-gradient(135deg,var(--accent),var(--accent2));width:32px;height:32px;border-radius:50%;display:flex;align-items:center;justify-content:center;color:#fff;font-weight:700;font-size:11px;font-family:Inter,sans-serif}

.tc-cold{color:var(--cold)}.tc-cool{color:var(--cool)}.tc-warm{color:var(--warm)}.tc-hot{color:var(--hot)}

@media(max-width:768px){
    .stats{display:none}
    .header{padding:10px 16px}
    .header .status{display:none}
    .logo h1{font-size:0.95em}
    .logo-sub{display:none}
    .mobile-toggle{display:flex;align-items:center;justify-content:center}
    .sidebar{position:fixed;top:0;right:-100%;width:85%;max-width:360px;height:100vh;z-index:1100;transition:right 0.3s ease;box-shadow:-4px 0 30px rgba(0,0,0,0.5)}
    .sidebar.open{right:0}
    .sidebar.open .mobile-close{display:block}
    .chart-box{width:95%;padding:14px}
    .chart-box canvas{height:220px!important}
}
</style>
</head>
<body>

<div class="splash" id="splash">
    <img src="/static/logo_inicio.png" alt="MET Red de Estaciones Meteorologicas">
    <div class="splash-text">Iniciando sistema de monitoreo...</div>
    <div class="splash-loader"><div class="splash-loader-bar"></div></div>
</div>

<div class="header">
    <div class="logo">
        <img src="/static/logo_header.png" alt="MET." class="logo-img">
        <div>
            <h1><span>MET.</span> Red Ambiental</h1>
            <div class="logo-sub">RED DE ESTACIONES METEOROLOGICAS &bull; ESP32 MESH</div>
        </div>
    </div>
    <div class="stats">
        <div class="stat estaciones"><div class="val" id="s-total">0</div><div class="lbl">Estaciones</div></div>
        <div class="stat promedio"><div class="val" id="s-prom">--</div><div class="lbl">Promedio</div></div>
        <div class="stat minima"><div class="val" id="s-min">--</div><div class="lbl">Min</div></div>
        <div class="stat maxima"><div class="val" id="s-max">--</div><div class="lbl">Max</div></div>
    </div>
    <div class="status"><div class="dot"></div><span id="status-text">Conectado</span></div>
</div>

<div class="main">
    <div id="map"></div>
    <div class="sidebar" id="sidebar">
        <button class="mobile-close" onclick="toggleSidebar()">&times;</button>
        <div class="sidebar-header">
            <h2>Estaciones</h2>
            <div class="badge" id="badge-count">0</div>
        </div>
        <div id="alert-banner" class="alert-banner">
            <span>&#9888;</span>
            <span id="alert-msg">Alerta</span>
            <span class="alert-close" onclick="document.getElementById('alert-banner').style.display='none'">&times;</span>
        </div>
        <div class="sidebar-tabs">
            <div class="sidebar-tab active" onclick="switchTab('tab-stations',this)">Estaciones</div>
            <div class="sidebar-tab" onclick="switchTab('tab-alerts',this)">Alertas</div>
            <div class="sidebar-tab" onclick="switchTab('tab-health',this)">Red</div>
            <div class="sidebar-tab" onclick="switchTab('tab-avg',this)">Promedios</div>
            <div class="sidebar-tab" onclick="switchTab('tab-config',this)">Config</div>
        </div>

        <div id="tab-stations" class="tab-content active">
            <div class="toggle-row">
                <span class="toggle-label">Marcadores</span>
                <label class="toggle"><input type="checkbox" id="toggle-markers" checked onchange="toggleMarkers()"><span class="slider"></span></label>
            </div>
            <div class="toggle-row">
                <span class="toggle-label">Lineas</span>
                <label class="toggle"><input type="checkbox" id="toggle-lines" checked onchange="toggleLines()"><span class="slider"></span></label>
            </div>
            <div class="toggle-row">
                <span class="toggle-label">Heatmap</span>
                <label class="toggle"><input type="checkbox" id="toggle-heatmap" checked onchange="toggleHeatmap()"><span class="slider"></span></label>
            </div>
            <div class="export-row">
                <button class="btn-export" onclick="exportarCSV()">&#128196; Exportar CSV (24h)</button>
            </div>
            <div class="notif-row">
                <button class="btn-notif" id="btn-notif" onclick="toggleNotificaciones()">&#128276; Activar notificaciones</button>
            </div>
            <div class="stations" id="station-list">
                <div class="empty"><div class="empty-icon">&#128225;</div><h3>Esperando estaciones...</h3><p>Enciende tus ESP32 o carga datos de demo.</p></div>
            </div>
        </div>

        <div id="tab-alerts" class="tab-content">
            <div class="alert-config">
                <h3 style="font-size:0.85em;margin-bottom:10px">Configurar alertas</h3>
                <div class="alert-row">
                    <div><label>Temp. minima</label><input type="number" id="alert-min" value="0" step="0.5" onchange="guardarAlertas()"></div>
                    <div><label>Temp. maxima</label><input type="number" id="alert-max" value="55" step="0.5" onchange="guardarAlertas()"></div>
                </div>
                <div style="display:flex;align-items:center;gap:8px;margin-top:4px">
                    <label class="toggle"><input type="checkbox" id="alert-activa" checked onchange="guardarAlertas()"><span class="slider"></span></label>
                    <span style="font-size:0.72em;color:var(--text2)">Alertas activas</span>
                </div>
            </div>
            <div id="alert-list"></div>
        </div>

        <div id="tab-health" class="tab-content"><div id="health-list"><div class="empty"><div class="empty-icon">&#128225;</div><h3>Sin datos de salud</h3></div></div></div>

        <div id="tab-avg" class="tab-content"><div class="avg-section" id="avg-list"><div class="empty"><div class="empty-icon">&#128202;</div><h3>Sin promedios</h3><p>Carga datos para ver promedios.</p></div></div></div>

        <div id="tab-config" class="tab-content">
            <div class="config-section">
                <div class="config-section-title">&#128204; Marcadores</div>
                <div class="config-row">
                    <span class="config-label">Tamano marcador</span>
                    <input type="range" class="config-slider" id="cfg-marker-size" min="20" max="60" value="38" oninput="updateConfig()">
                    <span class="config-value" id="cfg-marker-size-val">38px</span>
                </div>
            </div>
            <div class="config-section">
                <div class="config-section-title">&#127777; Heatmap</div>
                <div class="config-row">
                    <span class="config-label">Radio</span>
                    <input type="range" class="config-slider" id="cfg-heat-radius" min="15" max="120" value="50" oninput="updateConfig()">
                    <span class="config-value" id="cfg-heat-radius-val">50</span>
                </div>
                <div class="config-row">
                    <span class="config-label">Blur</span>
                    <input type="range" class="config-slider" id="cfg-heat-blur" min="10" max="80" value="35" oninput="updateConfig()">
                    <span class="config-value" id="cfg-heat-blur-val">35</span>
                </div>
                <div class="config-row">
                    <span class="config-label">Opacidad</span>
                    <input type="range" class="config-slider" id="cfg-heat-opacity" min="10" max="90" value="40" oninput="updateConfig()">
                    <span class="config-value" id="cfg-heat-opacity-val">40%</span>
                </div>
            </div>
            <div class="config-section">
                <div class="config-section-title">&#128123; Nodos Fantasma</div>
                <button class="config-btn" id="btn-ghost-toggle" onclick="toggleGhosts()">&#128123; Activar nodos fantasma (14)</button>
                <button class="config-btn danger" id="btn-ghost-clear" onclick="clearGhosts()" style="display:none">&#10060; Desactivar todos</button>
                <div style="margin-top:8px;padding:8px;background:var(--card-bg);border:1px solid var(--border);border-radius:8px">
                    <div style="font-size:0.75em;font-weight:600;color:var(--text2);margin-bottom:6px">Agregar nodo fantasma</div>
                    <div style="display:flex;gap:4px;margin-bottom:4px">
                        <input type="text" id="ghost-new-id" placeholder="ID (ej: GHOST-15)" style="flex:1;padding:4px 6px;font-size:0.72em;background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:4px">
                    </div>
                    <div style="display:flex;gap:4px;margin-bottom:4px">
                        <input type="number" id="ghost-new-lat" placeholder="Latitud" step="0.0001" style="flex:1;padding:4px 6px;font-size:0.72em;background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:4px">
                        <input type="number" id="ghost-new-lon" placeholder="Longitud" step="0.0001" style="flex:1;padding:4px 6px;font-size:0.72em;background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:4px">
                    </div>
                    <button class="config-btn" onclick="crearGhostCustom()" style="font-size:0.72em;padding:5px 10px">&#10133; Agregar</button>
                </div>
                <div class="ghost-list" id="ghost-list"></div>
            </div>
        </div>

        <div class="sidebar-footer">
            <button class="btn btn-primary" onclick="actualizar()">&#8635; Actualizar</button>
            <button class="btn btn-secondary" onclick="cargarDemo()">Demo</button>
        </div>
    </div>
</div>

<button class="mobile-toggle" onclick="toggleSidebar()">&#9776;</button>

<div class="chart-modal" id="chart-modal" onclick="if(event.target===this)cerrarGrafico()">
    <div class="chart-box">
        <div class="chart-header">
            <h3 id="chart-title">Historial</h3>
            <button class="chart-close" onclick="cerrarGrafico()">&times;</button>
        </div>
        <div class="chart-time-range" id="chart-time-range">
            <button class="chart-time-btn" onclick="changeChartRange(1,this)">1h</button>
            <button class="chart-time-btn" onclick="changeChartRange(6,this)">6h</button>
            <button class="chart-time-btn" onclick="changeChartRange(12,this)">12h</button>
            <button class="chart-time-btn active" onclick="changeChartRange(24,this)">24h</button>
            <button class="chart-time-btn" onclick="changeChartRange(48,this)">48h</button>
            <button class="chart-time-btn" onclick="changeChartRange(168,this)">7d</button>
        </div>
        <canvas id="chart-canvas"></canvas>
    </div>
</div>

<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="https://unpkg.com/leaflet.heat@0.2.0/dist/leaflet-heat.js"></script>
<script src="https://unpkg.com/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<script>
function hideSplash(){var el=document.getElementById('splash');if(el)el.classList.add('hidden');}
hideSplash();
setTimeout(hideSplash,800);

const API=window.location.origin;
const darkTile=L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',{attribution:'CartoDB',maxZoom:19});
const satTile=L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',{attribution:'Esri'});
const topoTile=L.tileLayer('https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png',{attribution:'OpenTopoMap'});
const streetTile=L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{attribution:'OSM'});
const map=L.map('map',{center:[-33.3919,-56.5189],zoom:15,layers:[darkTile],zoomControl:true});
L.control.layers({'Oscuro':darkTile,'Satelite':satTile,'Topografico':topoTile,'Calles':streetTile},{},{position:'topright'}).addTo(map);

let heatLayer=null,polylines=[],primeraCarga=true;
let showMarkers=true,showLines=true,showHeatmap=true;
let alertConfig={temp_min:0,temp_max:55,activa:true};
let chartInstance=null,notifEnabled=false;
let currentChartNode=null,currentChartRange=24,chartRefreshTimer=null;
let ghostsActive=false;
let cfgMarkerSize=38,cfgHeatRadius=50,cfgHeatBlur=35,cfgHeatOpacity=0.4;

const clusterGroup=L.markerClusterGroup({
    maxClusterRadius:60,spiderfyOnMaxZoom:true,showCoverageOnHover:false,zoomToBoundsOnClick:true,
    iconCreateFunction:function(cluster){
        var markers=cluster.getAllChildMarkers();
        var sum=0,cnt=0;
        markers.forEach(function(m){if(m._tempVal!==undefined){sum+=m._tempVal;cnt++;}});
        var avg=cnt>0?Math.round(sum/cnt):0;
        var c=tempColorHex(avg);
        return L.divIcon({
            html:'<div style="background:'+c+';width:40px;height:40px;border-radius:50%;display:flex;align-items:center;justify-content:center;color:#fff;font-weight:700;font-size:12px;font-family:Inter,sans-serif;border:3px solid rgba(255,255,255,0.3);box-shadow:0 2px 15px rgba(0,0,0,0.5)"><span>'+avg+'&deg;</span><span style="position:absolute;bottom:-4px;right:-4px;background:#111827;color:#e2e8f0;font-size:9px;padding:1px 4px;border-radius:4px;font-weight:600">'+cnt+'</span></div>',
            className:'marker-cluster-custom',iconSize:[44,44],iconAnchor:[22,22]
        });
    }
});
map.addLayer(clusterGroup);

function tempColorHex(t){if(t<20)return'#118ab2';if(t<30)return'#06d6a0';if(t<40)return'#ffd166';return'#ef476f';}
function tempClass(t){if(t<20)return'tc-cold';if(t<30)return'tc-cool';if(t<40)return'tc-warm';return'tc-hot';}
function crearIconoOffline(temp,sz){
    sz=sz||cfgMarkerSize;
    return L.divIcon({className:'',
        html:'<div style="position:relative;background:#475569;width:'+sz+'px;height:'+sz+'px;border-radius:50%;display:flex;align-items:center;justify-content:center;color:#94a3b8;font-weight:700;font-size:'+(sz*0.29)+'px;font-family:Inter,sans-serif;border:2px solid #334155;box-shadow:0 2px 10px rgba(0,0,0,0.5);opacity:0.6;filter:grayscale(0.5)">'+Math.round(temp)+'&deg;</div>',
        iconSize:[sz,sz],iconAnchor:[sz/2,sz/2]});
}
function crearIcono(temp,esRoot,isGhost,sz){
    sz=sz||cfgMarkerSize;
    var c=isGhost?'#8b5cf6':tempColorHex(temp);
    var rootSz=esRoot?sz+6:sz;var fs=rootSz*0.29;
    var brd=esRoot?'3px solid #06d6a0':isGhost?'2px solid rgba(139,92,246,0.5)':'2px solid rgba(255,255,255,0.3)';
    var shd=esRoot?'0 0 20px rgba(6,214,160,0.5)':isGhost?'0 0 15px rgba(139,92,246,0.3)':'0 2px 10px rgba(0,0,0,0.5)';
    var rb=esRoot?'<div style="position:absolute;top:-6px;right:-6px;background:#06d6a0;color:#000;font-size:8px;font-weight:800;padding:1px 4px;border-radius:4px;">ROOT</div>':'';
    var gb=isGhost?'<div style="position:absolute;bottom:-4px;right:-4px;background:#8b5cf6;color:#fff;font-size:7px;font-weight:700;padding:1px 3px;border-radius:3px;">G</div>':'';
    return L.divIcon({className:'',
        html:'<div style="position:relative;background:'+c+';width:'+rootSz+'px;height:'+rootSz+'px;border-radius:50%;display:flex;align-items:center;justify-content:center;color:#fff;font-weight:700;font-size:'+fs+'px;font-family:Inter,sans-serif;border:'+brd+';box-shadow:'+shd+';transition:all 0.3s">'+Math.round(temp)+'&deg;'+rb+gb+'</div>',
        iconSize:[rootSz,rootSz],iconAnchor:[rootSz/2,rootSz/2]});
}
function miniChart(datos){
    if(!datos||datos.length<2)return'';
    var vals=datos.slice(-20).map(function(d){return d.temp;});
    var mn=Math.min.apply(null,vals),mx=Math.max.apply(null,vals),rg=mx-mn||1;
    var b='';vals.forEach(function(v){var h=Math.max(3,((v-mn)/rg)*28);b+='<div class="minibar" style="height:'+h+'px;background:'+tempColorHex(v)+'"></div>';});
    return'<div class="minichart">'+b+'</div>';
}
function signalBars(rssi){
    if(rssi===null||rssi===undefined)return '';

    var abs=Math.abs(rssi);
    var level=0,cls='active';

    if(abs<=50){
        level=4;
        cls='active';
    }else if(abs<=65){
        level=3;
        cls='active';
    }else if(abs<=75){
        level=2;
        cls='warn';
    }else{
        level=1;
        cls='bad';
    }

    var heights=[4,7,10,14];
    var bars='';

    for(var i=0;i<4;i++){
        var on=i<level;
        bars+='<div class="bar'+(on?' '+cls:'')+'" style="height:'+heights[i]+'px"></div>';
    }

    return '<div class="scard-signal">' +
           '<div class="signal-bars">'+bars+'</div>' +
           '<span class="signal-val">'+rssi+' dBm</span>' +
           '</div>';
}
function hopsBadge(hops){if(hops===null||hops===undefined||hops===0)return'';return'<span class="signal-hops">'+hops+' salto'+(hops>1?'s':'')+'</span>';}

function updateConfig(){
    cfgMarkerSize=parseInt(document.getElementById('cfg-marker-size').value);
    cfgHeatRadius=parseInt(document.getElementById('cfg-heat-radius').value);
    cfgHeatBlur=parseInt(document.getElementById('cfg-heat-blur').value);
    cfgHeatOpacity=parseInt(document.getElementById('cfg-heat-opacity').value)/100;
    document.getElementById('cfg-marker-size-val').textContent=cfgMarkerSize+'px';
    document.getElementById('cfg-heat-radius-val').textContent=cfgHeatRadius;
    document.getElementById('cfg-heat-blur-val').textContent=cfgHeatBlur;
    document.getElementById('cfg-heat-opacity-val').textContent=document.getElementById('cfg-heat-opacity').value+'%';
    actualizar();
}

async function toggleGhosts(){
    if(!ghostsActive){
        try{await fetch(API+'/api/ghost/activar',{method:'POST'});ghostsActive=true;
        document.getElementById('btn-ghost-toggle').classList.add('active');
        document.getElementById('btn-ghost-toggle').innerHTML='&#128123; Nodos fantasma ACTIVOS';
        document.getElementById('btn-ghost-clear').style.display='block';
        await actualizar();actualizarGhostList();}catch(e){console.error(e);}
    }
}
async function clearGhosts(){
    try{await fetch(API+'/api/ghost/desactivar',{method:'POST'});ghostsActive=false;
    document.getElementById('btn-ghost-toggle').classList.remove('active');
    document.getElementById('btn-ghost-toggle').innerHTML='&#128123; Activar nodos fantasma (14)';
    document.getElementById('btn-ghost-clear').style.display='none';
    document.getElementById('ghost-list').innerHTML='';await actualizar();}catch(e){console.error(e);}
}
async function toggleSingleGhost(gid){
    try{await fetch(API+'/api/ghost/toggle/'+gid,{method:'POST'});await actualizar();actualizarGhostList();}catch(e){console.error(e);}
}
async function crearGhostCustom(){
    var gid=document.getElementById('ghost-new-id').value.trim();
    var lat=document.getElementById('ghost-new-lat').value;
    var lon=document.getElementById('ghost-new-lon').value;
    if(!gid||!lat||!lon){alert('Completa ID, Latitud y Longitud');return;}
    try{
        var r=await fetch(API+'/api/ghost/crear',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:gid,lat:parseFloat(lat),lon:parseFloat(lon)})});
        var d=await r.json();
        if(d.ok){ghostsActive=true;document.getElementById('btn-ghost-toggle').classList.add('active');document.getElementById('btn-ghost-toggle').innerHTML='&#128123; Nodos fantasma ACTIVOS';document.getElementById('btn-ghost-clear').style.display='block';document.getElementById('ghost-new-id').value='';document.getElementById('ghost-new-lat').value='';document.getElementById('ghost-new-lon').value='';await actualizar();actualizarGhostList();}
        else{alert(d.error||'Error al crear nodo');}
    }catch(e){console.error(e);alert('Error de conexion');}
}
async function actualizarGhostList(){
    if(!ghostsActive)return;
    try{
        var r=await fetch(API+'/api/datos');
        var datos=await r.json();
        var ghosts=Object.values(datos).filter(function(n){return n.ghost;});
        if(ghosts.length===0){document.getElementById('ghost-list').innerHTML='';return;}
        var h='';
        ghosts.forEach(function(g){
            var on=g.online!==false;
           h += `
  <div class="ghost-item" onclick="toggleSingleGhost('${g.id}')">
    <span class="ghost-item-name">${g.id}</span>
    <span class="ghost-item-status ${on ? 'on' : 'off'}">
      ${on ? 'ON' : 'OFF'}
    </span>
  </div>
`;});
        document.getElementById('ghost-list').innerHTML=h;
    }catch(e){console.error(e);}
}

function toggleHeatmap(){showHeatmap=document.getElementById('toggle-heatmap').checked;if(heatLayer){if(showHeatmap)map.addLayer(heatLayer);else map.removeLayer(heatLayer);}}

async function actualizar(){
    try{
        var responses=await Promise.all([fetch(API+'/api/datos'),fetch(API+'/api/resumen')]);
        var datos=await responses[0].json();var res=await responses[1].json();
        document.getElementById('s-total').textContent=res.total;
        document.getElementById('s-prom').textContent=res.promedio!==null?res.promedio+'°':'--';
        document.getElementById('s-min').textContent=res.minima!==null?res.minima+'°':'--';
        document.getElementById('s-max').textContent=res.maxima!==null?res.maxima+'°':'--';
        document.getElementById('badge-count').textContent=res.total;
        document.getElementById('status-text').textContent='Actualizado '+new Date().toLocaleTimeString();

        if(heatLayer){map.removeLayer(heatLayer);heatLayer=null;}
        clusterGroup.clearLayers();
        polylines.forEach(function(p){map.removeLayer(p);});polylines=[];

        var nodos=Object.values(datos);
        if(nodos.length===0){document.getElementById('station-list').innerHTML='<div class="empty"><div class="empty-icon">&#128225;</div><h3>Sin estaciones</h3><p>Enciende tus ESP32 o carga demo.</p></div>';return;}

        var onlineNodos=nodos.filter(function(n){return n.online!==false;});
        var temps=onlineNodos.map(function(n){return n.temp;});
        var tMin=temps.length>0?Math.min.apply(null,temps):0;
        var tMax=temps.length>0?Math.max.apply(null,temps):60;
        var tRange=tMax-tMin;if(tRange<5)tRange=5;
        var hp=onlineNodos.map(function(n){return[n.lat,n.lon,Math.max(0.05,(n.temp-tMin)/tRange)];});
        var effectiveBlur=Math.max(cfgHeatBlur,Math.round(cfgHeatRadius*0.45));
        if(hp.length>0){
            heatLayer=L.heatLayer(hp,{radius:cfgHeatRadius,blur:effectiveBlur,maxZoom:18,minOpacity:cfgHeatOpacity,
                gradient:{0.0:'#118ab2',0.25:'#06d6a0',0.5:'#ffd166',0.75:'#ef476f',1.0:'#9b2226'}});
            if(showHeatmap)heatLayer.addTo(map);
        }

        var realNodos=nodos.filter(function(n){return!n.ghost;});
        if(realNodos.length>1){
            var root=realNodos.find(function(n){return n.id==='MET-001'||(n.tipo&&n.tipo.includes('ROOT'));})||realNodos[0];
            realNodos.forEach(function(n){if(n.id!==root.id){
                var isOn=n.online!==false;var lnC=isOn?'rgba(6,214,160,0.4)':'rgba(100,116,139,0.2)';
                var pl=L.polyline([[root.lat,root.lon],[n.lat,n.lon]],{color:lnC,weight:2,dashArray:'8,8',className:isOn?'animated-line':''});
                if(showLines)pl.addTo(map);polylines.push(pl);
            }});
        }
        var ghostNodos=nodos.filter(function(n){return n.ghost&&n.online!==false;});
        if(ghostNodos.length>0){
            var closestReal=realNodos.find(function(n){return n.online!==false;});
            if(closestReal){ghostNodos.forEach(function(g){
                var pl=L.polyline([[closestReal.lat,closestReal.lon],[g.lat,g.lon]],{color:'rgba(139,92,246,0.25)',weight:1.5,dashArray:'6,6',className:'animated-line'});
                if(showLines)pl.addTo(map);polylines.push(pl);
            });}
        }

        var histPromises=realNodos.map(function(n){return fetch(API+'/api/historial/'+encodeURIComponent(n.id)+'?limit=20').then(function(r){return r.json();}).catch(function(){return[];});});
        var hist=await Promise.all(histPromises);
        var histMap={};realNodos.forEach(function(n,i){histMap[n.id]=hist[i];});

        nodos.forEach(function(n){
            var esRoot=n.id==='MET-001'||(n.tipo&&n.tipo.includes('ROOT'));
            var isOn=n.online!==false;var isGhost=n.ghost||false;
            var iconFn=isOn?crearIcono(n.temp,esRoot,isGhost):crearIconoOffline(n.temp);
            var rssiH=n.rssi!=null?'<div style="font-size:0.75em;color:#94a3b8;margin-top:4px">Senal: '+n.rssi+' dBm'+(n.hops?' | '+n.hops+' salto'+(n.hops>1?'s':''):'')+'</div>':'';
            var stH=!isOn?'<div style="font-size:0.7em;color:#64748b;margin-top:4px">DESCONECTADO</div>':'';
            var gH=isGhost?'<div style="font-size:0.7em;color:#8b5cf6;margin-top:2px">NODO FANTASMA</div>':'';
            var mk=L.marker([n.lat,n.lon],{icon:iconFn}).bindPopup('<div class="popup"><div class="popup-id">'+n.id+'</div><div class="popup-type">'+(n.tipo||'ESP32-interno')+(esRoot?' - GATEWAY':'')+'</div><div class="popup-temp '+tempClass(n.temp)+'">'+n.temp+'&deg;C</div>'+rssiH+gH+stH+'<div class="popup-time">Actualizado: '+(n.hora||'--')+'</div>'+miniChart(histMap[n.id]||[])+'</div>',{maxWidth:220});
            mk._tempVal=n.temp;if(showMarkers)clusterGroup.addLayer(mk);
        });

        var lH='';nodos.sort(function(a,b){return a.id.localeCompare(b.id);});
        nodos.forEach(function(n){
            var esRoot=n.id==='MET-001'||(n.tipo&&n.tipo.includes('ROOT'));
            var isOn=n.online!==false;var isGhost=n.ghost||false;
            var offCls=isOn?'':'offline';var typeCls=isGhost?'ghost':(esRoot?'root':'nodo');
            lH+='<div class="scard '+typeCls+' '+offCls+'" onclick="map.setView(['+n.lat+','+n.lon+'],17)">'
                +'<div class="scard-top"><div><div class="scard-name">'+n.id+(esRoot?' <span style="color:#06d6a0;font-size:0.7em">ROOT</span>':'')+(isGhost?'<span class="ghost-badge">FANTASMA</span>':'')+(isOn?'':'<span class="offline-badge">OFFLINE</span>')+'</div>'
                +'<div class="scard-type">'+(n.tipo||'ESP32-interno')+'</div></div>'
                +'<div class="scard-temp '+tempClass(n.temp)+'">'+n.temp+'&deg;</div></div>'
                +(!isGhost
  ? `<div style="cursor:pointer" onclick="event.stopPropagation();abrirGrafico('${n.id}')">
      ${miniChart(histMap[n.id]||[])}
     </div>`
  : '')
                +signalBars(n.rssi)+hopsBadge(n.hops)+(n.rssi!=null?'</div>':'')
                +'<div class="scard-bottom"><div class="scard-coord">'+n.lat.toFixed(4)+', '+n.lon.toFixed(4)+'</div>'
                +'<div class="scard-time"><div class="tdot"></div>'+(n.hora||'--')+'</div></div></div>';
        });
        document.getElementById('station-list').innerHTML=lH;
        checkAlerts(nodos);

        if(primeraCarga&&nodos.length>0){
            if(nodos.length===1)map.setView([nodos[0].lat,nodos[0].lon],16);
            else map.fitBounds(L.latLngBounds(nodos.map(function(n){return[n.lat,n.lon];})).pad(0.3));
            primeraCarga=false;
        }
    }catch(err){console.error('Error:',err);document.getElementById('status-text').textContent='Error de conexion';}
}

async function cargarDemo(){try{await fetch(API+'/api/demo',{method:'POST'});await actualizar();}catch(e){console.error(e);}}

function toggleMarkers(){showMarkers=document.getElementById('toggle-markers').checked;if(showMarkers)map.addLayer(clusterGroup);else map.removeLayer(clusterGroup);}
function toggleLines(){showLines=document.getElementById('toggle-lines').checked;polylines.forEach(function(p){if(showLines)p.addTo(map);else map.removeLayer(p);});}

function switchTab(tabId,el){
    document.querySelectorAll('.tab-content').forEach(function(t){t.classList.remove('active');});
    document.querySelectorAll('.sidebar-tab').forEach(function(t){t.classList.remove('active');});
    document.getElementById(tabId).classList.add('active');el.classList.add('active');
    if(tabId==='tab-health')actualizarSalud();
    if(tabId==='tab-avg')actualizarPromedios();
    if(tabId==='tab-config'&&ghostsActive)actualizarGhostList();
}

function toggleSidebar(){document.getElementById('sidebar').classList.toggle('open');}

async function cargarAlertConfig(){
    try{var r=await fetch(API+'/api/alertas');alertConfig=await r.json();
    document.getElementById('alert-min').value=alertConfig.temp_min;
    document.getElementById('alert-max').value=alertConfig.temp_max;
    document.getElementById('alert-activa').checked=alertConfig.activa;}catch(e){}
}
async function guardarAlertas(){
    var cfg={temp_min:parseFloat(document.getElementById('alert-min').value)||0,temp_max:parseFloat(document.getElementById('alert-max').value)||55,activa:document.getElementById('alert-activa').checked};
    try{await fetch(API+'/api/alertas',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(cfg)});alertConfig=cfg;}catch(e){}
}
function checkAlerts(nodos){
    if(!alertConfig.activa){document.getElementById('alert-banner').style.display='none';return;}
    var alertas=[];
    nodos.forEach(function(n){if(n.online!==false&&!n.ghost){
        if(n.temp<alertConfig.temp_min)alertas.push(n.id+': '+n.temp+'C (bajo min '+alertConfig.temp_min+')');
        if(n.temp>alertConfig.temp_max)alertas.push(n.id+': '+n.temp+'C (sobre max '+alertConfig.temp_max+')');
    }});
    var banner=document.getElementById('alert-banner');
    if(alertas.length>0){banner.style.display='flex';document.getElementById('alert-msg').textContent=alertas.join(' | ');sendNotification('Alerta Red Ambiental',alertas.join('\\n'));}
    else{banner.style.display='none';}
    var aH='';
    if(alertas.length>0){alertas.forEach(function(a){aH+='<div style="padding:6px 0;border-bottom:1px solid var(--border);color:var(--hot)">'+a+'</div>';});}
    else{aH='<div style="padding:20px;text-align:center;color:var(--accent)">Temperaturas dentro del rango</div>';}
    document.getElementById('alert-list').innerHTML=aH;
}

async function actualizarSalud(){
    try{var r=await fetch(API+'/api/salud');var salud=await r.json();
    if(salud.length===0){document.getElementById('health-list').innerHTML='<div class="empty"><div class="empty-icon">&#128225;</div><h3>Sin datos</h3></div>';return;}
    var h='';salud.forEach(function(s){
        var signalQ=s.rssi?Math.min(100,Math.max(0,2*(s.rssi+100)))+'%':'--';var isGhost=s.ghost||false;
        h+='<div class="health-card"><div class="health-card-header"><span class="health-card-name">'+s.id+(isGhost?' <span style="color:#8b5cf6;font-size:0.8em">&#128123;</span>':'')+'</span>'
            +'<span class="health-status '+(s.online?'on':'off')+'">'+(s.online?'ONLINE':'OFFLINE')+'</span></div>'
            +'<div class="health-grid">'
            +'<div class="health-item">Senal <span class="hval">'+(s.rssi?s.rssi+' dBm':'--')+'</span></div>'
            +'<div class="health-item">Calidad <span class="hval">'+signalQ+'</span></div>'
            +'<div class="health-item">Saltos <span class="hval">'+s.hops+'</span></div>'
            +'<div class="health-item">Edad <span class="hval">'+(s.online?Math.round(s.edad_seg)+'s':'--')+'</span></div>'
            +'<div class="health-item">Total <span class="hval">'+s.lecturas_total+'</span></div>'
            +'<div class="health-item">Ult.hora <span class="hval">'+s.lecturas_1h+'</span></div>'
            +'</div></div>';
    });document.getElementById('health-list').innerHTML=h;}catch(e){console.error(e);}
}

function exportarCSV(){window.open(API+'/api/exportar/csv?horas=24','_blank');}

async function abrirGrafico(nodoId){
    currentChartNode=nodoId;currentChartRange=24;
    document.getElementById('chart-modal').classList.add('active');
    document.getElementById('chart-title').textContent='Historial: '+nodoId;
    var btns=document.querySelectorAll('.chart-time-btn');btns.forEach(function(b){b.classList.remove('active');});
    if(btns[3])btns[3].classList.add('active');
    await cargarDatosGrafico(nodoId,24);
    if(chartRefreshTimer)clearInterval(chartRefreshTimer);
    chartRefreshTimer=setInterval(function(){if(currentChartNode)cargarDatosGrafico(currentChartNode,currentChartRange);},5000);
}
async function changeChartRange(horas,el){
    currentChartRange=horas;document.querySelectorAll('.chart-time-btn').forEach(function(b){b.classList.remove('active');});
    el.classList.add('active');if(currentChartNode)await cargarDatosGrafico(currentChartNode,horas);
}
async function cargarDatosGrafico(nodoId,horas){
    try{var r=await fetch(API+'/api/historial/db/'+encodeURIComponent(nodoId)+'?horas='+horas);var datos=await r.json();
    var labels=datos.map(function(d){try{var dt=new Date(d.timestamp);return dt.getHours()+':'+String(dt.getMinutes()).padStart(2,'0');}catch(e){return'';}});
    var temps=datos.map(function(d){return d.temp;});
    if(chartInstance){chartInstance.destroy();}
    var ctx=document.getElementById('chart-canvas').getContext('2d');
    chartInstance=new Chart(ctx,{type:'line',
        data:{labels:labels,datasets:[{label:'Temperatura (C)',data:temps,borderColor:'#06d6a0',backgroundColor:'rgba(6,214,160,0.1)',fill:true,tension:0.3,pointRadius:temps.length>100?0:2,borderWidth:2}]},
        options:{responsive:true,maintainAspectRatio:false,animation:{duration:0},
            plugins:{legend:{labels:{color:'#e2e8f0'}}},
            scales:{x:{ticks:{color:'#94a3b8',maxTicksLimit:12},grid:{color:'rgba(30,41,59,0.5)'}},y:{ticks:{color:'#94a3b8'},grid:{color:'rgba(30,41,59,0.5)'}}}
        }
    });}catch(e){console.error(e);}
}
function cerrarGrafico(){
    document.getElementById('chart-modal').classList.remove('active');
    if(chartInstance){chartInstance.destroy();chartInstance=null;}
    if(chartRefreshTimer){clearInterval(chartRefreshTimer);chartRefreshTimer=null;}currentChartNode=null;
}

async function toggleNotificaciones(){
    var btn=document.getElementById('btn-notif');
    if(!notifEnabled){
        if(!('Notification' in window)){alert('Tu navegador no soporta notificaciones');return;}
        var perm=await Notification.requestPermission();
        if(perm==='granted'){notifEnabled=true;btn.classList.add('active');btn.innerHTML='&#128276; Notificaciones activas';
        new Notification('Red Ambiental',{body:'Notificaciones activadas.'});}
    }else{notifEnabled=false;btn.classList.remove('active');btn.innerHTML='&#128276; Activar notificaciones';}
}
function sendNotification(title,body){if(notifEnabled&&'Notification' in window&&Notification.permission==='granted'){new Notification(title,{body:body});}}

async function actualizarPromedios(){
    try{var r=await fetch(API+'/api/promedios?horas=24');var data=await r.json();
    var nodos=Object.keys(data);
    if(nodos.length===0){document.getElementById('avg-list').innerHTML='<div class="empty"><div class="empty-icon">&#128202;</div><h3>Sin datos</h3><p>Carga datos para ver promedios.</p></div>';return;}
    var h='';nodos.forEach(function(nid){
        var entries=data[nid];if(!entries||entries.length===0)return;
        var allProms=entries.map(function(e){return e.prom;});
        var gP=(allProms.reduce(function(a,b){return a+b;},0)/allProms.length).toFixed(1);
        var gMin=Math.min.apply(null,entries.map(function(e){return e.min;})).toFixed(1);
        var gMax=Math.max.apply(null,entries.map(function(e){return e.max;})).toFixed(1);
        var tL=entries.reduce(function(a,e){return a+e.lecturas;},0);
        h+='<div class="avg-card" onclick="abrirGrafico(&#39;'+nid+'&#39;)">'
            +'<div class="avg-card-header"><span class="avg-card-name">'+nid+'</span><span class="avg-card-val tc-warm">'+gP+'&deg;</span></div>'
            +'<div class="avg-grid">'
            +'<div class="avg-item">Min<span class="av cool">'+gMin+'&deg;</span></div>'
            +'<div class="avg-item">Prom<span class="av warm">'+gP+'&deg;</span></div>'
            +'<div class="avg-item">Max<span class="av hot">'+gMax+'&deg;</span></div></div>'
            +'<div style="font-size:0.65em;color:var(--text2);margin-top:6px;text-align:center">'+tL+' lecturas en '+entries.length+' hora'+(entries.length>1?'s':'')+'</div></div>';
    });document.getElementById('avg-list').innerHTML=h;}catch(e){console.error(e);}
}

cargarAlertConfig();actualizar();
setInterval(actualizar,5000);
setInterval(function(){if(document.getElementById('tab-health').classList.contains('active'))actualizarSalud();},5000);
setInterval(function(){if(document.getElementById('tab-avg').classList.contains('active'))actualizarPromedios();},10000);
</script>
</body>
</html>"""
