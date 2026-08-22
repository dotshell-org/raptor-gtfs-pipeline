package eu.dotshell.raptor.gtfs.pipeline.gtfs

import com.charleskorn.kaml.Yaml
import eu.dotshell.raptor.gtfs.pipeline.PipelineLog
import eu.dotshell.raptor.gtfs.pipeline.gtfs.models.PeriodRule
import eu.dotshell.raptor.gtfs.pipeline.gtfs.models.Profile
import eu.dotshell.raptor.gtfs.pipeline.gtfs.models.ServicePeriod
import eu.dotshell.raptor.gtfs.pipeline.gtfs.models.Calendar
import java.io.File

object ProfileAnalyzer {
    private val DAY_INDEX = mapOf(
        "mon" to 0, "tue" to 1, "wed" to 2, "thu" to 3, "fri" to 4, "sat" to 5, "sun" to 6
    )
    private val DAY_ALIASES = mapOf(
        "weekday" to setOf(0, 1, 2, 3, 4), "weekdays" to setOf(0, 1, 2, 3, 4),
        "weekend" to setOf(5, 6), "weekends" to setOf(5, 6),
        "daily" to (0..6).toSet(), "everyday" to (0..6).toSet(), "all" to (0..6).toSet()
    )

    fun load(path: String): Profile {
        val text = File(path).readText()
        return Yaml.default.decodeFromString(Profile.serializer(), text)
    }

    private fun parseDays(tokens: List<String>): Set<Int> {
        val result = mutableSetOf<Int>()
        for (token in tokens) {
            val t = token.trim().lowercase()
            when {
                DAY_ALIASES.containsKey(t) -> result.addAll(DAY_ALIASES[t]!!)
                "-" in t -> {
                    val parts = t.split("-")
                    val start = DAY_INDEX[parts[0].trim()] ?: continue
                    val end = DAY_INDEX[parts[1].trim()] ?: continue
                    result.addAll((start..end).toSet())
                }
                DAY_INDEX.containsKey(t) -> result.add(DAY_INDEX[t]!!)
            }
        }
        return result
    }

    /** Normalises YYYY-MM-DD or YYYYMMDD to the YYYYMMDD the feed uses. Null if it is neither. */
    private fun normalizeDate(value: String): String? {
        val digits = value.filter { it.isDigit() }
        return if (digits.length == 8) digits else null
    }

    private fun dayOfWeekIndex(yyyymmdd: String): Int? {
        val date = try {
            java.time.LocalDate.parse(
                yyyymmdd,
                java.time.format.DateTimeFormatter.BASIC_ISO_DATE
            )
        } catch (_: java.time.format.DateTimeParseException) {
            return null
        }
        // Monday is 0 here, as everywhere else in this file; java.time counts Monday as 1.
        return date.dayOfWeek.value - 1
    }

    /**
     * Does this service run on this date?
     *
     * calendar.txt gives the weekly pattern and the span; calendar_dates.txt overrides it for
     * single dates, and an override wins — that is the whole point of the file. A service present
     * only in calendar_dates.txt has no pattern at all and runs exactly on its added dates.
     */
    private fun runsOn(
        serviceId: String,
        yyyymmdd: String,
        cal: Calendar?,
        exceptions: Map<Pair<String, String>, Int>
    ): Boolean {
        when (exceptions[Pair(serviceId, yyyymmdd)]) {
            1 -> return true
            2 -> return false
        }
        if (cal == null) return false

        val dayIndex = dayOfWeekIndex(yyyymmdd) ?: return false
        val runsToday = when (dayIndex) {
            0 -> cal.monday
            1 -> cal.tuesday
            2 -> cal.wednesday
            3 -> cal.thursday
            4 -> cal.friday
            5 -> cal.saturday
            else -> cal.sunday
        }
        if (!runsToday) return false

        return cal.startDate <= yyyymmdd && yyyymmdd <= cal.endDate
    }

