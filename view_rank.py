import psycopg2

conn = psycopg2.connect(
    host="localhost",
    database="dota_db",
    user="dota",
    password="dota123"
)

cursor = conn.cursor()

cursor.execute("""
SELECT  
    t.name,  
    r.rating,  
    r.rd,  
    (r.rating - 2*r.rd) AS score  
FROM ratings r  
JOIN teams t ON r.team = t.name  
WHERE r.rd < 100  
ORDER BY score DESC  
LIMIT 20;
""")

rows = cursor.fetchall()

print(f"{'Rank':<5} {'Team':<25} {'Rating':<10} {'RD':<10} {'Score':<10}")
print("-" * 65)

for i, row in enumerate(rows, start=1):
    team, rating, rd, score = row
    print(f"{i:<5} {team:<25} {rating:.2f}   {rd:.2f}   {score:.2f}")

cursor.close()
conn.close()