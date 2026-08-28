import race_analysis
import temperature_profile
from pathlib import Path
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo
from heatmap_request import (
    build_course_aoi,
    build_heatmap_cache_path,
    get_heatmap_response,
    is_heatmap_cache_valid,
)
import streamlit as st
from streamlit_folium import st_folium
from course_loader import (
    detect_course_timezone,
    load_course_upload,
    reverse_course_direction,
)
from map_visualization import (
    build_course_preview_map,
    build_optimization_result_map,
)

from station_loader import (
    load_station_csv,
    locate_stations_on_course,
)


st.set_page_config(
    page_title="RaceGuard",
    page_icon="🏃",
    layout="wide",
)


# Center the RaceGuard logo.
logo_left, logo_center, logo_right = st.columns(
    [2.3, 0.7, 2.3]
)

with logo_center:
    st.image(
        "assets/raceguardlogo2.png",
        use_container_width=True,
    )


st.markdown(
    (
        '<div style="max-width:850px; margin:-0.5rem auto 1.75rem auto; '
        'text-align:center;">'

        '<h1 style="font-size:2rem; font-weight:750; '
        'margin-bottom:0.65rem;">'
        'Put race relief where runners face the most heat.'
        '</h1>'

        '<p style="color:#5f6670; font-size:1.08rem; '
        'line-height:1.6; margin:0 auto 0.9rem auto;">'
        "RaceGuard combines FortyGuard's hyperlocal temperature "
        'data with constrained optimization to reposition existing '
        'relief stations and reduce the worst uninterrupted '
        'relative heat exposure along a race course.'
        '</p>'

        '<span style="display:inline-block; background:#fff3ed; '
        'color:#c44f21; border:1px solid #f3c1aa; '
        'border-radius:999px; padding:0.3rem 0.8rem; '
        'font-size:0.86rem; font-weight:650;">'
        'Powered by the FortyGuard Temperature API'
        '</span>'

        '</div>'
    ),
    unsafe_allow_html=True,
)


# Keep the mode selector centered.
mode_left, mode_center, mode_right = st.columns([1, 1.2, 1])

with mode_center:
    mode = st.radio(
        "How would you like to begin?",
        options=[
            "Explore an example",
            "Analyze your race",
        ],
        horizontal=True,
    )

analysis_result = None

