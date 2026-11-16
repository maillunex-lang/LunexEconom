"""Validate the monetization proposal. Does not read or write server/ or client/."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROPOSAL = Path(__file__).resolve().parent / "sim" / "data" / "monetization_proposed"
CONTENT = ROOT / "docs" / "content" / "monetization.ru.md"
FILES = (
    "privileges",
    "forbidden",
    "alternatives",
    "automation",
    "plans",
    "packages",
    "cosmetics",
    "shop_lines",
)
HARD_BANS = (
    "grant_game_rubles",
    "lootbox_random",
    "market_advantage_exclusive",
    "hidden_autorenew",
)
TIERS = ("start", "entrepreneur", "magnate")
TIER_RANK = {name: index for index, name in enumerate(TIERS)}
VARIANTS = ("A", "B", "C")
MODES = ("manual", "assistant", "automatic")
ROLES = ("coo", "cto", "cmo", "cfo")
KIND_PRIVILEGE = {
    "profile_frame": "cosmetic_frame",
    "company_color": "cosmetic_company_color",
    "ui_theme_token": "cosmetic_ui_theme",
    "badge": "",
}
BADGE_PRIVILEGE = {
    "badge_supporter": "supporter_badge",
    "badge_patron": "patron_badge",
}
PACKAGE_PRIVILEGES = {
    "cosmetic_frame",
    "cosmetic_company_color",
    "cosmetic_ui_theme",
    "supporter_badge",
    "patron_badge",
}
GROWING = (
    "automation_slots_bonus",
    "report_history_days",
    "notification_slots",
    "rule_presets",
)
PRESSURE = ("только сегодня", "успей", "последний шанс", "не упусти")
FLAG_MUST = {
    "accel_enabled": 0,
    "allow_below_cost_default": 0,
    "stop_on_overdue": 1,
    "auto_renew_default": 0,
    "automation_may_take_loans": 0,
    "automation_may_fire": 0,
    "automation_may_issue_shares": 0,
    "automation_may_bid_land": 0,
    "automation_may_acquire": 0,
    "automation_may_sell_below_cost_without_consent": 0,
}


class ProposalError(ValueError):
    pass


def _pairs(pairs):
    item = {}
    for key, value in pairs:
        if key in item:
            raise ProposalError(f"duplicate JSON key {key!r}")
        item[key] = value
    return item


def _reject_float(token):
    raise ProposalError(f"non-integer number {token}")


def _reject_constant(token):
    raise ProposalError(f"non-integer number {token}")


def load_proposal(root=None):
    root = Path(root) if root is not None else PROPOSAL
    data = {}
    for name in FILES:
        path = root / f"{name}.json"
        raw = path.read_text(encoding="utf-8")
        data[name] = json.loads(
            raw,
            object_pairs_hook=_pairs,
            parse_float=_reject_float,
            parse_constant=_reject_constant,
        )
    return data


def _integers(value, path, errors):
    if isinstance(value, bool):
        errors.append(f"{path}: bool is not an integer")
        return
    if isinstance(value, float):
        errors.append(f"{path}: float")
        return
    if isinstance(value, int) or isinstance(value, str) or value is None:
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _integers(item, f"{path}[{index}]", errors)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            _integers(item, f"{path}.{key}", errors)
        return
    errors.append(f"{path}: not an integer ({type(value).__name__})")


def _unique(items, label, errors):
    seen = set()
    for item in items:
        if item in seen:
            errors.append(f"duplicate {label} id {item}")
        seen.add(item)
    return seen


def _grant_map(plan, errors):
    found = {}
    for grant in plan["grants"]:
        privilege = grant["privilege"]
        if privilege in found:
            errors.append(f"{plan['id']}: duplicate grant {privilege}")
        found[privilege] = grant["amount"]
    return found


def _text_pressure(label, text, errors):
    folded = text.casefold()
    for phrase in PRESSURE:
        if phrase in folded:
            errors.append(f"pressure: {label} contains {phrase}")


def shelf_price(competitor, direction, delta_bp, unit_cost, allow_below_cost, basis=10000, delta_max=2000):
    """Integer shelf price. direction 0 match, 1 undercut, 2 premium. Floor division."""
    if type(competitor) is not int or type(delta_bp) is not int or type(unit_cost) is not int:
        raise ProposalError("shelf inputs must be integers")
    if delta_bp < 0 or delta_bp > delta_max or basis < 1:
        raise ProposalError("shelf delta out of range")
    if direction == 0:
        price = competitor
    elif direction == 1:
        price = (competitor * (basis - delta_bp)) // basis
    elif direction == 2:
        price = (competitor * (basis + delta_bp)) // basis
    else:
        raise ProposalError("shelf direction must be 0, 1 or 2")
    if price < 1:
        price = 1
    if allow_below_cost == 0 and price < unit_cost:
        price = unit_cost
    return price


def executive_salary(base, skill, city_index_permille, permille=1000):
    """Module 10 salary: (base * skill * city_index_‰) // 1000."""
    return (base * skill * city_index_permille) // permille


