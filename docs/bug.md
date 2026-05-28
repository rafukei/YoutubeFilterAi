# YoutubeFilterAi — Bug Report

**Päivämäärä:** 2026-05-28
**Edellinen päivitys:** 2026-05-28 aamulla
**Tämä päivitys:** 2026-05-28 klo ~08:23 (UTC+3)

---

## 🔴 AKTIIVINEN BUGI: Scheduler ei käynnisty restartin jälkeen (08:16 → 08:23, 0 scheduler-lokitusta)

### Oire
Container käynnistyi onnistuneesti klo **08:16 UTC** (`INFO:scheduler:Scheduler started (scan interval: 60s)` näkyy kerran). Sen jälkeen:
- **EI yhtään** scheduler-aktiviteettia (ei kanavaskannausta, ei uusia video-lokeja)
- `activity_logs` viimeisin entry klo **08:04:36** — 19 minuuttia sitten
- **36 kanavaa** overdue (viimeksi tarkistettu yli 60 min sitten)
- YouTube RSS palauttaa nyt **200 OK** (aikaisemmin 404) — mutta sitä ei koskaan käsitellä

### Juurisyy: WatchFiles-reloader tappaa scheduler-taskin mutta EI käynnistä sitä uudelleen

**Koodipolku (`main.py:46-51`):**
```python
app.state.scheduler_task = asyncio.create_task(scheduler_loop(app.state.redis))
yield
# Shutdown
app.state.scheduler_task.cancel()
```

FastAPI/uvicorn `--reload` käyttää WatchFiles:ia. Kun `scheduler.py` muutetaan:
1. WatchFiles havaitsee muutoksen → lähettää SIGTERM
2. `lifespan` shutdown ajaa `scheduler_task.cancel()`
3. Uusi prosessi käynnistyy, uusi `scheduler_loop` luodaan
4. **ONGELMA:** Jos scheduler_loop heittää poikkeuksen ensimmäisen 60s aikana, se ei restartaa koska `scheduler_loop` ei ole `create_task` sisällä try/except

**Logs näyttää reload-silmukan:**
```
INFO:     Shutting down
INFO:     Waiting for application shutdown.
INFO:scheduler:Scheduler started (scan interval: 60s)
WARNING:  WatchFiles detected changes in 'app/services/scheduler.py'. Reloading...
```
Reload tapahtuu mutta scheduler ei tuota uusia lokeja.

### Vaihtoehtoinen hypoteesi: DB-yhteys katkeaa restartissa

`async_session_factory` saattaa mennä rikki uudelleenaloituksessa. Tarkista:
```sql
SELECT COUNT(*) FROM youtube_channels WHERE is_active = true;  -- pitäisi palauttaa > 0
```

### Korjaus:
1. Kova restart: `docker restart youtubefilterai-backend-1`
2. Tarkista onko scheduler käynnissä: `docker logs --since 5m | grep "Scheduler started"`
3. Vältä reloadia tuotannossa: poista `--reload` flag from `command:` in docker-compose.yml

---

## 📊 Status table (2026-05-28 08:23 UTC)

| Komponentti | Status | Huom |
|---|---|---|
| Backend container | ✅ Running (start 08:16) | Ei scheduler-aktiviteettia |
| Scheduler loop | ❌ Ei tuota lokeja | Ei käynnistynyt kunnolla |
| DB queries | ✅ Toimii (activity_logs päivittyy viimeiseen 08:04) | |
| YouTube RSS | ✅ 200 OK (aiemmin 404) | Kanavat löydetty |
| yt-dlp rate-limit | ❓ Ei lokeja viimeisen 45 min | Ehkä korjattu, ehkä ei testattu |
| Telegram-viestit | ❌ 0 uutta viimeisen 1h | Scheduler ei toimi |

---

## ✅ Korjatut bugit (historiasta)

### BUG-012 (aiempi): yt-dlp rate-limit + IP block looppi
- **Oire:** Jokainen uusi video → yt-dlp rate-limit → IP block counter ei koskaan saavuta 3
- **Korjaus:** `_IP_BLOCK_THRESHOLD` → 1, lisätty cooldown-tarkistus
- **Status:** Koodi korjattu, mutta ei testattu koska scheduler ei ole käynnissä

### BUG-013 (aiempi): @handle-kanavien consent-sivu
- **Oire:** `@AILuke` resolve epäonnistui consent-sivun takia
- **Korjaus:** Lisätty `"Before you continue" in body` -tarkistus
- **Status:** Korjaus tehty, ei testattu

---

## 🔧 Nopea korjaus (tee nyt)

```bash
# 1. Restart ilman reload-silmukkaa
docker --host=unix:///home/raafael/.docker/desktop/docker.sock restart youtubefilterai-backend-1

# 2. Tarkista scheduler käynnistyi
sleep 10 && docker --host=unix:///home/raafael/.docker/desktop/docker.sock logs youtubefilterai-backend-1 --since 2m | grep "Scheduler started"

# 3. Tarkista kanavat skannataan
sleep 60 && docker --host=unix:///home/raafael/.docker/desktop/docker.sock exec youtubefilterai-db-1 psql -U ytfilter -d ytfilter -c "SELECT created_at, level, source, message FROM activity_logs ORDER BY created_at DESC LIMIT 5;"
```

---

## 📋 Diagnosis queries (aja jos restart ei auta)

```bash
# Kanavat jotka ovat overdue
docker exec youtubefilterai-db-1 psql -U ytfilter -d ytfilter -c \
  "SELECT channel_name, last_checked_at, check_interval_minutes FROM youtube_channels \
   WHERE is_active=true AND (last_checked_at IS NULL OR last_checked_at < NOW() - INTERVAL '60 minutes') LIMIT 10;"

# Sektorit joissa ei ole viestejä 1h
docker exec youtubefilterai-db-1 psql -U ytfilter -d ytfilter -c \
  "SELECT COUNT(*) FROM messages WHERE created_at > NOW() - INTERVAL '1 hour';"

# Scheduler loop errorit
docker logs youtubefilterai-backend-1 --since 2h 2>&1 | grep "Scheduler loop error"
```