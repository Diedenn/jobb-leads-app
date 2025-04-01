import sqlite3
import requests
import pandas as pd
from datetime import datetime, timedelta

DB_PATH = "jobbdata.db"
TABLE_NAME = "annonser"

def fetch_jobs_from_api(start_date, end_date):
    url = "https://jobsearch.api.jobtechdev.se/search"
    headers = {"accept": "application/json"}
    all_hits = []

    while start_date <= end_date:
        offset = 0
        while True:
            params = {
                "limit": 100,
                "offset": offset,
                "published-after": f"{start_date}T00:00:00",
                "published-before": f"{start_date + timedelta(days=1)}T00:00:00"
            }
            response = requests.get(url, headers=headers, params=params)
            if response.status_code != 200:
                break
            hits = response.json().get("hits", [])
            if not hits:
                break
            all_hits.extend(hits)
            offset += 100
        start_date += timedelta(days=1)

    return pd.json_normalize(all_hits)

def save_to_db(df):
    conn = sqlite3.connect(DB_PATH)
    df.to_sql(TABLE_NAME, conn, if_exists='replace', index=False)
    conn.close()

# ✅ HÄR KÖRS DET!
if __name__ == "__main__":
    print("🔄 Hämtar jobbannonser...")
    start = datetime.today() - timedelta(days=2)
    end = datetime.today()
    df = fetch_jobs_from_api(start, end)

    if not df.empty:
        save_to_db(df)
        print(f"✅ Klar! Totalt sparade annonser: {len(df)}")
    else:
        print("⚠️ Inga annonser hämtades.")
