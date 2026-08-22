package eu.dotshell.raptor.gtfs.pipeline

/**
 * Where the conversion narrates its progress.
 *
 * The pipeline says what it is doing as it goes — a large feed is otherwise several silent
 * minutes — but a library has no business writing to the stdout of a host that already owns
 * a logger. [sink] is that seam: the CLI leaves it on `println`, a server points it at its
 * own logging.
 *
 * The sink is process-wide. Two conversions running **concurrently** therefore interleave
 * their lines with nothing to tell them apart, which is a deliberate trade: threading a
 * logger through every builder, writer and analyzer would add a parameter to a dozen
 * internal signatures to serve a case neither consumer has. Convert one dataset at a time,
 * or accept the interleaving.
 */
public object PipelineLog {
    @Volatile
    public var sink: (String) -> Unit = ::println

    public fun info(message: String) {
        sink(message)
    }

    /**
     * Runs [block] with [sink] pointed at [target], then restores it.
     *
     * Convenience for a host that only wants the pipeline's own output redirected, not the
     * whole process's. Not reentrant across threads, for the reason above.
     */
    public fun <T> withSink(target: (String) -> Unit, block: () -> T): T {
        val previous = sink
        sink = target
        try {
            return block()
        } finally {
            sink = previous
        }
    }
}
