"""Polymarket Smart Money Monitor - main entry point.

Usage:
    python scripts/monitor.py              # run continuous polling loop
    python scripts/monitor.py --once       # one cycle, then exit
    python scripts/monitor.py --list       # show current top markets
    python scripts/monitor.py --diagnose   # check config + API connectivity
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime
from pathlib import Path


# ── .env loading (stdlib, no python-dotenv needed) ──────────────────────────

def _load_env() -> None:
    env_path = Path(__file__).parent.parent / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        val = val.strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), val)


_load_env()
sys.path.insert(0, str(Path(__file__).parent))

import alert
import store
from lib import polymarket

# ── Config (read after .env is loaded) ──────────────────────────────────────

POLL_INTERVAL_SEC = int(os.environ.get("POLL_INTERVAL_MINUTES", "10")) * 60
PRICE_THRESHOLD = float(os.environ.get("PRICE_CHANGE_THRESHOLD", "0.10"))
MIN_LIQUIDITY = float(os.environ.get("MIN_LIQUIDITY", "10000"))
TOP_N = int(os.environ.get("TOP_N_MARKETS", "20"))
COOLDOWN_HOURS = int(os.environ.get("ALERT_COOLDOWN_HOURS", "2"))
MIN_TRADE_SIZE = float(os.environ.get("MIN_TRADE_SIZE", "5000"))


# ── Core monitoring logic ────────────────────────────────────────────────────

def run_once() -> int:
    """Fetch markets, compare to last snapshot, send alerts. Returns alert count."""
    print(f"[POLL] Fetching top {TOP_N} markets (min liquidity ${MIN_LIQUIDITY:,.0f})...")

    try:
        events = polymarket.get_top_markets(n=TOP_N, min_liquidity=MIN_LIQUIDITY)
    except Exception as exc:
        print(f"[ERROR] Gamma API: {exc}")
        return 0

    print(f"[POLL] Got {len(events)} markets")
    alerts_sent = 0
    is_first_run = store.get_snapshot_count() == 0

    for event in events:
        market = polymarket.build_market_dict(event)

        for outcome in market["outcomes"]:
            last = store.get_last_snapshot(market["event_id"], outcome["name"])

            if last is None:
                # First time seeing this market/outcome - save baseline, skip alert
                store.save_snapshot(market, outcome)
                continue

            abs_delta = abs(outcome["price"] - last["price"])

            if (
                abs_delta >= PRICE_THRESHOLD
                and not store.was_recently_alerted(
                    market["event_id"], outcome["name"], COOLDOWN_HOURS
                )
            ):
                alert.send_alert(market, outcome, last["price"], "price_move")
                store.log_alert(market, outcome, last["price"], "price_move")
                alerts_sent += 1

            store.save_snapshot(market, outcome)

        # V2: large single-trade detection via CLOB API
        if MIN_TRADE_SIZE > 0 and market.get("condition_id"):
            trades = polymarket.fetch_large_trades(market["condition_id"], MIN_TRADE_SIZE)
            time.sleep(0.2)
            for trade in trades:
                trade_id = str(trade.get("id", ""))
                if not trade_id or store.is_trade_seen(trade_id):
                    continue
                outcome_name = polymarket.get_outcome_name(
                    market, str(trade.get("asset_id", ""))
                )
                alert.send_trade_alert(market, trade, outcome_name)
                store.mark_trade_seen(trade_id, market["event_id"])
                alerts_sent += 1

    if is_first_run and events:
        msg = (
            f"Polymarket Monitor da khoi dong!\n"
            f"Dang theo doi {len(events)} markets\n"
            f"Nguong canh bao: >= {PRICE_THRESHOLD * 100:.0f}% thay doi odds\n"
            f"Lenh bet don le: >= ${MIN_TRADE_SIZE:,.0f}\n"
            f"Se gui canh bao khi phat hien bien dong."
        )
        alert.send_telegram(msg)
        print("[START] Startup notification sent to Telegram")

    return alerts_sent


# ── CLI sub-commands ─────────────────────────────────────────────────────────

def cmd_list() -> None:
    """Print current top markets without alerting."""
    print(f"\nTop {TOP_N} markets (politics/economics, min liquidity ${MIN_LIQUIDITY:,.0f}):\n")
    try:
        events = polymarket.get_top_markets(n=TOP_N, min_liquidity=MIN_LIQUIDITY)
    except Exception as exc:
        print(f"[ERROR] {exc}")
        return

    for i, event in enumerate(events, 1):
        m = polymarket.build_market_dict(event)
        outcomes = m["outcomes"]
        # Show YES price for binary, top outcome price for multi
        yes = next((o["price"] for o in outcomes if o["name"].lower() == "yes"), None)
        top_price = yes or (outcomes[0]["price"] if outcomes else 0.0)
        top_name = next((o["name"] for o in outcomes if o["name"].lower() == "yes"), "")
        if not top_name and outcomes:
            top_name = outcomes[0]["name"]

        print(
            f"  {i:2}. [{top_price * 100:4.0f}% {top_name[:3]}] "
            f"Vol24h: ${m['volume24hr']:>9,.0f}  "
            f"Liq: ${m['liquidity']:>9,.0f}  "
            f"Closes: {m['end_date'] or 'N/A'}"
        )
        print(f"       {m['title'][:90]}")
    print()


def cmd_diagnose() -> None:
    """Check configuration and API connectivity."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")

    print("[DIAGNOSE] Polymarket Smart Money Tracker")
    print(f"  Telegram token : {'SET (' + token[:10] + '...)' if token else 'NOT SET <-- required'}")
    print(f"  Telegram chatID: {'SET (' + chat_id + ')' if chat_id else 'NOT SET <-- required'}")
    print(f"  Poll interval  : {POLL_INTERVAL_SEC // 60} min")
    print(f"  Price threshold: {PRICE_THRESHOLD * 100:.0f}%")
    print(f"  Min liquidity  : ${MIN_LIQUIDITY:,.0f}")
    print(f"  Top N markets  : {TOP_N}")
    print(f"  Alert cooldown : {COOLDOWN_HOURS}h")
    print(f"  DB path        : {store.DB_PATH}")
    print(f"  Alert log      : {alert.LOG_PATH}")

    if token and chat_id:
        print("\n[TEST] Sending Telegram test message...")
        ok = alert.send_telegram("Polymarket Monitor: ket noi Telegram thanh cong!")
        print(f"  {'OK - Kiem tra hop thoai Telegram cua ban' if ok else 'ERROR - Gui that bai (kiem tra lai token + chat_id)'}")
    else:
        print("\n[SKIP] Telegram test skipped (token/chat_id chua set)")

    print("\n[TEST] Calling Gamma API...")
    try:
        events = polymarket.get_top_markets(n=1)
        if events:
            m = polymarket.build_market_dict(events[0])
            print(f"  OK - First market: {m['title']}")
            print(f"       Volume24h: ${m['volume24hr']:,.0f}  Liquidity: ${m['liquidity']:,.0f}")
        else:
            print("  WARN - No markets returned (check MIN_LIQUIDITY or network)")
    except Exception as exc:
        print(f"  ERROR - {exc}")