if mode == "Explore an example":
    st.divider()

    example_intro, example_picker = st.columns(
        [1.4, 1],
        gap="large",
        vertical_alignment="bottom",
    )

    with example_intro:
        st.header("See RaceGuard in action")

        st.write(
            "Explore a prepared race using validated FortyGuard "
            "temperature data—no API key or credits required."
        )

    with example_picker:
        selected_example = st.selectbox(
            "Choose a race",
            options=[
                "AJC Peachtree Road Race",
                "BOLDERBoulder",
            ],
        )

    if selected_example == "AJC Peachtree Road Race":
        example_course_path = Path(
            "data/processed/peachtree_course.geojson"
        )

        example_station_path = Path(
            "data/processed/peachtree_stations.csv"
        )

        example_heatmap_path = Path(
            "data/raw/fortyguard/"
            "peachtree_heatmap_2026_07_04_0900_g100.json"
        )

        example_min_gap_m = 1000
        example_max_gap_m = 2000
        example_max_movement_m = 500

        example_description = (
            "Atlanta, Georgia · 10 km · "
            "4 July 2026 at 09:00"
        )

    else:
        example_course_path = Path(
            "data/processed/bolder_boulder_course.geojson"
        )

        example_station_path = None

        example_heatmap_path = Path(
            "data/raw/fortyguard/"
            "bolder_boulder_heatmap_2026-05-25_0800_g100.json"
        )

        example_min_gap_m = 1000
        example_max_gap_m = None
        example_max_movement_m = 500

        example_description = (
            "Boulder, Colorado · 10 km · "
            "25 May 2026 at 08:00"
        )

    example_files = [
        example_course_path,
        example_heatmap_path,
    ]

    if example_station_path is not None:
        example_files.append(
            example_station_path
        )

    missing_files = [
        path
        for path in example_files
        if not path.is_file()
    ]

    if missing_files:
        st.error(
            "Example files are missing: "
            + ", ".join(
                str(path)
                for path in missing_files
            )
        )

    else:
        try:
            with st.spinner(
                f"Loading {selected_example}..."
            ):
                example_course = load_course_upload(
                    file_name=example_course_path.name,
                    file_bytes=example_course_path.read_bytes(),
                )

                example_route_profile = (
                    temperature_profile
                    .build_route_temperature_profile(
                        example_course,
                        example_heatmap_path,
                        spacing_m=100,
                        max_nearest_distance_m=150,
                    )
                )

                if (
                    selected_example
                    == "AJC Peachtree Road Race"
                ):
                    (
                        example_stations,
                        example_location_method,
                    ) = load_station_csv(
                        example_station_path.read_bytes()
                    )

                    example_positioned_stations = (
                        locate_stations_on_course(
                            course=example_course,
                            stations=example_stations,
                            location_method=(
                                example_location_method
                            ),
                        )
                    )

                    baseline_station_positions = (
                        example_positioned_stations[
                            "baseline_distance_m"
                        ].to_numpy()
                    )

                    baseline_station_data = (
                        example_positioned_stations
                    )

                else:
                    metres_per_mile = 1609.344

                    baseline_station_positions = [
                        2 * metres_per_mile,
                        3 * metres_per_mile,
                        4 * metres_per_mile,
                        5 * metres_per_mile,
                    ]

                    baseline_station_data = None

                    source_length_m = float(
                        example_route_profile[
                            "distance_m"
                        ].iloc[-1]
                    )

                    if source_length_m <= 0:
                        raise ValueError(
                            "The BOLDERBoulder course "
                            "length is invalid."
                        )

                    distance_scale = (
                        10_000.0 / source_length_m
                    )

                    example_route_profile[
                        "source_distance_m"
                    ] = example_route_profile[
                        "distance_m"
                    ]

                    example_route_profile[
                        "distance_m"
                    ] = (
                        example_route_profile[
                            "source_distance_m"
                        ]
                        * distance_scale
                    )

                    example_route_profile[
                        "distance_km"
                    ] = (
                        example_route_profile[
                            "distance_m"
                        ]
                        / 1000
                    )

                example_burden_profile = (
                    temperature_profile
                    .add_relative_heat_burden(
                        example_route_profile
                    )
                )

                analysis_result = (
                    race_analysis.analyze_station_plan(
                        race_name=selected_example,
                        profile=example_burden_profile,
                        baseline_station_positions=(
                            baseline_station_positions
                        ),
                        baseline_station_data=(
                            baseline_station_data
                        ),
                        min_gap_m=example_min_gap_m,
                        max_gap_m=example_max_gap_m,
                        max_movement_m=(
                            example_max_movement_m
                        ),
                    )
                )

            st.markdown(
                f"**{selected_example}** · "
                f"{example_description}"
            )

            if selected_example == "BOLDERBoulder":
                st.caption(
                    "Prepared validation setup with baseline "
                    "stations at miles 2, 3, 4, and 5."
                )

            st.caption(
                "Prepared FortyGuard case study · "
                "100 m temperature resolution · "
                "No API credits required."
            )

        except Exception as error:
            analysis_result = None

            st.error(
                "RaceGuard could not load the example: "
                f"{error}"
            )

