import sqlite3
from datetime import date, timedelta, datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

# --- ВАШИ ДАННЫЕ ---
TOKEN = "9292282503:AAGTBe4jryIjP_XrU1OjZQgCD-XWDP3xo-E"
ADMIN_ID = 7014970015  # ВСТАВЬТЕ_СЮДА_ВАШ_ID (твой личный ID)

# --- ТОВАРЫ (название, себест, опт, розница, возим_в_магазины) ---
PRODUCTS = [
    ("Булочка со сгущёнкой", 4.69, 15, 20, True),
    ("Хлеб домашний", 50, 0, 60, False),
    ("Хлеб обычный", 40, 0, 50, False),
    ("Пончики", 25, 0, 50, False),
    ("Пицца", 17.76, 55, 70, True),
    ("Сосиска в тесте", 9.94, 25, 35, True),
    ("Бургер", 60, 85, 100, True),
    ("Сосиска на шпажке", 13.23, 0, 30, False),
]
STORES = ["Магазин 1", "Магазин 2", "Своя точка"]
PROD_DICT = {p[0]: p for p in PRODUCTS}

# --- СКЛАД (Сырьё: название, текущий_остаток, минимальный_остаток, ед_изм) ---
INGREDIENTS = {
    "Мука": {"qty": 50.0, "min": 10.0, "unit": "кг"},
    "Сахар": {"qty": 20.0, "min": 5.0, "unit": "кг"},
    "Дрожжи": {"qty": 2.0, "min": 0.5, "unit": "кг"},
    "Маргарин": {"qty": 5.0, "min": 1.0, "unit": "кг"},
    "Сгущенка": {"qty": 20.0, "min": 5.0, "unit": "кг"},
    "Сосиски": {"qty": 100.0, "min": 20.0, "unit": "шт"},
    "Сыр Моцарелла": {"qty": 10.0, "min": 2.0, "unit": "кг"},
    "Томат (соус)": {"qty": 5.0, "min": 1.0, "unit": "кг"},
    "Панировка": {"qty": 3.0, "min": 1.0, "unit": "кг"},
    "Шпажки": {"qty": 100.0, "min": 20.0, "unit": "шт"},
}

# --- РЕЦЕПТЫ (сколько сырья уходит на 1 партию) ---
# (название товара: {ингредиент: сколько_тратится})
RECIPES = {
    "Булочка со сгущёнкой": {"Мука": 0.05, "Сахар": 0.01, "Дрожжи": 0.001, "Маргарин": 0.004, "Сгущенка": 0.01},
    "Пицца": {"Мука": 0.1, "Сосиски": 0.5, "Сыр Моцарелла": 0.025, "Томат (соус)": 0.005},
    "Сосиска в тесте": {"Мука": 0.05, "Сосиски": 1.0},
    "Сосиска на шпажке": {"Мука": 0.1, "Сосиски": 1.0, "Панировка": 0.01, "Шпажки": 1.0},
}

