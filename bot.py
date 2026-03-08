import os
import re
import json
import logging
import httpx
import anthropic
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode, ChatAction

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# Store rates and conversation history per user
user_data: dict = {}


def get_user(user_id: int) -> dict:
    if user_id not in user_data:
        user_data[user_id] = {
            "bcv": None,
            "binance": None,
            "history": []
        }
    return user_data[user_id]


async def fetch_bcv_rate() -> float | None:
    """Scrape BCV official USD rate from bcv.org.ve"""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml",
        }
        async with httpx.AsyncClient(timeout=15, headers=headers, follow_redirects=True) as c:
            r = await c.get("https://www.bcv.org.ve/")
            text = r.text
            # BCV displays USD rate in a strong tag near "USD"
            usd_match = re.search(
                r'USD.*?<strong[^>]*>\s*([\d]+[,\.][\d]+)\s*</strong>',
                text, re.DOTALL | re.IGNORECASE
            )
            if usd_match:
                rate_str = usd_match.group(1).replace(",", ".")
                return float(rate_str)
            # Fallback pattern
            fallback = re.search(
                r'(?:dolar|USD|usd)[^0-9]*(\d{2,3}[,\.]\d{2,8})',
                text, re.IGNORECASE
            )
            if fallback:
                rate_str = fallback.group(1).replace(",", ".")
                return float(rate_str)
    except Exception as e:
        logger.error(f"BCV scrape error: {e}")
    return None


async def fetch_binance_rate() -> float | None:
    """Fetch Binance P2P VES rate via public API"""
    try:
        payload = {
            "fiat": "VES",
            "page": 1,
            "rows": 5,
            "tradeType": "BUY",
            "asset": "USDT",
            "countries": [],
            "proMerchantAds": False,
            "shieldMerchantAds": False,
            "filterType": "all",
            "periods": [],
            "additionalKycVerifyFilter": 0,
            "publisherType": None,
            "payTypes": [],
            "classifies": ["mass", "profession"]
        }
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0"
        }
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(
                "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search",
                json=payload,
                headers=headers
            )
            data = r.json()
            ads = data.get("data", [])
            if ads:
                prices = [float(ad["adv"]["price"]) for ad in ads[:3]]
                return sum(prices) / len(prices)
    except Exception as e:
        logger.error(f"Binance P2P error: {e}")

    # Fallback: exchangerate-api
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get("https://api.exchangerate-api.com/v4/latest/USD")
            data = r.json()
            ves = data.get("rates", {}).get("VES")
            if ves:
                return float(ves)
    except Exception as e:
        logger.error(f"Fallback rate error: {e}")
    return None


async def fetch_rates(user_id: int) -> tuple[float | None, float | None, str]:
    """Fetch both BCV and Binance rates."""
    try:
        bcv = await fetch_bcv_rate()
        binance = await fetch_binance_rate()
        data = get_user(user_id)
        if bcv:
            data["bcv"] = bcv
        if binance:
            data["binance"] = binance

        if bcv and binance:
            return bcv, binance, "ok"
        elif bcv:
            return bcv, None, "partial_bcv"
        elif binance:
            return None, binance, "partial_binance"
        else:
            return None, None, "error"
    except Exception as e:
        logger.error(f"Error fetching rates: {e}")
        return None, None, "error"


def fmt_bs(n: float) -> str:
    return f"{n:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


