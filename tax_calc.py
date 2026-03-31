"""
Polish Tax Calculator 2026 — Python port of frontend/src/utils/taxCalculator.js

Calculates monthly netto ("na rękę") from:
  - B2B: faktura netto → netto after ZUS + zdrowotna + tax − vacation cost
  - UoP: brutto → netto after ZUS + zdrowotna + PIT

All calculations are MONTHLY averages. Yearly amounts (PIT thresholds,
IKZE limits, ZUS caps) are divided by 12 for monthly approximation.

Standalone — no external dependencies beyond Python stdlib.
"""

# =============================================================================
# Constants
# =============================================================================

TAX_YEAR = 2026

# -- Time constants --
WORKING_DAYS_YEAR = 251
WORKING_DAYS_MONTH = WORKING_DAYS_YEAR / 12  # ~20.917
WORKING_HOURS_MONTH = round(WORKING_DAYS_YEAR / 12 * 8, 1)  # 167.3
UOP_PAID_VACATION_DAYS = 26

# -- Wages --
MIN_WAGE = 4806

# -- UoP: employee social contributions (% of gross) --
UOP_EMERYTALNA = 0.0976
UOP_RENTOWA = 0.015
UOP_CHOROBOWA = 0.0245
UOP_SPOLECZNE = 0.1371  # sum of above three (used only when below cap)
UOP_ZDROWOTNA_RATE = 0.09

# -- UoP: yearly ZUS cap --
UOP_ZUS_CAP_YEARLY = 282600

# -- UoP: Koszty Uzyskania Przychodu --
UOP_KUP_STANDARD = 250
UOP_KUP_PODWYZSZONE = 300
UOP_KUP_50_MAX_MONTHLY = 10000

# -- PIT --
PIT_RATE_1 = 0.12
PIT_RATE_2 = 0.32
PIT_THRESHOLD_YEARLY = 120000
PIT_KWOTA_WOLNA_YEARLY = 3600  # 12% × 30,000
KWOTA_WOLNA_ROCZNA = 30000

# -- Employer cost (UoP) --
PRACODAWCA_TOTAL = 0.2048

# -- B2B: ZUS configurations --
ZUS_CONFIGS = {
    "duzy": {
        "podstawa": 5652,
        "emerytalne": 0.1952,
        "rentowe": 0.08,
        "wypadkowe": 0.0167,
        "chorobowe": 0.0245,
        "fp": 0.0245,
    },
    "maly": {
        "podstawa": 1441.80,
        "emerytalne": 0.1952,
        "rentowe": 0.08,
        "wypadkowe": 0.0167,
        "chorobowe": 0.0245,
        "fp": 0,
    },
    "ulga_na_start": {
        "podstawa": 0,
        "emerytalne": 0,
        "rentowe": 0,
        "wypadkowe": 0,
        "chorobowe": 0,
        "fp": 0,
    },
}

# -- B2B: Health insurance --
B2B_ZDROWOTNA_MIN = 432.54
RYCZALT_ZDROWOTNA_BASE = 9228.64
B2B_ZDROWOTNA_LINIOWY_RATE = 0.049
B2B_ZDROWOTNA_SKALA_RATE = 0.09
LINIOWY_ZDROWOTNA_CAP_YEARLY = 14100

# -- IKZE --
IKZE_LIMIT_UOP_YEARLY = 11304
IKZE_LIMIT_B2B_YEARLY = 16956


# =============================================================================
# Helpers — match JS rounding: Number(x.toFixed(2)) → round(x, 2)
# =============================================================================

def _r2(x):
    """Round to 2 decimal places (matches JS .toFixed(2))."""
    return round(x, 2)


def _r0(x):
    """Round to 0 decimal places (matches JS .toFixed(0) / Math.round)."""
    return round(x)


# =============================================================================
# B2B ZUS components
# =============================================================================

