# Portugal AutoSwitch — MVP (Manie-style)

Auto-switches electricity provider at contract end to cheapest offer.

## Run (no deps, stdlib only)

```bash
cd portugal-autoswitch-mvp
python3 app.py
# open http://localhost:8787
```

## Flow
1. Register contract: CPE, supplier, power kVA, annual kWh, tariff, `contract_end`, explicit mandate checkbox (RGPD).
2. `POST /api/cron/run` scans contracts where `contract_end - today <= 30d` (or no end date). If cheapest saves ≥20€/yr ex-VAT vs current, creates `pending` switch with 48h `expires_at`.
3. User Confirm / Cancel / Execute in UI. Execute simulates new-supplier adhesion and updates contract.

## APIs
- `GET /api/offers` — seeded from `offers.json` (update from https://simuladorprecos.erse.pt/)
- `POST /api/contracts` — requires `cpe`, `email`, `consent:true`
- `GET /api/compare?contract_id=N`
- `POST /api/cron/run {"min_saving":20}`
- `POST /api/switches/<id>/confirm|cancel|execute`

## Comparison: `compare.py:1`
`annual = kWh*price_kwh + power_price_day*365`, +23% IVA for display. Bi-horário uses 60/40 split by default.

## Production gaps (intentional for MVP)
- Offers are static seed. Need ERSE scraper + supplier tariff PDFs.
- Invoice PDF parsing not included — add `fatura` upload + CPE/kWh extractor.
- Real switch needs mandate PDF + supplier adhesion (no central API in PT).
- Add auth, E-REDES CPE validation, MEO/EDP distributor handling, fidelity penalty check.
