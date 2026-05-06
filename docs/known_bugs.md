# YoutubeFilterAi — Tunnetut Bugit & Historiallinen Bugitrackeri

> Tämä dokumentti on **totuuden lähde** bugeille. Ennen uuden bugin korjaamista, tarkista onko se jo täällä.
> Järjestelmä lukee tätä tiedostoa ja käyttää sitä välttääkseen jo korjattujen bugien uudelleenluomisen.

---

## 🔴 Aktiiviset Bugit

### BUG-001: `last_video_id` ei päivity epäonnistumisessa → infinite retry loop
- **Tunnistettu:** 2026-04-25 (commit `4de31f6`)
- **Palasi:** 2026-05-06 (commit `b113b55`) — **sama bugi korjattiin kahdesti**
- **Vakavuus:** Kriittinen — yksi viallinen video jumittaa koko kanavan loputtomasti
- **Oire:** Schedulerlogs näyttää samaa videota yhä uudestaan: `"Transcript fetch failed for {video_id}"` 60s välein
- **Historialliset korjaukset:**
  - `4de31f6`: `last_video_id` asetetaan ENNEN transcript-fetchiä (not after success)
  - `b113b55`: Lisätty `transcript_retry_count` kenttä + `_TRANSCRIPT_RETRY_MAX = 3` raja
- **Juurisyy:** Kun `fetch_transcript` epäonnistui, funktio palasi ilman `last_video_id`-päivitystä. Seuraavalla kierroksella sama video havaittiin "uutena" → loop.
- **Korjaus (current):** `last_video_id` päivittyy HETI kun uusi video havaitaan (rivillä 405). Epäonnistuessa `transcript_retry_count` kasvaa. 3 epäonnistumisen jälkeen video hylätään.
- **Sisäänrakennettu suoja:** `_TRANSCRIPT_RETRY_MAX = 3` + `transcript_retry_count` kenttä estää infinite loopin

---

## 🟡 Korjatut Bugit (historia)

### BUG-002: OOM kills, scheduler crash loops
- **Päivämäärä:** 2026-04-25 (commit `4de31f6`)
- **Oire:** Docker kontti kaatui muistinvirheen takia, scheduler meni crash looppiin
- **Korjaus:** `mem_limit` kaikille kontuille (db=512m, redis=256m, backend=512m, frontend=512m, nginx=128m), `NODE_OPTIONS=--max-old-space-size=256`
- **Ei palaa:** Hard memory limits docker-compose.yml:ssä

### BUG-003: Duplicate video processing
- **Päivämäärä:** 2026-04-25 (commit `4de31f6`)
- **Oire:** Sama video saattoi olla käsitelty useita kertoja
- **Korjaus:** `last_video_id` päivittyy ENNEN transcript-fetchiä — restart ei toista samaa videota

### BUG-004: Kovakoodatut AI-mallit UI:ssa (Frontend)
- **Päivämäärä:** 2026-05-06 (commit `b113b55`)
- **Oire:** UI näytti `DEFAULT_MODELS`-listan, ei OpenRouterin todellista mallilistaa
- **Korjaus:** `_validate_model()` tarkistaa mallin OpenRouter API:sta ennen käyttöä (5 min välimuisti)
- **HUOM:** Frontend (`frontend/src/constants/models.ts`) käyttää edelleen kovakoodattua listaa — tämä on UI-only ongelma, ei estä toimintaa

### BUG-005: `Sijoittaminen`-prompti käytti ei-olemassa olevaa mallia
- **Päivämäärä:** 2026-05-06 (commit `b113b55`)
- **Oire:** `google/gemma-3-27b-it:free` → 404 OpenRouterissa
- **Korjaus:** Malli korjattu muotoon `google/gemma-3-27b-it`, fallback: `openai/gpt-4.1-mini`
- **Tietokantakorjaus:** `UPDATE prompts SET ai_model='google/gemma-3-27b-it', fallback_ai_model='openai/gpt-4.1-mini' WHERE name='Sijoittaminen'`

