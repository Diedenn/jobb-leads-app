import streamlit as st
import pandas as pd
import requests
import re
from io import BytesIO
from openai import OpenAI
from datetime import datetime, timedelta

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

# --- Region- och yrkesgrupp-ID:n ---
region_choices = {
    "Stockholms län": "1",
    "Uppsala län": "3",
    "Södermanlands län": "4",
    "Östergötlands län": "5",
    "Jönköpings län": "6",
    "Kronobergs län": "7",
    "Kalmar län": "8",
    "Gotlands län": "9",
    "Blekinge län": "10",
    "Skåne län": "12",
    "Hallands län": "13",
    "Västra Götalands län": "14",
    "Värmlands län": "17",
    "Örebro län": "18",
    "Västmanlands län": "19",
    "Dalarnas län": "20",
    "Gävleborgs län": "21",
    "Västernorrlands län": "22",
    "Jämtlands län": "23",
    "Västerbottens län": "24",
    "Norrbottens län": "25"
}

occupation_groups = {
    "Installation, drift, underhåll": "3",
    "Hälso- och sjukvård": "4",
    "Pedagogiskt arbete": "5",
    "Bygg och anläggning": "6",
    "Hotell, restaurang, storhushåll": "7",
    "Transport": "8",
    "Tekniskt arbete": "9",
    "Industriell tillverkning": "10",
    "Försäljning, inköp, marknadsföring": "11",
    "Data/IT": "12",
    "Administration, ekonomi, juridik": "13"
}

# --- Välj datumintervall och filter ---
st.sidebar.markdown("### 📅 Hämta jobbannonser via API")
start_date = st.sidebar.date_input("Startdatum", value=datetime.today() - timedelta(days=7))
end_date = st.sidebar.date_input("Slutdatum", value=datetime.today())
q_filter = st.sidebar.text_input("Sökord (t.ex. elektriker)", value="")
region_choice = st.sidebar.selectbox("Välj region", [""] + list(region_choices.keys()))
extent_filter = st.sidebar.selectbox("Arbetstid", ["", "1 - Heltid", "2 - Deltid"])
occupation_choice = st.sidebar.selectbox("Välj yrkesområde", [""] + list(occupation_groups.keys()))
kundfilter_val = st.sidebar.radio("Kundfilter", ["Alla annonser", "Endast nuvarande kunder", "Endast mina kunder", "Endast nya leads"])
require_contact = st.sidebar.checkbox("Endast annonser med kontaktperson & telefonnummer")

# --- API-hämtning dag för dag ---
@st.cache_data(ttl=3600)
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
            if q_filter:
                params["q"] = q_filter
            if region_choice:
                params["region"] = region_choices[region_choice]
            if extent_filter.startswith("1"):
                params["extent"] = "1"
            elif extent_filter.startswith("2"):
                params["extent"] = "2"
            if occupation_choice:
                params["occupation-group-id"] = occupation_groups[occupation_choice]

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

if st.sidebar.button("🔄 Hämta nya jobbannonser"):
    jobs_df = hamta_jobtech_data_interval(start_date, end_date)
    st.session_state["jobs_df"] = jobs_df

# --- Använd cachead version om inget klickas ---
if "jobs_df" not in st.session_state:
    st.info("🔹 Klicka på 'Hämta nya jobbannonser' i sidopanelen för att ladda data från API.")
    st.stop()

jobs_df = st.session_state["jobs_df"]

# --- Ladda in kundlistor ---
kund_team = pd.read_csv("data/kundlista_team.csv", sep=';', dtype=str)
kund_master = pd.read_csv("data/kundlista_master.csv", sep=';', dtype=str)
kund_team.columns = kund_team.columns.str.strip().str.lower()
kund_master.columns = kund_master.columns.str.strip().str.lower()
kund_team = kund_team.rename(columns={"org. nr (standardfält)": "orgnr", "kontoansvarig": "saljare"})
kund_master = kund_master.rename(columns={"customer_organization_number": "orgnr"})
kund_team['orgnr'] = kund_team['orgnr'].str.replace(r'[^0-9]', '', regex=True)
kund_master['orgnr'] = kund_master['orgnr'].str.replace(r'[^0-9]', '', regex=True)

# --- Förbered kolumner ---
jobs_df.columns = [str(col).lower() for col in jobs_df.columns]

if st.sidebar.checkbox("Visa tillgängliga kolumner (debug)"):
    st.write(jobs_df.columns.tolist())

jobs_df['orgnr'] = jobs_df.get('employer.organization_number', pd.NA).astype(str).str.replace(r'[^0-9]', '', regex=True)
jobs_df['description'] = jobs_df.get('description.text', pd.NA)
jobs_df['headline'] = jobs_df.get('headline', pd.NA)
jobs_df['region'] = jobs_df.get('workplace_address.region', pd.NA)
jobs_df['occupation'] = jobs_df.get('occupation.label', pd.NA)
jobs_df['occupation_group'] = jobs_df.get('occupation_group.label', pd.NA)
jobs_df['employer_name'] = jobs_df.get('employer.name', pd.NA)
jobs_df['working_hours_type'] = jobs_df.get('working_time_extent.label', pd.NA)

# --- Matchning ---
val_saljare = st.sidebar.selectbox("Filtrera på säljare (valfritt)", ["Visa alla"] + sorted(kund_team['saljare'].dropna().unique().tolist()))
aktiv_kundlista = kund_team[kund_team['saljare'] == val_saljare] if val_saljare != "Visa alla" else kund_master
jobs_df['kund'] = jobs_df['orgnr'].isin(kund_master['orgnr'])
jobs_df['mina_kunder'] = jobs_df['orgnr'].isin(aktiv_kundlista['orgnr'])

# --- Extrahera kontaktuppgifter ---
jobs_df['telefon'] = jobs_df['description'].str.extract(r'(\b\d{2,4}[-\s]?\d{5,})')
jobs_df['kontakt_namn'] = jobs_df['description'].str.extract(r'(\b[A-ZÅÄÖ][a-zåäö]+ [A-ZÅÄÖ][a-zåäö]+)')
jobs_df['kontakt_titel'] = jobs_df['description'].str.extract(r'(?:titel|roll|befattning)[:\-\s]*([\w \u00e5\u00e4\u00f6]+)', flags=re.IGNORECASE)

# --- Filtrera enligt kundval ---
df = jobs_df.copy()
if kundfilter_val == "Endast nuvarande kunder":
    df = df[df['kund'] == True]
elif kundfilter_val == "Endast mina kunder":
    df = df[df['mina_kunder'] == True]
elif kundfilter_val == "Endast nya leads":
    df = df[df['kund'] == False]

# --- Valfri filtrering: endast med kontaktperson och telefon ---
if require_contact:
    df = df[df['telefon'].notnull() & df['kontakt_namn'].notnull()]

# --- Visa resultat ---
st.subheader(f"Resultat: {len(df)} annonser")
st.dataframe(df[['employer_name', 'headline', 'description', 'region', 'working_hours_type', 'telefon', 'kontakt_namn', 'kontakt_titel', 'kund', 'mina_kunder']].reset_index(drop=True))

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
