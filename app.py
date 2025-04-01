
import streamlit as st
import pandas as pd
import re
from io import BytesIO

st.set_page_config(page_title="Jobbmatchning", layout="wide")
st.title("💼 Jobbmatchning & Leadsanalys")

# --- Filuppladdning ---
st.sidebar.header("📂 Ladda upp filer")
jobs_file = st.sidebar.file_uploader("Ladda upp jobbdata (Excel)", type=["xlsx"])
org_file = st.sidebar.file_uploader("Ladda upp kundlista (Excel/CSV)", type=["xlsx", "csv"])

if jobs_file and org_file:
    # --- Läs in jobbdata ---
    jobs_excel = pd.ExcelFile(jobs_file)
    sheet_names = jobs_excel.sheet_names
    selected_sheet = st.sidebar.selectbox("Välj flik i jobbdata", sheet_names)
    jobs_df = jobs_excel.parse(selected_sheet)

    # --- Läs in kundlista ---
    if org_file.name.endswith("csv"):
        org_df = pd.read_csv(org_file, dtype=str)
    else:
        org_df = pd.read_excel(org_file, dtype=str)

    # --- Grundrensning ---
    jobs_df.columns = jobs_df.columns.str.lower()
    org_df.columns = org_df.columns.str.lower()

    # --- Filtreringspanel ---
    st.sidebar.header("🔍 Filtrera")
    selected_region = st.sidebar.multiselect("Region", options=jobs_df['region'].dropna().unique())
    selected_hours = st.sidebar.multiselect("Arbetstid", options=jobs_df['working_hours_type'].dropna().unique())
    job_title_query = st.sidebar.text_input("Jobbtitel (del av text)")
    require_phone = st.sidebar.checkbox("Endast med telefonnummer")
    exclude_union = st.sidebar.checkbox("Exkludera fackliga kontakter")
    only_non_customers = st.sidebar.checkbox("Visa endast nya leads")

    # --- Filtrering ---
    df = jobs_df.copy()
    if selected_region:
        df = df[df['region'].isin(selected_region)]
    if selected_hours:
        df = df[df['working_hours_type'].isin(selected_hours)]
    if job_title_query:
        df = df[df['headline'].str.contains(job_title_query, case=False, na=False)]
    if require_phone:
        df = df[df['description'].str.contains(r'\b\d{2,4}[-\s]?\d{5,}', na=False)]
    if exclude_union:
        df = df[~df['description'].str.contains("fack|unionen|saco|förbund", case=False, na=False)]

    # --- Matcha mot kundlista ---
    if 'employer_organization_number' in df.columns and 'orgnr' in org_df.columns:
        df['orgnr'] = df['employer_organization_number'].astype(str)
        org_df['orgnr'] = org_df['orgnr'].astype(str)
        df['kund'] = df['orgnr'].isin(org_df['orgnr'])
        if only_non_customers:
            df = df[~df['kund']]
    else:
        df['kund'] = False

    # --- Extrahera telefonnummer ---
    df['telefon'] = df['description'].str.extract(r'(\b\d{2,4}[-\s]?\d{5,})')

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
        label="🗃️ Ladda ner resultat som Excel",
        data=excel_bytes,
        file_name="filtrerat_resultat.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

else:
    st.info("Ladda upp både jobbdata och kundlista för att börja.")
