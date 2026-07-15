package com.raptor.gtfs

import com.charleskorn.kaml.Yaml
import com.raptor.gtfs.models.PeriodRule
import com.raptor.gtfs.models.Profile
import com.raptor.gtfs.models.ServicePeriod
import java.io.File

object CalendarAnalyzer {
    fun analyzeServicePeriods(reader: GTFSReader): List<ServicePeriod> {
        if (reader.calendar.isEmpty() && reader.calendarDates.isEmpty()) {
            return emptyList()
        }

        val patterns = mutableMapOf<List<Boolean>, MutableList<String>>()
        for (cal in reader.calendar) {
            val pattern = listOf(
                cal.monday, cal.tuesday, cal.wednesday,
                cal.thursday, cal.friday, cal.saturday, cal.sunday
            )
            patterns.computeIfAbsent(pattern) { mutableListOf() }.add(cal.service_id)
        }

        val periods = mutableListOf<ServicePeriod>()

        val weekdayPattern = listOf(true, true, true, true, true, false, false)
        patterns.remove(weekdayPattern)?.let {
            periods.add(ServicePeriod("weekday", it, "Monday to Friday service"))
        }

        val saturdayPattern = listOf(false, false, false, false, false, true, false)
        patterns.remove(saturdayPattern)?.let {
            periods.add(ServicePeriod("saturday", it, "Saturday service"))
        }

        val sundayPattern = listOf(false, false, false, false, false, false, true)
        patterns.remove(sundayPattern)?.let {
            periods.add(ServicePeriod("sunday", it, "Sunday and holidays service"))
        }

        val weekendPattern = listOf(false, false, false, false, false, true, true)
        patterns.remove(weekendPattern)?.let {
            periods.add(ServicePeriod("weekend", it, "Weekend service"))
        }

        val allweekPattern = listOf(true, true, true, true, true, true, true)
        patterns.remove(allweekPattern)?.let {
            periods.add(ServicePeriod("daily", it, "Daily service (all days)"))
        }

        if (patterns.isNotEmpty()) {
            val otherServiceIds = patterns.values.flatten().toMutableList()
            periods.add(ServicePeriod("other", otherServiceIds, "Other non-standard weekly patterns"))
        }

        if (periods.isEmpty() && reader.calendarDates.isNotEmpty()) {
            val servicesFromDates = reader.calendarDates.map { it.service_id }.distinct().sorted()
            periods.add(ServicePeriod("other", servicesFromDates.toMutableList(), "Services from calendar_dates.txt"))
        }

        return periods
    }

    fun getTripsForPeriod(reader: GTFSReader, period: ServicePeriod): Set<String> {
        val ids = period.service_ids.toSet()
        return reader.trips.filter { it.service_id in ids }.map { it.trip_id }.toSet()
    }
}

object PeloPeriodAnalyzer {
    private val SCHOOL_WEEKDAY = Regex("-[0-9A-Za-z]+M-")
    private val VACATION_WEEKDAY = Regex("-[0-9A-Za-z]+[VW]-")

    fun build(reader: GTFSReader): List<ServicePeriod> {
        if (reader.calendar.isEmpty()) return emptyList()

        val jdRoutes = reader.routes
            .filter { it.route_short_name.startsWith("JD") || "-JD" in it.route_short_name }
            .map { it.route_id }.toSet()

        val serviceToRoutes = reader.trips.groupBy({ it.service_id }, { it.route_id })
            .mapValues { it.value.toSet() }

        val schoolOn = mutableSetOf<String>()
        val schoolOff = mutableSetOf<String>()
        val saturdays = mutableSetOf<String>()
        val sundays = mutableSetOf<String>()

        for (cal in reader.calendar) {
            val sid = cal.service_id
            val routesForService = serviceToRoutes[sid] ?: emptySet()
            val isJdOnly = routesForService.isNotEmpty() && jdRoutes.containsAll(routesForService)
            val hasWeekday = cal.monday || cal.tuesday || cal.wednesday || cal.thursday || cal.friday
            val isAllWeek = cal.monday && cal.tuesday && cal.wednesday && cal.thursday && cal.friday && cal.saturday && cal.sunday

            if (hasWeekday) {
                if (isJdOnly) {
                    schoolOn.add(sid)
                } else if (isAllWeek) {
                    schoolOn.add(sid)
                    schoolOff.add(sid)
                } else if (VACATION_WEEKDAY.containsMatchIn(sid)) {
                    schoolOff.add(sid)
                } else if (SCHOOL_WEEKDAY.containsMatchIn(sid)) {
                    schoolOn.add(sid)
                } else {
                    schoolOn.add(sid)
                    schoolOff.add(sid)
                }
            }
            if (cal.saturday) saturdays.add(sid)
            if (cal.sunday) sundays.add(sid)
        }

        val specs = listOf(
            Triple("school_on_weekdays", schoolOn, "Weekdays during school periods"),
            Triple("school_off_weekdays", schoolOff, "Weekdays during school holidays"),
            Triple("saturday", saturdays, "Saturday service"),
            Triple("sunday", sundays, "Sunday service")
        )

        return specs.filter { it.second.isNotEmpty() }.map { (name, ids, desc) ->
            ServicePeriod(name, ids.sorted().toMutableList(), desc)
        }
    }
}

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

    private fun matches(rule: PeriodRule, serviceId: String, activeDays: Set<Int>): Boolean {
        if (rule.service_id_matches != null && !Regex(rule.service_id_matches).containsMatchIn(serviceId)) {
            return false
        }
        if (rule.days.isNotEmpty() && activeDays.intersect(parseDays(rule.days)).isEmpty()) {
            return false
        }
        return true
    }

    fun build(profile: Profile, reader: GTFSReader): List<ServicePeriod> {
        val services = mutableMapOf<String, Set<Int>>()
        for (cal in reader.calendar) {
            val active = mutableSetOf<Int>()
            if (cal.monday) active.add(0)
            if (cal.tuesday) active.add(1)
            if (cal.wednesday) active.add(2)
            if (cal.thursday) active.add(3)
            if (cal.friday) active.add(4)
            if (cal.saturday) active.add(5)
            if (cal.sunday) active.add(6)
            services[cal.service_id] = active
        }
        for (cd in reader.calendarDates) {
            services.putIfAbsent(cd.service_id, emptySet())
        }

        val assigned = profile.periods.keys.associateWith { mutableListOf<String>() }
        val matched = mutableSetOf<String>()

        for ((serviceId, activeDays) in services) {
            for ((name, rule) in profile.periods) {
                if (matches(rule, serviceId, activeDays)) {
                    assigned[name]!!.add(serviceId)
                    matched.add(serviceId)
                }
            }
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
