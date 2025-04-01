import streamlit as st
import pandas as pd
import re
import requests
from io import BytesIO
from datetime import datetime, timedelta
from openai import OpenAI

st.set_page_config(page_title="Jobbmatchning", layout="wide")

# --- Enkel lösenordsskydd ---
def check_password():
    def password_entered():
        if "password" not in st.session_state:
            return
        if st.session_state["password"] == "Satellite2025":
            st.session_state["password_correct"] = True
            del st.session_state["password"]
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        st.text_input("Lösenord", type="password", on_change=password_entered, key="password")
        st.stop()
    elif not st.session_state["password_correct"]:
        st.error("Fel lösenord")
        st.stop()

check_password()

st.title("Jobbmatchning & Leadsanalys")

client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])

kund_team = pd.read_csv("data/kundlista_team.csv", sep=';', dtype=str)
kund_master = pd.read_csv("data/kundlista_master.csv", sep=';', dtype=str)
kund_team.columns = kund_team.columns.str.strip().str.lower()
kund_master.columns = kund_master.columns.str.strip().str.lower()
kund_team = kund_team.rename(columns={"org. nr (standardfält)": "orgnr", "kontoansvarig": "saljare"})
kund_master = kund_master.rename(columns={"customer_organization_number": "orgnr"})
kund_team['orgnr'] = kund_team['orgnr'].str.replace(r'[^0-9]', '', regex=True)
kund_master['orgnr'] = kund_master['orgnr'].str.replace(r'[^0-9]', '', regex=True)

# --- API-datahämtning ---
def hamta_jobtech_data_interval(start, end):
    url = "https://jobsearch.api.jobtechdev.se/search"
    headers = {"accept": "application/json"}
    all_hits = []
    current_date = start

    while current_date <= end:
        next_day = current_date + timedelta(days=1)
        offset = 0
        while True:
            params = {
                "limit": 100,
                "offset": offset,
                "published-after": f"{current_date}T00:00:00",
                "published-before": f"{next_day}T00:00:00"
            }
            r = requests.get(url, headers=headers, params=params)
            if r.status_code != 200:
                break
            data = r.json()
            hits = data.get("hits", [])
            if not hits:
                break
            all_hits.extend(hits)
            offset += 100
        current_date = next_day

    return pd.json_normalize(all_hits)

start_date = st.sidebar.date_input("Startdatum", value=datetime.today() - timedelta(days=2))
end_date = st.sidebar.date_input("Slutdatum", value=datetime.today())

if st.sidebar.button("🔄 Hämta nya jobbannonser"):
    with st.spinner("Hämtar annonser från API..."):
        jobs_df = hamta_jobtech_data_interval(start_date, end_date)
        st.session_state["jobs_df"] = jobs_df

if "jobs_df" not in st.session_state:
    st.info("🔹 Klicka på 'Hämta nya jobbannonser' i sidopanelen.")
    st.stop()

jobs_df = st.session_state["jobs_df"]
jobs_df.columns = [str(c).lower() for c in jobs_df.columns]
jobs_df['employer.organization_number'] = jobs_df['employer.organization_number'].astype(str).str.replace(r'[^0-9]', '', regex=True)
jobs_df['orgnr'] = jobs_df['employer.organization_number']

# --- Extrahera kontaktuppgifter med regex ---
jobs_df['description.text'] = jobs_df.get('description.text', '')
jobs_df['telefon'] = jobs_df['description.text'].str.extract(r'(\b\d{2,4}[-\s]?\d{5,})')
jobs_df['kontakt_namn'] = jobs_df['description.text'].str.extract(r'(\b[A-ZÅÄÖ][a-zåäö]+ [A-ZÅÄÖ][a-zåäö]+)')
jobs_df['kontakt_titel'] = jobs_df['description.text'].str.extract(r'(?:titel|roll|befattning)[:\-\s]*([\w \u00e5\u00e4\u00f6]+)', flags=re.IGNORECASE)

# --- Matcha kundlistor ---
val_saljare = st.sidebar.selectbox("Filtrera på säljare (valfritt)", ["Visa alla"] + sorted(kund_team['saljare'].dropna().unique().tolist()))
aktiv_kundlista = kund_team[kund_team['saljare'] == val_saljare] if val_saljare != "Visa alla" else kund_master
jobs_df['kund'] = jobs_df['orgnr'].isin(kund_master['orgnr'])
jobs_df['mina_kunder'] = jobs_df['orgnr'].isin(aktiv_kundlista['orgnr'])

# --- Filtrering ---
selected_region = st.sidebar.multiselect("Region", options=jobs_df['workplace_address.region'].dropna().unique())
selected_hours = st.sidebar.multiselect("Arbetstid", options=jobs_df['working_time_extent.label'].dropna().unique())
job_title_query = st.sidebar.text_input("Jobbtitel (del av text)")
require_phone = st.sidebar.checkbox("Endast med telefonnummer")
exclude_union = st.sidebar.checkbox("Exkludera fackliga kontakter")
only_non_customers = st.sidebar.checkbox("Visa endast nya leads")

# --- Applicera filter ---
df = jobs_df.copy()
if selected_region:
    df = df[df['workplace_address.region'].isin(selected_region)]
if selected_hours:
    df = df[df['working_time_extent.label'].isin(selected_hours)]
if job_title_query:
    df = df[
        df['headline'].str.contains(job_title_query, case=False, na=False) |
        df['description.text'].str.contains(job_title_query, case=False, na=False) |
        df['occupation_group.label'].str.contains(job_title_query, case=False, na=False) |
        df['occupation.label'].str.contains(job_title_query, case=False, na=False)
    ]
if require_phone:
    df = df[df['telefon'].notnull()]
if exclude_union:
    df = df[~df['description.text'].str.contains("fack|unionen|saco|förbund", case=False, na=False)]
if val_saljare != "Visa alla":
    df = df[df['mina_kunder'] == True]
if only_non_customers:
    df = df[~df['kund']]

# --- Visa resultat ---
st.subheader(f"Resultat: {len(df)} annonser")
st.dataframe(df[['employer.name', 'headline', 'description.text', 'workplace_address.region', 'working_time_extent.label', 'telefon', 'kontakt_namn', 'kontakt_titel', 'kund', 'mina_kunder']].reset_index(drop=True))

# --- Export ---
def to_excel_bytes(df):
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False)
    return output.getvalue()

excel_bytes = to_excel_bytes(df)
st.download_button(
    label="Ladda ner resultat som Excel",
    data=excel_bytes,
    file_name="filtrerat_resultat.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)
