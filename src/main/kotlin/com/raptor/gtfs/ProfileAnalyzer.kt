package com.raptor.gtfs

import com.charleskorn.kaml.Yaml
import com.raptor.gtfs.models.PeriodRule
import com.raptor.gtfs.models.Profile
import com.raptor.gtfs.models.ServicePeriod
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
            services[cal.serviceId] = active
        }
        for (cd in reader.calendarDates) {
            services.putIfAbsent(cd.serviceId, emptySet())
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
