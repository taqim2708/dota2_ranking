import argparse
import time
import requests
import psycopg2
from datetime import datetime
from glicko2 import Player

BASE_URL = "https://api.opendota.com/api"


# -----------------------------
# DB CONNECTION
# -----------------------------
def get_conn():
    return psycopg2.connect(
        host="localhost",
        database="dota_db",
        user="dota",
        password="dota123"
    )


# -----------------------------
# FETCH PRO MATCHES
# -----------------------------
def fetch_matches(less_than=None):
    url = f"{BASE_URL}/proMatches"
    if less_than:
        url += f"?less_than_match_id={less_than}"

    r = requests.get(url, timeout=20)
    r.raise_for_status()
    return r.json()


# -----------------------------
# INGEST MATCHES + TEAMS
# -----------------------------
def ingest(pages=20):
    conn = get_conn()
    cur = conn.cursor()

    last_id = None

    for i in range(pages):
        matches = fetch_matches(last_id)
        if not matches:
            break

        for m in matches:
            match_id = m["match_id"]

            radiant_id = m.get("radiant_team_id")
            dire_id = m.get("dire_team_id")

            radiant_name = m.get("radiant_name")
            dire_name = m.get("dire_name")

            # insert match
            cur.execute("""
                INSERT INTO matches (
                    match_id, start_time,
                    radiant_team_id, dire_team_id,
                    radiant_score, dire_score,
                    radiant_win, league_name
                )
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (match_id) DO NOTHING
            """, (
                match_id,
                datetime.fromtimestamp(m["start_time"]),
                radiant_id,
                dire_id,
                m.get("radiant_score"),
                m.get("dire_score"),
                m.get("radiant_win"),
                m.get("league_name")
            ))

            # upsert teams (IMPORTANT FIX)
            if radiant_id:
                cur.execute("""
                    INSERT INTO teams (team_id, name)
                    VALUES (%s, %s)
                    ON CONFLICT (team_id)
                    DO UPDATE SET name = EXCLUDED.name
                """, (radiant_id, radiant_name))

            if dire_id:
                cur.execute("""
                    INSERT INTO teams (team_id, name)
                    VALUES (%s, %s)
                    ON CONFLICT (team_id)
                    DO UPDATE SET name = EXCLUDED.name
                """, (dire_id, dire_name))

        conn.commit()

        last_id = min(m["match_id"] for m in matches)
        print(f"[INGEST] batch {i+1} done, last_id={last_id}")

        time.sleep(1)

    cur.close()
    conn.close()


# -----------------------------
# COMPUTE GLICKO-2
# -----------------------------
BASE_RATING = 1500
def compute():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT radiant_team_id, dire_team_id, radiant_win
        FROM matches
        WHERE radiant_team_id IS NOT NULL AND dire_team_id IS NOT NULL
        ORDER BY start_time ASC
    """)
    all_matches = cur.fetchall()

    players = {}

    def get_p(tid):
        if tid not in players:
            players[tid] = Player()
        return players[tid]

    # 1. Define a Batch Size (Rating Period)
    # Glicko-2 works best when a player has multiple games per update
    batch_size = 50 
    
    for i in range(0, len(all_matches), batch_size):
        batch = all_matches[i : i + batch_size]
        
        # 2. Create a Snapshot of ratings for THIS period
        # This ensures all calculations in this batch use "start-of-period" stats
        snapshot = {tid: (p.rating, p.rd) for tid, p in players.items()}
        
        # 3. Collect match data for every player in this batch
        period_data = {} # { team_id: { opp_ratings: [], opp_rds: [], outcomes: [] } }

        for a, b, win in batch:
            get_p(a); get_p(b) # Ensure they exist in 'players'
            
            # Helper to append match results
            for self_id, opp_id, outcome in [(a, b, 1 if win else 0), (b, a, 0 if win else 1)]:
                if self_id not in period_data:
                    period_data[self_id] = {'r': [], 'rd': [], 'o': []}
                
                # Use snapshot if available, else default starting values
                opp_r, opp_rd = snapshot.get(opp_id, (BASE_RATING, 350))
                
                period_data[self_id]['r'].append(opp_r)
                period_data[self_id]['rd'].append(opp_rd)
                period_data[self_id]['o'].append(outcome)

        # 4. Update players who played and handle those who didn't
        for tid, p in players.items():
            if tid in period_data:
                data = period_data[tid]
                p.update_player(data['r'], data['rd'], data['o'])
            else:
                # IMPORTANT: RD must increase for inactive players
                p.did_not_compete()

    # 5. Save to Database
    for team_id, p in players.items():
        cur.execute("""
            INSERT INTO ratings (team, rating, rd, sigma)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (team) DO UPDATE SET
                rating = EXCLUDED.rating,
                rd = EXCLUDED.rd,
                sigma = EXCLUDED.sigma,
                last_updated = NOW()
        """, (team_id, p.rating, p.rd, p.vol))

    conn.commit()
    cur.close()
    conn.close()
    print("[GLICKO] Batch computation complete")

# -----------------------------
# SHOW RANKINGS
# -----------------------------
def show(limit=20):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT 
            COALESCE(t.name, r.team::text) AS team,
            r.rating,
            r.rd,
            r.rating AS score
        FROM ratings r
        LEFT JOIN teams t
            ON t.team_id = r.team::bigint
        WHERE r.rd < 90
        ORDER BY score DESC
        LIMIT %s;
    """, (limit,))

    rows = cur.fetchall()

    print(f"\nRANK|{' TEAM ':<27}| RATING |{' RD ':<6}| SCORE")
    print("-" * 60)

    for i, row in enumerate(rows, 1):
        print(f"{i:>3} | {row[0]:<25} | {row[1]:.1f} | {row[2]:.1f} | {row[3]:.1f}")

    cur.close()
    conn.close()


# -----------------------------
# CLI
# -----------------------------
def main():
    parser = argparse.ArgumentParser()

    parser.add_argument("--ingest", action="store_true")
    parser.add_argument("--compute", action="store_true")
    parser.add_argument("--show", action="store_true")
    parser.add_argument("--pages", type=int, default=20)
    parser.add_argument("--limit", type=int, default=20)

    args = parser.parse_args()

    if args.ingest:
        ingest(args.pages)

    if args.compute:
        compute()

    if args.show:
        show(args.limit)


if __name__ == "__main__":
    main()