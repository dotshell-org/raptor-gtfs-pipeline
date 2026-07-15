package com.raptor

import com.github.ajalt.clikt.core.CliktCommand
import com.github.ajalt.clikt.parameters.options.default
import com.github.ajalt.clikt.parameters.options.option
import com.github.ajalt.clikt.parameters.options.required
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder

class VisualizerCommand : CliktCommand(name = "visualize", help = "Generate HTML map from RAPTOR binary data") {
    private val data by option("--data", help = "Path to raptor_data directory").required()
    private val output by option("--output", help = "Output HTML file").default("network_map.html")

    private fun readUint16(buffer: ByteBuffer): Int = buffer.short.toInt() and 0xFFFF
    private fun readUint32(buffer: ByteBuffer): Long = buffer.int.toLong() and 0xFFFFFFFF
    private fun readFloat64(buffer: ByteBuffer): Double = buffer.double
    
    private fun readString(buffer: ByteBuffer): String {
        val length = readUint16(buffer)
        val bytes = ByteArray(length)
        buffer.get(bytes)
        return String(bytes, Charsets.UTF_8)
    }

    private fun readStops(stopsPath: File): List<Map<String, Any>> {
        val bytes = stopsPath.readBytes()
        val buffer = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN)
        
        val magic = ByteArray(4)
        buffer.get(magic)
        if (String(magic, Charsets.US_ASCII) != "RST2") {
            throw IllegalArgumentException("Invalid stops.bin magic")
        }

        readUint16(buffer) // schema_version
        val stopCount = readUint32(buffer).toInt()

