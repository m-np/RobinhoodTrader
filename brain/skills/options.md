# Options Trading Skill

## Philosophy

Options are precision instruments for specific purposes. In aggressive growth investing,
options serve three distinct roles:
1. LEAP calls on core tickers at 52-week lows — leverage thesis with capped downside
2. Covered calls on large core positions — generate income while holding
3. Puts as portfolio hedge during elevated VIX periods — cost of insurance, not profit

Each options trade must have a clearly defined max loss, target exit, and expiration plan.
If you cannot articulate all three before entering, do not trade.
Options allocation is capped at 25% of total portfolio value — enforced as a hard rule.

---

## When to Use Options

### Use options instead of stock when:
- Core tier ticker is within 5% of 52-week low AND IVR < 35% (LEAP opportunity)
- You own 100+ shares of a core position and it is trading sideways (covered call)
- Portfolio is overweight one sector and you want downside protection (protective put)
- You want leveraged upside on a short-term catalyst with defined risk (long call)

### Do NOT use options when:
- IVR is above 60% and you want to buy options — you are overpaying for the move
- You have no specific thesis and time horizon written down
- You are under capital pressure — options can expire worthless; size accordingly
- The ticker is in moon shot tier — options on speculative names compound binary risk
- You are uncertain about direction — theta burns while you wait

---

## Core Strategies

### 1. LEAP Call — Core Tier at Discounts (New for Aggressive Growth)

Use when: Core tier ticker is within 5% of 52-week low, thesis intact, IVR < 35%.
This replaces buying the stock outright — gives equivalent exposure for 60-70% less capital.

- Strike: deep in-the-money, delta >= 0.70 (moves nearly 1:1 with stock)
- Expiry: 12-18 months (Jan or Jun expiry cycles only)
- Size: replaces 50% of what you would allocate to the stock position
- IVR gate: must be below 35% — if IV is elevated, buy stock instead of LEAP
- Exit plan: close at 50% profit OR roll forward at 60 DTE if thesis still intact
- Never hold a LEAP to expiration — roll or close at 60 DTE minimum

Example: PLTR at $118 (near 52w low of $117.94), IVR at 28%.
Instead of buying $2,000 of PLTR stock: buy 1 Jan 2027 $90 call (delta ~0.75) for ~$600.
Max loss: $600. Upside: same as owning 100 shares above $90.

### 2. Long Call — Bullish Directional

Use when: Strong bullish conviction, confirmed catalyst, IVR < 30%.

DTE by tier:
- Core: 90-120 DTE (give the thesis time, minimize theta pressure)
- Growth: 60-90 DTE
- Moon Shot: do not use long calls on moon shots — buy stock in small size instead

- Strike: 1-2 strikes OTM for leverage, ATM for higher probability
- Exit plan: close at 50% profit OR at 21 DTE, whichever comes first
- Max loss: premium paid — never add to a losing long option position
- If down 50% on the option before 21 DTE: close it, accept the loss

### 3. Covered Call — Income Generation on Core Positions

Use when: You own 100+ shares of a core ticker and it is in consolidation.

For aggressive growth holdings: use wider strikes to preserve upside.
- Strike: 20-30% OTM (not 10-20% as in standard skill — growth names run hard)
- Expiry: 30-45 DTE for maximum theta decay rate
- Premium target: 0.5-1.5% of stock value per month (growth names have higher IV)
- Do NOT sell covered calls within 14 days of earnings on that ticker
- If stock rips through your strike and is called away: this is a profitable outcome.
  Do not buy back the call to avoid assignment unless the gain would be taxed suboptimally.
- After assignment: see CSP-to-Covered-Call lifecycle below

### 4. Cash-Secured Put — Entry Strategy for Core and Growth Tiers

Use when: You want to own a core or growth ticker at a price 5-15% below market.
Only sell CSPs on tickers you genuinely want to own at the strike price.

- Strike: 5-15% OTM (your target entry price)
- Expiry: 30-45 DTE
- IVR gate: above 30% preferred — you want elevated IV when selling
- If assigned: you buy the stock at strike minus premium — lower cost basis than market
- If not assigned: premium is yours, re-evaluate next cycle

### CSP-to-Covered-Call Lifecycle (Complete)
After a CSP is assigned and you own the shares:
1. Immediately verify: is the thesis still intact at current price?
   - Thesis intact: proceed to step 2
   - Thesis broken since selling the put: sell shares immediately, document why
2. Evaluate covered call at 20-30% OTM, 30-45 DTE on the assigned shares
3. Track effective cost basis = strike price - CSP premium - all CC premiums collected
4. Continue selling covered calls monthly until:
   - CC premiums have fully offset original cost basis (you are now in for free)
   - OR: thesis breaks (sell shares immediately)
   - OR: stock rips to assignment (profitable outcome — accept it)

### 5. Protective Put — Portfolio Hedge

Use when: VIX is climbing above 25, portfolio is 80%+ deployed, macro risk is elevated.
This is insurance, not a profit center. Size accordingly.

- Buy SPY or QQQ puts (not individual stock puts unless concentrated risk in one name)
- Strike: 5-10% OTM
- Expiry: 45-60 DTE
- Size: enough to offset 20-30% portfolio drawdown at max pain scenario
- Exit: close at 50% profit OR when VIX normalizes below 20, whichever comes first
- Cost budget: no more than 0.5% of portfolio value per month on portfolio hedges

---

## Greeks to Monitor Each Cycle

**Delta (Δ):** Direction exposure.
- Long calls: positive. Long puts: negative. Covered calls: reduces net delta.
- Keep net portfolio delta aligned with your market view
- If VIX spikes and you want to reduce risk: sell covered calls on core positions
  (reduces delta and generates premium simultaneously)

**Theta (Θ):** Time decay.
- Buying options: minimize theta by trading 60-120 DTE and exiting at 21 DTE
- Selling options (covered calls, CSPs): maximize by targeting 30-45 DTE
- In consolidating markets: theta decay favors sellers — focus on covered calls

**Vega (V):** IV sensitivity.
- Buy options when IVR < 30% (IV is cheap — own the volatility)
- Sell options when IVR > 50% (IV is elevated — collect inflated premium)
- IVR between 30-50%: context-dependent, check direction of IV trend

**Gamma (Γ):** Delta acceleration near expiry.
- Avoid holding short options within 7 DTE — gamma risk spikes dramatically
- Never hold short options through an earnings announcement
- Long options within 7 DTE of expiry: close them — time value is nearly zero

---

## Risk Rules — Non-Negotiable

- Maximum options allocation: 25% of total portfolio value
- Never sell naked calls — covered calls only (must own the underlying shares)
- Never sell naked puts beyond cash-secured (must have full cash collateral)
- Never let a long option lose more than 50% — close it and accept the loss
- Never hold a long option to expiration — exit at 21 DTE minimum
- Moon shot tickers: no options — buy stock in small size or not at all
- Always know your maximum loss before entering:
  - Long options: premium paid
  - Covered calls: opportunity cost if stock exceeds strike
  - CSPs: strike price × 100 minus premium collected

---

## IVR and Earnings Discipline

- Check IVR before every options trade — record it in the rationale field
- Never buy options within 7 days of earnings on that ticker (matches stock rule)
- Never sell covered calls within 14 days of earnings (buyback risk too high)
- If you hold long options and earnings are approaching: close before open on
  announcement day unless conviction is extremely high and position is small
- After earnings: IVR typically collapses (IV crush). Avoid buying options
  immediately after earnings — wait 2-3 sessions for IV to normalize