async def ask_claude(user_id: int, message: str) -> str:
    data = get_user(user_id)
    bcv = data["bcv"]
    binance = data["binance"]

    system_prompt = f"""Eres BolivAr Bot, un asistente venezolano experto en tasas de cambio que ayuda a decidir si conviene más pagar en Bolívares (Bs) o en dólares en efectivo ($).

TASAS ACTUALES:
- BCV (oficial): {f"Bs {fmt_bs(bcv)} por USD" if bcv else "NO DISPONIBLE — pide al usuario que use /tasas"}
- Binance P2P: {f"Bs {fmt_bs(binance)} por USD" if binance else "NO DISPONIBLE — pide al usuario que use /tasas"}

LÓGICA PRINCIPAL:
Cuando una tienda muestra dos precios (ej: Bs 100.000 o $3 efectivo):
- Pagar en Bs: cuesta Bs_precio ÷ tasa_BCV dólares reales
- Pagar en $ efectivo: esos mismos dólares se podrían cambiar en Binance a tasa_Binance, costo real = Bs_precio ÷ tasa_Binance dólares
- MEJOR OPCIÓN: la que cueste menos dólares reales

Ejemplo con BCV=36 y Binance=41, precios Bs 100.000 o $3:
- Pagar Bs: $2,78 (100.000÷36)
- Pagar $ efectivo: $3,00
- Conviene pagar en Bs → ahorras $0,22 (7,3%)

CONSEJO EXTRA: Si el usuario solo tiene dólares pero quiere pagar en Bs, debe cambiarlos en Binance (no en BCV) para obtener más bolívares.

FORMATO DE RESPUESTA (Markdown de Telegram):
Cuando te den precios responde así:

[breve explicación 1-2 líneas]

📊 *Análisis de Precio*
━━━━━━━━━━━━━━━
💵 Precio en Bs: `[valor]`
💵 Precio en $ efectivo: `[valor]`
━━━━━━━━━━━━━━━
🔵 Pagar en Bs te cuesta: `$[X,XX]`
🔵 Pagar en $ efectivo te cuesta: `$[X,XX]`
💰 Ahorro: `$[X,XX] ([Y]%)`
━━━━━━━━━━━━━━━
✅ *MEJOR OPCIÓN: [Pagar en Bs / Pagar en $ efectivo]*
_Ahorras $[X,XX] ([Y]%)_

Habla en español venezolano, sé amigable y conciso. Usa puntos para miles y comas para decimales."""

    data["history"].append({"role": "user", "content": message})
    history = data["history"][-10:]

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1000,
        system=system_prompt,
        messages=history
    )

    reply = response.content[0].text
    data["history"].append({"role": "assistant", "content": reply})
    return reply


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = ReplyKeyboardMarkup(
        [[KeyboardButton("📊 Actualizar Tasas"), KeyboardButton("❓ Ayuda")]],
        resize_keyboard=True
    )
    await update.message.reply_text(
        "👋 ¡Hola! Soy *BolivAr Bot* 🇻🇪\n\n"
        "Te ayudo a decidir si conviene más pagar en *Bolívares (Bs)* o en *dólares en efectivo ($)*, "
        "tomando en cuenta la tasa BCV y la tasa Binance P2P.\n\n"
        "Primero déjame buscar las tasas de hoy... 🔍",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboard
    )
    await cmd_tasas(update, context)


async def cmd_tasas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.chat.send_action(ChatAction.TYPING)
    msg = await update.message.reply_text("🔍 Buscando tasas actuales...")
    user_id = update.effective_user.id
    bcv, binance, status = await fetch_rates(user_id)

    if status == "ok":
        await msg.edit_text(
            f"✅ *Tasas actualizadas*\n\n"
            f"🏦 *BCV (oficial):* `Bs {fmt_bs(bcv)} / $`\n"
            f"💹 *Binance P2P:* `Bs {fmt_bs(binance)} / $`\n\n"
            f"Ahora dime los dos precios del producto y te digo cuál conviene más 😊\n"
            f"_Ejemplo: Bs 150.000 o $4 efectivo_",
            parse_mode=ParseMode.MARKDOWN
        )
    elif status == "partial_bcv":
        await msg.edit_text(
            f"⚠️ *Tasa parcial*\n\n"
            f"🏦 *BCV:* `Bs {fmt_bs(bcv)} / $`\n"
            f"💹 *Binance P2P:* No disponible\n\n"
            f"Dime la tasa Binance: _\"Binance está a 45\"_",
            parse_mode=ParseMode.MARKDOWN
        )
    elif status == "partial_binance":
        await msg.edit_text(
            f"⚠️ *Tasa parcial*\n\n"
            f"🏦 *BCV:* No disponible\n"
            f"💹 *Binance P2P:* `Bs {fmt_bs(binance)} / $`\n\n"
            f"Dime la tasa BCV: _\"BCV está a 36\"_",
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await msg.edit_text(
            "⚠️ No pude obtener las tasas automáticamente.\n\n"
            "Dime las tasas manualmente:\n"
            "_\"BCV está a 36,5 y Binance a 41,2\"_",
            parse_mode=ParseMode.MARKDOWN
        )


async def cmd_ayuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "❓ *¿Cómo usar BolivAr Bot?*\n\n"
        "1️⃣ Usa /tasas para obtener las tasas del día\n"
        "2️⃣ Dime los dos precios: _\"Bs 100.000 o $3 efectivo\"_\n"
        "3️⃣ Te digo cuál opción te cuesta menos ✅\n\n"
        "*Comandos:*\n"
        "/start — Iniciar\n"
        "/tasas — Actualizar tasas\n"
        "/ayuda — Esta ayuda\n"
        "/limpiar — Borrar historial",
        parse_mode=ParseMode.MARKDOWN
    )


async def cmd_limpiar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in user_data:
        user_data[user_id]["history"] = []
    await update.message.reply_text("🗑️ Historial borrado. ¡Empecemos de nuevo!")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id

    if text == "📊 Actualizar Tasas":
        await cmd_tasas(update, context)
        return
    if text == "❓ Ayuda":
        await cmd_ayuda(update, context)
        return

    await update.message.chat.send_action(ChatAction.TYPING)
    try:
        reply = await ask_claude(user_id, text)
        await update.message.reply_text(reply, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text(
            "⚠️ Algo salió mal. Intenta de nuevo o usa /limpiar."
        )


def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("tasas", cmd_tasas))
    app.add_handler(CommandHandler("ayuda", cmd_ayuda))
    app.add_handler(CommandHandler("limpiar", cmd_limpiar))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("🤖 BolivAr Bot iniciado...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
