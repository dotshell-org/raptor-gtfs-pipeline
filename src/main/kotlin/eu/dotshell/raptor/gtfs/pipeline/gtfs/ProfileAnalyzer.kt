package eu.dotshell.raptor.gtfs.pipeline.gtfs

import com.charleskorn.kaml.Yaml
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

    private fun matchesRule(rule: PeriodRule, serviceId: String, activeDays: Set<Int>, cal: Calendar?): Boolean {
        if (rule.serviceIdMatches != null && !Regex(rule.serviceIdMatches).containsMatchIn(serviceId)) {
            return false
        }
        if (rule.days.isNotEmpty() && activeDays.intersect(parseDays(rule.days)).isEmpty()) {
            return false
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

        val assigned = profile.periods.keys.associateWith { mutableListOf<String>() }
        val matched = mutableSetOf<String>()

        for ((serviceId, activeDays) in services) {
            val cal = calendars[serviceId]
            for ((name, def) in profile.periods) {
                val effectiveRules = def.getEffectiveRules()
                var anyMatch = false
                if (effectiveRules.isEmpty()) {
                    // if no rules, it matches everything (fallback behavior)
                    anyMatch = true
                } else {
                    for (rule in effectiveRules) {
                        if (matchesRule(rule, serviceId, activeDays, cal)) {
                            anyMatch = true
                            break
                        }
                    }
                }
                
                if (anyMatch) {
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
