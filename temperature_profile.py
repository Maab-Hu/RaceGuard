"""Functions for building RaceGuard's route-temperature profile."""
import math
from pathlib import Path
import geopandas as gpd
import numpy as np
import json
import pandas as pd

def build_route_temperature_profile(
    course_path,
    heatmap_path,
    spacing_m=100,
    max_nearest_distance_m=50,
):
    course_points = sample_course_points(
        course_path,
        spacing_m=spacing_m,
    )

    heatmap_tiles = load_heatmap_tiles(
        heatmap_path,
    )

    return match_course_points_to_heatmap(
        course_points,
        heatmap_tiles,
        max_nearest_distance_m=max_nearest_distance_m,
    )

def sample_course_points(
    course_path,
    spacing_m=100,
):
    """
    Generate evenly spaced points along a course.

    Parameters
    ----------
    course_path:
        Path to a GeoJSON containing one LineString course.

    spacing_m:
        Distance in metres between consecutive samples.

    Returns
    -------
    geopandas.GeoDataFrame
        Route samples in EPSG:4326 with their distances, coordinates
        and Point geometries.
    """
    if spacing_m <= 0:
        raise ValueError(
            "spacing_m must be greater than zero."
        )

    spacing_m = float(spacing_m)

    if isinstance(course_path, gpd.GeoDataFrame):
        course = course_path.copy()

    else:
        course_path = Path(course_path)

        if not course_path.is_file():
            raise FileNotFoundError(
                f"Course file not found: {course_path}"
            )

        course = gpd.read_file(course_path)

    if len(course) != 1:
        raise ValueError(
            "The course must contain exactly one feature."
        )

    if course.crs is None:
        raise ValueError(
            "The course has no coordinate reference system."
        )

    course_line = course.geometry.iloc[0]

    if course_line.geom_type != "LineString":
        raise ValueError(
            "The course geometry must be a LineString."
        )

    if course_line.is_empty or not course_line.is_valid:
        raise ValueError(
            "The course LineString must be non-empty and valid."
        )

    # Latitude and longitude use degrees, so estimate a local projected
    # coordinate system where distances are measured in metres.
    metric_crs = course.estimate_utm_crs()

    if metric_crs is None:
        raise ValueError(
            "A metre-based CRS could not be estimated."
        )

    course_metric = course.to_crs(metric_crs)
    course_line_metric = course_metric.geometry.iloc[0]

    course_length_m = float(
        course_line_metric.length
    )

    # Generate 0, 100, 200... up to the final complete interval.
    complete_steps = int(
        course_length_m // spacing_m
    )

    sample_distances = [
        step * spacing_m
        for step in range(complete_steps + 1)
    ]

    # The course is about 9,990 metres, not exactly 10,000 metres.
    # Append its exact finish unless it is already in the list.
    if not math.isclose(
        sample_distances[-1],
        course_length_m,
        abs_tol=1e-6,
    ):
        sample_distances.append(course_length_m)

    # Interpolate walks along the LineString and returns the point at
    # each requested cumulative distance.
    sample_points = [
        course_line_metric.interpolate(distance_m)
        for distance_m in sample_distances
    ]

    samples_metric = gpd.GeoDataFrame(
        {
            "sample_id": range(
                len(sample_distances)
            ),
            "distance_m": sample_distances,
            "distance_km": [
                distance_m / 1000
                for distance_m in sample_distances
            ],
        },
        geometry=sample_points,
        crs=metric_crs,
    )

    # Convert the newly generated points back to longitude/latitude.
    samples_geo = samples_metric.to_crs(
        "EPSG:4326"
    )

    samples_geo["latitude"] = (
        samples_geo.geometry.y
    )

    samples_geo["longitude"] = (
        samples_geo.geometry.x
    )

    samples_geo = samples_geo[
        [
            "sample_id",
            "distance_m",
            "distance_km",
            "latitude",
            "longitude",
            "geometry",
        ]
    ].copy()

    # Store useful information about how the samples were generated.
    samples_geo.attrs["course_length_m"] = (
        course_length_m
    )

    samples_geo.attrs["spacing_m"] = spacing_m

    samples_geo.attrs["metric_crs"] = (
        metric_crs.to_string()
    )

    return samples_geo

