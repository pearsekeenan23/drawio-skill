#!/usr/bin/env python3
"""Draw a conceptual ER model (JSON) as an editable .drawio diagram,
in Chen notation or crow's foot notation.

The JSON *is* the ER model: entities, attributes, relationships, and for every
end of every relationship its cardinality and participation. The same file can
be drawn in either notation (like drawing one model twice in a lab).

  python3 erdgen.py model.json -o model.drawio                 # Chen (default)
  python3 erdgen.py model.json -o model-cf.drawio --notation crowsfoot
  python3 erdgen.py model.json --check                         # checks only
  python3 erdgen.py model.json -o model.drawio --url           # + diagrams.net link

Model format (see references/er-chen-crowsfoot.md for the full description):

  {
    "title": "Olympic Games",
    "entities": [
      {"name": "COUNTRY", "attributes": [
         {"name": "country_code", "key": true},
         {"name": "country_name"},
         {"name": "phone_numbers", "multivalued": true},
         {"name": "age", "derived": true},
         {"name": "address", "parts": ["street", "town"]}]},
      {"name": "NEXT_OF_KIN", "weak": true, "attributes": [
         {"name": "kin_name", "partial_key": true}]}
    ],
    "relationships": [
      {"name": "Sends",
       "ends": [
         {"entity": "COUNTRY",    "card": "1", "participation": "full"},
         {"entity": "COMPETITOR", "card": "N", "participation": "full"}],
       "attributes": []}
    ]
  }

How to read an end: {"entity": "COMPETITOR", "card": "N"} puts "N" beside
COMPETITOR, i.e. one COUNTRY relates to N competitors. "participation" says
whether EVERY occurrence of that end's entity must take part (full) or not
(partial).

Layout: entities on a grid (related ones side by side), diamonds between them,
attributes fanned out away from the lines. Pin an entity with "at": [col, row]. Every
check finding has a stable code (E-..., W-...) and a fix hint, like validate.py.
"""
import argparse
import json
import os
import sys
from xml.sax.saxutils import escape

CARDS = {"1", "N", "M"}
PARTS = {"full", "partial"}

# ---------------------------------------------------------------- styles ----
# Chen shapes follow draw.io's built-in "Entity Relation" library, so the
# result stays editable with the same shapes students use in the labs.
S_ENTITY = "rounded=0;whiteSpace=wrap;html=1;fillColor=#ffffff;strokeColor=#000000;"
S_WEAK = "shape=ext;margin=3;double=1;whiteSpace=wrap;html=1;fillColor=#ffffff;strokeColor=#000000;"
S_REL = "shape=rhombus;perimeter=rhombusPerimeter;whiteSpace=wrap;html=1;fillColor=#ffffff;strokeColor=#000000;"
S_IDREL = "shape=rhombus;double=1;perimeter=rhombusPerimeter;whiteSpace=wrap;html=1;fillColor=#ffffff;strokeColor=#000000;"
S_ATTR = "ellipse;whiteSpace=wrap;html=1;fillColor=#ffffff;strokeColor=#000000;"
S_KEY = S_ATTR + "fontStyle=4;"                       # underlined
S_MULTI = "ellipse;shape=doubleEllipse;margin=3;whiteSpace=wrap;html=1;fillColor=#ffffff;strokeColor=#000000;"
S_DERIVED = S_ATTR + "dashed=1;"
S_LINE = "endArrow=none;html=1;rounded=0;strokeColor=#000000;"
S_FULL = "shape=link;html=1;rounded=0;strokeColor=#000000;"   # double line
S_CARD_LABEL = "edgeLabel;html=1;align=center;verticalAlign=middle;resizable=0;points=[];labelBackgroundColor=none;"

# crow's foot
S_CF_TABLE = ("swimlane;fontStyle=0;childLayout=stackLayout;horizontal=1;startSize=28;"
              "horizontalStack=0;resizeParent=1;resizeParentMax=0;resizeLast=0;collapsible=0;"
              "marginBottom=0;html=1;fillColor=#ffffff;strokeColor=#000000;")
S_CF_ROW = ("text;strokeColor=none;fillColor=none;align=left;verticalAlign=middle;spacingLeft=6;"
            "spacingRight=4;overflow=hidden;rotatable=0;points=[[0,0.5],[1,0.5]];"
            "portConstraint=eastwest;html=1;")