else:
    st.divider()

    st.header("Optimize your race plan")

    st.write(
        "Upload an existing course and relief-station plan. "
        "RaceGuard will map the route's temperature variation "
        "and recommend feasible station relocations."
    )

    st.info(
        "RaceGuard validates every input and shows the exact "
        "request area before any FortyGuard API credits are used.",
        icon="🛡️",
    )

    course = None
    course_length_m = None

    stations = None
    positioned_stations = None
    location_method = None

    race_name = ""
    race_date = None
    race_start_time = None
    race_datetime = None

    temperature_mode = None
    analysis_basis = None
    course_timezone_name = None

    min_gap_m = None
    max_gap_m = None
    max_movement_m = None

    settings_valid = False

    course_aoi = None
    heatmap_aoi = None
    aoi_area_km2 = None
    heatmap_response = None
    heatmap_cache_path = None   
    input_column, preview_column = st.columns(
        [0.42, 0.58],
        gap="large",
    )

    with input_column:
        st.subheader("1. Race course")

        course_file = st.file_uploader(
            "Upload the race course",
            type=["gpx", "geojson", "json"],
            help=(
                "Upload an ordered GPX track or a GeoJSON "
                "LineString representing the course."
            ),
        )

        if course_file is not None:
            file_size_kb = course_file.size / 1024

            st.caption(
                f"✓ Course loaded · {course_file.name} · "
                f"{file_size_kb:.1f} KB"
            )

            try:
                course = load_course_upload(
                    file_name=course_file.name,
                    file_bytes=course_file.getvalue(),
                )

                reverse_direction = st.checkbox(
                    "Reverse course direction",
                    help=(
                        "Select this if the start and finish "
                        "markers appear in the wrong locations."
                    ),
                )

                if reverse_direction:
                    course = reverse_course_direction(course)

                metric_crs = course.estimate_utm_crs()

                if metric_crs is None:
                    raise ValueError(
                        "Could not determine a metric coordinate "
                        "system for this course."
                    )

                course_length_m = float(
                    course
                    .to_crs(metric_crs)
                    .length
                    .iloc[0]
                )

                st.metric(
                    "Course length",
                    f"{course_length_m / 1000:.2f} km",
                )

                st.caption(
                    "Geometry type: "
                    f"{course.geometry.iloc[0].geom_type}"
                )

            except Exception as error:
                course = None
                course_length_m = None

                st.error(
                    "RaceGuard could not read this course: "
                    f"{error}"
                )

        if course is not None:
            st.subheader("2. Existing relief stations")

            station_template = (
                "station_id,distance_km,latitude,longitude,"
                "has_water,has_restrooms,has_first_aid\n"
            )

            st.download_button(
                label="Download station CSV template",
                data=station_template,
                file_name="raceguard_station_template.csv",
                mime="text/csv",
            )

            station_file = st.file_uploader(
                "Upload the existing relief stations",
                type=["csv"],
                help=(
                    "Provide station_id and either distance_km, "
                    "or latitude and longitude."
                ),
            )

            if station_file is not None:
                try:
                    stations, location_method = load_station_csv(
                        station_file.getvalue()
                    )

                    positioned_stations = (
                        locate_stations_on_course(
                            course=course,
                            stations=stations,
                            location_method=location_method,
                        )
                    )

                    st.caption(
                        f"✓ {len(positioned_stations)} stations loaded · "
                        f"Positioned using {location_method}"
                    )

                    offsets = positioned_stations[
                        "source_coordinate_offset_m"
                    ].dropna()

                    if (
                        not offsets.empty
                        and offsets.max() > 100
                    ):
                        st.warning(
                            "One or more supplied station coordinates "
                            "differ from their course positions by "
                            "more than 100 metres. Review the Station "
                            "data tab before continuing."
                        )

                except Exception as error:
                    stations = None
                    positioned_stations = None

                    st.error(
                        "RaceGuard could not read these stations: "
                        f"{error}"
                    )

        if positioned_stations is not None:
            st.subheader("3. Race settings")

            race_name = st.text_input(
                "Race name",
                placeholder="e.g. Peachtree Road Race",
            )

            temperature_mode = st.radio(
                "Temperature analysis",
                options=[
                    "Historical conditions",
                    "12-hour forecast",
                ],
                horizontal=True,
                help=(
                    "Historical conditions use one selected past "
                    "hour. Forecast analysis is limited to the "
                    "next 12 hours."
                ),
            )

            try:
                course_timezone_name = detect_course_timezone(
                    course
                )

                course_timezone = ZoneInfo(
                    course_timezone_name
                )

                now_local = datetime.now(course_timezone)
                forecast_limit = (
                    now_local + timedelta(hours=12)
                )

                st.caption(
                    f"Course timezone: {course_timezone_name} · "
                    f"Current local time: "
                    f"{now_local:%d %b %Y, %H:%M}"
                )

                datetime_valid = True

                if (
                    temperature_mode
                    == "Historical conditions"
                ):
                    analysis_basis = "historical"

                    historical_default_date = max(
                        date(2021, 1, 1),
                        now_local.date()
                        - timedelta(days=1),
                    )

                    date_column, time_column = st.columns(2)

                    with date_column:
                        race_date = st.date_input(
                            "Historical race date",
                            value=historical_default_date,
                            min_value=date(2021, 1, 1),
                            max_value=now_local.date(),
                            key="historical_race_date",
                        )

                    with time_column:
                        race_start_time = st.time_input(
                            "Historical start time",
                            value=time(9, 0),
                            step=3600,
                            key="historical_race_time",
                            help=(
                                "RaceGuard will analyze this "
                                "hourly temperature snapshot."
                            ),
                        )

                    race_datetime = datetime.combine(
                        race_date,
                        race_start_time,
                        tzinfo=course_timezone,
                    )

                    if race_datetime >= now_local:
                        st.error(
                            "Historical analysis requires a time "
                            "earlier than the current local time "
                            "at the course."
                        )
                        datetime_valid = False

                else:
                    analysis_basis = "forecast"

                    default_forecast_datetime = (
                        now_local + timedelta(hours=1)
                    ).replace(
                        minute=0,
                        second=0,
                        microsecond=0,
                    )

                    date_column, time_column = st.columns(2)

                    with date_column:
                        race_date = st.date_input(
                            "Forecast race date",
                            value=(
                                default_forecast_datetime.date()
                            ),
                            min_value=now_local.date(),
                            max_value=forecast_limit.date(),
                            key="forecast_race_date",
                        )

                    with time_column:
                        race_start_time = st.time_input(
                            "Forecast start time",
                            value=(
                                default_forecast_datetime.time()
                            ),
                            step=3600,
                            key="forecast_race_time",
                        )

                    race_datetime = datetime.combine(
                        race_date,
                        race_start_time,
                        tzinfo=course_timezone,
                    )

                    if not (
                        now_local
                        <= race_datetime
                        <= forecast_limit
                    ):
                        st.error(
                            "Forecast time must fall between "
                            f"{now_local:%d %b, %H:%M} and "
                            f"{forecast_limit:%d %b, %H:%M} "
                            f"({course_timezone_name})."
                        )
                        datetime_valid = False

            except Exception as error:
                datetime_valid = False

                st.error(
                    "RaceGuard could not determine the valid "
                    f"analysis time: {error}"
                )

            st.markdown("**Operational constraints**")

            min_gap_m = st.number_input(
                "Minimum gap between stations (m)",
                min_value=100.0,
                max_value=float(course_length_m),
                value=min(
                    1000.0,
                    float(course_length_m),
                ),
                step=100.0,
                help=(
                    "RaceGuard will not place two relief "
                    "stations closer than this distance."
                ),
            )

            max_gap_m = st.number_input(
                "Maximum gap between stations (m)",
                min_value=100.0,
                max_value=float(course_length_m),
                value=min(
                    2000.0,
                    float(course_length_m),
                ),
                step=100.0,
                help=(
                    "RaceGuard will not leave runners without "
                    "a relief station for more than this distance."
                ),
            )

            max_movement_m = st.number_input(
                "Maximum movement per station (m)",
                min_value=0.0,
                max_value=float(course_length_m),
                value=min(
                    500.0,
                    float(course_length_m),
                ),
                step=100.0,
                help=(
                    "The maximum distance each existing station "
                    "may move from its baseline position."
                ),
            )

            station_count = len(positioned_stations)

            st.caption(
                f"RaceGuard will keep all {station_count} "
                "existing stations and search for better "
                "positions within these constraints."
            )

            constraints_valid = (
                max_gap_m >= min_gap_m
            )

            if not race_name.strip():
                st.info(
                    "Enter a race name to complete the setup."
                )

            if not constraints_valid:
                st.error(
                    "The maximum station gap cannot be smaller "
                    "than the minimum station gap."
                )

            settings_valid = (
                bool(race_name.strip())
                and datetime_valid
                and constraints_valid
            )

            if settings_valid:
                if analysis_basis == "historical":
                    analysis_description = (
                        "historical temperature conditions"
                    )
                else:
                    analysis_description = (
                        "the 12-hour temperature forecast"
                    )

                st.success(
                    "Course, stations, and race settings are "
                    f"ready for {analysis_description}."
                )

                try:
                    (
                        course_aoi,
                        heatmap_aoi,
                        aoi_area_km2,
                    ) = build_course_aoi(
                        course=course,
                        buffer_m=200,
                    )

                    st.subheader(
                        "4. Review Temperature Request"
                    )

                    st.metric(
                        "Heatmap coverage area",
                        f"{aoi_area_km2:.2f} km²",
                    )

                    if analysis_basis == "historical":
                        request_type_label = (
                            "Historical hourly snapshot"
                        )
                    else:
                        request_type_label = (
                            "12-hour forecast snapshot"
                        )

                    st.write(
                        f"**Analysis:** {request_type_label}"
                    )

                    st.write(
                        "**Race-local time:** "
                        f"{race_datetime:%d %b %Y, %H:%M}"
                    )

                    st.write(
                        f"**Timezone:** {course_timezone_name}"
                    )

                    st.write(
                        "**Heatmap resolution:** 100 metres"
                    )

                    st.write(
                        "**Course buffer:** 200 metres "
                        "on each side"
                    )

                    st.info(
                        "The orange area on the map is the "
                        "only region RaceGuard will send to "
                        "FortyGuard."
                    )

                    heatmap_cache_path = (
                        build_heatmap_cache_path(
                            aoi_geojson=heatmap_aoi,
                            race_datetime=race_datetime,
                            analysis_basis=analysis_basis,
                            granularity=100,
                        )
                    )

                    cache_available = (
                        is_heatmap_cache_valid(
                            cache_path=heatmap_cache_path,
                            analysis_basis=analysis_basis,
                        )
                    )

                    request_identifier = (
                        heatmap_cache_path.stem
                    )

                    if (
                        st.session_state.get(
                            "heatmap_request_identifier"
                        )
                        == request_identifier
                    ):
                        heatmap_response = (
                            st.session_state.get(
                                "heatmap_response"
                            )
                        )

                    if cache_available:
                        st.success(
                            "A valid cached heatmap is available. "
                            "Loading it will not spend credits."
                        )

                        if st.button(
                            "Load cached temperature data",
                            type="primary",
                        ):
                            try:
                                (
                                    heatmap_response,
                                    _,
                                    _,
                                ) = get_heatmap_response(
                                    aoi_geojson=heatmap_aoi,
                                    race_datetime=race_datetime,
                                    analysis_basis=analysis_basis,
                                    granularity=100,
                                )

                                st.session_state[
                                    "heatmap_response"
                                ] = heatmap_response

                                st.session_state[
                                    "heatmap_request_identifier"
                                ] = request_identifier

                            except Exception as error:
                                st.error(
                                    "RaceGuard could not load the "
                                    f"cached heatmap: {error}"
                                )

                    else:
                        fortyguard_api_key = st.text_input(
                            "FortyGuard API key",
                            type="password",
                            help=(
                                "The key is kept only in this "
                                "Streamlit session and is never "
                                "written to the cache."
                            ),
                        )

                        confirm_paid_request = st.checkbox(
                            "I understand that this request will "
                            "consume FortyGuard API credits."
                        )

                        request_enabled = bool(
                            fortyguard_api_key.strip()
                            and confirm_paid_request
                        )

                        if st.button(
                            "Request temperature heatmap",
                            type="primary",
                            disabled=not request_enabled,
                        ):
                            try:
                                with st.spinner(
                                    "FortyGuard is generating the "
                                    "course heatmap..."
                                ):
                                    (
                                        heatmap_response,
                                        _,
                                        loaded_from_cache,
                                    ) = get_heatmap_response(
                                        aoi_geojson=heatmap_aoi,
                                        race_datetime=race_datetime,
                                        analysis_basis=analysis_basis,
                                        api_key=fortyguard_api_key,
                                        granularity=100,
                                    )

                                st.session_state[
                                    "heatmap_response"
                                ] = heatmap_response

                                st.session_state[
                                    "heatmap_request_identifier"
                                ] = request_identifier

                                st.success(
                                    "Temperature heatmap received "
                                    "and cached successfully."
                                )

                            except Exception as error:
                                st.error(
                                    "FortyGuard could not complete "
                                    f"the request: {error}"
                                )

                    if heatmap_response is not None:
                        analysis_identifier = (
                            request_identifier,
                            tuple(
                                round(float(value), 3)
                                for value in positioned_stations[
                                    "baseline_distance_m"
                                ]
                            ),
                            float(min_gap_m),
                            float(max_gap_m),
                            float(max_movement_m),
                        )

                        if (
                            st.session_state.get(
                                "analysis_identifier"
                            )
                            == analysis_identifier
                        ):
                            analysis_result = (
                                st.session_state.get(
                                    "analysis_result"
                                )
                            )

                        if st.button(
                            "Optimize relief stations",
                            type="primary",
                        ):
                            try:
                                with st.spinner(
                                    "Calculating route exposure "
                                    "and optimizing stations..."
                                ):
                                    route_profile = (
                                        temperature_profile
                                        .build_route_temperature_profile(
                                            course,
                                            heatmap_response,
                                            spacing_m=100,
                                            max_nearest_distance_m=150,
                                        )
                                    )

                                    burden_profile = (
                                        temperature_profile
                                        .add_relative_heat_burden(
                                            route_profile
                                        )
                                    )

                                    analysis_result = (
                                        race_analysis
                                        .analyze_station_plan(
                                            race_name=race_name.strip(),
                                            profile=burden_profile,
                                            baseline_station_positions=(
                                                positioned_stations[
                                                    "baseline_distance_m"
                                                ].to_numpy()
                                            ),
                                            baseline_station_data=(
                                                positioned_stations
                                            ),
                                            min_gap_m=min_gap_m,
                                            max_gap_m=max_gap_m,
                                            max_movement_m=max_movement_m,
                                        )
                                    )

                                st.session_state[
                                    "analysis_result"
                                ] = analysis_result

                                st.session_state[
                                    "analysis_identifier"
                                ] = analysis_identifier

                            except Exception as error:
                                analysis_result = None

                                st.error(
                                    "RaceGuard could not optimize "
                                    f"the station layout: {error}"
                                )

                except Exception as error:
                    course_aoi = None
                    heatmap_aoi = None
                    aoi_area_km2 = None
                    settings_valid = False

                    st.error(
                        "RaceGuard could not prepare the "
                        f"temperature request area: {error}"
                    )

                st.caption(
                    "No paid FortyGuard request has been made."
                )

    with preview_column:
        st.subheader("Input preview")

        if course is None:
            st.caption(
                "Your course map and station positions will appear "
                "here after a valid route is uploaded."
            )

        else:
            course_tab, station_tab = st.tabs(
                [
                    "Course map",
                    "Station data",
                ]
            )

            with course_tab:
                course_map = build_course_preview_map(
                    course,
                    positioned_stations,
                    aoi = course_aoi
                )

                st_folium(
                    course_map,
                    use_container_width=True,
                    height=520,
                )

            with station_tab:
                if positioned_stations is not None:
                    display_stations = (
                        positioned_stations.copy()
                    )

                    display_stations[
                        "baseline_distance_km"
                    ] = display_stations[
                        "baseline_distance_km"
                    ].round(2)

                    display_stations[
                        "latitude"
                    ] = display_stations[
                        "latitude"
                    ].round(6)

                    display_stations[
                        "longitude"
                    ] = display_stations[
                        "longitude"
                    ].round(6)

                    display_stations[
                        "source_coordinate_offset_m"
                    ] = display_stations[
                        "source_coordinate_offset_m"
                    ].round(1)

                    summary_columns = [
                        "station_id",
                        "baseline_distance_km",
                        "latitude",
                        "longitude",
                        "source_coordinate_offset_m",
                    ]

                    optional_columns = [
                        column
                        for column in [
                            "has_water",
                            "has_restrooms",
                            "has_first_aid",
                        ]
                        if column
                        in display_stations.columns
                    ]

                    st.dataframe(
                        display_stations[
                            summary_columns
                            + optional_columns
                        ],
                        use_container_width=True,
                        hide_index=True,
                    )

                    with st.expander(
                        "View technical station data"
                    ):
                        st.dataframe(
                            positioned_stations,
                            use_container_width=True,
                            hide_index=True,
                        )

                else:
                    st.info(
                        "Upload a station CSV to inspect "
                        "the station locations."
                    )
