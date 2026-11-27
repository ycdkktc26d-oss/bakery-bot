import sqlite3
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import date, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

# --- ЗАГЛУШКА ДЛЯ RAILWAY (чтобы сервер не выключал бота) ---
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

# --- БАЗА ДАННЫХ ---
def init_db():
    conn = sqlite3.connect("bakery.db")
    c = conn.cursor()
    # Создаем пустые таблицы (старые товары удалены)
    c.execute("""CREATE TABLE IF NOT EXISTS products
                 (id INTEGER PRIMARY KEY, name TEXT, opt_price REAL, retail_price REAL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS stores
                 (id INTEGER PRIMARY KEY, name TEXT, address TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS store_products
                 (store_name TEXT, product_name TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS shipments
                 (id INTEGER PRIMARY KEY, store TEXT, product TEXT, qty INTEGER, date TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS leftovers
                 (id INTEGER PRIMARY KEY, store TEXT, product TEXT, qty INTEGER, date TEXT)""")
    
    conn.commit()
    conn.close()

def get_db():
    return sqlite3.connect("bakery.db", timeout=10)

# --- ГЛАВНОЕ МЕНЮ ---
def main_menu_kb(is_admin=False):
    kb = [
        [InlineKeyboardButton("📦 Отгрузить товар", callback_data="ship")],
        [InlineKeyboardButton("📊 Ввести остаток", callback_data="left")],
    ]
    if is_admin:
        kb.append([InlineKeyboardButton("📈 Статистика", callback_data="stats_menu")])
        kb.append([InlineKeyboardButton("⚙️ Админка", callback_data="admin_menu")])
    return InlineKeyboardMarkup(kb)

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    is_admin = (update.effective_user.id == ADMIN_ID)
    await update.message.reply_text("🥖 Главное меню:", reply_markup=main_menu_kb(is_admin))

async def cmd_reset(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    conn = get_db(); c = conn.cursor()
    c.execute("DELETE FROM shipments")
    c.execute("DELETE FROM leftovers")
    conn.commit(); conn.close()
    await update.message.reply_text("🗑 Все продажи и остатки сброшены в ноль! Товары и магазины на месте.")

async def cmd_reset_all(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    conn = get_db(); c = conn.cursor()
    c.execute("DELETE FROM shipments")
    c.execute("DELETE FROM leftovers")
    c.execute("DELETE FROM products")
    c.execute("DELETE FROM stores")
    c.execute("DELETE FROM store_products")
    conn.commit(); conn.close()
    await update.message.reply_text("🔥 База ПОЛНОСТЬЮ ОЧИЩЕНА! Все товары и магазины удалены.")

async def main_menu_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    ctx.user_data.clear()
    is_admin = (q.from_user.id == ADMIN_ID)
    await q.edit_message_text("🥖 Главное меню:", reply_markup=main_menu_kb(is_admin))

# --- СТАТИСТИКА (Только текст) ---
async def stats_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    kb = [
        [InlineKeyboardButton("📊 Сегодня", callback_data="stat_today")],
        [InlineKeyboardButton("📊 За неделю", callback_data="stat_week")],
        [InlineKeyboardButton("📊 За месяц", callback_data="stat_month")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="main_menu")]
    ]
    await q.edit_message_text("📈 Выбери период:", reply_markup=InlineKeyboardMarkup(kb))

async def show_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE, start_date: str, end_date: str, title: str):
    q = update.callback_query
    conn = get_db(); c = conn.cursor()
    total_revenue = 0; total_profit = 0
    text = f"📈 Статистика: {title}\n({start_date} - {end_date})\n\n"
    
    c.execute("SELECT DISTINCT store FROM shipments WHERE date BETWEEN ? AND ?", (start_date, end_date))
    stores = [r[0] for r in c.fetchall()]
    
    if not stores:
        text += "Нет данных за этот период."
    else:
        for store in stores:
            text += f"📍 {store}\n"
            store_rev = 0; store_prof = 0
            c.execute("SELECT DISTINCT product FROM shipments WHERE store=? AND date BETWEEN ? AND ?", (store, start_date, end_date))
            for prod in [r[0] for r in c.fetchall()]:
                c.execute("SELECT SUM(qty) FROM shipments WHERE store=? AND product=? AND date BETWEEN ? AND ?", (store, prod, start_date, end_date))
                shipped = c.fetchone()[0] or 0
                c.execute("SELECT SUM(qty) FROM leftovers WHERE store=? AND product=? AND date BETWEEN ? AND ?", (store, prod, start_date, end_date))
                left = c.fetchone()[0] or 0
                sold = shipped - left
                if sold > 0:
                    c.execute("SELECT opt_price, retail_price FROM products WHERE name=?", (prod,))
                    res = c.fetchone()
                    if res:
                        opt, ret = res
                        price = ret if "Своя" in store else opt
                        rev = sold * price
                        store_rev += rev
                        text += f"  • {prod}: {sold} шт = {rev:.0f} ₽\n"
            text += f"  Итого: {store_rev:.0f} ₽\n\n"
            total_revenue += store_rev
        text += f"━━━━━━━━━━━━━━━\n💰 ВЫРУЧКА: {total_revenue:.0f} ₽"
    
    conn.close()
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="stats_menu")]]))

