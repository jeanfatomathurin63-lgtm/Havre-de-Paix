import os
import re
import io
import sqlite3
import hashlib
from datetime import datetime, date
from pathlib import Path

import pandas as pd
import streamlit as st
import plotly.express as px
from PIL import Image

try:
    import pytesseract
    OCR_AVAILABLE = True
except Exception:
    OCR_AVAILABLE = False

try:
    from sklearn.linear_model import LinearRegression
    import numpy as np
    SKLEARN_AVAILABLE = True
except Exception:
    SKLEARN_AVAILABLE = False


# =========================
# CONFIGURATION
# =========================

APP_NAME = "Simple Business Admin App"
DB_NAME = "database.db"

Path("receipts").mkdir(exist_ok=True)
Path("exports").mkdir(exist_ok=True)

st.set_page_config(
    page_title=APP_NAME,
    page_icon="💼",
    layout="wide"
)

st.markdown("""
<style>
.block-container {
    padding-top: 2rem;
}
.big-title {
    font-size: 34px;
    font-weight: 800;
}
.subtitle {
    color: #6b7280;
    font-size: 16px;
}
</style>
""", unsafe_allow_html=True)


# =========================
# DATABASE
# =========================

def connect_db():
    return sqlite3.connect(DB_NAME, check_same_thread=False)


def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()