def load_heatmap_tiles(
    heatmap_path,
):
    if isinstance(heatmap_path, dict):
        payload = heatmap_path

    else:
        heatmap_path = Path(heatmap_path)

        if not heatmap_path.is_file():
            raise FileNotFoundError(
                f"Heatmap file not found: {heatmap_path}"
            )

        with heatmap_path.open(
            "r",
            encoding="utf-8",
        ) as file:
            payload = json.load(file)

    if not isinstance(payload, dict):
        raise ValueError(
            "Heatmap payload is not a dictionary."
        )

    result = payload.get("result")

    if not isinstance(result, dict):
        raise ValueError(
            "Heatmap payload has no valid 'result' object."
        )

    map_data = result.get("map_data")

    if not isinstance(map_data, dict):
        raise ValueError(
            "Heatmap result has no valid 'map_data' object."
        )

    if map_data.get("type") != "FeatureCollection":
        raise ValueError(
            "Expected map_data to be a GeoJSON "
            f"FeatureCollection, got {map_data.get('type')!r}."
        )

    features = map_data.get("features")

    if not isinstance(features, list) or not features:
        raise ValueError(
            "Heatmap contains no feature list."
        )

    heatmap = gpd.GeoDataFrame.from_features(
        features,
        crs="EPSG:4326",
    )

    heatmap = heatmap.reset_index(
        drop=True
    )

    if "tile_id" not in heatmap.columns:
        raise ValueError(
            "Heatmap tiles have no 'tile_id' field."
        )

    if not heatmap["tile_id"].is_unique:
        raise ValueError(
            "Heatmap tile IDs must be unique."
        )

    if (
        heatmap.geometry.isna().any()
        or heatmap.geometry.is_empty.any()
    ):
        raise ValueError(
            "Heatmap contains missing or empty geometry."
        )

    allowed_geometry_types = {
        "Polygon",
        "MultiPolygon",
    }

    geometry_types = set(
        heatmap.geometry.geom_type
    )

    if not geometry_types.issubset(
        allowed_geometry_types
    ):
        raise ValueError(
            "Heatmap contains unsupported geometry types: "
            f"{sorted(geometry_types)}"
        )

    if not heatmap.geometry.is_valid.all():
        raise ValueError(
            "Heatmap contains invalid polygon geometry."
        )

    temperature_columns = (
        "average_temperature",
        "temperature",
    )

    temperature_column = next(
        (
            column
            for column in temperature_columns
            if column in heatmap.columns
        ),
        None,
    )

    if temperature_column is None:
        raise ValueError(
            "Heatmap tiles contain no average temperature."
        )

    heatmap["average_temperature"] = pd.to_numeric(
        heatmap[temperature_column],
        errors="coerce",
    )

    if heatmap["average_temperature"].isna().any():
        raise ValueError(
            "One or more heatmap tiles have an invalid "
            "average temperature."
        )

    return heatmap

