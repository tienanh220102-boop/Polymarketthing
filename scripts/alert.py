"""Telegram alert sender + file logger for smart money detection."""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lib import http

LOG_PATH = Path(__file__).parent.parent / "outputs" / "alerts.log"


def _esc(text: str) -> str:
    """Escape HTML special chars for Telegram HTML parse_mode."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _odds_summary(market: dict) -> str:
    """Current odds of all outcomes, e.g. 'Yes 72% / No 28%'."""
    outcomes = market.get("outcomes") or []
    top = sorted(outcomes, key=lambda o: o["price"], reverse=True)[:4]
    return " / ".join(f"{_esc(o['name'])} {o['price'] * 100:.0f}%" for o in top)


def format_message(market: dict, outcome: dict, old_price: float, alert_type: str) -> str:
    """Build HTML-formatted Telegram message."""
    title = _esc(market.get("title", ""))
    question = _esc(market.get("question", ""))
    outcome_name = _esc(outcome["name"])
    new_price = outcome["price"]
    delta = new_price - old_price
    sign = "+" if delta >= 0 else ""
    direction = "UP" if delta >= 0 else "DOWN"

    vol = market.get("volume24hr") or 0
    liq = market.get("liquidity") or 0
    end_date = market.get("end_date", "")
    url = market.get("url", "")

    type_label = "PRICE MOVE" if alert_type == "price_move" else "VOLUME SPIKE"

    lines = [
        f"POLYMARKET ALERT - {type_label}",
        "",
        f"<b>{title}</b>",
    ]

    if question and question != market.get("title", ""):
        lines.append(f"<i>{question}</i>")

    lines += [
        "",
        f"Outcome: <b>{outcome_name}</b>  {direction}",
        f"Odds: <b>{old_price * 100:.0f}%</b>  ->  <b>{new_price * 100:.0f}%</b>  "
        f"(<b>{sign}{delta * 100:.1f}%</b>)",
        f"Volume 24h: <b>${vol:,.0f}</b>",
        f"Liquidity:  <b>${liq:,.0f}</b>",
    ]

    odds = _odds_summary(market)
    if odds:
        lines.append(f"Thị trường hiện tại: <b>{odds}</b>")

    if end_date:
        lines.append(f"Closes: <b>{end_date}</b>")

    if url:
        lines.append(f"\n<a href=\"{url}\">Xem trên Polymarket</a>")

    return "\n".join(lines)


def format_trade_alert(market: dict, trade: dict, outcome_name: str) -> str:
    """Build HTML Telegram message for a large single trade."""
    title = _esc(market.get("title", ""))
    question = _esc(market.get("question", ""))
    size = float(trade.get("size") or 0)
    price = float(trade.get("price") or 0)
    usd = float(trade.get("usd_value") or size * price)
    side = str(trade.get("side") or "?").upper()
    outcome_name = _esc(outcome_name)
    url = market.get("url", "")
    vol = market.get("volume24hr") or 0
    who = _esc(str(trade.get("pseudonym") or str(trade.get("proxyWallet") or "")[:10] or "?"))

    # BUY Yes = whale tin Yes; SELL Yes = whale chống Yes
    stance = "TIN" if side == "BUY" else "CHỐNG" if side == "SELL" else "?"

    lines = [
        "POLYMARKET - LARGE BET DETECTED",
        "",
        f"<b>{title}</b>",
    ]
    if question and question != title:
        lines.append(f"<i>{question}</i>")
    lines += [
        "",
        f"Bet: <b>{side} {outcome_name}</b>  @{price * 100:.0f}%  ({stance} {outcome_name})",
        f"Giá trị: <b>${usd:,.0f}</b>  ({size:,.0f} shares)",
        f"Trader: <b>{who}</b>",
        f"Volume 24h: <b>${vol:,.0f}</b>",
    ]
    odds = _odds_summary(market)
    if odds:
        lines.append(f"Thị trường hiện tại: <b>{odds}</b>")
    if url:
        lines.append(f"\n<a href=\"{url}\">Xem trên Polymarket</a>")
    return "\n".join(lines)


def send_telegram(text: str) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    result = http.post_json(
        url,
        {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": False},
        timeout=10,
    )
    return bool(result and result.get("ok"))


def log_to_file(text: str) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(f"\n[{ts}]\n{text}\n{'=' * 60}\n")


def send_trade_alert(market: dict, trade: dict, outcome_name: str) -> None:
    """Send large-trade alert to Telegram and log to file."""
    text = format_trade_alert(market, trade, outcome_name)
    ok = send_telegram(text)
    status = "OK" if ok else "TELEGRAM_FAIL"
    log_to_file(text)
    size = float(trade.get("size") or 0)
    price = float(trade.get("price") or 0)
    usd = float(trade.get("usd_value") or size * price)
    side = str(trade.get("side") or "?").upper()
    print(
        f"[TRADE {status}] {market['title'][:50]} | "
        f"{side} {outcome_name[:20]} | ${usd:,.0f}"
    )


def send_alert(market: dict, outcome: dict, old_price: float, alert_type: str) -> None:
    """Send alert to Telegram and log to file."""
    text = format_message(market, outcome, old_price, alert_type)

    ok = send_telegram(text)
    status = "OK" if ok else "TELEGRAM_FAIL"
    log_to_file(text)

    # ASCII-safe console output (Windows cp1252 safe)
    title_short = market["title"][:60]
    delta = outcome["price"] - old_price
    sign = "+" if delta >= 0 else ""
    print(
        f"[ALERT {status}] {title_short} | {outcome['name']} | "
        f"{old_price * 100:.0f}% -> {outcome['price'] * 100:.0f}% ({sign}{delta * 100:.1f}%)"
    )
