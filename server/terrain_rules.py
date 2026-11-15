"""Chunk-local terrain read for authoritative road planning and manual edits.

Use one bounded query for all chunks crossed by a search box; no per-cell SQL.
This function does not cache across transactions so concurrent editors remain visible.
"""
import roads

CHUNK = 12


def preload(db, ph, box):
    x0,x1,y0,y1 = box
    import terrain_edits
    overrides = {}
    # A single range scan also handles rectangle sizes not aligned to chunks.
    for x,y,kind,manual in db.execute(
        'SELECT x,y,kind,manual FROM terrain_edits WHERE x>='+ph+' AND x<='+ph+' AND y>='+ph+' AND y<='+ph,
        (x0,x1,y0,y1)).fetchall():
        overrides[(int(x),int(y))] = (kind,bool(manual))
    return overrides


def is_water(x,y,overrides=None):
    if overrides is not None:
        item=overrides.get((x,y))
        if item is not None:
            return item[0]=='water' and not roads.is_base_road(x,y)
    return roads.is_water(x,y)


def manual(x,y,overrides):
    return bool(overrides.get((x,y),(None,False))[1])