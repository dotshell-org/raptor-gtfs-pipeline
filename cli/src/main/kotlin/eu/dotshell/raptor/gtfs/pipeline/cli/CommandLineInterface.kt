package eu.dotshell.raptor.gtfs.pipeline.cli

import com.github.ajalt.clikt.core.CliktCommand
import com.github.ajalt.clikt.parameters.options.flag
import com.github.ajalt.clikt.parameters.options.option

class CommandLineInterface : CliktCommand(name = "raptor-gtfs", help = "Convert GTFS datasets to RAPTOR binary format") {
    private val verbose by option("-v", "--verbose", help = "Verbose output").flag()

    override fun run() {
        if (verbose) {
            println("Verbose mode enabled")
        }
    }
}
