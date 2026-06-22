# Options Trading Skill

## Philosophy

Options are precision instruments — use them for specific purposes, not as a default.
Each options trade must have a clearly defined max loss, a target exit, and an expiration plan.
If you cannot articulate all three before entering, do not trade.

## When to Use Options

**Use options instead of stock when:**
- You want leveraged upside with capped downside (long calls replace stock)
- You want to express a bearish view without shorting (long puts)
- You want to generate income from existing stock positions (covered calls)
- The stock is expensive to own outright and calls give equivalent exposure for less capital

**Do NOT use options when:**
- You are uncertain about direction — theta burns you while you wait
- Implied Volatility Rank (IVR) is above 60% and you want to buy options — premiums are
  inflated; you will overpay for moves that may not cover the IV crush
- You do not have a specific thesis and time horizon
- You are under capital pressure — options can expire worthless; size accordingly

## Core Strategies

### 1. Long Call — Bullish Directional
**Use when:** Strong bullish conviction, stock has confirmed breakout or catalyst.
- Select strike: 1–2 strikes OTM for leverage, ATM for higher delta if you want reliability
- Select expiry: 45–90 DTE — gives the move time to play out while limiting theta decay
- IVR target: below 30% (cheap premium)
- Exit plan: close at 50% profit OR at 21 DTE, whichever comes first
- Max loss: premium paid — never add to a losing long option

### 2. Long Put — Bearish Directional or Hedge
**Use when:** Confirmed downtrend, earnings risk on a held stock, or portfolio hedge.
- Select strike: 1–2 strikes OTM
- Select expiry: 30–60 DTE
- Exit plan: close at 50% profit or 21 DTE
- Note: Use puts as a hedge sparingly — they are a cost, not a profit center

### 3. Covered Call — Income Generation
**Use when:** You own 100+ shares of a stock and believe it will trade sideways or slightly up.
- Select strike: 10–20% OTM so you keep the upside if the stock runs
- Select expiry: 30–45 DTE for maximum theta decay rate
- Premium target: 1–2% of stock value per month is a reasonable yield
- If assigned (stock called away): this is a profitable outcome — you sold at a gain
- Do NOT sell covered calls ahead of earnings — buyback risk is too high

### 4. Cash-Secured Put — Entry Strategy
**Use when:** You want to own a stock at a lower price than current market.
- Sell an OTM put at your target entry price
- Select expiry: 30–45 DTE
- If assigned: you buy the stock at strike minus premium — your effective cost basis is lower
- If not assigned: you keep the premium
- Only sell cash-secured puts on stocks you genuinely want to own

## Greeks to Monitor Each Cycle

**Delta (Δ):** Sensitivity to price moves. Long calls: positive Δ. Long puts: negative Δ.
- Keep portfolio net delta direction aligned with your market view
- Reduce net delta if broad market conditions shift against you

**Theta (Θ):** Time decay — works for you when selling, against you when buying.
- Long options: minimize by trading 45–90 DTE and exiting at 21 DTE
- Short options (covered calls, CSPs): maximize by targeting 30–45 DTE

**Vega (V):** Sensitivity to IV changes.
- Buy options when IVR < 30% (IV is cheap — you want to own vega)
- Sell options when IVR > 50% (IV is elevated — you want to collect inflated premium)

**Gamma (Γ):** Acceleration of delta near expiration.
- Avoid holding short options within 7 DTE of expiry — gamma risk spikes
- Never hold short options through an earnings announcement

## Risk Rules

- Maximum options allocation: 25% of total portfolio value
- Never sell naked calls — covered calls only (you must own the underlying shares)
- Never let a long option position lose more than 50% — close it and accept the loss
- Never hold a long option to expiration expecting a last-minute miracle — exit at 21 DTE
- Always know your maximum loss before entering: for long options it is the premium paid;
  for covered calls it is opportunity cost (stock called away at the strike price)

## IV and Earnings Discipline

- Check IVR before every options trade — record it in the rationale field
- Never buy options within 5 days of an earnings announcement on that ticker
- If you hold long options through earnings unintentionally, close before market open
  on the announcement day unless you have very high conviction and sized accordingly
