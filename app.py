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
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
header {visibility: hidden;}
[data-testid="stToolbar"] {display: none !important;}
[data-testid="stDecoration"] {display: none !important;}
[data-testid="stStatusWidget"] {display: none !important;}
.auth-card {
    background: #ffffff;
    padding: 1.5rem;
    border-radius: 18px;
    border: 1px solid #e5e7eb;
    box-shadow: 0 8px 24px rgba(15, 23, 42, 0.08);
}
.info-box {
    background: #f8fafc;
    padding: 1rem;
    border-radius: 14px;
    border-left: 5px solid #2563eb;
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
        role TEXT DEFAULT 'staff',
        created_at TEXT
    )
    """)

    # Migration for older databases already created without user roles
    try:
        cur.execute("ALTER TABLE users ADD COLUMN role TEXT DEFAULT 'staff'")
    except sqlite3.OperationalError:
        pass

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


    cur.execute("""
    CREATE TABLE IF NOT EXISTS business_plans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        plan_date TEXT,
        business_name TEXT,
        current_cash REAL,
        monthly_revenue_goal REAL,
        monthly_expense_budget REAL,
        desired_profit_margin REAL,
        monthly_saving_goal REAL,
        investment_goal REAL,
        notes TEXT,
        created_at TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS savings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        saving_date TEXT,
        reason TEXT,
        amount REAL,
        target TEXT,
        created_at TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS investments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        investment_date TEXT,
        investment_type TEXT,
        amount REAL,
        expected_return REAL,
        status TEXT,
        notes TEXT,
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