def calc_zus_components(zus_type="duzy", include_chorobowe=False):
    """
    Monthly ZUS contributions for B2B based on ZUS tier.
    Chorobowe (sickness) is voluntary for B2B — OFF by default.

    Returns dict: { emerytalne, rentowe, wypadkowe, chorobowe, fp, spoleczne }
    where spoleczne = em + rent + wyp + chor (NO FP)
    """
    cfg = ZUS_CONFIGS.get(zus_type, ZUS_CONFIGS["duzy"])
    p = cfg["podstawa"]
    emerytalne = _r2(p * cfg["emerytalne"])
    rentowe = _r2(p * cfg["rentowe"])

def oblicz_pit_roczny(podstawa_roczna):
    """
    Progressive PIT scale used by UoP and B2B skala.
    0–30k → 0 (kwota wolna), 30k–120k → 12%, 120k+ → 32%.
    """
    a = float(podstawa_roczna)
    if a <= 0:
        return 0
    if a <= KWOTA_WOLNA_ROCZNA:
        return 0
    if a <= PIT_THRESHOLD_YEARLY:
        return max(0, PIT_RATE_1 * a - PIT_KWOTA_WOLNA_YEARLY)
    # II bracket: 10,800 = PIT at threshold (12% × 120k - 3,600)
    nadwyzka = a - PIT_THRESHOLD_YEARLY
    return 10800 + PIT_RATE_2 * nadwyzka


# =============================================================================
# UoP: brutto → netto
# =============================================================================

def calc_uop(brutto, options=None):
    """
    UoP brutto → netto.

    Options (dict):
        kup50, kup50_percent, uop_vacation_days, podwyzszone_kup,
        age_under_26, spouse_joint, ikze, tax_relief
    """
    if options is None:
        options = {}

    kup50 = options.get("kup50", False)
    kup50_percent = options.get("kup50_percent", None)
    uop_vacation_days = options.get("uop_vacation_days", 0)
    podwyzszone_kup = options.get("podwyzszone_kup", False)
    age_under_26 = options.get("age_under_26", False)
    spouse_joint = options.get("spouse_joint", False)
    ikze = options.get("ikze", False)
    tax_relief = options.get("tax_relief", None)

    # 1. Social contributions with yearly cap
    yearly_brutto = brutto * 12
    if yearly_brutto > UOP_ZUS_CAP_YEARLY:
        emerytalna = _r2(UOP_ZUS_CAP_YEARLY * UOP_EMERYTALNA / 12)
        rentowa = _r2(UOP_ZUS_CAP_YEARLY * UOP_RENTOWA / 12)
    else:
        emerytalna = _r2(brutto * UOP_EMERYTALNA)
        rentowa = _r2(brutto * UOP_RENTOWA)
    chorobowa = _r2(brutto * UOP_CHOROBOWA)
    zus_spoleczne = _r2(emerytalna + rentowa + chorobowa)

    # 2. Health insurance
    podstawa_zdrowotna = brutto - zus_spoleczne
    zdrowotna = _r2(podstawa_zdrowotna * UOP_ZDROWOTNA_RATE)

    # 3. KUP
    standard_kup = UOP_KUP_PODWYZSZONE if podwyzszone_kup else UOP_KUP_STANDARD
    if kup50:
        work_ratio = (
            max(0, (WORKING_DAYS_YEAR - uop_vacation_days) / WORKING_DAYS_YEAR)
            if uop_vacation_days > 0
            else 1
        )
        kup50_pct = kup50_percent / 100 if kup50_percent is not None else 1
        creative_base = podstawa_zdrowotna * work_ratio * kup50_pct
        kup50_amount = min(0.5 * creative_base, UOP_KUP_50_MAX_MONTHLY)
        kup = kup50_amount + standard_kup
    else:
        kup = standard_kup

    # 4. Monthly tax base → yearly for PIT brackets
    podstawa_mies = max(0, round(brutto - zus_spoleczne - kup))
    podstawa_roczna = podstawa_mies * 12

    # 5. PIT (yearly → monthly)
    if age_under_26 or tax_relief:
        pit_roczny = 0
    elif spouse_joint:
        pit_roczny = oblicz_pit_roczny(podstawa_roczna)
        if podstawa_roczna <= PIT_THRESHOLD_YEARLY * 2:
            pit_roczny = max(0, PIT_RATE_1 * podstawa_roczna - PIT_KWOTA_WOLNA_YEARLY * 2)
    else:
        pit_roczny = oblicz_pit_roczny(podstawa_roczna)

    pit_mies = max(0, round(pit_roczny / 12))

    # IKZE
    if ikze:
        ikze_mies = IKZE_LIMIT_UOP_YEARLY / 12
        pit_rate = PIT_RATE_1 if podstawa_roczna <= PIT_THRESHOLD_YEARLY else PIT_RATE_2
        pit_mies = max(0, pit_mies - round(ikze_mies * pit_rate))

    # 6. Final netto
    netto = _r2(brutto - zus_spoleczne - zdrowotna - pit_mies)
    koszt_pracodawcy = _r2(brutto * (1 + PRACODAWCA_TOTAL))

    return {
        "netto": netto,
        "breakdown": {
            "brutto": brutto,
            "zus_spoleczne": zus_spoleczne,
            "zdrowotna": zdrowotna,
            "podatek": pit_mies,
            "kup": kup,
            "koszt_pracodawcy": koszt_pracodawcy,
        },
    }