def init_db():
    conn = connect_db()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password_hash TEXT,
        created_at TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS expenses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        expense_date TEXT,
        category TEXT,
        description TEXT,
        amount REAL,
        payment_method TEXT,
        supplier TEXT,
        created_at TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS clients (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        phone TEXT,
        email TEXT,
        service_product TEXT,
        created_at TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS client_payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_id INTEGER,
        payment_date TEXT,
        amount REAL,
        payment_method TEXT,
        status TEXT,
        created_at TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS employees (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        position TEXT,
        payment_type TEXT,
        fixed_salary REAL,
        hourly_rate REAL,
        created_at TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS employee_payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_id INTEGER,
        payment_date TEXT,
        hours_worked REAL,
        amount_paid REAL,
        status TEXT,
        created_at TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS receipts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        receipt_date TEXT,
        store_name TEXT,
        total_amount REAL,
        category TEXT,
        detected_text TEXT,
        image_path TEXT,
        created_at TEXT
    )
    """)

    conn.commit()
    conn.close()


def create_default_user():
    conn = connect_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM users")
    count = cur.fetchone()[0]

    if count == 0:
        cur.execute(
            "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
            ("admin", hash_password("admin123"), datetime.now().isoformat())
        )
        conn.commit()

    conn.close()


def insert_sample_data():
    conn = connect_db()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM expenses")
    expenses_count = cur.fetchone()[0]

    if expenses_count == 0:
        now = datetime.now().isoformat()

        expenses = [
            ("2026-01-05", "Loyer", "Paiement du local", 1200, "Virement", "Propriétaire", now),
            ("2026-01-12", "Internet", "Internet business", 95, "Carte", "Fournisseur Internet", now),
            ("2026-02-03", "Matériel", "Achat imprimante", 320, "Carte", "Best Office", now),
            ("2026-03-08", "Nourriture", "Repas équipe", 150, "Carte", "Restaurant", now),
        ]

        cur.executemany("""
        INSERT INTO expenses 
        (expense_date, category, description, amount, payment_method, supplier, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """, expenses)

        clients = [
            ("Jean Client", "514-000-1111", "jean@example.com", "Consultation administrative", now),
            ("Marie Client", "514-000-2222", "marie@example.com", "Service mensuel", now),
        ]

        cur.executemany("""
        INSERT INTO clients (name, phone, email, service_product, created_at)
        VALUES (?, ?, ?, ?, ?)
        """, clients)

        payments = [
            (1, "2026-01-20", 800, "Virement", "payé", now),
            (2, "2026-02-10", 1200, "Carte", "payé", now),
            (1, "2026-03-15", 950, "Virement", "payé", now),
        ]

        cur.executemany("""
        INSERT INTO client_payments
        (client_id, payment_date, amount, payment_method, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """, payments)

        employees = [
            ("Natacha Bernard", "Assistante administrative", "Salaire fixe", 2500, 0, now),
            ("Frantz Global", "Technicien support", "Taux horaire", 0, 25, now),
        ]

        cur.executemany("""
        INSERT INTO employees
        (name, position, payment_type, fixed_salary, hourly_rate, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """, employees)

        emp_payments = [
            (1, "2026-01-30", 0, 2500, "payé", now),
            (2, "2026-02-28", 40, 1000, "payé", now),
        ]

        cur.executemany("""
        INSERT INTO employee_payments
        (employee_id, payment_date, hours_worked, amount_paid, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """, emp_payments)

        conn.commit()

    conn.close()


def read_sql(query, params=None):
    conn = connect_db()
    try:
        df = pd.read_sql_query(query, conn, params=params or [])
    except Exception as e:
        st.error(f"Erreur SQL : {e}")
        df = pd.DataFrame()
    conn.close()
    return df


def execute_sql(query, params=None):
    conn = connect_db()
    cur = conn.cursor()
    try:
        cur.execute(query, params or [])
        conn.commit()
        success = True
    except Exception as e:
        st.error(f"Erreur base de données : {e}")
        success = False
    conn.close()
    return success


# =========================
# AUTHENTICATION
# =========================

def authenticate(username, password):
    conn = connect_db()
    cur = conn.cursor()
    cur.execute("SELECT password_hash FROM users WHERE username = ?", (username,))
    row = cur.fetchone()
    conn.close()

    if not row:
        return False

    return row[0] == hash_password(password)


def login_page():
    st.markdown("<div class='big-title'>💼 Simple Business Admin App</div>", unsafe_allow_html=True)
    st.markdown("<p class='subtitle'>Application simple pour gérer une petite entreprise</p>", unsafe_allow_html=True)

    col1, col2, col3 = st.columns([1, 1.2, 1])

    with col2:
        st.subheader("Connexion")

        username = st.text_input("Utilisateur", value="admin")
        password = st.text_input("Mot de passe", type="password", value="admin123")

        if st.button("Se connecter", use_container_width=True):
            if authenticate(username, password):
                st.session_state["logged_in"] = True
                st.session_state["username"] = username
                st.success("Connexion réussie")
                st.rerun()
            else:
                st.error("Utilisateur ou mot de passe incorrect")

        st.info("Login test : admin / admin123")


# =========================
# HELPERS
# =========================

def money(value):
    try:
        return f"${float(value):,.2f}"
    except Exception:
        return "$0.00"


def get_totals():
    expenses = read_sql("SELECT * FROM expenses")
    client_payments = read_sql("SELECT * FROM client_payments")
    employee_payments = read_sql("SELECT * FROM employee_payments")

    total_expenses = expenses["amount"].sum() if not expenses.empty else 0
    total_revenue = client_payments["amount"].sum() if not client_payments.empty else 0
    total_employee_paid = employee_payments["amount_paid"].sum() if not employee_payments.empty else 0
    profit = total_revenue - total_expenses - total_employee_paid

    return total_revenue, total_expenses, total_employee_paid, profit


def monthly_data():
    expenses = read_sql("SELECT expense_date AS date, amount, 'Dépenses' AS type FROM expenses")
    revenues = read_sql("SELECT payment_date AS date, amount, 'Revenus' AS type FROM client_payments")
    salaries = read_sql("SELECT payment_date AS date, amount_paid AS amount, 'Salaires' AS type FROM employee_payments")

    frames = []

    for df in [expenses, revenues, salaries]:
        if not df.empty:
            frames.append(df)

    if not frames:
        return pd.DataFrame()

    data = pd.concat(frames)
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    data = data.dropna(subset=["date"])
    data["month"] = data["date"].dt.to_period("M").astype(str)

    return data.groupby(["month", "type"], as_index=False)["amount"].sum()


def extract_receipt_info(text):
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    store = lines[0] if lines else "Magasin inconnu"

    date_match = re.search(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{2,4}", text)
    receipt_date = date_match.group(0) if date_match else date.today().isoformat()

    amounts = re.findall(r"\d+[.,]\d{2}", text)
    amount = 0.0

    if amounts:
        try:
            amount = max([float(a.replace(",", ".")) for a in amounts])
        except Exception:
            amount = 0.0

    lower = text.lower()

    if "restaurant" in lower or "food" in lower or "repas" in lower:
        category = "Nourriture"
    elif "gas" in lower or "essence" in lower or "taxi" in lower:
        category = "Transport"
    elif "internet" in lower or "wifi" in lower:
        category = "Internet"
    elif "office" in lower or "bureau" in lower or "printer" in lower:
        category = "Matériel"
    else:
        category = "Autre"

    return receipt_date, store, amount, category


def excel_download(sheets):
    output = io.BytesIO()

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for name, df in sheets.items():
            if df.empty:
                pd.DataFrame({"Message": ["Aucune donnée"]}).to_excel(writer, sheet_name=name[:31], index=False)
            else:
                df.to_excel(writer, sheet_name=name[:31], index=False)

    output.seek(0)
    return output.getvalue()


# =========================
# PAGES
# =========================

def dashboard_page():
    st.markdown("<div class='big-title'>📊 Dashboard</div>", unsafe_allow_html=True)

    total_revenue, total_expenses, total_employee_paid, profit = get_totals()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Argent entré", money(total_revenue))
    c2.metric("Dépenses", money(total_expenses))
    c3.metric("Paiements employés", money(total_employee_paid))
    c4.metric("Profit net", money(profit))

    st.divider()

    data = monthly_data()

    if data.empty:
        st.info("Aucune donnée pour afficher les graphiques.")
    else:
        fig = px.bar(data, x="month", y="amount", color="type", barmode="group", title="Résumé mensuel")
        st.plotly_chart(fig, use_container_width=True)

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Dernières dépenses")
        df = read_sql("SELECT expense_date, category, description, amount FROM expenses ORDER BY id DESC LIMIT 5")
        st.dataframe(df, use_container_width=True, hide_index=True)

    with col2:
        st.subheader("Derniers paiements clients")
        df = read_sql("""
        SELECT cp.payment_date, c.name AS client, cp.amount, cp.status
        FROM client_payments cp
        LEFT JOIN clients c ON cp.client_id = c.id
        ORDER BY cp.id DESC LIMIT 5
        """)
        st.dataframe(df, use_container_width=True, hide_index=True)


def expenses_page():
    st.markdown("<div class='big-title'>💸 Dépenses</div>", unsafe_allow_html=True)

    with st.form("expense_form"):
        col1, col2, col3 = st.columns(3)

        expense_date = col1.date_input("Date", value=date.today())
        category = col2.selectbox("Catégorie", ["Loyer", "Internet", "Nourriture", "Transport", "Matériel", "Salaire", "Autre"])
        amount = col3.number_input("Montant", min_value=0.0, step=1.0)

        description = st.text_input("Description")

        col4, col5 = st.columns(2)
        payment_method = col4.selectbox("Méthode paiement", ["Cash", "Carte", "Virement", "Chèque", "Autre"])
        supplier = col5.text_input("Fournisseur / magasin")

        if st.form_submit_button("Ajouter dépense"):
            execute_sql("""
            INSERT INTO expenses 
            (expense_date, category, description, amount, payment_method, supplier, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (expense_date.isoformat(), category, description, amount, payment_method, supplier, datetime.now().isoformat()))

            st.success("Dépense ajoutée")
            st.rerun()

    st.subheader("Liste des dépenses")

    df = read_sql("SELECT * FROM expenses ORDER BY id DESC")
    st.dataframe(df, use_container_width=True, hide_index=True)

    if not df.empty:
        st.subheader("Supprimer une dépense")

        selected_id = st.selectbox("Choisir ID", df["id"].tolist())

        if st.button("Supprimer"):
            execute_sql("DELETE FROM expenses WHERE id = ?", (int(selected_id),))
            st.success("Dépense supprimée")
            st.rerun()


def receipts_page():
    st.markdown("<div class='big-title'>🧾 Scanner reçu</div>", unsafe_allow_html=True)

    if not OCR_AVAILABLE:
        st.warning("OCR non disponible. Installe pytesseract et tesseract-ocr.")

    uploaded = st.file_uploader("Uploader un reçu", type=["png", "jpg", "jpeg"])

    if uploaded:
        image = Image.open(uploaded)
        st.image(image, caption="Reçu uploadé", use_container_width=True)

        detected_text = ""

        if OCR_AVAILABLE:
            try:
                detected_text = pytesseract.image_to_string(image)
            except Exception as e:
                st.error(f"Erreur OCR : {e}")

        st.subheader("Texte détecté")
        detected_text = st.text_area("Texte OCR", value=detected_text, height=200)

        receipt_date, store, amount, category = extract_receipt_info(detected_text)

        st.subheader("Informations à sauvegarder")

        with st.form("receipt_form"):
            col1, col2 = st.columns(2)

            receipt_date = col1.text_input("Date", value=receipt_date)
            store = col2.text_input("Magasin", value=store)

            col3, col4 = st.columns(2)

            amount = col3.number_input("Montant total", value=float(amount), min_value=0.0)
            category = col4.selectbox("Catégorie", ["Nourriture", "Transport", "Internet", "Matériel", "Loyer", "Autre"])

            save_as_expense = st.checkbox("Ajouter aussi comme dépense", value=True)

            if st.form_submit_button("Sauvegarder reçu"):
                image_path = f"receipts/receipt_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                image.save(image_path)

                execute_sql("""
                INSERT INTO receipts 
                (receipt_date, store_name, total_amount, category, detected_text, image_path, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (receipt_date, store, amount, category, detected_text, image_path, datetime.now().isoformat()))

                if save_as_expense:
                    execute_sql("""
                    INSERT INTO expenses
                    (expense_date, category, description, amount, payment_method, supplier, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (receipt_date, category, "Dépense depuis reçu scanné", amount, "Non précisé", store, datetime.now().isoformat()))

                st.success("Reçu sauvegardé")
                st.rerun()

    st.subheader("Reçus sauvegardés")
    df = read_sql("SELECT id, receipt_date, store_name, total_amount, category FROM receipts ORDER BY id DESC")
    st.dataframe(df, use_container_width=True, hide_index=True)


def clients_page():
    st.markdown("<div class='big-title'>👥 Clients et paiements</div>", unsafe_allow_html=True)

    tab1, tab2, tab3 = st.tabs(["Ajouter client", "Paiement client", "Historique"])

    with tab1:
        with st.form("client_form"):
            name = st.text_input("Nom client")
            phone = st.text_input("Téléphone")
            email = st.text_input("Email")
            service = st.text_input("Service ou produit")

            if st.form_submit_button("Ajouter client"):
                execute_sql("""
                INSERT INTO clients (name, phone, email, service_product, created_at)
                VALUES (?, ?, ?, ?, ?)
                """, (name, phone, email, service, datetime.now().isoformat()))

                st.success("Client ajouté")
                st.rerun()

        df = read_sql("SELECT * FROM clients ORDER BY id DESC")
        st.dataframe(df, use_container_width=True, hide_index=True)

    with tab2:
        clients = read_sql("SELECT id, name FROM clients ORDER BY name")

        if clients.empty:
            st.warning("Ajoute un client d'abord.")
        else:
            options = {f"{row['name']} - ID {row['id']}": row["id"] for _, row in clients.iterrows()}

            with st.form("client_payment_form"):
                selected = st.selectbox("Client", list(options.keys()))
                payment_date = st.date_input("Date paiement", value=date.today())
                amount = st.number_input("Montant payé", min_value=0.0, step=1.0)
                method = st.selectbox("Méthode", ["Cash", "Carte", "Virement", "Chèque", "Autre"])
                status = st.selectbox("Statut", ["payé", "partiellement payé", "en attente"])

                if st.form_submit_button("Ajouter paiement"):
                    execute_sql("""
                    INSERT INTO client_payments
                    (client_id, payment_date, amount, payment_method, status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """, (options[selected], payment_date.isoformat(), amount, method, status, datetime.now().isoformat()))

                    st.success("Paiement ajouté")
                    st.rerun()

    with tab3:
        df = read_sql("""
        SELECT cp.id, cp.payment_date, c.name AS client, cp.amount, cp.payment_method, cp.status
        FROM client_payments cp
        LEFT JOIN clients c ON cp.client_id = c.id
        ORDER BY cp.id DESC
        """)

        st.dataframe(df, use_container_width=True, hide_index=True)


def employees_page():
    st.markdown("<div class='big-title'>🧑‍💼 Employés et salaires</div>", unsafe_allow_html=True)

    tab1, tab2, tab3 = st.tabs(["Ajouter employé", "Paiement employé", "Historique"])

    with tab1:
        with st.form("employee_form"):
            name = st.text_input("Nom employé")
            position = st.text_input("Poste")
            payment_type = st.selectbox("Type paiement", ["Salaire fixe", "Taux horaire"])

            col1, col2 = st.columns(2)
            fixed_salary = col1.number_input("Salaire fixe", min_value=0.0, step=10.0)
            hourly_rate = col2.number_input("Taux horaire", min_value=0.0, step=1.0)

            if st.form_submit_button("Ajouter employé"):
                execute_sql("""
                INSERT INTO employees
                (name, position, payment_type, fixed_salary, hourly_rate, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """, (name, position, payment_type, fixed_salary, hourly_rate, datetime.now().isoformat()))

                st.success("Employé ajouté")
                st.rerun()

        df = read_sql("SELECT * FROM employees ORDER BY id DESC")
        st.dataframe(df, use_container_width=True, hide_index=True)

    with tab2:
        employees = read_sql("SELECT * FROM employees ORDER BY name")

        if employees.empty:
            st.warning("Ajoute un employé d'abord.")
        else:
            options = {f"{row['name']} - {row['payment_type']} - ID {row['id']}": row for _, row in employees.iterrows()}

            with st.form("employee_payment_form"):
                selected = st.selectbox("Employé", list(options.keys()))
                emp = options[selected]

                payment_date = st.date_input("Date paiement", value=date.today())
                hours = st.number_input("Heures travaillées", min_value=0.0, step=1.0)

                if emp["payment_type"] == "Taux horaire":
                    calculated = float(emp["hourly_rate"]) * hours
                else:
                    calculated = float(emp["fixed_salary"])

                amount_paid = st.number_input("Montant payé", value=float(calculated), min_value=0.0)
                status = st.selectbox("Statut", ["payé", "non payé"])

                if st.form_submit_button("Ajouter paiement employé"):
                    execute_sql("""
                    INSERT INTO employee_payments
                    (employee_id, payment_date, hours_worked, amount_paid, status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """, (int(emp["id"]), payment_date.isoformat(), hours, amount_paid, status, datetime.now().isoformat()))

                    st.success("Paiement employé ajouté")
                    st.rerun()

    with tab3:
        df = read_sql("""
        SELECT ep.id, ep.payment_date, e.name AS employee, ep.hours_worked, ep.amount_paid, ep.status
        FROM employee_payments ep
        LEFT JOIN employees e ON ep.employee_id = e.id
        ORDER BY ep.id DESC
        """)

        st.dataframe(df, use_container_width=True, hide_index=True)


def predictions_page():
    st.markdown("<div class='big-title'>🔮 Prédictions financières</div>", unsafe_allow_html=True)

    if not SKLEARN_AVAILABLE:
        st.error("Scikit-learn n'est pas disponible.")
        return

    data = monthly_data()

    if data.empty:
        st.warning("Pas assez de données.")
        return

    results = {}

    for target in ["Revenus", "Dépenses", "Salaires"]:
        df = data[data["type"] == target].copy()

        if len(df) >= 2:
            df = df.sort_values("month")
            df["x"] = range(1, len(df) + 1)

            model = LinearRegression()
            model.fit(df[["x"]], df["amount"])

            pred = model.predict([[len(df) + 1]])[0]
            results[target] = max(0, float(pred))
        else:
            results[target] = 0

    predicted_profit = results["Revenus"] - results["Dépenses"] - results["Salaires"]

    c1, c2, c3, c4 = st.columns(4)

    c1.metric("Revenus prochain mois", money(results["Revenus"]))
    c2.metric("Dépenses prochain mois", money(results["Dépenses"]))
    c3.metric("Salaires prochain mois", money(results["Salaires"]))
    c4.metric("Profit prévu", money(predicted_profit))

    fig = px.line(data, x="month", y="amount", color="type", markers=True, title="Historique financier")
    st.plotly_chart(fig, use_container_width=True)

    st.info("Prédiction simple avec LinearRegression. Plus tu ajoutes de données, plus le résultat sera utile.")


def reports_page():
    st.markdown("<div class='big-title'>📁 Rapports Excel</div>", unsafe_allow_html=True)

    expenses = read_sql("SELECT * FROM expenses")
    clients = read_sql("SELECT * FROM clients")
    client_payments = read_sql("""
    SELECT cp.id, cp.payment_date, c.name AS client, cp.amount, cp.payment_method, cp.status
    FROM client_payments cp
    LEFT JOIN clients c ON cp.client_id = c.id
    """)
    employees = read_sql("SELECT * FROM employees")
    employee_payments = read_sql("""
    SELECT ep.id, ep.payment_date, e.name AS employee, ep.hours_worked, ep.amount_paid, ep.status
    FROM employee_payments ep
    LEFT JOIN employees e ON ep.employee_id = e.id
    """)
    receipts = read_sql("SELECT * FROM receipts")

    total_revenue, total_expenses, total_employee_paid, profit = get_totals()

    summary = pd.DataFrame({
        "Indicateur": ["Revenus", "Dépenses", "Paiements employés", "Profit net"],
        "Montant": [total_revenue, total_expenses, total_employee_paid, profit]
    })

    excel_file = excel_download({
        "Résumé": summary,
        "Dépenses": expenses,
        "Clients": clients,
        "Paiements clients": client_payments,
        "Employés": employees,
        "Paiements employés": employee_payments,
        "Reçus": receipts
    })

    st.download_button(
        "Télécharger rapport Excel",
        data=excel_file,
        file_name="rapport_business.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True
    )

    st.dataframe(summary, use_container_width=True, hide_index=True)


def settings_page():
    st.markdown("<div class='big-title'>⚙️ Paramètres</div>", unsafe_allow_html=True)

    st.write("Base de données :", DB_NAME)
    st.write("OCR disponible :", OCR_AVAILABLE)
    st.write("Scikit-learn disponible :", SKLEARN_AVAILABLE)

    if st.button("Ajouter données exemples"):
        insert_sample_data()
        st.success("Données exemples ajoutées si la base était vide.")
        st.rerun()


# =========================
# MAIN
# =========================

def main():
    init_db()
    create_default_user()
    insert_sample_data()

    if "logged_in" not in st.session_state:
        st.session_state["logged_in"] = False

    if not st.session_state["logged_in"]:
        login_page()
        return

    with st.sidebar:
        st.title("💼 Admin App")
        st.write("Utilisateur :", st.session_state.get("username", "admin"))

        page = st.radio(
            "Menu",
            [
                "Dashboard",
                "Dépenses",
                "Scanner reçu",
                "Clients et paiements",
                "Employés et salaires",
                "Prédictions",
                "Rapports",
                "Paramètres"
            ]
        )

        if st.button("Déconnexion"):
            st.session_state["logged_in"] = False
            st.rerun()

    if page == "Dashboard":
        dashboard_page()
    elif page == "Dépenses":
        expenses_page()
    elif page == "Scanner reçu":
        receipts_page()
    elif page == "Clients et paiements":
        clients_page()
    elif page == "Employés et salaires":
        employees_page()
    elif page == "Prédictions":
        predictions_page()
    elif page == "Rapports":
        reports_page()
    elif page == "Paramètres":
        settings_page()


if __name__ == "__main__":
    main()
