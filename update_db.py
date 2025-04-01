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
            if offset >= 2000:
                break

            params = {
                "limit": 100,
                "offset": offset,
                "published-after": f"{start_date.strftime('%Y-%m-%dT00:00:00')}",
                "published-before": f"{(start_date + timedelta(days=1)).strftime('%Y-%m-%dT00:00:00')}"
            }
            response = requests.get(url, headers=headers, params=params)
            if response.status_code != 200:
                print(f"Fel vid API-anrop {response.status_code}: {response.text}")
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
    df.to_sql(TABLE_NAME, conn, if_exists='append', index=False)
    conn.close()

if __name__ == "__main__":
    start_date = datetime.today() - timedelta(days=7)
    end_date = datetime.today()

    df = fetch_jobs_from_api(start_date, end_date)

    if not df.empty:
        df = df.applymap(lambda x: ', '.join(x) if isinstance(x, list) else x)
        save_to_db(df)
        print(f"✅ Klar! Totalt sparade annonser: {len(df)}")
    else:
        print("⚠️ Inga jobbannonser hittades för valt datumintervall.")
