import sqlite3
import os
import requests
import urllib3
from datetime import date, timedelta, datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from fpdf import FPDF

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- ВАШИ ДАННЫЕ ---
TOKEN = "9292282503:AAGTBe4jryIjP_XrU1OjZQgCD-XWDP3xo-E"
ADMIN_ID = 7014970015  # ВАШ ID
BAKER_ID = 8596668517 # ID пекаря

# --- БАЗА ДАННЫХ ---
def init_db():
    conn = sqlite3.connect("bakery.db")
    c = conn.cursor()
    
    # Таблица ингредиентов (сырье)
    c.execute("""CREATE TABLE IF NOT EXISTS ingredients
                 (id INTEGER PRIMARY KEY, name TEXT, unit TEXT, price REAL)""")
    # Таблица товаров
    c.execute("""CREATE TABLE IF NOT EXISTS products
                 (id INTEGER PRIMARY KEY, name TEXT, opt_price REAL, retail_price REAL, cost REAL)""")
    # Рецепты (связь товаров и ингредиентов)
    c.execute("""CREATE TABLE IF NOT EXISTS recipes
                 (product_name TEXT, ing_name TEXT, qty REAL)""")
    # Магазины (Каталоги)
    c.execute("""CREATE TABLE IF NOT EXISTS stores
                 (id INTEGER PRIMARY KEY, name TEXT, address TEXT)""")
    # Связь магазинов и товаров (что где продается)
    c.execute("""CREATE TABLE IF NOT EXISTS store_products
                 (store_name TEXT, product_name TEXT)""")
    # Отгрузки
    c.execute("""CREATE TABLE IF NOT EXISTS shipments
                 (id INTEGER PRIMARY KEY, store TEXT, product TEXT, qty INTEGER, date TEXT)""")
    # Остатки
    c.execute("""CREATE TABLE IF NOT EXISTS leftovers
                 (id INTEGER PRIMARY KEY, store TEXT, product TEXT, qty INTEGER, date TEXT)""")
    
    conn.commit()
    conn.close()

def get_db():
    return sqlite3.connect("bakery.db")

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
        kb.append([InlineKeyboardButton("⚙️ Управление (Админка)", callback_data="admin_menu")])
    return InlineKeyboardMarkup(kb)

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    is_admin = (update.effective_user.id == ADMIN_ID)
    await update.message.reply_text("🥖 Главное меню:", reply_markup=main_menu_kb(is_admin))

async def main_menu_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    ctx.user_data.clear()
    is_admin = (q.from_user.id == ADMIN_ID)
    await q.edit_message_text("🥖 Главное меню:", reply_markup=main_menu_kb(is_admin))

# --- АДМИНКА (КОНСТРУКТОР) ---
async def admin_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    kb = [
        [InlineKeyboardButton("➕ Добавить сырье (Склад)", callback_data="admin_add_ing")],
        [InlineKeyboardButton("➕ Создать товар", callback_data="admin_add_prod")],
        [InlineKeyboardButton("➕ Добавить магазин", callback_data="admin_add_store")],
        [InlineKeyboardButton("🔗 Привязать товары к магазину", callback_data="admin_link")],
        [InlineKeyboardButton("⬅️ Меню", callback_data="main_menu")]
    ]
    await q.edit_message_text("⚙️ Управление пекарней:", reply_markup=InlineKeyboardMarkup(kb))

