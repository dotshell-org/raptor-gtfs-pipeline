package com.raptor.gtfs

import com.raptor.gtfs.models.ServicePeriod

object PeloPeriodAnalyzer {
    private val SCHOOL_WEEKDAY = Regex("-[0-9A-Za-z]+M-")
    private val VACATION_WEEKDAY = Regex("-[0-9A-Za-z]+[VW]-")

    fun build(reader: GTFSReader): List<ServicePeriod> {
        if (reader.calendar.isEmpty()) return emptyList()

        val jdRoutes = reader.routes
            .filter { it.routeShortName.startsWith("JD") || "-JD" in it.routeShortName }
            .map { it.routeId }.toSet()

        val serviceToRoutes = reader.trips.groupBy({ it.serviceId }, { it.routeId })
            .mapValues { it.value.toSet() }

        val schoolOn = mutableSetOf<String>()
        val schoolOff = mutableSetOf<String>()
        val saturdays = mutableSetOf<String>()
        val sundays = mutableSetOf<String>()

        for (cal in reader.calendar) {
            val sid = cal.serviceId
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
