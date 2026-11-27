import sqlite3
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import date, timedelta, datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from fpdf import FPDF
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- ЗАГЛУШКА ДЛЯ RAILWAY ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

def run_health_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

threading.Thread(target=run_health_server, daemon=True).start()
# -----------------------------------------------------------

# --- ВАШИ ДАННЫЕ ---
TOKEN = "9292282503:AAGTBe4jryIjP_XrU1OjZQgCD-XWDP3xo-E" 
ADMIN_ID = 7014970015  # Твой ID
BAKER_ID = 8596668517  # ID пекаря

# --- БАЗА ДАННЫХ ---
def init_db():
    conn = sqlite3.connect("bakery.db")
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS products
                 (id INTEGER PRIMARY KEY, name TEXT, cost REAL, opt_price REAL, retail_price REAL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS stores
                 (id INTEGER PRIMARY KEY, name TEXT, address TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS store_products
                 (store_name TEXT, product_name TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS shipments
                 (id INTEGER PRIMARY KEY, store TEXT, product TEXT, qty INTEGER, date TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS leftovers
                 (id INTEGER PRIMARY KEY, store TEXT, product TEXT, qty INTEGER, date TEXT)""")
    
    c.execute("SELECT count(*) FROM products")
    if c.fetchone()[0] == 0:
        prods = [
            ("Булочка сгущ.", 4.69, 15, 20),
            ("Хлеб дом.", 50, 0, 60),
            ("Хлеб обыч.", 40, 0, 50),
            ("Пончики", 25, 0, 50),
            ("Пицца", 17.76, 55, 70),
            ("Сосиска в тесте", 9.94, 25, 35),
            ("Бургер", 60, 85, 100),
            ("Сосиска шпаж.", 13.23, 0, 30),
        ]
        c.executemany("INSERT INTO products (name, cost, opt_price, retail_price) VALUES (?,?,?,?)", prods)
        
    c.execute("SELECT count(*) FROM stores")
    if c.fetchone()[0] == 0:
        stores = [("Магазин 1", "ул. Ленина 1"), ("Магазин 2", "ул. Пушкина 2"), ("Своя точка", "Пекарня")]
        c.executemany("INSERT INTO stores (name, address) VALUES (?,?)", stores)
        
    conn.commit()
    conn.close()

def get_db():
    return sqlite3.connect("bakery.db")

# --- МЕНЮ ---
def main_menu_kb(is_admin=False):
    kb = [
        [InlineKeyboardButton("📦 Отгрузить товар (Водитель)", callback_data="ship")],
        [InlineKeyboardButton("📊 Ввести остаток", callback_data="left")],
    ]
    if is_admin:
        kb.append([InlineKeyboardButton("📈 Статистика", callback_data="stats_menu")])
        kb.append([InlineKeyboardButton("⚙️ Админка", callback_data="admin_menu")])
    return InlineKeyboardMarkup(kb)

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    is_admin = (update.effective_user.id == ADMIN_ID)
    await update.message.reply_text("🥖 Главное меню:", reply_markup=main_menu_kb(is_admin))

async def main_menu_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    ctx.user_data.clear()
    is_admin = (q.from_user.id == ADMIN_ID)
    await q.edit_message_text("🥖 Главное меню:", reply_markup=main_menu_kb(is_admin))

# --- СТАТИСТИКА ---
async def stats_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    kb = [
        [InlineKeyboardButton("📊 На экране (Сегодня)", callback_data="stat_view_today")],
        [InlineKeyboardButton("📊 На экране (За неделю)", callback_data="stat_view_week")],
        [InlineKeyboardButton("📊 На экране (За месяц)", callback_data="stat_view_month")],
        [InlineKeyboardButton("📄 Скачать PDF (Сегодня)", callback_data="rep_today")],
        [InlineKeyboardButton("📄 Скачать PDF (За неделю)", callback_data="rep_week")],
        [InlineKeyboardButton("⬅️ Меню", callback_data="main_menu")]
    ]
    await q.edit_message_text("📈 Выбери формат статистики:", reply_markup=InlineKeyboardMarkup(kb))

async def show_stats_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE, start_date: str, end_date: str, title: str):
    q = update.callback_query
    conn = get_db(); c = conn.cursor()
    
    total_revenue = 0
    total_profit = 0
    text = f"📈 Статистика: {title}\n({start_date} - {end_date})\n\n"
    
    c.execute("SELECT DISTINCT store FROM shipments WHERE date BETWEEN ? AND ?", (start_date, end_date))
    stores = [r[0] for r in c.fetchall()]
    
    if not stores:
        text += "Пока нет данных за этот период."
    else:
        for store in stores:
            text += f"📍 {store}\n"
            store_rev = 0
            store_prof = 0
            
            c.execute("SELECT DISTINCT product FROM shipments WHERE store=? AND date BETWEEN ? AND ?", (store, start_date, end_date))
            prods = [r[0] for r in c.fetchall()]
            for prod in prods:
                c.execute("SELECT SUM(qty) FROM shipments WHERE store=? AND product=? AND date BETWEEN ? AND ?", (store, prod, start_date, end_date))
                shipped = c.fetchone()[0] or 0
                c.execute("SELECT SUM(qty) FROM leftovers WHERE store=? AND product=? AND date BETWEEN ? AND ?", (store, prod, start_date, end_date))
                left = c.fetchone()[0] or 0
                sold = shipped - left
                
                if sold > 0:
                    c.execute("SELECT cost, opt_price, retail_price FROM products WHERE name=?", (prod,))
                    res = c.fetchone()
                    if res:
                        cost, opt, ret = res
                        price = ret if store == "Своя точка" else opt
                        rev = sold * price
                        prof = sold * (price - cost)
                        store_rev += rev
                        store_prof += prof
                        text += f"  • {prod}: {sold} шт = {rev:.0f} ₽ (прибыль {prof:.0f} ₽)\n"
            
            text += f"  Итого: {store_rev:.0f} ₽\n\n"
            total_revenue += store_rev
            total_profit += store_prof
            
        text += f"━━━━━━━━━━━━━━━━━━\n"
        text += f"💰 ВЫРУЧКА: {total_revenue:.0f} ₽\n"
        text += f"📈 ПРИБЫЛЬ: {total_profit:.0f} ₽"
    
    conn.close()
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="stats_menu")]]))

async def stat_today(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    today = str(date.today())
    await show_stats_text(update, ctx, today, today, "За сегодня")

async def stat_week(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    start = str(date.today() - timedelta(days=7))
    end = str(date.today())
    await show_stats_text(update, ctx, start, end, "За неделю")

async def stat_month(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    start = str(date.today() - timedelta(days=30))
    end = str(date.today())
    await show_stats_text(update, ctx, start, end, "За месяц")

# --- PDF ОТЧЕТ ---
async def generate_pdf_report(update: Update, ctx: ContextTypes.DEFAULT_TYPE, start_date: str, end_date: str, title: str):
    q = update.callback_query
    await q.edit_message_text("⏳ Собираю данные и создаю PDF...")
    
    conn = get_db(); c = conn.cursor()
    total_revenue = 0
    total_profit = 0
    rows = []
    
    c.execute("SELECT DISTINCT store FROM shipments WHERE date BETWEEN ? AND ?", (start_date, end_date))
    stores = [r[0] for r in c.fetchall()]
    
    for store in stores:
        c.execute("SELECT DISTINCT product FROM shipments WHERE store=? AND date BETWEEN ? AND ?", (store, start_date, end_date))
        prods = [r[0] for r in c.fetchall()]
        for prod in prods:
            c.execute("SELECT SUM(qty) FROM shipments WHERE store=? AND product=? AND date BETWEEN ? AND ?", (store, prod, start_date, end_date))
            shipped = c.fetchone()[0] or 0
            c.execute("SELECT SUM(qty) FROM leftovers WHERE store=? AND product=? AND date BETWEEN ? AND ?", (store, prod, start_date, end_date))
            left = c.fetchone()[0] or 0
            sold = shipped - left
            if sold > 0:
                c.execute("SELECT cost, opt_price, retail_price FROM products WHERE name=?", (prod,))
                res = c.fetchone()
                if res:
                    cost, opt, ret = res
                    price = ret if store == "Своя точка" else opt
                    rev = sold * price
                    prof = sold * (price - cost)
                    total_revenue += rev
                    total_profit += prof
                    rows.append((store, prod, sold, rev, prof))
    conn.close()
    
    font_path = "DejaVuSans.ttf"
    if not os.path.exists(font_path):
        url = "https://github.com/dejavu-fonts/dejavu-fonts/raw/master/ttf/DejaVuSans.ttf"
        r = requests.get(url, verify=False)
        with open(font_path, "wb") as f:
            f.write(r.content)

    pdf = FPDF()
    pdf.add_page()
    pdf.add_font("DejaVu", "", font_path, uni=True)
    pdf.set_font("DejaVu", size=14)
    pdf.cell(0, 10, f"Отчет: {title}", ln=True, align='C')
    pdf.set_font("DejaVu", size=10)
    pdf.cell(0, 10, f"Период: {start_date} - {end_date}", ln=True, align='C')
    pdf.ln(5)
    
    pdf.set_font("DejaVu", size=9)
    pdf.cell(35, 8, "Точка", 1)
    pdf.cell(45, 8, "Товар", 1)
    pdf.cell(15, 8, "Шт", 1)
    pdf.cell(35, 8, "Выручка", 1)
    pdf.cell(35, 8, "Прибыль", 1)
    pdf.ln()
    
    for r in rows:
        pdf.cell(35, 8, str(r[0])[:15], 1)
        pdf.cell(45, 8, str(r[1])[:20], 1)
        pdf.cell(15, 8, str(r[2]), 1)
        pdf.cell(35, 8, f"{r[3]:.0f} руб", 1)
        pdf.cell(35, 8, f"{r[4]:.0f} руб", 1)
        pdf.ln()
        
    pdf.ln(5)
    pdf.set_font("DejaVu", size=12)
    pdf.cell(0, 10, f"ВЫРУЧКА: {total_revenue:.0f} руб", ln=True)
    pdf.cell(0, 10, f"ЧИСТАЯ ПРИБЫЛЬ: {total_profit:.0f} руб", ln=True)
    
    filename = f"report_{start_date}_{end_date}.pdf"
    pdf.output(filename)
    
    await q.message.reply_document(document=open(filename, "rb"), caption=f"💰 Отчет: {title}")
    os.remove(filename)
    await q.edit_message_text("✅ PDF сформирован!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="stats_menu")]]))

async def report_today(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    today = str(date.today())
    await generate_pdf_report(update, ctx, today, today, "За сегодня")

async def report_week(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    start = str(date.today() - timedelta(days=7))
    end = str(date.today())
    await generate_pdf_report(update, ctx, start, end, "За неделю")

# --- ОТГРУЗКА ---
async def ship_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT name, address FROM stores")
    stores = c.fetchall()
    conn.close()
    if not stores:
        await q.edit_message_text("Сначала добавь магазины в Админке!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Меню", callback_data="main_menu")]]))
        return
    kb = [[InlineKeyboardButton(f"{s[0]} ({s[1]})", callback_data=f"shipstore_{s[0]}")] for s in stores]
    kb.append([InlineKeyboardButton("⬅️ Меню", callback_data="main_menu")])
    await q.edit_message_text("Выбери точку:", reply_markup=InlineKeyboardMarkup(kb))

async def ship_store(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    store = q.data.replace("shipstore_", "")
    ctx.user_data["store"] = store
    ctx.user_data["ship_data"] = {}
    await show_ship_keyboard(q, ctx)

async def show_ship_keyboard(q, ctx):
    store = ctx.user_data["store"]
    data = ctx.user_data["ship_data"]
    conn = get_db(); c = conn.cursor()
    if store == "Своя точка":
        c.execute("SELECT name FROM products")
    else:
        c.execute("SELECT product_name FROM store_products WHERE store_name=?", (store,))
    prods = [r[0] for r in c.fetchall()]
    conn.close()
    
    if not prods:
        await q.edit_message_text("Тут пока нет товаров!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Меню", callback_data="main_menu")]]))
        return

    kb = []
    for name in prods:
        qty = data.get(name, 0)
        kb.append([InlineKeyboardButton(f"{name}: {qty} шт", callback_data=f"add_{name}")])
    kb.append([InlineKeyboardButton("✅ Завершить", callback_data="finish_ship")])
    kb.append([InlineKeyboardButton("⬅️ Меню", callback_data="main_menu")])
    await q.edit_message_text(f"📍 {store}\nЖми на товар:", reply_markup=InlineKeyboardMarkup(kb))

async def add_product_qty(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    prod = q.data.replace("add_", "")
    ctx.user_data["current_prod"] = prod
    await q.edit_message_text(f"Введи кол-во «{prod}»:")

async def finish_ship(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    store = ctx.user_data["store"]
    data = ctx.user_data["ship_data"]
    if not data:
        await q.edit_message_text("Отмена.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Меню", callback_data="main_menu")]]))
        return
    conn = get_db(); c = conn.cursor()
    today = str(date.today())
    for prod, qty in data.items():
        c.execute("INSERT INTO shipments (store, product, qty, date) VALUES (?,?,?,?)", (store, prod, qty, today))
    conn.commit(); conn.close()
    
    text = f"✅ Отгружено в {store}:\n" + "\n".join(f"• {k}: {v} шт" for k, v in data.items())
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Меню", callback_data="main_menu")]]))
    ctx.user_data.clear()

# --- ОСТАТКИ ---
async def left_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT name, address FROM stores")
    stores = c.fetchall()
    conn.close()
    if not stores:
        await q.edit_message_text("Сначала добавь магазины в Админке!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Меню", callback_data="main_menu")]]))
        return
    kb = [[InlineKeyboardButton(f"{s[0]}", callback_data=f"leftstore_{s[0]}")] for s in stores]
    kb.append([InlineKeyboardButton("⬅️ Меню", callback_data="main_menu")])
    await q.edit_message_text("Где вводим остаток?", reply_markup=InlineKeyboardMarkup(kb))

async def left_store(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    store = q.data.replace("leftstore_", "")
    ctx.user_data.update({"store": store, "leftover": {}})
    
    conn = get_db(); c = conn.cursor()
    if store == "Своя точка":
        c.execute("SELECT name FROM products")
    else:
        c.execute("SELECT product_name FROM store_products WHERE store_name=?", (store,))
    ctx.user_data["left_products"] = [r[0] for r in c.fetchall()]
    conn.close()
    await show_left_keyboard(q, ctx)

async def show_left_keyboard(q, ctx):
    store = ctx.user_data["store"]
    data = ctx.user_data.get("leftover", {})
    prods = ctx.user_data["left_products"]
    
    if not prods:
        await q.edit_message_text("В этом магазине нет товаров.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Меню", callback_data="main_menu")]]))
        return

    kb = []
    for name in prods:
        qty = data.get(name, "—")
        kb.append([InlineKeyboardButton(f"{name}: {qty}", callback_data=f"setleft_{name}")])
    kb.append([InlineKeyboardButton("✅ Сохранить остатки", callback_data="save_left")])
    kb.append([InlineKeyboardButton("⬅️ Меню", callback_data="main_menu")])
    
    class FQ:
        async def edit_message_text(self, t, **kw): await q.message.reply_text(t, **kw)
        async def answer(self): pass
    await q.edit_message_text(f"📍 {store}\nЖми на товар и вводи остаток:", reply_markup=InlineKeyboardMarkup(kb))

async def set_leftover_qty(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    prod = q.data.replace("setleft_", "")
    ctx.user_data["current_left_prod"] = prod
    await q.edit_message_text(f"Введи остаток для «{prod}» (в штуках):")

async def save_leftovers(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    store = ctx.user_data["store"]
    data = ctx.user_data.get("leftover", {})
    conn = get_db(); c = conn.cursor()
    today = str(date.today())
    
    text = f"📊 Остатки в {store} сохранены.\nИтог продаж за сегодня:\n"
    total_rev = 0
    total_prof = 0
    
    for prod in ctx.user_data["left_products"]:
        left = data.get(prod, 0)
        c.execute("INSERT INTO leftovers (store, product, qty, date) VALUES (?,?,?,?)", (store, prod, left, today))
        
        c.execute("SELECT SUM(qty) FROM shipments WHERE store=? AND product=? AND date=?", (store, prod, today))
        shipped = c.fetchone()[0] or 0
        sold = shipped - left
        
        if sold > 0:
            c.execute("SELECT cost, opt_price, retail_price FROM products WHERE name=?", (prod,))
            res = c.fetchone()
            if res:
                cost, opt, ret = res
                price = ret if store == "Своя точка" else opt
                rev = sold * price
                prof = sold * (price - cost)
                total_rev += rev
                total_prof += prof
                text += f"• {prod}: продано {sold} шт = {rev:.0f} руб (прибыль {prof:.0f} руб)\n"
            
    conn.commit(); conn.close()
    text += f"\n💰 Выручка: {total_rev:.0f} руб\n📈 Прибыль: {total_prof:.0f} руб"
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Меню", callback_data="main_menu")]]))
    ctx.user_data.clear()

# --- АДМИНКА ---
async def admin_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    kb = [
        [InlineKeyboardButton("➕ Добавить товар", callback_data="admin_add_prod")],
        [InlineKeyboardButton("✏️ Редактировать товар", callback_data="admin_edit_prod_list")],
        [InlineKeyboardButton("➕ Добавить магазин", callback_data="admin_add_store")],
        [InlineKeyboardButton("✏️ Редактировать магазин", callback_data="admin_edit_store_list")],
        [InlineKeyboardButton("🔗 Привязать товары", callback_data="admin_link")],
        [InlineKeyboardButton("⬅️ Меню", callback_data="main_menu")]
    ]
    await q.edit_message_text("⚙️ Админка:", reply_markup=InlineKeyboardMarkup(kb))

async def admin_add_prod(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    ctx.user_data["admin_state"] = "add_prod_name"
    await q.edit_message_text("Введи НАЗВАНИЕ товара:")

async def admin_add_store(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    ctx.user_data["admin_state"] = "add_store_name"
    await q.edit_message_text("Введи НАЗВАНИЕ магазина:")

async def admin_edit_prod_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT name FROM products")
    prods = [r[0] for r in c.fetchall()]
    conn.close()
    if not prods:
        await q.edit_message_text("Товаров нет.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="admin_menu")]]))
        return
    kb = [[InlineKeyboardButton(p, callback_data=f"editprod_{p}")] for p in prods]
    kb.append([InlineKeyboardButton("⬅️ Назад", callback_data="admin_menu")])
    await q.edit_message_text("Выбери товар для редактирования:", reply_markup=InlineKeyboardMarkup(kb))

async def admin_edit_store_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT name, address FROM stores")
    stores = c.fetchall()
    conn.close()
    if not stores:
        await q.edit_message_text("Магазинов нет.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="admin_menu")]]))
        return
    kb = [[InlineKeyboardButton(f"{s[0]}", callback_data=f"editstore_{s[0]}")] for s in stores]
    kb.append([InlineKeyboardButton("⬅️ Назад", callback_data="admin_menu")])
    await q.edit_message_text("Выбери магазин для редактирования:", reply_markup=InlineKeyboardMarkup(kb))

async def select_edit_prod(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    prod = q.data.replace("editprod_", "")
    ctx.user_data["edit_prod"] = prod
    ctx.user_data["admin_state"] = "edit_prod_name"
    await q.edit_message_text(f"Товар «{prod}».\nВведи НОВОЕ название (или напиши то же самое):")

async def select_edit_store(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    store = q.data.replace("editstore_", "")
    ctx.user_data["edit_store"] = store
    ctx.user_data["admin_state"] = "edit_store_name"
    await q.edit_message_text(f"Магазин «{store}».\nВведи НОВОЕ название (или напиши то же самое):")

async def admin_link(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT name FROM stores")
    stores = [r[0] for r in c.fetchall()]
    conn.close()
    if not stores:
        await q.edit_message_text("Сначала добавь магазины.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="admin_menu")]]))
        return
    kb = [[InlineKeyboardButton(s, callback_data=f"linkstore_{s}")] for s in stores]
    kb.append([InlineKeyboardButton("⬅️ Назад", callback_data="admin_menu")])
    await q.edit_message_text("Выбери магазин:", reply_markup=InlineKeyboardMarkup(kb))

async def link_store_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    store = q.data.replace("linkstore_", "")
    ctx.user_data["link_store"] = store
    await show_link_keyboard(q, ctx)

async def show_link_keyboard(q, ctx):
    store = ctx.user_data["link_store"]
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT name FROM products")
    prods = [r[0] for r in c.fetchall()]
    c.execute("SELECT product_name FROM store_products WHERE store_name=?", (store,))
    linked = [r[0] for r in c.fetchall()]
    conn.close()
    
    if not prods:
        await q.edit_message_text("Сначала добавь товары.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="admin_link")]]))
        return
    
    kb = []
    for p in prods:
        mark = "✅ " if p in linked else "❌ "
        kb.append([InlineKeyboardButton(f"{mark}{p}", callback_data=f"toggle_{p}")])
    kb.append([InlineKeyboardButton("⬅️ Назад", callback_data="admin_link")])
    
    class FQ:
        async def edit_message_text(self, t, **kw): await q.message.reply_text(t, **kw)
        async def answer(self): pass
    await q.edit_message_text(f"Магазин: {store}\nЖми, чтобы вкл/выкл:", reply_markup=InlineKeyboardMarkup(kb))

async def toggle_product(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    prod = q.data.replace("toggle_", "")
    store = ctx.user_data["link_store"]
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT * FROM store_products WHERE store_name=? AND product_name=?", (store, prod))
    if c.fetchone():
        c.execute("DELETE FROM store_products WHERE store_name=? AND product_name=?", (store, prod))
    else:
        c.execute("INSERT INTO store_products (store_name, product_name) VALUES (?,?)", (store, prod))
    conn.commit(); conn.close()
    await show_link_keyboard(q, ctx)

# --- ОБРАБОТЧИК ТЕКСТА ---
async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.replace(",", ".")
    state = ctx.user_data.get("admin_state")
    
    if state == "add_prod_name":
        ctx.user_data["new_prod_name"] = text
        ctx.user_data["admin_state"] = "add_prod_cost"
        await update.message.reply_text("Введи СЕБЕСТОИМОСТЬ (например, 15.5):")
        return
    elif state == "add_prod_cost":
        ctx.user_data["new_prod_cost"] = float(text)
        ctx.user_data["admin_state"] = "add_prod_opt"
        await update.message.reply_text("Введи ОПТОВУЮ цену:")
        return
    elif state == "add_prod_opt":
        ctx.user_data["new_prod_opt"] = float(text)
        ctx.user_data["admin_state"] = "add_prod_retail"
        await update.message.reply_text("Введи РОЗНИЧНУЮ цену:")
        return
    elif state == "add_prod_retail":
        retail = float(text)
        name = ctx.user_data["new_prod_name"]
        cost = ctx.user_data["new_prod_cost"]
        opt = ctx.user_data["new_prod_opt"]
        conn = get_db(); c = conn.cursor()
        c.execute("INSERT INTO products (name, cost, opt_price, retail_price) VALUES (?,?,?,?)", (name, cost, opt, retail))
        conn.commit(); conn.close()
        ctx.user_data.clear()
        await update.message.reply_text(f"✅ Товар «{name}» добавлен!", reply_markup=main_menu_kb(True))
        return
        
    elif state == "edit_prod_name":
        ctx.user_data["edit_new_name"] = text
        ctx.user_data["admin_state"] = "edit_prod_cost"
        await update.message.reply_text("Введи НОВУЮ себестоимость:")
        return
    elif state == "edit_prod_cost":
        ctx.user_data["edit_new_cost"] = float(text)
        ctx.user_data["admin_state"] = "edit_prod_opt"
        await update.message.reply_text("Введи НОВУЮ оптовую цену:")
        return
    elif state == "edit_prod_opt":
        ctx.user_data["edit_new_opt"] = float(text)
        ctx.user_data["admin_state"] = "edit_prod_retail"
        await update.message.reply_text("Введи НОВУЮ розничную цену:")
        return
    elif state == "edit_prod_retail":
        retail = float(text)
        old_name = ctx.user_data["edit_prod"]
        new_name = ctx.user_data["edit_new_name"]
        cost = ctx.user_data["edit_new_cost"]
        opt = ctx.user_data["edit_new_opt"]
        conn = get_db(); c = conn.cursor()
        c.execute("UPDATE products SET name=?, cost=?, opt_price=?, retail_price=? WHERE name=?", (new_name, cost, opt, retail, old_name))
        conn.commit(); conn.close()
        ctx.user_data.clear()
        await update.message.reply_text(f"✅ Товар обновлен!", reply_markup=main_menu_kb(True))
        return

    elif state == "add_store_name":
        ctx.user_data["new_store_name"] = text
        ctx.user_data["admin_state"] = "add_store_addr"
        await update.message.reply_text("Введи АДРЕС магазина:")
        return
    elif state == "add_store_addr":
        name = ctx.user_data["new_store_name"]
        addr = text
        conn = get_db(); c = conn.cursor()
        c.execute("INSERT INTO stores (name, address) VALUES (?,?)", (name, addr))
        conn.commit(); conn.close()
        ctx.user_data.clear()
        await update.message.reply_text(f"✅ Магазин «{name}» добавлен!", reply_markup=main_menu_kb(True))
        return
        
    elif state == "edit_store_name":
        ctx.user_data["edit_new_store_name"] = text
        ctx.user_data["admin_state"] = "edit_store_addr"
        await update.message.reply_text("Введи НОВЫЙ адрес магазина:")
        return
    elif state == "edit_store_addr":
        addr = text
        old_name = ctx.user_data["edit_store"]
        new_name = ctx.user_data["edit_new_store_name"]
        conn = get_db(); c = conn.cursor()
        c.execute("UPDATE stores SET name=?, address=? WHERE name=?", (new_name, addr, old_name))
        conn.commit(); conn.close()
        ctx.user_data.clear()
        await update.message.reply_text(f"✅ Магазин обновлен!", reply_markup=main_menu_kb(True))
        return

    try:
        qty = float(text) if "." in text else int(text)
    except:
        await update.message.reply_text("Введи число.")
        return

    if "current_prod" in ctx.user_data:
        prod = ctx.user_data.pop("current_prod")
        if qty > 0: ctx.user_data["ship_data"][prod] = qty
        elif qty == 0 and prod in ctx.user_data["ship_data"]: del ctx.user_data["ship_data"][prod]
        class FQ:
            async def edit_message_text(self, t, **kw): await update.message.reply_text(t, **kw)
            async def answer(self): pass
        await show_ship_keyboard(FQ(), ctx)
    
    elif "buy_ing" in ctx.user_data:
        # Заглушка, так как склада больше нет
        ctx.user_data.pop("buy_ing")

    elif "current_left_prod" in ctx.user_data:
        prod = ctx.user_data.pop("current_left_prod")
        ctx.user_data["leftover"][prod] = qty
        class FQ:
            async def edit_message_text(self, t, **kw): await update.message.reply_text(t, **kw)
            async def answer(self): pass
        await show_left_keyboard(FQ(), ctx)

# --- УВЕДОМЛЕНИЯ ---
async def send_night_report(ctx: ContextTypes.DEFAULT_TYPE):
    text = "🌙 Ночной отчет (готово к работе)."
    try:
        msg = await ctx.bot.send_message(chat_id=BAKER_ID, text=text)
        await ctx.bot.send_message(chat_id=ADMIN_ID, text=f"📤 Отчет пекарю отправлен.")
    except Exception as e:
        await ctx.bot.send_message(chat_id=ADMIN_ID, text=f"⚠️ Ошибка отправки пекарю: {e}")

def main():
    init_db()
    app = Application.builder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(ship_menu, pattern="^ship$"))
    app.add_handler(CallbackQueryHandler(ship_store, pattern="^shipstore_"))
    app.add_handler(CallbackQueryHandler(add_product_qty, pattern="^add_"))
    app.add_handler(CallbackQueryHandler(finish_ship, pattern="^finish_ship$"))
    app.add_handler(CallbackQueryHandler(left_menu, pattern="^left$"))
    app.add_handler(CallbackQueryHandler(left_store, pattern="^leftstore_"))
    app.add_handler(CallbackQueryHandler(set_leftover_qty, pattern="^setleft_"))
    app.add_handler(CallbackQueryHandler(save_leftovers, pattern="^save_left$"))
    
    app.add_handler(CallbackQueryHandler(stats_menu, pattern="^stats_menu$"))
    app.add_handler(CallbackQueryHandler(stat_today, pattern="^stat_view_today$"))
    app.add_handler(CallbackQueryHandler(stat_week, pattern="^stat_view_week$"))
    app.add_handler(CallbackQueryHandler(stat_month, pattern="^stat_view_month$"))
    app.add_handler(CallbackQueryHandler(report_today, pattern="^rep_today$"))
    app.add_handler(CallbackQueryHandler(report_week, pattern="^rep_week$"))
    
    app.add_handler(CallbackQueryHandler(admin_menu, pattern="^admin_menu$"))
    app.add_handler(CallbackQueryHandler(admin_add_prod, pattern="^admin_add_prod$"))
    app.add_handler(CallbackQueryHandler(admin_add_store, pattern="^admin_add_store$"))
    app.add_handler(CallbackQueryHandler(admin_edit_prod_list, pattern="^admin_edit_prod_list$"))
    app.add_handler(CallbackQueryHandler(admin_edit_store_list, pattern="^admin_edit_store_list$"))
    app.add_handler(CallbackQueryHandler(select_edit_prod, pattern="^editprod_"))
    app.add_handler(CallbackQueryHandler(select_edit_store, pattern="^editstore_"))
    app.add_handler(CallbackQueryHandler(admin_link, pattern="^admin_link$"))
    app.add_handler(CallbackQueryHandler(link_store_menu, pattern="^linkstore_"))
    app.add_handler(CallbackQueryHandler(toggle_product, pattern="^toggle_"))
    app.add_handler(CallbackQueryHandler(main_menu_callback, pattern="^main_menu$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    job_queue = app.job_queue
    if job_queue:
        job_queue.run_daily(send_night_report, time=datetime.strptime("17:00", "%H:%M").time())

    print("Бот запущен!")
    app.run_polling()

if __name__ == "__main__":
    main()