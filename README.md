# 🇻🇪 BolivAr Bot — Telegram

Bot de Telegram que compara precios en Bs vs dólares en efectivo usando tasas BCV y Binance P2P en tiempo real.

---

## 🚀 Despliegue en Railway (paso a paso)

### Paso 1: Crea tu bot en Telegram
1. Abre Telegram y busca **@BotFather**
2. Envía `/newbot`
3. Ponle un nombre: `BolivAr Bot`
4. Ponle un usuario: `bolivar_tasa_bot` (debe terminar en `bot`)
5. Copia el **token** que te da BotFather (ej: `7123456789:AAFxxx...`)

### Paso 2: Obtén tu API Key de Anthropic
1. Ve a https://console.anthropic.com
2. Crea una cuenta o inicia sesión
3. Ve a **API Keys** → **Create Key**
4. Copia la clave (empieza con `sk-ant-...`)

### Paso 3: Sube el código a GitHub
1. Crea una cuenta en https://github.com si no tienes
2. Crea un repositorio nuevo llamado `bolivar-bot`
3. Sube estos archivos:
   - `bot.py`
   - `requirements.txt`
   - `railway.toml`
   - `Procfile`

   Puedes hacerlo directamente desde la web de GitHub con "Add file → Upload files"

### Paso 4: Despliega en Railway
1. Ve a https://railway.app y crea una cuenta (con GitHub)
2. Haz clic en **"New Project"**
3. Selecciona **"Deploy from GitHub repo"**
4. Elige tu repositorio `bolivar-bot`
5. Railway detectará el proyecto automáticamente

### Paso 5: Configura las variables de entorno
En Railway, ve a tu proyecto → **Variables** → agrega:

| Variable | Valor |
|----------|-------|
| `TELEGRAM_TOKEN` | El token de BotFather |
| `ANTHROPIC_API_KEY` | Tu API key de Anthropic |

### Paso 6: ¡Listo!
Railway desplegará el bot automáticamente. En 1-2 minutos tu bot estará en línea.

Busca tu bot en Telegram por el nombre de usuario que elegiste y escríbele `/start` 🎉

---

## 💬 Comandos del Bot

| Comando | Descripción |
|---------|-------------|
| `/start` | Iniciar el bot y cargar tasas |
| `/tasas` | Actualizar tasas BCV y Binance |
| `/ayuda` | Ver instrucciones de uso |
| `/limpiar` | Borrar historial de conversación |

## 📱 Cómo usarlo

1. Escribe `/tasas` para obtener las tasas del día
2. Luego escribe los dos precios: `Bs 150.000 o $4 efectivo`
3. El bot te dice cuál opción te cuesta menos dólares reales ✅

---

## 🔧 Ejecutar localmente (para probar)

```bash
pip install -r requirements.txt
export TELEGRAM_TOKEN="tu_token_aqui"
export ANTHROPIC_API_KEY="tu_api_key_aqui"
python bot.py
```
