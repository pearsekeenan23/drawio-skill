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

Layout uses Graphviz (neato) when available; otherwise a simple grid. Every
check finding has a stable code (E-..., W-...) and a fix hint, like validate.py.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
from xml.sax.saxutils import escape

CARDS = {"1", "N", "M"}
PARTS = {"full", "partial"}

# ---------------------------------------------------------------- styles ----
# Chen shapes follow draw.io's built-in "Entity Relation" library, so the
# result stays editable with the same shapes students use in the labs.
S_ENTITY = "rounded=0;whiteSpace=wrap;html=1;fontStyle=1;fillColor=#ffffff;strokeColor=#000000;"
S_WEAK = "shape=ext;margin=3;double=1;whiteSpace=wrap;html=1;fontStyle=1;fillColor=#ffffff;strokeColor=#000000;"
S_REL = "shape=rhombus;perimeter=rhombusPerimeter;whiteSpace=wrap;html=1;fillColor=#ffffff;strokeColor=#000000;"
S_IDREL = "shape=rhombus;double=1;perimeter=rhombusPerimeter;whiteSpace=wrap;html=1;fillColor=#ffffff;strokeColor=#000000;"
S_ATTR = "ellipse;whiteSpace=wrap;html=1;fillColor=#ffffff;strokeColor=#000000;fontSize=11;"
S_KEY = S_ATTR + "fontStyle=4;"                       # underlined
S_MULTI = "ellipse;shape=doubleEllipse;margin=3;whiteSpace=wrap;html=1;fillColor=#ffffff;strokeColor=#000000;fontSize=11;"
S_DERIVED = S_ATTR + "dashed=1;"
S_LINE = "endArrow=none;html=1;rounded=0;strokeColor=#000000;"
S_FULL = "shape=link;html=1;rounded=0;strokeColor=#000000;"   # double line
S_CARD_LABEL = "edgeLabel;html=1;align=center;verticalAlign=middle;resizable=0;points=[];fontStyle=1;fontSize=12;labelBackgroundColor=#ffffff;"
S_TITLE = "text;html=1;fontSize=16;fontStyle=1;align=left;verticalAlign=middle;"
S_LEGEND = "text;html=1;fontSize=11;align=left;verticalAlign=top;fontColor=#555555;whiteSpace=wrap;"

# crow's foot
S_CF_TABLE = ("swimlane;fontStyle=1;childLayout=stackLayout;horizontal=1;startSize=28;"
              "horizontalStack=0;resizeParent=1;resizeParentMax=0;resizeLast=0;collapsible=0;"
              "marginBottom=0;html=1;fillColor=#ffffff;strokeColor=#000000;")
S_CF_ROW = ("text;strokeColor=none;fillColor=none;align=left;verticalAlign=middle;spacingLeft=6;"
            "spacingRight=4;overflow=hidden;rotatable=0;points=[[0,0.5],[1,0.5]];"
            "portConstraint=eastwest;html=1;fontSize=11;")
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
        elif not any(a.get("key") for a in attrs):
            E("E-NO-KEY", n, "entity has no identifier", "mark its identifying attribute with \"key\": true")
        if not attrs:
            W("W-NO-ATTRS", n, "entity has no attributes", "list its attributes (an entity is described by more than one)")
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


def _neato(nodes, edges, sep=18):
    """nodes: {id: (w, h)} in px; edges: [(a, b, length_in_inches)].
    Returns {id: (cx, cy)} in px, y downwards, or None without Graphviz."""
    exe = shutil.which("neato")
    if not exe:
        return None
    lines = ["graph G {", f'graph [overlap=false, splines=false, sep="+{sep}", esep="+10", start=7];',
             "node [fixedsize=true, label=\"\"];"]
    for nid, (w, h) in nodes.items():
        lines.append(f'"{nid}" [width={w / 72:.3f}, height={h / 72:.3f}];')
    for a, b, ln in edges:
        lines.append(f'"{a}" -- "{b}" [len={ln}];')
    lines.append("}")
    res = subprocess.run([exe, "-Tplain"], input="\n".join(lines), capture_output=True, text=True)
    if res.returncode:
        return None
    pos, height = {}, 0
    for line in res.stdout.splitlines():
        p = line.split()
        if p and p[0] == "graph":
            height = float(p[3]) * 72
        elif p and p[0] == "node":
            pos[p[1].strip('"')] = (float(p[2]) * 72, height - float(p[3]) * 72)
    return pos


