import sqlite3
from datetime import date, timedelta, datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

# --- ВАШИ ДАННЫЕ ---
TOKEN = "9292282503:AAGTBe4jryIjP_XrU1OjZQgCD-XWDP3xo-E"
ADMIN_ID = 7014970015  # ВСТАВЬТЕ_СЮДА_ВАШ_ID
BAKER_ID = 8596668517 # ID пекаря

# --- ТОВАРЫ ---
PRODUCTS = [
    ("Булочка сгущ.", 4.69, 15, 20, True),
    ("Хлеб дом.", 50, 0, 60, False),
    ("Хлеб обыч.", 40, 0, 50, False),
    ("Пончики", 25, 0, 50, False),
    ("Пицца", 17.76, 55, 70, True),
    ("Сосиска в тесте", 9.94, 25, 35, True),
    ("Бургер", 60, 85, 100, True),
    ("Сосиска шпаж.", 13.23, 0, 30, False),
]
STORES = ["Магазин 1", "Магазин 2", "Своя точка"]
PROD_DICT = {p[0]: p for p in PRODUCTS}

# --- СКЛАД ---
INGREDIENTS = {
    "Мука": {"qty": 50.0, "min": 10.0, "unit": "кг"},
    "Сахар": {"qty": 20.0, "min": 5.0, "unit": "кг"},
    "Дрожжи": {"qty": 2.0, "min": 0.5, "unit": "кг"},
    "Маргарин": {"qty": 5.0, "min": 1.0, "unit": "кг"},
    "Сгущенка": {"qty": 20.0, "min": 5.0, "unit": "кг"},
    "Сосиски": {"qty": 100.0, "min": 20.0, "unit": "шт"},
    "Сыр": {"qty": 10.0, "min": 2.0, "unit": "кг"},
    "Томат": {"qty": 5.0, "min": 1.0, "unit": "кг"},
    "Панировка": {"qty": 3.0, "min": 1.0, "unit": "кг"},
    "Шпажки": {"qty": 100.0, "min": 20.0, "unit": "шт"},
}

# --- РЕЦЕПТЫ ---
RECIPES = {
    "Булочка сгущ.": {"Мука": 0.05, "Сахар": 0.01, "Дрожжи": 0.001, "Маргарин": 0.004, "Сгущенка": 0.01},
    "Пицца": {"Мука": 0.1, "Сосиски": 0.5, "Сыр": 0.025, "Томат": 0.005},
    "Сосиска в тесте": {"Мука": 0.05, "Сосиски": 1.0},
    "Сосиска шпаж.": {"Мука": 0.1, "Сосиски": 1.0, "Панировка": 0.01, "Шпажки": 1.0},
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

def main_menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📦 Отгрузить товар (Водитель)", callback_data="ship")],
        [InlineKeyboardButton("📊 Ввести остаток (Магазины)", callback_data="left")],
        [InlineKeyboardButton("💰 Прибыль за сегодня", callback_data="profit_today")],
        [InlineKeyboardButton("📈 Прибыль за неделю", callback_data="profit_week")],
        [InlineKeyboardButton("📚 Склад (Сырье)", callback_data="warehouse")],
        [InlineKeyboardButton("🚚 Закуп (Приход)", callback_data="purchase")],
        [InlineKeyboardButton("🔔 Тест уведомления пекарю", callback_data="test_baker")],
    ])

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🥖 Главное меню:", reply_markup=main_menu_kb())

# --- ОТГРУЗКА ---
async def ship_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    kb = [[InlineKeyboardButton(s, callback_data=f"shipstore_{s}")] for s in STORES]
    kb.append([InlineKeyboardButton("⬅️ Главное меню", callback_data="main_menu")])
    await q.edit_message_text("Выбери магазин/точку:", reply_markup=InlineKeyboardMarkup(kb))

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
    kb.append([InlineKeyboardButton("✅ Завершить", callback_data="finish_ship")])
    kb.append([InlineKeyboardButton("⬅️ Главное меню", callback_data="main_menu")])
    await q.edit_message_text(f"📍 {store}\nЖми на товар, чтобы ввести кол-во:", reply_markup=InlineKeyboardMarkup(kb))

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
        await q.edit_message_text("Ничего не добавлено. Отмена.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Меню", callback_data="main_menu")]]))
        return
    conn = sqlite3.connect("bakery.db"); c = conn.cursor()
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
    text += "\n📉 Склад обновлен."
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
        kb.append([InlineKeyboardButton(f"{name} ({data['unit']})", callback_data=f"buy_{name}")])
    kb.append([InlineKeyboardButton("⬅️ Главное меню", callback_data="main_menu")])
    await q.edit_message_text("Что закупаем?", reply_markup=InlineKeyboardMarkup(kb))