async def stat_today(update, ctx): await show_stats(update, ctx, str(date.today()), str(date.today()), "Сегодня")
async def stat_week(update, ctx): await show_stats(update, ctx, str(date.today()-timedelta(days=7)), str(date.today()), "Неделя")
async def stat_month(update, ctx): await show_stats(update, ctx, str(date.today()-timedelta(days=30)), str(date.today()), "Месяц")

# --- ОТГРУЗКА ---
async def ship_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT name, address FROM stores")
    stores = c.fetchall(); conn.close()
    if not stores:
        await q.edit_message_text("Сначала добавь магазины в Админке!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="main_menu")]]))
        return
    kb = [[InlineKeyboardButton(f"{s[0]} ({s[1]})", callback_data=f"shipstore_{s[0]}")] for s in stores]
    kb.append([InlineKeyboardButton("⬅️ Назад", callback_data="main_menu")])
    await q.edit_message_text("Выбери точку:", reply_markup=InlineKeyboardMarkup(kb))

async def ship_store(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    store = q.data.replace("shipstore_", "")
    ctx.user_data.update({"store": store, "ship_data": {}})
    await show_ship_kb(q, ctx)

async def show_ship_kb(q, ctx):
    store = ctx.user_data["store"]; data = ctx.user_data["ship_data"]
    conn = get_db(); c = conn.cursor()
    if "Своя" in store: c.execute("SELECT name FROM products")
    else: c.execute("SELECT product_name FROM store_products WHERE store_name=?", (store,))
    prods = [r[0] for r in c.fetchall()]; conn.close()
    
    if not prods:
        await q.edit_message_text("Нет товаров!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="main_menu")]]))
        return
    kb = [[InlineKeyboardButton(f"{p}: {data.get(p, 0)} шт", callback_data=f"add_{p}")] for p in prods]
    kb.append([InlineKeyboardButton("✅ Завершить", callback_data="finish_ship")])
    kb.append([InlineKeyboardButton("⬅️ Назад", callback_data="main_menu")])
    await q.edit_message_text(f"📍 {store}", reply_markup=InlineKeyboardMarkup(kb))

async def add_prod_qty(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    ctx.user_data["current_prod"] = q.data.replace("add_", "")
    await q.edit_message_text(f"Введи кол-во «{ctx.user_data['current_prod']}»:")

async def finish_ship(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    store = ctx.user_data["store"]; data = ctx.user_data["ship_data"]
    if not data:
        await q.edit_message_text("Отмена.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="main_menu")]]))
        return
    conn = get_db(); c = conn.cursor()
    today = str(date.today())
    for p, qty in data.items():
        c.execute("INSERT INTO shipments (store, product, qty, date) VALUES (?,?,?,?)", (store, p, qty, today))
    conn.commit(); conn.close()
    text = f"✅ Отгружено в {store}:\n" + "\n".join(f"• {k}: {v} шт" for k, v in data.items())
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="main_menu")]]))
    ctx.user_data.clear()

# --- ОСТАТКИ ---
async def left_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT name FROM stores")
    stores = [r[0] for r in c.fetchall()]; conn.close()
    if not stores:
        await q.edit_message_text("Сначала добавь магазины!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="main_menu")]]))
        return
    kb = [[InlineKeyboardButton(f"{s}", callback_data=f"leftstore_{s}")] for s in stores]
    kb.append([InlineKeyboardButton("⬅️ Назад", callback_data="main_menu")])
    await q.edit_message_text("Где вводим остаток?", reply_markup=InlineKeyboardMarkup(kb))

async def left_store(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    store = q.data.replace("leftstore_", "")
    ctx.user_data.update({"store": store, "leftover": {}})
    conn = get_db(); c = conn.cursor()
    if "Своя" in store: c.execute("SELECT name FROM products")
    else: c.execute("SELECT product_name FROM store_products WHERE store_name=?", (store,))
    ctx.user_data["left_products"] = [r[0] for r in c.fetchall()]; conn.close()
    await show_left_kb(q, ctx)

async def show_left_kb(q, ctx):
    store = ctx.user_data["store"]; data = ctx.user_data.get("leftover", {})
    prods = ctx.user_data["left_products"]
    if not prods:
        await q.edit_message_text("Нет товаров.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="main_menu")]]))
        return
    kb = [[InlineKeyboardButton(f"{p}: {data.get(p, '—')}", callback_data=f"setleft_{p}")] for p in prods]
    kb.append([InlineKeyboardButton("✅ Сохранить", callback_data="save_left")])
    kb.append([InlineKeyboardButton("⬅️ Назад", callback_data="main_menu")])
    await q.edit_message_text(f"📍 {store}", reply_markup=InlineKeyboardMarkup(kb))

async def set_left_qty(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    ctx.user_data["current_left_prod"] = q.data.replace("setleft_", "")
    await q.edit_message_text(f"Введи остаток «{ctx.user_data['current_left_prod']}»:")

async def save_leftovers(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    store = ctx.user_data["store"]; data = ctx.user_data.get("leftover", {})
    conn = get_db(); c = conn.cursor()
    today = str(date.today())
    for p in ctx.user_data["left_products"]:
        left = data.get(p, 0)
        c.execute("INSERT INTO leftovers (store, product, qty, date) VALUES (?,?,?,?)", (store, p, left, today))
    conn.commit(); conn.close()
    await q.edit_message_text(f"📊 Остатки в {store} сохранены.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="main_menu")]]))
    ctx.user_data.clear()

# --- АДМИНКА ---
async def admin_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    kb = [
        [InlineKeyboardButton("➕ Добавить товар", callback_data="admin_add_prod")],
        [InlineKeyboardButton("✏️ Редактировать/Удалить товар", callback_data="admin_edit_prod_list")],
        [InlineKeyboardButton("➕ Добавить магазин", callback_data="admin_add_store")],
        [InlineKeyboardButton("✏️ Редактировать/Удалить магазин", callback_data="admin_edit_store_list")],
        [InlineKeyboardButton("🔗 Привязать товары", callback_data="admin_link")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="main_menu")]
    ]
    await q.edit_message_text("⚙️ Админка:\n(Сброс данных: /reset)", reply_markup=InlineKeyboardMarkup(kb))

async def admin_add_prod(update, ctx):
    q = update.callback_query; await q.answer()
    ctx.user_data["admin_state"] = "add_prod_name"
    await q.edit_message_text("Введи НАЗВАНИЕ товара:\n\nДля отмены нажми /start")

async def admin_add_store(update, ctx):
    q = update.callback_query; await q.answer()
    ctx.user_data["admin_state"] = "add_store_name"
    await q.edit_message_text("Введи НАЗВАНИЕ магазина:\n\nДля отмены нажми /start")

async def admin_edit_prod_list(update, ctx):
    q = update.callback_query; await q.answer()
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT name FROM products")
    prods = [r[0] for r in c.fetchall()]; conn.close()
    if not prods:
        await q.edit_message_text("Товаров нет.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="admin_menu")]]))
        return
    kb = [[InlineKeyboardButton(p, callback_data=f"editprod_{p}")] for p in prods]
    kb.append([InlineKeyboardButton("⬅️ Назад", callback_data="admin_menu")])
    await q.edit_message_text("Выбери товар:", reply_markup=InlineKeyboardMarkup(kb))

async def admin_edit_store_list(update, ctx):
    q = update.callback_query; await q.answer()
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT name FROM stores")
    stores = [r[0] for r in c.fetchall()]; conn.close()
    if not stores:
        await q.edit_message_text("Магазинов нет.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="admin_menu")]]))
        return
    kb = [[InlineKeyboardButton(s, callback_data=f"editstore_{s}")] for s in stores]
    kb.append([InlineKeyboardButton("⬅️ Назад", callback_data="admin_menu")])
    await q.edit_message_text("Выбери магазин:", reply_markup=InlineKeyboardMarkup(kb))

async def select_edit_prod(update, ctx):
    q = update.callback_query; await q.answer()
    prod = q.data.replace("editprod_", "")
    ctx.user_data["edit_prod"] = prod
    ctx.user_data["admin_state"] = "edit_prod_name"
    kb = [
        [InlineKeyboardButton("🗑 УДАЛИТЬ ТОВАР", callback_data=f"delprod_{prod}")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="admin_menu")]
    ]
    await q.edit_message_text(f"Товар «{prod}».\nВведи НОВОЕ название (или нажми 'Удалить'):", reply_markup=InlineKeyboardMarkup(kb))

async def select_edit_store(update, ctx):
    q = update.callback_query; await q.answer()
    store = q.data.replace("editstore_", "")
    ctx.user_data["edit_store"] = store
    ctx.user_data["admin_state"] = "edit_store_name"
    kb = [
        [InlineKeyboardButton("🗑 УДАЛИТЬ МАГАЗИН", callback_data=f"delstore_{store}")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="admin_menu")]
    ]
    await q.edit_message_text(f"Магазин «{store}».\nВведи НОВОЕ название (или нажми 'Удалить'):", reply_markup=InlineKeyboardMarkup(kb))

async def delete_prod(update, ctx):
    q = update.callback_query; await q.answer()
    prod = q.data.replace("delprod_", "")
    conn = get_db(); c = conn.cursor()
    c.execute("DELETE FROM products WHERE name=?", (prod,))
    c.execute("DELETE FROM store_products WHERE product_name=?", (prod,))
    conn.commit(); conn.close()
    await q.edit_message_text(f"🗑 Товар «{prod}» удален!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="admin_menu")]]))
    ctx.user_data.clear()

async def delete_store(update, ctx):
    q = update.callback_query; await q.answer()
    store = q.data.replace("delstore_", "")
    conn = get_db(); c = conn.cursor()
    c.execute("DELETE FROM stores WHERE name=?", (store,))
    c.execute("DELETE FROM store_products WHERE store_name=?", (store,))
    conn.commit(); conn.close()
    await q.edit_message_text(f"🗑 Магазин «{store}» удален!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="admin_menu")]]))
    ctx.user_data.clear()

async def admin_link(update, ctx):
    q = update.callback_query; await q.answer()
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT name FROM stores")
    stores = [r[0] for r in c.fetchall()]; conn.close()
    if not stores:
        await q.edit_message_text("Сначала добавь магазины.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="admin_menu")]]))
        return
    kb = [[InlineKeyboardButton(s, callback_data=f"linkstore_{s}")] for s in stores]
    kb.append([InlineKeyboardButton("⬅️ Назад", callback_data="admin_menu")])
    await q.edit_message_text("Выбери магазин:", reply_markup=InlineKeyboardMarkup(kb))

async def link_store_menu(update, ctx):
    q = update.callback_query; await q.answer()
    store = q.data.replace("linkstore_", "")
    ctx.user_data["link_store"] = store
    await show_link_kb(q, ctx)

async def show_link_kb(q, ctx):
    store = ctx.user_data["link_store"]
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT name FROM products")
    prods = [r[0] for r in c.fetchall()]
    c.execute("SELECT product_name FROM store_products WHERE store_name=?", (store,))
    linked = [r[0] for r in c.fetchall()]; conn.close()
    
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

async def toggle_product(update, ctx):
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
    await show_link_kb(q, ctx)

# --- ОБРАБОТЧИК ТЕКСТА (Устранены баги с числами) ---
async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.replace(",", ".")
    state = ctx.user_data.get("admin_state")
    
    # Добавление товара
    if state == "add_prod_name":
        ctx.user_data["new_prod_name"] = text
        ctx.user_data["admin_state"] = "add_prod_opt"
        await update.message.reply_text("Введи ОПТОВУЮ цену (например, 50):")
        return
    elif state == "add_prod_opt":
        try: float(text)
        except: 
            await update.message.reply_text("❌ Ошибка! Введи ЧИСЛО (например, 50):")
            return
        ctx.user_data["new_prod_opt"] = float(text)
        ctx.user_data["admin_state"] = "add_prod_retail"
        await update.message.reply_text("Введи РОЗНИЧНУЮ цену (например, 70):")
        return
    elif state == "add_prod_retail":
        try: float(text)
        except: 
            await update.message.reply_text("❌ Ошибка! Введи ЧИСЛО (например, 70):")
            return
        retail = float(text)
        name = ctx.user_data["new_prod_name"]
        opt = ctx.user_data["new_prod_opt"]
        conn = get_db(); c = conn.cursor()
        c.execute("INSERT INTO products (name, opt_price, retail_price) VALUES (?,?,?)", (name, opt, retail))
        conn.commit(); conn.close()
        ctx.user_data.clear()
        await update.message.reply_text(f"✅ Товар «{name}» добавлен!", reply_markup=main_menu_kb(True))
        return
        
    # Редактирование товара
    elif state == "edit_prod_name":
        ctx.user_data["edit_new_name"] = text
        ctx.user_data["admin_state"] = "edit_prod_opt"
        await update.message.reply_text("Введи НОВУЮ ОПТОВУЮ цену (или напиши 'нет'):")
        return
    elif state == "edit_prod_opt":
        if text.lower() == 'нет':
            ctx.user_data["edit_new_opt"] = None
        else:
            try: ctx.user_data["edit_new_opt"] = float(text)
            except: 
                await update.message.reply_text("❌ Ошибка! Введи ЧИСЛО или 'нет':")
                return
        ctx.user_data["admin_state"] = "edit_prod_retail"
        await update.message.reply_text("Введи НОВУЮ РОЗНИЧНУЮ цену (или напиши 'нет'):")
        return
    elif state == "edit_prod_retail":
        retail = None
        if text.lower() != 'нет':
            try: retail = float(text)
            except: 
                await update.message.reply_text("❌ Ошибка! Введи ЧИСЛО или 'нет':")
                return
        
        old_name = ctx.user_data["edit_prod"]
        new_name = ctx.user_data["edit_new_name"]
        opt = ctx.user_data.get("edit_new_opt")
        
        conn = get_db(); c = conn.cursor()
        c.execute("SELECT opt_price, retail_price FROM products WHERE name=?", (old_name,))
        res = c.fetchone()
        if not opt: opt = res[0]
        if not retail: retail = res[1]
        
        c.execute("UPDATE products SET name=?, opt_price=?, retail_price=? WHERE name=?", (new_name, opt, retail, old_name))
        conn.commit(); conn.close()
        ctx.user_data.clear()
        await update.message.reply_text(f"✅ Товар обновлен!", reply_markup=main_menu_kb(True))
        return

    # Добавление магазина
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
        
    # Редактирование магазина
    elif state == "edit_store_name":
        ctx.user_data["edit_new_store_name"] = text
        ctx.user_data["admin_state"] = "edit_store_addr"
        await update.message.reply_text("Введи НОВЫЙ адрес магазина (или напиши 'нет'):")
        return
    elif state == "edit_store_addr":
        addr = None
        if text.lower() != 'нет':
            addr = text
        old_name = ctx.user_data["edit_store"]
        new_name = ctx.user_data["edit_new_store_name"]
        
        conn = get_db(); c = conn.cursor()
        c.execute("SELECT address FROM stores WHERE name=?", (old_name,))
        old_addr = c.fetchone()[0]
        if not addr: addr = old_addr
        
        c.execute("UPDATE stores SET name=?, address=? WHERE name=?", (new_name, addr, old_name))
        conn.commit(); conn.close()
        ctx.user_data.clear()
        await update.message.reply_text(f"✅ Магазин обновлен!", reply_markup=main_menu_kb(True))
        return

    # Ввод цифр (Отгрузка, Остатки)
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
        await show_ship_kb(FQ(), ctx)

    elif "current_left_prod" in ctx.user_data:
        prod = ctx.user_data.pop("current_left_prod")
        ctx.user_data["leftover"][prod] = qty
        class FQ:
            async def edit_message_text(self, t, **kw): await update.message.reply_text(t, **kw)
            async def answer(self): pass
        await show_left_kb(FQ(), ctx)

def main():
    init_db()
    app = Application.builder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(CommandHandler("resetall", cmd_reset_all))
    
    app.add_handler(CallbackQueryHandler(main_menu_callback, pattern="^main_menu$"))
    
    # Статистика
    app.add_handler(CallbackQueryHandler(stats_menu, pattern="^stats_menu$"))
    app.add_handler(CallbackQueryHandler(stat_today, pattern="^stat_today$"))
    app.add_handler(CallbackQueryHandler(stat_week, pattern="^stat_week$"))
    app.add_handler(CallbackQueryHandler(stat_month, pattern="^stat_month$"))
    
    # Отгрузка
    app.add_handler(CallbackQueryHandler(ship_menu, pattern="^ship$"))
    app.add_handler(CallbackQueryHandler(ship_store, pattern="^shipstore_"))
    app.add_handler(CallbackQueryHandler(add_prod_qty, pattern="^add_"))
    app.add_handler(CallbackQueryHandler(finish_ship, pattern="^finish_ship$"))
    
    # Остатки
    app.add_handler(CallbackQueryHandler(left_menu, pattern="^left$"))
    app.add_handler(CallbackQueryHandler(left_store, pattern="^leftstore_"))
    app.add_handler(CallbackQueryHandler(set_left_qty, pattern="^setleft_"))
    app.add_handler(CallbackQueryHandler(save_leftovers, pattern="^save_left$"))
    
    # Админка
    app.add_handler(CallbackQueryHandler(admin_menu, pattern="^admin_menu$"))
    app.add_handler(CallbackQueryHandler(admin_add_prod, pattern="^admin_add_prod$"))
    app.add_handler(CallbackQueryHandler(admin_add_store, pattern="^admin_add_store$"))
    app.add_handler(CallbackQueryHandler(admin_edit_prod_list, pattern="^admin_edit_prod_list$"))
    app.add_handler(CallbackQueryHandler(admin_edit_store_list, pattern="^admin_edit_store_list$"))
    app.add_handler(CallbackQueryHandler(select_edit_prod, pattern="^editprod_"))
    app.add_handler(CallbackQueryHandler(select_edit_store, pattern="^editstore_"))
    app.add_handler(CallbackQueryHandler(delete_prod, pattern="^delprod_"))
    app.add_handler(CallbackQueryHandler(delete_store, pattern="^delstore_"))
    app.add_handler(CallbackQueryHandler(admin_link, pattern="^admin_link$"))
    app.add_handler(CallbackQueryHandler(link_store_menu, pattern="^linkstore_"))
    app.add_handler(CallbackQueryHandler(toggle_product, pattern="^toggle_"))
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    print("Бот запущен! База пуста, всё готово для ручного заполнения.")
    app.run_polling()

if __name__ == "__main__":
    main()