plugins {
    kotlin("jvm")
    kotlin("plugin.serialization")
    application
}

description = "Times raptor-kmp on the pipeline's output for the whole-France benchmark."

// The engine as apps get it: the JVM artifact published on Maven Central, not its sources.
val raptorKmpVersion = (findProperty("raptorKmpVersion") as String?) ?: "2.2.0"

dependencies {
    implementation("eu.dotshell:raptor-kmp-jvm:$raptorKmpVersion")
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.6.3")
}

kotlin {
    jvmToolchain(21)
}

// The engine version travels with the harness, so every report says which engine it timed.
val engineVersionFile = tasks.register("writeEngineVersion") {
    val dir = layout.buildDirectory.dir("generated/engine-version")
    inputs.property("version", raptorKmpVersion)
    outputs.dir(dir)
    doLast { dir.get().file("raptor-kmp.version").asFile.writeText(raptorKmpVersion) }
}
sourceSets.main { resources.srcDir(engineVersionFile) }

application {
    applicationName = "benchmark-engine"
    mainClass.set("eu.dotshell.raptor.bench.MainKt")
}
