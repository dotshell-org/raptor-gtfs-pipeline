package eu.dotshell.met.console

import com.sun.net.httpserver.HttpServer
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import java.net.InetSocketAddress
import java.nio.file.Files
import java.nio.file.Path
import java.security.MessageDigest
import java.nio.file.Paths
import kotlin.io.path.createDirectories
import kotlin.io.path.exists
import kotlin.io.path.readBytes
import kotlin.io.path.writeBytes
import kotlin.io.path.writeText
import kotlin.test.AfterTest
import kotlin.test.Test
import kotlin.test.assertContentEquals
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/**
 * SyncKt against a local HTTP server laid out like met-dataset-server's france-live: two small
 * versions and the packs the server's own `packs` command built for them (resources/sync).
 */
class SyncTest {
    private val v1 = "20261120-00000001"
    private val v2 = "20261121-00000002"
    private val fixtures = Paths.get(javaClass.getResource("/sync/versions")!!.toURI()).parent
    private val served: Path = Files.createTempDirectory("served")
    private val epoch = served.resolve("france-live/epoch-2-3").createDirectories()
    private val device: Path = Files.createTempDirectory("device")

    /** When set, the next pack is sent half and the connection dropped. */
    private var cutNextPack = false
    /** When set, Range is ignored: the whole file comes with 200. */
    private var ignoreRange = false
    private val requests = ArrayList<String>()