CF_END = {  # (min, max) -> draw.io ER arrow
    (1, "one"): "ERmandOne", (0, "one"): "ERzeroToOne",
    (1, "many"): "ERoneToMany", (0, "many"): "ERzeroToMany",
}

# ------------------------------------------------------------------ check ----


class Finding:
    def __init__(self, sev, code, subject, msg, fix):
        self.sev, self.code, self.subject, self.msg, self.fix = sev, code, subject, msg, fix

    def __str__(self):
        return f"{self.sev}: [{self.code}] {self.subject}: {self.msg} (fix: {self.fix})"


def check(model):
    """Structural checks on the model. Says what is MISSING or inconsistent,
    never whether a design choice is right for the scenario."""
    out = []
    E = lambda *a: out.append(Finding("error", *a))
    W = lambda *a: out.append(Finding("warning", *a))
    ents = model.get("entities", [])
    rels = model.get("relationships", [])
    names = [e.get("name", "") for e in ents]
    for n in set(names):
        if names.count(n) > 1:
            E("E-DUP-ENTITY", n, "entity name used more than once", "give each entity a unique name")
    used = set()
    for e in ents:
        n = e.get("name") or "?"
        attrs = e.get("attributes", [])
        if not e.get("name"):
            E("E-NO-NAME", "entity", "entity without a name", "add \"name\"")
        if e.get("weak"):
            if not any(a.get("partial_key") for a in attrs):
                W("W-WEAK-NO-PARTIAL-KEY", n, "weak entity has no partial key", "mark the attribute that identifies it within its owner with \"partial_key\": true")
        elif attrs and not any(a.get("key") for a in attrs):
            E("E-NO-KEY", n, "entity has no identifier", "mark its identifying attribute with \"key\": true")
        if not attrs:
            W("W-NO-ATTRS", n, "no attributes listed yet", "list its attributes, including its key")
        elif len(attrs) == 1:
            W("W-ONE-ATTR", n, "entity has only one attribute", "check it is really an entity, not an attribute of something else")
        for a in attrs:
            if a.get("key") and (a.get("multivalued") or a.get("derived")):
                E("E-BAD-KEY", f"{n}.{a.get('name')}", "an identifier cannot be multi-valued or derived", "choose a single, stored attribute as the key")
    for r in rels:
        rn = r.get("name") or "?"
        ends = r.get("ends", [])
        if len(ends) < 2:
            E("E-ENDS", rn, "relationship needs at least two ends", "add an \"ends\" entry for each entity it links")
        for i, end in enumerate(ends):
            ref = end.get("entity")
            used.add(ref)
            subj = f"{rn} end {i + 1} ({ref})"
            if ref not in names:
                E("E-UNKNOWN-ENTITY", subj, f"'{ref}' is not a declared entity", "fix the spelling or add the entity")
            if str(end.get("card", "")).upper() not in CARDS:
                E("E-NO-CARD", subj, "cardinality missing or not 1 / N / M", "set \"card\" to \"1\", \"N\" or \"M\" (ask the question both ways)")
            if end.get("participation") not in PARTS:
                E("E-NO-PARTICIPATION", subj, "participation missing or not full / partial", "set \"participation\" to \"full\" or \"partial\" (must EVERY one take part?)")
        cards = [str(x.get("card", "")).upper() for x in ends]
        many = sum(c in ("N", "M") for c in cards)
        if r.get("attributes") and len(ends) == 2 and many < 2:
            W("W-REL-ATTR-1N", rn, "attributes on a 1:1 / 1:N relationship", "usually these belong on the N-side entity; keep them here only if they describe the pairing")
        if r.get("identifying"):
            weak_ends = [x for x in ends if any(e.get("name") == x.get("entity") and e.get("weak") for e in ents)]
            if not weak_ends:
                E("E-ID-NO-WEAK", rn, "identifying relationship links no weak entity", "mark the dependent entity \"weak\": true or drop \"identifying\"")
            for x in weak_ends:
                if x.get("participation") != "full":
                    E("E-WEAK-PARTIAL", rn, f"weak entity {x.get('entity')} must take part fully", "set its participation to \"full\"")
    for e in ents:
        if e.get("weak") and not any(r.get("identifying") and any(x.get("entity") == e.get("name") for x in r.get("ends", [])) for r in rels):
            E("E-WEAK-NO-OWNER", e.get("name"), "weak entity has no identifying relationship", "add \"identifying\": true to the relationship with its owner")
    for n in names:
        if n not in used:
            W("W-ISOLATED", n, "entity takes part in no relationship", "connect it, or check it belongs in the model")
    return out

