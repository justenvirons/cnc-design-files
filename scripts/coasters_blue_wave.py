#!/usr/bin/env python3
"""
Generate the "2026 Blue Wave" political coasters (Steph's set) as Carbide Create
(.c2d) files plus SVG previews.

Each coaster is a pre-cut live-edge round with a 3" (76.2 mm) workable diameter.
The layout follows wall_lake_house.c2d (Nomad Pro, softwood, #122 1/32" flat end
mill, zero at the centre of the stock top):

    layer "text"  - candidate name + tagline   -> pocket, #122, 1.27 mm
    layer "state" - state silhouette           -> pocket, #122, 1.27 mm
    layer "wave"  - small blue wave (epoxy)    -> pocket, #122, 1.524 mm

Usage:  python3 scripts/coasters_blue_wave.py
Requires: shapely, fonttools
"""
import json
import math
import sqlite3
import uuid as uuidlib
import zlib
from pathlib import Path

from fontTools.pens.recordingPen import RecordingPen
from fontTools.ttLib import TTFont
from shapely import affinity
from shapely.geometry import LineString, MultiPolygon, Point, Polygon
from shapely.ops import unary_union

REPO = Path(__file__).resolve().parents[1]
OUT_DIR = REPO / "designs" / "coasters_blue_wave" / "steph"
STATES = REPO / "designs" / "coasters_blue_wave" / "data" / "states_tx_mi.geojson"
FONT = REPO / "fonts" / "Anton-Regular.ttf"
# Numbers (and + % ') are set in Arial Bold. Drop arialbd.ttf into fonts/ to use the real
# thing; otherwise Liberation Sans Bold (metric-compatible Arial clone) is used.
NUM_FONT = next(f for f in (REPO / "fonts" / "arialbd.ttf", REPO / "fonts" / "LiberationSans-Bold.ttf")
                if f.exists())
NUM_CHARS = set("0123456789+%\u2019'")

# ---------------------------------------------------------------- dimensions (mm)
STOCK = 76.2            # 3" square stock area; the round sits inside it
CX = CY = STOCK / 2     # centre of the coaster (also XY zero)
THICKNESS = 19.05       # same as reference; Z zero is the top, so it only affects the preview
R_SAFE = 35.5           # keep all artwork inside this radius (3" dia less a margin)
TOOL_D = 0.79502        # #122 1/32" flat end mill

DESIGNS = [
    dict(file="steph_01_tx_governor_hinojosa", state="Texas",
         name="HINOJOSA!", tag="1ST SINCE ’95!"),
    dict(file="steph_02_tx_senate_talarico", state="Texas",
         name="TALARICO!", tag="+12%"),
    dict(file="steph_03_mi_governor_benson", state="Michigan",
         name="BENSON!", tag="+11%"),
    dict(file="steph_04_mi_senate_abdul", state="Michigan",
         name="ABDUL!", tag="1ST MUSLIM!"),
]

# vertical bands, y measured upward from the coaster centre
NAME_BASE, NAME_CAP_MAX = 16.2, 10.5
STATE_TOP, STATE_BOTTOM, STATE_W_MAX = 12.4, -10.4, 48.0
TAG_BASE, TAG_CAP_MAX = -19.0, 6.6
TEXT_MARGIN = 3.0       # extra clearance from the safe circle for text

# ---------------------------------------------------------------- geometry helpers


def chord_half(y):
    """Half-width of the safe circle at height y."""
    return math.sqrt(max(R_SAFE ** 2 - y ** 2, 0.0))


