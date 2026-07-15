package com.raptor

import com.raptor.gtfs.CalendarAnalyzer
import com.raptor.gtfs.GTFSReader
import com.raptor.gtfs.models.ConvertConfig
import com.raptor.gtfs.models.Manifest
import com.raptor.gtfs.models.RouteData
import com.raptor.gtfs.models.ServicePeriod
import com.raptor.optimization.NetworkIndexBuilder
import com.raptor.output.BinarySerializer
import com.raptor.output.JsonSerializer
import com.raptor.output.LinesSerializer
import com.raptor.transform.LineGeometryBuilder
import com.raptor.transform.RouteBuilder
import com.raptor.transform.StopBuilder
import com.raptor.transform.TransferBuilder
import com.raptor.transform.TripBuilder
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import java.io.File
import java.time.ZoneOffset
import java.time.ZonedDateTime
import java.time.format.DateTimeFormatter

object PipelineConverter {
    fun convert(
        inputPath: String,
        outputPath: String,
        config: ConvertConfig,
        periodAnalyzer: ((GTFSReader) -> List<ServicePeriod>)? = null
    ): Manifest {
        println("Starting conversion: $inputPath -> $outputPath")
        val startTime = ZonedDateTime.now(ZoneOffset.UTC)

        val reader = GTFSReader(inputPath)
        reader.readAll(skipStopTimes = config.dryRun)

        val periods = resolvePeriods(reader, config, periodAnalyzer)

        if (config.dryRun) {
            return printDryRunPlan(reader, periods, inputPath, startTime)
        }

        println("Building routes and trips from GTFS data...")
        val routes = RouteBuilder.buildRoutes(reader)
        TripBuilder.buildAndSortTrips(reader, routes, allowPartial = config.allowPartialTrips)
        val totalTrips = routes.sumOf { it.trips.size }
        println("Built ${routes.size} routes with $totalTrips trips total")

        var linesWritten = false
        if (config.genTraces) {
            reader.readShapes()
            val lines = LineGeometryBuilder.buildLines(reader)
            if (lines.isNotEmpty()) {
                val linesDir = if (config.flatOutput && !config.pelo) File(outputPath, "raptor") else File(outputPath)
                LinesSerializer.writeLinesFile(linesDir, lines, Version.SCHEMA_VERSION)
                linesWritten = true
            } else {
                println("WARNING: --traces requested but no usable shapes.txt geometry was found; skipping lines.bin")
            }
        }

        if (periods != null && periods.isNotEmpty()) {
            val manifests = mutableListOf<Manifest>()
            val periodManifests = mutableListOf<Pair<ServicePeriod, Manifest>>()
            val baseOutput = File(outputPath)

            for (period in periods) {
                println("\n============================================================")
                println("Processing period: ${period.name}")
                println("Description: ${period.description}")
                println("Services: ${period.serviceIds.size}")
                println("============================================================\n")

                val periodTripIds = CalendarAnalyzer.getTripsForPeriod(reader, period)
                println("Found ${periodTripIds.size} trips for period ${period.name}")

                val filteredRoutes = filterRoutesByTrips(routes, periodTripIds)
                println("After filtering: ${filteredRoutes.size} routes with trips in this period")

                val periodOutput: File
                val periodSuffix: String
                when {
                    config.pelo -> {
                        periodOutput = baseOutput
                        periodSuffix = "_${period.name}"
                    }
                    config.flatOutput -> {
                        periodOutput = File(baseOutput, "raptor")
                        periodSuffix = "_${period.name}"
                    }
                    else -> {
                        periodOutput = File(baseOutput, period.name)
                        periodSuffix = ""
                    }
                }

                val manifest = writePeriodOutput(
                    reader, filteredRoutes, periodOutput, config, startTime, inputPath,
                    periodName = period.name, suffix = periodSuffix, writeManifest = !(config.flatOutput || config.pelo)
                )
                manifests.add(manifest)
                periodManifests.add(Pair(period, manifest))
            }

            if (!config.pelo) {
                writeRootIndex(baseOutput, config, periodManifests, linesWritten, inputPath, startTime)
            }

            println("\n============================================================")
            println("Generated ${manifests.size} period folders:")
            for (period in periods) {
                println("  - ${period.name}: ${period.description}")
            }
            println("============================================================\n")

            return manifests[0]
        } else {
            val singleManifest = writePeriodOutput(
                reader, routes, File(outputPath), config, startTime, inputPath, periodName = null
            )
            val singlePeriod = ServicePeriod("all", mutableListOf(), "Complete dataset")
            writeRootIndex(File(outputPath), config, listOf(Pair(singlePeriod, singleManifest)), linesWritten, inputPath, startTime)
            return singleManifest
        }
    }

