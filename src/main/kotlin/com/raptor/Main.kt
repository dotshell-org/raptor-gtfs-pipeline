package com.raptor

import com.github.ajalt.clikt.core.subcommands

fun main(args: Array<String>) {
    CommandLineInterface().subcommands(ConvertCommand(), VisualizerCommand()).main(args)
}
