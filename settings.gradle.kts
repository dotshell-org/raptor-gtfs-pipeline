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

// console/engine (the france-live console's JVM side) is a build of its own: it runs newer
// Kotlin libraries than this build compiles with. See console/README.md.
