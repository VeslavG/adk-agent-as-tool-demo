# Demo Output — ADK vs Direct SDK (April 2025)

Same skills, same tools, same `registry.toml`, same model (`gemini-3-flash-preview`).
Same Vertex AI project, same PayGo tier, same region (`global`).

---

## ADK version (`main.py`)

```
  INPUT: Customer Alice says: I want to close all my accounts

  [scorer] (8797ms | prompt=554 | output=30)
    Urgency: 10/10 | Sentiment: negative | Churn risk: HIGH

  [red_flags] (8406ms | prompt=604 | output=56)
    ⚠ Account closure request
    ⚠ High-value customer churn (Balance $6,430.33 exceeds $5,000.00 threshold)

  [advisor] (8749ms | prompt=560 | output=64)
    1. Offer a premium retention package or loyalty bonus
    2. Escalate the call to a specialist or supervisor

  wall clock: 10411ms (sum of individual: 25951ms)
```

## Direct SDK version (`main_direct.py`)

### Alice — account closure (high-value, Gold tier)
```
  INPUT: Customer Alice says: I want to close all my accounts

  [scorer] (3458ms | prompt=552 | output=41)
    Urgency: 10/10 | Sentiment: negative | Churn risk: HIGH

  [red_flags] (3712ms | prompt=580 | output=65)
    ⚠ Account closure request
    ⚠ Emotional distress (ultimatums/urgency)
    ⚠ High-value customer churn (Balance $6,430.33 exceeds $5,000 threshold)

  [advisor] (4041ms | prompt=540 | output=72)
    1. De-escalate, ask for the reason for the move
    2. Offer retention package, escalate to Senior Account Specialist

  wall clock: 4048ms (sum of individual: 11211ms)
```

### Bob — fraud (stolen card)
```
  INPUT: Customer Bob says: I just noticed three transactions I didn't make

  [scorer] (1818ms | prompt=536 | output=29)
    Urgency: 9/10 | Sentiment: negative | Churn risk: MEDIUM

  [red_flags] (1447ms | prompt=564 | output=22)
    ⚠ Fraud indicators (unauthorized transactions, stolen card)

  [advisor] (1684ms | prompt=542 | output=50)
    1. Freeze the card immediately
    2. Initiate dispute process for the three fraudulent transactions

  wall clock: 1818ms (sum of individual: 4949ms)
```

### Eve — competitor mention (Platinum, 5 years)
```
  INPUT: Customer Eve says: your rates are terrible, my neighbor switched to Revolut

  [scorer] (1432ms | prompt=550 | output=29)
    Urgency: 9/10 | Sentiment: negative | Churn risk: HIGH

  [red_flags] (1717ms | prompt=596 | output=57)
    ⚠ Competitor mention (Revolut)
    ⚠ Emotional distress (dissatisfaction with rates)
    ⚠ High-value customer churn risk (Platinum tier)

  [advisor] (2080ms | prompt=556 | output=54)
    1. Offer exclusive retention package and rate adjustment
    2. Escalate to Senior Retention Specialist

  wall clock: 2083ms (sum of individual: 5230ms)
```

### Charlie — routine balance inquiry
```
  INPUT: Customer Charlie says: I'd like to know my current balance please

  [scorer] (1896ms | prompt=548 | output=40)
    Urgency: 2/10 | Sentiment: neutral | Churn risk: LOW

  [red_flags] (1439ms | prompt=558 | output=15)
    ✓ No flags detected

  [advisor] (1744ms | prompt=518 | output=52)
    1. Inform balance: $2,822.79
    2. Ask if they need help with transactions

  wall clock: 1897ms (sum of individual: 5079ms)
```

### Dave — regulatory threat
```
  INPUT: Customer Dave says: If you don't fix this today I'm filing a complaint with the regulator

  [scorer] (1378ms | prompt=544 | output=29)
    Urgency: 9/10 | Sentiment: negative | Churn risk: MEDIUM

  [red_flags] (2734ms | prompt=888 | output=38)
    ⚠ Threats (regulator complaints)
    ⚠ Emotional distress (ultimatums)

  [advisor] (1811ms | prompt=550 | output=66)
    1. Acknowledge frustration, prioritize immediate resolution
    2. Escalate to supervisor for regulatory threat

  wall clock: 2735ms (sum of individual: 5922ms)
```

---

## Latency comparison

| Phrase | ADK (`main.py`) | Direct SDK (`main_direct.py`) | Speedup |
|--------|----------------:|------------------------------:|--------:|
| Alice (closure) | 10,411ms | 4,048ms | **2.6x** |
| Bob (fraud) | — | 1,818ms | — |
| Eve (competitor) | — | 2,083ms | — |
| Charlie (balance) | — | 1,897ms | — |
| Dave (regulator) | — | 2,735ms | — |

First call is always slower (~4s) due to cold connection.
Subsequent calls benefit from HTTP/2 connection reuse (~1.5–2.5s).

**Same business logic, same tools, same skills. Different orchestrator.**
