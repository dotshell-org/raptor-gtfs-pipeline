pluginManagement {
    repositories {
        mavenCentral()
        gradlePluginPortal()
    }
}

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        mavenCentral()
    }
}

rootProject.name = "raptor-gtfs-pipeline"

// :core is the library published to Maven Central as eu.dotshell:raptor-gtfs-pipeline.
// :cli is the command line front end — it depends on :core and is never published, so a
// consumer of the library never drags an argument parser into its own dependency tree.
include(":core", ":cli")

// :benchmark-engine times raptor-kmp on the pipeline's output for the whole-France benchmark
// (benchmark/README.md). It lives with the benchmark and, like :cli, is never published.
include(":benchmark-engine")
project(":benchmark-engine").projectDir = file("benchmark/engine")