### BUG-006: Scheduler crash on channel_id UPDATE
- **Päivämäärä:** 2026-04-25 (commit `4de31f6`)
- **Oire:** `IntegrityError` kun toinen prosessi oli jo päivittänyt channel_id:n
- **Korjaus:** `try/except IntegrityError` + `rollback` + early return

### BUG-007: Greenlet spawn error (lazy ORM loading after rollback)
- **Päivämäärä:** 2026-04-25 (commit `4de31f6`)
- **Oire:** `sqlalchemy.exc.MissingGreenletError` kun ORM-attribuutteja luettiin rollback:n jälkeen
- **Korjaus:** Kaikki ORM-data materialisoidaan dict-muotoon ENNEN `process_channel()`-kutsua (rivit 627-635)

---

## ⚠️ Tunnistetut Riskit (ei akuutteja, mutta valvottavia)

### RISK-001: Frontend mallilista ei vastaan OpenRouter API:ta
- **Sijainti:** `frontend/src/constants/models.ts`
- **Status:** UI näyttää vanhentuneita malleja, mutta backend valideeraa oikein
- **Ei estä toimintaa:** Backend fallback toimii, mutta UI-valinnat voivat olla vääriä
- **Pitkäaikainen korjaus:** Frontend tarvitsee endpointin joka hakee mallit OpenRouterista

### RISK-002: IP block cooldown on globaali muuttuja
- **Sijainti:** `scheduler.py` rivi 51: `_ip_block_cooldown_until`
- **Status:** Prosessi-restart nollaa counterin — ei persistent
- **Ei estä toimintaa:** Cooldown toimii prosessin sisällä, mutta ei yli restarteja

### RISK-003: Telegram-virhelogit eivät keskeytä videon käsittelyä
- **Sijainti:** `scheduler.py` rivit 553-565
- **Status:** Telegram-virhe kirjataan mutta jatkaa seuraavaan bottiin/promptiin
- **Ok:** Suunnittelun mukaan — yhden botin epäonnistuminen ei saa keskeyttää koko videota

---

## 🛡️ EnnaltaehkäisySäännöt (Testattava ennen jokaista commitia)

1. **`last_video_id` päivitys tulee AINA ennen riskialtista operaatiota (transcript fetch, AI call)**
2. **Jokainen database COMMIT tulee `try/except` sisällä** — epäonnistunut commit ei saa kaataa scheduleria
3. **Globaalit tilamuuttujat (rate limit, IP block) tulee olla `global`** ja resetoitava poikkeustapauksissa
4. **AI endpoint -virhe (503, 404) tulee käsitellä fallback-mallilla ENNEN luovutusta**
5. **Kaikki `fetch_transcript` epäonnistumiset tulee kirjata `transcript_retry_count`:iin**

---

## 📊 Bugitiheyden Seuranta

| Kuukausi | Bugikorjauksia | Huom |
|----------|----------------|------|
| 2026-04  | 3 (4de31f6)    | Suuri julkaisu - OOM, crash loop, duplicate |
| 2026-05  | 2 (b113b55)    | Infinite retry, mallin validointi |

---

## 🔴 Äskettäin Löydetyt Uudet Bugit (tutkimatta)

### BUG-008: `uq_user_channel` duplicate key constraint violation
- **Löydetty:** 2026-05-06 (monitor.py) — *TUTKIMATTA, KORJAAMATTA*
- **Vakavuus:** Kriittinen — toistuu ~77s välein, täyttää lokit ERROR-viesteillä
- **Oire:** `ERROR: duplicate key value violates unique constraint "uq_user_channel"` — toistuu 9 kertaa tunnissa per virhetapahtuma
- **Sijainti:** Tietokanta kirjoittaa tätä; joko UI lisää duplikaattikanavan TAI scheduler yrittää päivittää channel_id:ta duplikaattiin
- **Tutkiminen:** `resource_routes.py` — channel creation endpoint; `scheduler.py` — `resolve_channel_id` + `_update_channel`
- **TODO:** Ei korjattu vielä — tämä bugi vaatii erillisen tutkimuksen
