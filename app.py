# app.py

```python
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from datetime import datetime

app = FastAPI()

class TempData(BaseModel):
    nodo: str
    temp: float
    lat: float
    lon: float

nodos = {}

@app.post('/temperatura')
async def temperatura(data: TempData):

    nodos[data.nodo] = {
        'temp': round(data.temp, 1),
        'lat': data.lat,
        'lon': data.lon,
        'hora': datetime.now().strftime('%H:%M:%S')
    }

    print(nodos)

    return {'ok': True}

@app.get('/api/datos')
async def api_datos():
    return nodos

@app.get('/', response_class=HTMLResponse)
async def mapa():

    html = """
<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
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

        const response = await fetch('/api/datos');

        const datos = await response.json();

        markers.forEach(m => map.removeLayer(m));
        circles.forEach(c => map.removeLayer(c));

        markers = [];
        circles = [];

        for (const nodo in datos) {

            const info = datos[nodo];

            const color = colorTemp(info.temp);

            const marker = L.marker([
                info.lat,
                info.lon
            ]).addTo(map);

            marker.bindPopup(`
                <b>${nodo}</b><br>
                🌡 ${info.temp} °C<br>
                ⏰ ${info.hora}
            `);

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
```

---

# CÓDIGO GATEWAY ESP32

```cpp
#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>
#include <HTTPClient.h>

const char* ssid = "Gabriela";
const char* password = "52959534";

const char* serverUrl =
"https://red-ambiental-servidor.onrender.com/temperatura";

#define LED_PIN 2

float LATITUD = -33.39145024052057;
float LONGITUD = -56.51992894878338;

String NOMBRE = "GATEWAY";

typedef struct struct_message {

  char nodo[16];
  float temperatura;
  float lat;
  float lon;

} struct_message;

struct_message incomingData;

void parpadear() {

  digitalWrite(LED_PIN, HIGH);
  delay(50);
  digitalWrite(LED_PIN, LOW);
}

void enviarServidor(
  String nodo,
  float temp,
  float lat,
  float lon
) {

  HTTPClient http;

  http.begin(serverUrl);

  http.addHeader(
    "Content-Type",
    "application/json"
  );

  String json = "{";

  json += "\"nodo\":\"" + nodo + "\",";
  json += "\"temp\":" + String(temp) + ",";
  json += "\"lat\":" + String(lat, 6) + ",";
  json += "\"lon\":" + String(lon, 6);

  json += "}";

  int httpCode = http.POST(json);

  Serial.println(json);

  Serial.print("HTTP: ");
  Serial.println(httpCode);

  http.end();
}

void OnDataRecv(
  const esp_now_recv_info *info,
  const uint8_t *incomingDataBytes,
  int len
) {

  memcpy(
    &incomingData,
    incomingDataBytes,
    sizeof(incomingData)
  );

  Serial.println("====================");
  Serial.println("NODO RECIBIDO");

  Serial.print("Nodo: ");
  Serial.println(incomingData.nodo);

  Serial.print("Temp: ");
  Serial.println(incomingData.temperatura);

  enviarServidor(
    incomingData.nodo,
    incomingData.temperatura,
    incomingData.lat,
    incomingData.lon
  );

  parpadear();
}

void setup() {

  Serial.begin(115200);

  pinMode(LED_PIN, OUTPUT);

  WiFi.mode(WIFI_STA);

  WiFi.begin(ssid, password);

  while (WiFi.status() != WL_CONNECTED) {

    delay(500);
    Serial.print(".");
  }

  Serial.println("WIFI OK");

  esp_wifi_set_channel(
    WiFi.channel(),
    WIFI_SECOND_CHAN_NONE
  );

  if (esp_now_init() != ESP_OK) {

    Serial.println("Error ESP-NOW");
    return;
  }

  esp_now_register_recv_cb(OnDataRecv);
}

void loop() {

  float temp = temperatureRead();

  enviarServidor(
    NOMBRE,
    temp,
    LATITUD,
    LONGITUD
  );

  Serial.println("====================");
  Serial.println("GATEWAY ONLINE");

  Serial.print("Temp: ");
  Serial.println(temp);

  parpadear();

  delay(2000);
}
```

---

# CÓDIGO NODO ESP32

MODIFICÁS SOLO:

* nombre
* latitud
* longitud

```cpp
#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>

#define LED_PIN 2
#define WIFI_CHANNEL 6

String NOMBRE = "ESP1";

float LATITUD = -33.39111587564696;
float LONGITUD = -56.51843195456958;

uint8_t broadcastAddress[] =
{0xFF,0xFF,0xFF,0xFF,0xFF,0xFF};

typedef struct struct_message {

  char nodo[16];
  float temperatura;
  float lat;
  float lon;

} struct_message;

struct_message datos;

void parpadear() {

  digitalWrite(LED_PIN, HIGH);
  delay(50);
  digitalWrite(LED_PIN, LOW);
}

void setup() {

  Serial.begin(115200);

  pinMode(LED_PIN, OUTPUT);

  WiFi.mode(WIFI_STA);

  esp_wifi_set_channel(
    WIFI_CHANNEL,
    WIFI_SECOND_CHAN_NONE
  );

  if (esp_now_init() != ESP_OK) {

    Serial.println("Error ESP-NOW");
    return;
  }

  esp_now_peer_info_t peerInfo = {};

  memcpy(peerInfo.peer_addr,
         broadcastAddress,
         6);

  peerInfo.channel = WIFI_CHANNEL;
  peerInfo.encrypt = false;

  esp_now_add_peer(&peerInfo);

  Serial.println("Nodo listo");
}

void loop() {

  NOMBRE.toCharArray(datos.nodo, 16);

  datos.temperatura = temperatureRead();

  datos.lat = LATITUD;
  datos.lon = LONGITUD;

  esp_now_send(
    broadcastAddress,
    (uint8_t *) &datos,
    sizeof(datos)
  );

  Serial.println("====================");

  Serial.print("Nodo: ");
  Serial.println(datos.nodo);

  Serial.print("Temp: ");
  Serial.println(datos.temperatura);

  parpadear();

  delay(2000);
}
```

---

# AGREGAR MÁS ESP32

Solo cambiás:

```cpp
String NOMBRE = "ESP2";

float LATITUD = XXXXX;
float LONGITUD = XXXXX;
```

Y cargás el mismo código.
