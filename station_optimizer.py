from math import inf
from typing import Sequence
from temperature_profile import add_relative_heat_burden
import numpy as np
import pandas as pd


def build_dp_table(
    positions: Sequence[float],
    segment_burden: dict[tuple[int, int], float],
    baseline_station_positions: Sequence[float],
    num_stations: int,
    min_gap_m: float,
    max_gap_m: float,
    max_movement_m: float,
) -> tuple[
    dict[tuple[int, int], float],
    dict[tuple[int, int], int],
]:
    """
    Build the DP table while enforcing spacing and station-movement limits.

    The kth optimized station is compared with the kth baseline station.
    """
    num_candidates = len(positions) - 2

    if num_stations < 1:
        raise ValueError("num_stations must be at least 1.")

    if num_stations > num_candidates:
        raise ValueError(
            "num_stations cannot exceed the number of candidate locations."
        )

    if len(baseline_station_positions) != num_stations:
        raise ValueError(
            "One baseline position is required for every station."
        )

    if min_gap_m <= 0:
        raise ValueError("min_gap_m must be positive.")

    if max_gap_m < min_gap_m:
        raise ValueError("max_gap_m cannot be smaller than min_gap_m.")

    if max_movement_m < 0:
        raise ValueError("max_movement_m cannot be negative.")

    dp: dict[tuple[int, int], float] = {}
    parent_table: dict[tuple[int, int], int] = {}

    for total_stations in range(1, num_stations + 1):
        baseline_position = baseline_station_positions[
            total_stations - 1
        ]

        for current_station in range(
            total_stations,
            len(positions) - 1,
        ):
            current_position = positions[current_station]

            station_movement_m = abs(
                current_position - baseline_position
            )

            # This candidate is too far from the corresponding
            # existing station.
            if station_movement_m > max_movement_m:
                continue

            current_state = (
                current_station,
                total_stations,
            )

            # Base case: start → first station.
            if total_stations == 1:
                first_gap_m = (
                    current_position
                    - positions[0]
                )

                if min_gap_m <= first_gap_m <= max_gap_m:
                    dp[current_state] = segment_burden[
                        (0, current_station)
                    ]

                    parent_table[current_state] = 0

                continue

            best_candidate = inf
            best_previous_station = None

            for previous_station in range(
                total_stations - 1,
                current_station,
            ):
                previous_state = (
                    previous_station,
                    total_stations - 1,
                )

                if previous_state not in dp:
                    continue

                gap_m = (
                    current_position
                    - positions[previous_station]
                )

                if not min_gap_m <= gap_m <= max_gap_m:
                    continue

                candidate = max(
                    dp[previous_state],
                    segment_burden[
                        (previous_station, current_station)
                    ],
                )

                if candidate < best_candidate:
                    best_candidate = candidate
                    best_previous_station = previous_station

            if best_previous_station is not None:
                dp[current_state] = best_candidate
                parent_table[current_state] = (
                    best_previous_station
                )

    return dp, parent_table


def select_best_complete_layout(
    positions: Sequence[float],
    segment_burden: dict[tuple[int, int], float],
    dp: dict[tuple[int, int], float],
    num_stations: int,
    min_gap_m: float,
    max_gap_m: float,
) -> tuple[int, float]:
    """
    Select the final-station location that gives the lowest
    worst-segment burden across the complete course.
    """
    finish = len(positions) - 1

    best_last_station = -1
    best_complete_score = inf

    for last_station in range(num_stations, finish):
        state = (last_station, num_stations)

        if state not in dp:
            continue

        final_gap_m = (
            positions[finish]
            - positions[last_station]
        )

        if not min_gap_m <= final_gap_m <= max_gap_m:
            continue

        complete_score = max(
            dp[state],
            segment_burden[(last_station, finish)],
        )

        if complete_score < best_complete_score:
            best_complete_score = complete_score
            best_last_station = last_station

    if best_last_station == -1:
        raise ValueError(
            "No complete station layout satisfies the spacing constraints."
        )

    return best_last_station, best_complete_score

def reconstruct_stations(
    parent_table: dict[tuple[int, int], int],
    best_last_station: int,
    num_stations: int,
) -> list[int]:

    stations = []

    current_station = best_last_station
    remaining_stations = num_stations

    while remaining_stations > 0:
        stations.append(current_station)

        current_station = parent_table[
            (current_station, remaining_stations)
        ]

        remaining_stations -= 1

    stations.reverse()

    return stations

def build_segment_burden_lookup(
    cumulative_burden: Sequence[float],
) -> dict[tuple[int, int], float]:
    """
    Calculate the heat burden between every pair of course points.

    The burden from point i to point j is the cumulative burden at
    j minus the cumulative burden at i.
    """
    segment_burden: dict[tuple[int, int], float] = {}

    for start_index in range(len(cumulative_burden) - 1):
        for end_index in range(
            start_index + 1,
            len(cumulative_burden),
        ):
            segment_burden[(start_index, end_index)] = float(
                cumulative_burden[end_index]
                - cumulative_burden[start_index]
            )

    return segment_burden