def match_course_points_to_heatmap(
    course_points,
    heatmap_tiles,
    max_nearest_distance_m=50,
):
    """
    Attach a heatmap tile and temperature to every sampled course point.

    Direct polygon intersections are preferred. Points without a direct
    intersection may use the nearest tile within max_nearest_distance_m.
    """

    if course_points.empty:
        raise ValueError("Course points are empty.")

    if heatmap_tiles.empty:
        raise ValueError("Heatmap tiles are empty.")

    if course_points.crs is None:
        raise ValueError("Course points do not have a CRS.")

    if heatmap_tiles.crs is None:
        raise ValueError("Heatmap tiles do not have a CRS.")

    if not course_points.index.is_unique:
        raise ValueError("Course point indices must be unique.")

    if max_nearest_distance_m < 0:
        raise ValueError("Maximum nearest-tile distance cannot be negative.")

    required_tile_columns = {
        "tile_id",
        "average_temperature",
        "geometry",
    }

    missing_columns = required_tile_columns - set(heatmap_tiles.columns)

    if missing_columns:
        raise ValueError(
            f"Heatmap tiles are missing columns: {sorted(missing_columns)}"
        )

    points = course_points.copy()

    tiles = heatmap_tiles[
        ["tile_id", "average_temperature", "geometry"]
    ].copy()

    # Spatial joins require both datasets to use the same CRS.
    if tiles.crs != points.crs:
        tiles = tiles.to_crs(points.crs)

    # Find tiles that directly cover or touch each course point.
    profile = gpd.sjoin(
        points,
        tiles,
        how="left",
        predicate="intersects",
    )

    # A boundary point can match multiple tiles. Sorting places the lowest
    # tile_id first, after which repeated course-point indices are removed.
    profile = profile.sort_values(
        "tile_id",
        ascending=True,
        kind="stable",
        na_position="last",
    )

    profile = profile[
        ~profile.index.duplicated(keep="first")
    ]

    # Restore the original start-to-finish course order.
    profile = profile.loc[points.index].copy()

    profile["match_method"] = "intersects"
    profile["tile_distance_m"] = 0.0

    unmatched_mask = profile["tile_id"].isna()

    profile.loc[
        unmatched_mask,
        "match_method",
    ] = None

    profile.loc[
        unmatched_mask,
        "tile_distance_m",
    ] = float("nan")

    if unmatched_mask.any():
        # GeoPandas needs a metric CRS so max_distance=50 means 50 metres.
        metric_crs = points.estimate_utm_crs()

        if metric_crs is None:
            raise ValueError(
                "Could not determine a metric CRS for nearest-tile matching."
            )

        unmatched_points_metric = points.loc[
            unmatched_mask,
            ["geometry"],
        ].to_crs(metric_crs)

        tiles_metric = tiles.to_crs(metric_crs)

        nearest_matches = gpd.sjoin_nearest(
            unmatched_points_metric,
            tiles_metric,
            how="left",
            max_distance=max_nearest_distance_m,
            distance_col="tile_distance_m",
        )

        # Equidistant tiles can produce multiple rows. Apply the same
        # lowest-tile-ID rule used for direct boundary matches.
        nearest_matches = nearest_matches.sort_values(
            "tile_id",
            ascending=True,
            kind="stable",
            na_position="last",
        )

        nearest_matches = nearest_matches[
            ~nearest_matches.index.duplicated(keep="first")
        ]

        valid_nearest_matches = nearest_matches[
            nearest_matches["tile_id"].notna()
        ]

        matched_indices = valid_nearest_matches.index

        profile.loc[
            matched_indices,
            "tile_id",
        ] = valid_nearest_matches["tile_id"]

        profile.loc[
            matched_indices,
            "average_temperature",
        ] = valid_nearest_matches["average_temperature"]

        profile.loc[
            matched_indices,
            "match_method",
        ] = "nearest"

        profile.loc[
            matched_indices,
            "tile_distance_m",
        ] = valid_nearest_matches["tile_distance_m"]

    unresolved_mask = profile["tile_id"].isna()

    if unresolved_mask.any():
        useful_columns = [
            column
            for column in ["distance_m", "distance_km"]
            if column in profile.columns
        ]

        unresolved_points = profile.loc[
            unresolved_mask,
            useful_columns,
        ].to_dict("records")

        raise ValueError(
            f"{unresolved_mask.sum()} course points have no heatmap tile "
            f"within {max_nearest_distance_m} metres: "
            f"{unresolved_points}"
        )

    if profile["average_temperature"].isna().any():
        raise ValueError(
            "At least one matched heatmap tile has no average temperature."
        )

    # The left join temporarily converts tile_id to float because it contains
    # NaN values. Restore the heatmap's original tile-ID datatype.
    profile["tile_id"] = profile["tile_id"].astype(
        heatmap_tiles["tile_id"].dtype
    )

    # index_right is an internal spatial-join reference, not product data.
    profile = profile.drop(
        columns=["index_right"],
        errors="ignore",
    )

    return profile

