"""SQL for the Arcade Scores dashboard.

All timestamps in ARCADE_SCORES.GAME_ENDED_AT are TIMESTAMP_NTZ in UTC, so every
time window is anchored to the current UTC time as TIMESTAMP_NTZ. Numeric
columns are cast explicitly so pandas receives predictable dtypes.
"""

TABLE = "ARCADE_DB.PUBLIC.ARCADE_SCORES"
NOW_UTC = "CONVERT_TIMEZONE('UTC', CURRENT_TIMESTAMP())::TIMESTAMP_NTZ"

# 1. Global leaderboard: highest single scores in the last 24 hours.
LEADERBOARD_24H = f"""
SELECT
    PLAYER_NAME,
    GAME_NAME,
    GAME_MODE,
    PLATFORM,
    PLAYER_COUNTRY,
    SCORE::INT          AS SCORE,
    LEVEL_REACHED::INT  AS LEVEL_REACHED,
    ACCURACY_PCT::FLOAT AS ACCURACY_PCT,
    GAME_ENDED_AT
FROM {TABLE}
WHERE GAME_ENDED_AT >= DATEADD('hour', -24, {NOW_UTC})
ORDER BY SCORE DESC, GAME_ENDED_AT ASC
LIMIT 25
"""

# 2. Top 5 players per game in the last hour (best score per player per game).
TOP_PLAYERS_BY_GAME_1H = f"""
WITH best AS (
    SELECT
        GAME_NAME,
        PLAYER_ID,
        ANY_VALUE(PLAYER_NAME)    AS PLAYER_NAME,
        ANY_VALUE(PLAYER_COUNTRY) AS PLAYER_COUNTRY,
        MAX(SCORE)::INT           AS BEST_SCORE,
        COUNT(*)::INT             AS GAMES_PLAYED
    FROM {TABLE}
    WHERE GAME_ENDED_AT >= DATEADD('hour', -1, {NOW_UTC})
    GROUP BY GAME_NAME, PLAYER_ID
)
SELECT
    GAME_NAME,
    ROW_NUMBER() OVER (PARTITION BY GAME_NAME ORDER BY BEST_SCORE DESC, PLAYER_ID)::INT AS RANK,
    PLAYER_NAME,
    PLAYER_COUNTRY,
    BEST_SCORE,
    GAMES_PLAYED
FROM best
QUALIFY RANK <= 5
ORDER BY GAME_NAME, RANK
"""

# 3. Country-level plays in the last hour, with a centroid for map placement.
COUNTRY_PLAYS_1H = f"""
SELECT
    PLAYER_COUNTRY,
    COUNT(*)::INT                  AS PLAYS,
    COUNT(DISTINCT PLAYER_ID)::INT AS PLAYERS,
    AVG(LATITUDE)::FLOAT           AS LAT,
    AVG(LONGITUDE)::FLOAT          AS LON
FROM {TABLE}
WHERE GAME_ENDED_AT >= DATEADD('hour', -1, {NOW_UTC})
GROUP BY PLAYER_COUNTRY
ORDER BY PLAYS DESC
"""

# 4. Game popularity (last hour).
GAME_POPULARITY_1H = f"""
SELECT
    GAME_NAME,
    COUNT(*)::INT                  AS SESSIONS,
    COUNT(DISTINCT PLAYER_ID)::INT AS PLAYERS
FROM {TABLE}
WHERE GAME_ENDED_AT >= DATEADD('hour', -1, {NOW_UTC})
GROUP BY GAME_NAME
ORDER BY SESSIONS DESC
"""

# 5. Platform breakdown (last hour).
PLATFORM_1H = f"""
SELECT
    PLATFORM,
    COUNT(*)::INT                  AS SESSIONS,
    COUNT(DISTINCT PLAYER_ID)::INT AS PLAYERS
FROM {TABLE}
WHERE GAME_ENDED_AT >= DATEADD('hour', -1, {NOW_UTC})
GROUP BY PLATFORM
ORDER BY SESSIONS DESC
"""