# =============================================================================
# B2B Ryczałt: faktura netto → netto na rękę
# =============================================================================

def calc_b2b_ryczalt(faktura_netto, options=None):
    """
    B2B ryczałt — flat tax rate on revenue.

    Options (dict):
        ryczalt_rate (default 12), zus_type, vacation_days,
        paid_vacation_days, ikze
    """
    if options is None:
        options = {}

    ryczalt_rate = options.get("ryczalt_rate", 12)
    zus_type = options.get("zus_type", "duzy")
    vacation_days = options.get("vacation_days", 0)
    paid_vacation_days = options.get("paid_vacation_days", 0)
    ikze = options.get("ikze", False)

    # 1. ZUS
    zus = calc_zus_components(zus_type)

    # 2. Zdrowotna (bracket-based)
    zdrowotna = calc_ryczalt_zdrowotna(faktura_netto, zus["spoleczne"])

    # 3. Total ZUS
    suma_zus = _r2(zus["spoleczne"] + zus["fp"] + zdrowotna)

    # 4. Tax: ryczałt rate × (przychód - społeczne - 50% zdrowotna)
    zdrowotna_deduction = _r2(0.5 * zdrowotna)
    tax_base = faktura_netto - zus["spoleczne"] - zdrowotna_deduction
    podatek = _r0(_r2(ryczalt_rate / 100 * tax_base))

    # 5. Netto before vacation
    na_reke = _r2(faktura_netto - podatek - suma_zus)

    # 6. Vacation cost
    dni_bezplatne = max(0, vacation_days - (paid_vacation_days or 0))
    urlop_koszt = 0
    if dni_bezplatne > 0:
        dzienna_stawka = _r2(faktura_netto / (WORKING_DAYS_YEAR / 12))
        urlop_koszt = _r2(dzienna_stawka * dni_bezplatne / 12)

    return {
        "netto": _r2(na_reke - urlop_koszt),
        "netto_bez_urlopu": na_reke,
        "breakdown": {
            "faktura_netto": faktura_netto,
            "zus_spoleczne": zus["spoleczne"],
            "zus_fp": zus["fp"],
            "zdrowotna": zdrowotna,
            "podatek": podatek,
            "urlop_koszt": urlop_koszt,
            "sumaZus": suma_zus,
        },
    }


# =============================================================================
# B2B Liniowy 19%: faktura netto → netto na rękę
# =============================================================================