    private fun resolvePeriods(
        reader: GTFSReader,
        config: ConvertConfig,
        periodAnalyzer: ((GTFSReader) -> List<ServicePeriod>)?
    ): List<ServicePeriod>? {
        if (!config.splitByPeriods && !config.dryRun) return null
        val periods = if (periodAnalyzer != null) {
            println("Using custom period analyzer")
            periodAnalyzer(reader)
        } else {
            CalendarAnalyzer.analyzeServicePeriods(reader)
        }
        if (periods.isEmpty()) {
            println("WARNING: Period splitting requested but no calendar data found; generating a single output")
            return null
        }
        return periods
    }

    private fun printDryRunPlan(
        reader: GTFSReader,
        periods: List<ServicePeriod>?,
        inputPath: String,
        startTime: ZonedDateTime
    ): Manifest {
        val tripCounts = reader.tripsData.groupingBy { it.serviceId }.eachCount()

        println("\nDry run — no files were written.")
        println("Input: $inputPath")
        val periodCount: Int
        if (periods == null || periods.isEmpty()) {
            println("Period split: none — a single output would be generated.")
            periodCount = 0
        } else {
            println("Would generate ${periods.size} period folder(s):")
            for (period in periods) {
                val nTrips = period.serviceIds.sumOf { tripCounts[it] ?: 0 }
                println("  ${period.name.padEnd(22)} ${period.serviceIds.size.toString().padStart(4)} service(s)  ${nTrips.toString().padStart(8)} trips   ${period.description}")
            }
            periodCount = periods.size
        }

        return Manifest(
            schemaVersion = Version.SCHEMA_VERSION,
            toolVersion = Version.VERSION,
            createdAtIso = startTime.format(DateTimeFormatter.ISO_INSTANT),
            inputs = mapOf("gtfs_path" to inputPath, "dry_run" to "true"),
            outputs = emptyMap(),
            stats = mapOf("periods" to periodCount),
            build = mapOf("platform" to System.getProperty("os.name"), "java" to System.getProperty("java.version"))
        )
    }

    private fun filterRoutesByTrips(routes: List<RouteData>, periodTripIds: Set<String>): List<RouteData> {
        val filteredRoutes = mutableListOf<RouteData>()
        for (route in routes) {
            val filteredTrips = route.trips.filter { it.tripIdGtfs in periodTripIds }.toMutableList()
            if (filteredTrips.isNotEmpty()) {
                filteredRoutes.add(route.copy(trips = filteredTrips))
            }
        }
        return filteredRoutes
    }

