plugins {
    kotlin("jvm")
    application
}

description = "Command line front end for the GTFS to RAPTOR binary pipeline."

dependencies {
    implementation(project(":core"))

    // Argument parsing stops here: it is a property of this front end, not of the
    // conversion, and nothing on Central should inherit it.
    implementation("com.github.ajalt.clikt:clikt:4.2.2")
}

kotlin {
    jvmToolchain(21)
}

application {
    // Keeps the launcher at build/install/raptor-gtfs-pipeline/bin/raptor-gtfs-pipeline
    // even though the Gradle project is now called :cli.
    applicationName = "raptor-gtfs-pipeline"
    mainClass.set("eu.dotshell.raptor.gtfs.pipeline.cli.MainKt")
}
