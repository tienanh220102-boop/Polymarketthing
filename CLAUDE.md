# Polymarket Smart Money Tracker

Theo doi bien dong odds lon tren Polymarket de detect smart money (nguoi co thong tin insider).

## Gia thuyet
Khi ai do bet mot luong tien lon, odds dich chuyen dot ngot.
Bet lon = co the co thong tin chua cong khai.
Tap trung: Top 20 markets politics + economics theo volume.

## Cach hoat dong
1. Moi POLL_INTERVAL phut: fetch top N events tu Gamma API (free, no auth)
2. So sanh odds hien tai voi snapshot lan poll truoc
3. Neu thay doi >= PRICE_CHANGE_THRESHOLD (default 10%) va het cooldown -> goi Telegram alert
4. Alert chua: ten event, outcome nao dang duoc cuoc, odds truoc/sau, volume, liquidity

## Files chinh
- `scripts/monitor.py`         - Entry point + polling loop + CLI commands
- `scripts/lib/polymarket.py`  - Gamma API client, market filtering, outcome parsing
- `scripts/store.py`           - SQLite snapshot + alert log (data/snapshots.db)
- `scripts/alert.py`           - Telegram sender + file logger

## Config (.env)
- TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID (bat buoc)
- POLL_INTERVAL_MINUTES=10
- PRICE_CHANGE_THRESHOLD=0.10
- MIN_LIQUIDITY=10000
- TOP_N_MARKETS=20
- ALERT_COOLDOWN_HOURS=2

## Gamma API
- Base URL: https://gamma-api.polymarket.com
- Browse events: GET /events?active=true&closed=false&limit=200
- Search events: GET /public-search?q={topic}&events_status=active
- Free, no auth, 15K req/10s

## Gioi han V1
- Chi detect price movement (khong detect individual large trades)
- Individual trade detection can CLOB API (clob.polymarket.com) - Phase 2
- Phase 2: theo doi fills > $X$ tren CLOB de phat hien 1 lenh cuoc lon duy nhat

## Du lieu
- data/snapshots.db  - lich su odds theo tung poll
- outputs/alerts.log - tat ca alerts da gui