    private fun writePeriodOutput(
        reader: GTFSReader,
        routes: List<RouteData>,
        outputPath: File,
        config: ConvertConfig,
        startTime: ZonedDateTime,
        inputPath: String,
        periodName: String?,
        suffix: String = "",
        writeManifest: Boolean = true
    ): Manifest {
        val stops = StopBuilder.buildStops(reader, routes)
        TransferBuilder.buildTransfers(reader, stops, config.genTransfers, config.speedWalk, config.transferCutoff)

        val index = NetworkIndexBuilder.buildNetworkIndex(routes, stops)

        val filesWritten = mutableMapOf<String, String>()

        if (config.format == "binary" || config.format == "both") {
            filesWritten.putAll(BinarySerializer.writeBinaryFiles(
                outputPath, routes, stops, index, Version.SCHEMA_VERSION, config.compression, suffix, config.writeIndex
            ))
        }

        if (config.format == "json" || config.format == "both" || config.debugJson) {
            filesWritten.putAll(JsonSerializer.writeJsonFiles(
                outputPath, routes, stops, index, suffix, config.writeIndex
            ))
        }

        val checksums = mutableMapOf<String, String>()
        for ((filename, filepath) in filesWritten) {
            val fileBytes = File(filepath).readBytes()
            val md = java.security.MessageDigest.getInstance("SHA-256")
            val digest = md.digest(fileBytes)
            checksums[filename] = digest.joinToString("") { "%02x".format(it) }
        }

        val stats = mapOf(
            "stops" to stops.size,
            "routes" to routes.size,
            "trips" to routes.sumOf { it.trips.size },
            "stop_times" to routes.sumOf { it.stopIds.size * it.trips.size },
            "transfers" to stops.sumOf { it.transfers.size }
        )

        val manifestInputs = mutableMapOf("gtfs_path" to inputPath)
        if (periodName != null) {
            manifestInputs["period"] = periodName
        }

        val manifest = Manifest(
            schemaVersion = Version.SCHEMA_VERSION,
            toolVersion = Version.VERSION,
            createdAtIso = startTime.format(DateTimeFormatter.ISO_INSTANT),
            inputs = manifestInputs,
            outputs = checksums,
            stats = stats,
            build = mapOf("platform" to System.getProperty("os.name"), "java" to System.getProperty("java.version"))
        )

        if (writeManifest) {
            val manifestPath = File(outputPath, "manifest$suffix.json")
            val jsonFormat = Json { prettyPrint = true }
            manifestPath.writeText(jsonFormat.encodeToString(manifest))
            println("Wrote manifest to $manifestPath")
        }

        if (periodName != null) {
            println("Period '$periodName' completed")
        } else {
            val elapsed = java.time.Duration.between(startTime, ZonedDateTime.now(ZoneOffset.UTC)).toMillis() / 1000.0
            println("Conversion completed in ${String.format("%.2f", elapsed)}s")
        }

        return manifest
    }

    private fun writeRootIndex(
        baseOutput: File,
        config: ConvertConfig,
        periodManifests: List<Pair<ServicePeriod, Manifest>>,
        linesWritten: Boolean,
        inputPath: String,
        startTime: ZonedDateTime
    ) {
        val layout = when {
            config.flatOutput -> "flat"
            periodManifests.size == 1 && periodManifests[0].first.name == "all" -> "single"
            else -> "nested"
        }

        fun relPath(periodName: String, filename: String): String {
            return when (layout) {
                "nested" -> "$periodName/$filename"
                "flat" -> "raptor/$filename"
                else -> filename
            }
        }

        @kotlinx.serialization.Serializable
        data class PeriodIndex(
            val name: String,
            val description: String,
            val files: Map<String, String>,
            val checksums: Map<String, String>,
            val stats: Map<String, Int>
        )

        @kotlinx.serialization.Serializable
        data class DatasetIndex(
            @kotlinx.serialization.SerialName("schema_version")
            val schemaVersion: Int,
            @kotlinx.serialization.SerialName("tool_version")
            val toolVersion: String,
            val createdAt: String,
            val input: Map<String, String>,
            val layout: String,
            val lines: Map<String, String>?,
            val periods: List<PeriodIndex>
        )

        val periodsIndex = mutableListOf<PeriodIndex>()
        for ((period, manifest) in periodManifests) {
            val files = mutableMapOf<String, String>()
            for (fname in manifest.outputs.keys) {
                if (fname.endsWith(".bin")) {
                    if (fname.startsWith("routes")) files["routes"] = relPath(period.name, fname)
                    if (fname.startsWith("stops")) files["stops"] = relPath(period.name, fname)
                    if (fname.startsWith("index")) files["index"] = relPath(period.name, fname)
                }
            }

            val checksums = manifest.outputs.mapKeys { relPath(period.name, it.key) }

            periodsIndex.add(PeriodIndex(
                name = period.name,
                description = period.description,
                files = files,
                checksums = checksums,
                stats = manifest.stats
            ))
        }

        val linesMap = if (linesWritten) {
            mapOf(
                "file" to (if (layout == "flat") "raptor/lines.bin" else "lines.bin"),
                "coord_scale" to LinesSerializer.COORD_SCALE.toString()
            )
        } else null

        val index = DatasetIndex(
            schemaVersion = Version.SCHEMA_VERSION,
            toolVersion = Version.VERSION,
            createdAt = startTime.format(DateTimeFormatter.ISO_INSTANT),
            input = mapOf("gtfs_path" to inputPath),
            layout = layout,
            lines = linesMap,
            periods = periodsIndex
        )

        val indexPath = File(baseOutput, "dataset.json")
        val jsonFormat = Json { prettyPrint = true }
        indexPath.writeText(jsonFormat.encodeToString(index))
        println("Wrote dataset index to $indexPath")
    }
}