    /**
     * Every date a rule names: its single date, its list, and every day of each window.
     *
     * Windows are expanded rather than tested as intervals because a service's presence is a
     * property of a date — the calendar's pattern and the exceptions of calendar_dates.txt both
     * answer for one day at a time, and a withdrawal is invisible to anything coarser.
     */
    private fun datesOf(rule: PeriodRule): List<String> {
        val dates = mutableListOf<String>()

        rule.onDate?.let { dates.add(requireDate(it, "onDate")) }
        rule.onDates.forEach { dates.add(requireDate(it, "onDates")) }

        for (range in rule.dateRanges) {
            val from = requireDate(range.from, "dateRanges.from")
            val to = requireDate(range.to, "dateRanges.to")
            require(from <= to) { "dateRanges window runs backwards: $from to $to" }

            var day = java.time.LocalDate.parse(from, java.time.format.DateTimeFormatter.BASIC_ISO_DATE)
            val last = java.time.LocalDate.parse(to, java.time.format.DateTimeFormatter.BASIC_ISO_DATE)
            while (!day.isAfter(last)) {
                dates.add(day.format(java.time.format.DateTimeFormatter.BASIC_ISO_DATE))
                day = day.plusDays(1)
            }
        }

        return dates
    }

    private fun requireDate(value: String, field: String): String =
        normalizeDate(value)
            ?: throw IllegalArgumentException("$field must be YYYYMMDD or YYYY-MM-DD, got '$value'")

    private fun matchesRule(
        rule: PeriodRule,
        serviceId: String,
        activeDays: Set<Int>,
        cal: Calendar?,
        exceptions: Map<Pair<String, String>, Int>
    ): Boolean {
        if (rule.serviceIdMatches != null && !Regex(rule.serviceIdMatches).containsMatchIn(serviceId)) {
            return false
        }
        if (rule.days.isNotEmpty() && activeDays.intersect(parseDays(rule.days)).isEmpty()) {
            return false
        }
        val candidateDates = datesOf(rule)
        if (candidateDates.isNotEmpty()) {
            /*
             * One match is enough, and that is deliberate.
             *
             * A period is the union of its windows: a service running only over the February break
             * belongs to the holiday dataset even though it is absent at Toussaint. Requiring it to
             * run on every listed date would keep only the services common to all breaks, which is
             * a dataset no real day matches either — and it would drop precisely the school-holiday
             * reinforcements the period exists to describe.
             */
            val wanted = if (rule.days.isEmpty()) null else parseDays(rule.days)
            val runsOnAny = candidateDates.any { date ->
                (wanted == null || dayOfWeekIndex(date) in wanted) &&
                    runsOn(serviceId, date, cal, exceptions)
            }
            if (!runsOnAny) return false
        }

        if (cal != null && cal.startDate.length == 8 && cal.endDate.length == 8) {
            val sYear = cal.startDate.substring(0, 4).toIntOrNull() ?: 0
            val eYear = cal.endDate.substring(0, 4).toIntOrNull() ?: 0
            val sMonth = cal.startDate.substring(4, 6).toIntOrNull() ?: 0
            val eMonth = cal.endDate.substring(4, 6).toIntOrNull() ?: 0
            
            val activeMonths = mutableSetOf<Int>()
            var currY = sYear
            var currM = sMonth
            while (currY < eYear || (currY == eYear && currM <= eMonth)) {
                activeMonths.add(currM)
                currM++
                if (currM > 12) {
                    currM = 1
                    currY++
                }
            }

            if (rule.activeInMonths != null) {
                if (activeMonths.intersect(rule.activeInMonths.toSet()).isEmpty()) return false
            }
            if (rule.notActiveInMonths != null) {
                if (activeMonths.intersect(rule.notActiveInMonths.toSet()).isNotEmpty()) return false
            }
            
            val durationMonths = (eYear - sYear) * 12 + (eMonth - sMonth)
            if (rule.maxDurationMonths != null && durationMonths > rule.maxDurationMonths) {
                return false
            }
            if (rule.minDurationMonths != null && durationMonths < rule.minDurationMonths) {
                return false
            }
        } else if (cal == null && (rule.activeInMonths != null || rule.notActiveInMonths != null || rule.maxDurationMonths != null || rule.minDurationMonths != null)) {
            // Cannot evaluate date-based rules without a calendar entry
            return false
        }

        return true
    }