async def admin_add_ing(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    ctx.user_data["admin_state"] = "ing_name"
    await q.edit_message_text("Введи НАЗВАНИЕ сырья (например, Мука, Сосиски, Сыр):")

async def admin_add_prod(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    ctx.user_data["admin_state"] = "prod_name"
    await q.edit_message_text("Введи НАЗВАНИЕ нового товара (например, Пицца):")

async def admin_add_store(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    ctx.user_data["admin_state"] = "store_name"
    await q.edit_message_text("Введи НАЗВАНИЕ магазина:")

# --- ПРИВЯЗКА ТОВАРОВ К МАГАЗИНУ ---
async def admin_link(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT name FROM stores")
    stores = [r[0] for r in c.fetchall()]
    conn.close()
    if not stores:
        await q.edit_message_text("Сначала добавь магазин!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="admin_menu")]]))
        return
    kb = [[InlineKeyboardButton(s, callback_data=f"linkstore_{s}")] for s in stores]
    kb.append([InlineKeyboardButton("⬅️ Назад", callback_data="admin_menu")])
    await q.edit_message_text("Выбери магазин для привязки товаров:", reply_markup=InlineKeyboardMarkup(kb))

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
    
    kb = []
    for p in prods:
        mark = "✅ " if p in linked else "❌ "
        kb.append([InlineKeyboardButton(f"{mark}{p}", callback_data=f"toggle_{p}")])
    kb.append([InlineKeyboardButton("⬅️ Назад", callback_data="admin_link")])
    
    class FQ:
        async def edit_message_text(self, t, **kw): await q.message.reply_text(t, **kw)
        async def answer(self): pass
    await q.edit_message_text(f"Магазин: {store}\nЖми на товар, чтобы вкл/выкл:", reply_markup=InlineKeyboardMarkup(kb))

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
    
    # Обновляем клавиатуру на лету
    c2 = conn.cursor() # dummy
    class FQ:
        async def edit_message_text(self, t, **kw): pass
        async def answer(self): pass
        async def reply_text(self, t, **kw): pass
    await show_link_keyboard(q, ctx)

# --- ОБРАБОТЧИК ТЕКСТА (КОНСТРУКТОР) ---
async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.replace(",", ".")
    state = ctx.user_data.get("admin_state")
    
    # 1. Добавление сырья
    if state == "ing_name":
        ctx.user_data["new_ing_name"] = text
        ctx.user_data["admin_state"] = "ing_unit"
        await update.message.reply_text("Введи единицу измерения (кг, шт, л):")
        return
    elif state == "ing_unit":
        ctx.user_data["new_ing_unit"] = text.lower()
        ctx.user_data["admin_state"] = "ing_price"
        await update.message.reply_text(f"Сколько стоит 1 {text.lower()} этого сырья? (в рублях):")
        return
    elif state == "ing_price":
        price = float(text)
        name = ctx.user_data["new_ing_name"]
        unit = ctx.user_data["new_ing_unit"]
        conn = get_db(); c = conn.cursor()
        c.execute("INSERT INTO ingredients (name, unit, price) VALUES (?,?,?)", (name, unit, price))
        conn.commit(); conn.close()
        ctx.user_data.clear()
        await update.message.reply_text(f"✅ Сырье «{name}» добавлено!", reply_markup=main_menu_kb(True))
        return

    # 2. Создание товара
    elif state == "prod_name":
        ctx.user_data["new_prod_name"] = text
        ctx.user_data["admin_state"] = "prod_opt"
        await update.message.reply_text("Введи ОПТОВУЮ цену (для магазинов):")
        return
    elif state == "prod_opt":
        ctx.user_data["new_prod_opt"] = float(text)
        ctx.user_data["admin_state"] = "prod_retail"
        await update.message.reply_text("Введи РОЗНИЧНУЮ цену (для своей точки):")
        return
    elif state == "prod_retail":
        ctx.user_data["new_prod_retail"] = float(text)
        ctx.user_data["prod_recipe"] = {}
        
        # Показываем склад для выбора ингредиентов
        conn = get_db(); c = conn.cursor()
        c.execute("SELECT name FROM ingredients")
        ings = [r[0] for r in c.fetchall()]
        conn.close()
        if not ings:
            await update.message.reply_text("❌ Сначала добавь сырье на склад!")
            ctx.user_data.clear()
            return
            
        kb = [[InlineKeyboardButton(i, callback_data=f"adding_{i}")] for i in ings]
        kb.append([InlineKeyboardButton("✅ Сохранить товар", callback_data="save_prod")])
        await update.message.reply_text("Выбери ингредиенты для товара:", reply_markup=InlineKeyboardMarkup(kb))
        ctx.user_data["admin_state"] = "prod_recipe"
        return

    # 3. Добавление магазина
    elif state == "store_name":
        ctx.user_data["new_store_name"] = text
        ctx.user_data["admin_state"] = "store_addr"
        await update.message.reply_text("Введи АДРЕС магазина:")
        return
    elif state == "store_addr":
        name = ctx.user_data["new_store_name"]
        addr = text
        conn = get_db(); c = conn.cursor()
        c.execute("INSERT INTO stores (name, address) VALUES (?,?)", (name, addr))
        conn.commit(); conn.close()
        ctx.user_data.clear()
        await update.message.reply_text(f"✅ Магазин «{name}» добавлен!", reply_markup=main_menu_kb(True))
        return

    # --- ОСНОВНЫЕ ПРОЦЕССЫ (Отгрузка, Закуп, Остатки) ---
    try:
        qty = float(text) if "." in text else int(text)
    except:
        await update.message.reply_text("Введи число.")
        return

    # Ввод кол-ва для рецепта (при создании товара)
    if state == "prod_recipe_qty":
        ing = ctx.user_data["current_recipe_ing"]
        ctx.user_data["prod_recipe"][ing] = qty
        conn = get_db(); c = conn.cursor()
        c.execute("SELECT name FROM ingredients")
        ings = [r[0] for r in c.fetchall()]
        conn.close()
        kb = [[InlineKeyboardButton(i, callback_data=f"adding_{i}")] for i in ings]
        kb.append([InlineKeyboardButton("✅ Сохранить товар", callback_data="save_prod")])
        await update.message.reply_text(f"Добавлено: {ing} - {qty}\nВыбери еще или сохрани:", reply_markup=InlineKeyboardMarkup(kb))
        ctx.user_data["admin_state"] = "prod_recipe"
        return

    # Отгрузка
    if "current_prod" in ctx.user_data:
        prod = ctx.user_data.pop("current_prod")
        if qty > 0: ctx.user_data["ship_data"][prod] = qty
        elif qty == 0 and prod in ctx.user_data["ship_data"]: del ctx.user_data["ship_data"][prod]
        class FQ:
            async def edit_message_text(self, t, **kw): await update.message.reply_text(t, **kw)
            async def answer(self): pass
        await show_ship_keyboard(FQ(), ctx)
    
    # Закуп (Приход)
    elif "buy_ing" in ctx.user_data:
        ing = ctx.user_data.pop("buy_ing")
        packs = qty
        # Тут мы обновляем цену закупки и приход (упрощенно для примера, склад будем считать по продажам, но физический приход фиксируем)
        conn = get_db(); c = conn.cursor()
        c.execute("UPDATE ingredients SET price=? WHERE name=?", (packs, ing)) # тут можно цену партии записать, но для простоты обновляем цену
        conn.commit(); conn.close()
        await update.message.reply_text(f"✅ Закуплено {packs}. Данные обновлены.", reply_markup=main_menu_kb(True))

    # Остатки
    elif "current_product" in ctx.user_data:
        prod = ctx.user_data.pop("current_product")
        if qty >= 0: ctx.user_data["leftover"][prod] = qty
        ctx.user_data["idx"] += 1
        class FQ:
            async def edit_message_text(self, t, **kw): await update.message.reply_text(t, **kw)
            async def answer(self): pass
        await ask_next_leftover(FQ(), ctx)

async def select_adding_ing(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    ing = q.data.replace("adding_", "")
    ctx.user_data["current_recipe_ing"] = ing
    ctx.user_data["admin_state"] = "prod_recipe_qty"
    # Получаем единицу измерения
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT unit FROM ingredients WHERE name=?", (ing,))
    unit = c.fetchone()[0]
    conn.close()
    await q.edit_message_text(f"Сколько «{ing}» уходит на 1 единицу товара? (в {unit}):")

async def save_new_product(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    name = ctx.user_data["new_prod_name"]
    opt = ctx.user_data["new_prod_opt"]
    retail = ctx.user_data["new_prod_retail"]
    recipe = ctx.user_data.get("prod_recipe", {})
    
    # Считаем себестоимость
    total_cost = 0
    conn = get_db(); c = conn.cursor()
    for ing, qty in recipe.items():
        c.execute("SELECT price FROM ingredients WHERE name=?", (ing,))
        price = c.fetchone()[0]
        total_cost += price * qty
    
    c.execute("INSERT INTO products (name, opt_price, retail_price, cost) VALUES (?,?,?,?)", (name, opt, retail, total_cost))
    for ing, qty in recipe.items():
        c.execute("INSERT INTO recipes (product_name, ing_name, qty) VALUES (?,?,?)", (name, ing, qty))
    conn.commit(); conn.close()
    
    ctx.user_data.clear()
    await q.edit_message_text(f"✅ Товар «{name}» создан!\nСебестоимость: {total_cost:.2f} ₽\nОпт: {opt} ₽\nРозница: {retail} ₽", reply_markup=main_menu_kb(True))

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
    c.execute("SELECT product_name FROM store_products WHERE store_name=?", (store,))
    prods = [r[0] for r in c.fetchall()]
    conn.close()
    
    if not prods:
        await q.edit_message_text("В этот магазин еще не привязаны товары в Админке!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Меню", callback_data="main_menu")]]))
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
    
    # Списание со склада по рецептам
    for prod, qty_sold in data.items():
        c = conn.cursor()
        c.execute("SELECT ing_name, qty FROM recipes WHERE product_name=?", (prod,))
        for ing, amount in c.fetchall():
            c.execute("UPDATE ingredients SET stock = stock - ? WHERE name=?", (amount * qty_sold, ing))
        conn.commit()
    
    text = f"✅ Отгружено в {store}:\n" + "\n".join(f"• {k}: {v} шт" for k, v in data.items())
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Меню", callback_data="main_menu")]]))
    ctx.user_data.clear()

# --- СКЛАД (ОСТАТКИ) ---
async def warehouse_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT name, unit, price FROM ingredients")
    ings = c.fetchall()
    conn.close()
    text = "📚 Склад (Сырье):\n\n"
    for i in ings:
        text += f"• {i[0]}: {i[2]:.2f} руб/{i[1]}\n"
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Меню", callback_data="main_menu")]]))

# --- ЗАКУП ---
async def purchase_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT name FROM ingredients")
    ings = [r[0] for r in c.fetchall()]
    conn.close()
    if not ings:
        await q.edit_message_text("Склад пуст. Добавь сырье в Админке!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Меню", callback_data="main_menu")]]))
        return
    kb = [[InlineKeyboardButton(i, callback_data=f"buy_{i}")] for i in ings]
    kb.append([InlineKeyboardButton("⬅️ Меню", callback_data="main_menu")])
    await q.edit_message_text("Что закупаем? (Обновление цен):", reply_markup=InlineKeyboardMarkup(kb))

