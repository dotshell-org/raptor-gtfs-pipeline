plugins {
    kotlin("jvm") version "2.1.0"
    kotlin("plugin.serialization") version "2.1.0"
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
    // Gradle 9 no longer bundles the JUnit Platform launcher on the test runtime classpath.
    testRuntimeOnly("org.junit.platform:junit-platform-launcher")
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