async def select_purchase(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    ing = q.data.replace("buy_", "")
    ctx.user_data["buy_ing"] = ing
    unit = INGREDIENTS[ing]['unit']
    await q.edit_message_text(f"Сколько {ing} привезли? (в {unit})\nНапиши просто число:")

# --- ОСТАТКИ ---
async def left_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    kb = [[InlineKeyboardButton(s, callback_data=f"leftstore_{s}")] for s in STORES]
    kb.append([InlineKeyboardButton("⬅️ Главное меню", callback_data="main_menu")])
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
    text = f"📊 Остатки в {store} записаны.\nПродано:\n"
    for prod in [p[0] for p in PRODUCTS]:
        c.execute("SELECT SUM(qty) FROM shipments WHERE store=? AND product=? AND date=?", (store, prod, today))
        shipped = c.fetchone()[0] or 0
        left = data.get(prod, 0)
        sold = shipped - left
        if shipped > 0:
            price = PROD_DICT[prod][2] if store != "Своя точка" else PROD_DICT[prod][3]
            profit = sold * (price - PROD_DICT[prod][1])
            text += f"• {prod}: {sold} шт = {profit:.0f} ₽\n"
    conn.commit(); conn.close()
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Меню", callback_data="main_menu")]]))
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
    text += f"💵 ИТОГО: {total:.0f} ₽"
    conn.close()
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Меню", callback_data="main_menu")]]))

# --- ОБРАБОТЧИК ТЕКСТА ---
async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.replace(",", ".")
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
        await update.message.reply_text(f"✅ Принято! {ing} теперь: {INGREDIENTS[ing]['qty']:.2f} {INGREDIENTS[ing]['unit']}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Меню", callback_data="main_menu")]]))

    elif "current_product" in ctx.user_data:
        prod = ctx.user_data.pop("current_product")
        if qty >= 0: ctx.user_data["leftover"][prod] = qty
        ctx.user_data["idx"] += 1
        class FQ:
            async def edit_message_text(self, t, **kw): await update.message.reply_text(t, **kw)
            async def answer(self): pass
        await ask_next_leftover(FQ(), ctx)

async def main_menu_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    ctx.user_data.clear()
    await q.edit_message_text("🥖 Главное меню:", reply_markup=main_menu_kb())

# --- ТЕСТ УВЕДОМЛЕНИЯ И НОЧНОЙ ОТЧЕТ ---
async def test_baker_notification(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    text = "🌙 ПРОБНЫЙ Ночной отчет (остатки на складе):\n\n"
    for name, data in INGREDIENTS.items():
        text += f"• {name}: {data['qty']:.2f} {data['unit']}\n"
    try:
        await ctx.bot.send_message(chat_id=BAKER_ID, text=text)
        await q.edit_message_text("✅ Тестовое сообщение отправлено пекарю! Проверь её Телеграм.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Меню", callback_data="main_menu")]]))
    except Exception as e:
        await q.edit_message_text(f"❌ Ошибка! Пекарь не нажал /start у бота, или ID неверный.\nДетали: {e}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Меню", callback_data="main_menu")]]))

async def send_night_report(ctx: ContextTypes.DEFAULT_TYPE):
    text = "🌙 Ночной отчет (остатки на складе):\n\n"
    for name, data in INGREDIENTS.items():
        text += f"• {name}: {data['qty']:.2f} {data['unit']}\n"
    try:
        await ctx.bot.send_message(chat_id=BAKER_ID, text=text)
    except:
        print("Ошибка ночной отправки. Пекарь заблокировал бота.")

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
    app.add_handler(CallbackQueryHandler(test_baker_notification, pattern="^test_baker$"))
    app.add_handler(CallbackQueryHandler(main_menu_callback, pattern="^main_menu$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    job_queue = app.job_queue
    if job_queue:
        # Время по UTC (на сервере). Если у вас МСК, то 00:00 МСК = 21:00 UTC.
        job_queue.run_daily(send_night_report, time=datetime.strptime("21:00", "%H:%M").time())

    print("Бот запущен! Финальная сборка готова.")
    app.run_polling()

if __name__ == "__main__":
    main()
