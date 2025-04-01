import streamlit as st
import pandas as pd
import re
from io import BytesIO
import openai
import os

st.set_page_config(page_title="Jobbmatchning", layout="wide")
st.title("💼 Jobbmatchning & Leadsanalys")

openai.api_key = st.secrets["OPENAI_API_KEY"]

# --- Läs in data ---
jobs_excel = pd.ExcelFile("data/jobbdata.xlsx")
jobs_df = jobs_excel.parse(jobs_excel.sheet_names[0])

kund_team = pd.read_csv("data/kundlista_team.csv", sep=';', dtype=str)
kund_master = pd.read_csv("data/kundlista_master.csv", sep=';', dtype=str)

# --- Rensa kolumnnamn ---
jobs_df.columns = jobs_df.columns.str.lower()
kund_team.columns = kund_team.columns.str.strip().str.lower()
kund_master.columns = kund_master.columns.str.strip().str.lower()

# --- Döp om kolumner för enhetlighet ---
kund_team = kund_team.rename(columns={
    "org. nr (standardf\u00e4lt)": "orgnr",
    "kontoansvarig": "saljare"
})
kund_master = kund_master.rename(columns={
    "customer_organization_number": "orgnr"
})

# --- Säljare att välja mellan ---
saljare_lista = kund_team['saljare'].dropna().unique().tolist()
val_saljare = st.sidebar.selectbox("\ud83d\udcbc Välj säljare (filtrerar kundlistan)", saljare_lista)
filtrerad_teamlista = kund_team[kund_team['saljare'] == val_saljare]

# --- Val av kundlista ---
kundval = st.sidebar.radio("\ud83d\udc65 Filtrera mot:", ["Endast mina kunder", "Hela bolaget"])
aktiv_kundlista = filtrerad_teamlista if kundval == "Endast mina kunder" else kund_master

# --- Sidofilter ---
selected_region = st.sidebar.multiselect("Region", options=jobs_df['region'].dropna().unique())
selected_hours = st.sidebar.multiselect("Arbetstid", options=jobs_df['working_hours_type'].dropna().unique())
job_title_query = st.sidebar.text_input("Jobbtitel (del av text)")
require_phone = st.sidebar.checkbox("Endast med telefonnummer")
exclude_union = st.sidebar.checkbox("Exkludera fackliga kontakter")
only_non_customers = st.sidebar.checkbox("Visa endast nya leads")

# --- Matchning ---
jobs_df['orgnr'] = jobs_df['employer_organization_number'].astype(str)
aktiv_kundlista['orgnr'] = aktiv_kundlista['orgnr'].astype(str)
jobs_df['kund'] = jobs_df['orgnr'].isin(aktiv_kundlista['orgnr'])

# --- Extrahera telefonnummer ---
jobs_df['telefon'] = jobs_df['description'].str.extract(r'(\b\d{2,4}[-\s]?\d{5,})')

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
    df = df[~df['description'].str.contains("fack|unionen|saco|f\u00f6rbund", case=False, na=False)]
if only_non_customers:
    df = df[~df['kund']]

# --- GPT-fråga ---
with st.sidebar.expander("\ud83e\udd16 AI-fråga till datan"):
    user_question = st.text_area("Din fråga:")
    if user_question:
        prompt = f"""
        Du är en assistent som hjälper till att filtrera en pandas DataFrame.
        Kolumnerna i datan är: region, working_hours_type, kund, telefon, headline.
        Skapa ett Python-uttryck f\u00f6r att filtrera DataFrame df enligt fr\u00e5gan:

        Fr\u00e5ga: {user_question}
        """
        try:
            response = openai.ChatCompletion.create(
                model="gpt-4",
                messages=[{"role": "user", "content": prompt}],
                temperature=0
            )
            code = response.choices[0].message.content.strip()
            st.code(code, language='python')
            with st.spinner("K\u00f6r GPT-filter..."):
                df = eval(code)
        except Exception as e:
            st.error(f"Fel vid GPT-tolkning: {e}")

# --- Visa resultat ---
st.subheader(f"Resultat: {len(df)} annonser")
st.dataframe(df[['employer_name', 'headline', 'region', 'working_hours_type', 'telefon', 'kund']].reset_index(drop=True))

# --- Export ---
def to_excel_bytes(df):
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False)
    return output.getvalue()

excel_bytes = to_excel_bytes(df)
st.download_button(
    label="\ud83d\uddc3\ufe0f Ladda ner resultat som Excel",
    data=excel_bytes,
    file_name="filtrerat_resultat.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)