    fun build(profile: Profile, reader: GTFSReader): List<ServicePeriod> {
        val services = mutableMapOf<String, Set<Int>>()
        val calendars = reader.calendar.associateBy { it.serviceId }
        
        for (cal in reader.calendar) {
            val active = mutableSetOf<Int>()
            if (cal.monday) active.add(0)
            if (cal.tuesday) active.add(1)
            if (cal.wednesday) active.add(2)
            if (cal.thursday) active.add(3)
            if (cal.friday) active.add(4)
            if (cal.saturday) active.add(5)
            if (cal.sunday) active.add(6)
            services[cal.serviceId] = active
        }
        for (cd in reader.calendarDates) {
            services.putIfAbsent(cd.serviceId, emptySet())
        }

        // calendar_dates.txt, indexed for the date rules. One entry per service and date.
        val exceptions = reader.calendarDates.associate {
            Pair(it.serviceId, it.date) to it.exceptionType
        }

        val assigned = profile.periods.keys.associateWith { mutableListOf<String>() }
        val matched = mutableSetOf<String>()
        /** How many services each rule accounted for, so a rule that never fires can be reported. */
        val ruleHits = mutableMapOf<Pair<String, Int>, Int>()
        /** Services landing in more than one period, which is legal but rarely intended. */
        val periodsOfService = mutableMapOf<String, MutableList<String>>()

        for ((serviceId, activeDays) in services) {
            val cal = calendars[serviceId]
            for ((name, def) in profile.periods) {
                val effectiveRules = def.getEffectiveRules()
                var anyMatch = false
                if (effectiveRules.isEmpty()) {
                    // if no rules, it matches everything (fallback behavior)
                    anyMatch = true
                } else {
                    for ((index, rule) in effectiveRules.withIndex()) {
                        if (matchesRule(rule, serviceId, activeDays, cal, exceptions)) {
                            ruleHits[Pair(name, index)] = (ruleHits[Pair(name, index)] ?: 0) + 1
                            anyMatch = true
                            break
                        }
                    }
                }

                if (anyMatch) {
                    assigned[name]!!.add(serviceId)
                    matched.add(serviceId)
                    periodsOfService.getOrPut(serviceId) { mutableListOf() }.add(name)
                }
            }
        }

        /*
         * Report what the profile did, because both of these failed silently before.
         *
         * A rule matching nothing is a rule written for another feed: the Lyon profile keyed school
         * services off service ids ending in "-M-", a convention this TCL export no longer uses, so
         * its two most precise rules matched zero of 4 278 services and every classification fell
         * through to date-span guesses that cannot tell a school term from a holiday.
         *
         * A service in several periods is legal — a line running all year belongs to every weekday
         * period — but when it happens to most of the feed the periods are not describing different
         * service, and the output is one period repeated under several names.
         */
        for ((name, def) in profile.periods) {
            def.getEffectiveRules().forEachIndexed { index, rule ->
                if ((ruleHits[Pair(name, index)] ?: 0) == 0) {
                    PipelineLog.info("  ! period '$name' rule #${index + 1} matched no service: $rule")
                }
            }
        }
        val shared = periodsOfService.values.count { it.size > 1 }
        if (shared > 0) {
            val share = shared * 100 / services.size.coerceAtLeast(1)
            PipelineLog.info("  ! $shared of ${services.size} services ($share%) fall in more than one period")
        }

        val periods = mutableListOf<ServicePeriod>()
        for ((name, ids) in assigned) {
            if (ids.isNotEmpty()) {
                val desc = profile.periods[name]?.description?.takeIf { it.isNotBlank() } ?: "Profile period '$name'"
                periods.add(ServicePeriod(name, ids.sorted().toMutableList(), desc))
            }
        }

        val unmatched = services.keys.minus(matched).sorted()
        if (unmatched.isNotEmpty()) {
            if (profile.unmatched == "other") {
                periods.add(ServicePeriod("other", unmatched.toMutableList(), "${unmatched.size} service(s) not matched by the profile"))
            }
        }

        return periods
    }
}