def init_db():
    conn = sqlite3.connect("bakery.db")
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS shipments
                 (id INTEGER PRIMARY KEY, store TEXT, product TEXT, qty INTEGER, date TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS leftovers
                 (id INTEGER PRIMARY KEY, store TEXT, product TEXT, qty INTEGER, date TEXT)""")
    conn.commit()
    conn.close()

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    kb = [
        [InlineKeyboardButton("📦 Отгрузить товар (Водитель)", callback_data="ship")],
        [InlineKeyboardButton("📊 Ввести остаток (Магазины)", callback_data="left")],
        [InlineKeyboardButton("💰 Прибыль за сегодня", callback_data="profit_today")],
        [InlineKeyboardButton("📈 Прибыль за неделю", callback_data="profit_week")],
        [InlineKeyboardButton("📚 Склад (Сырье)", callback_data="warehouse")],
        [InlineKeyboardButton("🚚 Закуп (Приход сырья)", callback_data="purchase")],
    ]
    await update.message.reply_text("🥖 Пекарня — Главное меню:", reply_markup=InlineKeyboardMarkup(kb))

# --- ОТГРУЗКА (ВОДИТЕЛЬ) ---
async def ship_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    kb = [[InlineKeyboardButton(s, callback_data=f"shipstore_{s}")] for s in STORES if s != "Своя точка"]
    kb.append([InlineKeyboardButton("⬅️ Назад", callback_data="back_to_start")])
    await q.edit_message_text("Выбери магазин для отгрузки:", reply_markup=InlineKeyboardMarkup(kb))

async def ship_store(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    store = q.data.replace("shipstore_", "")
    ctx.user_data["store"] = store
    ctx.user_data["ship_data"] = {}
    await show_ship_keyboard(q, ctx)

async def show_ship_keyboard(q, ctx):
    store = ctx.user_data["store"]
    data = ctx.user_data["ship_data"]
    kb = []
    for p in PRODUCTS:
        if p[4]: 
            qty = data.get(p[0], 0)
            kb.append([InlineKeyboardButton(f"{p[0]}: {qty} шт", callback_data=f"add_{p[0]}")])
    kb.append([InlineKeyboardButton("✅ Завершить отгрузку", callback_data="finish_ship")])
    kb.append([InlineKeyboardButton("⬅️ Отмена", callback_data="back_to_start")])
    await q.edit_message_text(f"📍 {store}\nНажимай на товар, чтобы ввести количество:", reply_markup=InlineKeyboardMarkup(kb))

async def add_product_qty(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    prod = q.data.replace("add_", "")
    ctx.user_data["current_prod"] = prod
    await q.edit_message_text(f"Введи количество для «{prod}» (или 0, чтобы убрать):")

async def finish_ship(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    store = ctx.user_data["store"]
    data = ctx.user_data["ship_data"]
    if not data:
        await q.edit_message_text("Ты ничего не добавил. Отгрузка отменена.")
        return
    conn = sqlite3.connect("bakery.db"); c = conn.cursor()
    today = str(date.today())
    for prod, qty in data.items():
        c.execute("INSERT INTO shipments (store, product, qty, date) VALUES (?,?,?,?)", (store, prod, qty, today))
    conn.commit(); conn.close()
    
    # --- АВТОМАТИЧЕСКОЕ СПИСАНИЕ СО СКЛАДА ---
    for prod, qty in data.items():
        if prod in RECIPES:
            for ing, amount_per_unit in RECIPES[prod].items():
                total_needed = amount_per_unit * qty
                if ing in INGREDIENTS:
                    INGREDIENTS[ing]["qty"] -= total_needed
                    # Если остаток стал меньше минимума - предупреждаем
                    if INGREDIENTS[ing]["qty"] <= INGREDIENTS[ing]["min"]:
                        pass # В реале тут надо отправить сообщение админу, но для теста просто вычтем

    text = f"✅ Успешно отгружено в {store}:\n" + "\n".join(f"• {k}: {v} шт" for k, v in data.items())
    text += "\n\n📉 Склад автоматически обновлен по рецептам."
    await q.edit_message_text(text)
    ctx.user_data.clear()

# --- СКЛАД ---
async def warehouse_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    text = "📚 Остатки на складе:\n\n"
    for name, data in INGREDIENTS.items():
        text += f"{name}: {data['qty']:.1f} {data['unit']}\n"
    
    kb = [[InlineKeyboardButton("⬅️ Назад", callback_data="back_to_start")]]
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))

# --- ЗАКУП ---
async def purchase_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    kb = []
    for name in INGREDIENTS.keys():
        kb.append([InlineKeyboardButton(name, callback_data=f"buy_{name}")])
    kb.append([InlineKeyboardButton("⬅️ Назад", callback_data="back_to_start")])
    await q.edit_message_text("Что закупаем?", reply_markup=InlineKeyboardMarkup(kb))

async def select_purchase(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    ing = q.data.replace("buy_", "")
    ctx.user_data["buy_ing"] = ing
    await q.edit_message_text(f"Сколько {ing} привезли? (в {INGREDIENTS[ing]['unit']})")

# --- ОСТАТКИ ---
async def left_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    kb = [[InlineKeyboardButton(s, callback_data=f"leftstore_{s}")] for s in STORES]
    kb.append([InlineKeyboardButton("⬅️ Назад", callback_data="back_to_start")])
    await q.edit_message_text("Где вводим остаток?", reply_markup=InlineKeyboardMarkup(kb))

async def left_store(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    store = q.data.replace("leftstore_", "")
    ctx.user_data.update({"store": store, "leftover": {}, "idx": 0, "mode": "leftover"})
    await ask_next_leftover(q, ctx)

async def ask_next_leftover(q, ctx):
    idx = ctx.user_data["idx"]
    avail = [p[0] for p in PRODUCTS]
    if idx >= len(avail):
        await save_leftovers(q, ctx)
        return
    prod = avail[idx]
    ctx.user_data["current_product"] = prod
    await q.edit_message_text(f"Остаток «{prod}» (введи число):")

async def save_leftovers(q, ctx):
    conn = sqlite3.connect("bakery.db"); c = conn.cursor()
    today = str(date.today())
    store = ctx.user_data["store"]
    data = ctx.user_data.get("leftover", {})
    for prod, qty in data.items():
        c.execute("INSERT INTO leftovers (store, product, qty, date) VALUES (?,?,?,?)", (store, prod, qty, today))
    text = f"📊 Остатки в {store} записаны.\n"
    for prod in [p[0] for p in PRODUCTS]:
        c.execute("SELECT SUM(qty) FROM shipments WHERE store=? AND product=? AND date=?", (store, prod, today))
        shipped = c.fetchone()[0] or 0
        left = data.get(prod, 0)
        sold = shipped - left
        if shipped > 0:
            price = PROD_DICT[prod][2] if store != "Своя точка" else PROD_DICT[prod][3]
            profit = sold * (price - PROD_DICT[prod][1])
            text += f"{prod}: продано {sold} шт, прибыль {profit:.0f} ₽\n"
    conn.commit(); conn.close()
    await q.edit_message_text(text)
    ctx.user_data.clear()

# --- ПРИБЫЛЬ ---
async def profit_report(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    days = 1 if q.data == "profit_today" else 7
    since = str(date.today() - timedelta(days=days-1))
    conn = sqlite3.connect("bakery.db"); c = conn.cursor()
    text = f"💰 Прибыль за {days} дн.:\n\n"
    total = 0
    for store in STORES:
        text += f"📍 {store}\n"
        store_total = 0
        for prod in [p[0] for p in PRODUCTS]:
            c.execute("SELECT SUM(qty) FROM shipments WHERE store=? AND product=? AND date>=?", (store, prod, since))
            shipped = c.fetchone()[0] or 0
            if shipped == 0: continue
            c.execute("SELECT SUM(qty) FROM leftovers WHERE store=? AND product=? AND date>=?", (store, prod, since))
            left = c.fetchone()[0] or 0
            sold = shipped - left
            price = PROD_DICT[prod][2] if store != "Своя точка" else PROD_DICT[prod][3]
            profit = sold * (price - PROD_DICT[prod][1])
            store_total += profit
            text += f"  {prod}: {sold} шт = {profit:.0f} ₽\n"
        text += f"  Итого: {store_total:.0f} ₽\n\n"
        total += store_total
    text += f"💵 ОБЩАЯ ПРИБЫЛЬ: {total:.0f} ₽"
    conn.close()
    await q.edit_message_text(text)

# --- ОБРАБОТЧИКИ ТЕКСТА ---
async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
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
        INGREDIENTS[ing]["qty"] += qty
        await update.message.reply_text(f"✅ Принято! Теперь {ing} на складе: {INGREDIENTS[ing]['qty']} {INGREDIENTS[ing]['unit']}")

    elif "current_product" in ctx.user_data:
        prod = ctx.user_data.pop("current_product")
        if qty >= 0: ctx.user_data["leftover"][prod] = qty
        ctx.user_data["idx"] += 1
        class FQ:
            async def edit_message_text(self, t, **kw): await update.message.reply_text(t, **kw)
            async def answer(self): pass
        await ask_next_leftover(FQ(), ctx)

async def back_to_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    ctx.user_data.clear()
    kb = [
        [InlineKeyboardButton("📦 Отгрузить товар (Водитель)", callback_data="ship")],
        [InlineKeyboardButton("📊 Ввести остаток (Магазины)", callback_data="left")],
        [InlineKeyboardButton("💰 Прибыль за сегодня", callback_data="profit_today")],
        [InlineKeyboardButton("📈 Прибыль за неделю", callback_data="profit_week")],
        [InlineKeyboardButton("📚 Склад (Сырье)", callback_data="warehouse")],
        [InlineKeyboardButton("🚚 Закуп (Приход сырья)", callback_data="purchase")],
    ]
    await q.edit_message_text("Главное меню:", reply_markup=InlineKeyboardMarkup(kb))

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
    app.add_handler(CallbackQueryHandler(profit_report, pattern="^profit_"))
    app.add_handler(CallbackQueryHandler(warehouse_menu, pattern="^warehouse$"))
    app.add_handler(CallbackQueryHandler(purchase_menu, pattern="^purchase$"))
    app.add_handler(CallbackQueryHandler(select_purchase, pattern="^buy_"))
    app.add_handler(CallbackQueryHandler(back_to_start, pattern="^back_to_start$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    print("Бот запущен! Склад и отгрузки в работе.")
    app.run_polling()

if __name__ == "__main__":
    main()
