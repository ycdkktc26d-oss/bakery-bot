import sqlite3
import os
from datetime import date, timedelta, datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from fpdf import FPDF

# --- ВАШИ ДАННЫЕ ---
TOKEN = "9292282503:AAGTBe4jryIjP_XrU1OjZQgCD-XWDP3xo-E"
ADMIN_ID = 7014970015  # ВАШ ID
BAKER_ID = 8596668517 # ID пекаря

# --- БАЗА ДАННЫХ ---
def init_db():
    conn = sqlite3.connect("bakery.db")
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS products
                 (id INTEGER PRIMARY KEY, name TEXT, cost REAL, opt_price REAL, retail_price REAL, in_stores INTEGER)""")
    c.execute("""CREATE TABLE IF NOT EXISTS stores
                 (id INTEGER PRIMARY KEY, name TEXT, address TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS shipments
                 (id INTEGER PRIMARY KEY, store TEXT, product TEXT, qty INTEGER, date TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS leftovers
                 (id INTEGER PRIMARY KEY, store TEXT, product TEXT, qty INTEGER, date TEXT)""")
    
    c.execute("SELECT count(*) FROM products")
    if c.fetchone()[0] == 0:
        prods = [
            ("Булочка сгущ.", 4.69, 15, 20, 1),
            ("Хлеб дом.", 50, 0, 60, 0),
            ("Хлеб обыч.", 40, 0, 50, 0),
            ("Пончики", 25, 0, 50, 0),
            ("Пицца", 17.76, 55, 70, 1),
            ("Сосиска в тесте", 9.94, 25, 35, 1),
            ("Бургер", 60, 85, 100, 1),
            ("Сосиска шпаж.", 13.23, 0, 30, 0),
        ]
        c.executemany("INSERT INTO products (name, cost, opt_price, retail_price, in_stores) VALUES (?,?,?,?,?)", prods)
        
    c.execute("SELECT count(*) FROM stores")
    if c.fetchone()[0] == 0:
        stores = [("Магазин 1", "ул. Ленина 1"), ("Магазин 2", "ул. Пушкина 2"), ("Своя точка", "Пекарня")]
        c.executemany("INSERT INTO stores (name, address) VALUES (?,?)", stores)
        
    conn.commit()
    conn.close()

def get_db():
    return sqlite3.connect("bakery.db")

# --- СКЛАД (Умный) ---
INGREDIENTS = {
    "Мука": {"qty": 50.0, "unit": "кг", "pack_name": "мешок", "pack_weight": 45.0},
    "Сахар": {"qty": 20.0, "unit": "кг", "pack_name": "мешок", "pack_weight": 50.0},
    "Дрожжи": {"qty": 2.0, "unit": "кг", "pack_name": "пачка", "pack_weight": 0.5},
    "Маргарин": {"qty": 5.0, "unit": "кг", "pack_name": "пачка", "pack_weight": 0.1},
    "Сгущенка": {"qty": 20.0, "unit": "кг", "pack_name": "банка", "pack_weight": 1.0},
    "Сосиски": {"qty": 100.0, "unit": "шт", "pack_name": "пачка", "pack_weight": 10.0},
    "Сыр": {"qty": 10.0, "unit": "кг", "pack_name": "кг", "pack_weight": 1.0},
    "Томат": {"qty": 5.0, "unit": "кг", "pack_name": "банка", "pack_weight": 0.7},
    "Панировка": {"qty": 3.0, "unit": "кг", "pack_name": "пачка", "pack_weight": 1.0},
    "Шпажки": {"qty": 100.0, "unit": "шт", "pack_name": "пачка", "pack_weight": 100.0},
}

RECIPES = {
    "Булочка сгущ.": {"Мука": 0.05, "Сахар": 0.01, "Дрожжи": 0.001, "Маргарин": 0.004, "Сгущенка": 0.01},
    "Пицца": {"Мука": 0.1, "Сосиски": 0.5, "Сыр": 0.025, "Томат": 0.005},
    "Сосиска в тесте": {"Мука": 0.05, "Сосиски": 1.0},
    "Сосиска шпаж.": {"Мука": 0.1, "Сосиски": 1.0, "Панировка": 0.01, "Шпажки": 1.0},
}

# --- МЕНЮ ---
def main_menu_kb(is_admin=False):
    kb = [
        [InlineKeyboardButton("📦 Отгрузить товар (Водитель)", callback_data="ship")],
        [InlineKeyboardButton("📊 Ввести остаток (Магазины)", callback_data="left")],
        [InlineKeyboardButton("📚 Склад (Сырье)", callback_data="warehouse")],
        [InlineKeyboardButton("🚚 Закуп (Приход)", callback_data="purchase")],
    ]
    if is_admin:
        kb.append([InlineKeyboardButton("💰 Чистая прибыль (PDF)", callback_data="profit_pdf")])
        kb.append([InlineKeyboardButton("⚙️ Админка (Товары/Магазины)", callback_data="admin_menu")])
    return InlineKeyboardMarkup(kb)

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    is_admin = (update.effective_user.id == ADMIN_ID)
    await update.message.reply_text("🥖 Главное меню:", reply_markup=main_menu_kb(is_admin))

async def main_menu_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    ctx.user_data.clear()
    is_admin = (q.from_user.id == ADMIN_ID)
    await q.edit_message_text("🥖 Главное меню:", reply_markup=main_menu_kb(is_admin))

# --- ОТГРУЗКА ---
async def ship_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT name FROM stores")
    stores = [row[0] for row in c.fetchall()]
    conn.close()
    kb = [[InlineKeyboardButton(s, callback_data=f"shipstore_{s}")] for s in stores]
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
    c.execute("SELECT name, in_stores FROM products")
    prods = c.fetchall()
    conn.close()
    
    kb = []
    for name, in_stores in prods:
        if (store == "Своя точка" and in_stores == 0) or (store != "Своя точка" and in_stores == 1):
            qty = data.get(name, 0)
            kb.append([InlineKeyboardButton(f"{name}: {qty} шт", callback_data=f"add_{name}")])
            
    kb.append([InlineKeyboardButton("✅ Завершить", callback_data="finish_ship")])
    kb.append([InlineKeyboardButton("⬅️ Меню", callback_data="main_menu")])
    await q.edit_message_text(f"📍 {store}\nЖми на товар:", reply_markup=InlineKeyboardMarkup(kb))

async def add_product_qty(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    prod = q.data.replace("add_", "")
    ctx.user_data["current_prod"] = prod
    await q.edit_message_text(f"Введи кол-во «{prod}» (или 0, чтобы убрать):")

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
    
    for prod, qty in data.items():
        if prod in RECIPES:
            for ing, amount in RECIPES[prod].items():
                if ing in INGREDIENTS:
                    INGREDIENTS[ing]["qty"] -= (amount * qty)
    
    text = f"✅ Отгружено в {store}:\n" + "\n".join(f"• {k}: {v} шт" for k, v in data.items())
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Меню", callback_data="main_menu")]]))
    ctx.user_data.clear()

# --- СКЛАД ---
async def warehouse_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    text = "📚 Остатки на складе:\n\n"
    for name, data in INGREDIENTS.items():
        text += f"• {name}: {data['qty']:.2f} {data['unit']}\n"
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Меню", callback_data="main_menu")]]))

# --- ЗАКУП ---
async def purchase_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    kb = []
    for name, data in INGREDIENTS.items():
        kb.append([InlineKeyboardButton(f"{name}", callback_data=f"buy_{name}")])
    kb.append([InlineKeyboardButton("⬅️ Меню", callback_data="main_menu")])
    await q.edit_message_text("Что закупаем?", reply_markup=InlineKeyboardMarkup(kb))

async def select_purchase(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    ing = q.data.replace("buy_", "")
    ctx.user_data["buy_ing"] = ing
    pack = INGREDIENTS[ing]['pack_name']
    await q.edit_message_text(f"Сколько {ing} привезли? (в {pack}ах)\nНапиши просто число:")

# --- ОСТАТКИ ---
async def left_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT name FROM stores")
    stores = [row[0] for row in c.fetchall()]
    conn.close()
    kb = [[InlineKeyboardButton(s, callback_data=f"leftstore_{s}")] for s in stores]
    kb.append([InlineKeyboardButton("⬅️ Меню", callback_data="main_menu")])
    await q.edit_message_text("Где вводим остаток?", reply_markup=InlineKeyboardMarkup(kb))

async def left_store(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    store = q.data.replace("leftstore_", "")
    ctx.user_data.update({"store": store, "leftover": {}, "idx": 0, "mode": "leftover"})
    ctx.user_data["left_products"] = []
    
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT name, in_stores FROM products")
    for name, in_stores in c.fetchall():
        if (store == "Своя точка" and in_stores == 0) or (store != "Своя точка" and in_stores == 1):
            ctx.user_data["left_products"].append(name)
    conn.close()
    await ask_next_leftover(q, ctx)

async def ask_next_leftover(q, ctx):
    idx = ctx.user_data["idx"]
    avail = ctx.user_data["left_products"]
    if idx >= len(avail):
        await save_leftovers(q, ctx)
        return
    prod = avail[idx]
    ctx.user_data["current_product"] = prod
    await q.edit_message_text(f"Остаток «{prod}» (введи число):")

async def save_leftovers(q, ctx):
    conn = get_db(); c = conn.cursor()
    today = str(date.today())
    store = ctx.user_data["store"]
    data = ctx.user_data.get("leftover", {})
    for prod, qty in data.items():
        c.execute("INSERT INTO leftovers (store, product, qty, date) VALUES (?,?,?,?)", (store, prod, qty, today))
    text = f"📊 Остатки в {store} записаны."
    conn.commit(); conn.close()
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Меню", callback_data="main_menu")]]))
    ctx.user_data.clear()

# --- ПРИБЫЛЬ В PDF ---
async def profit_pdf(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    today = str(date.today())
    conn = get_db(); c = conn.cursor()
    
    total_revenue = 0
    total_profit = 0
    rows = []
    
    c.execute("SELECT DISTINCT store FROM shipments WHERE date=?", (today,))
    stores = [r[0] for r in c.fetchall()]
    
    for store in stores:
        c.execute("SELECT DISTINCT product FROM shipments WHERE store=? AND date=?", (store, today))
        prods = [r[0] for r in c.fetchall()]
        for prod in prods:
            c.execute("SELECT SUM(qty) FROM shipments WHERE store=? AND product=? AND date=?", (store, prod, today))
            shipped = c.fetchone()[0] or 0
            c.execute("SELECT SUM(qty) FROM leftovers WHERE store=? AND product=? AND date=?", (store, prod, today))
            left = c.fetchone()[0] or 0
            sold = shipped - left
            if sold > 0:
                c.execute("SELECT cost, opt_price, retail_price FROM products WHERE name=?", (prod,))
                cost, opt, ret = c.fetchone()
                price = ret if store == "Своя точка" else opt
                rev = sold * price
                prof = sold * (price - cost)
                total_revenue += rev
                total_profit += prof
                rows.append((store, prod, sold, price, rev, prof))
    conn.close()
    
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(200, 10, f"Otchet za {today}", ln=True, align='C')
    pdf.ln(10)
    
    pdf.set_font("Arial", size=10)
    pdf.cell(40, 10, "Tochka", 1)
    pdf.cell(50, 10, "Tovar", 1)
    pdf.cell(20, 10, "Sht", 1)
    pdf.cell(30, 10, "Vyruchka", 1)
    pdf.cell(30, 10, "Pribyl", 1)
    pdf.ln()
    
    for r in rows:
        pdf.cell(40, 10, str(r[0]), 1)
        pdf.cell(50, 10, str(r[1]), 1)
        pdf.cell(20, 10, str(r[2]), 1)
        pdf.cell(30, 10, f"{r[4]:.0f} rub", 1)
        pdf.cell(30, 10, f"{r[5]:.0f} rub", 1)
        pdf.ln()
        
    pdf.ln(10)
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(200, 10, f"ITOGO VYRCHKA: {total_revenue:.0f} rub", ln=True)
    pdf.cell(200, 10, f"CHISTAYA PRIBYL: {total_profit:.0f} rub", ln=True)
    
    filename = f"report_{today}.pdf"
    pdf.output(filename)
    
    await q.message.reply_document(document=open(filename, "rb"), caption="💰 Ваш отчет за сегодня")
    os.remove(filename)
    await q.edit_message_text("PDF сформирован!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Меню", callback_data="main_menu")]]))

# --- АДМИНКА ---
async def admin_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    kb = [
        [InlineKeyboardButton("➕ Добавить товар", callback_data="admin_add_prod")],
        [InlineKeyboardButton("✏️ Изменить цены", callback_data="admin_edit_prices")],
        [InlineKeyboardButton("➕ Добавить магазин", callback_data="admin_add_store")],
        [InlineKeyboardButton("⬅️ Меню", callback_data="main_menu")]
    ]
    await q.edit_message_text("⚙️ Админка:", reply_markup=InlineKeyboardMarkup(kb))

async def admin_add_prod(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    ctx.user_data["admin_state"] = "add_prod_name"
    await q.edit_message_text("Введи НАЗВАНИЕ товара (например, Пирожок):")

async def admin_add_store(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    ctx.user_data["admin_state"] = "add_store_name"
    await q.edit_message_text("Введи НАЗВАНИЕ магазина:")

async def admin_edit_prices(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT name FROM products")
    prods = [row[0] for row in c.fetchall()]
    conn.close()
    
    kb = [[InlineKeyboardButton(p, callback_data=f"editprod_{p}")] for p in prods]
    kb.append([InlineKeyboardButton("⬅️ Назад", callback_data="admin_menu")])
    await q.edit_message_text("Выбери товар для изменения цен:", reply_markup=InlineKeyboardMarkup(kb))

async def select_edit_product(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    prod = q.data.replace("editprod_", "")
    ctx.user_data["edit_prod"] = prod
    ctx.user_data["admin_state"] = "edit_prod_cost"
    await q.edit_message_text(f"Товар: {prod}\nВведи НОВУЮ СЕБЕСТОИМОСТЬ:")

# --- ОБРАБОТЧИК ТЕКСТА ---
async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.replace(",", ".")
    
    # Админка - добавление товара
    if ctx.user_data.get("admin_state") == "add_prod_name":
        name = text
        conn = get_db(); c = conn.cursor()
        c.execute("INSERT INTO products (name, cost, opt_price, retail_price, in_stores) VALUES (?, 0, 0, 0, 1)", (name,))
        conn.commit(); conn.close()
        ctx.user_data.clear()
        await update.message.reply_text(f"✅ Товар «{name}» добавлен! Не забудь поменять ему цены через «✏️ Изменить цены».", reply_markup=main_menu_kb(True))
        return

    # Админка - изменение цен (себестоимость)
    elif ctx.user_data.get("admin_state") == "edit_prod_cost":
        ctx.user_data["edit_cost"] = float(text)
        ctx.user_data["admin_state"] = "edit_prod_opt"
        await update.message.reply_text("Введи НОВУЮ ОПТОВУЮ цену:")
        return
        
    # Админка - изменение цен (опт)
    elif ctx.user_data.get("admin_state") == "edit_prod_opt":
        ctx.user_data["edit_opt"] = float(text)
        ctx.user_data["admin_state"] = "edit_prod_retail"
        await update.message.reply_text("Введи НОВУЮ РОЗНИЧНУЮ цену:")
        return
        
    # Админка - изменение цен (розница и сохранение)
    elif ctx.user_data.get("admin_state") == "edit_prod_retail":
        retail = float(text)
        prod = ctx.user_data["edit_prod"]
        cost = ctx.user_data["edit_cost"]
        opt = ctx.user_data["edit_opt"]
        
        conn = get_db(); c = conn.cursor()
        c.execute("UPDATE products SET cost=?, opt_price=?, retail_price=? WHERE name=?", (cost, opt, retail, prod))
        conn.commit(); conn.close()
        ctx.user_data.clear()
        await update.message.reply_text(f"✅ Цены для «{prod}» обновлены!", reply_markup=main_menu_kb(True))
        return

    # Админка - добавление магазина (имя)
    elif ctx.user_data.get("admin_state") == "add_store_name":
        ctx.user_data["new_store_name"] = text
        ctx.user_data["admin_state"] = "add_store_addr"
        await update.message.reply_text("Введи АДРЕС магазина:")
        return
    # Админка - добавление магазина (адрес)
    elif ctx.user_data.get("admin_state") == "add_store_addr":
        name = ctx.user_data["new_store_name"]
        addr = text
        conn = get_db(); c = conn.cursor()
        c.execute("INSERT INTO stores (name, address) VALUES (?,?)", (name, addr))
        conn.commit(); conn.close()
        ctx.user_data.clear()
        await update.message.reply_text(f"✅ Магазин «{name}» добавлен!", reply_markup=main_menu_kb(True))
        return

    # Основные процессы
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
        ing = ctx.user_data.pop("buy_ing")
        packs = qty
        if ing in INGREDIENTS:
            total_weight = packs * INGREDIENTS[ing]["pack_weight"]
            INGREDIENTS[ing]["qty"] += total_weight
            await update.message.reply_text(f"✅ Закуплено {packs} {INGREDIENTS[ing]['pack_name']}.\nНа складе: {INGREDIENTS[ing]['qty']:.2f} {INGREDIENTS[ing]['unit']}", reply_markup=main_menu_kb(True))

    elif "current_product" in ctx.user_data:
        prod = ctx.user_data.pop("current_product")
        if qty >= 0: ctx.user_data["leftover"][prod] = qty
        ctx.user_data["idx"] += 1
        class FQ:
            async def edit_message_text(self, t, **kw): await update.message.reply_text(t, **kw)
            async def answer(self): pass
        await ask_next_leftover(FQ(), ctx)

# --- УВЕДОМЛЕНИЯ ---
async def send_night_report(ctx: ContextTypes.DEFAULT_TYPE):
    text = "🌙 Остатки на завтра:\n\n"
    for name, data in INGREDIENTS.items():
        text += f"• {name}: {data['qty']:.2f} {data['unit']}\n"
    try:
        msg = await ctx.bot.send_message(chat_id=BAKER_ID, text=text)
        await ctx.bot.send_message(chat_id=ADMIN_ID, text=f"📤 Отчет пекарю отправлен.\nСтатус: Доставлено (ID: {msg.message_id})")
    except Exception as e:
        await ctx.bot.send_message(chat_id=ADMIN_ID, text=f"⚠️ Ошибка! Пекарь не получил отчет. Детали: {e}")

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
    app.add_handler(CallbackQueryHandler(warehouse_menu, pattern="^warehouse$"))
    app.add_handler(CallbackQueryHandler(purchase_menu, pattern="^purchase$"))
    app.add_handler(CallbackQueryHandler(select_purchase, pattern="^buy_"))
    app.add_handler(CallbackQueryHandler(profit_pdf, pattern="^profit_pdf$"))
    app.add_handler(CallbackQueryHandler(admin_menu, pattern="^admin_menu$"))
    app.add_handler(CallbackQueryHandler(admin_add_prod, pattern="^admin_add_prod$"))
    app.add_handler(CallbackQueryHandler(admin_add_store, pattern="^admin_add_store$"))
    app.add_handler(CallbackQueryHandler(admin_edit_prices, pattern="^admin_edit_prices$"))
    app.add_handler(CallbackQueryHandler(select_edit_product, pattern="^editprod_"))
    app.add_handler(CallbackQueryHandler(main_menu_callback, pattern="^main_menu$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    job_queue = app.job_queue
    if job_queue:
        job_queue.run_daily(send_night_report, time=datetime.strptime("17:00", "%H:%M").time())

    print("Финальный бот запущен!")
    app.run_polling()

if __name__ == "__main__":
    main()
