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
                    var activeInAugust = false
                    var activeInSept = false
                    if (cal.startDate.length == 8 && cal.endDate.length == 8) {
                        val year = cal.startDate.substring(0, 4)
                        val aug15 = "${year}0815"
                        val sep15 = "${year}0915"
                        if (cal.startDate <= aug15 && cal.endDate >= aug15) activeInAugust = true
                        if (cal.startDate <= sep15 && cal.endDate >= sep15) activeInSept = true
                    }
                    
                    if (activeInAugust && !activeInSept) {
                        schoolOff.add(sid)
                    } else if (activeInSept && !activeInAugust) {
                        schoolOn.add(sid)
                    } else if (!activeInAugust && !activeInSept && cal.startDate.length == 8 && cal.endDate.length == 8) {
                        val sYear = cal.startDate.substring(0, 4).toIntOrNull() ?: 0
                        val eYear = cal.endDate.substring(0, 4).toIntOrNull() ?: 0
                        val sMonth = cal.startDate.substring(4, 6).toIntOrNull() ?: 0
                        val eMonth = cal.endDate.substring(4, 6).toIntOrNull() ?: 0
                        val monthDiff = (eYear - sYear) * 12 + (eMonth - sMonth)
                        if (monthDiff <= 1) {
                            schoolOff.add(sid)
                        } else {
                            schoolOn.add(sid)
                            schoolOff.add(sid)
                        }
                    } else {
                        schoolOn.add(sid)
                        schoolOff.add(sid)
                    }
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
