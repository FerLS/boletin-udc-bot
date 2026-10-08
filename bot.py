"""
Bot de Telegram: cada lunes a las 09:00 (Europe/Madrid) envía el enlace
al "Boletín do estudantado" de la UDC publicado en Telegraph ese día.

URL de ejemplo: https://telegra.ph/Boletín-do-estudantado-10-05  (MM-DD)

Si a las 09:00 el boletín aún no está publicado (el del 05/10 salió a las
12:05), el bot sigue comprobando cada POLL_MINUTES hasta MAX_WAIT_HOURS.

Variables de entorno:
  TELEGRAM_TOKEN    token del bot (BotFather)
  TELEGRAM_CHAT_ID  tu chat id
  CRON              (opcional) cron que lanzó la ejecución en GitHub Actions
  DATE              (opcional) fecha YYYY-MM-DD para probar con otro día
  POLL_MINUTES      (opcional, def. 10)
  MAX_WAIT_HOURS    (opcional, def. 5)
"""

import html
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Madrid")
SEND_HOUR = 9
TITLE_SLUG = "Boletín-do-estudantado"
MAX_SUFFIX = 5  # Telegraph añade -2, -3... si el slug ya existe (p. ej. de otro año)
POLL_MINUTES = float(os.getenv("POLL_MINUTES") or 10)
MAX_WAIT_HOURS = float(os.getenv("MAX_WAIT_HOURS") or 5)


def page_url(d: date, suffix: int = 0) -> str:
    slug = f"{TITLE_SLUG}-{d:%m-%d}" + (f"-{suffix}" if suffix > 1 else "")
    return "https://telegra.ph/" + urllib.parse.quote(slug)


def fetch(url: str) -> str | None:
    req = urllib.request.Request(url, headers={"User-Agent": "boletin-bot/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def meta(page: str, prop: str) -> str | None:
    for tag in re.findall(r"<meta\b[^>]*>", page):
        if f'property="{prop}"' in tag or f'name="{prop}"' in tag:
            m = re.search(r'content="([^"]*)"', tag)
            if m:
                return html.unescape(m.group(1))
    return None


def find_bulletin(d: date) -> tuple[str, str] | None:
    """Devuelve (url, titular) del boletín publicado el día d, o None."""
    for suffix in [0] + list(range(2, MAX_SUFFIX + 1)):
        url = page_url(d, suffix)
        page = fetch(url)
        if page is None:
            return None  # si no existe este, tampoco existirán los siguientes
        published = meta(page, "article:published_time")
        if published:
            pub = datetime.strptime(published, "%Y-%m-%dT%H:%M:%S%z").astimezone(TZ)
            if pub.date() != d:
                continue  # es de otro año, probar el siguiente sufijo
        desc = meta(page, "og:description") or ""
        headline = desc.strip().splitlines()[0] if desc.strip() else ""
        return url, headline
    return None


def send(text: str) -> None:
    token = os.environ["TELEGRAM_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage", data=data
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        r.read()


def main() -> int:
    now = datetime.now(TZ)

    # GitHub Actions solo entiende UTC: hay dos crons (07 y 08 UTC) y aquí
    # nos quedamos con el que corresponde a las 09:00 de Madrid según el
    # horario de verano/invierno.
    cron = (os.getenv("CRON") or "").strip()
    if cron:
        cron_utc_hour = int(cron.split()[1])
        offset = int(now.utcoffset().total_seconds() // 3600)
        if cron_utc_hour != SEND_HOUR - offset:
            print(f"Cron {cron!r} no corresponde a las {SEND_HOUR}:00 de Madrid hoy. Salgo.")
            return 0

    d = date.fromisoformat(os.environ["DATE"]) if os.getenv("DATE") else now.date()
    deadline = time.monotonic() + MAX_WAIT_HOURS * 3600

    while True:
        result = find_bulletin(d)
        if result:
            url, headline = result
            text = f"📰 Boletín do estudantado · {d:%d/%m}"
            if headline:
                text += f"\n\nDestacado: {headline}"
            text += f"\n\n{url}"
            send(text)
            print(f"Enviado: {url}")
            return 0
        if time.monotonic() >= deadline:
            send(
                f"📰 Hoy ({d:%d/%m}) no ha aparecido el Boletín do estudantado.\n"
                f"Comprobado: {page_url(d)}"
            )
            print("No publicado; aviso enviado.")
            return 0
        print(f"Aún no publicado ({page_url(d)}). Reintento en {POLL_MINUTES:g} min.")
        time.sleep(POLL_MINUTES * 60)


if __name__ == "__main__":
    sys.exit(main())
