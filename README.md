# discount-alert-bot

Bot multiusuario para detectar ofertas en tiendas como `paris.cl` y `lider.cl` y enviar alertas personalizadas por Telegram usando infraestructura gratuita:

- `Vercel` para webhook + cron
- `Supabase` para base de datos

## Arquitectura

- `api/index.py`: entrypoint para Vercel
- `server/app.py`: rutas HTTP
- `services/telegram_bot_service.py`: comandos Telegram
- `services/alert_engine.py`: scraping + matching + envio
- `database/supabase_repository.py`: acceso a Supabase
- `scraper/paris_scraper.py`: scraper de Paris
- `scraper/lider_scraper.py`: scraper de Lider
- `supabase/schema.sql`: esquema SQL

## Que soporta ahora

- multiples usuarios
- multiples suscripciones por usuario
- busquedas especificas como `televisor oled`, `playstation 4`, `iphone 17`
- filtros por keywords include/exclude
- validacion de pagina de producto real
- validacion de stock usando JSON-LD de la PDP
- prevencion de duplicados por usuario y suscripcion
- historial de precios en base de datos

## Uso en Telegram

Flujo principal:

- menu persistente con `Agregar alerta`, `Ver mis alertas`, `Eliminar alerta`, `Ayuda`
- alta guiada paso a paso para no tener que escribir comandos complejos

## Comandos de respaldo

- `/start`
- `/help`
- `/watch televisor oled`
- `/watch cama 2 plaza | min=25 | exclude=soporte,cable | label=Mi cama`
- `/list`
- `/delete 3`

Reglas de `/watch`:

- la primera parte es la busqueda
- `min=` define descuento minimo
- `exclude=` bloquea palabras separadas por coma
- `any=` define palabras opcionales
- `all=` define palabras obligatorias
- `label=` cambia el titulo de la suscripcion
- `stock=false` permite recibir productos aunque no aparezcan `InStock`

Ejemplo:

```text
/watch iphone 17 | min=15 | exclude=funda,cable | label=iPhone 17
```

## Variables de entorno

Copia `.env.example` a `.env` en local.

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_WEBHOOK_SECRET`
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `CRON_SECRET`
- `MIN_DISCOUNT`
- `MAX_ALERTS_PER_RUN`
- `REQUEST_TIMEOUT`
- `REQUEST_RETRIES`
- `REQUIRE_IN_STOCK`

`TELEGRAM_CHAT_ID` queda opcional y solo sirve si quieres pruebas manuales.

## Configurar Supabase

1. Crea un proyecto en Supabase.
2. Ve al SQL Editor.
3. Ejecuta el contenido de [supabase/schema.sql](/c:/Users/leyst/Documents/myapps/app-lab/supabase/schema.sql).
4. Copia:
   - `Project URL`
   - `service_role key`

Usa la `service_role key` solo en Vercel. Nunca en frontend.

## Configurar Telegram

1. Crea el bot con `@BotFather`.
2. Guarda el token.
3. Despliega primero el proyecto en Vercel.
4. Define el webhook:

```text
https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://TU-PROYECTO.vercel.app/api/telegram-webhook&secret_token=TU_SECRET
```

## Desplegar en Vercel

1. Sube el repo a GitHub.
2. Importa el repo en Vercel.
3. Agrega estas variables de entorno en Vercel:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_WEBHOOK_SECRET`
   - `SUPABASE_URL`
   - `SUPABASE_SERVICE_ROLE_KEY`
   - `CRON_SECRET`
   - `MIN_DISCOUNT`
   - `MAX_ALERTS_PER_RUN`
   - `REQUEST_TIMEOUT`
   - `REQUEST_RETRIES`
   - `REQUIRE_IN_STOCK`
4. Vercel leerá [vercel.json](/c:/Users/leyst/Documents/myapps/app-lab/vercel.json) y creará el cron.

Cron actual:

```text
*/10 * * * *
```

Puedes cambiarlo a cada 5 minutos si quieres:

```json
{
  "path": "/api/cron/run-scraper",
  "schedule": "*/5 * * * *"
}
```

## Flujo real del sistema

1. El usuario escribe `/watch televisor oled` al bot.
2. Telegram envia el update al webhook en Vercel.
3. Vercel guarda la suscripcion en Supabase.
4. El cron de Vercel llama `/api/cron/run-scraper`.
5. El scraper busca una vez por cada query activa.
6. El matcher cruza productos contra cada suscripcion.
7. Si encuentra una oferta valida y no duplicada, envia Telegram.
8. Supabase guarda productos, historial y alertas enviadas.

## Ejecucion local

```bash
pip install -r requirements.txt
python main.py
```

Eso ejecuta un ciclo de scraping y matching usando Supabase.

## Notas de escalabilidad

- no se hace un scraper por usuario
- se scrapea una vez por query unica
- luego se reparte a los usuarios correspondientes
- esto escala mucho mejor para multiusuario

## Limitaciones actuales

- `paris.cl` y `lider.cl` estan activos
- las suscripciones son por texto, no por UI web
- el bot no tiene comandos de pausa/edicion todavia
- el scraper depende de la estructura actual de Paris
