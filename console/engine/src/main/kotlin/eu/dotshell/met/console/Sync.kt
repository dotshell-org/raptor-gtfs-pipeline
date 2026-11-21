package eu.dotshell.met.console

import eu.dotshell.met.sync.DatasetSync
import eu.dotshell.met.sync.FileStats
import eu.dotshell.met.sync.Latest
import eu.dotshell.met.sync.SyncListener
import eu.dotshell.met.sync.SyncPlan
import eu.dotshell.met.sync.SyncResult
import eu.dotshell.met.sync.Transport
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonObjectBuilder
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import kotlinx.serialization.json.putJsonObject
import okio.FileSystem
import okio.Path.Companion.toPath
import okio.Source
import okio.source
import java.io.FileDescriptor
import java.io.FileOutputStream
import java.io.IOException
import java.io.PrintStream
import java.net.URI
import java.net.http.HttpClient
import java.net.http.HttpRequest
import java.net.http.HttpResponse
import java.time.Duration
import kotlin.system.exitProcess

/**
 * Checks for or installs the latest version of a dataset with dataset-sync, the library apps use,
 * telling what happens as one JSON object per line: what the console's Mise à jour tab reads.
 *
 *     SyncKt --root console/data/france-live --base-url https://api.dotshell.eu
 *            [--city france-live] [--epoch epoch-2-3] [--check]
 *
 * Lines, in order:
 *
 *     {"type":"installed","version":…|null}
 *     {"type":"latest","version","total_bytes","full_bytes","deltas":{from: bytes}}
 *     {"type":"up_to_date","version"}                                   and nothing else, or
 *     {"type":"plan","method","from","to","bytes","full_bytes","total_bytes"}
 *     --check stops here. An update goes on:
 *     {"type":"progress","done","total"}                                 at most ten a second
 *     {"type":"file","path","bytes","copied","reused","inserted","derived","index","count"}
 *     {"type":"switched","version"}
 *     {"type":"done","from","version","method","downloaded","download_ms","apply_ms",
 *      "bytes","copied","reused","inserted","derived"}
 *
 * or, when anything fails, {"type":"error","kind","message"} last and exit code 1. The installed
 * version is then as it was, and a partial download is resumed by the next update.
 */
fun main(args: Array<String>) {
    // The console may not be UTF-8 (Windows): write bytes ourselves.
    val out = PrintStream(FileOutputStream(FileDescriptor.out), true, Charsets.UTF_8)
    exitProcess(Sync.run(args.toList()) { out.println(it.toString()) })
}

object Sync {
    const val USAGE = "SyncKt --root <dir> --base-url <url> [--city france-live] [--epoch epoch-2-3] [--check]"

    /** Runs a check or an update, each step a line to [emit]; returns the exit code. */
    fun run(args: List<String>, transport: Transport? = null, emit: (JsonObject) -> Unit): Int {
        val options = HashMap<String, String>()
        var check = false
        var i = 0
        try {
            while (i < args.size) {
                val key = args[i]
                when {
                    key == "--check" -> check = true
                    key.startsWith("--") && i + 1 < args.size -> options[key.removePrefix("--")] = args[++i]
                    else -> throw IllegalArgumentException("unexpected '$key'\n$USAGE")
                }
                i++
            }
            val root = options["root"] ?: throw IllegalArgumentException("--root is required\n$USAGE")
            val city = options["city"] ?: "france-live"
            val epoch = options["epoch"] ?: "epoch-2-3"
            val link = transport ?: HttpTransport(epochUrl(options["base-url"] ?: throw IllegalArgumentException("--base-url is required\n$USAGE"), city, epoch))
            val fs = FileSystem.SYSTEM
            val dir = root.toPath()
            fs.createDirectories(dir)
            val sync = DatasetSync(fs, dir, link)
            return runBlocking { if (check) check(sync, emit) else update(sync, emit) }
        } catch (error: Throwable) {
            emit(buildJsonObject {
                put("type", "error")
                put("kind", error::class.simpleName ?: "Error")
                put("message", error.message ?: error.toString())
            })
            return 1
        }
    }

    /** `<base>/<city>/<epoch>/`, the URL every path of the protocol is relative to. */
    fun epochUrl(base: String, city: String, epoch: String) = base.trimEnd('/') + "/$city/$epoch/"

