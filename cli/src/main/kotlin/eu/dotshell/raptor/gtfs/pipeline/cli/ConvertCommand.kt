package eu.dotshell.raptor.gtfs.pipeline.cli

import com.github.ajalt.clikt.core.CliktCommand
import com.github.ajalt.clikt.parameters.options.default
import com.github.ajalt.clikt.parameters.options.flag
import com.github.ajalt.clikt.parameters.options.option
import com.github.ajalt.clikt.parameters.options.required
import com.github.ajalt.clikt.parameters.types.double
import com.github.ajalt.clikt.parameters.types.int
import eu.dotshell.raptor.gtfs.pipeline.ConvertRequest
import eu.dotshell.raptor.gtfs.pipeline.Pipeline
import eu.dotshell.raptor.gtfs.pipeline.gtfs.models.ConvertConfig
import kotlin.io.path.Path

/**
 * Argument parsing, and nothing else: extraction, profiles and conversion all live in the
 * library, so this front end and a server driving it can never diverge on what a flag means.
 */
class ConvertCommand : CliktCommand(name = "convert", help = "Convert GTFS to binary format") {
    private val input by option("--input", help = "Path to GTFS directory or ZIP file").required()
    private val output by option("--output", help = "Output directory").default("./raptor_data")
    private val format by option("--format", help = "Output format").default("binary")
    private val compression by option("--compression", help = "Enable delta compression").flag(default = true)
    private val debugJson by option("--debug-json", help = "Generate debug JSON files").flag(default = false)
    private val genTransfers by option("--gen-transfers", help = "Generate walking transfers").flag(default = false)
    private val allowPartialTrips by option("--allow-partial-trips", help = "Allow partial trips").flag(default = false)
    private val speedWalk by option("--speed-walk", help = "Walking speed in m/s").double().default(1.33)
    private val transferCutoff by option("--transfer-cutoff", help = "Transfer generation cutoff in meters").int().default(500)
    private val jobs by option("--jobs", help = "Number of parallel jobs").int().default(1)
    private val splitByPeriods by option("--split-by-periods", help = "Generate separate folders per service period").flag(default = false)
    private val traces by option("--traces", help = "Generate line geometry from shapes.txt").flag(default = false)
    private val dryRun by option("--dry-run", help = "Print the service-period plan without writing any files").flag(default = false)
    private val profile by option("--profile", help = "Path to a YAML period profile")
    private val flat by option("--flat", help = "Group app-ready per-period files under raptor/").flag(default = false)
    private val noIndex by option("--no-index", help = "Skip index.bin").flag(default = false)

    override fun run() {
        val request = ConvertRequest(
            input = Path(input),
            output = Path(output),
            profile = profile?.let { Path(it) },
            config = ConvertConfig(
                format = format,
                compression = compression,
                debugJson = debugJson,
                genTransfers = genTransfers,
                allowPartialTrips = allowPartialTrips,
                speedWalk = speedWalk,
                transferCutoff = transferCutoff,
                jobs = jobs,
                splitByPeriods = splitByPeriods,
                genTraces = traces,
                flatOutput = flat,
                writeIndex = !noIndex
            )
        )

        try {
            if (dryRun) {
                Pipeline.dryRun(request)
                return
            }

            val dataset = Pipeline.convert(request)
            println("\nConversion successful!")
            println("Output directory: $output")
            for (period in dataset.periods) {
                println("  ${period.name}: ${period.stats}")
            }
        } catch (e: Exception) {
            System.err.println("Error: ${e.message}")
            e.printStackTrace()
            kotlin.system.exitProcess(1)
        }
    }
}
