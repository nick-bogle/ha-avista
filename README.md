# Avista Utilities for Home Assistant

Pulls electric and gas usage and cost from [Avista](https://www.myavista.com) into
Home Assistant's Energy dashboard, via the [bidgely](https://github.com/nick-bogle/bidgely)
library.

Avista publishes usage roughly a day late, so this integration writes **long term
statistics** rather than live sensors. It creates no entities; the data appears in
the Energy dashboard and in Developer Tools -> Statistics.

## Installation

1. Add this repository to HACS as a custom repository (category: Integration), or
   copy `custom_components/avista/` into your `config/custom_components/`.
2. Restart Home Assistant.
3. Settings -> Devices & Services -> Add Integration -> **Avista Utilities**.
4. Sign in with your myavista.com email and password.

Electric and gas are detected automatically: the setup probes each fuel and enables
whichever the account actually has service for.

## Energy dashboard

Settings -> Energy, then add:

| Source | Statistic |
|---|---|
| Electricity grid consumption | `Avista electric consumption` |
| ... with cost | `Avista electric cost` |
| Gas consumption | `Avista gas consumption` |
| ... with cost | `Avista gas cost` |

## Known caveat: gas is reported in therms, labelled CCF

**Avista meters gas in therms. Home Assistant has no therm unit**, so the gas
statistic is labelled `CCF` (hundred cubic feet) — the same unit the `opower`
integration uses for gas.

The therm values are passed through **unconverted**. Therms measure energy and CCF
measures volume; converting between them requires the gas heat content, which the
Avista API never returns. Any conversion factor would be a guess that corrupts the
numbers, so the numbers you see match your bill exactly and only the unit label is
wrong (1 CCF is roughly 1.037 therms, so treat the label as nominal).

Costs are unaffected — they come straight from the API in dollars.

## Notes

- **No bill forecast.** Avista's Bidgely host puts `/2.1/*` (`billprojections`)
  behind AWS IAM auth and rejects bearer tokens, so no forecast is available.
- **First run is slow.** Hourly data costs one request per day, so the initial
  365-day backfill makes a few hundred requests (4 at a time). Later refreshes
  re-read only the last 30 days, every 12 hours, to pick up utility corrections.
- **Statistic IDs** are keyed by the Bidgely user id, because Avista's
  `getBidgelyWidgetData` returns whichever account the session has active — the
  account number is never sent.

## Requirements

Home Assistant 2026.2.3 or newer — verified against that version. The statistics
metadata this writes uses `mean_type`/`unit_class`, which replaced the `has_mean`
field removed in 2026.4.
