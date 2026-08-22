plugins {
    kotlin("jvm") version "2.1.0" apply false
    kotlin("plugin.serialization") version "2.1.0" apply false
    id("com.gradleup.nmcp") version "1.6.1" apply false
    // Applied here for one reason beyond aggregating :core's publication: this is what
    // registers nmcpPublishDeployment, the task that releases a deployment left waiting in
    // the portal by -PpublishingType=USER_MANAGED. Without it, an inspect-then-release
    // publication can only be finished by clicking in the Central UI.
    id("com.gradleup.nmcp.aggregation") version "1.6.1"
}

// Credentials live in ~/.gradle/gradle.properties or the environment — never in this
// repository's own gradle.properties, which is committed.
fun secret(property: String, environmentVariable: String): String? =
    findProperty(property) as String? ?: System.getenv(environmentVariable)

nmcpAggregation {
    centralPortal {
        username.set(secret("ossrhUsername", "OSSRH_USERNAME") ?: "")
        password.set(secret("ossrhPassword", "OSSRH_PASSWORD") ?: "")
        // AUTOMATIC releases as soon as Central's validation passes. Pass
        // -PpublishingType=USER_MANAGED to stop at the portal and look first.
        publishingType.set(findProperty("publishingType") as String? ?: "AUTOMATIC")
    }
}

dependencies {
    // Only :core publishes; :cli is the command line front end and stays unpublished.
    nmcpAggregation(project(":core"))
}