def flatten_glyphs(text, font, num_font, tracking=0.04):
    """Return text as a shapely geometry in main-font units (baseline y=0), plus cap height.

    Characters in NUM_CHARS come from num_font, scaled so its cap height matches."""
    upm = font["head"].unitsPerEm
    cap = font["OS/2"].sCapHeight
    num_scale = cap / num_font["OS/2"].sCapHeight
    x = 0.0
    polys = []
    for ch in text:
        f, k = (num_font, num_scale) if ch in NUM_CHARS else (font, 1.0)
        gs, cmap = f.getGlyphSet(), f.getBestCmap()
        gname = cmap[ord(ch)]
        pen = RecordingPen()
        gs[gname].draw(pen)
        rings, cur = [], []
        for op, args in pen.value:
            if op == "moveTo":
                cur = [args[0]]
            elif op == "lineTo":
                cur.append(args[0])
            elif op == "qCurveTo":
                cur.extend(_quad_points(cur[-1], args))
            elif op == "curveTo":
                cur.extend(_cubic_points(cur[-1], *args))
            elif op in ("closePath", "endPath"):
                if len(cur) > 2:
                    rings.append([(px * k + x, py * k) for px, py in cur])
                cur = []
        # even-odd fill: build glyph from rings
        g = None
        for r in rings:
            p = Polygon(r).buffer(0)
            g = p if g is None else g.symmetric_difference(p)
        if g is not None:
            polys.append(g)
        x += gs[gname].width * k + tracking * upm
    return unary_union(polys), cap


def _quad_points(p0, args, n=10):
    # TrueType qCurveTo with implied on-curve points
    pts = []
    offs = list(args[:-1])
    end = args[-1]
    start = p0
    for i, c in enumerate(offs):
        nxt = end if i == len(offs) - 1 else ((c[0] + offs[i + 1][0]) / 2, (c[1] + offs[i + 1][1]) / 2)
        for k in range(1, n + 1):
            t = k / n
            pts.append(((1 - t) ** 2 * start[0] + 2 * (1 - t) * t * c[0] + t * t * nxt[0],
                        (1 - t) ** 2 * start[1] + 2 * (1 - t) * t * c[1] + t * t * nxt[1]))
        start = nxt
    return pts


def _cubic_points(p0, c1, c2, p1, n=12):
    return [((1 - t) ** 3 * p0[0] + 3 * (1 - t) ** 2 * t * c1[0] + 3 * (1 - t) * t * t * c2[0] + t ** 3 * p1[0],
             (1 - t) ** 3 * p0[1] + 3 * (1 - t) ** 2 * t * c1[1] + 3 * (1 - t) * t * t * c2[1] + t ** 3 * p1[1])
            for t in (k / n for k in range(1, n + 1))]


def text_block(text, font, num_font, baseline, cap_max):
    """Centre text on the coaster at `baseline`, shrinking it to fit the safe circle."""
    geom, cap_units = flatten_glyphs(text, font, num_font)
    minx, miny, maxx, maxy = geom.bounds
    s = cap_max / cap_units
    for _ in range(60):
        w = (maxx - minx) * s
        top, bot = baseline + maxy * s, baseline + miny * s
        avail = 2 * (min(chord_half(top), chord_half(bot)) - TEXT_MARGIN)
        if w <= avail:
            break
        s *= 0.98
    g = affinity.scale(geom, s, s, origin=(0, 0))
    g = affinity.translate(g, -(minx + maxx) / 2 * s, baseline)
    return g, cap_units * s


def state_shape(name):
    fc = json.loads(STATES.read_text())
    feat = next(f for f in fc["features"] if f["properties"]["name"] == name)
    polys = [Polygon(p[0], p[1:]) for p in feat["geometry"]["coordinates"]]
    polys.sort(key=lambda p: p.area, reverse=True)
    # keep the main land masses only (Michigan: both peninsulas; drops Isle Royale etc.)
    keep = [p for p in polys if p.area > 0.04 * polys[0].area]
    g = unary_union(keep)
    minx, miny, maxx, maxy = g.bounds
    s = min(STATE_W_MAX / (maxx - minx), (STATE_TOP - STATE_BOTTOM) / (maxy - miny))
    g = affinity.scale(g, s, s, origin=(0, 0))
    minx, miny, maxx, maxy = g.bounds
    g = affinity.translate(g, -(minx + maxx) / 2, (STATE_TOP + STATE_BOTTOM) / 2 - (miny + maxy) / 2)
    # smooth away features the 1/32" cutter can't resolve, then simplify
    r = TOOL_D * 0.55
    g = g.buffer(-r, join_style=1).buffer(r, join_style=1).simplify(0.03)
    return g


def _arc(cx, cy, r, a0, a1, n=72):
    return [(cx + r * math.cos(math.radians(a0 + (a1 - a0) * i / n)),
             cy + r * math.sin(math.radians(a0 + (a1 - a0) * i / n))) for i in range(n + 1)]