def auto_cap(free_slots, plan_bonus, executives, coverage):
    """Free slots plus the larger of the subscription bonus and hired coverage."""
    covered = executives * coverage
    extra = plan_bonus if plan_bonus > covered else covered
    return free_slots + extra


def validate(data, content_text=None):
    errors = []
    _integers(data, "proposal", errors)
    if content_text is None:
        if CONTENT.is_file():
            content_text = CONTENT.read_text(encoding="utf-8")
        else:
            content_text = ""
            errors.append("missing docs/content/monetization.ru.md")
    if content_text:
        nonempty = [line for line in content_text.splitlines() if line.strip()]
        if len(nonempty) < 40:
            errors.append("monetization.ru.md needs at least 40 non-empty lines")
        if "Внутриигровые рубли ненастоящие" not in content_text:
            errors.append("content missing fake-money warning")

    for name in FILES:
        block = data[name]
        if block.get("balance") != "draft":
            errors.append(f"{name}: balance must be draft")

    allowed = {}
    for row in data["privileges"]["allowed"]:
        if row["id"] in allowed:
            errors.append(f"duplicate privilege id {row['id']}")
        allowed[row["id"]] = row
        if row["competitive"] not in (0, 1):
            errors.append(f"{row['id']}: competitive must be 0 or 1")
        if row["competitive"] == 1 and not row["game_money_alternative"]:
            errors.append(f"{row['id']}: competitive privilege needs a game-money alternative")
        if row["competitive"] == 0 and row["game_money_alternative"]:
            errors.append(f"{row['id']}: non-competitive privilege must not pretend to have an alternative")

    forbidden = {}
    for row in data["forbidden"]["forbidden"]:
        if row["id"] in forbidden:
            errors.append(f"duplicate forbidden id {row['id']}")
        forbidden[row["id"]] = row
        if row["id"] in allowed:
            errors.append(f"{row['id']}: privilege cannot be both allowed and forbidden")
    for ban in HARD_BANS:
        if ban not in forbidden:
            errors.append(f"forbidden list missing hard ban {ban}")

    alternatives = {}
    for row in data["alternatives"]["alternatives"]:
        if row["id"] in alternatives:
            errors.append(f"duplicate alternative id {row['id']}")
        alternatives[row["id"]] = row
        if row["pay_with"] != "game_rub":
            errors.append(f"{row['id']}: alternative must be paid in game rubles")
    for row in allowed.values():
        alt = row["game_money_alternative"]
        if alt and alt not in alternatives:
            errors.append(f"{row['id']}: unknown alternative {alt}")

    auto = data["automation"]
    if auto["recommended_variant"] != "A":
        errors.append("recommended variant must be A")
    if tuple(auto["modes"]) != MODES:
        errors.append("modes must be manual, assistant, automatic")
    if tuple(auto["roles"]) != ROLES:
        errors.append("roles must be coo, cto, cmo, cfo")
    rule_ids = []
    for rule in auto["rules"]:
        rule_ids.append(rule["id"])
        for role in rule["roles"]:
            if role not in ROLES:
                errors.append(f"{rule['id']}: unknown role {role}")
    _unique(rule_ids, "rule", errors)
    for needed in ("buy_min_stock", "shelf_vs_competitor", "restock_shelf", "hire_to_staffing", "work_schedule", "alerts"):
        if needed not in rule_ids:
            errors.append(f"missing automation rule {needed}")
    flags = auto["flags"]
    for key, expected in FLAG_MUST.items():
        if flags.get(key) != expected:
            errors.append(f"flags.{key} must be {expected}")
    limits = auto["limits"]
    for key, value in limits.items():
        if type(value) is not int or value < 1:
            errors.append(f"limits.{key} must be a positive integer")
    if not errors or all(not line.startswith("limits.") for line in errors):
        _limit_relations(limits, alternatives, errors)

    plans_doc = data["plans"]
    if plans_doc["recommended_variant"] != auto["recommended_variant"]:
        errors.append("plans and automation disagree on the recommended variant")
    if plans_doc.get("consent_text_id") != "sub_consent_v1":
        errors.append("consent_text_id must be sub_consent_v1")
    consent = plans_doc["consent_text"]
    if "Автопродление" not in consent or "Внутриигровые рубли ненастоящие" not in consent:
        errors.append("consent text must name auto-renew and fake money")
    _text_pressure("consent", consent, errors)
    _remember(content_text, consent, "consent", errors)
    early = plans_doc["early_adopter"]
    if early["auto_renew"] != 0 or early["stacks_with_trial"] != 0:
        errors.append("early adopter grant must not auto-renew or stack with the trial")
    if early["window_real_days"] != limits["early_window_real_days"]:
        errors.append("early window does not match automation limits")
    if early["grant_real_days"] != limits["early_grant_real_days"]:
        errors.append("early grant length does not match automation limits")

    plans = plans_doc["plans"]
    plan_ids = _unique([plan["id"] for plan in plans], "plan", errors)
    by_variant = {name: {} for name in VARIANTS}
    for plan in plans:
        pid = plan["id"]
        if plan["variant"] not in VARIANTS:
            errors.append(f"{pid}: unknown variant")
            continue
        if plan["tier"] not in TIER_RANK:
            errors.append(f"{pid}: unknown tier")
        if plan["variant"] == "C" and plan["sellable"] != 0:
            errors.append(f"{pid}: variant C must not be sellable")
        if plan["variant"] == "B" and plan["sellable"] != 0:
            errors.append(f"{pid}: variant B stays unsellable while A is recommended")
        if plan["variant"] == "A" and plan["sellable"] != 1:
            errors.append(f"{pid}: variant A plan must be sellable")
        if plan["sellable"] not in (0, 1):
            errors.append(f"{pid}: sellable must be 0 or 1")
        _price(plan, errors)
        if plan["duration_real_days"] != limits["subscription_real_days"]:
            errors.append(f"{pid}: duration must be {limits['subscription_real_days']} real days")
        if plan["auto_renew_default"] != 0:
            errors.append(f"{pid}: auto-renew default must be 0")
        if plan["trial_real_days"] < 0:
            errors.append(f"{pid}: trial days cannot be negative")
        if not plan["description"].strip():
            errors.append(f"{pid}: missing description")
        else:
            _text_pressure(pid, plan["description"], errors)
            _remember(content_text, plan["description"], pid, errors)
        if not plan["cancel_text"].strip():
            errors.append(f"{pid}: missing cancel text")
        else:
            _text_pressure(pid, plan["cancel_text"], errors)
            _remember(content_text, plan["cancel_text"], pid, errors)
        grants = _grant_map(plan, errors)
        if set(plan["privileges"]) != set(grants):
            errors.append(f"{pid}: privileges and grants differ")
        for privilege, amount in grants.items():
            if privilege in forbidden:
                errors.append(f"{pid}: forbidden privilege {privilege}")
            elif privilege not in allowed:
                errors.append(f"{pid}: unknown privilege {privilege}")
            if type(amount) is not int or amount < 1:
                errors.append(f"{pid}: grant {privilege} must be a positive integer")
        if "construction_accel_token" in grants and plan["sellable"] == 1:
            errors.append(f"{pid}: sellable plan cannot include a construction token while accel is off")
        if "construction_accel_token" in grants and grants["construction_accel_token"] != limits["accel_per_real_day"]:
            errors.append(f"{pid}: accel token amount must equal the shared daily cap")
        bonus = grants.get("automation_slots_bonus")
        if bonus is not None and limits["executive_coverage_enterprises"] > 0:
            if bonus % limits["executive_coverage_enterprises"] != 0:
                errors.append(f"{pid}: slot bonus must match whole executives")
        if plan["variant"] == "C":
            if plan["privileges"] or plan["grants"]:
                errors.append(f"{pid}: variant C grants nothing")
            if not plan["illustrative_forbidden"]:
                errors.append(f"{pid}: variant C must list the privileges it refuses")
        elif plan["illustrative_forbidden"]:
            errors.append(f"{pid}: only variant C lists illustrative forbidden privileges")
        for privilege in plan["illustrative_forbidden"]:
            if privilege not in forbidden:
                errors.append(f"{pid}: illustrative privilege {privilege} is not forbidden")
        by_variant[plan["variant"]][plan["tier"]] = plan

    for variant in VARIANTS:
        for tier in TIERS:
            if tier not in by_variant[variant]:
                errors.append(f"missing plan {variant} {tier}")
    _compare_tiers(by_variant, limits, errors)
    if early["grant_plan_id"] not in plan_ids:
        errors.append("early adopter plan is missing")
    elif data["plans"]["plans"]:
        granted = next(plan for plan in plans if plan["id"] == early["grant_plan_id"])
        if granted["sellable"] != 1:
            errors.append("early adopter plan must be a sellable plan")

    trials = [plan for plan in plans if plan["sellable"] == 1 and plan["trial_real_days"] > 0]
    if len(trials) != 1 or trials[0]["id"] != "a_entrepreneur":
        errors.append("the only sellable trial is a_entrepreneur")
    elif trials[0]["trial_real_days"] != limits["trial_real_days_once"]:
        errors.append("trial length must match the once-only limit")

    packages = {}
    for pack in data["packages"]["packages"]:
        if pack["id"] in packages:
            errors.append(f"duplicate package id {pack['id']}")
        packages[pack["id"]] = pack
        _price(pack, errors)
        if pack["price_rub"] < 1:
            errors.append(f"{pack['id']}: package price must be positive")
        if not pack["description"].strip():
            errors.append(f"{pack['id']}: missing description")
        else:
            _text_pressure(pack["id"], pack["description"], errors)
            _remember(content_text, pack["description"], pack["id"], errors)
        _remember(content_text, pack["name"], pack["id"], errors)
        for privilege in pack["privileges"]:
            if privilege in forbidden:
                errors.append(f"{pack['id']}: forbidden privilege {privilege}")
            elif privilege not in PACKAGE_PRIVILEGES:
                errors.append(f"{pack['id']}: package privilege {privilege} is not cosmetic")
            elif privilege not in allowed:
                errors.append(f"{pack['id']}: unknown privilege {privilege}")
        _unique(pack["cosmetic_ids"], f"{pack['id']} cosmetic", errors)

    cosmetics = {}
    catalog = data["cosmetics"]
    if catalog["pack_kind"] != "ui_theme" or catalog["pack_name"] != "ui_theme":
        errors.append("cosmetics must reference the signed ui_theme pack")
    for row in catalog["cosmetics"]:
        if row["id"] in cosmetics:
            errors.append(f"duplicate cosmetic id {row['id']}")
        cosmetics[row["id"]] = row
        if row["asset_id"] != row["id"]:
            errors.append(f"{row['id']}: asset_id must match id")
        if row["kind"] not in KIND_PRIVILEGE:
            errors.append(f"{row['id']}: unknown cosmetic kind")
        if row["permanent"] not in (0, 1):
            errors.append(f"{row['id']}: permanent must be 0 or 1")
        if row["source"] == "package":
            if row["permanent"] != 1:
                errors.append(f"{row['id']}: donation cosmetics stay after a subscription ends")
            if row["source_id"] not in packages:
                errors.append(f"{row['id']}: unknown package {row['source_id']}")
            elif row["id"] not in packages[row["source_id"]]["cosmetic_ids"]:
                errors.append(f"{row['id']}: source package does not list it")
        elif row["source"] == "plan":
            if row["permanent"] != 0:
                errors.append(f"{row['id']}: subscription cosmetics are not permanent")
            if row["tier"] not in TIER_RANK:
                errors.append(f"{row['id']}: unknown tier")
            source = next((plan for plan in plans if plan["id"] == row["source_id"]), None)
            if source is None or source["variant"] != "A":
                errors.append(f"{row['id']}: cosmetic must point at a variant A plan")
        else:
            errors.append(f"{row['id']}: unknown source")
        privilege = BADGE_PRIVILEGE.get(row["id"], KIND_PRIVILEGE.get(row["kind"], ""))
        if row["kind"] == "badge" and row["id"] not in BADGE_PRIVILEGE:
            errors.append(f"{row['id']}: badge needs a privilege mapping")
        if privilege and row["source"] == "package" and row["source_id"] in packages:
            if privilege not in packages[row["source_id"]]["privileges"]:
                errors.append(f"{row['id']}: package missing privilege {privilege}")
        if privilege and row["source"] == "plan":
            source = next((plan for plan in plans if plan["id"] == row["source_id"]), None)
            if source is not None and privilege not in source["privileges"]:
                errors.append(f"{row['id']}: plan missing privilege {privilege}")

    for pack in packages.values():
        for cosmetic_id in pack["cosmetic_ids"]:
            row = cosmetics.get(cosmetic_id)
            if row is None:
                errors.append(f"{pack['id']}: unknown cosmetic {cosmetic_id}")
                continue
            privilege = BADGE_PRIVILEGE.get(row["id"], KIND_PRIVILEGE.get(row["kind"], ""))
            if privilege and privilege not in pack["privileges"]:
                errors.append(f"{pack['id']}: lists {cosmetic_id} without {privilege}")

    for plan in plans:
        if plan["sellable"] != 1:
            continue
        rank = TIER_RANK[plan["tier"]]
        for privilege, kind in (
            ("cosmetic_frame", "profile_frame"),
            ("cosmetic_company_color", "company_color"),
            ("cosmetic_ui_theme", "ui_theme_token"),
        ):
            if privilege not in plan["privileges"]:
                continue
            found = False
            for row in cosmetics.values():
                if row["kind"] != kind or row["source"] != "plan":
                    continue
                if TIER_RANK[row["tier"]] <= rank:
                    found = True
            if not found:
                errors.append(f"{plan['id']}: no cosmetic for {privilege}")

    shop = data["shop_lines"]
    if shop["screen_max"] != 90 or shop["detail_max"] != 140:
        errors.append("shop limits must stay 90 and 140")
    line_ids = []
    if len(shop["lines"]) < 12:
        errors.append("shop needs at least 12 lines")
    for line in shop["lines"]:
        line_ids.append(line["id"])
        screen = line["screen"]
        detail = line["detail"]
        if not screen.strip() or not detail.strip():
            errors.append(f"{line['id']}: empty shop line")
        if len(screen) > shop["screen_max"] or len(detail) > shop["detail_max"]:
            errors.append(f"{line['id']}: shop line is too long")
        _text_pressure(line["id"], screen + " " + detail, errors)
        _remember(content_text, screen, line["id"], errors)
        _remember(content_text, detail, line["id"], errors)
    _unique(line_ids, "shop line", errors)
    return errors