# ── Main loop ────────────────────────────────────────────────────────────────

def run_loop() -> None:
    store.init_db()
    print(
        f"[START] Polymarket Tracker | "
        f"interval={POLL_INTERVAL_SEC // 60}min | "
        f"threshold={PRICE_THRESHOLD * 100:.0f}% | "
        f"top={TOP_N} markets"
    )

    cycle = 0
    while True:
        cycle += 1
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"\n[CYCLE {cycle}] {ts}")

        try:
            n = run_once()
            print(f"[CYCLE {cycle}] Done - {n} alert(s) sent")
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            print(f"[ERROR] Cycle {cycle}: {exc}")

        # Cleanup old snapshots every ~1000 cycles (~1 week at 10min interval)
        if cycle % 1000 == 0:
            deleted = store.cleanup_old_snapshots(keep_days=7)
            deleted_t = store.cleanup_old_seen_trades(keep_hours=24)
            print(f"[CLEANUP] Deleted {deleted} snapshots, {deleted_t} seen trades")

        try:
            time.sleep(POLL_INTERVAL_SEC)
        except KeyboardInterrupt:
            raise


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Polymarket Smart Money Monitor",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  python scripts/monitor.py              # run continuously\n"
            "  python scripts/monitor.py --once       # one check, then exit\n"
            "  python scripts/monitor.py --list       # show current markets\n"
            "  python scripts/monitor.py --diagnose   # check config + API\n"
        ),
    )
    parser.add_argument("--once", action="store_true", help="Run one cycle and exit")
    parser.add_argument("--list", action="store_true", help="List current top markets")
    parser.add_argument("--diagnose", action="store_true", help="Check config and API connectivity")
    args = parser.parse_args()

    try:
        if args.list:
            cmd_list()
        elif args.diagnose:
            cmd_diagnose()
        elif args.once:
            store.init_db()
            n = run_once()
            print(f"Done - {n} alert(s)")
        else:
            run_loop()
    except KeyboardInterrupt:
        print("\n[STOP] Interrupted")


if __name__ == "__main__":
    main()