def calc_b2b_liniowy(faktura_netto, options=None):
    """
    B2B liniowy — flat 19% on profit.

    Options (dict):
        zus_type, vacation_days, paid_vacation_days, ikze
    """
    if options is None:
        options = {}

    zus_type = options.get("zus_type", "duzy")
    vacation_days = options.get("vacation_days", 0)
    paid_vacation_days = options.get("paid_vacation_days", 0)
    ikze = options.get("ikze", False)

    # 1. ZUS
    zus = calc_zus_components(zus_type)

    # 2. Zdrowotna: 4.9% of (revenue - społeczne), min 432.54
    zdrowotna_base = faktura_netto - zus["spoleczne"]
    zdrowotna = max(B2B_ZDROWOTNA_MIN, _r2(zdrowotna_base * B2B_ZDROWOTNA_LINIOWY_RATE))

    # 3. Total ZUS
    suma_zus = _r2(zus["spoleczne"] + zus["fp"] + zdrowotna)

    # 4. Tax: 19% × (przychód - społeczne - FP - zdrowotna_deduction)
    s = _r2(zus["spoleczne"] + zus["fp"])
    zdrowotna_deduction = _r2(min(zdrowotna, LINIOWY_ZDROWOTNA_CAP_YEARLY / 12))
    tax_base = faktura_netto - s - zdrowotna_deduction
    podatek = _r0(_r2(0.19 * tax_base))

    # IKZE
    if ikze:
        ikze_mies = IKZE_LIMIT_B2B_YEARLY / 12
        podatek = max(0, _r0(podatek - _r0(ikze_mies * 0.19)))

    # 5. Netto before vacation
    na_reke = _r2(faktura_netto - podatek - suma_zus)

    # 6. Vacation cost
    dni_bezplatne = max(0, vacation_days - (paid_vacation_days or 0))
    urlop_koszt = 0
    if dni_bezplatne > 0:
        dzienna_stawka = _r2(faktura_netto / (WORKING_DAYS_YEAR / 12))
        urlop_koszt = _r2(dzienna_stawka * dni_bezplatne / 12)

    return {
        "netto": _r2(na_reke - urlop_koszt),
        "netto_bez_urlopu": na_reke,
        "breakdown": {
            "faktura_netto": faktura_netto,
            "zus_spoleczne": zus["spoleczne"],
            "zus_fp": zus["fp"],
            "zdrowotna": zdrowotna,
            "podatek": podatek,
            "urlop_koszt": urlop_koszt,
            "sumaZus": suma_zus,
        },
    }


# =============================================================================
# B2B Skala 12/32%: faktura netto → netto na rękę
# =============================================================================

def calc_b2b_skala(faktura_netto, options=None):
    """
    B2B skala — progressive scale (12%/32%), same brackets as UoP PIT.

    Options (dict):
        zus_type, vacation_days, paid_vacation_days, spouse_joint, ikze
    """
    if options is None:
        options = {}

    zus_type = options.get("zus_type", "duzy")
    vacation_days = options.get("vacation_days", 0)
    paid_vacation_days = options.get("paid_vacation_days", 0)
    spouse_joint = options.get("spouse_joint", False)
    ikze = options.get("ikze", False)

    # 1. ZUS
    zus = calc_zus_components(zus_type)

    # 2. Zdrowotna: 9% of (revenue - społeczne), min 432.54
    zdrowotna_base = faktura_netto - zus["spoleczne"]
    zdrowotna = max(B2B_ZDROWOTNA_MIN, _r2(zdrowotna_base * B2B_ZDROWOTNA_SKALA_RATE))

    # 3. Total ZUS
    suma_zus = _r2(zus["spoleczne"] + zus["fp"] + zdrowotna)

    # 4. Tax: progressive scale on (przychód - społeczne - FP)
    s = _r2(zus["spoleczne"] + zus["fp"])
    podstawa_roczna = 12 * (faktura_netto - s)

    if spouse_joint and podstawa_roczna <= PIT_THRESHOLD_YEARLY * 2:
        pit_roczny = max(0, PIT_RATE_1 * podstawa_roczna - PIT_KWOTA_WOLNA_YEARLY * 2)
    else:
        pit_roczny = oblicz_pit_roczny(podstawa_roczna)

    podatek = max(0, round(pit_roczny / 12))

    # IKZE
    if ikze:
        ikze_mies = IKZE_LIMIT_B2B_YEARLY / 12
        rate = PIT_RATE_1 if podstawa_roczna <= PIT_THRESHOLD_YEARLY else PIT_RATE_2
        podatek = max(0, podatek - round(ikze_mies * rate))

    # 5. Netto before vacation
    na_reke = _r2(faktura_netto - podatek - suma_zus)

    # 6. Vacation cost
    dni_bezplatne = max(0, vacation_days - (paid_vacation_days or 0))
    urlop_koszt = 0
    if dni_bezplatne > 0:
        dzienna_stawka = _r2(faktura_netto / (WORKING_DAYS_YEAR / 12))
        urlop_koszt = _r2(dzienna_stawka * dni_bezplatne / 12)

    return {
        "netto": _r2(na_reke - urlop_koszt),
        "netto_bez_urlopu": na_reke,
        "breakdown": {
            "faktura_netto": faktura_netto,
            "zus_spoleczne": zus["spoleczne"],
            "zus_fp": zus["fp"],
            "zdrowotna": zdrowotna,
            "podatek": podatek,
            "urlop_koszt": urlop_koszt,
            "sumaZus": suma_zus,
        },
    }


