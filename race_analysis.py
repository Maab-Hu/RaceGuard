from typing import Sequence

import numpy as np
import pandas as pd

import station_optimizer


def analyze_station_plan(
    race_name: str,
    profile: pd.DataFrame,
    baseline_station_positions: Sequence[float],
    baseline_station_data: pd.DataFrame | None = None,
    min_gap_m: float = 1000,
    max_gap_m: float | None = None,
    max_movement_m: float = 500,
) -> dict[str, object]:
    """
    Run the station optimizer and package its results for the UI.

    baseline_station_positions contains each current station's distance
    along the course, in metres.

    baseline_station_data is optional. When supplied, its real station
    IDs and coordinates are used. Otherwise, coordinates are estimated
    from the route profile.
    """

    route_profile = (
        profile
        .sort_values("distance_m")
        .reset_index(drop=True)
        .copy()
    )

    baseline_positions = np.asarray(
        baseline_station_positions,
        dtype=float,
    )

    route_length_m = float(route_profile["distance_m"].iloc[-1])

    # When the client does not set a maximum gap, preserve the largest
    # gap already present in the current station layout.
    if max_gap_m is None:
        baseline_boundaries = np.array(
            [
                0.0,
                *baseline_positions,
                route_length_m,
            ]
        )
        max_gap_m = float(np.diff(baseline_boundaries).max())
        max_gap_source = "current layout"
    else:
        max_gap_m = float(max_gap_m)
        max_gap_source = "client selected"

    optimized_stations, _ = (
        station_optimizer.optimize_station_placement(
            profile=route_profile,
            baseline_station_positions=baseline_positions,
            min_gap_m=min_gap_m,
            max_gap_m=max_gap_m,
            max_movement_m=max_movement_m,
        )
    )

    (
        summary,
        baseline_segments,
        optimized_segments,
    ) = station_optimizer.evaluate_station_layouts(
        profile=route_profile,
        baseline_station_positions=baseline_positions,
        optimized_stations=optimized_stations,
    )

    profile_distances = route_profile["distance_m"].to_numpy()

    # Estimate current station values from the route profile. Real
    # coordinates will replace these estimates when station data exists.
    current_latitudes = np.interp(
        baseline_positions,
        profile_distances,
        route_profile["latitude"].to_numpy(),
    )
    current_longitudes = np.interp(
        baseline_positions,
        profile_distances,
        route_profile["longitude"].to_numpy(),
    )
    current_temperatures = np.interp(
        baseline_positions,
        profile_distances,
        route_profile["average_temperature"].to_numpy(),
    )

    station_ids = [
        f"STATION_{number}"
        for number in range(1, len(baseline_positions) + 1)
    ]

    station_data = None

    if baseline_station_data is not None:
        station_data = baseline_station_data.reset_index(drop=True).copy()

        if len(station_data) != len(baseline_positions):
            raise ValueError(
                "baseline_station_data must contain one row for each "
                "baseline station position."
            )

        if "station_id" in station_data.columns:
            station_ids = station_data["station_id"].tolist()

        if {"latitude", "longitude"}.issubset(station_data.columns):
            current_latitudes = station_data["latitude"].to_numpy()
            current_longitudes = station_data["longitude"].to_numpy()

    proposed_positions = optimized_stations["distance_m"].to_numpy()
    signed_movements = proposed_positions - baseline_positions

    movement_directions = np.where(
        signed_movements > 0,
        "later along course",
        np.where(
            signed_movements < 0,
            "earlier along course",
            "unchanged",
        ),
    )

    station_movements = pd.DataFrame(
        {
            "station_id": station_ids,
            "current_distance_m": baseline_positions,
            "current_distance_km": baseline_positions / 1000,
            "proposed_distance_m": proposed_positions,
            "proposed_distance_km": proposed_positions / 1000,
            "movement_m": np.abs(signed_movements),
            "movement_direction": movement_directions,
            "current_latitude": current_latitudes,
            "current_longitude": current_longitudes,
            "proposed_latitude": optimized_stations[
                "latitude"
            ].to_numpy(),
            "proposed_longitude": optimized_stations[
                "longitude"
            ].to_numpy(),
            "current_temperature": current_temperatures,
            "proposed_temperature": optimized_stations[
                "average_temperature"
            ].to_numpy(),
        }
    )

    # Carry station facility information into the UI result when available.
    if station_data is not None:
        facility_columns = [
            "side_count",
            "has_water",
            "has_restrooms",
            "has_first_aid",
            "position_uncertainty_m",
            "source_url",
        ]

        for column in facility_columns:
            if column in station_data.columns:
                station_movements[column] = station_data[column].to_numpy()

    headline = (
        f"{summary['worst_exposure_reduction_percent']:.1f}% reduction "
        "in worst uninterrupted relative heat exposure"
    )

    return {
        "race_name": race_name,
        "headline": headline,
        "metric_description": (
            "The optimizer minimizes the largest accumulated "
            "route-relative temperature burden runners experience "
            "between consecutive relief opportunities."
        ),
        "summary": summary,
        "constraints": {
            "minimum_station_gap_m": float(min_gap_m),
            "maximum_station_gap_m": max_gap_m,
            "maximum_station_movement_m": float(max_movement_m),
            "maximum_gap_source": max_gap_source,
        },
        "route_profile": route_profile,
        "station_movements": station_movements,
        "baseline_segments": baseline_segments,
        "optimized_segments": optimized_segments,
    }