async def select_purchase(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    ing = q.data.replace("buy_", "")
    ctx.user_data["buy_ing"] = ing
    await q.edit_message_text(f"Введи НОВУЮ цену закупки за 1 единицу для «{ing}»:")

# --- ОСТАТКИ ---
async def left_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT name FROM stores")
    stores = [r[0] for r in c.fetchall()]
    conn.close()
    kb = [[InlineKeyboardButton(s, callback_data=f"leftstore_{s}")] for s in stores]
    kb.append([InlineKeyboardButton("⬅️ Меню", callback_data="main_menu")])
    await q.edit_message_text("Где вводим остаток?", reply_markup=InlineKeyboardMarkup(kb))

async def left_store(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    store = q.data.replace("leftstore_", "")
    ctx.user_data.update({"store": store, "leftover": {}, "idx": 0})
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT product_name FROM store_products WHERE store_name=?", (store,))
    ctx.user_data["left_products"] = [r[0] for r in c.fetchall()]
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
    await q.edit_message_text(f"Остаток «{prod}»:")

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

# --- ПРИБЫЛЬ В PDF (РУССКИЙ) ---
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
                price = ret if "Своя" in store else opt
                rev = sold * price
                prof = sold * (price - cost)
                total_revenue += rev
                total_profit += prof
                rows.append((store, prod, sold, price, rev, prof))
    conn.close()
    
    # Скачиваем шрифт для русского языка
    font_path = "DejaVuSans.ttf"
    if not os.path.exists(font_path):
        url = "https://github.com/dejavu-fonts/dejavu-fonts/raw/master/ttf/DejaVuSans.ttf"
        r = requests.get(url, verify=False)
        with open(font_path, "wb") as f:
            f.write(r.content)

    pdf = FPDF()
    pdf.add_page()
    pdf.add_font("DejaVu", "", font_path, uni=True)
    pdf.set_font("DejaVu", size=16)
    pdf.cell(0, 10, f"Отчет за {today}", ln=True, align='C')
    pdf.ln(10)
    
    pdf.set_font("DejaVu", size=10)
    pdf.cell(40, 10, "Точка", 1)
    pdf.cell(50, 10, "Товар", 1)
    pdf.cell(20, 10, "Шт", 1)
    pdf.cell(35, 10, "Выручка", 1)
    pdf.cell(35, 10, "Прибыль", 1)
    pdf.ln()
    
    for r in rows:
        pdf.cell(40, 10, str(r[0]), 1)
        pdf.cell(50, 10, str(r[1]), 1)
        pdf.cell(20, 10, str(r[2]), 1)
        pdf.cell(35, 10, f"{r[4]:.0f} руб", 1)
        pdf.cell(35, 10, f"{r[5]:.0f} руб", 1)
        pdf.ln()
        
    pdf.ln(10)
    pdf.set_font("DejaVu", size=12)
    pdf.cell(0, 10, f"ИТОГО ВЫРУЧКА: {total_revenue:.0f} руб", ln=True)
    pdf.cell(0, 10, f"ЧИСТАЯ ПРИБЫЛЬ: {total_profit:.0f} руб", ln=True)
    
    filename = f"report_{today}.pdf"
    pdf.output(filename)
    
    await q.message.reply_document(document=open(filename, "rb"), caption="💰 Ваш отчет за сегодня")
    os.remove(filename)
    await q.edit_message_text("PDF сформирован!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Меню", callback_data="main_menu")]]))

