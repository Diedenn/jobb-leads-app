import streamlit as st
import pandas as pd
import re
from io import BytesIO
from openai import OpenAI
import os

st.set_page_config(page_title="Jobbmatchning", layout="wide")

# --- Enkel lösenordsskydd utan hash ---
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

# --- Grundläggande filtrering ---
val_saljare = st.sidebar.selectbox("Filtrera på säljare (valfritt)", ["Visa alla"] + sorted(kund_team['saljare'].dropna().unique().tolist()))
if val_saljare != "Visa alla":
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
    df = df[
        df['headline'].str.contains(job_title_query, case=False, na=False) |
        df['description'].str.contains(job_title_query, case=False, na=False) |
        df['occupation_group'].str.contains(job_title_query, case=False, na=False) |
        df['occupation'].str.contains(job_title_query, case=False, na=False)
    ]
if require_phone:
    df = df[df['telefon'].notnull()]
if exclude_union:
    df = df[~df['description'].str.contains("fack|unionen|saco|förbund", case=False, na=False)]
if val_saljare != "Visa alla":
    df = df[df['kund'] == True]
if only_non_customers:
    df = df[~df['kund']]

# --- AI Chat-gränssnitt ---
st.sidebar.markdown("### 💬 GPT-fråga till datan")
user_input = st.chat_input("Ställ en fråga till GPT om jobbdatat")
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

for msg in st.session_state.chat_history:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

if user_input:
    st.session_state.chat_history.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    prompt = f"""
    Du får en pandas-DataFrame som heter df med kolumner: region, working_hours_type, kund, telefon, headline, description, kontakt_namn, kontakt_titel, occupation_group, occupation.
    Din uppgift är att hjälpa användaren filtrera data. 
    Om användaren frågar om ett yrke eller roll, sök i kolumnerna: headline, description, occupation_group och occupation.
    Returnera först en kort förklaring på svenska om vad filtret gör, och sedan ett filteruttryck (t.ex. (df['region'] == 'Stockholm') & ...).
    Använd .notna() för att filtrera på kontaktfält. Skriv aldrig df['col1'].str.contains(df['col2']).
    Svara alltid i formatet:
    Förklaring: <kort text>
    Filter: <pandas-filter-uttryck>

    Fråga: {user_input}
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
        output = response.choices[0].message.content.strip()
        explanation, filter_code = output.split("Filter:", 1)
        filter_code = filter_code.strip()

        st.session_state.chat_history.append({"role": "assistant", "content": explanation.strip() + f"\n```python\ndf = df[{filter_code}]\n```"})
        with st.chat_message("assistant"):
            st.markdown(explanation.strip())
            editable_code = st.text_area("Redigera filter (valfritt innan körning)", value=filter_code, height=100)
            if st.button("Kör detta filter"):
                try:
                    df = df[eval(editable_code)]
                    st.success("Filtrering genomförd!")
                except Exception as e:
                    st.error(f"Fel i filterkoden: {e}")
    except Exception as e:
        st.error(f"Fel vid GPT-anrop: {e}")

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
