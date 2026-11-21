// The console's JVM side: its own build, apart from the pipeline's (Kotlin 2.1), because the
// libraries it runs are newer: raptor-kmp and dataset-sync, as apps get them.
//
//     ..\..\gradlew.bat installDist          (from console/engine)
pluginManagement {
    repositories {
        mavenCentral()
        gradlePluginPortal()
    }
}

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        // ~/.m2 for eu.dotshell artifacts only: dataset-sync (met-dataset-server,
        // `publishToMavenLocal`) and a raptor-kmp not yet on Maven Central.
        mavenLocal { content { includeGroupByRegex("eu\\.dotshell(\\..*)?") } }
        mavenCentral()
    }
}

rootProject.name = "console-engine"
