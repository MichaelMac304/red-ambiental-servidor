const map = L.map('map').setView([-33.3918, -56.5189], 18);
                    color: color,
                    fillColor: color,
                    fillOpacity: 0.8
                }
            ).addTo(map);

        }else{

            markers[node.id].setLatLng([
                node.lat,
                node.lon
            ]);
        }

        markers[node.id].bindPopup(`
            <b>${node.id}</b><br>
            🌡 ${node.temp.toFixed(1)} °C
        `);

        nodeList.innerHTML += `
            <div class="node ${node.temp > 45 ? 'hot':'cold'}">
                <strong>${node.id}</strong><br>
                🌡 ${node.temp.toFixed(1)} °C<br>
                📍 ${node.lat.toFixed(5)}, ${node.lon.toFixed(5)}
            </div>
        `;

    });

    document.getElementById('onlineCount').innerText = Object.keys(data).length;

    document.getElementById('maxTemp').innerText = maxTemp.toFixed(1) + '°C';

    // ================= LIMPIAR LINEAS =================
    lines.forEach(line => map.removeLayer(line));
    lines = [];

    // ================= CREAR LINEAS =================
    links.forEach(link => {

        const line = L.polyline(
            [link.from, link.to],
            {
                color: '#38bdf8',
                weight: 3,
                opacity: 0.7
            }
        ).addTo(map);

        lines.push(line);
    });

    // ================= HEATMAP =================
    if(heatLayer){
        map.removeLayer(heatLayer);
    }

    heatLayer = L.heatLayer(
        heatPoints,
        {
            radius: 35,
            blur: 25,
            maxZoom: 19
        }
    ).addTo(map);
}

setInterval(updateMap, 2000);

updateMap();
