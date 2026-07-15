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

fun main(args: Array<String>) {
    CommandLineInterface().subcommands(ConvertCommand(), VisualizerCommand()).main(args)
}