# =============================================================================
# All B2B forms at once
# =============================================================================

def calc_b2b_all_forms(faktura_netto, tax_profile=None, job_overrides=None):
    """
    Runs ryczałt, liniowy, and skala for the same faktura netto.

    tax_profile and job_overrides are dicts matching DB column names.
    """
    if tax_profile is None:
        tax_profile = {}
    if job_overrides is None:
        job_overrides = {}

    opts = {
        "zus_type": tax_profile.get("b2b_zus_type") or "duzy",
        "vacation_days": tax_profile.get("b2b_vacation_days_year") if tax_profile.get("b2b_vacation_days_year") is not None else 0,
        "paid_vacation_days": job_overrides.get("b2b_paid_vacation_days") or 0,
        "spouse_joint": bool(tax_profile.get("spouse_joint_filing")),
        "ikze": bool(tax_profile.get("ikze")),
    }

    return {
        "ryczalt": calc_b2b_ryczalt(faktura_netto, {
            **opts,
            "ryczalt_rate": tax_profile.get("b2b_ryczalt_rate") or 12,
        }),
        "liniowy": calc_b2b_liniowy(faktura_netto, opts),
        "skala": calc_b2b_skala(faktura_netto, opts),
    }


# =============================================================================
# Unified calculator: job + tax profile → netto for each applicable variant
# =============================================================================

