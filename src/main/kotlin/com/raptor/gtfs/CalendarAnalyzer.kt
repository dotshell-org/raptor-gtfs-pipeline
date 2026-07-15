package com.raptor.gtfs

import com.raptor.gtfs.models.ServicePeriod

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
            patterns.computeIfAbsent(pattern) { mutableListOf() }.add(cal.serviceId)
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
            val servicesFromDates = reader.calendarDates.map { it.serviceId }.distinct().sorted()
            periods.add(ServicePeriod("other", servicesFromDates.toMutableList(), "Services from calendar_dates.txt"))
        }

        return periods
    }

    fun getTripsForPeriod(reader: GTFSReader, period: ServicePeriod): Set<String> {
        val ids = period.serviceIds.toSet()
        return reader.trips.filter { it.serviceId in ids }.map { it.tripId }.toSet()
    }
}
