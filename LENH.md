# Lenh thuong dung - Polymarket Tracker

## Buoc dau tien (setup)
```bash
cd D:/polymarket-tracker
copy .env.example .env       # Windows
# hoac: cp .env.example .env  # Bash
# Sua .env: dien TELEGRAM_BOT_TOKEN va TELEGRAM_CHAT_ID
python scripts/monitor.py --diagnose
```

## Chay monitor
```bash
python scripts/monitor.py              # loop lien tuc (Ctrl+C de dung)
python scripts/monitor.py --once       # chay 1 lan roi thoat (test)
python scripts/monitor.py --list       # xem top markets hien tai
python scripts/monitor.py --diagnose   # kiem tra config + API
```

## Lay Telegram credentials
1. Nhan tin cho @BotFather -> /newbot -> dat ten -> lay TOKEN
2. Nhan tin bat ky cho bot vua tao
3. Truy cap: https://api.telegram.org/bot{TOKEN}/getUpdates
4. Tim "chat" -> "id" trong JSON -> do la CHAT_ID
5. Dien vao .env

## Xem logs
```bash
# Alert history
type outputs\alerts.log          # Windows
# hoac: cat outputs/alerts.log    # Bash

# SQLite database
# Mo bang DB Browser for SQLite hoac:
python -c "import sqlite3; conn=sqlite3.connect('data/snapshots.db'); print([r for r in conn.execute('SELECT * FROM alert_log ORDER BY alerted_at DESC LIMIT 10')])"
```

## Tuy chinh nguong (sua .env)
```
PRICE_CHANGE_THRESHOLD=0.05   # 5% - nhanh hon, nhieu alert hon
PRICE_CHANGE_THRESHOLD=0.15   # 15% - chi bat bien dong lon
POLL_INTERVAL_MINUTES=5       # poll 5 phut 1 lan
MIN_LIQUIDITY=50000           # chi xem market co liquidity > $50K
TOP_N_MARKETS=30              # theo doi top 30
```

## Neu gap loi WinError 10054 / Connection Reset
Gamma API (gamma-api.polymarket.com) co the bi chan hoac rate-limited.
Cach xu ly:
1. Dung VPN, sau do them vao .env:
   HTTPS_PROXY=http://127.0.0.1:7890   (doi port theo VPN cua ban)
2. Hoac doi 1-2 gio roi thu lai (neu chi la rate limit tam thoi)
3. Test xem API co hoat dong: python scripts/monitor.py --diagnose

## Chay tu dong khi Windows khoi dong
1. Mo Task Scheduler
2. Create Task -> Triggers: At startup
3. Action: Start a program
   Program: python
   Arguments: D:\polymarket-tracker\scripts\monitor.py
   Start in: D:\polymarket-tracker