    private suspend fun check(sync: DatasetSync, emit: (JsonObject) -> Unit): Int {
        val latest = start(sync, emit)
        val plan = sync.plan(latest)
        emit(if (plan == null) upToDate(latest.version) else planLine(plan))
        return 0
    }

    private suspend fun update(sync: DatasetSync, emit: (JsonObject) -> Unit): Int {
        start(sync, emit)
        val listener = object : SyncListener {
            private var last = 0L

            override fun planned(plan: SyncPlan) = emit(planLine(plan))

            override fun downloading(done: Long, total: Long) {
                val now = System.nanoTime()
                if (done < total && now - last < 100_000_000) return
                last = now
                emit(buildJsonObject { put("type", "progress"); put("done", done); put("total", total) })
            }

            override fun verified(file: FileStats, index: Int, count: Int) = emit(buildJsonObject {
                put("type", "file"); put("path", file.path); bytes(file); put("index", index); put("count", count)
            })

            override fun switched(version: String) = emit(buildJsonObject { put("type", "switched"); put("version", version) })
        }
        when (val result = sync.update(listener)) {
            is SyncResult.UpToDate -> emit(upToDate(result.version))
            is SyncResult.Updated -> emit(buildJsonObject {
                put("type", "done")
                put("from", result.from)
                put("version", result.version)
                put("method", result.method)
                put("downloaded", result.downloaded)
                put("download_ms", result.stats.downloadMillis)
                put("apply_ms", result.stats.applyMillis)
                put("bytes", result.stats.bytes)
                put("copied", result.stats.copied)
                put("reused", result.stats.reused)
                put("inserted", result.stats.inserted)
                put("derived", result.stats.derived)
            })
        }
        return 0
    }

    /** What is installed and what the server has. */
    private suspend fun start(sync: DatasetSync, emit: (JsonObject) -> Unit): Latest {
        emit(buildJsonObject { put("type", "installed"); put("version", sync.installed()?.version) })
        val latest = sync.check()
        emit(buildJsonObject {
            put("type", "latest")
            put("version", latest.version)
            put("total_bytes", latest.totalBytes)
            put("full_bytes", latest.packs?.full?.bytes)
            putJsonObject("deltas") { latest.packs?.deltas?.forEach { (from, pack) -> put(from, pack.bytes) } }
        })
        return latest
    }

    private fun upToDate(version: String) = buildJsonObject { put("type", "up_to_date"); put("version", version) }

    private fun planLine(plan: SyncPlan) = buildJsonObject {
        put("type", "plan")
        put("method", plan.method)
        put("from", plan.from)
        put("to", plan.to)
        put("bytes", plan.bytes)
        put("full_bytes", plan.fullBytes)
        put("total_bytes", plan.totalBytes)
    }

    private fun JsonObjectBuilder.bytes(file: FileStats) {
        put("bytes", file.bytes); put("copied", file.copied); put("reused", file.reused)
        put("inserted", file.inserted); put("derived", file.derived)
    }
}

/**
 * dataset-sync's transport over the JDK's HTTP client: GET under [epochUrl], from a byte offset
 * with a Range request when resuming.
 */
class HttpTransport(private val epochUrl: String) : Transport {
    private val client = HttpClient.newBuilder()
        .followRedirects(HttpClient.Redirect.NORMAL)
        .connectTimeout(Duration.ofSeconds(20))
        .build()

    override suspend fun open(path: String, from: Long): Source = withContext(Dispatchers.IO) {
        val request = HttpRequest.newBuilder(URI.create(epochUrl + path))
            .header("User-Agent", "met-console/1.0")
            .timeout(Duration.ofSeconds(60))
            .apply { if (from > 0) header("Range", "bytes=$from-") }
            .GET().build()
        val response = client.send(request, HttpResponse.BodyHandlers.ofInputStream())
        val body = response.body()
        when (response.statusCode()) {
            206 -> Unit
            // A server that ignores Range sends the whole file: skip what is already here.
            200 -> if (from > 0) body.skipNBytes(from)
            else -> { body.close(); throw IOException("$path: HTTP ${response.statusCode()}") }
        }
        body.source()
    }
}
