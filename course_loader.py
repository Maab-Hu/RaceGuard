from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

import geopandas as gpd
from shapely.geometry import LineString, MultiLineString
from shapely.ops import linemerge
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


def _normalize_course_lines(
    uploaded_geometries: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    """
    Convert loaded line geometry into one course LineString.
    """

    if uploaded_geometries.empty:
        raise ValueError("The uploaded course contains no geometry.")

    if uploaded_geometries.crs is None:
        uploaded_geometries = uploaded_geometries.set_crs(
            "EPSG:4326"
        )
    else:
        uploaded_geometries = uploaded_geometries.to_crs(
            "EPSG:4326"
        )

    line_parts = []

    for geometry in uploaded_geometries.geometry:
        if geometry is None or geometry.is_empty:
            continue

        if isinstance(geometry, LineString):
            line_parts.append(geometry)

        elif isinstance(geometry, MultiLineString):
            line_parts.extend(geometry.geoms)

        else:
            raise ValueError(
                "The course must contain line geometry, "
                f"not {geometry.geom_type}."
            )

    if not line_parts:
        raise ValueError(
            "The uploaded file contains no usable course lines."
        )

    if len(line_parts) == 1:
        course_line = line_parts[0]
    else:
        course_line = linemerge(
            MultiLineString(line_parts)
        )

    if not isinstance(course_line, LineString):
        raise ValueError(
            "The course sections are not connected into one route."
        )

    if course_line.is_empty or not course_line.is_valid:
        raise ValueError(
            "The resulting course LineString is empty or invalid."
        )

    return gpd.GeoDataFrame(
        {"geometry": [course_line]},
        crs="EPSG:4326",
    )


def load_geojson_course(
    file_bytes: bytes,
) -> gpd.GeoDataFrame:
    """
    Read an uploaded GeoJSON course.
    """

    uploaded_geometries = gpd.read_file(
        BytesIO(file_bytes)
    )

    return _normalize_course_lines(
        uploaded_geometries
    )


def load_gpx_course(
    file_bytes: bytes,
) -> gpd.GeoDataFrame:
    """
    Read the track or route layer from an uploaded GPX course.
    """

    with TemporaryDirectory() as temporary_directory:
        gpx_path = (
            Path(temporary_directory) / "uploaded_course.gpx"
        )

        gpx_path.write_bytes(file_bytes)

        for layer_name in ("tracks", "routes"):
            try:
                uploaded_geometries = gpd.read_file(
                    gpx_path,
                    layer=layer_name,
                )
            except Exception:
                continue

            if not uploaded_geometries.empty:
                return _normalize_course_lines(
                    uploaded_geometries
                )

    raise ValueError(
        "The GPX file contains no usable track or route."
    )


def load_course_upload(
    file_name: str,
    file_bytes: bytes,
) -> gpd.GeoDataFrame:
    """
    Select the correct course loader from the filename.
    """

    file_suffix = Path(file_name).suffix.lower()

    if file_suffix in {".geojson", ".json"}:
        return load_geojson_course(file_bytes)

    if file_suffix == ".gpx":
        return load_gpx_course(file_bytes)

    raise ValueError(
        f"Unsupported course file type: {file_suffix}"
    )

def reverse_course_direction(
    course: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    """
    Return a copy of the course with its direction reversed.
    """

    reversed_course = course.copy()
    course_line = course.geometry.iloc[0]

    reversed_coordinates = list(
        course_line.coords
    )[::-1]

    reversed_course["geometry"] = [
        LineString(reversed_coordinates)
    ]

    return reversed_course