def optimize_station_placement(
    profile,
    baseline_station_positions,
    min_gap_m=1000,
    max_gap_m=2000,
    max_movement_m=500,
):
    """
    Find station positions that minimize the worst uninterrupted
    heat-burden segment while respecting spacing and movement limits.

    Returns
    -------
    optimized_stations:
        Rows from the route profile representing the selected stations.

    optimized_worst_burden:
        Heat burden of the worst segment in the optimized layout.
    """
    profile = add_relative_heat_burden(profile)

    positions = profile["distance_m"].to_list()

    segment_burden = build_segment_burden_lookup(
        profile["cumulative_heat_burden_c_m"].to_list()
    )

    num_stations = len(baseline_station_positions)

    dp, parent_table = build_dp_table(
        positions=positions,
        segment_burden=segment_burden,
        baseline_station_positions=baseline_station_positions,
        num_stations=num_stations,
        min_gap_m=min_gap_m,
        max_gap_m=max_gap_m,
        max_movement_m=max_movement_m,
    )

    best_last_station, optimized_worst_burden = (
        select_best_complete_layout(
            positions=positions,
            segment_burden=segment_burden,
            dp=dp,
            num_stations=num_stations,
            min_gap_m=min_gap_m,
            max_gap_m=max_gap_m,
        )
    )

    station_indices = reconstruct_stations(
        parent_table=parent_table,
        best_last_station=best_last_station,
        num_stations=num_stations,
    )

    optimized_stations = profile.iloc[station_indices].copy()

    optimized_stations.insert(
        0,
        "station_id",
        [
            f"OPT_{station_number}"
            for station_number in range(1, num_stations + 1)
        ],
    )

    optimized_stations["baseline_distance_m"] = list(
        baseline_station_positions
    )

    optimized_stations["movement_m"] = (
        optimized_stations["distance_m"]
        - optimized_stations["baseline_distance_m"]
    ).abs()

    optimized_stations = optimized_stations.reset_index(drop=True)

    return optimized_stations, optimized_worst_burden

def evaluate_station_layouts(
    profile,
    baseline_station_positions,
    optimized_stations,
):
    """
    Compare the current and optimized station layouts.

    Returns
    -------
    summary:
        Human-readable comparison metrics for the UI.

    baseline_segments:
        Exposure between each pair of current relief boundaries.

    optimized_segments:
        Exposure between each pair of proposed relief boundaries.
    """

    profile = add_relative_heat_burden(profile)

    course_distances = profile["distance_m"].to_numpy()
    cumulative_burden = profile[
        "cumulative_heat_burden_c_m"
    ].to_numpy()

    course_finish_m = float(course_distances[-1])
    total_burden = float(cumulative_burden[-1])

    def build_segment_table(
        layout_name,
        station_positions,
        station_ids,
    ):
        boundaries = np.array(
            [0.0, *station_positions, course_finish_m],
            dtype=float,
        )

        boundary_names = [
            "START",
            *station_ids,
            "FINISH",
        ]

        # Estimate cumulative burden at boundaries that fall between
        # the course's 100 m sample points.
        boundary_burden = np.interp(
            boundaries,
            course_distances,
            cumulative_burden,
        )

        rows = []

        for index in range(len(boundaries) - 1):
            start_distance = boundaries[index]
            end_distance = boundaries[index + 1]

            segment_burden = (
                boundary_burden[index + 1]
                - boundary_burden[index]
            )

            burden_share = (
                100 * segment_burden / total_burden
                if total_burden > 0
                else 0.0
            )

            rows.append(
                {
                    "layout": layout_name,
                    "segment_id": index + 1,
                    "start_boundary": boundary_names[index],
                    "end_boundary": boundary_names[index + 1],
                    "start_distance_m": start_distance,
                    "end_distance_m": end_distance,
                    "segment_distance_m": (
                        end_distance - start_distance
                    ),
                    "segment_distance_km": (
                        end_distance - start_distance
                    )
                    / 1000,
                    "relative_heat_burden_c_m": segment_burden,
                    "burden_share_percent": burden_share,
                }
            )

        segments = pd.DataFrame(rows)

        worst_index = segments[
            "relative_heat_burden_c_m"
        ].idxmax()

        segments["is_worst_segment"] = False
        segments.loc[worst_index, "is_worst_segment"] = True

        return segments

    baseline_ids = [
        f"AID_{number}"
        for number in range(
            1,
            len(baseline_station_positions) + 1,
        )
    ]

    baseline_segments = build_segment_table(
        layout_name="baseline",
        station_positions=baseline_station_positions,
        station_ids=baseline_ids,
    )

    optimized_segments = build_segment_table(
        layout_name="optimized",
        station_positions=optimized_stations[
            "distance_m"
        ].to_list(),
        station_ids=optimized_stations[
            "station_id"
        ].to_list(),
    )

    baseline_worst = baseline_segments.loc[
        baseline_segments["relative_heat_burden_c_m"].idxmax()
    ]

    optimized_worst = optimized_segments.loc[
        optimized_segments["relative_heat_burden_c_m"].idxmax()
    ]

    baseline_worst_burden = float(
        baseline_worst["relative_heat_burden_c_m"]
    )

    optimized_worst_burden = float(
        optimized_worst["relative_heat_burden_c_m"]
    )

    burden_reduction_percent = (
        100
        * (
            baseline_worst_burden
            - optimized_worst_burden
        )
        / baseline_worst_burden
        if baseline_worst_burden > 0
        else 0.0
    )

    summary = {
        "worst_exposure_reduction_percent": (
            burden_reduction_percent
        ),
        "baseline_worst_burden_share_percent": float(
            baseline_worst["burden_share_percent"]
        ),
        "optimized_worst_burden_share_percent": float(
            optimized_worst["burden_share_percent"]
        ),
        "baseline_worst_segment_distance_km": float(
            baseline_worst["segment_distance_km"]
        ),
        "optimized_worst_segment_distance_km": float(
            optimized_worst["segment_distance_km"]
        ),
        "maximum_station_movement_m": float(
            optimized_stations["movement_m"].max()
        ),
        "total_station_movement_m": float(
            optimized_stations["movement_m"].sum()
        ),
        "baseline_worst_burden_c_m": (
            baseline_worst_burden
        ),
        "optimized_worst_burden_c_m": (
            optimized_worst_burden
        ),
    }

    return summary, baseline_segments, optimized_segments