# --- УВЕДОМЛЕНИЯ ---
async def send_night_report(ctx: ContextTypes.DEFAULT_TYPE):
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT name, unit, price FROM ingredients")
    ings = c.fetchall()
    conn.close()
    text = "🌙 Остатки на завтра (склад):\n\n"
    for i in ings:
        text += f"• {i[0]}: {i[2]:.2f} руб/{i[1]}\n"
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
    
    # Админка
    app.add_handler(CallbackQueryHandler(admin_menu, pattern="^admin_menu$"))
    app.add_handler(CallbackQueryHandler(admin_add_ing, pattern="^admin_add_ing$"))
    app.add_handler(CallbackQueryHandler(admin_add_prod, pattern="^admin_add_prod$"))
    app.add_handler(CallbackQueryHandler(admin_add_store, pattern="^admin_add_store$"))
    app.add_handler(CallbackQueryHandler(admin_link, pattern="^admin_link$"))
    app.add_handler(CallbackQueryHandler(link_store_menu, pattern="^linkstore_"))
    app.add_handler(CallbackQueryHandler(toggle_product, pattern="^toggle_"))
    app.add_handler(CallbackQueryHandler(select_adding_ing, pattern="^adding_"))
    app.add_handler(CallbackQueryHandler(save_new_product, pattern="^save_prod$"))
    
    app.add_handler(CallbackQueryHandler(main_menu_callback, pattern="^main_menu$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    job_queue = app.job_queue
    if job_queue:
        job_queue.run_daily(send_night_report, time=datetime.strptime("17:00", "%H:%M").time())

    print("Конструктор запущен!")
    app.run_polling()

if __name__ == "__main__":
    main()
