import org.jetbrains.kotlin.gradle.dsl.JvmTarget

plugins {
    kotlin("jvm")
    kotlin("plugin.serialization")
    `maven-publish`
    signing
    id("com.gradleup.nmcp") version "1.6.1"
}

description = "Converts GTFS datasets into the compact binaries the RAPTOR routing algorithm reads."

base {
    // The Gradle project is called :core; the artifact is not.
    archivesName.set("raptor-gtfs-pipeline")
}

dependencies {
    // The models are @Serializable and consumers deserialize dataset.json with the
    // serializers generated here, so the runtime belongs on their compile classpath: api,
    // not implementation.
    api("org.jetbrains.kotlinx:kotlinx-serialization-json:1.6.3")

    implementation("com.charleskorn.kaml:kaml:0.57.0") // YAML period profiles
    implementation("com.github.doyaaaaaken:kotlin-csv-jvm:1.9.3") // streaming GTFS CSV reader

    testImplementation(kotlin("test"))
    // Gradle 9 no longer bundles the JUnit Platform launcher on the test runtime classpath.
    testRuntimeOnly("org.junit.platform:junit-platform-launcher")
}

kotlin {
    jvmToolchain(21)
    // Built with 21, emitted for 17: the README has always promised Java 17, and a library
    // on Central should not force its version of the JVM on the projects that use it.
    compilerOptions {
        jvmTarget.set(JvmTarget.JVM_17)
    }
}

java {
    sourceCompatibility = JavaVersion.VERSION_17
    targetCompatibility = JavaVersion.VERSION_17
    withSourcesJar()
}

tasks.test {
    useJUnitPlatform()
}

// ---------------------------------------------------------------------------
// Version, generated from the build
// ---------------------------------------------------------------------------
// Every dataset.json carries the tool_version that produced it, and a publisher copies
// that into what it serves. Reading it from gradle.properties rather than from a second
// hand-edited constant is what keeps "0.4.0 wrote this file" true.
val pipelineVersion = version.toString()
val versionSourceDir = layout.buildDirectory.dir("generated/source/version")

val generateVersionFile by tasks.registering {
    inputs.property("version", pipelineVersion)
    outputs.dir(versionSourceDir)
    doLast {
        val file = versionSourceDir.get()
            .file("eu/dotshell/raptor/gtfs/pipeline/PipelineVersion.kt").asFile
        file.parentFile.mkdirs()
        file.writeText(
            """
            package eu.dotshell.raptor.gtfs.pipeline

            /** Generated from the Gradle project version — edit gradle.properties, not this file. */
            public const val PIPELINE_VERSION: String = "$pipelineVersion"

            """.trimIndent()
        )
    }
}

kotlin.sourceSets.named("main") {
    kotlin.srcDir(generateVersionFile)
}

// ---------------------------------------------------------------------------
// Publication
// ---------------------------------------------------------------------------
val javadocJar by tasks.registering(Jar::class) {
    archiveClassifier.set("javadoc")
    // Central requires a javadoc artifact. The KDoc travels in the sources jar, which is
    // what an IDE actually reads, so this one is deliberately empty rather than a Dokka
    // build that adds a plugin to serve a file nobody opens.
}

publishing {
    publications {
        create<MavenPublication>("maven") {
            from(components["java"])
            artifact(javadocJar)
            artifactId = "raptor-gtfs-pipeline"

            pom {
                name.set("Raptor GTFS Pipeline")
                description.set(project.description)
                url.set("https://github.com/dotshell-org/raptor-gtfs-pipeline")

                licenses {
                    // Matches the LICENSE file at the root of this repository.
                    license {
                        name.set("MIT License")
                        url.set("https://opensource.org/licenses/MIT")
                    }
                }

                developers {
                    developer {
                        id.set("tristan")
                        name.set("Tristan")
                        email.set("contact@dotshell.eu")
                    }
                }

                scm {
                    connection.set("scm:git:git://github.com/dotshell-org/raptor-gtfs-pipeline.git")
                    developerConnection.set("scm:git:ssh://github.com:dotshell-org/raptor-gtfs-pipeline.git")
                    url.set("https://github.com/dotshell-org/raptor-gtfs-pipeline")
                }
            }
        }
    }
}

// Credentials live in ~/.gradle/gradle.properties or the environment — never in this
// repository's own gradle.properties, which is committed.
fun secret(property: String, environmentVariable: String): String? =
    findProperty(property) as String? ?: System.getenv(environmentVariable)

signing {
    val keyId = secret("signing.keyId", "SIGNING_KEY_ID")
    val password = secret("signing.password", "SIGNING_PASSWORD")
    val keyRingFile = secret("signing.secretKeyRingFile", "SIGNING_KEY_RING_FILE")
    // An armoured key in the environment is how CI signs; a keyring file is how a laptop
    // does. Central accepts either — it only ever sees the signatures.
    val inMemoryKey = System.getenv("SIGNING_KEY")

    when {
        inMemoryKey != null && password != null -> {
            useInMemoryPgpKeys(keyId, inMemoryKey, password)
            sign(publishing.publications)
        }
        keyId != null && password != null && keyRingFile != null -> {
            extra["signing.keyId"] = keyId
            extra["signing.password"] = password
            extra["signing.secretKeyRingFile"] = keyRingFile
            sign(publishing.publications)
        }
        // Otherwise the build stays usable — it simply cannot publish, and nmcp says so.
    }
}

nmcp {
    publishAllPublicationsToCentralPortal {
        username.set(secret("ossrhUsername", "OSSRH_USERNAME") ?: "")
        password.set(secret("ossrhPassword", "OSSRH_PASSWORD") ?: "")
        // AUTOMATIC releases as soon as Central's validation passes, like raptor-kmp.
        // Set -PpublishingType=USER_MANAGED to stop at the portal and eyeball it first.
        publishingType.set(findProperty("publishingType") as String? ?: "AUTOMATIC")
    }
}