    private val server = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0).apply {
        createContext("/") { exchange ->
            exchange.use {
                val path = it.requestURI.path
                requests += path + (it.requestHeaders.getFirst("Range")?.let { r -> " $r" } ?: "")
                val file = served.resolve(path.removePrefix("/"))
                if (".." in path || !Files.isRegularFile(file)) { it.sendResponseHeaders(404, -1); return@use }
                val bytes = file.readBytes()
                val from = it.requestHeaders.getFirst("Range")?.takeUnless { ignoreRange }
                    ?.removePrefix("bytes=")?.removeSuffix("-")?.toInt() ?: 0
                val body = bytes.copyOfRange(from, bytes.size)
                it.sendResponseHeaders(if (from > 0) 206 else 200, body.size.toLong())
                if (cutNextPack && "/packs/" in path) {
                    cutNextPack = false
                    it.responseBody.write(body, 0, body.size / 2)
                    it.responseBody.flush()
                    return@use // closed early: the client sees the body end short
                }
                it.responseBody.write(body)
            }
        }
        start()
    }
    private val base = "http://127.0.0.1:${server.address.port}"

    @AfterTest
    fun stop() = server.stop(0)

    /** Puts [version] on the server, with its packs, and points latest.json at it. */
    private fun publish(version: String) {
        val files = Files.walk(fixtures.resolve("versions/$version")).use { s ->
            s.filter { Files.isRegularFile(it) }.toList()
        }.sortedBy { it.toString() }
        val dir = fixtures.resolve("versions/$version")
        val entries = files.map { f ->
            val rel = dir.relativize(f).joinToString("/")
            epoch.resolve("$version/$rel").also { it.parent.createDirectories() }.writeBytes(f.readBytes())
            """{"path":"$rel","sha256":"${sha(f)}","bytes":${Files.size(f)}}"""
        }
        val packDir = fixtures.resolve("packs/$version")
        val packs = Files.list(packDir).use { it.toList() }.associateBy { it.fileName.toString() }
        for ((name, p) in packs) epoch.resolve("packs/$version/$name").also { it.parent.createDirectories() }.writeBytes(p.readBytes())
        fun ref(name: String) = """{"path":"packs/$version/$name","bytes":${Files.size(packs.getValue(name))},"sha256":"${sha(packs.getValue(name))}"}"""
        val deltas = packs.keys.filter { it.startsWith("from-") }.joinToString(",") { "\"${it.removePrefix("from-").removeSuffix(".pack")}\":${ref(it)}" }
        epoch.resolve("latest.json").writeText("""
            {"epoch":"epoch-2-3","version":"$version","path":"$version","schema_version":2,
             "total_bytes":${files.sumOf { Files.size(it) }},"files":[${entries.joinToString(",")}],
             "packs":{"full":${ref("full.pack")},"deltas":{$deltas}}}
        """.trimIndent())
    }

    private fun sha(file: Path) = MessageDigest.getInstance("SHA-256").digest(file.readBytes()).joinToString("") { "%02x".format(it) }

    private fun sync(vararg extra: String): Pair<Int, List<JsonObject>> {
        val lines = ArrayList<JsonObject>()
        val code = Sync.run(listOf("--root", device.toString(), "--base-url", base) + extra) { lines += it }
        return code to lines
    }

    private fun List<JsonObject>.types() = map { it.type() }.filter { it != "progress" && it != "file" }
    private fun JsonObject.type() = getValue("type").jsonPrimitive.content
    private fun JsonObject.text(key: String) = get(key)?.takeUnless { it is JsonNull }?.jsonPrimitive?.content
    private fun JsonObject.number(key: String) = getValue(key).jsonPrimitive.long
    private fun List<JsonObject>.one(type: String) = single { it.type() == type }

    private fun assertInstalled(version: String) {
        val dir = fixtures.resolve("versions/$version")
        val expected = Files.walk(dir).use { s -> s.filter { Files.isRegularFile(it) }.map { dir.relativize(it).joinToString("/") }.toList() }.sorted()
        val onDevice = device.resolve(version)
        val got = Files.walk(onDevice).use { s -> s.filter { Files.isRegularFile(it) }.map { onDevice.relativize(it).joinToString("/") }.toList() }.sorted()
        assertEquals(expected, got)
        for (f in expected) assertContentEquals(dir.resolve(f).readBytes(), onDevice.resolve(f).readBytes(), f)
        assertTrue(device.resolve("installed.json").exists())
    }

    @Test
    fun `a check says what an update would do, and changes nothing`() {
        publish(v1)
        val (code, lines) = sync("--check")
        assertEquals(0, code)
        assertEquals(listOf("installed", "latest", "plan"), lines.types())
        assertEquals(null, lines.one("installed").text("version"))
        val plan = lines.one("plan")
        assertEquals("full", plan.text("method"))
        assertEquals(Files.size(fixtures.resolve("packs/$v1/full.pack")), plan.number("bytes"))
        assertEquals(listOf("/france-live/epoch-2-3/latest.json"), requests)
        assertTrue(Files.list(device).use { it.toList() }.isEmpty(), "nothing written")
    }

    @Test
    fun `the full pack first, then the delta, each file reported`() {
        publish(v1)
        val (code, first) = sync()
        assertEquals(0, code, "$first")
        assertEquals(listOf("installed", "latest", "plan", "switched", "done"), first.types())
        assertEquals("full", first.one("done").text("method"))
        assertEquals(3, first.count { it.type() == "file" })
        assertTrue(first.any { it.type() == "progress" })
        assertInstalled(v1)
        assertEquals(listOf("installed", "latest", "up_to_date"), sync().second.types())

        publish(v2)
        val (_, check) = sync("--check")
        assertEquals("delta", check.one("plan").text("method"))
        assertEquals(v1, check.one("plan").text("from"))
        val (code2, second) = sync()
        assertEquals(0, code2, "$second")
        val done = second.one("done")
        assertEquals("delta", done.text("method"))
        assertEquals(Files.size(fixtures.resolve("packs/$v2/from-$v1.pack")), done.number("downloaded"))
        assertEquals(done.number("bytes"), done.number("copied") + done.number("reused") + done.number("inserted") + done.number("derived"))
        assertTrue(done.number("copied") > done.number("inserted") * 10, "most of v2 comes from v1: $done")
        val samedi = second.single { it.type() == "file" && it.text("path") == "samedi/stops.bin" }
        assertEquals(samedi.number("bytes"), samedi.number("copied"), "unchanged: copied whole")
        assertInstalled(v2)
        assertTrue(!device.resolve(v1).exists(), "the old version is gone")
    }

    @Test
    fun `a corrupt delta is refused, the installed version stays`() {
        publish(v1)
        sync()
        publish(v2)
        val pack = epoch.resolve("packs/$v2/from-$v1.pack")
        pack.writeBytes(pack.readBytes().also { it[it.size - 5] = (it[it.size - 5] + 1).toByte() })
        val (code, lines) = sync()
        assertEquals(1, code)
        val error = lines.last()
        assertEquals("error", error.type())
        assertEquals("SyncException", error.text("kind"))
        assertTrue("SHA-256" in error.text("message")!!, "$error")
        assertInstalled(v1)
    }

    @Test
    fun `a cut download is resumed by the next update`() {
        publish(v1)
        sync()
        publish(v2)
        cutNextPack = true
        val (code, lines) = sync()
        assertEquals(1, code)
        assertEquals("error", lines.last().type())
        assertInstalled(v1)
        val size = Files.size(epoch.resolve("packs/$v2/from-$v1.pack"))
        val (code2, again) = sync()
        assertEquals(0, code2, "$again")
        assertEquals(size - size / 2, again.one("done").number("downloaded"), "only the rest")
        assertTrue(requests.any { it.endsWith("bytes=${size / 2}-") }, "$requests")
        assertEquals(size / 2, again.first { it.type() == "progress" }.number("done"))
        assertInstalled(v2)
    }

    @Test
    fun `a server that ignores Range still resumes right`() {
        publish(v1)
        sync()
        publish(v2)
        cutNextPack = true
        sync()
        ignoreRange = true
        val (code, lines) = sync()
        assertEquals(0, code, "$lines")
        assertInstalled(v2)
    }

    @Test
    fun `no server, or no dataset there, is an error line`() {
        val (code, lines) = sync()
        assertEquals(1, code)
        assertEquals("error", lines.last().type())
        assertTrue("HTTP 404" in lines.last().text("message")!!, "${lines.last()}")
        val usage = ArrayList<JsonObject>()
        assertEquals(1, Sync.run(listOf("--base-url", base)) { usage += it })
        assertTrue("--root is required" in usage.single().text("message")!!)
    }
}
