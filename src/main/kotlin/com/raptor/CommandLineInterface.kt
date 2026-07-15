package com.raptor

import com.github.ajalt.clikt.core.CliktCommand
import com.github.ajalt.clikt.core.subcommands
import com.github.ajalt.clikt.parameters.options.*
import com.github.ajalt.clikt.parameters.types.double
import com.github.ajalt.clikt.parameters.types.int
import com.raptor.gtfs.GTFSReader
import com.raptor.gtfs.PeloPeriodAnalyzer
import com.raptor.gtfs.ProfileAnalyzer
import com.raptor.gtfs.models.ConvertConfig
import com.raptor.gtfs.models.ServicePeriod
import java.io.File
import java.nio.file.Files
import java.nio.file.Path
import java.util.zip.ZipFile

class CommandLineInterface : CliktCommand(name = "raptor-gtfs", help = "Convert GTFS datasets to RAPTOR binary format") {
    private val verbose by option("-v", "--verbose", help = "Verbose output").flag()

    override fun run() {
        if (verbose) {
            println("Verbose mode enabled")
        }
    }
}

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
    private val traces by option("--traces", "--tracés", help = "Generate line geometry from shapes.txt").flag(default = false)
    private val dryRun by option("--dry-run", help = "Print the service-period plan without writing any files").flag(default = false)
    private val profile by option("--profile", help = "Path to a YAML period profile")
    private val flat by option("--flat", help = "Group app-ready per-period files under raptor/").flag(default = false)
    private val noIndex by option("--no-index", help = "Skip index.bin").flag(default = false)
    private val pelo by option("--pelo", help = "Pelo app preset").flag(default = false)

    override fun run() {
        var tempDir: Path? = null
        try {
            val inputPath = File(input)
            val actualInput: String

            if (inputPath.isFile && inputPath.extension.equals("zip", ignoreCase = true)) {
                println("Extracting GTFS ZIP file: $inputPath")
                tempDir = Files.createTempDirectory("raptor_gtfs_")
                ZipFile(inputPath).use { zip ->
                    zip.entries().asSequence().forEach { entry ->
                        val destFile = File(tempDir.toFile(), entry.name)
                        if (entry.isDirectory) {
                            destFile.mkdirs()
                        } else {
                            destFile.parentFile?.mkdirs()
                            zip.getInputStream(entry).use { input ->
                                destFile.outputStream().use { output ->
                                    input.copyTo(output)
                                }
                            }
                        }
                    }
                }
                
                val txtFiles = tempDir.toFile().walkTopDown().filter { it.extension.equals("txt", ignoreCase = true) }.toList()
                if (txtFiles.isEmpty()) {
                    throw RuntimeException("No .txt files found inside the GTFS ZIP archive.")
                }
                actualInput = txtFiles[0].parentFile.absolutePath
                println("Using extracted GTFS directory: $actualInput")
            } else {
                actualInput = inputPath.absolutePath
            }

            var periodAnalyzer: ((GTFSReader) -> List<ServicePeriod>)? = null
            if (pelo) {
                periodAnalyzer = PeloPeriodAnalyzer::build
                if (profile != null) println("WARNING: --pelo overrides --profile")
            } else if (profile != null) {
                val loadedProfile = ProfileAnalyzer.load(profile!!)
                periodAnalyzer = { reader -> ProfileAnalyzer.build(loadedProfile, reader) }
            }

            val config = ConvertConfig(
                input_path = actualInput,
                output_path = output,
                format = format,
                compression = compression,
                debug_json = debugJson,
                gen_transfers = genTransfers,
                allow_partial_trips = allowPartialTrips,
                speed_walk = speedWalk,
                transfer_cutoff = transferCutoff,
                jobs = jobs,
                split_by_periods = splitByPeriods || profile != null || pelo,
                gen_traces = traces,
                dry_run = dryRun,
                flat_output = flat,
                write_index = !noIndex && !pelo,
                pelo = pelo
            )

            val manifest = PipelineConverter.convert(actualInput, output, config, periodAnalyzer)
            if (!dryRun) {
                println("\nConversion successful!")
                println("Output directory: $output")
                println("Stats: ${manifest.stats}")
            }
        } catch (e: Exception) {
            System.err.println("Error: ${e.message}")
            e.printStackTrace()
            kotlin.system.exitProcess(1)
        } finally {
            tempDir?.toFile()?.deleteRecursively()
        }
    }
}

fun main(args: Array<String>) {
    CommandLineInterface().subcommands(ConvertCommand(), VisualizerCommand()).main(args)
}
