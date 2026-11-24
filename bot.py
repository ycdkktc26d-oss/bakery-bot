import sqlite3
from datetime import date, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

# --- ВАШИ ДАННЫЕ ---
TOKEN = "9292282503:AAGTBe4jryIjP_XrU1OjZQgCD-XWDP3xo-E"
ADMIN_ID = 7014970015  # ВСТАВЬТЕ_СЮДА_ВАШ_ID

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
        [InlineKeyboardButton("📦 Отгрузка", callback_data="ship")],
        [InlineKeyboardButton("📊 Ввести остаток", callback_data="left")],
        [InlineKeyboardButton("💰 Прибыль за сегодня", callback_data="profit_today")],
        [InlineKeyboardButton("📈 Прибыль за неделю", callback_data="profit_week")],
    ]
    await update.message.reply_text("🥖 Пекарня — выберите действие:", reply_markup=InlineKeyboardMarkup(kb))

async def ship_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    kb = [[InlineKeyboardButton(s, callback_data=f"shipstore_{s}")] for s in STORES]
    await q.edit_message_text("Куда отгружаем?", reply_markup=InlineKeyboardMarkup(kb))

async def ship_store(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    store = q.data.replace("shipstore_", "")
    ctx.user_data.update({"store": store, "ship": {}, "idx": 0, "mode": "ship"})
    await ask_next(q, ctx)

async def ask_next(q, ctx):
    mode = ctx.user_data["mode"]
    idx = ctx.user_data["idx"]
    if mode == "ship":
        avail = [p[0] for p in PRODUCTS if p[4]]
    else:
        avail = [p[0] for p in PRODUCTS]
    if idx >= len(avail):
        await save_and_finish(q, ctx)
        return
    prod = avail[idx]
    ctx.user_data["current_product"] = prod
    await q.edit_message_text(f"{prod}: введите количество (0 — пропустить)")

async def save_and_finish(q, ctx):
    conn = sqlite3.connect("bakery.db"); c = conn.cursor()
    today = str(date.today())
    mode = ctx.user_data["mode"]
    store = ctx.user_data["store"]
    data = ctx.user_data.get("ship" if mode == "ship" else "leftover", {})
    if mode == "ship":
        for prod, qty in data.items():
            c.execute("INSERT INTO shipments (store, product, qty, date) VALUES (?,?,?,?)",
                      (store, prod, qty, today))
        text = f"✅ Отгружено в {store}:\n" + "\n".join(f"{k}: {v} шт" for k, v in data.items())
    else:
        for prod, qty in data.items():
            c.execute("INSERT INTO leftovers (store, product, qty, date) VALUES (?,?,?,?)",
                      (store, prod, qty, today))
        text = f"📊 Остатки в {store} записаны. Продано сегодня:\n"
        for prod in [p[0] for p in PRODUCTS]:
            c.execute("SELECT SUM(qty) FROM shipments WHERE store=? AND product=? AND date=?", (store, prod, today))
            shipped = c.fetchone()[0] or 0
            left = data.get(prod, 0)
            sold = shipped - left
            if shipped > 0:
                price = PROD_DICT[prod][2] if store != "Своя точка" else PROD_DICT[prod][3]
                profit = sold * (price - PROD_DICT[prod][1])
                text += f"{prod}: продано {sold} шт, прибыль {profit:.2f} ₽\n"
    conn.commit(); conn.close()
    await q.edit_message_text(text)

async def left_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    kb = [[InlineKeyboardButton(s, callback_data=f"leftstore_{s}")] for s in STORES]
    await q.edit_message_text("Где вводим остаток?", reply_markup=InlineKeyboardMarkup(kb))

async def left_store(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    store = q.data.replace("leftstore_", "")
    ctx.user_data.update({"store": store, "leftover": {}, "idx": 0, "mode": "leftover"})
    await ask_next(q, ctx)

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

async def handle_qty(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if "current_product" not in ctx.user_data: return
    try:
        qty = int(update.message.text)
    except:
        await update.message.reply_text("Введите целое число")
        return
    prod = ctx.user_data.pop("current_product")
    mode = ctx.user_data["mode"]
    key = "ship" if mode == "ship" else "leftover"
    if qty > 0:
        ctx.user_data[key][prod] = qty
    ctx.user_data["idx"] += 1
    class FQ:
        async def edit_message_text(self, t, **kw): await update.message.reply_text(t, **kw)
        async def answer(self): pass
    await ask_next(FQ(), ctx)

def main():
    init_db()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(ship_menu, pattern="^ship$"))
    app.add_handler(CallbackQueryHandler(ship_store, pattern="^shipstore_"))
    app.add_handler(CallbackQueryHandler(left_menu, pattern="^left$"))
    app.add_handler(CallbackQueryHandler(left_store, pattern="^leftstore_"))
    app.add_handler(CallbackQueryHandler(profit_report, pattern="^profit_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_qty))
    print("Бот запущен и готов к работе!")
    app.run_polling()

if __name__ == "__main__":
    main()