def _tapered_stroke(spine, r0, r1):
    """Union of circles along a spine with radius tapering r0 -> r1 (round-tipped claw)."""
    n = len(spine) - 1
    return unary_union([Point(x, y).buffer(r0 + (r1 - r0) * i / n, quad_segs=16)
                        for i, (x, y) in enumerate(spine)])


def wave_shape():
    """A single great curling wave, simplified woodblock style.

    Built in local units (roughly mm) then scaled to sit under the tagline:
      body  - back of the wave rising from a tapered tail, rolling over into the crest
      eye   - hollow under the curl (left as wood), open at the bottom like a tube
      claws - foam fingers reaching off the leading lip
      spray - a few foam dots ahead of the crest
      swell - low trailing water to the right with a small secondary hump
      stripe- a thin wood line through the body and curl, like a brush stroke
    """
    cx, cy, R, RI = 13.0, 6.0, 5.0, 2.6            # crest centre, outer / eye radius
    lip = -40                                      # angle where the curl ends
    jx, jy = cx + R * math.cos(math.radians(160)), cy + R * math.sin(math.radians(160))
    tail_x = 1.5
    back = [(tail_x + (jx - tail_x) * t, jy * t ** 2.0) for t in (i / 60 for i in range(61))]
    outer = _arc(cx, cy, R, 160, lip)
    inner = _arc(cx, cy, RI, lip, 205)
    fx, fy = inner[-1]
    face_end = (cx + 2.6, 0.0)
    ctrl = (cx - 1.6, 0.4)                         # hollow, concave wave face
    face = [((1 - t) ** 2 * fx + 2 * (1 - t) * t * ctrl[0] + t * t * face_end[0],
             (1 - t) ** 2 * fy + 2 * (1 - t) * t * ctrl[1] + t * t * face_end[1])
            for t in (i / 30 for i in range(1, 31))]
    body = Polygon(back + outer[1:] + inner + face + [(tail_x, 0.0)]).buffer(0)

    # trailing swell with a small hump
    sw_top = []
    x_end = cx + 10.0
    for i in range(61):
        x = cx + 1.5 + (x_end - cx - 1.5) * i / 60
        taper = min(1.0, (x_end - x) / 2.2)
        sw_top.append((x, max(0.0, taper * (0.95 + 1.0 * math.exp(-((x - (cx + 6.3)) / 1.4) ** 2)))))
    swell = Polygon([(cx + 1.0, 0.0)] + sw_top + [(x_end, 0.0)])

    # foam claws off the outer edge of the crest, curling forward and down
    claws = []
    for ang, length in ((36, 2.2), (14, 2.6), (-8, 2.6), (-30, 2.3)):
        a = math.radians(ang)
        x, y = cx + (R - 0.5) * math.cos(a), cy + (R - 0.5) * math.sin(a)
        heading = a - math.radians(20)
        spine = [(x, y)]
        for _ in range(12):
            heading -= math.radians(6.0)            # bend clockwise as it reaches out
            x += length / 12 * math.cos(heading)
            y += length / 12 * math.sin(heading)
            spine.append((x, y))
        claws.append(_tapered_stroke(spine, 0.8, 0.5))

    spray = [Point(x, y).buffer(r, quad_segs=16) for x, y, r in
             ((cx + 6.9, cy + 4.2, 0.65), (cx + 8.2, cy + 2.2, 0.58), (cx + 5.6, cy + 6.0, 0.52))]

    # wood brush stripe: parallel to the back, then following the curl
    sr = (R + RI) / 2
    sx, sy = cx + sr * math.cos(math.radians(160)), cy + sr * math.sin(math.radians(160))
    sp = [(tail_x + 4.0 + (sx - tail_x - 4.0) * t, 0.9 + (sy - 0.9) * t ** 1.6)
          for t in (i / 30 for i in range(31))]
    sp += _arc(cx, cy, sr, 160, 70, 30)[1:]
    stripe = _tapered_stroke(sp, 0.12, 0.26)

    base = Polygon([(tail_x + 1.0, 0.0), (x_end - 1.0, 0.0), (x_end - 1.0, 0.95), (tail_x + 1.0, 0.95)])
    g = unary_union([body, swell, base, *claws, *spray]).difference(stripe)

    # scale/position: top just under the tagline, everything inside the safe circle
    top_y = TAG_BASE - 1.7
    sc = 1.5
    for _ in range(120):
        gg = affinity.scale(g, sc, sc, origin=(0, 0))
        bx0, by0, bx1, by1 = gg.bounds
        gg = affinity.translate(gg, -(bx0 + bx1) / 2, top_y - by1)
        if gg.difference(Point(0, 0).buffer(R_SAFE - 0.3, quad_segs=64)).area < 1e-6:
            break
        sc *= 0.99
    # keep only what the 1/32" cutter can actually make, so the file matches the result
    r = TOOL_D / 2 * 0.98
    return gg.buffer(-r, quad_segs=16).buffer(r, quad_segs=16).simplify(0.02)


