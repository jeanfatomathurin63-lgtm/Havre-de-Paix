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
    SKLEARN_AVAILABLE = True
except Exception:
    SKLEARN_AVAILABLE = False


# =========================
# CONFIGURATION
# =========================

APP_NAME = "Havre de Paix Systeme Management"
DB_NAME = "havre_de_paix_database.db"

Path("receipts").mkdir(exist_ok=True)
Path("exports").mkdir(exist_ok=True)

st.set_page_config(
    page_title=APP_NAME,
    page_icon="🏢",
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

def user_exists():
    conn = connect_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM users")
    count = cur.fetchone()[0]
    conn.close()
    return count > 0


def create_user(username, password):
    if not username.strip():
        return False, "Username is required."

    if not password.strip():
        return False, "Password is required."

    if len(password) < 6:
        return False, "Password must have at least 6 characters."

    conn = connect_db()
    cur = conn.cursor()

    try:
        cur.execute(
            "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
            (username.strip(), hash_password(password), datetime.now().isoformat())
        )
        conn.commit()
        conn.close()
        return True, "Account created successfully."
    except Exception as e:
        conn.close()
        return False, f"Error: {e}"


def authenticate(username, password):
    conn = connect_db()
    cur = conn.cursor()
    cur.execute("SELECT password_hash FROM users WHERE username = ?", (username.strip(),))
    row = cur.fetchone()
    conn.close()

    if not row:
        return False

    return row[0] == hash_password(password)


def login_page():
    st.markdown("<div class='big-title'>🏢 Havre de Paix Systeme Management</div>", unsafe_allow_html=True)
    st.markdown("<p class='subtitle'>Private business administration system</p>", unsafe_allow_html=True)

    col1, col2, col3 = st.columns([1, 1.2, 1])

    with col2:
        if not user_exists():
            st.subheader("Create your admin account")

            new_username = st.text_input("Create username")
            new_password = st.text_input("Create password", type="password")
            confirm_password = st.text_input("Confirm password", type="password")

            if st.button("Create my account", use_container_width=True):
                if new_password != confirm_password:
                    st.error("Passwords do not match.")
                else:
                    success, message = create_user(new_username, new_password)
                    if success:
                        st.success(message)
                        st.info("Now log in with your new account.")
                        st.rerun()
                    else:
                        st.error(message)

        else:
            st.subheader("Login")

            username = st.text_input("Username")
            password = st.text_input("Password", type="password")

            if st.button("Login", use_container_width=True):
                if authenticate(username, password):
                    st.session_state["logged_in"] = True
                    st.session_state["username"] = username
                    st.success("Login successful.")
                    st.rerun()
                else:
                    st.error("Incorrect username or password.")


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
    expenses = read_sql("SELECT expense_date AS date, amount, 'Expenses' AS type FROM expenses")
    revenues = read_sql("SELECT payment_date AS date, amount, 'Revenue' AS type FROM client_payments")
    salaries = read_sql("SELECT payment_date AS date, amount_paid AS amount, 'Salaries' AS type FROM employee_payments")

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
    text = text or ""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    store = lines[0] if lines else "Unknown store"

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
        category = "Food"
    elif "gas" in lower or "essence" in lower or "taxi" in lower:
        category = "Transport"
    elif "internet" in lower or "wifi" in lower:
        category = "Internet"
    elif "office" in lower or "bureau" in lower or "printer" in lower:
        category = "Material"
    else:
        category = "Other"

    return receipt_date, store, amount, category


def excel_download(sheets):
    output = io.BytesIO()

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for name, df in sheets.items():
            if df.empty:
                pd.DataFrame({"Message": ["No data"]}).to_excel(writer, sheet_name=name[:31], index=False)
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
    c1.metric("Money In", money(total_revenue))
    c2.metric("Expenses", money(total_expenses))
    c3.metric("Employee Payments", money(total_employee_paid))
    c4.metric("Net Profit", money(profit))

    st.divider()

    data = monthly_data()

    if data.empty:
        st.info("No data yet. Add expenses, clients, payments, and employees to see charts.")
    else:
        fig = px.bar(data, x="month", y="amount", color="type", barmode="group", title="Monthly Summary")
        st.plotly_chart(fig, use_container_width=True)

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Latest Expenses")
        df = read_sql("SELECT expense_date, category, description, amount FROM expenses ORDER BY id DESC LIMIT 5")
        st.dataframe(df, use_container_width=True, hide_index=True)

    with col2:
        st.subheader("Latest Client Payments")
        df = read_sql("""
        SELECT cp.payment_date, c.name AS client, cp.amount, cp.status
        FROM client_payments cp
        LEFT JOIN clients c ON cp.client_id = c.id
        ORDER BY cp.id DESC LIMIT 5
        """)
        st.dataframe(df, use_container_width=True, hide_index=True)


def expenses_page():
    st.markdown("<div class='big-title'>💸 Expenses</div>", unsafe_allow_html=True)

    with st.form("expense_form"):
        col1, col2, col3 = st.columns(3)

        expense_date = col1.date_input("Date", value=date.today())
        category = col2.selectbox("Category", ["Rent", "Internet", "Food", "Transport", "Material", "Salary", "Other"])
        amount = col3.number_input("Amount", min_value=0.0, step=1.0)

        description = st.text_input("Description")

        col4, col5 = st.columns(2)
        payment_method = col4.selectbox("Payment method", ["Cash", "Card", "Transfer", "Check", "Other"])
        supplier = col5.text_input("Supplier / Store")

        if st.form_submit_button("Add expense"):
            execute_sql("""
            INSERT INTO expenses 
            (expense_date, category, description, amount, payment_method, supplier, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (expense_date.isoformat(), category, description, amount, payment_method, supplier, datetime.now().isoformat()))

            st.success("Expense added.")
            st.rerun()

    st.subheader("Expenses list")

    df = read_sql("SELECT * FROM expenses ORDER BY id DESC")
    st.dataframe(df, use_container_width=True, hide_index=True)

    if not df.empty:
        st.subheader("Delete expense")

        selected_id = st.selectbox("Choose ID", df["id"].tolist())

        if st.button("Delete"):
            execute_sql("DELETE FROM expenses WHERE id = ?", (int(selected_id),))
            st.success("Expense deleted.")
            st.rerun()


def receipts_page():
    st.markdown("<div class='big-title'>🧾 Receipt Scanner</div>", unsafe_allow_html=True)

    if not OCR_AVAILABLE:
        st.warning("OCR is not available. Install pytesseract and tesseract-ocr.")

    uploaded = st.file_uploader("Upload receipt", type=["png", "jpg", "jpeg"])

    if uploaded:
        image = Image.open(uploaded)
        st.image(image, caption="Uploaded receipt", use_container_width=True)

        detected_text = ""

        if OCR_AVAILABLE:
            try:
                detected_text = pytesseract.image_to_string(image)
            except Exception as e:
                st.error(f"OCR error: {e}")

        st.subheader("Detected text")
        detected_text = st.text_area("OCR text", value=detected_text, height=200)

        receipt_date, store, amount, category = extract_receipt_info(detected_text)

        st.subheader("Information to save")

        with st.form("receipt_form"):
            col1, col2 = st.columns(2)

            receipt_date = col1.text_input("Date", value=receipt_date)
            store = col2.text_input("Store", value=store)

            col3, col4 = st.columns(2)

            amount = col3.number_input("Total amount", value=float(amount), min_value=0.0)
            category = col4.selectbox("Category", ["Food", "Transport", "Internet", "Material", "Rent", "Other"])

            save_as_expense = st.checkbox("Also add as expense", value=True)

            if st.form_submit_button("Save receipt"):
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
                    """, (receipt_date, category, "Expense from scanned receipt", amount, "Not specified", store, datetime.now().isoformat()))

                st.success("Receipt saved.")
                st.rerun()

    st.subheader("Saved receipts")
    df = read_sql("SELECT id, receipt_date, store_name, total_amount, category FROM receipts ORDER BY id DESC")
    st.dataframe(df, use_container_width=True, hide_index=True)


def clients_page():
    st.markdown("<div class='big-title'>👥 Clients and Payments</div>", unsafe_allow_html=True)

    tab1, tab2, tab3 = st.tabs(["Add client", "Client payment", "History"])

    with tab1:
        with st.form("client_form"):
            name = st.text_input("Client name")
            phone = st.text_input("Phone")
            email = st.text_input("Email")
            service = st.text_input("Service or product")

            if st.form_submit_button("Add client"):
                if not name.strip():
                    st.error("Client name is required.")
                else:
                    execute_sql("""
                    INSERT INTO clients (name, phone, email, service_product, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """, (name, phone, email, service, datetime.now().isoformat()))

                    st.success("Client added.")
                    st.rerun()

        df = read_sql("SELECT * FROM clients ORDER BY id DESC")
        st.dataframe(df, use_container_width=True, hide_index=True)

    with tab2:
        clients = read_sql("SELECT id, name FROM clients ORDER BY name")

        if clients.empty:
            st.warning("Add a client first.")
        else:
            options = {f"{row['name']} - ID {row['id']}": row["id"] for _, row in clients.iterrows()}

            with st.form("client_payment_form"):
                selected = st.selectbox("Client", list(options.keys()))
                payment_date = st.date_input("Payment date", value=date.today())
                amount = st.number_input("Amount paid", min_value=0.0, step=1.0)
                method = st.selectbox("Method", ["Cash", "Card", "Transfer", "Check", "Other"])
                status = st.selectbox("Status", ["Paid", "Partially paid", "Pending"])

                if st.form_submit_button("Add payment"):
                    execute_sql("""
                    INSERT INTO client_payments
                    (client_id, payment_date, amount, payment_method, status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """, (options[selected], payment_date.isoformat(), amount, method, status, datetime.now().isoformat()))

                    st.success("Payment added.")
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
    st.markdown("<div class='big-title'>🧑‍💼 Employees and Salaries</div>", unsafe_allow_html=True)

    tab1, tab2, tab3 = st.tabs(["Add employee", "Employee payment", "History"])

    with tab1:
        with st.form("employee_form"):
            name = st.text_input("Employee name")
            position = st.text_input("Position")
            payment_type = st.selectbox("Payment type", ["Fixed salary", "Hourly rate"])

            col1, col2 = st.columns(2)
            fixed_salary = col1.number_input("Fixed salary", min_value=0.0, step=10.0)
            hourly_rate = col2.number_input("Hourly rate", min_value=0.0, step=1.0)

            if st.form_submit_button("Add employee"):
                if not name.strip():
                    st.error("Employee name is required.")
                else:
                    execute_sql("""
                    INSERT INTO employees
                    (name, position, payment_type, fixed_salary, hourly_rate, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """, (name, position, payment_type, fixed_salary, hourly_rate, datetime.now().isoformat()))

                    st.success("Employee added.")
                    st.rerun()

        df = read_sql("SELECT * FROM employees ORDER BY id DESC")
        st.dataframe(df, use_container_width=True, hide_index=True)

    with tab2:
        employees = read_sql("SELECT * FROM employees ORDER BY name")

        if employees.empty:
            st.warning("Add an employee first.")
        else:
            options = {f"{row['name']} - {row['payment_type']} - ID {row['id']}": row for _, row in employees.iterrows()}

            with st.form("employee_payment_form"):
                selected = st.selectbox("Employee", list(options.keys()))
                emp = options[selected]

                payment_date = st.date_input("Payment date", value=date.today())
                hours = st.number_input("Hours worked", min_value=0.0, step=1.0)

                if emp["payment_type"] == "Hourly rate":
                    calculated = float(emp["hourly_rate"]) * hours
                else:
                    calculated = float(emp["fixed_salary"])

                amount_paid = st.number_input("Amount paid", value=float(calculated), min_value=0.0)
                status = st.selectbox("Status", ["Paid", "Not paid"])

                if st.form_submit_button("Add employee payment"):
                    execute_sql("""
                    INSERT INTO employee_payments
                    (employee_id, payment_date, hours_worked, amount_paid, status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """, (int(emp["id"]), payment_date.isoformat(), hours, amount_paid, status, datetime.now().isoformat()))

                    st.success("Employee payment added.")
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
    st.markdown("<div class='big-title'>🔮 Financial Predictions</div>", unsafe_allow_html=True)

    if not SKLEARN_AVAILABLE:
        st.error("Scikit-learn is not available.")
        return

    data = monthly_data()

    if data.empty:
        st.warning("Not enough data. Add revenue, expenses, and payments first.")
        return

    results = {}

    for target in ["Revenue", "Expenses", "Salaries"]:
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

    predicted_profit = results["Revenue"] - results["Expenses"] - results["Salaries"]

    c1, c2, c3, c4 = st.columns(4)

    c1.metric("Next month revenue", money(results["Revenue"]))
    c2.metric("Next month expenses", money(results["Expenses"]))
    c3.metric("Next month salaries", money(results["Salaries"]))
    c4.metric("Predicted profit", money(predicted_profit))

    fig = px.line(data, x="month", y="amount", color="type", markers=True, title="Financial History")
    st.plotly_chart(fig, use_container_width=True)

    st.info("Simple prediction with LinearRegression. Add more data to improve results.")


def reports_page():
    st.markdown("<div class='big-title'>📁 Excel Reports</div>", unsafe_allow_html=True)

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
        "Indicator": ["Revenue", "Expenses", "Employee payments", "Net profit"],
        "Amount": [total_revenue, total_expenses, total_employee_paid, profit]
    })

    excel_file = excel_download({
        "Summary": summary,
        "Expenses": expenses,
        "Clients": clients,
        "Client payments": client_payments,
        "Employees": employees,
        "Employee payments": employee_payments,
        "Receipts": receipts
    })

    st.download_button(
        "Download Excel report",
        data=excel_file,
        file_name="havre_de_paix_report.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True
    )

    st.dataframe(summary, use_container_width=True, hide_index=True)


