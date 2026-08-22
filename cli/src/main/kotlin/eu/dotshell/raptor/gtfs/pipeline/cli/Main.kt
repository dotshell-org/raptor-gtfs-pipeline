package eu.dotshell.raptor.gtfs.pipeline.cli

import com.github.ajalt.clikt.core.subcommands

fun main(args: Array<String>) {
    CommandLineInterface().subcommands(ConvertCommand(), VisualizerCommand(), VisualizeNetworkCommand()).main(args)
}