# 6. Recent activity: last 30 scores.
RECENT_30 = f"""
SELECT
    GAME_ENDED_AT,
    PLAYER_NAME,
    GAME_NAME,
    PLATFORM,
    PLAYER_CITY,
    PLAYER_COUNTRY,
    SCORE::INT             AS SCORE,
    DURATION_SECONDS::INT  AS DURATION_SECONDS,
    ACHIEVEMENT
FROM {TABLE}
ORDER BY GAME_ENDED_AT DESC
LIMIT 30
"""

# 7. Achievements: all earned achievements (all time).
ACHIEVEMENTS = f"""
SELECT
    ACHIEVEMENT,
    COUNT(*)::INT                  AS TIMES_EARNED,
    COUNT(DISTINCT PLAYER_ID)::INT AS PLAYERS,
    MAX(GAME_ENDED_AT)             AS LAST_EARNED_AT
FROM {TABLE}
WHERE ACHIEVEMENT IS NOT NULL
GROUP BY ACHIEVEMENT
ORDER BY TIMES_EARNED DESC
"""

# 8. Most active cities in the last minute.
ACTIVE_CITIES_1M = f"""
SELECT
    PLAYER_CITY,
    PLAYER_COUNTRY,
    COUNT(*)::INT                  AS PLAYS,
    COUNT(DISTINCT PLAYER_ID)::INT AS PLAYERS
FROM {TABLE}
WHERE GAME_ENDED_AT >= DATEADD('minute', -1, {NOW_UTC})
GROUP BY PLAYER_CITY, PLAYER_COUNTRY
ORDER BY PLAYS DESC, PLAYER_CITY
LIMIT 15
"""

# 9a. Pipeline health headline numbers.
PIPELINE_KPIS = f"""
SELECT
    COUNT(*)::INT AS TOTAL_GAMES,
    (DATEDIFF('millisecond', MAX(GAME_ENDED_AT), {NOW_UTC}) / 1000.0)::FLOAT AS FRESHNESS_SECONDS,
    MAX(GAME_ENDED_AT) AS LATEST_EVENT_AT,
    {NOW_UTC} AS NOW_UTC
FROM {TABLE}
"""

# 9b. Per-minute pipeline series for the last 60 *complete* minutes.
# The in-progress minute is excluded so rows/sec is never under-counted.
# FRESHNESS_SECONDS = gap between the newest row in a minute and that minute's end,
# i.e. how stale the table was at the close of each minute.
# ROWS_PER_SEC = rows in the minute / 60.
PIPELINE_SERIES_1H = f"""
WITH bounds AS (
    SELECT DATE_TRUNC('minute', {NOW_UTC}) AS END_TS
)
SELECT
    DATE_TRUNC('minute', s.GAME_ENDED_AT) AS MINUTE,
    COUNT(*)::INT AS ROW_COUNT,
    (COUNT(*) / 60.0)::FLOAT AS ROWS_PER_SEC,
    (DATEDIFF('millisecond', MAX(s.GAME_ENDED_AT),
              DATEADD('minute', 1, DATE_TRUNC('minute', s.GAME_ENDED_AT))) / 1000.0)::FLOAT
        AS FRESHNESS_SECONDS
FROM {TABLE} s, bounds b
WHERE s.GAME_ENDED_AT >= DATEADD('minute', -60, b.END_TS)
  AND s.GAME_ENDED_AT <  b.END_TS
GROUP BY MINUTE
ORDER BY MINUTE
"""

ALL = {
    "LEADERBOARD_24H": LEADERBOARD_24H,
    "TOP_PLAYERS_BY_GAME_1H": TOP_PLAYERS_BY_GAME_1H,
    "COUNTRY_PLAYS_1H": COUNTRY_PLAYS_1H,
    "GAME_POPULARITY_1H": GAME_POPULARITY_1H,
    "PLATFORM_1H": PLATFORM_1H,
    "RECENT_30": RECENT_30,
    "ACHIEVEMENTS": ACHIEVEMENTS,
    "ACTIVE_CITIES_1M": ACTIVE_CITIES_1M,
    "PIPELINE_KPIS": PIPELINE_KPIS,
    "PIPELINE_SERIES_1H": PIPELINE_SERIES_1H,
}
