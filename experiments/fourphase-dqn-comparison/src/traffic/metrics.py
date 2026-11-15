"""Metrics that keep unfinished and not-yet-inserted vehicles visible."""

import math
import statistics
import xml.etree.ElementTree as ET


def mean_or_none(values):
    return statistics.fmean(values) if values else None


def summarize(schedule, tripinfo_path, samples, warmup, end):
    trips = {item.attrib["id"]: item.attrib for item in ET.parse(tripinfo_path).getroot().iter("tripinfo")}
    if not set(trips) <= set(schedule):
        raise ValueError("TripInfo contains vehicles absent from the demand file")
    started = {key: value for key, value in trips.items() if float(value["depart"]) >= 0}
    arrived = {key: value for key, value in started.items() if float(value["arrival"]) >= 0}
    due = {key for key, departure in schedule.items() if departure < end}
    future = set(schedule) - due
    unfinished = set(started) - set(arrived)
    pending = due - set(started)
    # Cohort membership depends on planned departures, never on controller performance.
    cohort = {key for key, departure in schedule.items() if warmup <= departure < end}
    cohort_started = cohort & set(started)
    cohort_arrived = cohort & set(arrived)
    measured = [row for row in samples if row["measured"]]
    queues = [row["network_halting"] for row in measured]
    ordered = sorted(queues)
    return {
        "counts": {
            "scheduled_total": len(schedule),
            "scheduled_before_end": len(due),
            "scheduled_after_end": len(future),
            "departed": len(started),
            "arrived": len(arrived),
            "unfinished": len(unfinished),
            "not_departed_due": len(pending),
            "cohort_due": len(cohort),
            "cohort_departed": len(cohort_started),
            "cohort_arrived": len(cohort_arrived),
            "cohort_unfinished": len(cohort_started - cohort_arrived),
            "cohort_not_departed": len(cohort - cohort_started),
            "arrived_during_measurement": sum(float(trip["arrival"]) > warmup for trip in arrived.values()),
        },
        "metrics": {
            "cohort_mean_waiting_observed_s": mean_or_none([
                float(started[key]["waitingTime"]) for key in sorted(cohort_started)
            ]),
            "cohort_completed_mean_waiting_s": mean_or_none([
                float(arrived[key]["waitingTime"]) for key in sorted(cohort_arrived)
            ]),
            "cohort_completed_mean_travel_s": mean_or_none([
                float(arrived[key]["duration"]) for key in sorted(cohort_arrived)
            ]),
            "cohort_mean_departure_delay_s": mean_or_none([
                float(started[key]["departDelay"]) for key in sorted(cohort_started)
            ]),
            "cohort_pending_departure_wait_s": sum(end - schedule[key] for key in sorted(cohort - cohort_started)),
            "network_queue_vehicle_seconds": sum(row["network_halting"] * row["step_seconds"] for row in measured),
            "network_queue_mean_vehicles": mean_or_none(queues),
            "network_queue_p95_vehicles": ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)] if ordered else None,
            "network_queue_max_vehicles": max(queues) if queues else None,
        },
    }
