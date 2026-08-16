# Bot Biwenger

Gestor personal de tu liga en [Biwenger](https://biwenger.as.com/). Recomienda alineación, mercado y ventas por Telegram. **No ejecuta nada en Biwenger hasta que pulsas un botón.** Empieza en modo `DRY_RUN`.

Biwenger no tiene API pública. El cliente habla con los mismos endpoints que usa la web (`api/v2`). Si un endpoint cambia, el fallo queda aislado en `biwenger/client.py`.

## Qué hace

| Comando | Acción |
|---|---|
| `/alineacion` | XI + formación + capitán según forma, rival y titularidad |
| `/mercado` | Gangas, techo de puja y botón para pujar |
| `/vender` | Lesionados, precio a la baja, calendario duro |
| `/equipo` | Plantilla, saldo, tendencia de precio |
| `/calendario` | Próximos 5 rivales de tus clubs |
| `/clasificacion` | Tabla de tu liga |
| `/auto` | Pone el XI ~4 h antes del primer partido (off por defecto) |
| `/resumen` | Briefing de ahora |
| `/token` | Renueva el token si caduca (login social) |

Cada día, a las 10:00 (Europe/Madrid), te manda el briefing solo.

## Arranque rápido

```powershell
cd C:\Users\juanl\biwenger-bot
copy .env.example .env
# edita .env con tus datos
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py --check
python main.py
```

O `run.bat --check` / `run.bat`.

## Configuración

Copia `.env.example` a `.env`.

**Login**

- Email + contraseña de Biwenger, o
- Login social: en `biwenger.as.com` logueado, F12 → Console:

  ```js
  localStorage.getItem('satellizer_token')
  ```

  Pega el valor en `BIWENGER_TOKEN`. Si caduca, `/token <nuevo>` desde Telegram.

`BIWENGER_LEAGUE_ID` y `BIWENGER_USER_ID` se resuelven solos. El user id es el **equipo dentro de la liga**, no el id de cuenta.

Si ves `Old version`, actualiza `BIWENGER_APP_VERSION` (F12 → Network → header `X-Version`).

**Telegram**

1. Habla con [@BotFather](https://t.me/BotFather) → `/newbot` → copia el token a `TELEGRAM_BOT_TOKEN`.
2. Arranca el bot y escríbele `/start`. En el log (o en el propio mensaje) verás tu `chat_id`.
3. Ponlo en `TELEGRAM_CHAT_ID` y reinicia. Solo ese chat puede usarlo.

**Modo seguro**

`DRY_RUN=true` (por defecto): los botones simulan pujar/alinear/vender. Cuando lo hayas mirado un par de días:

```
DRY_RUN=false
```

`BUDGET_SAFETY_MARGIN` es dinero que nunca entra en las pujas.

## Comandos locales

```
python main.py --check      # login + ids
python main.py --once       # XI + mercado en consola
python main.py --print squad
python main.py              # Telegram + briefing diario
```

## Cómo puntúa al XI

1. Forma reciente (últimas 5, más peso a lo último). Si no hay datos, media de la temporada pasada.
2. Dificultad del próximo rival (la que calcula Biwenger).
3. Si suele ser titular.
4. Lesionados y sancionados a 0. Prueba 4-3-3, 4-4-2, 3-5-2, 3-4-3, 5-3-2, 5-4-1 y se queda la mejor. Capitán = más puntos esperados.

## Aviso

Automatizar la cuenta puede chocar con las normas de Biwenger (riesgo de ban, no legal). Por eso:

- Empieza en `DRY_RUN`.
- No hace sniping a última hora ni martillea el mercado.
- Las escrituras van una a una y solo si pulsas.

No está afiliado a Biwenger ni a Diario AS.

## Tests

```
pytest -q
```