def create_user(username, password, role="staff"):
    if not username.strip():
        return False, "Username is required."

    if not password.strip():
        return False, "Password is required."

    if len(password) < 6:
        return False, "Password must have at least 6 characters."

    role = role if role in ["admin", "manager", "staff"] else "staff"

    conn = connect_db()
    cur = conn.cursor()

    try:
        cur.execute(
            "INSERT INTO users (username, password_hash, role, created_at) VALUES (?, ?, ?, ?)",
            (username.strip(), hash_password(password), role, datetime.now().isoformat())
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
    cur.execute("SELECT password_hash, role FROM users WHERE username = ?", (username.strip(),))
    row = cur.fetchone()
    conn.close()

    if not row:
        return False, None

    if row[0] == hash_password(password):
        return True, row[1] or "staff"

    return False, None


def get_user_role(username):
    conn = connect_db()
    cur = conn.cursor()
    cur.execute("SELECT role FROM users WHERE username = ?", (username.strip(),))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else "staff"


def login_page():
    st.markdown("<div class='big-title'>🏢 Havre de Paix Systeme Management</div>", unsafe_allow_html=True)
    st.markdown("<p class='subtitle'>Private Login / Signup for your business web app</p>", unsafe_allow_html=True)

    left, center, right = st.columns([1, 1.25, 1])

    with center:
        st.markdown("<div class='auth-card'>", unsafe_allow_html=True)
        tab_login, tab_signup = st.tabs(["🔐 Login", "📝 Signup"])

        with tab_login:
            st.subheader("Welcome back")
            username = st.text_input("Username", key="login_username")
            password = st.text_input("Password", type="password", key="login_password")

            if st.button("Login", use_container_width=True):
                ok, role = authenticate(username, password)
                if ok:
                    st.session_state["logged_in"] = True
                    st.session_state["username"] = username.strip()
                    st.session_state["role"] = role
                    st.success("Login successful.")
                    st.rerun()
                else:
                    st.error("Incorrect username or password.")

        with tab_signup:
            st.subheader("Create a new account")
            st.caption("First account becomes Admin. Other new accounts become Staff automatically.")
            new_username = st.text_input("Create username", key="signup_username")
            new_password = st.text_input("Create password", type="password", key="signup_password")
            confirm_password = st.text_input("Confirm password", type="password", key="signup_confirm")

            if st.button("Create account", use_container_width=True):
                if new_password != confirm_password:
                    st.error("Passwords do not match.")
                else:
                    role = "admin" if not user_exists() else "staff"
                    success, message = create_user(new_username, new_password, role=role)
                    if success:
                        st.success(message)
                        st.info(f"Account created as {role}. Go to Login and connect.")
                    else:
                        st.error(message)
        st.markdown("</div>", unsafe_allow_html=True)


def admin_users_page():
    st.markdown("<div class='big-title'>👑 Admin Users</div>", unsafe_allow_html=True)
    st.info("Use this page to create access for your wife or employees. Staff users cannot see Admin Users, Settings, Reports, or technical management pages.")

    with st.form("admin_create_user_form"):
        col1, col2, col3 = st.columns(3)
        username = col1.text_input("New username")
        password = col2.text_input("New password", type="password")
        role = col3.selectbox("Role", ["staff", "manager", "admin"])
        submitted = st.form_submit_button("Create user")
        if submitted:
            success, message = create_user(username, password, role=role)
            if success:
                st.success(message)
                st.rerun()
            else:
                st.error(message)

    df = read_sql("SELECT id, username, role, created_at FROM users ORDER BY id DESC")
    st.dataframe(df, use_container_width=True, hide_index=True)

    if not df.empty:
        st.subheader("Change user role")
        user_options = {f"{row['username']} - {row['role']} - ID {row['id']}": row for _, row in df.iterrows()}
        selected = st.selectbox("Choose user", list(user_options.keys()))
        new_role = st.selectbox("New role", ["staff", "manager", "admin"], key="change_role")
        if st.button("Update role"):
            user_id = int(user_options[selected]["id"])
            execute_sql("UPDATE users SET role = ? WHERE id = ?", (new_role, user_id))
            st.success("Role updated.")
            st.rerun()

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
    st.caption("Add clients, record every payment they make to you, and see exactly how much each client has paid.")

    payments_summary = read_sql("""
    SELECT 
        c.id AS client_id,
        c.name AS client,
        c.phone,
        c.email,
        c.service_product,
        COALESCE(SUM(cp.amount), 0) AS total_paid,
        COUNT(cp.id) AS number_of_payments,
        MAX(cp.payment_date) AS last_payment_date
    FROM clients c
    LEFT JOIN client_payments cp ON cp.client_id = c.id
    GROUP BY c.id, c.name, c.phone, c.email, c.service_product
    ORDER BY total_paid DESC, c.name ASC
    """)

    all_payments = read_sql("""
    SELECT cp.id, cp.payment_date, c.name AS client, cp.amount, cp.payment_method, cp.status
    FROM client_payments cp
    LEFT JOIN clients c ON cp.client_id = c.id
    ORDER BY cp.payment_date DESC, cp.id DESC
    """)

    total_client_money = payments_summary["total_paid"].sum() if not payments_summary.empty else 0
    total_clients = len(payments_summary) if not payments_summary.empty else 0
    total_payment_count = payments_summary["number_of_payments"].sum() if not payments_summary.empty else 0

    c1, c2, c3 = st.columns(3)
    c1.metric("Total money received from clients", money(total_client_money))
    c2.metric("Total clients", total_clients)
    c3.metric("Number of client payments", int(total_payment_count))

    tab1, tab2, tab3, tab4 = st.tabs([
        "➕ Add client",
        "💰 Add client payment",
        "📊 How much each client paid me",
        "📜 Payment history"
    ])

    with tab1:
        st.subheader("Add a new client")
        with st.form("client_form"):
            name = st.text_input("Client name")
            phone = st.text_input("Phone")
            email = st.text_input("Email")
            service = st.text_input("Service or product")

            if st.form_submit_button("Save client", use_container_width=True):
                if not name.strip():
                    st.error("Client name is required.")
                else:
                    execute_sql("""
                    INSERT INTO clients (name, phone, email, service_product, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """, (name.strip(), phone.strip(), email.strip(), service.strip(), datetime.now().isoformat()))

                    st.success("Client saved successfully.")
                    st.rerun()

        st.subheader("Client list")
        clients_df = read_sql("SELECT id, name, phone, email, service_product, created_at FROM clients ORDER BY id DESC")
        st.dataframe(clients_df, use_container_width=True, hide_index=True)

    with tab2:
        st.subheader("Record money paid by a client")
        clients = read_sql("SELECT id, name, service_product FROM clients ORDER BY name")

        if clients.empty:
            st.warning("Add a client first before recording a payment.")
        else:
            options = {
                f"{row['name']} | {row['service_product'] or 'No service'} | ID {row['id']}": row["id"]
                for _, row in clients.iterrows()
            }

            with st.form("client_payment_form"):
                selected = st.selectbox("Choose client", list(options.keys()))
                col1, col2 = st.columns(2)
                payment_date = col1.date_input("Payment date", value=date.today())
                amount = col2.number_input("Amount the client paid you", min_value=0.0, step=1.0)

                col3, col4 = st.columns(2)
                method = col3.selectbox("Payment method", ["Cash", "Card", "Transfer", "Check", "Other"])
                status = col4.selectbox("Status", ["Paid", "Partially paid", "Pending"])

                if st.form_submit_button("Save client payment", use_container_width=True):
                    if amount <= 0:
                        st.error("Please enter an amount greater than 0.")
                    else:
                        execute_sql("""
                        INSERT INTO client_payments
                        (client_id, payment_date, amount, payment_method, status, created_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """, (options[selected], payment_date.isoformat(), amount, method, status, datetime.now().isoformat()))

                        st.success("Client payment saved. This money is now counted as revenue.")
                        st.rerun()

    with tab3:
        st.subheader("How much each client paid me")
        if payments_summary.empty:
            st.info("No client payment data yet.")
        else:
            st.dataframe(payments_summary, use_container_width=True, hide_index=True)

            chart_df = payments_summary[payments_summary["total_paid"] > 0].copy()
            if not chart_df.empty:
                fig = px.bar(
                    chart_df,
                    x="client",
                    y="total_paid",
                    text="total_paid",
                    title="Total paid by each client"
                )
                fig.update_traces(texttemplate="$%{text:,.2f}", textposition="outside")
                fig.update_layout(yaxis_title="Total paid", xaxis_title="Client")
                st.plotly_chart(fig, use_container_width=True)

    with tab4:
        st.subheader("All client payment history")
        st.dataframe(all_payments, use_container_width=True, hide_index=True)

        if not all_payments.empty:
            st.subheader("Delete a client payment")
            selected_id = st.selectbox("Choose payment ID to delete", all_payments["id"].tolist(), key="delete_client_payment_id")
            if st.button("Delete selected client payment"):
                execute_sql("DELETE FROM client_payments WHERE id = ?", (int(selected_id),))
                st.success("Client payment deleted.")
                st.rerun()


def employees_page():
    st.markdown("<div class='big-title'>🧑‍💼 Employees and Payments</div>", unsafe_allow_html=True)
    st.caption("Add employees, record every payment you make to them, and see exactly how much you paid each employee.")

    employee_summary = read_sql("""
    SELECT 
        e.id AS employee_id,
        e.name AS employee,
        e.position,
        e.payment_type,
        e.fixed_salary,
        e.hourly_rate,
        COALESCE(SUM(ep.amount_paid), 0) AS total_paid,
        COALESCE(SUM(ep.hours_worked), 0) AS total_hours,
        COUNT(ep.id) AS number_of_payments,
        MAX(ep.payment_date) AS last_payment_date
    FROM employees e
    LEFT JOIN employee_payments ep ON ep.employee_id = e.id
    GROUP BY e.id, e.name, e.position, e.payment_type, e.fixed_salary, e.hourly_rate
    ORDER BY total_paid DESC, e.name ASC
    """)

    payment_history = read_sql("""
    SELECT ep.id, ep.payment_date, e.name AS employee, e.position, ep.hours_worked, ep.amount_paid, ep.status
    FROM employee_payments ep
    LEFT JOIN employees e ON ep.employee_id = e.id
    ORDER BY ep.payment_date DESC, ep.id DESC
    """)

    total_employee_paid = employee_summary["total_paid"].sum() if not employee_summary.empty else 0
    total_employees = len(employee_summary) if not employee_summary.empty else 0
    total_payments = employee_summary["number_of_payments"].sum() if not employee_summary.empty else 0

    c1, c2, c3 = st.columns(3)
    c1.metric("Total paid to employees", money(total_employee_paid))
    c2.metric("Total employees", total_employees)
    c3.metric("Number of salary payments", int(total_payments))

    tab1, tab2, tab3, tab4 = st.tabs([
        "➕ Add employee",
        "💵 Pay employee",
        "📊 How much I paid each employee",
        "📜 Salary payment history"
    ])

    with tab1:
        st.subheader("Add a new employee")
        with st.form("employee_form"):
            name = st.text_input("Employee name")
            position = st.text_input("Position")
            payment_type = st.selectbox("Payment type", ["Fixed salary", "Hourly rate"])

            col1, col2 = st.columns(2)
            fixed_salary = col1.number_input("Fixed salary", min_value=0.0, step=10.0)
            hourly_rate = col2.number_input("Hourly rate", min_value=0.0, step=1.0)

            if st.form_submit_button("Save employee", use_container_width=True):
                if not name.strip():
                    st.error("Employee name is required.")
                else:
                    execute_sql("""
                    INSERT INTO employees
                    (name, position, payment_type, fixed_salary, hourly_rate, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """, (name.strip(), position.strip(), payment_type, fixed_salary, hourly_rate, datetime.now().isoformat()))

                    st.success("Employee saved successfully.")
                    st.rerun()

        st.subheader("Employee list")
        employees_df = read_sql("SELECT * FROM employees ORDER BY id DESC")
        st.dataframe(employees_df, use_container_width=True, hide_index=True)

    with tab2:
        st.subheader("Record payment made to an employee")
        employees = read_sql("SELECT * FROM employees ORDER BY name")

        if employees.empty:
            st.warning("Add an employee first before recording a payment.")
        else:
            options = {
                f"{row['name']} | {row['payment_type']} | ID {row['id']}": row
                for _, row in employees.iterrows()
            }

            with st.form("employee_payment_form"):
                selected = st.selectbox("Choose employee", list(options.keys()))
                emp = options[selected]

                col1, col2 = st.columns(2)
                payment_date = col1.date_input("Payment date", value=date.today())
                hours = col2.number_input("Hours worked", min_value=0.0, step=1.0)

                if emp["payment_type"] == "Hourly rate":
                    calculated = float(emp["hourly_rate"] or 0) * hours
                    st.info(f"Suggested payment based on hourly rate: {money(calculated)}")
                else:
                    calculated = float(emp["fixed_salary"] or 0)
                    st.info(f"Suggested fixed salary payment: {money(calculated)}")

                col3, col4 = st.columns(2)
                amount_paid = col3.number_input("Amount you paid to the employee", value=float(calculated), min_value=0.0, step=1.0)
                status = col4.selectbox("Status", ["Paid", "Not paid", "Partially paid"])

                if st.form_submit_button("Save employee payment", use_container_width=True):
                    if amount_paid <= 0:
                        st.error("Please enter an amount greater than 0.")
                    else:
                        execute_sql("""
                        INSERT INTO employee_payments
                        (employee_id, payment_date, hours_worked, amount_paid, status, created_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """, (int(emp["id"]), payment_date.isoformat(), hours, amount_paid, status, datetime.now().isoformat()))

                        st.success("Employee payment saved. This payment is now counted as salary cost.")
                        st.rerun()

    with tab3:
        st.subheader("How much I paid each employee")
        if employee_summary.empty:
            st.info("No employee payment data yet.")
        else:
            st.dataframe(employee_summary, use_container_width=True, hide_index=True)

            chart_df = employee_summary[employee_summary["total_paid"] > 0].copy()
            if not chart_df.empty:
                fig = px.bar(
                    chart_df,
                    x="employee",
                    y="total_paid",
                    text="total_paid",
                    title="Total paid to each employee"
                )
                fig.update_traces(texttemplate="$%{text:,.2f}", textposition="outside")
                fig.update_layout(yaxis_title="Total paid", xaxis_title="Employee")
                st.plotly_chart(fig, use_container_width=True)

    with tab4:
        st.subheader("All employee payment history")
        st.dataframe(payment_history, use_container_width=True, hide_index=True)

        if not payment_history.empty:
            st.subheader("Delete an employee payment")
            selected_id = st.selectbox("Choose payment ID to delete", payment_history["id"].tolist(), key="delete_employee_payment_id")
            if st.button("Delete selected employee payment"):
                execute_sql("DELETE FROM employee_payments WHERE id = ?", (int(selected_id),))
                st.success("Employee payment deleted.")
                st.rerun()


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



def get_business_strategy_numbers(plan):
    total_revenue, total_expenses, total_employee_paid, profit = get_totals()
    savings_df = read_sql("SELECT * FROM savings")
    investments_df = read_sql("SELECT * FROM investments")

    total_saved = savings_df["amount"].sum() if not savings_df.empty else 0
    total_invested = investments_df["amount"].sum() if not investments_df.empty else 0

    current_cash = float(plan.get("current_cash", 0) or 0) if plan else 0
    monthly_revenue_goal = float(plan.get("monthly_revenue_goal", 0) or 0) if plan else 0
    monthly_expense_budget = float(plan.get("monthly_expense_budget", 0) or 0) if plan else 0
    desired_profit_margin = float(plan.get("desired_profit_margin", 0) or 0) if plan else 0
    monthly_saving_goal = float(plan.get("monthly_saving_goal", 0) or 0) if plan else 0
    investment_goal = float(plan.get("investment_goal", 0) or 0) if plan else 0

    available_cash = current_cash + total_revenue - total_expenses - total_employee_paid - total_invested
    recommended_emergency_fund = max(monthly_expense_budget * 3, (total_expenses + total_employee_paid) * 3)
    target_profit = monthly_revenue_goal * (desired_profit_margin / 100)
    max_expenses_for_goal = max(0, monthly_revenue_goal - target_profit)
    gap_to_investment_goal = max(0, investment_goal - total_saved)

    return {
        "total_revenue": total_revenue,
        "total_expenses": total_expenses,
        "total_employee_paid": total_employee_paid,
        "profit": profit,
        "total_saved": total_saved,
        "total_invested": total_invested,
        "available_cash": available_cash,
        "recommended_emergency_fund": recommended_emergency_fund,
        "target_profit": target_profit,
        "max_expenses_for_goal": max_expenses_for_goal,
        "gap_to_investment_goal": gap_to_investment_goal,
        "monthly_saving_goal": monthly_saving_goal,
    }


def business_management_page():
    st.markdown("<div class='big-title'>💼 Business Growth & Investment Manager</div>", unsafe_allow_html=True)
    st.markdown("<p class='subtitle'>Plan your investment, save money, control expenses, and grow profit.</p>", unsafe_allow_html=True)

    latest_plan_df = read_sql("SELECT * FROM business_plans ORDER BY id DESC LIMIT 1")
    latest_plan = latest_plan_df.iloc[0].to_dict() if not latest_plan_df.empty else {}

    tab1, tab2, tab3, tab4 = st.tabs(["Business Plan", "Save Money", "Investments", "Strategy"])

    with tab1:
        st.subheader("Create or update your business financial plan")
        with st.form("business_plan_form"):
            col1, col2 = st.columns(2)
            business_name = col1.text_input("Business name", value=latest_plan.get("business_name", "Havre de Paix"))
            plan_date = col2.date_input("Plan date", value=date.today())

            col3, col4, col5 = st.columns(3)
            current_cash = col3.number_input("Current cash available", min_value=0.0, value=float(latest_plan.get("current_cash", 0) or 0), step=100.0)
            monthly_revenue_goal = col4.number_input("Monthly revenue goal", min_value=0.0, value=float(latest_plan.get("monthly_revenue_goal", 0) or 0), step=100.0)
            monthly_expense_budget = col5.number_input("Monthly expense budget", min_value=0.0, value=float(latest_plan.get("monthly_expense_budget", 0) or 0), step=100.0)

            col6, col7, col8 = st.columns(3)
            desired_profit_margin = col6.number_input("Desired profit margin (%)", min_value=0.0, max_value=100.0, value=float(latest_plan.get("desired_profit_margin", 20) or 20), step=1.0)
            monthly_saving_goal = col7.number_input("Monthly saving goal", min_value=0.0, value=float(latest_plan.get("monthly_saving_goal", 0) or 0), step=50.0)
            investment_goal = col8.number_input("Investment goal", min_value=0.0, value=float(latest_plan.get("investment_goal", 0) or 0), step=100.0)

            notes = st.text_area("Business notes / strategy", value=latest_plan.get("notes", ""))

            if st.form_submit_button("Save business plan", use_container_width=True):
                execute_sql("""
                INSERT INTO business_plans
                (plan_date, business_name, current_cash, monthly_revenue_goal, monthly_expense_budget,
                 desired_profit_margin, monthly_saving_goal, investment_goal, notes, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (plan_date.isoformat(), business_name, current_cash, monthly_revenue_goal,
                      monthly_expense_budget, desired_profit_margin, monthly_saving_goal,
                      investment_goal, notes, datetime.now().isoformat()))
                st.success("Business plan saved.")
                st.rerun()

        plans = read_sql("SELECT id, plan_date, business_name, current_cash, monthly_revenue_goal, monthly_expense_budget, desired_profit_margin, monthly_saving_goal, investment_goal FROM business_plans ORDER BY id DESC")
        st.dataframe(plans, use_container_width=True, hide_index=True)

    with tab2:
        st.subheader("Track money saved for future investment")
        with st.form("saving_form"):
            col1, col2, col3 = st.columns(3)
            saving_date = col1.date_input("Saving date", value=date.today())
            amount = col2.number_input("Amount saved", min_value=0.0, step=25.0)
            target = col3.selectbox("Saving target", ["Emergency fund", "New investment", "Equipment", "Marketing", "Expansion", "Other"])
            reason = st.text_input("Reason / note")

            if st.form_submit_button("Add saving"):
                execute_sql("""
                INSERT INTO savings (saving_date, reason, amount, target, created_at)
                VALUES (?, ?, ?, ?, ?)
                """, (saving_date.isoformat(), reason, amount, target, datetime.now().isoformat()))
                st.success("Saving added.")
                st.rerun()

        savings_df = read_sql("SELECT * FROM savings ORDER BY id DESC")
        st.dataframe(savings_df, use_container_width=True, hide_index=True)

    with tab3:
        st.subheader("Manage business investments")
        with st.form("investment_form"):
            col1, col2, col3 = st.columns(3)
            investment_date = col1.date_input("Investment date", value=date.today())
            investment_type = col2.selectbox("Investment type", ["Equipment", "Marketing", "Inventory", "Technology", "Vehicle", "Training", "Other"])
            amount = col3.number_input("Investment amount", min_value=0.0, step=100.0)

            col4, col5 = st.columns(2)
            expected_return = col4.number_input("Expected return / benefit", min_value=0.0, step=100.0)
            status = col5.selectbox("Status", ["Planned", "In progress", "Completed", "Paused"])
            notes = st.text_area("Investment notes")

            if st.form_submit_button("Add investment"):
                execute_sql("""
                INSERT INTO investments (investment_date, investment_type, amount, expected_return, status, notes, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (investment_date.isoformat(), investment_type, amount, expected_return, status, notes, datetime.now().isoformat()))
                st.success("Investment added.")
                st.rerun()

        investments_df = read_sql("SELECT * FROM investments ORDER BY id DESC")
        st.dataframe(investments_df, use_container_width=True, hide_index=True)

    with tab4:
        st.subheader("Automatic business strategy")
        latest_plan_df = read_sql("SELECT * FROM business_plans ORDER BY id DESC LIMIT 1")
        latest_plan = latest_plan_df.iloc[0].to_dict() if not latest_plan_df.empty else {}
        numbers = get_business_strategy_numbers(latest_plan)

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Available cash", money(numbers["available_cash"]))
        c2.metric("Net profit", money(numbers["profit"]))
        c3.metric("Total saved", money(numbers["total_saved"]))
        c4.metric("Total invested", money(numbers["total_invested"]))

        c5, c6, c7 = st.columns(3)
        c5.metric("Emergency fund target", money(numbers["recommended_emergency_fund"]))
        c6.metric("Target monthly profit", money(numbers["target_profit"]))
        c7.metric("Gap before investing", money(numbers["gap_to_investment_goal"]))

        st.markdown("<div class='info-box'>", unsafe_allow_html=True)
        st.write("### Recommendation")

        if not latest_plan:
            st.warning("Create your business plan first. The app will then calculate saving and investment recommendations.")
        else:
            if numbers["available_cash"] < 0:
                st.error("Your cash position is negative. Priority: reduce expenses, collect client payments, and pause non-essential investments.")
            elif numbers["total_saved"] < numbers["recommended_emergency_fund"]:
                st.warning("Priority: build your emergency fund before taking big investment risks.")
                st.write(f"Try to save at least {money(numbers['monthly_saving_goal'])} each month until your emergency fund is complete.")
            elif numbers["profit"] <= 0:
                st.warning("Your profit is too low or negative. Focus on increasing revenue and reducing monthly expenses before investing more.")
            else:
                st.success("Your business is in a better position to invest. Choose investments that increase revenue, reduce costs, or improve service quality.")

            st.write("**Simple senior strategy:**")
            st.write("1. Keep 3 months of expenses as emergency money.")
            st.write("2. Save a fixed amount every month before spending.")
            st.write("3. Invest only when the investment can bring more clients, better service, or lower costs.")
            st.write("4. Compare monthly revenue goal with your real expenses every week.")
            st.write(f"5. To reach your profit margin, your monthly expenses should stay around {money(numbers['max_expenses_for_goal'])} or less.")

        st.markdown("</div>", unsafe_allow_html=True)

        data = monthly_data()
        if not data.empty:
            fig = px.line(data, x="month", y="amount", color="type", markers=True, title="Business money flow")
            st.plotly_chart(fig, use_container_width=True)

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
    business_plans = read_sql("SELECT * FROM business_plans")
    savings = read_sql("SELECT * FROM savings")
    investments = read_sql("SELECT * FROM investments")

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
        "Receipts": receipts,
        "Business plans": business_plans,
        "Savings": savings,
        "Investments": investments
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

    user_role = st.session_state.get("role") or get_user_role(st.session_state.get("username", ""))
    st.session_state["role"] = user_role

    if user_role == "admin":
        pages = [
            "Dashboard",
            "Expenses",
            "Receipt Scanner",
            "Clients and Payments",
            "Employees and Salaries",
            "Business Growth",
            "Predictions",
            "Reports",
            "Admin Users",
            "Settings"
        ]
    elif user_role == "manager":
        pages = [
            "Dashboard",
            "Expenses",
            "Receipt Scanner",
            "Clients and Payments",
            "Employees and Salaries",
            "Business Growth",
            "Predictions",
            "Reports"
        ]
    else:
        pages = [
            "Dashboard",
            "Expenses",
            "Receipt Scanner",
            "Clients and Payments",
            "Business Growth"
        ]

    with st.sidebar:
        st.title("🏢 Havre de Paix")
        st.caption("Systeme Management")
        st.write("User:", st.session_state.get("username", ""))
        st.write("Role:", user_role)

        page = st.radio("Menu", pages)

        if st.button("Logout"):
            st.session_state["logged_in"] = False
            st.session_state["username"] = ""
            st.session_state["role"] = ""
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
    elif page == "Business Growth":
        business_management_page()
    elif page == "Predictions":
        predictions_page()
    elif page == "Reports":
        reports_page()
    elif page == "Admin Users" and user_role == "admin":
        admin_users_page()
    elif page == "Settings" and user_role == "admin":
        settings_page()
    else:
        st.error("Access denied.")


if __name__ == "__main__":
    main()
