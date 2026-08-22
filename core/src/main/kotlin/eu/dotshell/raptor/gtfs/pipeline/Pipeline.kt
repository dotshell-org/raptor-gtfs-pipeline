package eu.dotshell.raptor.gtfs.pipeline

import eu.dotshell.raptor.gtfs.pipeline.gtfs.GTFSReader
import eu.dotshell.raptor.gtfs.pipeline.gtfs.ProfileAnalyzer
import eu.dotshell.raptor.gtfs.pipeline.gtfs.models.ConvertConfig
import eu.dotshell.raptor.gtfs.pipeline.gtfs.models.DatasetIndex
import eu.dotshell.raptor.gtfs.pipeline.gtfs.models.Manifest
import eu.dotshell.raptor.gtfs.pipeline.gtfs.models.ServicePeriod
import kotlinx.serialization.json.Json
import java.nio.file.Files
import java.nio.file.Path
import java.util.zip.ZipFile
import kotlin.io.path.extension
import kotlin.io.path.isDirectory
import kotlin.io.path.isRegularFile

/**
 * One conversion: a GTFS feed in, a directory of RAPTOR binaries out.
 */
data class ConvertRequest(
    /** A GTFS directory, or a `.zip` — extracted to a temporary directory that is always cleaned up. */
    val input: Path,
    /** Where the binaries and `dataset.json` are written. Created if missing. */
    val output: Path,
    /** A YAML period profile. Supplying one implies splitting by period. */
    val profile: Path? = null,
    /** Everything else. The defaults produce a single, uncompressed-index binary dataset. */
    val config: ConvertConfig = ConvertConfig(),
    /**
     * What `dataset.json` should record as the input, when [input] is not the honest answer.
     * A zip is read from a temporary directory whose name tells a later reader nothing; a
     * publisher that downloaded the feed puts the upstream URL here.
     */
    val sourceLabel: String? = null
)

/** What a conversion produced. */
data class ConversionOutcome(
    /** The `dataset.json` written at the output root, or null for a dry run, which writes nothing. */
    val dataset: DatasetIndex?,
    /** One manifest per period written, in the order the periods were produced. */
    val manifests: List<Manifest>
)

/**
 * The library entry point: what the CLI does, minus the argument parsing.
 *
 * ```kotlin
 * val dataset = Pipeline.convert(
 *     ConvertRequest(
 *         input = Path("GTFS_TCL.zip"),
 *         output = Path("out"),
 *         profile = Path("profiles/lyon.yaml"),
 *     )
 * )
 * println(dataset.validity.endDate)
 * ```
 *
 * Progress goes to [PipelineLog]; point its sink at your own logger before calling.
 */
object Pipeline {

    /**
     * Converts [request] and returns the dataset index written at the output root.
     *
     * @throws IllegalArgumentException if the config asks for a dry run — that writes no
     *   dataset, so there would be nothing to return; call [dryRun] instead.
     */
    fun convert(request: ConvertRequest): DatasetIndex {
        require(!request.config.dryRun) { "convert() writes a dataset; use dryRun() for a plan" }
        return run(request).dataset
            ?: error("conversion produced no dataset index")
    }

    /** Reports the period plan a real conversion would follow, writing nothing. */
    fun dryRun(request: ConvertRequest): Manifest =
        run(request.copy(config = request.config.copy(dryRun = true))).manifests.first()

    /**
     * Reads back the `dataset.json` at [datasetRoot] (a directory, or the file itself).
     *
     * Unknown fields are tolerated: a publisher reading a dataset written by a newer pipeline
     * should fail on formats it cannot parse — which [DatasetIndex.schemaVersion] tells it —
     * not on a field that was merely added.
     */
    fun readDataset(datasetRoot: Path): DatasetIndex {
        val file = if (datasetRoot.isDirectory()) datasetRoot.resolve("dataset.json") else datasetRoot
        return lenientJson.decodeFromString(DatasetIndex.serializer(), Files.readString(file))
    }

    private val lenientJson = Json { ignoreUnknownKeys = true }

    private fun run(request: ConvertRequest): ConversionOutcome {
        var extracted: Path? = null
        try {
            val gtfsDirectory = when {
                request.input.isDirectory() -> request.input
                request.input.isRegularFile() && request.input.extension.equals("zip", ignoreCase = true) -> {
                    val temporary = Files.createTempDirectory("raptor_gtfs_")
                    extracted = temporary
                    PipelineLog.info("Extracting GTFS ZIP file: ${request.input}")
                    extractZip(request.input, temporary)
                    locateFeed(temporary)
                }
                else -> throw IllegalArgumentException("not a GTFS directory or .zip: ${request.input}")
            }

            // A profile decides both the periods and part of the layout, so it has to be
            // loaded before the config is final rather than handed to the converter as-is.
            var config = request.config
            var periodAnalyzer: ((GTFSReader) -> List<ServicePeriod>)? = null
            if (request.profile != null) {
                val profile = ProfileAnalyzer.load(request.profile.toString())
                periodAnalyzer = { reader -> ProfileAnalyzer.build(profile, reader) }
                config = config.copy(
                    splitByPeriods = true,
                    flatOutput = config.flatOutput || profile.options.flatOutput,
                    writeIndex = config.writeIndex && profile.options.writeIndex
                )
            }

            Files.createDirectories(request.output)
            return PipelineConverter.convert(
                inputPath = gtfsDirectory.toAbsolutePath().toString(),
                outputPath = request.output.toAbsolutePath().toString(),
                config = config,
                periodAnalyzer = periodAnalyzer,
                sourceLabel = request.sourceLabel
            )
        } finally {
            extracted?.toFile()?.deleteRecursively()
        }
    }

    /**
     * A feed is a downloaded file, so an entry named `../../etc/something` is a case to
     * refuse rather than a case to trust: every entry must land inside [destination].
     */
    private fun extractZip(zip: Path, destination: Path) {
        val root = destination.toAbsolutePath().normalize()
        ZipFile(zip.toFile()).use { archive ->
            for (entry in archive.entries()) {
                val target = root.resolve(entry.name).normalize()
                require(target.startsWith(root)) {
                    "GTFS archive entry escapes the extraction directory: ${entry.name}"
                }
                if (entry.isDirectory) {
                    Files.createDirectories(target)
                } else {
                    Files.createDirectories(target.parent)
                    archive.getInputStream(entry).use { input ->
                        Files.newOutputStream(target).use { output -> input.copyTo(output) }
                    }
                }
            }
        }
    }

    /**
     * The directory holding the feed's `.txt` files — feeds are commonly zipped with an
     * enclosing folder, and some carry documentation alongside the data.
     */
    private fun locateFeed(extracted: Path): Path {
        Files.walk(extracted).use { paths ->
            val txt = paths
                .filter { it.isRegularFile() && it.extension.equals("txt", ignoreCase = true) }
                .findFirst()
                .orElseThrow { IllegalArgumentException("no .txt files found inside the GTFS archive") }
            PipelineLog.info("Using extracted GTFS directory: ${txt.parent}")
            return txt.parent
        }
    }
}