def to_stock(g):
    """Coaster-centred coords (y up) -> Carbide Create stock coords (origin bottom-left)."""
    return affinity.translate(g, CX, CY)


def polygons(g):
    if isinstance(g, Polygon):
        return [g]
    if isinstance(g, MultiPolygon):
        return list(g.geoms)
    return [p for gg in g.geoms for p in polygons(gg)]


def rings(g):
    for p in polygons(g):
        yield list(p.exterior.coords)
        for i in p.interiors:
            yield list(i.coords)


def check_cuttable(name, g):
    """Report how much of a pocket the 1/32" cutter can actually reach."""
    r = TOOL_D / 2
    reach = g.buffer(-r).buffer(r)
    lost = 1 - reach.area / g.area
    print(f"    {name:6s} area {g.area:7.1f} mm^2, unreachable by #122: {lost * 100:4.1f}%")


# ---------------------------------------------------------------- c2d writer

def new_uuid():
    return "{" + str(uuidlib.uuid4()) + "}"


def layer_json(name, rgb, uid):
    return {"blue": rgb[2], "green": rgb[1], "locked": False, "name": name,
            "red": rgb[0], "uuid": uid, "visible": True}


def path_element(ring, layer):
    pts = [list(map(float, p)) for p in ring]
    if pts[0] != pts[-1]:
        pts.append(pts[0])
    n = len(pts)
    points = pts + [pts[0]]                       # trailing close marker (type 4)
    point_type = [0] + [1] * (n - 1) + [4]
    cp1 = [pts[0]] + [pts[i - 1] for i in range(1, n)] + [pts[0]]
    cp2 = [pts[0]] + [pts[i] for i in range(1, n)] + [pts[0]]
    return {"behavior": 0, "cp1": cp1, "cp2": cp2, "geometryType": "path", "group_id": [],
            "id": new_uuid(), "layer": layer, "point_type": point_type, "points": points,
            "position": [0, 0], "smooth": [0] * len(points), "tabs": []}


TOOL_122 = {
    "angle": 0, "corner_radius": 0, "diameter": TOOL_D, "display_mm": False,
    "finish_allowance": 0.1524, "flutes": 2, "length": 1.5875, "model": "122", "name": "",
    "number": 122, "overall_length": 3.175, "plungerate": 508, "read_only": True,
    "slot_depth": 0.254, "slot_feedrate": 1397, "slot_rpm": 24000, "surfacing_feedrate": 1397,
    "surfacing_rpm": 24000, "surfacing_stepover": 10, "type": 0,
    "url": "https://shop.carbide3d.com/products/122-0312-flat-cutter-qty-3",
    "uuid": "{00000000-0000-0000-0000-000000000000}", "vendor": "Carbide 3D",
}


def pocket_toolpath(name, depth, layer_uuid, group_uuid):
    return {"angle": 0, "automatic_parameters": True, "elements": [], "enable_ramping": False,
            "enable_rest": False, "enabled": True, "end_depth": f"{depth:.3f}", "name": name,
            "ramp_angle": 20, "rest_diameter": 6.35,
            "speeds": {"feedrate": 1397, "plungerate": 508, "rpm": 24000},
            "start_depth": "0.000", "stepdown": 0.254, "stepover": 0.4064, "stock_to_leave": 0.5,
            "tolerance": 0.01, "tool": dict(TOOL_122), "toolpath_group": group_uuid,
            "toolpath_layers": [layer_uuid], "type": "pocket_toolpath", "uuid": new_uuid()}


