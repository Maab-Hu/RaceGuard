import folium
import geopandas as gpd
from branca.colormap import LinearColormap
from html import escape

def build_optimization_result_map(
    analysis_result,
):
    """
    Build a temperature-coloured map comparing current and
    proposed relief-station positions.
    """
    route_profile = (
        analysis_result["route_profile"]
        .sort_values("distance_m")
        .reset_index(drop=True)
    )

    station_movements = (
        analysis_result["station_movements"]
        .reset_index(drop=True)
    )

    if route_profile.empty:
        raise ValueError(
            "The route profile is empty."
        )

    minimum_temperature = float(
        route_profile["average_temperature"].min()
    )

    maximum_temperature = float(
        route_profile["average_temperature"].max()
    )

    # Prevent a zero-width colour scale when a route has
    # effectively uniform temperature.
    colour_scale_maximum = maximum_temperature

    if colour_scale_maximum <= minimum_temperature:
        colour_scale_maximum = (
            minimum_temperature + 0.01
        )

    temperature_colormap = LinearColormap(
        colors=[
            "#2563EB",
            "#22C55E",
            "#FACC15",
            "#F97316",
            "#DC2626",
        ],
        vmin=minimum_temperature,
        vmax=colour_scale_maximum,
        caption="Average temperature (°C)",
    )

    route_coordinates = list(
        zip(
            route_profile["latitude"],
            route_profile["longitude"],
        )
    )

    result_map = folium.Map(
        location=route_coordinates[0],
        tiles="CartoDB positron",
        zoom_start=13,
        control_scale=True,
    )

    # Draw each sampled route interval using its local temperature.
    for index in range(len(route_profile) - 1):
        current_row = route_profile.iloc[index]
        next_row = route_profile.iloc[index + 1]

        interval_temperature = (
            float(current_row["average_temperature"])
            + float(next_row["average_temperature"])
        ) / 2

        folium.PolyLine(
            locations=[
                [
                    current_row["latitude"],
                    current_row["longitude"],
                ],
                [
                    next_row["latitude"],
                    next_row["longitude"],
                ],
            ],
            color=temperature_colormap(
                interval_temperature
            ),
            weight=7,
            opacity=0.9,
            tooltip=(
                f"{interval_temperature:.2f}°C · "
                f"{current_row['distance_km']:.2f}–"
                f"{next_row['distance_km']:.2f} km"
            ),
        ).add_to(result_map)

    # Draw station movements first so the station markers sit above them.
    for station in station_movements.itertuples():
        station_id = escape(
            str(station.station_id)
        )

        movement_direction = escape(
            str(station.movement_direction)
        )

        folium.PolyLine(
            locations=[
                [
                    station.current_latitude,
                    station.current_longitude,
                ],
                [
                    station.proposed_latitude,
                    station.proposed_longitude,
                ],
            ],
            color="#7C3AED",
            weight=3,
            opacity=0.85,
            dash_array="7, 7",
            tooltip=(
                f"{station_id}: move "
                f"{station.movement_m:.0f} m "
                f"{movement_direction}"
            ),
        ).add_to(result_map)

        folium.CircleMarker(
            location=[
                station.current_latitude,
                station.current_longitude,
            ],
            radius=7,
            color="#F97316",
            weight=4,
            fill=True,
            fill_color="#FFFFFF",
            fill_opacity=1,
            tooltip=(
                f"{station_id} current position · "
                f"{station.current_distance_km:.2f} km"
            ),
        ).add_to(result_map)

        folium.CircleMarker(
            location=[
                station.proposed_latitude,
                station.proposed_longitude,
            ],
            radius=8,
            color="#166534",
            weight=2,
            fill=True,
            fill_color="#22C55E",
            fill_opacity=1,
            tooltip=(
                f"{station_id} proposed position · "
                f"{station.proposed_distance_km:.2f} km"
            ),
        ).add_to(result_map)

    folium.Marker(
        route_coordinates[0],
        tooltip="Course start",
        icon=folium.Icon(
            color="green",
            icon="play",
            prefix="fa",
        ),
    ).add_to(result_map)

    folium.Marker(
        route_coordinates[-1],
        tooltip="Course finish",
        icon=folium.Icon(
            color="red",
            icon="flag-checkered",
            prefix="fa",
        ),
    ).add_to(result_map)

    temperature_colormap.add_to(result_map)

    legend_html = """
    <div style="
        position: fixed;
        bottom: 45px;
        left: 45px;
        z-index: 9999;
        background: white;
        padding: 12px 14px;
        border: 1px solid #D1D5DB;
        border-radius: 8px;
        font-size: 13px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.15);
    ">
        <div style="font-weight: 700; margin-bottom: 8px;">
            Relief stations
        </div>

        <div style="margin-bottom: 6px;">
            <span style="
                display: inline-block;
                width: 12px;
                height: 12px;
                margin-right: 7px;
                border: 3px solid #F97316;
                border-radius: 50%;
                background: white;
            "></span>
            Current position
        </div>

        <div style="margin-bottom: 6px;">
            <span style="
                display: inline-block;
                width: 14px;
                height: 14px;
                margin-right: 7px;
                border: 2px solid #166534;
                border-radius: 50%;
                background: #22C55E;
            "></span>
            Proposed position
        </div>

        <div>
            <span style="
                display: inline-block;
                width: 22px;
                margin-right: 7px;
                border-top: 3px dashed #7C3AED;
                vertical-align: middle;
            "></span>
            Recommended movement
        </div>
    </div>
    """

    result_map.get_root().html.add_child(
        folium.Element(legend_html)
    )

    result_map.fit_bounds(route_coordinates)

    return result_map