def calc_job_netto(job, tax_profile=None):
    """
    Main entry point. Job dict + tax profile dict → netto results.

    Returns dict with:
        b2b: { ryczalt, liniowy, skala } (each with netto, netto_bez_urlopu, breakdown)
        uop: { netto, breakdown }
        bestNetto: float or None
        bestLabel: str or None
    """
    if tax_profile is None:
        tax_profile = {}

    results = {}
    period = job.get("salary_period") or "month"

    # B2B calculation
    b2b_from = job.get("salary_b2b_from")
    b2b_to = job.get("salary_b2b_to")
    if b2b_from or b2b_to:
        amt = b2b_to or b2b_from

        # Vacation: reduce working days/hours BEFORE computing tax
        vac_days = tax_profile.get("b2b_vacation_days_year") if tax_profile.get("b2b_vacation_days_year") is not None else 0
        paid_vac_days = job.get("b2b_paid_vacation_days") or 0
        unpaid_vac_days = max(0, vac_days - paid_vac_days)
        effective_days_year = WORKING_DAYS_YEAR - unpaid_vac_days

        # Full faktura (no vacation) — for netto_bez_urlopu display
        full_faktura = amt * WORKING_HOURS_MONTH if period == "hour" else amt
        # Adjusted faktura — reduced income due to unpaid vacation
        if unpaid_vac_days > 0:
            if period == "hour":
                adj_faktura = amt * (effective_days_year / 12 * 8)
            else:
                adj_faktura = amt * (effective_days_year / WORKING_DAYS_YEAR)
        else:
            adj_faktura = full_faktura

        # Pass vacation_days=0 to avoid double-deduction
        no_vac_profile = {**tax_profile, "b2b_vacation_days_year": 0}

        if unpaid_vac_days > 0:
            b2b_adj = calc_b2b_all_forms(adj_faktura, no_vac_profile, job)
            b2b_full = calc_b2b_all_forms(full_faktura, no_vac_profile, job)

            results["b2b"] = {}
            for form in ("ryczalt", "liniowy", "skala"):
                results["b2b"][form] = {
                    **b2b_adj[form],
                    "netto_bez_urlopu": b2b_full[form]["netto"],
                    "breakdown": {
                        **b2b_adj[form]["breakdown"],
                        "faktura_netto": full_faktura,
                        "urlop_koszt": round(b2b_full[form]["netto"] - b2b_adj[form]["netto"]),
                    },
                }
        else:
            results["b2b"] = calc_b2b_all_forms(full_faktura, no_vac_profile, job)

    # UoP calculation
    uop_from = job.get("salary_uop_from")
    uop_to = job.get("salary_uop_to")
    if uop_from or uop_to:
        brutto = uop_to or uop_from
        monthly = brutto * WORKING_HOURS_MONTH if period == "hour" else brutto
        results["uop"] = calc_uop(monthly, {
            "kup50": bool(job.get("uop_kup_50")),
            "kup50_percent": job.get("uop_kup_50_percent"),
            "uop_vacation_days": tax_profile.get("uop_vacation_days") if tax_profile.get("uop_vacation_days") is not None else 26,
            "podwyzszone_kup": bool(job.get("uop_podwyzszone_kup") if job.get("uop_podwyzszone_kup") is not None else tax_profile.get("uop_podwyzszone_kup")),
            "age_under_26": bool(tax_profile.get("age_under_26")),
            "spouse_joint": bool(tax_profile.get("spouse_joint_filing")),
            "ikze": bool(tax_profile.get("ikze")),
            "tax_relief": tax_profile.get("tax_relief") or None,
        })

    # Determine best netto
    best_netto = None
    best_label = None

    if "b2b" in results:
        form = tax_profile.get("b2b_tax_form") or "ryczalt"
        b2b_data = results["b2b"]
        val = b2b_data.get(form, {}).get("netto") if b2b_data.get(form) else None
        if val is None:
            val = b2b_data["ryczalt"]["netto"]
        if best_netto is None or val > best_netto:
            best_netto = val
            best_label = f"B2B {form}"

    if "uop" in results:
        uop_netto = results["uop"]["netto"]
        if best_netto is None or uop_netto > best_netto:
            best_netto = uop_netto
            best_label = "UoP"

    results["bestNetto"] = best_netto
    results["bestLabel"] = best_label

    return results


# =============================================================================
# B2B netto → UoP brutto equivalent (binary search)
# =============================================================================

def find_uop_brutto_for_netto(target_netto):
    """
    What UoP brutto gives the same netto as a given B2B form?
    Uses standard UoP settings (no special deductions).
    Binary search: 50 iterations ≈ 0.01 PLN precision.
    """
    lo = target_netto
    hi = target_netto * 3
    for _ in range(50):
        mid = (lo + hi) / 2
        result = calc_uop(mid)
        if result["netto"] < target_netto:
            lo = mid
        else:
            hi = mid
    brutto = round((lo + hi) / 2)
    uop = calc_uop(brutto)
    return {"brutto": brutto, "netto": uop["netto"]}


# =============================================================================
# Conversions
# =============================================================================

def hourly_to_monthly(hourly):
    return _r2(hourly * WORKING_HOURS_MONTH)


def monthly_to_hourly(monthly):
    return _r2(monthly / WORKING_HOURS_MONTH)


# =============================================================================
# Exported constants dict (mirrors JS TAX_CONSTANTS)
# =============================================================================

TAX_CONSTANTS = {
    "TAX_YEAR": TAX_YEAR,
    "WORKING_DAYS_YEAR": WORKING_DAYS_YEAR,
    "WORKING_DAYS_MONTH": WORKING_DAYS_MONTH,
    "WORKING_HOURS_MONTH": WORKING_HOURS_MONTH,
    "UOP_PAID_VACATION_DAYS": UOP_PAID_VACATION_DAYS,
    "MIN_WAGE": MIN_WAGE,
    "PRACODAWCA_TOTAL": PRACODAWCA_TOTAL,
    "B2B_ZDROWOTNA_MIN": B2B_ZDROWOTNA_MIN,
    "RYCZALT_ZDROWOTNA_BASE": RYCZALT_ZDROWOTNA_BASE,
}