def _grid(nodes):
    pos, cols = {}, 4
    for i, nid in enumerate(nodes):
        pos[nid] = (120 + (i % cols) * 220, 120 + (i // cols) * 180)
    return pos

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

    def edge_label(self, edge_id, text, at):
        cid = self.nid("lbl")
        self.cells.append(
            f'<mxCell id="{cid}" value="{escape(text)}" style="{S_CARD_LABEL}" vertex="1" connectable="0" parent="{edge_id}">'
            f'<mxGeometry x="{at}" relative="1" as="geometry"><mxPoint as="offset"/></mxGeometry></mxCell>')

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


def render_chen(model):
    d = Doc()
    ents = model["entities"]
    rels = model.get("relationships", [])
    nodes, links, ids = {}, [], {}
    for e in ents:
        k = "E:" + e["name"]
        nodes[k] = (_ew(e["name"], 120, 8.5), 50)
        for i, a in enumerate(e.get("attributes", [])):
            ak = f"A:{e['name']}:{i}"
            nodes[ak] = (_ew(a["name"], 90), 36)
            links.append((k, ak, 1.0))
            for j, p in enumerate(a.get("parts", [])):
                pk = f"{ak}:{j}"
                nodes[pk] = (_ew(p, 80), 32)
                links.append((ak, pk, 0.9))
    for ri, r in enumerate(rels):
        rk = f"R:{ri}"
        nodes[rk] = (max(110, len(r["name"]) * 8 + 50), 64)
        for end in r["ends"]:
            links.append(("E:" + end["entity"], rk, 1.6))
        for i, a in enumerate(r.get("attributes", [])):
            ak = f"RA:{ri}:{i}"
            nodes[ak] = (_ew(a["name"], 90), 36)
            links.append((rk, ak, 1.1))
    pos = _neato(nodes, links) or _grid(nodes)
    minx = min(x - nodes[k][0] / 2 for k, (x, y) in pos.items())
    miny = min(y - nodes[k][1] / 2 for k, (x, y) in pos.items())
    ox, oy = 40 - minx, 80 - miny

    def place(key, cid, value, style):
        w, h = nodes[key]
        cx, cy = pos[key]
        d.vertex(cid, value, style, cx - w / 2 + ox, cy - h / 2 + oy, w, h)
        ids[key] = cid

    d.vertex("title", model.get("title", "ER diagram") + " — Chen notation", S_TITLE, 40, 20, 600, 30)
    for e in ents:
        k = "E:" + e["name"]
        place(k, d.nid("ent"), e["name"], S_WEAK if e.get("weak") else S_ENTITY)
        for i, a in enumerate(e.get("attributes", [])):
            ak = f"A:{e['name']}:{i}"
            place(ak, d.nid("att"), _attr_label(a), _attr_style(a))
            d.edge(d.nid("ln"), ids[k], ids[ak], S_LINE)
            for j, p in enumerate(a.get("parts", [])):
                pk = f"{ak}:{j}"
                place(pk, d.nid("att"), p, S_ATTR)
                d.edge(d.nid("ln"), ids[ak], ids[pk], S_LINE)
    for ri, r in enumerate(rels):
        rk = f"R:{ri}"
        place(rk, d.nid("rel"), r["name"], S_IDREL if r.get("identifying") else S_REL)
        for end in r["ends"]:
            eid = d.nid("end")
            d.edge(eid, ids["E:" + end["entity"]], ids[rk], S_FULL if end["participation"] == "full" else S_LINE)
            d.edge_label(eid, str(end["card"]).upper(), "-0.55")   # near the entity
        for i, a in enumerate(r.get("attributes", [])):
            ak = f"RA:{ri}:{i}"
            place(ak, d.nid("att"), _attr_label(a), _attr_style(a))
            d.edge(d.nid("ln"), ids[rk], ids[ak], S_LINE)
    ymax = max(cy + nodes[k][1] / 2 for k, (cx, cy) in pos.items()) + oy
    d.vertex("legend", "Chen notation · rectangle = entity · double rectangle = weak entity · diamond = relationship · "
             "double diamond = identifying relationship · underlined = key · dashed underline = partial key · "
             "double ellipse = multi-valued · dashed ellipse = derived · double line = full participation · "
             "single line = partial participation · 1 / N / M = cardinality",
             S_LEGEND, 40, ymax + 30, 760, 50)
    return d.xml(model.get("title", "ERD") + " (Chen)")


def render_crowsfoot(model):
    d = Doc()
    ents = model["entities"]
    rels = model.get("relationships", [])
    sizes, ids = {}, {}
    for e in ents:
        rows = e.get("attributes", [])
        width = max([_ew(e["name"], 150, 8.5)] + [_ew(_cf_row(a), 150, 6.6) for a in rows])
        sizes["E:" + e["name"]] = (width, 28 + 22 * max(1, len(rows)))
    links = []
    binary = [r for r in rels if len(r.get("ends", [])) == 2]
    for r in binary:
        links.append(("E:" + r["ends"][0]["entity"], "E:" + r["ends"][1]["entity"], 4.0))
    pos = _neato(sizes, links, sep=70) or _grid(sizes)
    minx = min(x - sizes[k][0] / 2 for k, (x, y) in pos.items())
    miny = min(y - sizes[k][1] / 2 for k, (x, y) in pos.items())
    ox, oy = 40 - minx, 80 - miny
    d.vertex("title", model.get("title", "ER diagram") + " — crow's foot notation", S_TITLE, 40, 20, 600, 30)
    for e in ents:
        k = "E:" + e["name"]
        w, h = sizes[k]
        cx, cy = pos[k]
        tid = d.nid("tbl")
        ids[k] = tid
        style = S_CF_TABLE + ("dashed=0;strokeWidth=2;" if e.get("weak") else "")
        d.vertex(tid, e["name"], style, cx - w / 2 + ox, cy - h / 2 + oy, w, h)
        for i, a in enumerate(e.get("attributes", []) or [{"name": ""}]):
            rs = S_CF_ROW + ("fontStyle=4;" if a.get("key") or a.get("partial_key") else "")
            d.vertex(d.nid("row"), _cf_row(a), rs, 0, 28 + 22 * i, w, 22, parent=tid)
    for r in binary:
        a, b = r["ends"]
        # The symbol beside entity X: max = X's own card, min = 1 if the OTHER
        # entity participates fully (every one of them must have an X), else 0.
        def sym(this, other):
            mx = "one" if str(this["card"]) == "1" else "many"
            mn = 1 if other["participation"] == "full" else 0
            return CF_END[(mn, mx)]
        style = (f"edgeStyle=entityRelationEdgeStyle;html=1;rounded=0;fontSize=11;labelBackgroundColor=#ffffff;"
                 f"strokeColor=#000000;startArrow={sym(a, b)};startFill=0;endArrow={sym(b, a)};endFill=0;")
        label = r["name"] + ("  [" + ", ".join(x["name"] for x in r.get("attributes", [])) + "]" if r.get("attributes") else "")
        d.edge(d.nid("rel"), ids["E:" + a["entity"]], ids["E:" + b["entity"]], style, label)
    ymax = max(cy + sizes[k][1] / 2 for k, (cx, cy) in pos.items()) + oy
    d.vertex("legend", "Crow's foot notation · bar = one · crow's foot = many · circle = zero (optional) · "
             "the symbol beside an entity says how many of THAT entity relate to one of the other · "
             "underlined = key · relationship attributes shown in [brackets] on the line",
             S_LEGEND, 40, ymax + 30, 760, 40)
    return d.xml(model.get("title", "ERD") + " (crow's foot)")


def _cf_row(a):
    tags = []
    if a.get("key"):
        tags.append("PK")
    if a.get("partial_key"):
        tags.append("partial key")
    if a.get("multivalued"):
        tags.append("multi-valued")
    if a.get("derived"):
        tags.append("derived")
    name = a["name"] + (" (" + ", ".join(a["parts"]) + ")" if a.get("parts") else "")
    return name + ("  — " + ", ".join(tags) if tags else "")

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
