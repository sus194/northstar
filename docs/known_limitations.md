# Known limitations (spec section 9.2)

Stated up front, per principle 6: parameters are frozen before testing, and
the limits of the test are stated before the test is run, not discovered
after a result looks good.

## Small n

The liquid TSX universe is roughly 300-400 names. With a 30% momentum cut,
a 30% dip cut, six veto layers, and a one-signal-per-day cap, expect on the
order of 5-15 signals per month in-sample. Twelve in-sample years is a few
hundred trades -- enough to detect a large edge, not a small one. Every
report should carry a confidence interval, not a point estimate, on mean R.

## Survivorship

If the chosen data vendor lacks delisted-symbol history, the backtest is
survivorship-biased and every report generated from it must say so on its
first line. See `docs/data_provider_requirements.md`.

## Canadian evidence is thin

Intermediate-term momentum on the TSX is documented (Assoe, Attig & Sy
2024). Five-day sector-relative reversal on the TSX specifically is not --
this strategy imports US/international evidence (Da, Liu & Schaumburg
2014; Dai, Medhat, Novy-Marx & Rizova 2024) onto a market it has not been
tested on until this project's own backtest runs.

## Long-only, gross-to-net

The academic reversal literature is mostly long-short and gross of costs.
This strategy is long-only and pays the spread on both legs. Expect
materially less than the published effect sizes.

## Trading calendar

`engine/calendar.py` approximates the TSX calendar with a Monday-Friday
business calendar and no holiday list. This shifts "N trading days"
computations by one around any holiday that doesn't fall on both the
Canadian and generic business calendars, biasing fill/expiry/time-limit
dates slightly. Replace with a real TSX holiday calendar
(`numpy.busdaycalendar(holidays=[...])`) before running the in-sample
backtest for real -- this is a correctness issue for that run, not just a
style note.

## Spread proxy

`engine/indicators.corwin_schultz_spread` estimates the bid-ask spread from
OHLC data alone (Corwin & Schultz 2012), since v1 has no NBBO feed. It is a
real, citable estimator -- not the earlier naive (high-low)/close proxy,
which conflates spread with intraday volatility and would fail nearly
every volatile momentum name against U2's 0.50% cap. Corwin-Schultz is
still an estimate; replace it with real quoted-spread data if a feed
becomes available.

## Backtest mechanics

- Equity is marked to market at each day's close; there is no intraday
  P&L path.
- One position per symbol at a time; partial fills are not modeled.
- Exit-watch regime and earnings-proximity checks in the backtest harness
  are simplified relative to the live nightly job (see
  `backtest/harness.py`); before trusting a holdout run, diff its exit
  logic against `scripts/run_nightly.py`'s.