def build_course_preview_map(course, stations=None, aoi=None):
    """
    Build a map showing the race course, start, finish,
    and optionally the existing relief stations.
    """
    course_wgs84 = course.to_crs("EPSG:4326")
    course_line = course_wgs84.geometry.iloc[0]

    # Shapely coordinates are (longitude, latitude), while Folium
    # expects (latitude, longitude).
    route_coordinates = [
        (latitude, longitude)
        for longitude, latitude in course_line.coords
    ]

    course_map = folium.Map(
        location=route_coordinates[0],
        tiles="CartoDB positron",
        zoom_start=13,
    )

    if aoi is not None and not aoi.empty:
        folium.GeoJson(
            data=aoi.__geo_interface__,
            name="Heatmap request area",
            style_function=lambda feature: {
                "color": "#F97316",
                "weight": 2,
                "fillColor": "#FDBA74",
                "fillOpacity": 0.22,
            },
        ).add_to(course_map)

    folium.PolyLine(
        route_coordinates,
        color="#2563EB",
        weight=5,
        opacity=0.9,
        tooltip="Race course",
    ).add_to(course_map)

    folium.Marker(
        route_coordinates[0],
        tooltip="Start",
        popup="Course start",
        icon=folium.Icon(
            color="green",
            icon="play",
            prefix="fa",
        ),
    ).add_to(course_map)

    folium.Marker(
        route_coordinates[-1],
        tooltip="Finish",
        popup="Course finish",
        icon=folium.Icon(
            color="red",
            icon="flag-checkered",
            prefix="fa",
        ),
    ).add_to(course_map)

    if stations is not None and not stations.empty:
        for station in stations.itertuples():
            station_id = escape(str(station.station_id))
            distance_km = float(station.baseline_distance_km)

            popup_text = (
                f"<strong>{station_id}</strong><br>"
                f"Course distance: {distance_km:.2f} km"
            )

            folium.CircleMarker(
                location=[
                    station.latitude,
                    station.longitude,
                ],
                radius=8,
                color="#0F172A",
                weight=2,
                fill=True,
                fill_color="#475569",
                fill_opacity=1,
                tooltip=f"{station_id} — {distance_km:.2f} km",
                popup=folium.Popup(
                    popup_text,
                    max_width=220,
                ),
            ).add_to(course_map)

    course_map.fit_bounds(route_coordinates)

    return course_map