def _limit_relations(limits, alternatives, errors):
    if not limits["spend_cap_game_day_min"] <= limits["spend_cap_game_day_default"] <= limits["spend_cap_game_day_max"]:
        errors.append("spend cap default must sit between min and max")
    if limits["target_stock_units_default"] < limits["min_stock_units_default"]:
        errors.append("target stock must be at least the minimum stock")
    if limits["staffing_permille_default"] > limits["staffing_permille_max"]:
        errors.append("default staffing exceeds the max")
    if limits["staffing_permille_max"] != limits["permille_basis"]:
        errors.append("full staffing is 1000 permille")
    if limits["shelf_delta_bp_max"] > limits["price_basis_bp"]:
        errors.append("shelf delta cannot exceed the price basis")
    if limits["shelf_delta_bp_max"] != 2000 or limits["price_basis_bp"] != 10000:
        errors.append("shelf band is 2000 bp on a 10000 basis")
    if limits["accel_per_real_day"] != 1 or limits["accel_stage_days_cut"] != 1:
        errors.append("construction accel is one game day, once per real day")
    if limits["accel_min_days_left"] != 1:
        errors.append("a stage cannot be finished by an accelerator")
    if limits["subscription_real_days"] != 30:
        errors.append("subscription length is 30 real days")
    if limits["trial_real_days_once"] > limits["subscription_real_days"]:
        errors.append("trial cannot outlast the paid period")
    if limits["early_grant_real_days"] > limits["subscription_real_days"]:
        errors.append("early grant cannot outlast the paid period")
    if limits["day_boundary_hour_ufa"] != 9 or limits["tz_offset_minutes"] != 300:
        errors.append("real-day boundary is 09:00 in Ufa")
    span = limits["support_max_rub"] - limits["support_min_rub"]
    if span < 1 or span % limits["support_step_rub"] != 0:
        errors.append("support slider must land on its step")
    if not limits["support_min_rub"] <= limits["badge_min_rub"] <= limits["support_max_rub"]:
        errors.append("badge threshold must sit inside the support slider")
    if limits["executive_skill_min"] >= limits["executive_skill_max"]:
        errors.append("skill range is empty")
    hire = alternatives.get("hire_executive_coverage")
    accel = alternatives.get("buy_accel_game_rub")
    if hire is None or accel is None:
        errors.append("both game-money alternatives are required")
        return
    if hire["coverage_enterprises"] != limits["executive_coverage_enterprises"]:
        errors.append("executive coverage does not match the alternative")
    if hire["salary_base_game_rub"] != limits["executive_salary_base_game_rub"]:
        errors.append("executive salary base does not match the alternative")
    if accel["price_game_rub"] != limits["accel_price_game_rub"]:
        errors.append("accel price does not match the alternative")
    if accel["per_real_day"] != limits["accel_per_real_day"]:
        errors.append("accel cap does not match the alternative")


