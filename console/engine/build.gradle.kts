plugins {
    kotlin("jvm") version "2.3.21"
    application
}

description = "The console's engine: routes on the installed france-live version, and keeps it up to date."

// The engine as apps get it: the JVM artifact, not its sources.
val raptorKmpVersion = (findProperty("raptorKmpVersion") as String?) ?: "2.4.1"

dependencies {
    implementation("eu.dotshell:raptor-kmp-jvm:$raptorKmpVersion")
    implementation("eu.dotshell.met:dataset-sync-jvm:1.0.0")
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.11.0")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-core:1.10.2")
    testImplementation(kotlin("test"))
}

kotlin {
    jvmToolchain(21)
}

tasks.test {
    useJUnitPlatform()
}

// The engine version travels with the server, so the console can say which one answers.
val engineVersionFile = tasks.register("writeEngineVersion") {
    val dir = layout.buildDirectory.dir("generated/engine-version")
    inputs.property("version", raptorKmpVersion)
    outputs.dir(dir)
    doLast { dir.get().file("raptor-kmp.version").asFile.writeText(raptorKmpVersion) }
}
sourceSets.main { resources.srcDir(engineVersionFile) }

// One install, two entry points started by class name: ServeKt (routing) and SyncKt (updates).
application {
    applicationName = "console-engine"
    mainClass.set("eu.dotshell.met.console.ServeKt")
}