def add_relative_heat_burden(profile):
    """
    Add relative heat intensity and accumulated heat burden to a
    route-temperature profile.

    The coolest route temperature is used as the reference temperature.

    interval_heat_burden_c_m represents the relative heat accumulated
    while travelling from the previous row to the current row.

    cumulative_heat_burden_c_m represents the total relative heat
    accumulated from the course start to the current row.
    """

    required_columns = {
        "distance_m",
        "average_temperature",
    }

    missing_columns = required_columns - set(profile.columns)

    if missing_columns:
        raise ValueError(
            f"Profile is missing required columns: {sorted(missing_columns)}"
        )

    if len(profile) < 2:
        raise ValueError(
            "At least two course points are required to calculate heat burden."
        )

    result = (
        profile
        .sort_values("distance_m")
        .reset_index(drop=True)
        .copy()
    )

    distances_m = result["distance_m"].to_numpy(dtype=float)

    temperatures_c = (
        result["average_temperature"]
        .to_numpy(dtype=float)
    )

    if not np.isfinite(distances_m).all():
        raise ValueError("Course distances contain missing or invalid values.")

    if not np.isfinite(temperatures_c).all():
        raise ValueError("Course temperatures contain missing or invalid values.")

    interval_distances_m = np.diff(distances_m)

    if np.any(interval_distances_m <= 0):
        raise ValueError(
            "Course distances must increase strictly from start to finish."
        )

    reference_temperature_c = temperatures_c.min()

    temperature_excess_c = (
        temperatures_c - reference_temperature_c
    )

    average_interval_excess_c = (
        temperature_excess_c[:-1]
        + temperature_excess_c[1:]
    ) / 2

    calculated_interval_burdens = (
        average_interval_excess_c
        * interval_distances_m
    )

    interval_heat_burden_c_m = np.zeros(
        len(result),
        dtype=float,
    )

    interval_heat_burden_c_m[1:] = (
        calculated_interval_burdens
    )

    cumulative_heat_burden_c_m = np.cumsum(
        interval_heat_burden_c_m
    )

    result["heat_reference_temperature_c"] = (
        reference_temperature_c
    )

    result["temperature_excess_c"] = (
        temperature_excess_c
    )

    result["interval_distance_m"] = np.concatenate(
        ([0.0], interval_distances_m)
    )

    result["interval_heat_burden_c_m"] = (
        interval_heat_burden_c_m
    )

    result["cumulative_heat_burden_c_m"] = (
        cumulative_heat_burden_c_m
    )

    return result

def _cumulative_burden_at_distance(
    burden_profile,
    target_distance_m,
):
    """
    Calculate cumulative relative heat burden at an exact course distance.

    When the requested distance falls between two sampled course points,
    temperature excess is linearly interpolated and the partial interval
    is integrated using the trapezoidal rule.
    """

    required_columns = {
        "distance_m",
        "temperature_excess_c",
        "cumulative_heat_burden_c_m",
    }

    missing_columns = (
        required_columns - set(burden_profile.columns)
    )

    if missing_columns:
        raise ValueError(
            "Burden profile is missing required columns: "
            f"{sorted(missing_columns)}"
        )

    route = (
        burden_profile
        .sort_values("distance_m")
        .reset_index(drop=True)
    )

    distances_m = route["distance_m"].to_numpy(dtype=float)

    temperature_excess_c = (
        route["temperature_excess_c"]
        .to_numpy(dtype=float)
    )

    cumulative_burden_c_m = (
        route["cumulative_heat_burden_c_m"]
        .to_numpy(dtype=float)
    )

    target_distance_m = float(target_distance_m)

    course_start_m = distances_m[0]
    course_finish_m = distances_m[-1]

    if not (
        course_start_m
        <= target_distance_m
        <= course_finish_m
    ):
        raise ValueError(
            f"Distance {target_distance_m:.2f} m is outside "
            f"the course range "
            f"{course_start_m:.2f}–{course_finish_m:.2f} m."
        )

    insertion_index = np.searchsorted(
        distances_m,
        target_distance_m,
        side="left",
    )

    if (
        insertion_index < len(distances_m)
        and np.isclose(
            distances_m[insertion_index],
            target_distance_m,
        )
    ):
        return cumulative_burden_c_m[insertion_index]

    right_index = insertion_index
    left_index = right_index - 1

    left_distance_m = distances_m[left_index]
    right_distance_m = distances_m[right_index]

    left_excess_c = temperature_excess_c[left_index]
    right_excess_c = temperature_excess_c[right_index]

    interval_fraction = (
        (target_distance_m - left_distance_m)
        / (right_distance_m - left_distance_m)
    )

    target_excess_c = (
        left_excess_c
        + interval_fraction
        * (right_excess_c - left_excess_c)
    )

    partial_distance_m = (
        target_distance_m - left_distance_m
    )

    partial_burden_c_m = (
        (left_excess_c + target_excess_c)
        / 2
        * partial_distance_m
    )

    return (
        cumulative_burden_c_m[left_index]
        + partial_burden_c_m
    )


