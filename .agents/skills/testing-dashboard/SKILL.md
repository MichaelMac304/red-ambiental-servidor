---
name: testing-dashboard
description: End-to-end testing guide for the Red Ambiental dashboard. Use when testing UI changes or verifying features after code changes.
---

# Testing the Red Ambiental Dashboard

## Setup

1. Start the server:
   ```bash
   cd /home/ubuntu/repos/red-ambiental-servidor && uvicorn app:app --host 0.0.0.0 --port 8000
   ```
2. Open http://localhost:8000 in Chrome
3. Verify server health: `curl http://localhost:8000/healthz`

## Load Test Data

- Click "Demo" button at bottom-right to load 2 demo stations (MET-001, MET-002)
- Or use API: `curl -X POST http://localhost:8000/api/demo`
- For more nodes: activate ghost nodes in Config tab (adds 14 simulated nodes)

## Critical Tests

### Splash Screen
- Hard refresh (Ctrl+Shift+R) and verify splash appears then disappears within ~2 seconds
- If splash gets stuck: check browser console (F12) for SyntaxError — this means a JS escape issue in app.py

### JS Escape Issues
- The entire dashboard is embedded in a Python triple-quoted string in app.py
- `\'` does NOT work in triple-quoted strings — use `&#39;` HTML entities or template literals
- `'\n'` in Python becomes a literal newline in HTML — use `'\\n'` to get `\n` in JS
- Always run `node --check` on extracted JS to verify syntax:
  ```bash
  curl -s http://localhost:8000 | python3 -c "
  import sys; html=sys.stdin.read()
  s=html.find('<script>')+8; e=html.find('</script>')
  open('/tmp/test.js','w').write(html[s:e])" && node --check /tmp/test.js
  ```

### Console Errors
- Open DevTools (F12) → Console tab
- Zero SyntaxError or Uncaught errors expected

## Feature Tests

| Feature | How to Test | Expected |
|---------|-------------|----------|
| Header logo | Check top-left after load | MET logo + "MET. Red Ambiental" text |
| Demo data | Click "Demo" | 2 stations with temps, markers on map |
| Clustering | Zoom out with ghost nodes active | Markers merge into numbered clusters |
| Heatmap | Check map after data load | Color gradient between station points |
| Heatmap sliders | Config tab → Radio/Blur/Opacidad | Heatmap updates visually |
| Ghost nodes | Config tab → "Activar nodos fantasma" | 14 ghost markers appear, count increases |
| Ghost toggle | Config tab → click a ghost node | Node toggles ON/OFF |
| Live chart | Click a station card or Promedios card | Modal opens with Chart.js graph + time range buttons |
| Marker size | Config tab → "Tamano marcador" slider | Markers change size on map |
| CSV export | Click "Exportar CSV" or `curl /api/exportar/csv?horas=24` | CSV with columns: Nodo, Temperatura, H:M:S, Tipo de sensor, Saltos |
| Sidebar tabs | Click each tab | Estaciones, Alertas, Red, Promedios, Config |
| Map layers | Click layers icon (top-right) | 4 options: Oscuro, Satelite, Topografico, Calles |
| Animated lines | Check lines between markers | Dashed lines with flowing animation |
| Notifications | Click "Activar notificaciones" | Browser asks for notification permission |

## API Endpoints for Testing

```bash
curl http://localhost:8000/healthz
curl http://localhost:8000/api/datos
curl http://localhost:8000/api/resumen
curl -X POST http://localhost:8000/api/demo
curl -X POST http://localhost:8000/api/ghost/activar
curl -X POST http://localhost:8000/api/ghost/toggle/GHOST-01
curl -X POST http://localhost:8000/api/ghost/desactivar
curl http://localhost:8000/api/exportar/csv?horas=24
curl http://localhost:8000/api/promedios?horas=24
curl http://localhost:8000/api/salud
```

## Known Caveats

- Ghost node state is in-memory — resets on server restart
- Map tile servers (Satellite, Topo, Streets) may not load from some VMs due to network restrictions — test on Render production instead
- The 5-second auto-refresh closes map popups quickly — this is expected for a real-time dashboard
- Render free tier sleeps after inactivity — first ESP32 connection may take 30-60s to wake up