# ----------------------------------------------------------------- layout ----
# Lecture-style layout, no external tools needed:
#   1. entities go on a grid; a small search picks the cells so related
#      entities are neighbours (short, straight lines, no crossings);
#   2. each relationship diamond sits halfway between its entities;
#   3. attributes fan out around their entity, in the gaps AWAY from its
#      relationship lines, and are nudged outwards if they would overlap.
# Pin an entity yourself with "at": [column, row] (0-based).


def _segments_cross(p1, p2, p3, p4):
    def orient(a, b, c):
        v = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
        return (v > 0) - (v < 0)
    if len({p1, p2, p3, p4}) < 4:      # sharing an entity is not a crossing
        return False
    return orient(p1, p2, p3) != orient(p1, p2, p4) and orient(p3, p4, p1) != orient(p3, p4, p2)


def _layout_cost(cells, pairs):
    occupied = set(cells.values())
    cost = 0.0
    segs = []
    for a, b in pairs:
        (c1, r1), (c2, r2) = cells[a], cells[b]
        dx, dy = abs(c1 - c2), abs(r1 - r2)
        if dx + dy == 1:
            cost += 1
        elif dx == 0 or dy == 0:   # straight but long: does it pass through an entity?
            cost += 3 * (dx + dy)
            steps = dx + dy
            for s in range(1, steps):
                cell = (c1 + (c2 - c1) * s // steps, r1 + (r2 - r1) * s // steps)
                if cell in occupied:
                    cost += 25
        else:                      # diagonal
            cost += 4 * max(dx, dy) + 2 * min(dx, dy)
        segs.append((cells[a], cells[b]))
    for i in range(len(segs)):
        for j in range(i + 1, len(segs)):
            if _segments_cross(*segs[i], *segs[j]):
                cost += 30
    # keep it compact and stable: prefer cells near the top-left
    cost += 0.01 * sum(c + r for c, r in cells.values())
    return cost


def grid_layout(entities, relationships, seed=7):
    """Return {entity_name: (col, row)}."""
    import math
    import random
    names = [e["name"] for e in entities]
    pinned = {e["name"]: tuple(e["at"]) for e in entities if e.get("at")}
    pairs = []
    for r in relationships:
        ends = [x["entity"] for x in r.get("ends", []) if x.get("entity") in names]
        for i in range(len(ends) - 1):
            if ends[i] != ends[i + 1]:
                pairs.append((ends[i], ends[i + 1]))
    n = len(names)
    best, best_cost = None, float("inf")
    base = max(1, math.ceil(math.sqrt(n)))
    shapes = {(base, math.ceil(n / base)), (base + 1, math.ceil(n / (base + 1))), (base, math.ceil(n / base) + 1)}
    for pc, pr in pinned.values():
        shapes = {(max(c, pc + 1), max(r, pr + 1)) for c, r in shapes}
    rng = random.Random(seed)
    for cols, rows in sorted(shapes):
        all_cells = [(c, r) for r in range(rows) for c in range(cols)]
        free = [c for c in all_cells if c not in pinned.values()]
        movable = [x for x in names if x not in pinned]
        if len(free) < len(movable):
            continue
        for _ in range(60):                       # random restarts
            rng.shuffle(free)
            cells = dict(pinned)
            cells.update(zip(movable, free))
            spare = free[len(movable):]
            cost = _layout_cost(cells, pairs)
            improved = True
            while improved:                       # hill-climb: swap / move
                improved = False
                for a in movable:
                    for b in [x for x in movable if x != a] + list(spare):
                        old_cells, old_spare = dict(cells), list(spare)
                        if isinstance(b, tuple):          # move a into an empty cell
                            spare[spare.index(b)] = cells[a]
                            cells[a] = b
                        else:                             # swap two entities
                            cells[a], cells[b] = cells[b], cells[a]
                        c2 = _layout_cost(cells, pairs)
                        if c2 + 1e-9 < cost:
                            cost, improved = c2, True
                        else:
                            cells, spare = old_cells, old_spare
            if cost < best_cost:
                best, best_cost = dict(cells), cost
    # drop empty rows/columns so the grid is tight
    used_c = sorted({c for c, r in best.values()})
    used_r = sorted({r for c, r in best.values()})
    return {k: (used_c.index(c), used_r.index(r)) for k, (c, r) in best.items()}


def _spread_angles(blocked, k, clearance=38.0):
    """k angles (degrees, screen coords: 0 = right, 90 = down) spread over the
    free gaps between the blocked directions."""
    if k == 0:
        return []
    if not blocked:
        return [(-90 + i * 360.0 / k) % 360 for i in range(k)]
    bl = sorted(b % 360 for b in blocked)
    gaps = []
    for i, b in enumerate(bl):
        nxt = bl[(i + 1) % len(bl)] + (360 if i + 1 == len(bl) else 0)
        start, end = b + clearance, nxt - clearance
        if end - start > 1:
            gaps.append((start, end))
    if not gaps:  # crowded: just avoid the exact directions
        gaps = [(b + 10, bl[(i + 1) % len(bl)] + (360 if i + 1 == len(bl) else 0) - 10) for i, b in enumerate(bl)]
    total = sum(e - s for s, e in gaps)
    counts = [int(k * (e - s) / total) for s, e in gaps]
    rema = sorted(range(len(gaps)), key=lambda i: -(k * (gaps[i][1] - gaps[i][0]) / total - counts[i]))
    for i in rema[: k - sum(counts)]:
        counts[i] += 1
    out = []
    for (s, e), c in zip(gaps, counts):
        out += [(s + (e - s) * (j + 0.5) / c) % 360 for j in range(c)]
    return out


class Placer:
    """Keeps every placed box; nudges new attribute ellipses outwards until
    they no longer overlap anything already placed."""

    def __init__(self):
        self.boxes = []   # (cx, cy, w, h)

    def add(self, cx, cy, w, h):
        self.boxes.append((cx, cy, w, h))

    def hits(self, cx, cy, w, h, pad=8):
        return any(abs(cx - x) < (w + bw) / 2 + pad and abs(cy - y) < (h + bh) / 2 + pad
                   for x, y, bw, bh in self.boxes)

    def place_around(self, ox, oy, angle, rx, ry, w, h):
        import math
        a = math.radians(angle)
        for step in range(40):
            grow = 1 + step * 0.08
            cx, cy = ox + math.cos(a) * rx * grow, oy + math.sin(a) * ry * grow
            if not self.hits(cx, cy, w, h):
                break
        self.add(cx, cy, w, h)
        return cx, cy

# ----------------------------------------------------------------- render ----


class Doc:
    def __init__(self):
        self.cells, self.n = [], 1

    def nid(self, prefix):
        self.n += 1
        return f"{prefix}{self.n}"

    def vertex(self, cid, value, style, x, y, w, h, parent="1"):
        self.cells.append(
            f'<mxCell id="{cid}" value="{escape(value, {chr(34): "&quot;"})}" style="{style}" vertex="1" parent="{parent}">'
            f'<mxGeometry x="{x:.0f}" y="{y:.0f}" width="{w:.0f}" height="{h:.0f}" as="geometry"/></mxCell>')

    def edge(self, cid, src, tgt, style, value=""):
        self.cells.append(
            f'<mxCell id="{cid}" value="{escape(value)}" style="{style}" edge="1" parent="1" source="{src}" target="{tgt}">'
            f'<mxGeometry relative="1" as="geometry"/></mxCell>')

    def edge_label(self, edge_id, text, at, dx=0, dy=0):
        cid = self.nid("lbl")
        self.cells.append(
            f'<mxCell id="{cid}" value="{escape(text)}" style="{S_CARD_LABEL}" vertex="1" connectable="0" parent="{edge_id}">'
            f'<mxGeometry x="{at}" relative="1" as="geometry"><mxPoint x="{dx:.0f}" y="{dy:.0f}" as="offset"/></mxGeometry></mxCell>')

    def xml(self, name):
        body = "".join(self.cells)
        return ('<mxfile host="erdgen"><diagram id="erd" name="' + escape(name) + '">'
                '<mxGraphModel dx="1200" dy="800" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" '
                'arrows="1" fold="1" page="1" pageScale="1" pageWidth="1169" pageHeight="827" math="0" shadow="0">'
                '<root><mxCell id="0"/><mxCell id="1" parent="0"/>' + body + '</root></mxGraphModel></diagram></mxfile>\n')


def _attr_style(a):
    if a.get("multivalued"):
        return S_MULTI
    if a.get("derived"):
        return S_DERIVED
    if a.get("key"):
        return S_KEY
    return S_ATTR


def _attr_label(a):
    if a.get("partial_key"):  # dashed underline = partial key of a weak entity
        return f'<span style="border-bottom:1px dashed;">{escape(a["name"])}</span>'
    return a["name"]


def _ew(text, minimum, per_char=7.2, pad=26):
    return max(minimum, len(text) * per_char + pad)


def _angle(x1, y1, x2, y2):
    import math
    return math.degrees(math.atan2(y2 - y1, x2 - x1)) % 360


def _rel_centres(rels, centre):
    """Diamond centre for each relationship: midpoint of its entities, spread
    apart when two relationships join the same pair."""
    import math
    out, seen = {}, {}
    for ri, r in enumerate(rels):
        pts = [centre[x["entity"]] for x in r["ends"]]
        cx = sum(p[0] for p in pts) / len(pts)
        cy = sum(p[1] for p in pts) / len(pts)
        key = tuple(sorted(x["entity"] for x in r["ends"]))
        k = seen.get(key, 0)
        seen[key] = k + 1
        if k and len(pts) >= 2:
            (x1, y1), (x2, y2) = pts[0], pts[1]
            d = math.hypot(x2 - x1, y2 - y1) or 1
            off = 80 * ((k + 1) // 2) * (1 if k % 2 else -1)
            cx += -(y2 - y1) / d * off
            cy += (x2 - x1) / d * off
        out[ri] = (cx, cy)
    return out


def render_chen(model):
    d = Doc()
    ents = model["entities"]
    rels = model.get("relationships", [])
    cells = grid_layout(ents, rels)
    CW, CH = 470, 380
    centre = {n: (c * CW, r * CH) for n, (c, r) in cells.items()}
    rcent = _rel_centres(rels, centre)
    pl = Placer()
    shapes = []   # (key, value, style, cx, cy, w, h)
    ids = {}

    esize = {e["name"]: (_ew(e["name"], 120, 8.5), 50) for e in ents}
    for e in ents:
        cx, cy = centre[e["name"]]
        w, h = esize[e["name"]]
        pl.add(cx, cy, w, h)
        shapes.append(("E:" + e["name"], e["name"], S_WEAK if e.get("weak") else S_ENTITY, cx, cy, w, h))
    for ri, r in enumerate(rels):
        cx, cy = rcent[ri]
        w, h = max(110, len(r["name"]) * 8 + 50), 64
        pl.add(cx, cy, w, h)
        shapes.append((f"R:{ri}", r["name"], S_IDREL if r.get("identifying") else S_REL, cx, cy, w, h))
    # directions each entity's relationship lines leave in
    lines_from = {e["name"]: [] for e in ents}
    for ri, r in enumerate(rels):
        for x in r["ends"]:
            ex, ey = centre[x["entity"]]
            lines_from[x["entity"]].append(_angle(ex, ey, *rcent[ri]))
    attr_links = []
    for e in ents:
        ex, ey = centre[e["name"]]
        attrs = e.get("attributes", [])
        k = len(attrs)
        rx, ry = max(150, 22 * k), max(92, 15 * k)
        for i, (a, ang) in enumerate(zip(attrs, _spread_angles(lines_from[e["name"]], k))):
            w, h = _ew(a["name"], 90), 36
            ax, ay = pl.place_around(ex, ey, ang, rx, ry, w, h)
            ak = f"A:{e['name']}:{i}"
            shapes.append((ak, _attr_label(a), _attr_style(a), ax, ay, w, h))
            attr_links.append(("E:" + e["name"], ak))
            parts = a.get("parts", [])
            for j, p in enumerate(parts):
                pang = ang + (j - (len(parts) - 1) / 2) * 32
                pw = _ew(p, 80)
                px, py = pl.place_around(ax, ay, pang, 120, 70, pw, 32)
                pk = f"{ak}:{j}"
                shapes.append((pk, p, S_ATTR, px, py, pw, 32))
                attr_links.append((ak, pk))
    for ri, r in enumerate(rels):
        rx0, ry0 = rcent[ri]
        blocked = [_angle(rx0, ry0, *centre[x["entity"]]) for x in r["ends"]]
        attrs = r.get("attributes", [])
        for i, (a, ang) in enumerate(zip(attrs, _spread_angles(blocked, len(attrs), 45))):
            w, h = _ew(a["name"], 90), 36
            ax, ay = pl.place_around(rx0, ry0, ang, 125, 80, w, h)
            ak = f"RA:{ri}:{i}"
            shapes.append((ak, _attr_label(a), _attr_style(a), ax, ay, w, h))
            attr_links.append((f"R:{ri}", ak))

    minx = min(cx - w / 2 for _, _, _, cx, cy, w, h in shapes)
    miny = min(cy - h / 2 for _, _, _, cx, cy, w, h in shapes)
    ox, oy = 40 - minx, 40 - miny
    for key, value, style, cx, cy, w, h in shapes:
        prefix = {"E": "ent", "R": "rel"}.get(key.split(":")[0], "att")
        ids[key] = d.nid(prefix)
        d.vertex(ids[key], value, style, cx - w / 2 + ox, cy - h / 2 + oy, w, h)
    for a, b in attr_links:
        d.edge(d.nid("ln"), ids[a], ids[b], S_LINE)
    for ri, r in enumerate(rels):
        for end in r["ends"]:
            eid = d.nid("end")
            d.edge(eid, ids["E:" + end["entity"]], ids[f"R:{ri}"], S_FULL if end["participation"] == "full" else S_LINE)
            # card beside the line (not on it), near the entity
            ex, ey = centre[end["entity"]]
            rx1, ry1 = rcent[ri]
            horizontal = abs(rx1 - ex) >= abs(ry1 - ey)
            dx, dy = (0, -12) if horizontal else (12, 0)
            d.edge_label(eid, str(end["card"]).upper(), "-0.5", dx, dy)
    return d.xml(model.get("title", "ERD") + " (Chen)")


def render_crowsfoot(model):
    d = Doc()
    ents = model["entities"]
    rels = model.get("relationships", [])
    sizes, ids = {}, {}
    for e in ents:
        rows = _cf_rows(e)
        width = max([_ew(e["name"], 150, 8.5)] + [_ew(a["name"], 150, 7.2) for a in rows])
        sizes[e["name"]] = (width, 28 + 22 * max(1, len(rows)))
    binary = [r for r in rels if len(r.get("ends", [])) == 2]
    cells = grid_layout(ents, binary)
    ncol = max(c for c, r in cells.values()) + 1
    nrow = max(r for c, r in cells.values()) + 1
    colw = [max([sizes[n][0] for n, (c, r) in cells.items() if c == ci] or [150]) for ci in range(ncol)]
    rowh = [max([sizes[n][1] for n, (c, r) in cells.items() if r == ri] or [60]) for ri in range(nrow)]
    GAPX, GAPY = 190, 110
    xs = [40 + sum(colw[:i]) + GAPX * i for i in range(ncol)]
    ys = [40 + sum(rowh[:i]) + GAPY * i for i in range(nrow)]
    for e in ents:
        n = e["name"]
        c, r = cells[n]
        w, h = sizes[n]
        x = xs[c] + (colw[c] - w) / 2          # centred in its column
        y = ys[r] + (rowh[r] - h) / 2          # centred in its row, so lines run straight
        tid = d.nid("tbl")
        ids[n] = tid
        style = S_CF_TABLE
        d.vertex(tid, n, style, x, y, w, h)
        for i, a in enumerate(_cf_rows(e) or [{"name": ""}]):
            rs = S_CF_ROW + ("fontStyle=4;" if a.get("key") else "")
            d.vertex(d.nid("row"), a["name"], rs, 0, 28 + 22 * i, w, 22, parent=tid)
    for r in binary:
        a, b = r["ends"]
        # The symbol beside entity X: max = X's own card, min = 1 if the OTHER
        # entity participates fully (every one of them must have an X), else 0.
        def sym(this, other):
            mx = "one" if str(this["card"]) == "1" else "many"
            mn = 1 if other["participation"] == "full" else 0
            return CF_END[(mn, mx)]
        # Name sits beside the line, never on it: above a horizontal line,
        # to the right of a vertical one (no white box cutting the line).
        (ca, ra), (cb, rb) = cells[a["entity"]], cells[b["entity"]]
        if ra == rb:
            place = "verticalAlign=bottom;align=center;spacingBottom=6;"
        elif ca == cb:
            place = "verticalAlign=middle;align=left;spacingLeft=10;"
        else:
            place = "verticalAlign=bottom;align=left;spacingLeft=8;spacingBottom=6;"
        style = (f"html=1;rounded=0;labelBackgroundColor=none;endSize=12;startSize=12;{place}"
                 f"strokeColor=#000000;startArrow={sym(a, b)};startFill=0;endArrow={sym(b, a)};endFill=0;")
        d.edge(d.nid("rel"), ids[a["entity"]], ids[b["entity"]], style, r["name"])
    return d.xml(model.get("title", "ERD") + " (crow's foot)")


def _cf_rows(e):
    """Crow's foot lists plain attributes: a composite is listed as its parts."""
    rows = []
    for a in e.get("attributes", []):
        if a.get("parts"):
            rows += [{"name": p} for p in a["parts"]]
        else:
            rows.append(a)
    return rows


def crowsfoot_notes(model):
    """What crow's foot notation has no symbol for, so it is not drawn."""
    out = []
    for e in model.get("entities", []):
        for a in e.get("attributes", []):
            if a.get("multivalued"):
                out.append(f"note: {e['name']}.{a['name']} is multi-valued; crow's foot has no symbol for that "
                           "(it is normally modelled as its own entity). Listed as a plain attribute.")
            if a.get("derived"):
                out.append(f"note: {e['name']}.{a['name']} is derived; crow's foot has no symbol for that. Listed as a plain attribute.")
        if e.get("weak"):
            out.append(f"note: {e['name']} is weak; crow's foot has no weak-entity symbol. Drawn as a normal entity.")
    for r in model.get("relationships", []):
        if r.get("attributes"):
            out.append(f"note: {r['name']} has attributes ({', '.join(x['name'] for x in r['attributes'])}); crow's foot "
                       "cannot draw attributes on a relationship (it is normally modelled as an associative entity). Not drawn.")
        if len(r.get("ends", [])) > 2:
            out.append(f"note: {r['name']} has {len(r['ends'])} ends; crow's foot only draws binary relationships. Not drawn.")
    return out

# ------------------------------------------------------------------- main ----


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("model", help="ER model JSON file")
    ap.add_argument("-o", "--output", help="output .drawio file")
    ap.add_argument("--notation", choices=["chen", "crowsfoot"], default=None,
                    help="default: the model's \"notation\" field, else chen")
    ap.add_argument("--check", action="store_true", help="only run the model checks")
    ap.add_argument("--url", action="store_true", help="also print an editable diagrams.net link")
    args = ap.parse_args(argv)
    with open(args.model, encoding="utf-8") as f:
        model = json.load(f)
    findings = check(model)
    for fd in findings:
        print(fd, file=sys.stderr)
    errors = [f for f in findings if f.sev == "error"]
    if args.check or errors:
        print(f"{len(errors)} error(s), {len(findings) - len(errors)} warning(s)", file=sys.stderr)
        return 1 if errors else 0
    notation = args.notation or model.get("notation", "chen")
    if notation == "crowsfoot":
        for note in crowsfoot_notes(model):
            print(note, file=sys.stderr)
    xml = render_crowsfoot(model) if notation == "crowsfoot" else render_chen(model)
    out = args.output or os.path.splitext(args.model)[0] + ("-crowsfoot" if notation == "crowsfoot" else "-chen") + ".drawio"
    with open(out, "w", encoding="utf-8") as f:
        f.write(xml)
    print(f"wrote {out} ({notation})")
    if args.url:
        here = os.path.dirname(os.path.abspath(__file__))
        sys.path.insert(0, here)
        from encode_drawio_url import edit_url
        print(edit_url(xml))
    return 0


if __name__ == "__main__":
    sys.exit(main())
