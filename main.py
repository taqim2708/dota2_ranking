import requests
import psycopg2
import time
from datetime import datetime

BASE_URL = "https://api.opendota.com/api"

conn = psycopg2.connect(
    host="localhost",
    database="dota_db",
    user="dota",
    password="dota123"
)

cursor = conn.cursor()


def fetch_pro_matches(less_than=None):
    url = f"{BASE_URL}/proMatches"
    if less_than:
        url += f"?less_than_match_id={less_than}"

    res = requests.get(url)
    res.raise_for_status()
    return res.json()


def insert_match(m):
    cursor.execute("""
        INSERT INTO matches (
            match_id, start_time, team_radiant, team_dire,
            radiant_score, dire_score, radiant_win, league_name
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (match_id) DO NOTHING
    """, (
        m["match_id"],
        datetime.fromtimestamp(m["start_time"]),
        m.get("radiant_name"),
        m.get("dire_name"),
        m.get("radiant_score"),
        m.get("dire_score"),
        m.get("radiant_win"),
        m.get("league_name")
    ))


def main():
    last_id = None

    for _ in range(50):  # paginate
        matches = fetch_pro_matches(last_id)

        if not matches:
            break

        for m in matches:
            insert_match(m)

        conn.commit()

        last_id = matches[-1]["match_id"]
        print(f"Inserted batch, last_id={last_id}")

        time.sleep(1)  # rate limit


if __name__ == "__main__":
    main()