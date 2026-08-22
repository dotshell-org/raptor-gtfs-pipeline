package eu.dotshell.raptor.gtfs.pipeline

import eu.dotshell.raptor.gtfs.pipeline.gtfs.CalendarAnalyzer
import eu.dotshell.raptor.gtfs.pipeline.gtfs.DatasetValidity
import eu.dotshell.raptor.gtfs.pipeline.gtfs.GTFSReader
import eu.dotshell.raptor.gtfs.pipeline.gtfs.ValidityAnalyzer
import eu.dotshell.raptor.gtfs.pipeline.gtfs.models.ConvertConfig
import eu.dotshell.raptor.gtfs.pipeline.gtfs.models.DatasetIndex
import eu.dotshell.raptor.gtfs.pipeline.gtfs.models.Manifest
import eu.dotshell.raptor.gtfs.pipeline.gtfs.models.PeriodIndex
import eu.dotshell.raptor.gtfs.pipeline.gtfs.models.RouteData
import eu.dotshell.raptor.gtfs.pipeline.gtfs.models.ServicePeriod
import eu.dotshell.raptor.gtfs.pipeline.optimization.NetworkIndexBuilder
import eu.dotshell.raptor.gtfs.pipeline.output.BinarySerializer
import eu.dotshell.raptor.gtfs.pipeline.output.JsonSerializer
import eu.dotshell.raptor.gtfs.pipeline.output.LinesSerializer
import eu.dotshell.raptor.gtfs.pipeline.transform.LineGeometryBuilder
import eu.dotshell.raptor.gtfs.pipeline.transform.RouteBuilder
import eu.dotshell.raptor.gtfs.pipeline.transform.StopBuilder
import eu.dotshell.raptor.gtfs.pipeline.transform.TransferBuilder
import eu.dotshell.raptor.gtfs.pipeline.transform.TripBuilder
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
        periodAnalyzer: ((GTFSReader) -> List<ServicePeriod>)? = null,
        sourceLabel: String? = null
    ): ConversionOutcome {
        PipelineLog.info("Starting conversion: $inputPath -> $outputPath")
        // What the manifests record as the input. A feed arriving as a zip is read from a
        // temporary directory whose name means nothing to anyone reading dataset.json later;
        // a caller that knows where the feed actually came from says so here.
        val recordedInput = sourceLabel ?: inputPath
        val startTime = ZonedDateTime.now(ZoneOffset.UTC)

        val reader = GTFSReader(inputPath)
        reader.readAll(skipStopTimes = config.dryRun)

        val periods = resolvePeriods(reader, config, periodAnalyzer)

        // How long this dataset may be trusted. Computed from the feed itself so the
        // apps can surface an expiry instead of silently serving stale timetables.
        val validity = ValidityAnalyzer.analyze(reader.feedInfo, reader.calendar, reader.calendarDates)
        PipelineLog.info("Dataset validity: ${validity.startDate ?: "?"} -> ${validity.endDate ?: "?"} (source: ${validity.source})")

        if (config.dryRun) {
            return ConversionOutcome(dataset = null, manifests = listOf(printDryRunPlan(reader, periods, recordedInput, startTime)))
        }

        PipelineLog.info("Building routes and trips from GTFS data...")
        val routes = RouteBuilder.buildRoutes(reader)
        TripBuilder.buildAndSortTrips(reader, routes, allowPartial = config.allowPartialTrips)
        val totalTrips = routes.sumOf { it.trips.size }
        PipelineLog.info("Built ${routes.size} routes with $totalTrips trips total")

        var linesWritten = false
        if (config.genTraces) {
            reader.readShapes()
            val lines = LineGeometryBuilder.buildLines(reader)
            if (lines.isNotEmpty()) {
                val linesDir = if (config.flatOutput) File(outputPath, "raptor") else File(outputPath)
                LinesSerializer.writeLinesFile(linesDir, lines, Version.SCHEMA_VERSION)
                linesWritten = true
            } else {
                PipelineLog.info("WARNING: --traces requested but no usable shapes.txt geometry was found; skipping lines.bin")
            }
        }

        if (periods != null && periods.isNotEmpty()) {
            val manifests = mutableListOf<Manifest>()
            val periodManifests = mutableListOf<Pair<ServicePeriod, Manifest>>()
            val baseOutput = File(outputPath)

            for (period in periods) {
                PipelineLog.info("\n============================================================")
                PipelineLog.info("Processing period: ${period.name}")
                PipelineLog.info("Description: ${period.description}")
                PipelineLog.info("Services: ${period.serviceIds.size}")
                PipelineLog.info("============================================================\n")

                val periodTripIds = CalendarAnalyzer.getTripsForPeriod(reader, period)
                PipelineLog.info("Found ${periodTripIds.size} trips for period ${period.name}")

                val filteredRoutes = filterRoutesByTrips(routes, periodTripIds)
                PipelineLog.info("After filtering: ${filteredRoutes.size} routes with trips in this period")

                val periodOutput: File
                val periodSuffix: String
                when {
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
                    reader, filteredRoutes, periodOutput, config, startTime, recordedInput,
                    periodName = period.name, suffix = periodSuffix, writeManifest = !config.flatOutput
                )
                manifests.add(manifest)
                periodManifests.add(Pair(period, manifest))
            }

            val dataset = writeRootIndex(baseOutput, config, periodManifests, linesWritten, recordedInput, startTime, validity)

            PipelineLog.info("\n============================================================")
            PipelineLog.info("Generated ${manifests.size} period folders:")
            for (period in periods) {
                PipelineLog.info("  - ${period.name}: ${period.description}")
            }
            PipelineLog.info("============================================================\n")

            return ConversionOutcome(dataset, manifests)
        } else {
            val singleManifest = writePeriodOutput(
                reader, routes, File(outputPath), config, startTime, recordedInput, periodName = null
            )
            val singlePeriod = ServicePeriod("all", mutableListOf(), "Complete dataset")
            val dataset = writeRootIndex(
                File(outputPath), config, listOf(Pair(singlePeriod, singleManifest)),
                linesWritten, recordedInput, startTime, validity
            )
            return ConversionOutcome(dataset, listOf(singleManifest))
        }
    }

    private fun resolvePeriods(
        reader: GTFSReader,
        config: ConvertConfig,
        periodAnalyzer: ((GTFSReader) -> List<ServicePeriod>)?
    ): List<ServicePeriod>? {
        if (!config.splitByPeriods && !config.dryRun) return null
        val periods = if (periodAnalyzer != null) {
            PipelineLog.info("Using custom period analyzer")
            periodAnalyzer(reader)
        } else {
            CalendarAnalyzer.analyzeServicePeriods(reader)
        }
        if (periods.isEmpty()) {
            PipelineLog.info("WARNING: Period splitting requested but no calendar data found; generating a single output")
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

        PipelineLog.info("\nDry run — no files were written.")
        PipelineLog.info("Input: $inputPath")
        val periodCount: Int
        if (periods == null || periods.isEmpty()) {
            PipelineLog.info("Period split: none — a single output would be generated.")
            periodCount = 0
        } else {
            PipelineLog.info("Would generate ${periods.size} period folder(s):")
            for (period in periods) {
                val nTrips = period.serviceIds.sumOf { tripCounts[it] ?: 0 }
                PipelineLog.info("  ${period.name.padEnd(22)} ${period.serviceIds.size.toString().padStart(4)} service(s)  ${nTrips.toString().padStart(8)} trips   ${period.description}")
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

    /**
     * The trips of one route that belong to a period, each departure kept once.
     *
     * A period spans several days, and an operator commonly gives each day its own service id
     * carrying an identical timetable. Unioned, the same departure arrives here five times over —
     * 22 % of the trips of a school-term week — and a timetable listing 05:00 three times reads as
     * a line running three times as often. Two trips of one route with the same times at the same
     * stops are the same departure, whatever their trip ids: the first is kept, the copies dropped.
     *
     * This belongs here rather than in TripBuilder, which builds routes across the whole feed
     * before any period exists. Deduplicating there keeps one trip per distinct timetable for the
     * entire season, and the survivor's id belongs to whichever service happened to come first —
     * so the period filter below then drops it, taking a real departure with it.
     */
    internal fun filterRoutesByTrips(routes: List<RouteData>, periodTripIds: Set<String>): List<RouteData> {
        val filteredRoutes = mutableListOf<RouteData>()
        for (route in routes) {
            val seen = HashSet<List<Float>>()
            val filteredTrips = route.trips
                .filter { it.tripIdGtfs in periodTripIds && seen.add(it.arrivalTimes) }
                .toMutableList()
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
            PipelineLog.info("Wrote manifest to $manifestPath")
        }

        if (periodName != null) {
            PipelineLog.info("Period '$periodName' completed")
        } else {
            val elapsed = java.time.Duration.between(startTime, ZonedDateTime.now(ZoneOffset.UTC)).toMillis() / 1000.0
            PipelineLog.info("Conversion completed in ${String.format("%.2f", elapsed)}s")
        }

        return manifest
    }

    private fun writeRootIndex(
        baseOutput: File,
        config: ConvertConfig,
        periodManifests: List<Pair<ServicePeriod, Manifest>>,
        linesWritten: Boolean,
        inputPath: String,
        startTime: ZonedDateTime,
        validity: DatasetValidity
    ): DatasetIndex {
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
            stopsSchemaVersion = Version.STOPS_SCHEMA_VERSION,
            toolVersion = Version.VERSION,
            createdAt = startTime.format(DateTimeFormatter.ISO_INSTANT),
            input = mapOf("gtfs_path" to inputPath),
            layout = layout,
            lines = linesMap,
            validity = validity,
            periods = periodsIndex
        )

        val indexPath = File(baseOutput, "dataset.json")
        val jsonFormat = Json { prettyPrint = true }
        indexPath.writeText(jsonFormat.encodeToString(index))
        PipelineLog.info("Wrote dataset index to $indexPath")
        return index
    }
}
