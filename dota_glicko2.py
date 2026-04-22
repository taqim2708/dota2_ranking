import psycopg2
from glicko2 import Player
from collections import defaultdict

# DB connection
conn = psycopg2.connect(
    host="localhost",
    database="dota_db",
    user="dota",
    password="dota123"
)
cursor = conn.cursor()

# Load matches (ordered by time)
cursor.execute("""
    SELECT 
        radiant_team_id,
        dire_team_id,
        radiant_win
    FROM matches
    WHERE radiant_team_id IS NOT NULL
      AND dire_team_id IS NOT NULL
    ORDER BY start_time ASC
""")

matches = cursor.fetchall()

# Team rating storage
players = {}

def get_player(team_id):
    if team_id not in players:
        players[team_id] = Player()
    return players[team_id]

# Process matches
for team_a, team_b, radiant_win in matches:
    player_a = get_player(team_a)
    player_b = get_player(team_b)

    # result: 1 = win, 0 = loss
    if radiant_win:
        score_a, score_b = 1, 0
    else:
        score_a, score_b = 0, 1

    # Update both players
    player_a.update_player(
        [player_b.rating],
        [player_b.rd],
        [score_a]
    )

    player_b.update_player(
        [player_a.rating],
        [player_a.rd],
        [score_b]
    )

cursor.execute("""
    CREATE TABLE teams (
    team_id BIGINT PRIMARY KEY,
    name TEXT
);
""")

# Save results back to Postgres
for team, p in players.items():
    cursor.execute("""
        INSERT INTO ratings (team, rating, rd, sigma)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (team)
        DO UPDATE SET
            rating = EXCLUDED.rating,
            rd = EXCLUDED.rd,
            sigma = EXCLUDED.sigma,
            last_updated = NOW()
    """, (team, p.rating, p.rd, p.vol))

conn.commit()
cursor.close()
conn.close()

print("Ratings computed and saved.")