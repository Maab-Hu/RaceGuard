from io import BytesIO
import geopandas as gpd
import pandas as pd
from timezonefinder import TimezoneFinder

def detect_course_timezone(course) -> str:
    """
    Detect the local timezone containing the middle of the race course.
    """
    course_wgs84 = course.to_crs("EPSG:4326")
    course_line = course_wgs84.geometry.iloc[0]

    course_midpoint = course_line.interpolate(
        0.5,
        normalized=True,
    )

    timezone_name = TimezoneFinder().timezone_at(
        lng=course_midpoint.x,
        lat=course_midpoint.y,
    )

    if timezone_name is None:
        raise ValueError(
            "RaceGuard could not detect the course timezone."
        )

    return timezone_name

def locate_stations_on_course(
    course: gpd.GeoDataFrame,
    stations: pd.DataFrame,
    location_method: str,
    max_snap_distance_m: float = 500,
) -> pd.DataFrame:
    """
    Convert uploaded station locations into distances along the race course.

    Course distance is authoritative when supplied. Coordinates are used
    either for validation or, when no distance exists, for snapping the
    station to the nearest point on the course.
    """
    if course.crs is None:
        raise ValueError("The uploaded course has no coordinate reference system.")

    metric_crs = course.estimate_utm_crs()

    if metric_crs is None:
        raise ValueError(
            "RaceGuard could not determine a metric coordinate system "
            "for this course."
        )

    result = stations.copy().reset_index(drop=True)

    # Preserve the coordinates supplied by the user before replacing them
    # with canonical points located directly on the course.
    if {"latitude", "longitude"}.issubset(result.columns):
        result["source_latitude"] = result["latitude"]
        result["source_longitude"] = result["longitude"]
    else:
        result["source_latitude"] = float("nan")
        result["source_longitude"] = float("nan")

    course_metric = course.to_crs(metric_crs)
    course_line_metric = course_metric.geometry.iloc[0]
    course_length_m = float(course_line_metric.length)

    offsets = pd.Series(
        float("nan"),
        index=result.index,
        dtype=float,
    )

    if location_method == "course distance":
        # The supplied distance determines the canonical station position.
        baseline_distance_m = (
            pd.to_numeric(result["distance_km"], errors="raise") * 1000
        )

        outside_course = (
            (baseline_distance_m <= 0)
            | (baseline_distance_m >= course_length_m)
        )

        if outside_course.any():
            bad_station_ids = result.loc[
                outside_course,
                "station_id",
            ].tolist()

            raise ValueError(
                "These station distances are outside the usable course "
                f"interior: {bad_station_ids}"
            )

        canonical_points_metric = [
            course_line_metric.interpolate(distance)
            for distance in baseline_distance_m
        ]

        # Coordinates are optional when official course distances exist.
        coordinate_mask = (
            result["source_latitude"].notna()
            & result["source_longitude"].notna()
        )

        if coordinate_mask.any():
            source_points = gpd.GeoDataFrame(
                index=result.index[coordinate_mask],
                geometry=gpd.points_from_xy(
                    result.loc[coordinate_mask, "source_longitude"],
                    result.loc[coordinate_mask, "source_latitude"],
                ),
                crs="EPSG:4326",
            ).to_crs(metric_crs)

            canonical_subset = gpd.GeoSeries(
                [
                    canonical_points_metric[index]
                    for index in result.index[coordinate_mask]
                ],
                index=result.index[coordinate_mask],
                crs=metric_crs,
            )

            offsets.loc[coordinate_mask] = (
                source_points.geometry.distance(canonical_subset)
            )

    elif location_method == "coordinates":
        coordinate_mask = (
            result["source_latitude"].notna()
            & result["source_longitude"].notna()
        )

        if not coordinate_mask.all():
            raise ValueError(
                "Every coordinate-based station needs both latitude "
                "and longitude."
            )

        source_points = gpd.GeoDataFrame(
            result[["station_id"]].copy(),
            geometry=gpd.points_from_xy(
                result["source_longitude"],
                result["source_latitude"],
            ),
            crs="EPSG:4326",
        ).to_crs(metric_crs)

        # project() means: find how far along the LineString the closest
        # point to this station occurs.
        baseline_distance_m = source_points.geometry.apply(
            course_line_metric.project
        )

        canonical_points_metric = [
            course_line_metric.interpolate(distance)
            for distance in baseline_distance_m
        ]

        canonical_series_metric = gpd.GeoSeries(
            canonical_points_metric,
            index=result.index,
            crs=metric_crs,
        )

        offsets = source_points.geometry.distance(
            canonical_series_metric
        )

        too_far_away = offsets > max_snap_distance_m

        if too_far_away.any():
            bad_station_ids = result.loc[
                too_far_away,
                "station_id",
            ].tolist()

            raise ValueError(
                "These stations are too far from the uploaded course "
                f"to snap reliably: {bad_station_ids}"
            )

    else:
        raise ValueError(
            f"Unsupported station location method: {location_method}"
        )

    canonical_series_metric = gpd.GeoSeries(
        canonical_points_metric,
        index=result.index,
        crs=metric_crs,
    )

    canonical_series_wgs84 = canonical_series_metric.to_crs(
        "EPSG:4326"
    )

    result["baseline_distance_m"] = baseline_distance_m.astype(float)
    result["baseline_distance_km"] = (
        result["baseline_distance_m"] / 1000
    )

    # These are the canonical coordinates directly on the course.
    result["longitude"] = canonical_series_wgs84.x
    result["latitude"] = canonical_series_wgs84.y
    result["source_coordinate_offset_m"] = offsets.astype(float)

    result = result.sort_values(
        "baseline_distance_m"
    ).reset_index(drop=True)

    main_columns = [
        "station_id",
        "baseline_distance_m",
        "baseline_distance_km",
        "latitude",
        "longitude",
        "source_latitude",
        "source_longitude",
        "source_coordinate_offset_m",
    ]

    remaining_columns = [
        column
        for column in result.columns
        if column not in main_columns
    ]

    return result[main_columns + remaining_columns]


