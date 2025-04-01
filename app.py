import streamlit as st
import pandas as pd
import re
import hashlib
from io import BytesIO
from openai import OpenAI
import os

st.set_page_config(page_title="Jobbmatchning", layout="wide")

# --- Enkel lösenordsskydd ---
def check_password():
    def password_entered():
        if hashlib.sha256(st.session_state["password"].encode()).hexdigest() == st.secrets["app_password"]:
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

# --- Läs in data ---
jobs_excel = pd.ExcelFile("data/jobbdata.xlsx")
jobs_df = jobs_excel.parse("jobbdata")

kund_team = pd.read_csv("data/kundlista_team.csv", sep=';', dtype=str)
kund_master = pd.read_csv("data/kundlista_master.csv", sep=';', dtype=str)

# --- Rensa kolumnnamn ---
jobs_df.columns = jobs_df.columns.str.lower()
kund_team.columns = kund_team.columns.str.strip().str.lower()
kund_master.columns = kund_master.columns.str.strip().str.lower()

# --- Döp om kolumner för enhetlighet ---
kund_team = kund_team.rename(columns={
    "org. nr (standardfält)": "orgnr",
    "kontoansvarig": "saljare"
})
kund_master = kund_master.rename(columns={
    "customer_organization_number": "orgnr"
})

# --- Standardisera orgnr-format (endast siffror) ---
kund_team['orgnr'] = kund_team['orgnr'].str.replace(r'[^0-9]', '', regex=True)
kund_master['orgnr'] = kund_master['orgnr'].str.replace(r'[^0-9]', '', regex=True)
jobs_df['employer_organization_number'] = jobs_df['employer_organization_number'].astype(str).str.replace(r'[^0-9]', '', regex=True)

# --- Val av kundlista ---
kundval = st.sidebar.radio("Filtrera mot:", ["Endast mina kunder", "Hela bolaget"])

# --- Säljare att välja mellan om 'endast mina kunder' är valt ---
if kundval == "Endast mina kunder":
    saljare_lista = kund_team['saljare'].dropna().unique().tolist()
    val_saljare = st.sidebar.selectbox("Välj säljare (filtrerar kundlistan)", saljare_lista)
    aktiv_kundlista = kund_team[kund_team['saljare'] == val_saljare]
else:
    aktiv_kundlista = kund_master

# --- Sidofilter ---
selected_region = st.sidebar.multiselect("Region", options=jobs_df['region'].dropna().unique())
selected_hours = st.sidebar.multiselect("Arbetstid", options=jobs_df['working_hours_type'].dropna().unique())
job_title_query = st.sidebar.text_input("Jobbtitel (del av text)")
require_phone = st.sidebar.checkbox("Endast med telefonnummer")
exclude_union = st.sidebar.checkbox("Exkludera fackliga kontakter")
only_non_customers = st.sidebar.checkbox("Visa endast nya leads")

# --- Matchning ---
jobs_df['orgnr'] = jobs_df['employer_organization_number']
aktiv_kundlista['orgnr'] = aktiv_kundlista['orgnr']
jobs_df['kund'] = jobs_df['orgnr'].isin(aktiv_kundlista['orgnr'])

# --- Extrahera kontaktuppgifter ---
jobs_df['telefon'] = jobs_df['description'].str.extract(r'(\b\d{2,4}[-\s]?\d{5,})')
jobs_df['kontakt_namn'] = jobs_df['description'].str.extract(r'(\b[A-ZÅÄÖ][a-zåäö]+ [A-ZÅÄÖ][a-zåäö]+)')
jobs_df['kontakt_titel'] = jobs_df['description'].str.extract(r'(?:titel|roll|befattning)[:\-\s]*([\w \u00e5\u00e4\u00f6]+)', flags=re.IGNORECASE)

# --- Grundfilter ---
df = jobs_df.copy()
if selected_region:
    df = df[df['region'].isin(selected_region)]
if selected_hours:
    df = df[df['working_hours_type'].isin(selected_hours)]
if job_title_query:
    df = df[df['headline'].str.contains(job_title_query, case=False, na=False)]
if require_phone:
    df = df[df['telefon'].notnull()]
if exclude_union:
    df = df[~df['description'].str.contains("fack|unionen|saco|förbund", case=False, na=False)]
if kundval == "Endast mina kunder":
    df = df[df['kund'] == True]
if only_non_customers:
    df = df[~df['kund']]

# --- GPT-fråga ---
with st.sidebar.expander("AI-fråga till datan"):
    st.markdown("Exempel på frågor du kan ställa:")
    st.markdown("- Visa alla jobb i Stockholm som är heltid och inte är kunder")
    st.markdown("- Filtrera ut annonser med titeln \"lastbilschaufför\" som har telefonnummer")
    st.markdown("- Visa alla jobb där det finns kontaktperson och titel i beskrivningen")
    st.markdown("- Filtrera på annonser som innehåller \"ekonomi\" i headline men inte är från kund")

    user_question = st.text_area("Din fråga:")
    if user_question:
        prompt = f"""
        Kolumnerna i datan är: region, working_hours_type, kund, telefon, headline, description, kontakt_namn, kontakt_titel.
        Skapa ett Python-uttryck för att filtrera DataFrame df enligt frågan:

        Fråga: {user_question}
        """
        try:
            response = client.chat.completions.create(
                model="gpt-4",
                messages=[
                    {"role": "system", "content": "Du är en assistent som hjälper till att filtrera en pandas DataFrame."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0
            )
            code = response.choices[0].message.content.strip()
            st.code(code, language='python')
            with st.spinner("Kör GPT-filter..."):
                df = eval(code)
        except Exception as e:
            st.error(f"Fel vid GPT-tolkning: {e}")

# --- Visa resultat ---
st.subheader(f"Resultat: {len(df)} annonser")
st.dataframe(df[['employer_name', 'headline', 'description', 'region', 'working_hours_type', 'telefon', 'kontakt_namn', 'kontakt_titel', 'kund']].reset_index(drop=True))

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