PARAMS = {
    "num_toolpaths": "3", "minimum_carbide_motion_version": "565", "requires_pro": "0",
    "active_layer": "", "version": "100", "build_num": "764", "minimum_build_num": "714",
    "width": f"{STOCK}", "height": f"{STOCK}", "thickness": f"{THICKNESS}", "display_mm": "0",
    "grid_enabled": "1", "grid_spacing": "0.254", "zero_z": "0.0", "zero_x": f"{CX}",
    "zero_y": f"{CY}", "material": "Softwood", "machine": "Nomad Pro", "machine_type": "Nomad",
    "retract": "3.81", "tiling_enabled": "0", "tile_margin_x": "25.4", "tile_overlap_y": "12.7",
    "tile_height": "38.1", "tile_current_index": "0", "background_visible": "0",
    "background_rotation": "0.0", "background_scale": "1.0", "background_position_x": "0.0",
    "background_position_y": "0.0", "background_opacity": "0.5", "show_notes": "1",
}

SCHEMA = """
CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE sqlar(name TEXT PRIMARY KEY, mode INT, mtime INT DEFAULT CURRENT_TIMESTAMP, sz INT, data BLOB);
CREATE TABLE params(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE items(id INTEGER PRIMARY KEY AUTOINCREMENT, uuid TEXT UNIQUE, name TEXT, type TEXT,
                   version TEXT, sz INT, data BLOB);
CREATE TABLE log(id INTEGER PRIMARY KEY AUTOINCREMENT, time INT DEFAULT CURRENT_TIMESTAMP,
                 type TEXT, name TEXT, data TEXT);
"""

# model blob copied from the reference file (identity model settings)
MODEL_BLOB = bytes.fromhex(
    "01000000000000005227a089b0e1b13f000000000000f03f0000000000000000"
    "00000000000000e8030000e80300000000000000")


def write_c2d(path, layers_geoms, notes, svg):
    if path.exists():
        path.unlink()
    db = sqlite3.connect(path)
    db.executescript(SCHEMA)
    db.executemany("INSERT INTO params VALUES (?,?)", PARAMS.items())

    def item(uid, name, typ, obj, version="J1"):
        raw = json.dumps(obj, indent=4).encode()
        db.execute("INSERT INTO items(uuid,name,type,version,sz,data) VALUES (?,?,?,?,?,?)",
                   (uid, name, typ, version, len(raw), zlib.compress(raw)))

    item("", "DEFAULT", "layer", layer_json("DEFAULT", (0, 0, 0), ""))
    layer_objs = {}
    for lname, (rgb, _geom, _depth, _tp) in layers_geoms.items():
        uid = new_uuid()
        layer_objs[lname] = layer_json(lname, rgb, uid)
        item(uid, lname, "layer", layer_objs[lname])
    for lname, (_rgb, geom, _depth, _tp) in layers_geoms.items():
        for ring in rings(geom):
            el = path_element(ring, layer_objs[lname])
            item(el["id"], "path", "element", el)
    gid = new_uuid()
    item(gid, "", "toolpath_group", {"enabled": True, "expanded": True, "name": "Coaster", "uuid": gid})
    for lname, (_rgb, _geom, depth, tpname) in layers_geoms.items():
        tp = pocket_toolpath(tpname, depth, layer_objs[lname]["uuid"], gid)
        item(tp["uuid"], "pocket_toolpath", "toolpath", tp)
    db.execute("INSERT INTO items(uuid,name,type,version,sz,data) VALUES (?,?,?,?,?,?)",
               ("MODEL", "", "model", "model_1", len(MODEL_BLOB), zlib.compress(MODEL_BLOB)))
    svgb = svg.encode()
    for n, data in (("all.svg", svgb), ("preview.svg", svgb), ("notes.txt", notes.encode())):
        db.execute("INSERT INTO sqlar(name,mode,sz,data) VALUES (?,?,?,?)",
                   (n, 33188, len(data), zlib.compress(data) if data else b""))
    db.commit()
    db.close()