        val stops = mutableListOf<Map<String, Any>>()
        for (i in 0 until stopCount) {
            val stopId = readUint32(buffer).toInt()
            val name = readString(buffer)
            val lat = readFloat64(buffer)
            val lon = readFloat64(buffer)

            val routeCount = readUint32(buffer).toInt()
            val routeIds = (0 until routeCount).map { readUint32(buffer).toInt() }

            val transferCount = readUint32(buffer).toInt()
            val transfers = (0 until transferCount).map {
                val targetStop = readUint32(buffer).toInt()
                val walkTime = buffer.int
                Pair(targetStop, walkTime)
            }

            stops.add(mapOf(
                "id" to stopId,
                "name" to name,
                "lat" to lat,
                "lon" to lon,
                "route_ids" to routeIds,
                "transfers" to transfers
            ))
        }
        return stops
    }

    private fun readRoutes(routesPath: File): List<Map<String, Any>> {
        val bytes = routesPath.readBytes()
        val buffer = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN)

        val magic = ByteArray(4)
        buffer.get(magic)
        if (String(magic, Charsets.US_ASCII) != "RRT2") {
            throw IllegalArgumentException("Invalid routes.bin magic")
        }

        readUint16(buffer) // schema_version
        val routeCount = readUint32(buffer).toInt()

        val routes = mutableListOf<Map<String, Any>>()
        for (i in 0 until routeCount) {
            val routeId = readUint32(buffer).toInt()
            val routeName = readString(buffer)
            val stopCount = readUint32(buffer).toInt()
            val tripCount = readUint32(buffer).toInt()

            val stopIds = (0 until stopCount).map { readUint32(buffer).toInt() }

            // Skip trips data
            for (j in 0 until tripCount) readUint32(buffer)
            for (j in 0 until (tripCount * stopCount)) buffer.int

            routes.add(mapOf(
                "id" to routeId,
                "name" to routeName,
                "stop_ids" to stopIds
            ))
        }
        return routes
    }

    override fun run() {
        val dataPath = File(data)
        val stopsPath = File(dataPath, "stops.bin")
        val routesPath = File(dataPath, "routes.bin")

        if (!stopsPath.exists()) throw RuntimeException("stops.bin not found in $dataPath")
        if (!routesPath.exists()) throw RuntimeException("routes.bin not found in $dataPath")

        println("Reading data from $dataPath...")
        val stops = readStops(stopsPath)
        val routes = readRoutes(routesPath)

        println("Found ${stops.size} stops and ${routes.size} routes")

        val outputPath = File(output)
        
        val centerLat = stops.sumOf { it["lat"] as Double } / stops.size
        val centerLon = stops.sumOf { it["lon"] as Double } / stops.size

        val stopById = stops.associateBy { it["id"] as Int }
        val colors = listOf(
            "#e6194b", "#3cb44b", "#ffe119", "#4363d8", "#f58231",
            "#911eb4", "#42d4f4", "#f032e6", "#bfef45", "#fabed4",
            "#469990", "#dcbeff", "#9A6324", "#fffac8", "#800000",
            "#aaffc3", "#808000", "#ffd8b1", "#000075", "#a9a9a9"
        )

        var html = """<!DOCTYPE html>
<html>
<head>
    <title>RAPTOR Network Map</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.css" />
    <link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.Default.css" />
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <script src="https://unpkg.com/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js"></script>
    <style>
        body { margin: 0; padding: 0; }
        #map { position: absolute; top: 0; bottom: 0; width: 100%; }
        .info-panel {
            position: absolute;
            top: 10px;
            right: 10px;
            background: white;
            padding: 15px;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.2);
            z-index: 1000;
            max-width: 300px;
        }
        .info-panel h3 { margin: 0 0 10px 0; }
        .stat { margin: 5px 0; }
        .zoom-info { 
            margin-top: 10px; 
            padding-top: 10px; 
            border-top: 1px solid #ddd; 
            font-size: 12px; 
            color: #666; 
        }
    </style>
</head>
<body>
    <div id="map"></div>
    <div class="info-panel">
        <h3>🚌 RAPTOR Network</h3>
        <div class="stat"><strong>Stops:</strong> ${stops.size}</div>
        <div class="stat"><strong>Routes:</strong> ${routes.size}</div>
        <div class="zoom-info">
            <div>Zoom: <span id="zoom-level">-</span></div>
            <div>Visible: <span id="visible-elements">-</span></div>
        </div>
    </div>
    <script>
        var map = L.map('map', {
            preferCanvas: true,
            renderer: L.canvas()
        }).setView([$centerLat, $centerLon], 12);
        
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '© OpenStreetMap contributors'
        }).addTo(map);
        
        map.createPane('routesPane');
        map.getPane('routesPane').style.zIndex = 450;
        
        map.createPane('transfersPane');
        map.getPane('transfersPane').style.zIndex = 440;
        
        var stopsData = [];
        var routesData = [];
        var transfersData = [];
        
        var routeLayer = L.layerGroup();
        var transferLayer = L.layerGroup();
        var stopClusterGroup = L.markerClusterGroup({
            chunkedLoading: true,
            chunkInterval: 200,
            chunkDelay: 50,
            maxClusterRadius: 50,
            spiderfyOnMaxZoom: true,
            showCoverageOnHover: false,
            zoomToBoundsOnClick: true
        });
"""

        for ((i, stop) in stops.withIndex()) {
            val popup = "${stop["name"]} (ID: ${stop["id"]})".replace("\"", "&quot;")
            html += """
        stopsData.push({
            id: ${stop["id"]},
            lat: ${stop["lat"]},
            lon: ${stop["lon"]},
            name: "$popup"
        });
"""
        }

        html += """
        stopsData.forEach(function(stop) {
            var marker = L.circleMarker([stop.lat, stop.lon], {
                radius: 4,
                fillColor: '#3388ff',
                color: '#fff',
                weight: 1,
                opacity: 1,
                fillOpacity: 0.7
            }).bindPopup(stop.name);
            stopClusterGroup.addLayer(marker);
        });
        stopClusterGroup.addTo(map);
"""

        for ((i, route) in routes.withIndex()) {
            val color = colors[i % colors.size]
            val coords = mutableListOf<String>()
            val stopIds = route["stop_ids"] as List<Int>
            for (stopId in stopIds) {
                stopById[stopId]?.let { s ->
                    coords.add("[${s["lat"]}, ${s["lon"]}]")
                }
            }
            if (coords.size >= 2) {
                val routeName = (route["name"] as String).replace("\"", "\\\"").replace("'", "\\'")
                html += """
        routesData.push({
            name: "$routeName",
            color: "$color",
            coords: [${coords.joinToString(", ")}]
        });
"""
            }
        }

        for (stop in stops) {
            val transfers = stop["transfers"] as List<Pair<Int, Int>>
            for ((targetId, walkTime) in transfers) {
                stopById[targetId]?.let { target ->
                    val minutes = walkTime / 60
                    html += """
        transfersData.push({
            from: [${stop["lat"]}, ${stop["lon"]}],
            to: [${target["lat"]}, ${target["lon"]}],
            minutes: $minutes
        });
"""
                }
            }
        }

        html += """
        function renderRoutes() {
            routeLayer.clearLayers();
            var zoom = map.getZoom();
            routesData.forEach(function(route) {
                L.polyline(route.coords, {
                    color: route.color,
                    weight: zoom < 10 ? 3 : (zoom < 12 ? 4 : (zoom < 14 ? 5 : 6)),
                    opacity: zoom < 10 ? 0.6 : (zoom < 12 ? 0.7 : 0.85),
                    pane: 'routesPane',
                    lineCap: 'round',
                    lineJoin: 'round'
                }).bindPopup(route.name).addTo(routeLayer);
            });
        }
        
        function renderTransfers() {
            transferLayer.clearLayers();
            var zoom = map.getZoom();
            if (zoom >= 13) {
                transfersData.forEach(function(transfer) {
                    L.polyline([transfer.from, transfer.to], {
                        color: '#888',
                        weight: 2,
                        opacity: 0.6,
                        dashArray: '5, 5',
                        pane: 'transfersPane'
                    }).bindPopup("Walk: " + transfer.minutes + " min").addTo(transferLayer);
                });
            }
        }
        
        function updateInfo() {
            var zoom = map.getZoom();
            document.getElementById('zoom-level').textContent = zoom;
            
            var visible = ['routes'];
            if (zoom >= 13) visible.push('transfers');
            visible.push('stops (clustered)');
            
            document.getElementById('visible-elements').textContent = visible.join(', ');
        }
        
        routeLayer.addTo(map);
        transferLayer.addTo(map);
        
        renderRoutes();
        renderTransfers();
        updateInfo();
        
        map.on('zoomend', function() {
            renderRoutes();
            renderTransfers();
            updateInfo();
        });
        
        if (stopsData.length > 0) {
            var bounds = L.latLngBounds(stopsData.map(s => [s.lat, s.lon]));
            map.fitBounds(bounds.pad(0.1));
        }
    </script>
</body>
</html>
"""
        outputPath.writeText(html)
        println("Map generated: $outputPath")
    }
}
