# Phase 1 — Data Feed Implementation (Kite + Upstox)

**Goal:** Replace every `NotImplementedError` stub in `upstox_feed.py` and
`kite_feed.py` with real broker API calls. By end of Phase 1 you can fetch a
live NIFTY 5-min candle, spot price, India VIX, and option chain from
whichever broker you have ready — just by changing one line in `config.yaml`.

**Time estimate:** 2–3 hours (includes token setup time).

**Output:**
- `python scripts/feed_healthcheck.py` connects to the active broker and
  prints live NIFTY spot price.
- `pytest tests/` passes (all mocked, no live API needed for tests).
- Token refresh scripts work end-to-end.

**What Phase 1 does NOT do:**
- No indicator calculations (Phase 2)
- No condition logic (Phase 3)
- No Telegram alerts (Phase 5)
- No order placement (Phase 8)

---

## STEP 1 — Get your broker credentials ready

### Kite (Zerodha)
After purchasing the Kite Connect API (₹500/month):
1. Go to https://developers.kite.trade
2. Create a new app → note down **API Key** and **API Secret**
3. Set Redirect URL to `http://127.0.0.1:8080` (we'll use this in the token script)
4. Fill these into `config/secrets.env`:
   ```
   KITE_API_KEY=your_actual_key
   KITE_API_SECRET=your_actual_secret
   ```

### Upstox
1. Go to https://account.upstox.com/developer/apps
2. Create app → note **API Key** and **Secret**
3. For the 1-year token: in Upstox web → top-right menu → **Analytics** →
   **Developer** → generate long-validity token, paste it into:
   ```
   UPSTOX_ACCESS_TOKEN=your_long_token
   UPSTOX_TOKEN_DATE=2026-05-25   ← today's date, update annually
   ```
4. For the standard OAuth token: run `python scripts/refresh_token_upstox.py`

Leave the other broker's fields as placeholder if you don't have it yet —
the inactive feed is never touched.

---

## STEP 2 — Run the token refresh for Kite (daily ritual)

```cmd
call venv\Scripts\activate.bat
python scripts\refresh_token_kite.py
```

The script will:
1. Print a login URL — open it in Chrome
2. Log in with your Zerodha credentials + TOTP
3. Browser redirects to `http://127.0.0.1:8080/?request_token=XXXX` —
   copy the `request_token` value from the URL bar
4. Paste it into the terminal when prompted
5. Script writes `KITE_ACCESS_TOKEN` and `KITE_TOKEN_DATE` to `secrets.env`

**You must do this every trading day before running the bot.**
Set a 9:00 AM Windows reminder.

---

## STEP 3 — Paste this prompt into Claude Code

```cmd
cd C:\trading\short-cover-cascade
claude
```

Then paste the entire block below:

````
Read CLAUDE.md fully before starting. Then read docs/phases/PHASE_1.md.
Current phase: Phase 1 — Data Feed Implementation.

CRITICAL INSTRUCTION: If any file already exists, OVERWRITE it completely
with the new version. Do not skip, do not merge — overwrite.

PHASE 1 SCOPE:
Implement both broker feeds (KiteFeed and UpstoxFeed) as full working
classes. All BaseFeed abstract methods must be implemented.
Token validation at startup. Feed healthcheck becomes a real connectivity
test. Unit tests with full mocking (never hit live API in tests).

--- TASK 1: Update scripts/refresh_token_kite.py ---

Rewrite completely. Requirements:
- Load KITE_API_KEY and KITE_API_SECRET from config/secrets.env
- If either missing, print clear error: "KITE_API_KEY missing from
  config/secrets.env — fill it in before running this script" and exit(1)
- Build the Kite login URL:
    from kiteconnect import KiteConnect
    kite = KiteConnect(api_key=api_key)
    print(kite.login_url())
- Print: "Open this URL in Chrome. After login, copy the request_token
  from the redirect URL and paste it below."
- Input prompt: "request_token: "
- Exchange token:
    data = kite.generate_session(request_token, api_secret=api_secret)
    access_token = data["access_token"]
- Write back to secrets.env using python-dotenv's set_key():
    KITE_ACCESS_TOKEN = access_token
    KITE_TOKEN_DATE = today's date as YYYY-MM-DD
- Print: "Kite token saved. Valid for today only. Run this script again
  tomorrow morning before 9:15 AM."
- Wrap in try/except — on any error print full traceback and exit(1)

--- TASK 2: Update scripts/refresh_token_upstox.py ---

Rewrite completely. Two modes:
MODE A (--manual flag): User pastes a long-validity token directly.
  - Prompt: "Paste your Upstox access token: "
  - Write UPSTOX_ACCESS_TOKEN and UPSTOX_TOKEN_DATE to secrets.env
  - Print confirmation

MODE B (default, no flag): Standard OAuth flow.
  - Load UPSTOX_API_KEY, UPSTOX_API_SECRET, UPSTOX_REDIRECT_URI
  - Build auth URL using upstox_client library
  - Print URL, ask user to open in browser
  - After redirect, user pastes full redirect URL
  - Extract code parameter from URL
  - Exchange for access token via Upstox v3 token endpoint:
    POST https://api.upstox.com/v2/login/authorization/token
    with grant_type=authorization_code
  - Write UPSTOX_ACCESS_TOKEN and UPSTOX_TOKEN_DATE to secrets.env
  - Print confirmation

Both modes: wrap in try/except, print full traceback on error.

--- TASK 3: Implement src/data/kite_feed.py ---

Full implementation of KiteFeed(BaseFeed). All imports of kiteconnect
go INSIDE __init__ or methods (lazy import pattern from CLAUDE.md).

class KiteFeed(BaseFeed):

    def __init__(self, config: AppConfig):
        self._config = config
        self._kite = None   # initialized in connect()
        self._connected = False

    def get_broker_name(self) -> str:
        return "kite"

    def is_token_valid(self) -> bool:
        """
        Check KITE_TOKEN_DATE in secrets.env.
        Returns True only if KITE_TOKEN_DATE == today's date (IST).
        Also checks KITE_ACCESS_TOKEN is non-empty.
        """

    def connect(self) -> bool:
        """
        1. Call is_token_valid() — if False, raise RuntimeError with message:
           "Kite token is stale. Run: python scripts/refresh_token_kite.py"
        2. from kiteconnect import KiteConnect
        3. self._kite = KiteConnect(api_key=KITE_API_KEY)
        4. self._kite.set_access_token(KITE_ACCESS_TOKEN)
        5. Call self._kite.profile() to verify connection — if it raises,
           catch and re-raise as RuntimeError("Kite connection failed: <err>")
        6. self._connected = True
        7. Log success with loguru: logger.info("Kite feed connected")
        8. Return True
        """

    def get_spot_price(self, symbol: str) -> float:
        """
        symbol: "NIFTY" or "BANKNIFTY"
        Kite instrument tokens:
          NIFTY:     NSE:NIFTY 50
          BANKNIFTY: NSE:NIFTY BANK
        Use self._kite.ltp(["NSE:NIFTY 50"]) → parse the last price.
        """

    def get_lot_size(self, symbol: str) -> int:
        """
        Fetch from NSE instrument dump via Kite:
          instruments = self._kite.instruments("NFO")
          Find rows where name == symbol and instrument_type == "FUT"
          and expiry is the nearest upcoming date.
          Return lot_size field.
        Cache the result in self._lot_sizes dict so we only fetch once
        per session (lot sizes don't change intraday).
        Fallback: if fetch fails, return value from config
        (config.instruments.nifty_lot_size or banknifty_lot_size).
        Log which source was used.
        """

    def get_5min_candles(self, instrument_key: str, n_candles: int) -> pd.DataFrame:
        """
        instrument_key format for Kite: "NFO:NIFTY2652524500CE"
        Use self._kite.historical_data(
            instrument_token,   ← need to resolve instrument_key to token first
            from_date,
            to_date,
            interval="5minute"
        )
        
        Steps:
        1. Resolve instrument_key to Kite numeric token via
           get_instrument_token(instrument_key) helper method (see below)
        2. Calculate from_date = now - (n_candles * 5 minutes) - 15 min buffer
           All times in IST (Asia/Kolkata)
        3. Fetch historical data
        4. Return DataFrame with columns:
           [timestamp, open, high, low, close, volume, oi]
           timestamp must be timezone-aware IST datetime
        5. Return last n_candles rows only
        6. On any API error: log warning, retry up to config.bot.api_retry_count
           times with config.bot.api_retry_delay_seconds delay between retries.
           After all retries exhausted, raise RuntimeError.
        """

    def get_option_chain(self, symbol: str, expiry: str) -> pd.DataFrame:
        """
        symbol: "NIFTY" or "BANKNIFTY"
        expiry: "YYYY-MM-DD" string
        
        Use self._kite.instruments("NFO") to get all NFO instruments.
        Filter by:
          - name == symbol
          - expiry == expiry date
          - instrument_type in ["CE", "PE"]
        Return DataFrame with columns:
          [strike, instrument_type, instrument_token, tradingsymbol,
           expiry, lot_size]
        Sort by strike ascending.
        """

    def get_india_vix(self) -> float:
        """
        India VIX from Kite:
        Use self._kite.ltp(["NSE:INDIA VIX"])
        Parse and return the last price as float.
        On error: log warning and return -1.0 (caller checks for -1)
        """

    def get_atm_strike(self, symbol: str) -> int:
        """
        1. Get spot price via get_spot_price(symbol)
        2. Round to nearest strike interval:
           NIFTY: nearest 50
           BANKNIFTY: nearest 100
        3. Return as int
        """

    def _get_instrument_token(self, trading_symbol: str, exchange: str = "NFO") -> int:
        """
        Helper: looks up numeric Kite instrument token from trading symbol.
        Caches the full instrument list in self._instruments_cache.
        Raises ValueError if symbol not found.
        """

--- TASK 4: Implement src/data/upstox_feed.py ---

Full implementation of UpstoxFeed(BaseFeed). All imports of upstox_client
go INSIDE __init__ or methods (lazy import pattern).

class UpstoxFeed(BaseFeed):

    def __init__(self, config: AppConfig):
        self._config = config
        self._api_client = None
        self._connected = False

    def get_broker_name(self) -> str:
        return "upstox"

    def is_token_valid(self) -> bool:
        """
        For Upstox: check UPSTOX_TOKEN_DATE exists and is non-empty.
        If token_validity_days == 365 in config: always return True if
        UPSTOX_ACCESS_TOKEN is non-empty (user manages annual renewal).
        If token_validity_days == 1: check date == today IST.
        """

    def connect(self) -> bool:
        """
        1. Check is_token_valid() — raise RuntimeError if invalid.
        2. import upstox_client
        3. Configure upstox_client.Configuration with access_token
        4. Create API client instances needed:
           - MarketQuoteApi (for spot, VIX)
           - HistoryApi (for candles)
           - OptionChainApi (for option chain)
        5. Verify connection by calling get_market_quote for NIFTY spot
        6. self._connected = True
        7. Log success
        8. Return True
        Upstox instrument keys:
          NIFTY spot:     "NSE_INDEX|Nifty 50"
          BANKNIFTY spot: "NSE_INDEX|Nifty Bank"
          India VIX:      "NSE_INDEX|India VIX"
        """

    def get_spot_price(self, symbol: str) -> float:
        """
        Upstox v3 instrument keys:
          NIFTY:     "NSE_INDEX|Nifty 50"
          BANKNIFTY: "NSE_INDEX|Nifty Bank"
        Use MarketQuoteApi.get_full_market_quote(symbol=instrument_key)
        Parse last_price from response.
        """

    def get_lot_size(self, symbol: str) -> int:
        """
        Upstox does not have a direct lot-size endpoint.
        Use the option chain data: fetch option chain, take first row,
        return lot_size field.
        Cache result in self._lot_sizes.
        Fallback: config value with a log warning.
        """

    def get_5min_candles(self, instrument_key: str, n_candles: int) -> pd.DataFrame:
        """
        Upstox instrument_key format: "NSE_FO|<numeric_token>"
        e.g. "NSE_FO|35001"
        
        Use HistoryApi.get_intra_day_candle_data(
            instrument_key=instrument_key,
            interval="5minute",
            api_version="2.0"
        )
        This returns today's intraday candles only (Upstox v3 intraday).
        
        Return DataFrame columns: [timestamp, open, high, low, close, volume, oi]
        timestamp: timezone-aware IST datetime
        Return last n_candles rows only.
        Retry logic same as KiteFeed.
        """

    def get_option_chain(self, symbol: str, expiry: str) -> pd.DataFrame:
        """
        Use OptionChainApi.get_option_chain_data(
            instrument_key = "NSE_INDEX|Nifty 50" or "NSE_INDEX|Nifty Bank",
            expiry_date = expiry  (format: "YYYY-MM-DD")
        )
        Return DataFrame columns:
          [strike, instrument_type, instrument_key, trading_symbol,
           expiry, lot_size]
        Sort by strike ascending.
        """

    def get_india_vix(self) -> float:
        """
        Instrument key: "NSE_INDEX|India VIX"
        Use MarketQuoteApi.get_full_market_quote()
        Return last_price as float.
        On error: return -1.0
        """

    def get_atm_strike(self, symbol: str) -> int:
        """
        Same logic as KiteFeed:
        1. get_spot_price(symbol)
        2. Round to nearest 50 (NIFTY) or 100 (BANKNIFTY)
        3. Return int
        """

--- TASK 5: Update src/data/feed_factory.py ---

Rewrite completely.

def get_feed(config: AppConfig) -> BaseFeed:
    active = config.feeds.active_feed.lower()
    if active == "kite":
        from src.data.kite_feed import KiteFeed
        feed = KiteFeed(config)
    elif active == "upstox":
        from src.data.upstox_feed import UpstoxFeed
        feed = UpstoxFeed(config)
    else:
        raise ConfigError(f"Unknown feed: {active}. Must be 'kite' or 'upstox'")
    return feed

Also add:

def connect_feed(config: AppConfig) -> BaseFeed:
    """
    Get the feed AND connect it in one call.
    Used by main.py and healthcheck.
    Raises RuntimeError if connection fails (token expired etc.)
    """
    feed = get_feed(config)
    feed.connect()
    return feed

--- TASK 6: Update scripts/feed_healthcheck.py ---

Rewrite completely. This is now a real connectivity test.

Steps:
1. Load config and secrets
2. Print: "=== Feed Health Check ==="
3. Print: "Active feed: <config.feeds.active_feed>"
4. Try to connect via feed_factory.connect_feed()
5. If connection fails: print error and exit(1)
6. Run these checks, print PASS/FAIL for each:
   a. get_spot_price("NIFTY") → print value
   b. get_spot_price("BANKNIFTY") → print value
   c. get_india_vix() → print value (warn if -1.0)
   d. get_lot_size("NIFTY") → print value, compare to config
   e. get_lot_size("BANKNIFTY") → print value, compare to config
   f. get_atm_strike("NIFTY") → print value
7. Print summary: "X/6 checks passed"
8. If lot size from broker differs from config value → print:
   "WARNING: Lot size mismatch! Update config.yaml before trading."
9. Exit(0) if all pass, exit(1) if any fail

--- TASK 7: Update src/main.py ---

Add feed connection to startup sequence:
1. (existing) Load config, load secrets, configure loguru, print banner
2. (NEW) Instantiate feed via feed_factory.get_feed()
3. (NEW) Call feed.is_token_valid() — if False:
   - For kite: print "ERROR: Kite token is stale. Run:
     python scripts\refresh_token_kite.py"
   - For upstox: print "ERROR: Upstox token missing. Run:
     python scripts\refresh_token_upstox.py --manual"
   - Exit(1)
4. (NEW) Print: "Token check: PASS (active feed: <broker>)"
5. (NOT YET) Do not call feed.connect() yet — that happens in Phase 5
   when the orchestrator starts. Phase 1 only checks token validity.
6. Print "Phase 1 complete — token valid, feed ready to connect"

--- TASK 8: Write unit tests ---

Create these test files. ALL tests use mocking — never hit live API.

tests/test_kite_feed.py:
- test_is_token_valid_today: mock TODAY's date in KITE_TOKEN_DATE → True
- test_is_token_valid_yesterday: mock yesterday's date → False
- test_is_token_valid_missing: empty KITE_TOKEN_DATE → False
- test_get_atm_strike_nifty: spot=24530 → nearest 50 = 24500
- test_get_atm_strike_banknifty: spot=54312 → nearest 100 = 54300
- test_connect_stale_token: connect() with stale token → raises RuntimeError
- test_get_spot_price: mock kite.ltp() response → correct float returned

tests/test_upstox_feed.py:
- test_is_token_valid_365day: token_validity_days=365, token non-empty → True
- test_is_token_valid_1day_today: token_validity_days=1, today's date → True
- test_is_token_valid_1day_yesterday: token_validity_days=1, yesterday → False
- test_get_atm_strike_nifty: same as kite test
- test_get_atm_strike_banknifty: same as kite test

tests/test_feed_factory.py:
- test_get_feed_kite: config with active_feed=kite → returns KiteFeed instance
- test_get_feed_upstox: config with active_feed=upstox → returns UpstoxFeed
- test_get_feed_invalid: config with active_feed=hdfc → raises ConfigError
- test_inactive_feed_not_imported: when active=kite, confirm upstox_client
  is NOT in sys.modules after get_feed()

After writing all files, run:
  call venv\Scripts\activate.bat
  pytest tests\ -v

All tests must pass. If any fail, fix them before reporting done.
Report: exact pytest output, any issues found, and confirm main.py
now prints "Phase 1 complete — token valid, feed ready to connect"
(it will show token stale warning if secrets.env isn't filled yet —
that's fine, report whatever it shows).
````

---

## STEP 4 — Fill in your real credentials then test

After Claude Code finishes:

```cmd
# 1. Fill your real Kite credentials into config/secrets.env
# 2. Run the token refresh
call venv\Scripts\activate.bat
python scripts\refresh_token_kite.py

# 3. Run the healthcheck
python scripts\feed_healthcheck.py

# 4. Run main.py
run.bat
```

---

## STEP 5 — Verification Checklist

Work through these in order. Stop if one fails and fix it before continuing.

| # | Check | What to run | Expected result |
|---|---|---|---|
| 1 | Tests pass | `pytest tests\ -v` | All green, 0 failures |
| 2 | Token refresh runs | `python scripts\refresh_token_kite.py` | Prints login URL, accepts token, saves to secrets.env |
| 3 | KITE_ACCESS_TOKEN updated | `type config\secrets.env` | KITE_ACCESS_TOKEN has a real value, KITE_TOKEN_DATE = today |
| 4 | Healthcheck connects | `python scripts\feed_healthcheck.py` | Prints live NIFTY spot price |
| 5 | Healthcheck shows VIX | Same | India VIX printed (real number, not -1.0) |
| 6 | Lot size check | Same | NIFTY lot=65, BANKNIFTY lot=30 (or warns if different) |
| 7 | ATM strike reasonable | Same | NIFTY ATM = round(current spot / 50) * 50 |
| 8 | run.bat passes token check | `run.bat` | Prints "Token check: PASS" |
| 9 | Stale token caught | Set KITE_TOKEN_DATE=2020-01-01, run `run.bat` | Prints "ERROR: Kite token is stale" and exits |
| 10 | Restore and rerun | Restore real token date, run `run.bat` | Passes again |
| 11 | Switch to Upstox | `active_feed: upstox` in config, run `run.bat` | Prints Upstox token warning (expected if not configured yet) |
| 12 | Switch back to Kite | `active_feed: kite` | Passes |

**Target: all 12 green before telling me Phase 1 is done.**

Minimum acceptable: checks 1–8 pass. Checks 9–12 can be "tested but expected
behavior" if you don't have Upstox configured yet.

---

## Questions to answer when you confirm Phase 1 complete

1. Paste exact output of `python scripts\feed_healthcheck.py`
2. What NIFTY spot price did it show? (Just confirms it's live data)
3. Did lot sizes match config (65 / 30)?
4. Any tests that failed and how Claude Code fixed them?
5. Upstox: do you want to configure it now or wait until Kite is stable?

These answers shape Phase 2 (indicator calculations).

---

## What Phase 2 will build (preview)

Once Phase 1 is confirmed working:

- VWAP (hlc3, session-anchored) using real candles from Phase 1's `get_5min_candles()`
- Wilder's RSI(14) — exact formula matching Upstox/TradingView
- OI MA(20), Volume MA(20), RSI MA(20) — all simple SMA
- Unit tests that validate against the 5 real candles in `docs/known_indicator_values.md`
- A standalone `python scripts\check_indicators.py` that fetches live candles
  and prints current VWAP, RSI, all MAs for a given strike — so you can
  visually compare to your Kite chart and confirm the numbers match

**End of Phase 1.**