def settings_page():
    st.markdown("<div class='big-title'>⚙️ Settings</div>", unsafe_allow_html=True)

    st.write("Application:", APP_NAME)
    st.write("Database:", DB_NAME)
    st.write("OCR available:", OCR_AVAILABLE)
    st.write("Scikit-learn available:", SKLEARN_AVAILABLE)

    st.warning("This application starts empty. All data must be added by you.")


# =========================
# MAIN
# =========================

def main():
    init_db()

    if "logged_in" not in st.session_state:
        st.session_state["logged_in"] = False

    if not st.session_state["logged_in"]:
        login_page()
        return

    with st.sidebar:
        st.title("🏢 Havre de Paix")
        st.caption("Systeme Management")
        st.write("User:", st.session_state.get("username", ""))

        page = st.radio(
            "Menu",
            [
                "Dashboard",
                "Expenses",
                "Receipt Scanner",
                "Clients and Payments",
                "Employees and Salaries",
                "Predictions",
                "Reports",
                "Settings"
            ]
        )

        if st.button("Logout"):
            st.session_state["logged_in"] = False
            st.rerun()

    if page == "Dashboard":
        dashboard_page()
    elif page == "Expenses":
        expenses_page()
    elif page == "Receipt Scanner":
        receipts_page()
    elif page == "Clients and Payments":
        clients_page()
    elif page == "Employees and Salaries":
        employees_page()
    elif page == "Predictions":
        predictions_page()
    elif page == "Reports":
        reports_page()
    elif page == "Settings":
        settings_page()


if __name__ == "__main__":
    main()
