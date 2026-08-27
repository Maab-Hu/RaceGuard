import json
import geopandas as gpd
import hashlib
import time
from datetime import datetime
from pathlib import Path
from fortyguard import FortyGuardClient

def build_heatmap_cache_path(
    aoi_geojson: dict,
    race_datetime: datetime,
    analysis_basis: str,
    granularity: int = 100,
    cache_directory: str | Path = "data/cache/heatmaps",
) -> Path:
    """
    Create a stable cache filename from the exact request inputs.
    """
    request_signature = {
        "polygon_aoi": aoi_geojson,
        "race_datetime": race_datetime.isoformat(),
        "analysis_basis": analysis_basis,
        "granularity": granularity,
        "filter_type": 1,
    }

    canonical_signature = json.dumps(
        request_signature,
        sort_keys=True,
        separators=(",", ":"),
    )

    request_hash = hashlib.sha256(
        canonical_signature.encode("utf-8")
    ).hexdigest()[:20]

    cache_directory = Path(cache_directory)

    return cache_directory / f"heatmap_{request_hash}.json"


def validate_heatmap_response(response: dict) -> None:
    """
    Perform lightweight validation of a FortyGuard heatmap response.
    """
    if not isinstance(response, dict):
        raise ValueError(
            "The FortyGuard response is not a dictionary."
        )

    result = response.get("result")

    if not isinstance(result, dict):
        raise ValueError(
            "The FortyGuard response has no valid result."
        )

    map_data = result.get("map_data")

    if not isinstance(map_data, dict):
        raise ValueError(
            "The FortyGuard response has no heatmap data."
        )

    features = map_data.get("features")

    if not isinstance(features, list) or not features:
        raise ValueError(
            "The FortyGuard heatmap contains no tiles."
        )


def is_heatmap_cache_valid(
    cache_path: str | Path,
    analysis_basis: str,
    forecast_ttl_minutes: int = 30,
) -> bool:
    """
    Historical caches do not expire. Forecast caches expire after
    the configured freshness period.
    """
    cache_path = Path(cache_path)

    if not cache_path.exists():
        return False

    if analysis_basis == "historical":
        return True

    if analysis_basis != "forecast":
        raise ValueError(
            f"Unknown analysis basis: {analysis_basis}"
        )

    cache_age_seconds = max(
        0,
        time.time() - cache_path.stat().st_mtime,
    )

    return (
        cache_age_seconds
        <= forecast_ttl_minutes * 60
    )


def load_cached_heatmap(
    cache_path: str | Path,
) -> dict:
    cache_path = Path(cache_path)

    response = json.loads(
        cache_path.read_text(encoding="utf-8")
    )

    validate_heatmap_response(response)

    return response


def get_heatmap_response(
    aoi_geojson: dict,
    race_datetime: datetime,
    analysis_basis: str,
    api_key: str | None = None,
    granularity: int = 100,
) -> tuple[dict, Path, bool]:
    """
    Load an existing valid cache or make one paid FortyGuard call.

    Returns:
        response,
        cache path,
        whether the result came from cache.
    """
    cache_path = build_heatmap_cache_path(
        aoi_geojson=aoi_geojson,
        race_datetime=race_datetime,
        analysis_basis=analysis_basis,
        granularity=granularity,
    )

    if is_heatmap_cache_valid(
        cache_path=cache_path,
        analysis_basis=analysis_basis,
    ):
        response = load_cached_heatmap(cache_path)

        return response, cache_path, True

    if not api_key:
        raise ValueError(
            "A FortyGuard API key is required because no valid "
            "cached response exists."
        )

    client = FortyGuardClient(
        api_key=api_key.strip()
    )

    response = client.create_heatmap(
        polygon_aoi=aoi_geojson,
        start_date=race_datetime.strftime("%Y-%m-%d"),
        start_time=race_datetime.strftime("%H:%M"),
        filter_type=1,
        granularity=granularity,
    )

    validate_heatmap_response(response)

    cache_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary_path = cache_path.with_suffix(".tmp")

    temporary_path.write_text(
        json.dumps(response),
        encoding="utf-8",
    )

    temporary_path.replace(cache_path)

    return response, cache_path, False


def build_course_aoi(
    course: gpd.GeoDataFrame,
    buffer_m: float = 200,
) -> tuple[gpd.GeoDataFrame, dict, float]:
    """
    Build a buffered heatmap request area around a race course.

    Returns:
        AOI GeoDataFrame in EPSG:4326 for map display.
        GeoJSON FeatureCollection for FortyGuard.
        AOI area in square kilometres.
    """
    if course.crs is None:
        raise ValueError(
            "The course has no coordinate reference system."
        )

    if buffer_m <= 0:
        raise ValueError(
            "The heatmap buffer must be greater than zero."
        )

    metric_crs = course.estimate_utm_crs()

    if metric_crs is None:
        raise ValueError(
            "Could not determine a metric CRS for the course."
        )

    course_metric = course.to_crs(metric_crs)
    course_line_metric = course_metric.geometry.iloc[0]

    buffered_geometry = course_line_metric.buffer(
        buffer_m
    )

    # Reduce unnecessary polygon detail while preserving its shape.
    buffered_geometry = buffered_geometry.simplify(
        tolerance=10,
        preserve_topology=True,
    )

    if (
        buffered_geometry.is_empty
        or not buffered_geometry.is_valid
    ):
        raise ValueError(
            "RaceGuard could not create a valid heatmap area."
        )

    aoi_metric = gpd.GeoDataFrame(
        {
            "buffer_m": [float(buffer_m)],
        },
        geometry=[buffered_geometry],
        crs=metric_crs,
    )

    aoi_area_km2 = float(
        aoi_metric.geometry.area.iloc[0] / 1_000_000
    )

    aoi_wgs84 = aoi_metric.to_crs("EPSG:4326")

    # FortyGuard expects a normal Python GeoJSON dictionary.
    aoi_geojson = json.loads(
        aoi_wgs84.to_json()
    )

    return (
        aoi_wgs84,
        aoi_geojson,
        aoi_area_km2,
    )