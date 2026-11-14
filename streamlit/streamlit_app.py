"""Arcade Scores — real-time dashboard on an Interactive Table.

Runs as Streamlit in Snowflake. The query warehouse (SUMMIT_INT_WH) is set on the
STREAMLIT object, so this app never issues USE WAREHOUSE.
"""

from datetime import datetime, timezone

import altair as alt
import pandas as pd
import pydeck as pdk
import streamlit as st

import queries as Q

st.set_page_config(
    page_title="Arcade Scores Live",
    page_icon=":material/sports_esports:",
    layout="wide",
)

ACCENT = "#29B5E8"
ACCENT_2 = "#FF6F61"
LIVE_TTL = 5  # seconds; matches the auto-refresh cadence

st.markdown(
    """
    <style>
      .block-container {padding-top: 2rem; padding-bottom: 2rem;}
      [data-testid="stMetricValue"] {font-size: 1.9rem; font-weight: 700;}
      [data-testid="stMetricLabel"] p {text-transform: uppercase; letter-spacing: .06em; font-size: .75rem; opacity: .75;}
      h3 {margin-bottom: .25rem;}
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------- data layer

conn = st.connection("snowflake")


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    """Uppercase column names and coerce Snowflake NUMBER/Decimal to numeric dtypes."""
    df = df.copy()
    df.columns = [c.upper() for c in df.columns]
    for col in df.columns:
        if df[col].dtype == object and len(df) and df[col].map(type).astype(str).str.contains("Decimal").any():
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def run(name: str, ttl: int = LIVE_TTL) -> pd.DataFrame:
    try:
        return _normalize(conn.query(Q.ALL[name], ttl=ttl))
    except Exception as exc:  # surface per-panel instead of crashing the page
        st.error(f"Query `{name}` failed: {exc}", icon=":material/error:")
        return pd.DataFrame()


def _int(df: pd.DataFrame, *cols: str) -> pd.DataFrame:
    for c in cols:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0).astype("int64")
    return df


def _float(df: pd.DataFrame, *cols: str) -> pd.DataFrame:
    for c in cols:
        df[c] = pd.to_numeric(df[c], errors="coerce").astype("float64")
    return df


def _ts(df: pd.DataFrame, *cols: str) -> pd.DataFrame:
    for c in cols:
        df[c] = pd.to_datetime(df[c])
    return df


def empty_note(df: pd.DataFrame, msg: str = "No data in this window yet.") -> bool:
    if df.empty:
        st.info(msg, icon=":material/hourglass_empty:")
        return True
    return False


def hbar(df: pd.DataFrame, cat: str, metrics: list[str], labels: dict[str, str]) -> alt.Chart:
    """Grouped horizontal bar chart for sessions vs players."""
    long = df.melt(id_vars=cat, value_vars=metrics, var_name="Metric", value_name="Count")
    long["Metric"] = long["Metric"].map(labels)
    order = df.sort_values(metrics[0], ascending=False)[cat].tolist()
    return (
        alt.Chart(long)
        .mark_bar(cornerRadiusEnd=3)
        .encode(
            y=alt.Y(f"{cat}:N", sort=order, title=None),
            x=alt.X("Count:Q", title=None, axis=alt.Axis(format="~s")),
            yOffset="Metric:N",
            color=alt.Color(
                "Metric:N",
                scale=alt.Scale(range=[ACCENT, ACCENT_2]),
                legend=alt.Legend(orient="top", title=None),
            ),
            tooltip=[alt.Tooltip(f"{cat}:N"), "Metric:N", alt.Tooltip("Count:Q", format=",")],
        )
        .properties(height=max(220, 34 * len(order)))
    )


# ---------------------------------------------------------------- sidebar

with st.sidebar:
    st.markdown("### :material/sports_esports: Arcade Scores")
    live = st.toggle("Auto-refresh (5s)", value=True)
    st.caption(
        "Source: `ARCADE_DB.PUBLIC.ARCADE_SCORES` (Interactive Table)  \n"
        "Warehouse: `SUMMIT_INT_WH`  \n"
        "All windows are relative to current UTC time."
    )

REFRESH = f"{LIVE_TTL}s" if live else None


def updated_caption() -> None:
    st.caption(f"Updated {datetime.now(timezone.utc):%H:%M:%S} UTC")


# ---------------------------------------------------------------- live page


@st.fragment(run_every=REFRESH)
def header_kpis() -> None:
    kpi = run("PIPELINE_KPIS")
    games = run("GAME_POPULARITY_1H")
    cities = run("ACTIVE_CITIES_1M")
    c1, c2, c3, c4 = st.columns(4)
    if not kpi.empty:
        kpi = _int(_float(kpi, "FRESHNESS_SECONDS"), "TOTAL_GAMES")
        c1.metric("Games played (all time)", f"{kpi.TOTAL_GAMES.iloc[0]:,}", border=True)
        c4.metric("Data freshness", f"{kpi.FRESHNESS_SECONDS.iloc[0]:.2f} s", help="Seconds since the newest GAME_ENDED_AT (UTC)", border=True)
    if not games.empty:
        games = _int(games, "SESSIONS")
    if not cities.empty:
        top = cities.iloc[0]
        c3.metric("Hottest city · last min", top.PLAYER_CITY, help=f"{int(top.PLAYS):,} plays in {top.PLAYER_CITY}, {top.PLAYER_COUNTRY} in the last 60s", border=True)
    if not games.empty:
        top_game = games.iloc[0]
        c2.metric("Sessions · last hour", f"{games.SESSIONS.sum():,}", help=f"Most played: {top_game.GAME_NAME}", border=True)


@st.fragment(run_every=REFRESH)
def leaderboard() -> None:
    with st.container(border=True):
        st.markdown("### :material/trophy: Global leaderboard")
        st.caption("Highest single-game scores · last 24 hours")
        df = run("LEADERBOARD_24H")
        if empty_note(df):
            return
        df = _ts(_float(_int(df, "SCORE", "LEVEL_REACHED"), "ACCURACY_PCT"), "GAME_ENDED_AT")
        df.insert(0, "RANK", range(1, len(df) + 1))
        st.dataframe(
            df,
            hide_index=True,
            height=420,
            column_config={
                "RANK": st.column_config.NumberColumn("#", width="small"),
                "PLAYER_NAME": "Player",
                "GAME_NAME": "Game",
                "GAME_MODE": "Mode",
                "PLATFORM": "Platform",
                "PLAYER_COUNTRY": "Country",
                "SCORE": st.column_config.NumberColumn("Score", format="localized"),
                "LEVEL_REACHED": st.column_config.NumberColumn("Level"),
                "ACCURACY_PCT": st.column_config.ProgressColumn(
                    "Accuracy", min_value=0, max_value=100, format="%.1f%%"
                ),
                "GAME_ENDED_AT": st.column_config.DatetimeColumn("Ended (UTC)", format="MMM D, HH:mm:ss"),
            },
        )


@st.fragment(run_every=REFRESH)
def recent_activity() -> None:
    with st.container(border=True):
        st.markdown("### :material/bolt: Recent activity")
        st.caption("Last 30 scores as they land")
        df = run("RECENT_30")
        if empty_note(df):
            return
        df = _ts(_int(df, "SCORE", "DURATION_SECONDS"), "GAME_ENDED_AT")
        st.dataframe(
            df,
            hide_index=True,
            height=420,
            column_config={
                "GAME_ENDED_AT": st.column_config.DatetimeColumn("Time (UTC)", format="HH:mm:ss.SSS"),
                "PLAYER_NAME": "Player",
                "GAME_NAME": "Game",
                "PLATFORM": "Platform",
                "PLAYER_CITY": "City",
                "PLAYER_COUNTRY": "Country",
                "SCORE": st.column_config.NumberColumn("Score", format="localized"),
                "DURATION_SECONDS": st.column_config.NumberColumn("Duration", format="%d s"),
                "ACHIEVEMENT": "Achievement",
            },
        )


@st.fragment(run_every=REFRESH)
def top_players_by_game() -> None:
    with st.container(border=True):
        st.markdown("### :material/military_tech: Top 5 players by game")
        st.caption("Each player's best score per game · last hour")
        df = run("TOP_PLAYERS_BY_GAME_1H")
        if empty_note(df):
            return
        df = _int(df, "RANK", "BEST_SCORE", "GAMES_PLAYED")
        games = sorted(df.GAME_NAME.unique())
        game = st.selectbox("Game", games, key="tp_game", label_visibility="collapsed")
        sub = df[df.GAME_NAME == game].drop(columns="GAME_NAME")
        top = int(sub.BEST_SCORE.max()) or 1
        st.dataframe(
            sub,
            hide_index=True,
            column_config={
                "RANK": st.column_config.NumberColumn("#", width="small"),
                "PLAYER_NAME": "Player",
                "PLAYER_COUNTRY": "Country",
                "BEST_SCORE": st.column_config.ProgressColumn(
                    "Best score", min_value=0, max_value=top, format="localized"
                ),
                "GAMES_PLAYED": st.column_config.NumberColumn("Games (1h)"),
            },
        )


@st.fragment(run_every=REFRESH)
def geo_heatmap() -> None:
    with st.container(border=True):
        st.markdown("### :material/public: Plays by country")
        st.caption("Country-level plays · last hour · bubble size and heat ∝ plays (placed at mean player location)")
        df = run("COUNTRY_PLAYS_1H")
        if empty_note(df):
            return
        df = _float(_int(df, "PLAYS", "PLAYERS"), "LAT", "LON").dropna(subset=["LAT", "LON"])
        df["RADIUS"] = (df.PLAYS / df.PLAYS.max()) ** 0.5 * 600_000 + 60_000
        map_col, list_col = st.columns([2.2, 1])
        with map_col:
            deck = pdk.Deck(
                map_provider="carto",
                map_style="dark",
                initial_view_state=pdk.ViewState(latitude=25, longitude=10, zoom=0.8),
                layers=[
                    pdk.Layer(
                        "HeatmapLayer", df, get_position=["LON", "LAT"], get_weight="PLAYS",
                        radius_pixels=60, opacity=0.6,
                    ),
                    pdk.Layer(
                        "ScatterplotLayer", df, get_position=["LON", "LAT"], get_radius="RADIUS",
                        get_fill_color=[41, 181, 232, 140], stroked=True, get_line_color=[255, 255, 255, 120],
                        line_width_min_pixels=1, pickable=True,
                    ),
                ],
                tooltip={"text": "{PLAYER_COUNTRY}\n{PLAYS} plays · {PLAYERS} players"},
            )
            st.pydeck_chart(deck, height=380)
        with list_col:
            st.dataframe(
                df[["PLAYER_COUNTRY", "PLAYS", "PLAYERS"]],
                hide_index=True,
                height=380,
                    column_config={
                    "PLAYER_COUNTRY": "Country",
                    "PLAYS": st.column_config.ProgressColumn(
                        "Plays", min_value=0, max_value=int(df.PLAYS.max()), format="localized"
                    ),
                    "PLAYERS": st.column_config.NumberColumn("Players", format="localized"),
                },
            )


@st.fragment(run_every=REFRESH)
def popularity_and_platforms() -> None:
    labels = {"SESSIONS": "Sessions", "PLAYERS": "Unique players"}
    g_col, p_col = st.columns([1.4, 1])
    with g_col, st.container(border=True):
        st.markdown("### :material/joystick: Game popularity")
        st.caption("Sessions and unique players by game · last hour")
        df = run("GAME_POPULARITY_1H")
        if not empty_note(df):
            df = _int(df, "SESSIONS", "PLAYERS")
            st.altair_chart(hbar(df, "GAME_NAME", ["SESSIONS", "PLAYERS"], labels), use_container_width=True)
    with p_col, st.container(border=True):
        st.markdown("### :material/devices: Platform breakdown")
        st.caption("Sessions and unique players by platform · last hour")
        df = run("PLATFORM_1H")
        if not empty_note(df):
            df = _int(df, "SESSIONS", "PLAYERS")
            total = df.SESSIONS.sum()
            df["SHARE"] = df.SESSIONS / total if total else 0.0
            donut = (
                alt.Chart(df)
                .mark_arc(innerRadius=60, cornerRadius=4)
                .encode(
                    theta="SESSIONS:Q",
                    color=alt.Color("PLATFORM:N", legend=alt.Legend(orient="right", title=None),
                                    scale=alt.Scale(scheme="tableau10")),
                    tooltip=["PLATFORM:N", alt.Tooltip("SESSIONS:Q", format=","),
                             alt.Tooltip("SHARE:Q", format=".1%", title="Share of sessions"),
                             alt.Tooltip("PLAYERS:Q", format=",", title="Unique players")],
                )
                .properties(height=220)
            )
            st.altair_chart(donut, use_container_width=True)
            st.dataframe(
                df,
                hide_index=True,
                    column_config={
                    "PLATFORM": "Platform",
                    "SESSIONS": st.column_config.NumberColumn("Sessions", format="localized"),
                    "PLAYERS": st.column_config.NumberColumn("Unique players", format="localized"),
                    "SHARE": st.column_config.NumberColumn("Share", format="percent"),
                },
            )
            st.caption("Players can use several platforms, so unique players don't sum to a total.")


@st.fragment(run_every=REFRESH)
def active_cities() -> None:
    with st.container(border=True):
        st.markdown("### :material/location_city: Active cities")
        st.caption("Most active cities · last 60 seconds")
        df = run("ACTIVE_CITIES_1M")
        if empty_note(df, "No plays in the last minute."):
            return
        df = _int(df, "PLAYS", "PLAYERS")
        df["CITY"] = df.PLAYER_CITY + ", " + df.PLAYER_COUNTRY
        chart = (
            alt.Chart(df)
            .mark_bar(color=ACCENT, cornerRadiusEnd=3)
            .encode(
                y=alt.Y("CITY:N", sort="-x", title=None),
                x=alt.X("PLAYS:Q", title="Plays (last 60s)"),
                tooltip=["CITY:N", alt.Tooltip("PLAYS:Q", format=","), alt.Tooltip("PLAYERS:Q", format=",")],
            )
            .properties(height=max(220, 26 * len(df)))
        )
        st.altair_chart(chart, use_container_width=True)


@st.fragment(run_every="30s" if live else None)
def achievements() -> None:
    with st.container(border=True):
        st.markdown("### :material/workspace_premium: Achievements")
        st.caption("All earned achievements · all time")
        df = run("ACHIEVEMENTS", ttl=30)
        if empty_note(df, "No achievements earned yet."):
            return
        df = _ts(_int(df, "TIMES_EARNED", "PLAYERS"), "LAST_EARNED_AT")
        st.dataframe(
            df,
            hide_index=True,
            height=min(38 + 35 * len(df), 460),
            column_config={
                "ACHIEVEMENT": "Achievement",
                "TIMES_EARNED": st.column_config.ProgressColumn(
                    "Times earned", min_value=0, max_value=int(df.TIMES_EARNED.max()), format="localized"
                ),
                "PLAYERS": st.column_config.NumberColumn("Unique players", format="localized"),
                "LAST_EARNED_AT": st.column_config.DatetimeColumn("Last earned (UTC)", format="MMM D, HH:mm:ss"),
            },
        )


def live_page() -> None:
    st.title("Arcade Scores · Live")
    header_kpis()
    left, right = st.columns([1.35, 1])
    with left:
        leaderboard()
    with right:
        recent_activity()
    left, right = st.columns([1, 1.35])
    with left:
        top_players_by_game()
    with right:
        geo_heatmap()
    popularity_and_platforms()
    left, right = st.columns(2)
    with left:
        active_cities()
    with right:
        achievements()
    updated_caption()


# ---------------------------------------------------------------- pipeline page


@st.fragment(run_every=REFRESH)
def pipeline_page() -> None:
    st.title("Pipeline health")
    st.caption("Snowpipe Streaming → Interactive Table operational metrics")

    kpi = run("PIPELINE_KPIS")
    series = run("PIPELINE_SERIES_1H")

    if not series.empty:
        series = _ts(_float(_int(series, "ROW_COUNT"), "ROWS_PER_SEC", "FRESHNESS_SECONDS"), "MINUTE")
        # Reindex onto every minute so outages show as 0 rows/sec instead of being skipped.
        now_min = pd.Timestamp(datetime.now(timezone.utc).replace(tzinfo=None)).floor("min")
        full = pd.date_range(end=now_min - pd.Timedelta(minutes=1), periods=60, freq="min")
        series = series.set_index("MINUTE").reindex(full)
        series["ROW_COUNT"] = series.ROW_COUNT.fillna(0).astype("int64")
        series["ROWS_PER_SEC"] = series.ROWS_PER_SEC.fillna(0.0)
        series = series.rename_axis("MINUTE").reset_index()

    c1, c2, c3, c4 = st.columns(4)
    if not kpi.empty:
        kpi = _ts(_int(_float(kpi, "FRESHNESS_SECONDS"), "TOTAL_GAMES"), "LATEST_EVENT_AT")
        fresh = float(kpi.FRESHNESS_SECONDS.iloc[0])
        c1.metric("Total games played", f"{kpi.TOTAL_GAMES.iloc[0]:,}", help="All rows in ARCADE_SCORES", border=True)
        c2.metric(
            "Current freshness",
            f"{fresh:.3f} s",
            help="Seconds between the newest GAME_ENDED_AT and current UTC time",
            border=True,
        )
    if not series.empty:
        c3.metric(
            "Avg ingest rate · last hour",
            f"{series.ROWS_PER_SEC.mean():,.1f} rows/s",
            help="Mean of per-minute (row count / 60) over the last 60 complete minutes",
            border=True,
        )
        c4.metric("Rows · last hour", f"{series.ROW_COUNT.sum():,}", border=True)

    if not kpi.empty:
        status = "healthy" if fresh < 10 else ("lagging" if fresh < 60 else "stalled")
        icon = {"healthy": ":material/check_circle:", "lagging": ":material/warning:", "stalled": ":material/error:"}[status]
        latest = kpi.LATEST_EVENT_AT.iloc[0].strftime("%H:%M:%S.%f")[:-3]
        st.caption(f"{icon} Stream is **{status}** · latest event {latest} UTC")

    if empty_note(series, "No rows in the last hour."):
        return

    base = alt.Chart(series).encode(x=alt.X("MINUTE:T", title="Minute (UTC)", axis=alt.Axis(format="%H:%M")))
    left, right = st.columns(2)
    with left, st.container(border=True):
        st.markdown("### :material/speed: Ingest rate")
        st.caption("Rows per second = rows in each minute ÷ 60 · last 60 complete minutes")
        chart = base.mark_line(color=ACCENT, strokeWidth=2.5, point=True).encode(
            y=alt.Y("ROWS_PER_SEC:Q", title="Rows / sec", scale=alt.Scale(zero=False)),
            tooltip=[alt.Tooltip("MINUTE:T", format="%H:%M", title="Minute (UTC)"),
                     alt.Tooltip("ROWS_PER_SEC:Q", format=",.2f", title="Rows/sec"),
                     alt.Tooltip("ROW_COUNT:Q", format=",", title="Rows")],
        )
        st.altair_chart(chart.properties(height=300), use_container_width=True)
    with right, st.container(border=True):
        st.markdown("### :material/schedule: Freshness over time")
        st.caption(
            "Per minute: seconds between the newest row in that minute and the minute's end "
            "(staleness at minute close; gaps = no data)"
        )
        chart = base.mark_line(color=ACCENT_2, strokeWidth=2.5, point=True).encode(
            y=alt.Y("FRESHNESS_SECONDS:Q", title="Freshness (s)"),
            tooltip=[alt.Tooltip("MINUTE:T", format="%H:%M", title="Minute (UTC)"),
                     alt.Tooltip("FRESHNESS_SECONDS:Q", format=".3f", title="Freshness (s)")],
        )
        st.altair_chart(chart.properties(height=300), use_container_width=True)

    with st.expander("Per-minute data"):
        st.dataframe(
            series.sort_values("MINUTE", ascending=False),
            hide_index=True,
            column_config={
                "MINUTE": st.column_config.DatetimeColumn("Minute (UTC)", format="HH:mm"),
                "ROW_COUNT": st.column_config.NumberColumn("Rows", format="localized"),
                "ROWS_PER_SEC": st.column_config.NumberColumn("Rows/sec", format="%.2f"),
                "FRESHNESS_SECONDS": st.column_config.NumberColumn("Freshness (s)", format="%.3f"),
            },
        )
    updated_caption()


# ---------------------------------------------------------------- navigation

pg = st.navigation(
    [
        st.Page(live_page, title="Live dashboard", icon=":material/dashboard:", default=True),
        st.Page(pipeline_page, title="Pipeline health", icon=":material/monitor_heart:", url_path="pipeline"),
    ]
)
pg.run()
