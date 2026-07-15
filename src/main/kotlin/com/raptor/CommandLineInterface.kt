package com.raptor

import com.github.ajalt.clikt.core.CliktCommand
import com.github.ajalt.clikt.parameters.options.*

class CommandLineInterface : CliktCommand(name = "raptor-gtfs", help = "Convert GTFS datasets to RAPTOR binary format") {
    private val verbose by option("-v", "--verbose", help = "Verbose output").flag()

    override fun run() {
        if (verbose) {
            println("Verbose mode enabled")
        }
    }
}
