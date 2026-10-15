"""Comparison engine for Portugal electricity MVP. Stdlib only."""
import json

IVA_RATE = 0.23

def load_offers(path="offers.json"):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data["offers"], data.get("iva_rate", IVA_RATE)

def annual_cost_ex_vat(offer, power_kva, annual_kwh, tariff="simples", night_share=0.4):
    """Estimate annual cost ex-VAT. Power key fallback to closest tier."""
    power_key = str(power_kva)
    ppd = offer.get("power_price_day", {})
    if power_key not in ppd:
        # fallback: nearest tier
        tiers = sorted(float(k) for k in ppd.keys())
        target = float(power_kva)
        nearest = min(tiers, key=lambda t: abs(t - target))
        power_key = str(nearest) if str(nearest) in ppd else f"{nearest:.2f}".rstrip("0").rstrip(".")
        # last resort: first value
        if power_key not in ppd:
            power_key = next(iter(ppd))
    power_cost = ppd[power_key] * 365

    if offer.get("tariff") == "bi-horario":
        if tariff == "bi-horario":
            day_kwh = annual_kwh * (1 - night_share)
            night_kwh = annual_kwh * night_share
        else:
            # user on simples comparing to bi-horario: assume 60/40 split
            day_kwh = annual_kwh * 0.6
            night_kwh = annual_kwh * 0.4
        energy_cost = day_kwh * offer["price_kwh_day"] + night_kwh * offer["price_kwh_night"]
    else:
        energy_cost = annual_kwh * offer["price_kwh"]

    return round(power_cost + energy_cost, 2)

def with_iva(value, rate=IVA_RATE):
    return round(value * (1 + rate), 2)

def rank_offers(offers, power_kva, annual_kwh, tariff="simples", current_offer_id=None, min_saving=20.0):
    """Return offers sorted by cost, plus best-switch recommendation."""
    ranked = []
    for o in offers:
        # skip bi-horario offers if user is simples? No - include all, engine handles split.
        cost = annual_cost_ex_vat(o, power_kva, annual_kwh, tariff)
        ranked.append({**o, "est_annual_ex_vat": cost, "est_annual_inc_vat": with_iva(cost)})
    ranked.sort(key=lambda r: r["est_annual_ex_vat"])

    current_cost = None
    if current_offer_id:
        for r in ranked:
            if r["id"] == current_offer_id:
                current_cost = r["est_annual_ex_vat"]
                break

    recommendation = None
    cheapest = ranked[0] if ranked else None
    if cheapest:
        base = current_cost
        if base is None:
            # no current mapped: recommend cheapest vs most expensive as reference
            most_exp = ranked[-1]["est_annual_ex_vat"]
            saving = round(most_exp - cheapest["est_annual_ex_vat"], 2)
            if saving >= min_saving:
                recommendation = {"offer": cheapest, "saving_ex_vat": saving, "vs": "most_expensive_in_db"}
        elif cheapest["id"] != current_offer_id:
            saving = round(base - cheapest["est_annual_ex_vat"], 2)
            if saving >= min_saving:
                recommendation = {"offer": cheapest, "saving_ex_vat": saving, "vs": current_offer_id}

    return ranked, recommendation
