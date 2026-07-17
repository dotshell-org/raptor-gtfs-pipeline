package eu.dotshell.raptor.gtfs.pipeline.output

import eu.dotshell.raptor.gtfs.pipeline.gtfs.models.LineData
import java.io.File

object LinesSerializer {
    const val COORD_SCALE = 1_000_000

    fun writeLinesFile(outputPath: File, lines: List<LineData>, schemaVersion: Int): String {
        outputPath.mkdirs()
        val linesPath = File(outputPath, "lines.bin")

        var totalPoints = 0
        linesPath.outputStream().use { f ->
            val writer = LinesWriter(f)
            writer.writeHeader(schemaVersion, COORD_SCALE, lines.size)
            for (line in lines) {
                writer.writeLine(line, COORD_SCALE)
                totalPoints += line.paths.sumOf { it.points.size }
            }
        }

        println("Wrote $linesPath (${lines.size} lines, $totalPoints points)")
        return linesPath.absolutePath
    }
}