def load_station_csv(
    file_bytes: bytes,
) -> tuple[pd.DataFrame, str]:
    """
    Load relief stations and identify how they are located.
    """

    stations = pd.read_csv(
        BytesIO(file_bytes)
    )

    stations.columns = (
        stations.columns
        .str.strip()
        .str.lower()
    )

    if "baseline_distance_km" in stations.columns:
        stations = stations.rename(
            columns={
                "baseline_distance_km": "distance_km"
            }
        )

    if stations.empty:
        raise ValueError(
            "The station file contains no stations."
        )

    if "station_id" not in stations.columns:
        raise ValueError(
            "The station file must contain a station_id column."
        )

    if stations["station_id"].isna().any():
        raise ValueError(
            "Every station must have a station_id."
        )

    stations["station_id"] = (
        stations["station_id"]
        .astype(str)
        .str.strip()
    )

    if stations["station_id"].duplicated().any():
        raise ValueError(
            "Every station_id must be unique."
        )

    if "distance_km" in stations.columns:
        stations["distance_km"] = pd.to_numeric(
            stations["distance_km"],
            errors="coerce",
        )

    coordinate_columns_exist = {
        "latitude",
        "longitude",
    }.issubset(stations.columns)

    if coordinate_columns_exist:
        stations["latitude"] = pd.to_numeric(
            stations["latitude"],
            errors="coerce",
        )
        stations["longitude"] = pd.to_numeric(
            stations["longitude"],
            errors="coerce",
        )

    has_complete_distances = (
        "distance_km" in stations.columns
        and stations["distance_km"].notna().all()
    )

    has_complete_coordinates = (
        coordinate_columns_exist
        and stations[
            ["latitude", "longitude"]
        ].notna().all(axis=1).all()
    )

    if has_complete_distances:
        location_method = "course distance"

        stations = stations.sort_values(
            "distance_km"
        ).reset_index(drop=True)

    elif has_complete_coordinates:
        location_method = "coordinates"

    else:
        raise ValueError(
            "Provide distance_km for every station, or provide "
            "latitude and longitude for every station."
        )

    return stations, location_method