# ---------------------------------------------------------------- previews

def svg_path_d(g, flip=True):
    out = []
    for ring in rings(g):
        pts = [(x, STOCK - y if flip else y) for x, y in ring]
        out.append("M" + " L".join(f"{x:.3f} {y:.3f}" for x, y in pts) + " Z")
    return " ".join(out)


def outline_svg(layers):
    """Plain outline SVG (stored inside the .c2d like Carbide Create does)."""
    body = "\n".join(f'<path d="{svg_path_d(g)}" stroke="black" stroke-width="0.2" fill="none" />'
                     for _rgb, g, _d, _t in layers.values())
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n'
            f'<svg version="1.1" xmlns="http://www.w3.org/2000/svg" width="{STOCK}mm" height="{STOCK}mm" '
            f'viewBox="0 0 {STOCK} {STOCK}">\n{body}\n</svg>\n')


def preview_svg(layers, title):
    """Coloured mock-up: wood round, pocketed areas darker, wave filled blue."""
    fills = {"text": "#5a3b1e", "state": "#5a3b1e", "wave": "#1f5fbf"}
    paths = "\n".join(f'  <path d="{svg_path_d(g)}" fill="{fills[n]}" fill-rule="evenodd" />'
                      for n, (_rgb, g, _d, _t) in layers.items())
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="600" height="600" viewBox="0 0 {STOCK} {STOCK}">
  <title>{title}</title>
  <rect width="{STOCK}" height="{STOCK}" fill="#ffffff"/>
  <circle cx="{CX}" cy="{CY}" r="{STOCK / 2}" fill="#e7c896" stroke="#7a5230" stroke-width="0.6"/>
  <circle cx="{CX}" cy="{CY}" r="{R_SAFE}" fill="none" stroke="#b08a5a" stroke-width="0.15" stroke-dasharray="1 1"/>
{paths}
</svg>
"""


# ---------------------------------------------------------------- main

def build(d, font, num_font):
    name, cap_n = text_block(d["name"], font, num_font, NAME_BASE, NAME_CAP_MAX)
    tag, cap_t = text_block(d["tag"], font, num_font, TAG_BASE, TAG_CAP_MAX)
    text = unary_union([name, tag])
    state = state_shape(d["state"])
    wave = wave_shape()
    for g, label in ((text, "text"), (state, "state"), (wave, "wave")):
        assert g.difference(Point(0, 0).buffer(R_SAFE, quad_segs=64)).area < 1e-6, f"{label} outside safe circle"
    assert not text.intersects(state) and not state.intersects(wave) and not text.intersects(wave)
    print(f"  {d['file']}: name cap {cap_n:.1f} mm, tagline cap {cap_t:.1f} mm")
    for g, label in ((text, "text"), (state, "state"), (wave, "wave")):
        check_cuttable(label, g)
    return {
        "text": ((0, 0, 255), to_stock(text), 1.270, "Text - pocket #122 1.27mm"),
        "state": ((0, 128, 0), to_stock(state), 1.270, "State - pocket #122 1.27mm"),
        "wave": ((0, 160, 255), to_stock(wave), 1.524, "Blue wave - pocket #122 1.524mm (epoxy)"),
    }


def main():
    font = TTFont(FONT)
    num_font = TTFont(NUM_FONT)
    print(f"numbers font: {NUM_FONT.name}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "previews").mkdir(exist_ok=True)
    for d in DESIGNS:
        layers = build(d, font, num_font)
        notes = (f"2026 Blue Wave coaster - {d['name']} / {d['tag']} ({d['state']})\n"
                 "Pre-cut live-edge round, 3in workable diameter. Zero XY at centre, Z at top.\n"
                 "Tool: #122 1/32in flat. Text + state pocket 1.27mm; wave pocket 1.524mm for blue epoxy.\n"
                 "Generated by scripts/coasters_blue_wave.py\n")
        write_c2d(OUT_DIR / f"{d['file']}.c2d", layers, notes, outline_svg(layers))
        (OUT_DIR / "previews" / f"{d['file']}.svg").write_text(
            preview_svg(layers, f"{d['name']} {d['tag']}"))


if __name__ == "__main__":
    main()
