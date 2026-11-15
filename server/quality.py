"""Product grade 1..5. Grade 3 is neutral: the clearing price is unchanged.

Grade rises with equipment level and a finished quality research, and falls when
the inputs themselves are poor. Legacy buildings have no equipment row and no
research, so they stay at 3 and the old honey/oil/goods prices do not move.
"""
import balance as balance_registry


def score(equipment, input_grade, bonus=0):
    """Integer grade. Equipment 1 and input grade 3 and no bonus → 3."""
    base = 2 + int(equipment) + int(bonus)
    shift = (int(input_grade) - 3) // 2
    return max(1, min(5, base + shift))


def price_factor(grade):
    step = float(balance_registry.get("QUALITY_PRICE_STEP"))
    return 1.0 + (float(grade) - 3.0) * step


def _q(sql, ph):
    return sql.replace("%s", ph)


def owner_grade(db, ph, owner, month):
    import research
    bonus = research.quality_bonus(db, ph, owner, month)
    row = db.execute(_q(
        "SELECT MAX(d.equipment_level) FROM building_dimensions d "
        "JOIN building_ops o ON o.object_id=d.object_id WHERE o.owner=%s", ph), (owner,)).fetchone()
    level = int(row[0]) if row and row[0] is not None else 1
    if bonus == 0 and level <= 1:
        return 3
    return score(level, 3, bonus)


def input_grade(inputs, grades):
    """Quantity-weighted grade of a recipe's inputs. A missing grade is the neutral 3. No inputs → 3."""
    if not inputs:
        return 3
    num = den = 0
    for raw, qty in inputs.items():
        num += int(grades.get(raw, 3)) * int(qty)
        den += int(qty)
    if den <= 0:
        return 3
    return max(1, min(5, int(round(num / float(den)))))


def factor_for(db, ph, produced_map, month, cache, grades=None):
    """Price multiplier for this product. Exactly 1.0 when every seller is grade 3.

    ``grades`` is an optional {owner: grade} already computed from equipment and inputs.
    Owners missing from it fall back to ``owner_grade`` (equipment and research only).
    """
    num = den = 0
    odd = False
    for owner, qty in produced_map.items():
        if qty <= 0:
            continue
        if grades is not None and owner in grades:
            grade = grades[owner]
        else:
            if owner not in cache:
                cache[owner] = owner_grade(db, ph, owner, month)
            grade = cache[owner]
        if grade != 3:
            odd = True
        num += grade * qty
        den += qty
    if not odd or den <= 0:
        return 1.0
    return price_factor(num / den)
