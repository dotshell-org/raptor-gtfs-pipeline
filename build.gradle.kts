plugins {
    kotlin("jvm") version "1.9.22"
    kotlin("plugin.serialization") version "1.9.22"
    application
}

group = "eu.dotshell.raptor.gtfs.pipeline"
version = "0.1.0"

repositories {
    mavenCentral()
}

dependencies {
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.6.3")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-core:1.8.0")
    implementation("com.charleskorn.kaml:kaml:0.57.0") // YAML support
    implementation("com.github.doyaaaaaken:kotlin-csv-jvm:1.9.3") // CSV support
    
    // Command line argument parsing
    implementation("com.github.ajalt.clikt:clikt:4.2.2")
    
    testImplementation(kotlin("test"))
}

tasks.test {
    useJUnitPlatform()
}

kotlin {
    jvmToolchain(21)
}

application {
    mainClass.set("eu.dotshell.raptor.gtfs.pipeline.MainKt")
}
