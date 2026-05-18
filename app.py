from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel
from datetime import datetime, timezone, timedelta
from typing import Optional
import sqlite3
import csv
import io
import os

app = FastAPI(title="Red Ambiental ESP32")

# Disable CORS. Do not remove this for full-stack development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
    c.execute('''CREATE TABLE IF NOT EXISTS lecturas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nodo TEXT NOT NULL,
        temp REAL NOT NULL,
        lat REAL,
        lon REAL,
        tipo TEXT,
        rssi INTEGER,
        hops INTEGER,
        timestamp TEXT NOT NULL
    )''')
    c.execute('''CREATE INDEX IF NOT EXISTS idx_lecturas_nodo ON lecturas(nodo)''')
    c.execute('''CREATE INDEX IF NOT EXISTS idx_lecturas_ts ON lecturas(timestamp)''')
    c.execute('''CREATE TABLE IF NOT EXISTS config_alertas (
        id INTEGER PRIMARY KEY CHECK(id=1),
        temp_min REAL DEFAULT 0,
        temp_max REAL DEFAULT 55,
        activa INTEGER DEFAULT 1
    )''')
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
        deleted = conn.execute('DELETE FROM lecturas WHERE timestamp < ?', (desde,)).rowcount
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
# ENDPOINTS DE DATOS
# =========================

@app.get("/healthz")
async def healthz():
    return {"status": "ok"}

