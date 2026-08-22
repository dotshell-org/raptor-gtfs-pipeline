package eu.dotshell.raptor.gtfs.pipeline.cli

import com.github.ajalt.clikt.core.CliktCommand
import com.github.ajalt.clikt.parameters.options.default
import com.github.ajalt.clikt.parameters.options.flag
import com.github.ajalt.clikt.parameters.options.option
import com.github.ajalt.clikt.parameters.options.required
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * Dev-only visualizer: renders a city's ENTIRE line network as a standalone HTML MapLibre GL map,
 * each line drawn with its real geometry in its operator colour — a faithful revival of the app's
 * removed "all-lines" mode, including the staggered 2 s reveal (grace 500 ms, waves of 4 lines,
 * 12 ms/line; the exact timing the app used).
 *
 * Reads the RLN2 `lines.bin` produced by `convert --traces`, so point `--data` at any converted
 * city directory. Nothing city-specific is hard-coded — "une ville au choix" is just its data dir.
 */
class VisualizeNetworkCommand : CliktCommand(
    name = "visualize-network",
    help = "Render a city's whole line network to an HTML map (revives the app's all-lines mode)"
) {
    private val data by option("--data", help = "Converted city directory containing lines.bin (or the lines.bin itself)").required()
    private val output by option("--output", help = "Output HTML file").default("network_map.html")
    private val noReveal by option("--no-reveal", help = "Disable the staggered 2 s reveal (draw all lines at once)").flag(default = false)
    private val basemap by option("--basemap", help = "MapLibre GL style URL for the basemap")
        .default("https://tiles.openfreemap.org/styles/positron")

    /** One line's decoded geometry: [paths] is one polyline per direction, each point being [lon, lat]. */
    private class Line(
        val name: String,
        val color: String,
        val transportType: Int,
        val paths: List<List<DoubleArray>>
    )

    private fun readString(buffer: ByteBuffer): String {
        val length = buffer.short.toInt() and 0xFFFF
        val bytes = ByteArray(length)
        buffer.get(bytes)
        return String(bytes, Charsets.UTF_8)
    }

    /** Parses the RLN2 lines.bin (see LinesWriter): header, then per line name/colour/paths with
     *  delta-encoded x (lon) and y (lat) integer coordinates scaled by `coordScale`. */
    private fun readLines(file: File): List<Line> {
        val buffer = ByteBuffer.wrap(file.readBytes()).order(ByteOrder.LITTLE_ENDIAN)

        val magic = ByteArray(4)
        buffer.get(magic)
        require(String(magic, Charsets.US_ASCII) == "RLN2") {
            "Invalid lines.bin magic '${String(magic, Charsets.US_ASCII)}' (expected RLN2)"
        }
        buffer.short // schema version
        val coordScale = (buffer.int.toLong() and 0xFFFFFFFF).toDouble()
        val lineCount = buffer.int

        val lines = ArrayList<Line>(lineCount)
        repeat(lineCount) {
            buffer.int // lineIdInternal
            val name = readString(buffer)
            val color = readString(buffer)
            readString(buffer) // textColor (unused for line rendering)
            val transportType = buffer.short.toInt() and 0xFFFF
            val pathCount = buffer.short.toInt() and 0xFFFF

            val paths = ArrayList<List<DoubleArray>>(pathCount)
            repeat(pathCount) {
                buffer.short // directionId
                val pointCount = buffer.int
                val xs = IntArray(pointCount) { buffer.int }
                val ys = IntArray(pointCount) { buffer.int }
                // Delta decode (inverse of TimeCompressor.encodeTimes): first value absolute, then cumulative.
                val pts = ArrayList<DoubleArray>(pointCount)
                var x = 0
                var y = 0
                for (i in 0 until pointCount) {
                    x = if (i == 0) xs[0] else x + xs[i]
                    y = if (i == 0) ys[0] else y + ys[i]
                    pts.add(doubleArrayOf(x / coordScale, y / coordScale)) // [lon, lat]
                }
                paths.add(pts)
            }
            lines.add(Line(name, color, transportType, paths))
        }
        return lines
    }

    /** Normalizes a GTFS route_color (hex, usually without '#') to a CSS colour, with a fallback. */
    private fun cssColor(raw: String): String {
        val hex = raw.trim().removePrefix("#")
        return if (hex.length == 6 && hex.all { it.isDigit() || it.lowercaseChar() in 'a'..'f' }) "#$hex" else "#8a8f98"
    }

    /** GTFS route_type → reveal priority so major modes (metro/tram/rail) sweep in before buses,
     *  mirroring the app's "strong lines first" ordering. */
    private fun revealPriority(routeType: Int): Int = when (routeType) {
        1 -> 0   // metro/subway
        0 -> 1   // tram
        2 -> 2   // rail
        else -> 3 // bus / coach / other
    }

    private fun jsonEscape(s: String): String = buildString {
        for (c in s) when (c) {
            '\\' -> append("\\\\"); '"' -> append("\\\""); '\n' -> append("\\n"); '\r' -> append("\\r"); '\t' -> append("\\t")
            else -> if (c < ' ') append("\\u%04x".format(c.code)) else append(c)
        }
    }

    override fun run() {
        val dataFile = File(data)
        val linesFile = if (dataFile.isDirectory) File(dataFile, "lines.bin") else dataFile
        if (!linesFile.exists()) {
            throw RuntimeException(
                "lines.bin not found at ${linesFile.absolutePath}.\n" +
                    "Convert the city with line geometry first, e.g.:\n" +
                    "  ./gradlew run --args=\"convert --input <gtfs> --output <dir> --traces\""
            )
        }

        println("Reading ${linesFile.absolutePath}...")
        val lines = readLines(linesFile)
        val pathCount = lines.sumOf { it.paths.size }
        println("Found ${lines.size} lines ($pathCount directional paths)")
        if (lines.isEmpty()) throw RuntimeException("lines.bin contains no lines")

        // Reveal rank in [0,1] per line: order by mode priority then name, so the sweep goes
        // structuring modes → buses. Both directions of a line share the line's rank.
        val order = lines.indices.sortedWith(
            compareBy({ revealPriority(lines[it].transportType) }, { lines[it].name })
        )
        val rankByLine = DoubleArray(lines.size)
        val denom = (lines.size - 1).coerceAtLeast(1).toDouble()
        for ((sortedPos, lineIdx) in order.withIndex()) rankByLine[lineIdx] = sortedPos / denom

        // Bounds + GeoJSON (one Feature per directional path).
        var minLon = Double.MAX_VALUE; var minLat = Double.MAX_VALUE
        var maxLon = -Double.MAX_VALUE; var maxLat = -Double.MAX_VALUE
        val features = StringBuilder()
        var first = true
        for (i in lines.indices) {
            val line = lines[i]
            val color = cssColor(line.color)
            val rank = rankByLine[i]
            for (path in line.paths) {
                if (path.size < 2) continue
                if (!first) features.append(",\n")
                first = false
                features.append("{\"type\":\"Feature\",\"properties\":{")
                    .append("\"name\":\"").append(jsonEscape(line.name)).append("\",")
                    .append("\"color\":\"").append(color).append("\",")
                    .append("\"rank\":").append("%.5f".format(rank))
                    .append("},\"geometry\":{\"type\":\"LineString\",\"coordinates\":[")
                for ((p, pt) in path.withIndex()) {
                    if (p > 0) features.append(',')
                    features.append('[').append("%.6f".format(pt[0])).append(',').append("%.6f".format(pt[1])).append(']')
                    if (pt[0] < minLon) minLon = pt[0]; if (pt[0] > maxLon) maxLon = pt[0]
                    if (pt[1] < minLat) minLat = pt[1]; if (pt[1] > maxLat) maxLat = pt[1]
                }
                features.append("]}}")
            }
        }

        val reveal = !noReveal
        val html = buildHtml(features.toString(), lines.size, pathCount, minLon, minLat, maxLon, maxLat, reveal)
        File(output).writeText(html)
        println("Map generated: ${File(output).absolutePath}${if (reveal) " (with staggered reveal)" else ""}")
    }

    private fun buildHtml(
        features: String, lineCount: Int, pathCount: Int,
        minLon: Double, minLat: Double, maxLon: Double, maxLat: Double, reveal: Boolean
    ): String = """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8" />
    <title>RAPTOR Network — all lines</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <script src="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js"></script>
    <link href="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.css" rel="stylesheet" />
    <style>
        body { margin: 0; padding: 0; font-family: system-ui, sans-serif; }
        #map { position: absolute; top: 0; bottom: 0; width: 100%; }
        .info { position: absolute; top: 12px; right: 12px; background: rgba(255,255,255,0.95);
                padding: 12px 14px; border-radius: 10px; box-shadow: 0 2px 12px rgba(0,0,0,0.18); z-index: 1; }
        .info h3 { margin: 0 0 6px 0; font-size: 14px; }
        .info div { font-size: 12px; color: #444; margin: 2px 0; }
    </style>
</head>
<body>
    <div id="map"></div>
    <div class="info">
        <h3>🕸️ Réseau complet</h3>
        <div><strong>Lignes:</strong> $lineCount</div>
        <div><strong>Tracés:</strong> $pathCount</div>
    </div>
    <script>
        const geojson = { "type": "FeatureCollection", "features": [
$features
        ]};
        const REVEAL = $reveal;
        const LINE_COUNT = $lineCount;

        const map = new maplibregl.Map({
            container: 'map',
            style: '$basemap',
            bounds: [[$minLon, $minLat], [$maxLon, $maxLat]],
            fitBoundsOptions: { padding: 40 }
        });
        map.addControl(new maplibregl.NavigationControl(), 'top-left');

        map.on('load', () => {
            map.addSource('lines', { type: 'geojson', data: geojson });
            map.addLayer({
                id: 'lines', type: 'line', source: 'lines',
                layout: { 'line-cap': 'round', 'line-join': 'round' },
                paint: {
                    'line-color': ['get', 'color'],
                    'line-opacity': 0.85,
                    'line-width': ['interpolate', ['linear'], ['zoom'], 8, 1.5, 12, 2.5, 16, 5]
                }
            });

            const popup = new maplibregl.Popup({ closeButton: false, closeOnClick: false });
            map.on('mousemove', 'lines', (e) => {
                map.getCanvas().style.cursor = 'pointer';
                const f = e.features[0];
                popup.setLngLat(e.lngLat).setHTML('<strong>' + f.properties.name + '</strong>').addTo(map);
            });
            map.on('mouseleave', 'lines', () => { map.getCanvas().style.cursor = ''; popup.remove(); });

            if (REVEAL) {
                // Exact timing of the app's removed all-lines reveal.
                map.setFilter('lines', ['<=', ['get', 'rank'], -0.001]);
                const durationMs = Math.max(LINE_COUNT * 12, 1200); // REVEAL_MS_PER_LINE = 12
                const waves = Math.max(Math.floor(LINE_COUNT / 4), 1); // REVEAL_LINES_PER_WAVE = 4
                const stepMs = Math.max(Math.floor(durationMs / waves), 50);
                setTimeout(() => { // REVEAL_PARSE_GRACE_MS = 500
                    let w = 0;
                    const timer = setInterval(() => {
                        w++;
                        map.setFilter('lines', ['<=', ['get', 'rank'], w / waves]);
                        if (w >= waves) { clearInterval(timer); map.setFilter('lines', null); }
                    }, stepMs);
                }, 500);
            }
        });
    </script>
</body>
</html>
"""
}
