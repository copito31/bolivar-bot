import os
import re
import json
import logging
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


async def fetch_rates(user_id: int) -> tuple[float | None, float | None, str]:
    """Fetch BCV and Binance rates using Claude with web search."""
    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1000,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            system="""Eres un extractor de datos. Tu ÚNICA tarea es buscar las tasas de cambio actuales USD a Bolívares venezolanos (VES/Bs).
Busca:
1. Tasa BCV (Banco Central de Venezuela) oficial - busca "BCV tasa dolar hoy"
2. Tasa Binance P2P USD/VES - busca "Binance P2P tasa bolivar dolar hoy"

Responde ÚNICAMENTE con un JSON sin markdown ni texto adicional:
{"bcv": <número>, "binance": <número>}

Ambas deben ser bolívares por 1 USD.""",
            messages=[{"role": "user", "content": "Obtén las tasas de cambio actuales BCV y Binance P2P para USD a VES ahora mismo."}]
        )

        full_text = "".join(b.text for b in response.content if hasattr(b, "text"))
        match = re.search(r'\{.*?"bcv".*?"binance".*?\}', full_text, re.DOTALL)

        if match:
            rates = json.loads(match.group())
            bcv = float(rates["bcv"])
            binance = float(rates["binance"])
            data = get_user(user_id)
            data["bcv"] = bcv
            data["binance"] = binance
            return bcv, binance, "ok"
        else:
            return None, None, "parse_error"

    except Exception as e:
        logger.error(f"Error fetching rates: {e}")
        return None, None, "error"


def fmt_bs(n: float) -> str:
    """Format number Venezuelan style: dots for thousands, comma for decimals."""
    return f"{n:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


async def ask_claude(user_id: int, message: str) -> str:
    """Send message to Claude with context about rates and Venezuelan pricing logic."""
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
- Pagar en $ efectivo: esos mismos dólares se podrían cambiar en Binance a tasa_Binance → costo real = Bs_precio ÷ tasa_Binance dólares
- MEJOR OPCIÓN: la que cueste menos dólares reales

Ejemplo con BCV=36 y Binance=41, precios Bs 100.000 o $3:
- Pagar Bs: $2,78 (100.000÷36)
- Pagar $ efectivo: $3,00
- Conviene pagar en Bs → ahorras $0,22 (7,3%)

CONSEJO EXTRA: Si el usuario solo tiene dólares pero quiere pagar en Bs, debe cambiarlos en Binance (no en BCV) para obtener más bolívares.

FORMATO DE RESPUESTA (usa Markdown de Telegram):
Cuando te den precios, responde así:

[breve explicación en 1-2 líneas]

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

Habla en español venezolano, sé amigable y conciso. Usa puntos para miles (100.000) y comas para decimales (3,50).
Si no tienes las tasas, indica que el usuario use el comando /tasas."""

    data["history"].append({"role": "user", "content": message})

    # Keep only last 10 messages to avoid token limits
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


# ─── Handlers ────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = ReplyKeyboardMarkup(
        [[KeyboardButton("📊 Actualizar Tasas"), KeyboardButton("❓ Ayuda")]],
        resize_keyboard=True
    )
    await update.message.reply_text(
        "👋 ¡Hola! Soy *BolivAr Bot* 🇻🇪\n\n"
        "Te ayudo a decidir si conviene más pagar en *Bolívares (Bs)* o en *dólares en efectivo ($)*, "
        "tomando en cuenta la tasa BCV y la tasa Binance P2P.\n\n"
        "Primero déjame buscar las tasas de hoy... 🔍\n"
        "_(usa /tasas para actualizar en cualquier momento)_",
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
    else:
        await msg.edit_text(
            "⚠️ No pude obtener las tasas automáticamente.\n\n"
            "Puedes decirme las tasas manualmente, por ejemplo:\n"
            "_\"BCV está a 36,5 y Binance a 41,2\"_\n\n"
            "Y haré el cálculo con esas tasas.",
            parse_mode=ParseMode.MARKDOWN
        )


async def cmd_ayuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "❓ *¿Cómo usar BolivAr Bot?*\n\n"
        "1️⃣ Usa /tasas para obtener las tasas BCV y Binance del día\n"
        "2️⃣ Dime los dos precios del producto:\n"
        "   _\"Bs 100.000 o $3 efectivo\"_\n"
        "3️⃣ Te digo cuál opción te cuesta menos dólares reales ✅\n\n"
        "*¿Por qué importa Binance?*\n"
        "Si pagas en $ efectivo, esos dólares los podrías cambiar en Binance "
        "a una tasa mejor que la BCV. Entonces tu costo real en dólares es menor "
        "que el precio en $ que te piden.\n\n"
        "*Comandos:*\n"
        "/start — Iniciar el bot\n"
        "/tasas — Actualizar tasas BCV y Binance\n"
        "/ayuda — Ver esta ayuda\n"
        "/limpiar — Borrar historial de conversación",
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

    # Handle keyboard buttons
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
            "⚠️ Algo salió mal. Por favor intenta de nuevo.\n"
            "Si el problema persiste, usa /limpiar para reiniciar."
        )


# ─── Main ─────────────────────────────────────────────────────────────────────

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
