package com.raptor.gtfs

import com.charleskorn.kaml.Yaml
import com.raptor.gtfs.models.PeriodRule
import com.raptor.gtfs.models.Profile
import com.raptor.gtfs.models.ServicePeriod
import java.io.File

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