if analysis_result is not None:
                            st.divider()

                            st.header(
                                f"{analysis_result['race_name']} recommendation"
                            )

                            st.success(
                                analysis_result["headline"],
                                icon="✅",
                            )

                            st.caption(
                                analysis_result["metric_description"]
                            )

                            summary = analysis_result["summary"]

                            baseline_segment_distance_km = float(
                                summary[
                                    "baseline_worst_segment_distance_km"
                                ]
                            )

                            optimized_segment_distance_km = float(
                                summary[
                                    "optimized_worst_segment_distance_km"
                                ]
                            )

                            segment_distance_change_km = (
                                optimized_segment_distance_km
                                - baseline_segment_distance_km
                            )

                            (
                                exposure_metric,
                                segment_metric,
                                movement_metric,
                                total_movement_metric,
                            ) = st.columns(4)

                            with exposure_metric:
                                st.metric(
                                    "Worst heat-burden reduction",
                                    (
                                        f"{summary['worst_exposure_reduction_percent']:.1f}%"
                                    ),
                                )

                            with segment_metric:
                                st.metric(
                                    "Worst segment length",
                                    f"{optimized_segment_distance_km:.2f} km",
                                    delta=(
                                        f"{segment_distance_change_km:+.2f} km"
                                    ),
                                    delta_color="inverse",
                                )

                            with movement_metric:
                                st.metric(
                                    "Largest station relocation",
                                    (
                                        f"{summary['maximum_station_movement_m']:.0f} m"
                                    ),
                                )

                            with total_movement_metric:
                                st.metric(
                                    "Total station relocation",
                                    (
                                        f"{summary['total_station_movement_m'] / 1000:.2f} km"
                                    ),
                                )

                            st.subheader(
                                "Recommended station movements"
                            )

                            optimization_map = (
                                build_optimization_result_map(
                                    analysis_result
                                )
                            )

                            st_folium(
                                optimization_map,
                                use_container_width=True,
                                height=650,
                                key="optimization_result_map",
                            )

                            st.caption(
                                "Route colours are scaled to the coolest and hottest points "
                                "on this course. They show relative spatial variation, not "
                                "medical heat-risk categories."
                            )

                            station_movements = (
                                analysis_result["station_movements"]
                                .copy()
                            )

                            movement_table = station_movements[
                                [
                                    "station_id",
                                    "current_distance_km",
                                    "proposed_distance_km",
                                    "movement_m",
                                    "movement_direction",
                                ]
                            ].copy()

                            movement_table = movement_table.rename(
                                columns={
                                    "station_id": "Station",
                                    "current_distance_km": "Current km",
                                    "proposed_distance_km": "Proposed km",
                                    "movement_m": "Movement (m)",
                                    "movement_direction": "Direction",
                                }
                            )

                            movement_table["Current km"] = (
                                movement_table["Current km"].round(2)
                            )

                            movement_table["Proposed km"] = (
                                movement_table["Proposed km"].round(2)
                            )

                            movement_table["Movement (m)"] = (
                                movement_table["Movement (m)"].round(0)
                            )

                            st.dataframe(
                                movement_table,
                                use_container_width=True,
                                hide_index=True,
                            )

                            recommendation_columns = [
                                "station_id",
                                "proposed_distance_km",
                                "proposed_latitude",
                                "proposed_longitude",
                                "movement_m",
                                "movement_direction",
                            ]

                            facility_columns = [
                                column
                                for column in [
                                    "side_count",
                                    "has_water",
                                    "has_restrooms",
                                    "has_first_aid",
                                ]
                                if column in station_movements.columns
                            ]

                            recommendation_export = station_movements[
                                recommendation_columns
                                + facility_columns
                            ].copy()

                            recommendation_export = (
                                recommendation_export.rename(
                                    columns={
                                        "proposed_distance_km": "distance_km",
                                        "proposed_latitude": "latitude",
                                        "proposed_longitude": "longitude",
                                    }
                                )
                            )

                            st.download_button(
                                label="Download recommended station CSV",
                                data=recommendation_export.to_csv(
                                    index=False
                                ),
                                file_name="raceguard_recommended_stations.csv",
                                mime="text/csv",
                            )

                            with st.expander(
                                "Technical exposure details"
                            ):
                                st.write(
                                    "**Baseline worst relative burden:** "
                                    f"{summary['baseline_worst_burden_c_m']:.2f} °C·m"
                                )

                                st.write(
                                    "**Optimized worst relative burden:** "
                                    f"{summary['optimized_worst_burden_c_m']:.2f} °C·m"
                                )

                                st.write(
                                    "**These values are route-relative planning "
                                    "metrics, not medical-risk measurements.**"
                                )

                                baseline_tab, optimized_tab = st.tabs(
                                    [
                                        "Current segments",
                                        "Optimized segments",
                                    ]
                                )

                                with baseline_tab:
                                    st.dataframe(
                                        analysis_result[
                                            "baseline_segments"
                                        ],
                                        use_container_width=True,
                                        hide_index=True,
                                    )

                                with optimized_tab:
                                    st.dataframe(
                                        analysis_result[
                                            "optimized_segments"
                                        ],
                                        use_container_width=True,
                                        hide_index=True,
                                    )