def _price(row, errors):
    price = row["price_rub"]
    low = row["price_rub_min"]
    high = row["price_rub_max"]
    ident = row["id"]
    if type(price) is not int or type(low) is not int or type(high) is not int:
        errors.append(f"{ident}: prices must be integers")
        return
    if price < 0 or low < 0 or high < 0:
        errors.append(f"{ident}: prices cannot be negative")
    if not low <= price <= high:
        errors.append(f"{ident}: price must sit between min and max")


def _compare_tiers(by_variant, limits, errors):
    free_bars = {
        "report_history_days": limits["report_history_days_free"],
        "notification_slots": limits["notification_slots_free"],
        "rule_presets": limits["rule_presets_free"],
    }
    previous = None
    for tier in TIERS:
        plan = by_variant["A"].get(tier)
        twin = by_variant["B"].get(tier)
        if plan is None or twin is None:
            continue
        grants = {item["privilege"]: item["amount"] for item in plan["grants"]}
        twin_grants = {item["privilege"]: item["amount"] for item in twin["grants"]}
        for privilege in GROWING:
            if privilege not in grants:
                errors.append(f"{plan['id']}: missing {privilege}")
                continue
            if twin_grants.get(privilege) != grants[privilege]:
                errors.append(f"{twin['id']}: {privilege} must match variant A")
            if privilege in free_bars and grants[privilege] <= free_bars[privilege]:
                errors.append(f"{plan['id']}: {privilege} must exceed the free baseline")
        if previous is not None:
            for privilege in GROWING:
                if privilege in grants and privilege in previous and grants[privilege] <= previous[privilege]:
                    errors.append(f"{plan['id']}: {privilege} must grow by tier")
        previous = grants
        if "construction_accel_token" in grants:
            errors.append(f"{plan['id']}: variant A has no accelerator")
        if twin_grants.get("construction_accel_token") != 1:
            errors.append(f"{twin['id']}: variant B includes exactly one accel token")


def _remember(content_text, snippet, label, errors):
    if content_text and snippet not in content_text:
        errors.append(f"{label}: text missing from monetization.ru.md")


def main(argv=None):
    try:
        data = load_proposal()
    except (OSError, ProposalError, ValueError, KeyError, TypeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    errors = validate(data)
    if errors:
        print(f"ERROR: {len(errors)} monetization problem(s)", file=sys.stderr)
        for line in errors:
            print(f"ERROR: {line}", file=sys.stderr)
        return 1
    sellable = sum(1 for plan in data["plans"]["plans"] if plan["sellable"] == 1)
    print(f"plans: {len(data['plans']['plans'])}")
    print(f"sellable: {sellable}")
    print(f"packages: {len(data['packages']['packages'])}")
    print(f"cosmetics: {len(data['cosmetics']['cosmetics'])}")
    print(f"shop lines: {len(data['shop_lines']['lines'])}")
    print(f"forbidden: {len(data['forbidden']['forbidden'])}")
    print("recommended: A")
    print("OK monetization proposal (balance: draft)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