@app.post("/temperatura")
async def temperatura(data: TempData):
    ahora = datetime.now(timezone.utc)
    nodos[data.nodo] = {
        "id": data.nodo,
        "temp": round(data.temp, 1),
        "lat": data.lat,
        "lon": data.lon,
        "tipo": "ESP32-interno",
        "hora": ahora.strftime("%H:%M:%S"),
        "timestamp": ahora.isoformat(),
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
        "id": data.station_id,
        "temp": round(data.temperature, 1),
        "lat": data.lat,
        "lon": data.lon,
        "tipo": data.sensor_type or "ESP32-interno",
        "hora": ahora.strftime("%H:%M:%S"),
        "timestamp": ahora.isoformat(),
        "rssi": data.rssi,
        "hops": data.hops if data.hops is not None else 0,
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
    return resultado

@app.get("/api/resumen")
async def api_resumen():
    if not nodos:
        return {"total": 0, "online": 0, "promedio": None, "minima": None, "maxima": None, "nodos": []}
    ahora = datetime.now(timezone.utc)
    online_count = 0
    for n in nodos.values():
        try:
            ts = datetime.fromisoformat(n["timestamp"])
            if (ahora - ts).total_seconds() < 30:
                online_count += 1
        except Exception:
            pass
    temps = [n["temp"] for n in nodos.values()]
    return {
        "total": len(nodos),
        "online": online_count,
        "promedio": round(sum(temps) / len(temps), 1),
        "minima": round(min(temps), 1),
        "maxima": round(max(temps), 1),
        "nodos": list(nodos.keys()),
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
        'SELECT nodo, temp, lat, lon, tipo, rssi, hops, timestamp FROM lecturas WHERE timestamp>=? ORDER BY timestamp',
        (desde,)
    ).fetchall()
    conn.close()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Nodo', 'Temperatura', 'Latitud', 'Longitud', 'Tipo', 'RSSI', 'Saltos', 'Timestamp'])
    for r in rows:
        writer.writerow([r['nodo'], r['temp'], r['lat'], r['lon'], r['tipo'], r['rssi'], r['hops'], r['timestamp']])
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
        '''SELECT nodo,
           strftime('%Y-%m-%dT%H:00:00', timestamp) as hora,
           ROUND(AVG(temp),1) as prom,
           ROUND(MIN(temp),1) as min_t,
           ROUND(MAX(temp),1) as max_t,
           COUNT(*) as cnt
        FROM lecturas WHERE timestamp >= ?
        GROUP BY nodo, strftime('%Y-%m-%dT%H:00:00', timestamp)
        ORDER BY hora''',
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
            "id": nid,
            "online": online,
            "rssi": n.get("rssi"),
            "hops": n.get("hops", 0),
            "edad_seg": round(edad, 1),
            "lecturas_total": total,
            "lecturas_1h": ultima_hora,
            "tipo": n.get("tipo", "ESP32-interno"),
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
<title>Red Ambiental ESP32</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
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

.header{
    background:linear-gradient(135deg,#0f172a 0%,#1e293b 100%);
    padding:12px 24px;display:flex;align-items:center;justify-content:space-between;
    border-bottom:1px solid var(--border);position:relative;z-index:1001;
}
.logo{display:flex;align-items:center;gap:12px}
.logo-icon{
    width:38px;height:38px;
    background:linear-gradient(135deg,var(--accent),var(--accent2));
    border-radius:10px;display:flex;align-items:center;justify-content:center;
    font-size:20px;box-shadow:0 0 20px var(--glow);
}
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
    width:320px;background:var(--card);border-left:1px solid var(--border);
    display:flex;flex-direction:column;z-index:1000;overflow:hidden;
}
.sidebar-header{
    padding:16px 20px 12px;border-bottom:1px solid var(--border);
    display:flex;align-items:center;justify-content:space-between;
}
.sidebar-header h2{font-size:0.9em;font-weight:600;letter-spacing:-0.3px}
.badge{
    background:var(--accent);color:#000;font-size:0.65em;font-weight:700;
    padding:2px 8px;border-radius:20px;
}

.stations{flex:1;overflow-y:auto;padding:12px 16px}
.stations::-webkit-scrollbar{width:4px}
.stations::-webkit-scrollbar-thumb{background:var(--border);border-radius:4px}

.scard{
    background:var(--card2);border:1px solid var(--border);border-radius:12px;
    padding:14px 16px;margin-bottom:10px;transition:all 0.3s ease;
    cursor:pointer;position:relative;overflow:hidden;
}
.scard::before{
    content:'';position:absolute;top:0;left:0;width:4px;height:100%;border-radius:4px 0 0 4px;
}
.scard.root::before{background:var(--accent)}
.scard.nodo::before{background:var(--accent2)}
.scard.offline{opacity:0.5;filter:grayscale(0.8)}
.scard.offline::before{background:#64748b}
.scard.offline .scard-temp{color:#64748b}
.scard.offline .tdot{background:#64748b;animation:none}
.scard:hover{
    border-color:var(--accent);transform:translateX(-2px);
    box-shadow:0 4px 20px rgba(0,0,0,0.3);
}
.scard-top{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:8px}
.scard-name{font-weight:600;font-size:0.9em}
.scard-type{font-size:0.65em;color:var(--text2);margin-top:2px}
.scard-temp{font-size:1.6em;font-weight:800;letter-spacing:-1px}
.scard-bottom{display:flex;justify-content:space-between;align-items:center;margin-top:6px}
.scard-coord{font-size:0.65em;color:var(--text2);font-family:monospace}
.scard-time{font-size:0.65em;color:var(--text2);display:flex;align-items:center;gap:4px}
.scard-time .tdot{width:5px;height:5px;border-radius:50%;background:#22c55e}
.offline-badge{font-size:0.6em;color:#64748b;background:#1e293b;padding:1px 6px;border-radius:4px;margin-left:6px}
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

.sidebar-footer{
    padding:12px 16px;border-top:1px solid var(--border);display:flex;gap:8px;
}
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

.leaflet-popup-content-wrapper{
    background:var(--card);color:var(--text);border-radius:12px;
    border:1px solid var(--border);box-shadow:0 8px 30px rgba(0,0,0,0.5);
}
.leaflet-popup-tip{background:var(--card)}
.popup{padding:4px}
.popup-id{font-weight:700;font-size:1em;margin-bottom:2px}
.popup-type{font-size:0.75em;color:var(--text2);margin-bottom:8px}
.popup-temp{font-size:2.2em;font-weight:800;letter-spacing:-1px;margin-bottom:4px}
.popup-time{font-size:0.7em;color:var(--text2)}

.minichart{display:flex;align-items:flex-end;gap:1px;height:30px;margin-top:8px}
.minibar{flex:1;min-width:2px;max-width:4px;border-radius:1px 1px 0 0;transition:height 0.3s ease}

.mesh-info{
    padding:12px 20px;background:var(--bg);border-bottom:1px solid var(--border);
    display:flex;align-items:center;gap:12px;
}
.mesh-icon{
    width:32px;height:32px;
    background:linear-gradient(135deg,var(--accent2),var(--accent));
    border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:14px;
}
.mesh-text{font-size:0.75em;color:var(--text2);line-height:1.4}
.mesh-text b{color:var(--text);font-weight:600}

.tc-cold{color:var(--cold)}.tc-cool{color:var(--cool)}.tc-warm{color:var(--warm)}.tc-hot{color:var(--hot)}

.sidebar-tabs{display:flex;border-bottom:1px solid var(--border)}
.sidebar-tab{flex:1;padding:8px 4px;text-align:center;font-size:0.7em;font-weight:600;color:var(--text2);cursor:pointer;border-bottom:2px solid transparent;transition:all 0.2s}
.sidebar-tab.active{color:var(--accent);border-bottom-color:var(--accent)}
.sidebar-tab:hover{color:var(--text)}
.tab-content{display:none;flex:1;overflow-y:auto;padding:12px 16px}
.tab-content.active{display:block}

.alert-banner{padding:10px 16px;background:rgba(239,71,111,0.1);border-bottom:1px solid rgba(239,71,111,0.3);display:none;align-items:center;gap:8px;font-size:0.75em;color:var(--hot);animation:alertPulse 2s infinite}
@keyframes alertPulse{0%,100%{opacity:1}50%{opacity:0.7}}
.alert-banner .alert-icon{font-size:1.2em}
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

@media(max-width:768px){
    .stats{display:none}
    .header{padding:10px 16px}
    .header .status{display:none}
    .logo h1{font-size:0.95em}
    .logo-sub{display:none}
    .mobile-toggle{display:flex;align-items:center;justify-content:center}
    .sidebar{
        position:fixed;top:0;right:-100%;width:85%;max-width:360px;height:100vh;
        z-index:1100;transition:right 0.3s ease;box-shadow:-4px 0 30px rgba(0,0,0,0.5);
    }
    .sidebar.open{right:0}
    .sidebar.open .mobile-close{display:block}
    .chart-box{width:95%;padding:14px}
    .chart-box canvas{height:220px!important}
}
</style>
</head>
<body>

<div class="header">
    <div class="logo">
        <div class="logo-icon">&#127758;</div>
        <div>
            <h1><span>RED</span> AMBIENTAL</h1>
            <div class="logo-sub">MONITOREO EN TIEMPO REAL &bull; ESP32 MESH</div>
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
            <span class="alert-icon">&#9888;</span>
            <span id="alert-msg">Alerta de temperatura</span>
            <span class="alert-close" onclick="document.getElementById('alert-banner').style.display='none'">&times;</span>
        </div>
        <div class="sidebar-tabs">
            <div class="sidebar-tab active" onclick="switchTab('tab-stations',this)">Estaciones</div>
            <div class="sidebar-tab" onclick="switchTab('tab-alerts',this)">Alertas</div>
            <div class="sidebar-tab" onclick="switchTab('tab-avg',this)">Promedios</div>
            <div class="sidebar-tab" onclick="switchTab('tab-health',this)">Red</div>
        </div>
        <div id="tab-stations" class="tab-content active">
            <div class="mesh-info" style="margin:-12px -16px 12px;padding:12px 20px;border-radius:0">
                <div class="mesh-icon">&#128225;</div>
                <div class="mesh-text"><b>Red Mesh ESP-NOW</b><br>Auto-descubrimiento &bull; Max 5 saltos</div>
            </div>
            <div id="station-list">
                <div class="empty">
                    <div class="empty-icon">&#128225;</div>
                    <h3>Sin estaciones conectadas</h3>
                    <p>Enciende tus ESP32 o carga datos de demo.</p>
                </div>
            </div>
        </div>
        <div id="tab-alerts" class="tab-content">
            <div class="alert-config">
                <div style="font-weight:600;font-size:0.85em;margin-bottom:10px">Configurar Alertas</div>
                <div class="toggle-row" style="padding:0;border:none;margin-bottom:10px">
                    <span class="toggle-label">Alertas activas</span>
                    <label class="toggle"><input type="checkbox" id="alert-activa" checked onchange="guardarAlertas()"><span class="slider"></span></label>
                </div>
                <div class="alert-row">
                    <div><label>Temp. minima (&deg;C)</label><input type="number" id="alert-min" value="0" step="0.5" onchange="guardarAlertas()"></div>
                    <div><label>Temp. maxima (&deg;C)</label><input type="number" id="alert-max" value="55" step="0.5" onchange="guardarAlertas()"></div>
                </div>
            </div>
            <div id="alert-list" style="font-size:0.75em;color:var(--text2)">Sin alertas activas</div>
        </div>
        <div id="tab-avg" class="tab-content">
            <div style="font-weight:600;font-size:0.85em;margin-bottom:10px">Promedios por hora (ult. 24h)</div>
            <div id="avg-list"><div class="empty"><div class="empty-icon">&#128202;</div><h3>Sin datos historicos</h3><p>Carga datos para ver promedios.</p></div></div>
        </div>
        <div id="tab-health" class="tab-content">
            <div id="health-list"><div class="empty"><div class="empty-icon">&#128225;</div><h3>Sin datos de red</h3><p>Carga datos para ver el estado de la red.</p></div></div>
        </div>
        <div class="toggle-row">
            <span class="toggle-label">Mostrar marcadores</span>
            <label class="toggle"><input type="checkbox" id="toggle-markers" checked onchange="toggleMarkers()"><span class="slider"></span></label>
        </div>
        <div class="toggle-row">
            <span class="toggle-label">Mostrar lineas mesh</span>
            <label class="toggle"><input type="checkbox" id="toggle-lines" checked onchange="toggleLines()"><span class="slider"></span></label>
        </div>
        <div class="notif-row">
            <button class="btn-notif" id="btn-notif" onclick="toggleNotificaciones()">&#128276; Activar notificaciones</button>
        </div>
        <div class="export-row">
            <button class="btn-export" onclick="exportarCSV()">&#128196; Exportar datos CSV</button>
        </div>
        <div class="sidebar-footer">
            <button class="btn btn-primary" onclick="actualizar()">Actualizar</button>
            <button class="btn btn-secondary" onclick="cargarDemo()">Demo</button>
        </div>
    </div>
</div>
<button class="mobile-toggle" onclick="toggleSidebar()">&#9776;</button>

<div id="chart-modal" class="chart-modal" onclick="if(event.target===this)cerrarGrafico()">
    <div class="chart-box">
        <div class="chart-header">
            <h3 id="chart-title">Historial</h3>
            <button class="chart-close" onclick="cerrarGrafico()">&times;</button>
        </div>
        <canvas id="chart-canvas"></canvas>
    </div>
</div>

<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="https://unpkg.com/leaflet.heat@0.2.0/dist/leaflet-heat.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<script>
const API=window.location.origin;
const map=L.map('map',{zoomControl:false}).setView([-33.3915,-56.5187],16);
L.control.zoom({position:'bottomleft'}).addTo(map);

const darkTile=L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',{attribution:'&copy; CARTO',maxZoom:20});
const satTile=L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',{attribution:'&copy; Esri',maxZoom:19});
const topoTile=L.tileLayer('https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png',{attribution:'&copy; OpenTopoMap',maxZoom:17});
const streetTile=L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{attribution:'&copy; OSM',maxZoom:19});
darkTile.addTo(map);
L.control.layers({'Oscuro':darkTile,'Satelite':satTile,'Topografico':topoTile,'Calles':streetTile},{},{position:'topright'}).addTo(map);

let heatLayer=null,markers=[],polylines=[],primeraCarga=true;
let showMarkers=true,showLines=true;
let alertConfig={temp_min:0,temp_max:55,activa:true};
let chartInstance=null;
let notifEnabled=false;

function tempColorHex(t){
    if(t<20)return'#118ab2';if(t<30)return'#06d6a0';if(t<40)return'#ffd166';return'#ef476f';
}
function tempClass(t){
    if(t<20)return'tc-cold';if(t<30)return'tc-cool';if(t<40)return'tc-warm';return'tc-hot';
}
function crearIconoOffline(temp){
    const sz=38;
    return L.divIcon({className:'',
        html:'<div style="position:relative;background:#475569;width:'+sz+'px;height:'+sz+'px;border-radius:50%;display:flex;align-items:center;justify-content:center;color:#94a3b8;font-weight:700;font-size:11px;font-family:Inter,sans-serif;border:2px solid #334155;box-shadow:0 2px 10px rgba(0,0,0,0.5);opacity:0.6;filter:grayscale(0.5)">'+Math.round(temp)+'\u00b0</div>',
        iconSize:[sz,sz],iconAnchor:[sz/2,sz/2]});
}
function crearIcono(temp,esRoot){
    const c=tempColorHex(temp),sz=esRoot?44:38,fs=esRoot?13:11;
    const brd=esRoot?'3px solid #06d6a0':'2px solid rgba(255,255,255,0.3)';
    const shd=esRoot?'0 0 20px rgba(6,214,160,0.5)':'0 2px 10px rgba(0,0,0,0.5)';
    const rb=esRoot?'<div style="position:absolute;top:-6px;right:-6px;background:#06d6a0;color:#000;font-size:8px;font-weight:800;padding:1px 4px;border-radius:4px;">ROOT</div>':'';
    return L.divIcon({className:'',
        html:'<div style="position:relative;background:'+c+';width:'+sz+'px;height:'+sz+'px;border-radius:50%;display:flex;align-items:center;justify-content:center;color:#fff;font-weight:700;font-size:'+fs+'px;font-family:Inter,sans-serif;border:'+brd+';box-shadow:'+shd+';transition:all 0.3s">'+Math.round(temp)+'\\u00b0'+rb+'</div>',
        iconSize:[sz,sz],iconAnchor:[sz/2,sz/2]});
}
function miniChart(datos){
    if(!datos||datos.length<2)return'';
    const vals=datos.slice(-20).map(d=>d.temp);
    const mn=Math.min(...vals),mx=Math.max(...vals),rg=mx-mn||1;
    let b='';vals.forEach(v=>{
        const h=Math.max(3,((v-mn)/rg)*28);
        b+='<div class="minibar" style="height:'+h+'px;background:'+tempColorHex(v)+'"></div>';
    });
    return'<div class="minichart">'+b+'</div>';
}
function signalBars(rssi){
    if(rssi===null||rssi===undefined)return'';
    const abs=Math.abs(rssi);
    let level=0,cls='active';
    if(abs<=50){level=4;cls='active';}
    else if(abs<=65){level=3;cls='active';}
    else if(abs<=75){level=2;cls='warn';}
    else{level=1;cls='bad';}
    const heights=[4,7,10,14];
    let bars='';
    for(let i=0;i<4;i++){
        const on=i<level;
        bars+='<div class="bar'+(on?' '+cls:'')+'" style="height:'+heights[i]+'px"></div>';
    }
    return'<div class="scard-signal"><div class="signal-bars">'+bars+'</div>'
        +'<span class="signal-val">'+rssi+' dBm</span>';
}
function hopsBadge(hops){
    if(hops===null||hops===undefined||hops===0)return'';
    return'<span class="signal-hops">'+hops+' salto'+(hops>1?'s':'')+'</span>';
}

async function actualizar(){
    try{
        const[dR,rR]=await Promise.all([fetch(API+'/api/datos'),fetch(API+'/api/resumen')]);
        const datos=await dR.json(),res=await rR.json();

        document.getElementById('s-total').textContent=res.total;
        document.getElementById('s-prom').textContent=res.promedio!==null?res.promedio+'\\u00b0':'--';
        document.getElementById('s-min').textContent=res.minima!==null?res.minima+'\\u00b0':'--';
        document.getElementById('s-max').textContent=res.maxima!==null?res.maxima+'\\u00b0':'--';
        document.getElementById('badge-count').textContent=res.total;
        document.getElementById('status-text').textContent='Actualizado '+new Date().toLocaleTimeString();

        if(heatLayer)map.removeLayer(heatLayer);
        markers.forEach(m=>map.removeLayer(m));polylines.forEach(p=>map.removeLayer(p));
        markers=[];polylines=[];

        const nodos=Object.values(datos);
        if(nodos.length===0){
            document.getElementById('station-list').innerHTML='<div class="empty"><div class="empty-icon">&#128225;</div><h3>Sin estaciones conectadas</h3><p>Enciende tus ESP32 o carga datos de demo.</p></div>';
            return;
        }

        const hp=nodos.map(n=>[n.lat,n.lon,Math.max(0.1,n.temp/60)]);
        heatLayer=L.heatLayer(hp,{radius:50,blur:35,maxZoom:18,minOpacity:0.4,
            gradient:{0.0:'#118ab2',0.25:'#06d6a0',0.5:'#ffd166',0.75:'#ef476f',1.0:'#9b2226'}
        }).addTo(map);

        if(nodos.length>1){
            const root=nodos.find(n=>n.id==='MET-001'||(n.tipo&&n.tipo.includes('ROOT')))||nodos[0];
            nodos.forEach(n=>{
                if(n.id!==root.id){
                    const isOnline=n.online!==false;
                    const lnColor=isOnline?'rgba(6,214,160,0.25)':'rgba(100,116,139,0.2)';
                    const pl=L.polyline([[root.lat,root.lon],[n.lat,n.lon]],{
                        color:lnColor,weight:2,dashArray:'8,8'
                    });
                    if(showLines)pl.addTo(map);polylines.push(pl);
                }
            });
        }

        const hP=nodos.map(n=>fetch(API+'/api/historial/'+encodeURIComponent(n.id)+'?limit=20').then(r=>r.json()).catch(()=>[]));
        const hist=await Promise.all(hP);
        const histMap={};nodos.forEach((n,i)=>{histMap[n.id]=hist[i];});

        nodos.forEach((n,i)=>{
            const esRoot=n.id==='MET-001'||(n.tipo&&n.tipo.includes('ROOT'));
            const isOnline=n.online!==false;
            const rssiHtml=n.rssi!=null?'<div style="font-size:0.75em;color:#94a3b8;margin-top:4px">Senal: '+n.rssi+' dBm'+(n.hops?' | '+n.hops+' salto'+(n.hops>1?'s':''):'')+'</div>':'';
            const statusHtml=!isOnline?'<div style="font-size:0.7em;color:#64748b;margin-top:4px">DESCONECTADO</div>':'';
            const iconFn=isOnline?crearIcono(n.temp,esRoot):crearIconoOffline(n.temp);
            const tmpCls=isOnline?tempClass(n.temp):'';
            const tmpStyle=isOnline?'':'style="color:#64748b"';
            const mk=L.marker([n.lat,n.lon],{icon:iconFn})
                .bindPopup('<div class="popup"><div class="popup-id">'+n.id+'</div><div class="popup-type">'+(n.tipo||'ESP32-interno')+(esRoot?' &#183; GATEWAY':'')+'</div><div class="popup-temp '+tmpCls+'" '+tmpStyle+'>'+n.temp+'\\u00b0C</div>'+rssiHtml+statusHtml+'<div class="popup-time">Actualizado: '+(n.hora||'--')+'</div>'+miniChart(histMap[n.id])+'</div>',{maxWidth:220});
            if(showMarkers)mk.addTo(map);markers.push(mk);
        });

        let lH='';nodos.sort((a,b)=>a.id.localeCompare(b.id));
        nodos.forEach((n,i)=>{
            const esRoot=n.id==='MET-001'||(n.tipo&&n.tipo.includes('ROOT'));
            const isOnline=n.online!==false;
            const offCls=isOnline?'':'offline';
            lH+='<div class="scard '+(esRoot?'root':'nodo')+' '+offCls+'" onclick="map.setView(['+n.lat+','+n.lon+'],17)">'
                +'<div class="scard-top"><div><div class="scard-name">'+n.id+(esRoot?' <span style=\\"color:#06d6a0;font-size:0.7em\\">ROOT</span>':'')+(isOnline?'':'<span class=\\"offline-badge\\">OFFLINE</span>')+'</div>'
                +'<div class="scard-type">'+(n.tipo||'ESP32-interno')+'</div></div>'
                +'<div class="scard-temp '+tempClass(n.temp)+'">'+n.temp+'\\u00b0</div></div>'
                +'<div style="cursor:pointer" onclick="event.stopPropagation();abrirGrafico(\\''+n.id+'\\')">'+miniChart(histMap[n.id])+'</div>'
                +signalBars(n.rssi)+hopsBadge(n.hops)+(n.rssi!=null?'</div>':'')
                +'<div class="scard-bottom"><div class="scard-coord">'+n.lat.toFixed(4)+', '+n.lon.toFixed(4)+'</div>'
                +'<div class="scard-time"><div class="tdot"></div>'+(n.hora||'--')+'</div></div></div>';
        });
        document.getElementById('station-list').innerHTML=lH;
        checkAlerts(nodos);

        if(primeraCarga&&nodos.length>0){
            if(nodos.length===1)map.setView([nodos[0].lat,nodos[0].lon],16);
            else map.fitBounds(L.latLngBounds(nodos.map(n=>[n.lat,n.lon])).pad(0.3));
            primeraCarga=false;
        }
    }catch(err){
        console.error('Error:',err);
        document.getElementById('status-text').textContent='Error de conexion';
    }
}

async function cargarDemo(){
    try{await fetch(API+'/api/demo',{method:'POST'});await actualizar();}catch(e){console.error(e);}
}

function toggleMarkers(){
    showMarkers=document.getElementById('toggle-markers').checked;
    markers.forEach(m=>{if(showMarkers)m.addTo(map);else map.removeLayer(m);});
}
function toggleLines(){
    showLines=document.getElementById('toggle-lines').checked;
    polylines.forEach(p=>{if(showLines)p.addTo(map);else map.removeLayer(p);});
}

function switchTab(tabId,el){
    document.querySelectorAll('.tab-content').forEach(t=>t.classList.remove('active'));
    document.querySelectorAll('.sidebar-tab').forEach(t=>t.classList.remove('active'));
    document.getElementById(tabId).classList.add('active');
    el.classList.add('active');
    if(tabId==='tab-health')actualizarSalud();
    if(tabId==='tab-avg')actualizarPromedios();
}

function toggleSidebar(){
    document.getElementById('sidebar').classList.toggle('open');
}

async function cargarAlertConfig(){
    try{
        const r=await fetch(API+'/api/alertas');
        alertConfig=await r.json();
        document.getElementById('alert-min').value=alertConfig.temp_min;
        document.getElementById('alert-max').value=alertConfig.temp_max;
        document.getElementById('alert-activa').checked=alertConfig.activa;
    }catch(e){}
}
async function guardarAlertas(){
    const cfg={
        temp_min:parseFloat(document.getElementById('alert-min').value)||0,
        temp_max:parseFloat(document.getElementById('alert-max').value)||55,
        activa:document.getElementById('alert-activa').checked
    };
    try{await fetch(API+'/api/alertas',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(cfg)});alertConfig=cfg;}catch(e){}
}
function checkAlerts(nodos){
    if(!alertConfig.activa){document.getElementById('alert-banner').style.display='none';return;}
    const alertas=[];
    nodos.forEach(n=>{
        if(n.online!==false){
            if(n.temp<alertConfig.temp_min)alertas.push(n.id+': '+n.temp+'\\u00b0C (bajo min '+alertConfig.temp_min+'\\u00b0)');
            if(n.temp>alertConfig.temp_max)alertas.push(n.id+': '+n.temp+'\\u00b0C (sobre max '+alertConfig.temp_max+'\\u00b0)');
        }
    });
    const banner=document.getElementById('alert-banner');
    if(alertas.length>0){
        banner.style.display='flex';
        document.getElementById('alert-msg').textContent='\\u26a0 '+alertas.join(' | ');
        sendNotification('\\u26a0 Alerta Red Ambiental',alertas.join('\\n'));
    }else{banner.style.display='none';}
    let aH='';
    if(alertas.length>0){
        alertas.forEach(a=>{aH+='<div style="padding:6px 0;border-bottom:1px solid var(--border);color:var(--hot)">\\u26a0 '+a+'</div>';});
    }else{aH='<div style="padding:20px;text-align:center;color:var(--accent)">\\u2713 Todas las temperaturas dentro del rango</div>';}
    document.getElementById('alert-list').innerHTML=aH;
}

async function actualizarSalud(){
    try{
        const r=await fetch(API+'/api/salud');
        const salud=await r.json();
        if(salud.length===0){document.getElementById('health-list').innerHTML='<div class="empty"><div class="empty-icon">&#128225;</div><h3>Sin datos</h3></div>';return;}
        let h='';
        salud.forEach(s=>{
            const signalQ=s.rssi?Math.min(100,Math.max(0,2*(s.rssi+100)))+'%':'--';
            h+='<div class="health-card">'
                +'<div class="health-card-header"><span class="health-card-name">'+s.id+'</span>'
                +'<span class="health-status '+(s.online?'on':'off')+'">'+(s.online?'ONLINE':'OFFLINE')+'</span></div>'
                +'<div class="health-grid">'
                +'<div class="health-item">Senal <span class="hval">'+(s.rssi?s.rssi+' dBm':'--')+'</span></div>'
                +'<div class="health-item">Calidad <span class="hval">'+signalQ+'</span></div>'
                +'<div class="health-item">Saltos <span class="hval">'+s.hops+'</span></div>'
                +'<div class="health-item">Edad <span class="hval">'+(s.online?Math.round(s.edad_seg)+'s':'--')+'</span></div>'
                +'<div class="health-item">Total lect. <span class="hval">'+s.lecturas_total+'</span></div>'
                +'<div class="health-item">Ult. hora <span class="hval">'+s.lecturas_1h+'</span></div>'
                +'</div></div>';
        });
        document.getElementById('health-list').innerHTML=h;
    }catch(e){console.error(e);}
}

function exportarCSV(){
    window.open(API+'/api/exportar/csv?horas=24','_blank');
}

async function abrirGrafico(nodoId){
    document.getElementById('chart-modal').classList.add('active');
    document.getElementById('chart-title').textContent='Historial: '+nodoId;
    try{
        const r=await fetch(API+'/api/historial/db/'+encodeURIComponent(nodoId)+'?horas=24');
        const datos=await r.json();
        const labels=datos.map(d=>{try{const dt=new Date(d.timestamp);return dt.getHours()+':'+String(dt.getMinutes()).padStart(2,'0');}catch(e){return'';}});
        const temps=datos.map(d=>d.temp);
        if(chartInstance){chartInstance.destroy();}
        const ctx=document.getElementById('chart-canvas').getContext('2d');
        chartInstance=new Chart(ctx,{
            type:'line',
            data:{labels:labels,datasets:[{label:'Temperatura (\\u00b0C)',data:temps,borderColor:'#06d6a0',backgroundColor:'rgba(6,214,160,0.1)',fill:true,tension:0.3,pointRadius:1,borderWidth:2}]},
            options:{responsive:true,maintainAspectRatio:false,
                plugins:{legend:{labels:{color:'#e2e8f0'}}},
                scales:{x:{ticks:{color:'#94a3b8',maxTicksLimit:12},grid:{color:'rgba(30,41,59,0.5)'}},y:{ticks:{color:'#94a3b8'},grid:{color:'rgba(30,41,59,0.5)'}}}
            }
        });
    }catch(e){console.error(e);}
}
function cerrarGrafico(){
    document.getElementById('chart-modal').classList.remove('active');
    if(chartInstance){chartInstance.destroy();chartInstance=null;}
}

async function toggleNotificaciones(){
    const btn=document.getElementById('btn-notif');
    if(!notifEnabled){
        if(!('Notification' in window)){alert('Tu navegador no soporta notificaciones');return;}
        const perm=await Notification.requestPermission();
        if(perm==='granted'){
            notifEnabled=true;
            btn.classList.add('active');
            btn.innerHTML='&#128276; Notificaciones activas';
            new Notification('Red Ambiental',{body:'Notificaciones activadas. Recibiras alertas de temperatura.',icon:'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><text y=".9em" font-size="90">&#127758;</text></svg>'});
        }
    }else{
        notifEnabled=false;
        btn.classList.remove('active');
        btn.innerHTML='&#128276; Activar notificaciones';
    }
}
function sendNotification(title,body){
    if(notifEnabled&&'Notification' in window&&Notification.permission==='granted'){
        new Notification(title,{body:body,icon:'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><text y=".9em" font-size="90">&#127758;</text></svg>'});
    }
}

async function actualizarPromedios(){
    try{
        const r=await fetch(API+'/api/promedios?horas=24');
        const data=await r.json();
        const nodos=Object.keys(data);
        if(nodos.length===0){document.getElementById('avg-list').innerHTML='<div class="empty"><div class="empty-icon">&#128202;</div><h3>Sin datos</h3><p>Carga datos para ver promedios.</p></div>';return;}
        let h='';
        nodos.forEach(nid=>{
            const entries=data[nid];
            if(!entries||entries.length===0)return;
            const allProms=entries.map(e=>e.prom);
            const globalProm=(allProms.reduce((a,b)=>a+b,0)/allProms.length).toFixed(1);
            const globalMin=Math.min(...entries.map(e=>e.min)).toFixed(1);
            const globalMax=Math.max(...entries.map(e=>e.max)).toFixed(1);
            const totalLect=entries.reduce((a,e)=>a+e.lecturas,0);
            h+='<div class="avg-card" onclick="abrirGrafico(\\''+nid+'\\')">'
                +'<div class="avg-card-header"><span class="avg-card-name">'+nid+'</span>'
                +'<span class="avg-card-val tc-warm">'+globalProm+'\\u00b0</span></div>'
                +'<div class="avg-grid">'
                +'<div class="avg-item">Min<span class="av cool">'+globalMin+'\\u00b0</span></div>'
                +'<div class="avg-item">Prom<span class="av warm">'+globalProm+'\\u00b0</span></div>'
                +'<div class="avg-item">Max<span class="av hot">'+globalMax+'\\u00b0</span></div>'
                +'</div>'
                +'<div style="font-size:0.65em;color:var(--text2);margin-top:6px;text-align:center">'+totalLect+' lecturas en '+entries.length+' hora'+(entries.length>1?'s':'')+'</div>'
                +'</div>';
        });
        document.getElementById('avg-list').innerHTML=h;
    }catch(e){console.error(e);}
}

cargarAlertConfig();
actualizar();
setInterval(actualizar,2000);
setInterval(()=>{if(document.getElementById('tab-health').classList.contains('active'))actualizarSalud();},5000);
setInterval(()=>{if(document.getElementById('tab-avg').classList.contains('active'))actualizarPromedios();},10000);
</script>
</body>
</html>"""