def evaluate_station_heat_segments(
    burden_profile,
    station_distances_m,
    station_ids=None,
):
    """
    Divide the course into segments using station locations and calculate
    the uninterrupted relative heat burden within every segment.
    """

    station_distances_m = np.asarray(
        station_distances_m,
        dtype=float,
    )

    if len(station_distances_m) == 0:
        raise ValueError(
            "At least one station distance is required."
        )

    if not np.isfinite(station_distances_m).all():
        raise ValueError(
            "Station distances contain missing or invalid values."
        )

    if station_ids is None:
        station_ids = [
            f"STATION_{number}"
            for number in range(
                1,
                len(station_distances_m) + 1,
            )
        ]
    else:
        station_ids = list(station_ids)

    if len(station_ids) != len(station_distances_m):
        raise ValueError(
            "The number of station IDs must match "
            "the number of station distances."
        )

    station_pairs = sorted(
        zip(station_distances_m, station_ids),
        key=lambda pair: pair[0],
    )

    sorted_station_distances_m = np.array(
        [pair[0] for pair in station_pairs],
        dtype=float,
    )

    sorted_station_ids = [
        pair[1] for pair in station_pairs
    ]

    if np.any(np.diff(sorted_station_distances_m) <= 0):
        raise ValueError(
            "Station distances must be unique."
        )

    course_start_m = float(
        burden_profile["distance_m"].min()
    )

    course_finish_m = float(
        burden_profile["distance_m"].max()
    )

    if np.any(
        sorted_station_distances_m <= course_start_m
    ):
        raise ValueError(
            "Every station must be after the course start."
        )

    if np.any(
        sorted_station_distances_m >= course_finish_m
    ):
        raise ValueError(
            "Every station must be before the course finish."
        )

    boundary_distances_m = np.concatenate(
        (
            [course_start_m],
            sorted_station_distances_m,
            [course_finish_m],
        )
    )

    boundary_names = [
        "START",
        *sorted_station_ids,
        "FINISH",
    ]

    boundary_burdens_c_m = np.array(
        [
            _cumulative_burden_at_distance(
                burden_profile,
                distance_m,
            )
            for distance_m in boundary_distances_m
        ],
        dtype=float,
    )

    segment_distances_m = np.diff(
        boundary_distances_m
    )

    segment_burdens_c_m = np.diff(
        boundary_burdens_c_m
    )

    average_excess_c = (
        segment_burdens_c_m
        / segment_distances_m
    )

    segments = pd.DataFrame(
        {
            "segment_id": np.arange(
                1,
                len(segment_distances_m) + 1,
            ),
            "start_boundary": boundary_names[:-1],
            "end_boundary": boundary_names[1:],
            "start_distance_m": boundary_distances_m[:-1],
            "end_distance_m": boundary_distances_m[1:],
            "segment_distance_m": segment_distances_m,
            "segment_distance_km": (
                segment_distances_m / 1000
            ),
            "segment_heat_burden_c_m": segment_burdens_c_m,
            "average_temperature_excess_c": average_excess_c,
        }
    )

    maximum_burden_c_m = (
        segments["segment_heat_burden_c_m"].max()
    )

    segments["is_worst_segment"] = np.isclose(
        segments["segment_heat_burden_c_m"],
        maximum_burden_c_m,
    )

    return segments