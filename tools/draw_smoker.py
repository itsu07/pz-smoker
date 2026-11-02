"""Draw the smoker tile procedurally (our own art, no vanilla images).

Usage: python draw_smoker.py <out dir> [variant ...]
Writes smoker_<variant>.png (one 128x256 frame, Tiles2x scale) per variant.
Feed the chosen one to make_tile.py.

Isometric layout of a Tiles2x frame: the floor diamond of the tile is
(64,192) (128,224) (64,256) (0,224); +1 tile in x moves (+64,+32), +1 tile in y
moves (-64,+32), and one storey (z) is 192 px up.
"""
import random
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

FW, FH = 128, 256
CX, CY = 64, 224          # screen position of the tile centre on the floor


def P(x, y, z):
    """World (tiles, tiles, px up) -> screen px."""
    return (CX + (x - y) * 64, CY + (x + y) * 32 - z)


def shade(c, k):
    return tuple(max(0, min(255, int(v * k))) for v in c[:3]) + (255,)


def mix(a, b, t):
    return tuple(int(a[i] * (1 - t) + b[i] * t) for i in range(3)) + (255,)


class Box:
    """Axis aligned box: x in [-w/2, w/2], y in [-d/2, d/2], z in [z0, z0+h]."""

    def __init__(self, w, d, z0, h):
        self.w, self.d, self.z0, self.h = w, d, z0, h

    # u: 0..1 along the face from left to right on screen, v: 0..1 bottom to top
    def south(self, u, v):
        return P(-self.w / 2 + u * self.w, self.d / 2, self.z0 + v * self.h)

    def east(self, u, v):
        return P(self.w / 2, self.d / 2 - u * self.d, self.z0 + v * self.h)

    def top(self, u, v):
        # u along x (screen right-down), v along -y (screen right-up)
        return P(-self.w / 2 + u * self.w, self.d / 2 - v * self.d, self.z0 + self.h)

    @staticmethod
    def quad(face, u0, v0, u1, v1):
        return [face(u0, v0), face(u1, v0), face(u1, v1), face(u0, v1)]


def textured(base_layer, seed, strength):
    """Add fine noise and faint streaks to everything drawn on base_layer."""
    rng = random.Random(seed)
    noise = Image.new('L', (FW, FH))
    px = noise.load()
    for y in range(FH):
        streak = rng.uniform(-1, 1) * 0.25
        for x in range(FW):
            px[x, y] = int(128 + (rng.uniform(-1, 1) + streak) * strength)
    noise = noise.filter(ImageFilter.GaussianBlur(0.6))
    rgb = base_layer.convert('RGB')
    grey = Image.merge('RGB', (noise, noise, noise))
    out = ImageChops.overlay(rgb, grey)
    out.putalpha(base_layer.split()[3])
    return out


def stains(im, box, color, seed, amount):
    """Soft heat stains concentrated low on the faces and around the fire door."""
    rng = random.Random(seed)
    layer = Image.new('RGBA', (FW, FH), color[:3] + (0,))
    mask = Image.new('L', (FW, FH))
    d = ImageDraw.Draw(mask)
    for _ in range(amount):
        face = rng.choice([box.south, box.east])
        u, v = rng.uniform(0.05, 0.95), rng.uniform(0.0, 0.9) ** 1.6
        x, y = face(u, v)
        r = rng.uniform(3, 9)
        d.ellipse((x - r, y - r * 0.7, x + r, y + r * 0.7), fill=rng.randint(40, 110))
    mask = mask.filter(ImageFilter.GaussianBlur(3))
    alpha = ImageChops.multiply(mask, im.split()[3])
    layer.putalpha(alpha)
    im.alpha_composite(layer)


def draw_legs(d, box, leg_color, inset=0.06, width=2):
    pts = []
    for sx, sy in ((-1, 1), (1, 1), (1, -1), (-1, -1)):
        x = sx * (box.w / 2 - inset)
        y = sy * (box.d / 2 - inset)
        pts.append((x, y))
    # back leg first (hidden mostly), then others
    for x, y in sorted(pts, key=lambda p: p[0] + p[1]):
        top = P(x, y, box.z0 + 2)
        bot = P(x, y, 0)
        d.line([top, bot], fill=leg_color, width=width)
        d.line([(bot[0] - 1, bot[1]), (bot[0] + 2, bot[1])], fill=shade(leg_color, 0.8), width=1)


def draw_door(d, face, u0, v0, u1, v1, plate, edge, handle, vents=0, knob=None):
    d.polygon(Box.quad(face, u0, v0, u1, v1), fill=plate, outline=edge)
    # inner bevel
    du, dv = (u1 - u0) * 0.08, (v1 - v0) * 0.1
    d.line([face(u0 + du, v1 - dv), face(u1 - du, v1 - dv)], fill=shade(plate, 1.18))
    d.line([face(u0 + du, v0 + dv), face(u1 - du, v0 + dv)], fill=shade(plate, 0.8))
    for i in range(vents):
        vu = u0 + (u1 - u0) * (0.25 + 0.5 * i / max(1, vents - 1))
        d.line([face(vu, v0 + (v1 - v0) * 0.3), face(vu, v0 + (v1 - v0) * 0.7)], fill=shade(plate, 0.45), width=1)
    if handle:
        hu = u1 - (u1 - u0) * 0.18
        a, b = face(hu, v0 + (v1 - v0) * 0.35), face(hu, v0 + (v1 - v0) * 0.65)
        d.line([a, b], fill=handle, width=2)
    if knob:
        x, y = face(u1 - (u1 - u0) * 0.18, (v0 + v1) / 2)
        d.ellipse((x - 2, y - 2, x + 2, y + 2), fill=knob, outline=shade(knob, 0.6))


def draw_bar_handle(d, face, face_name, u, v_lo, v_hi, color):
    """A pull handle standing off the door on two posts, lit from the upper left."""
    # screen step pointing out of the face (south: +y, east: +x), 3 px long
    out = (-3, 1) if face_name == 'south' else (3, 1)
    lo, hi = face(u, v_lo), face(u, v_hi)
    blo, bhi = (lo[0] + out[0], lo[1] + out[1]), (hi[0] + out[0], hi[1] + out[1])
    # soft shadow on the door, below and right of the bar
    d.line([(lo[0] + 1, lo[1] + 2), (hi[0] + 1, hi[1] + 2)], fill=(20, 18, 16, 150), width=2)
    # mounting plates and posts
    for p, b in ((lo, blo), (hi, bhi)):
        d.rectangle((p[0] - 1, p[1] - 1, p[0] + 1, p[1] + 1), fill=shade(color, 0.45))
        d.line([p, b], fill=shade(color, 0.6), width=2)
    # the bar: dark core, lit edge
    d.line([blo, bhi], fill=shade(color, 0.7), width=2)
    d.line([(blo[0] - 1, blo[1]), (bhi[0] - 1, bhi[1])], fill=shade(color, 1.3))


def draw_screws(d, face, coords, color):
    for u, v in coords:
        x, y = face(u, v)
        d.point((x, y), fill=color)
        d.point((x + 1, y), fill=shade(color, 0.7))


def smoker(variant):
    v = VARIANTS[variant]
    im = Image.new('RGBA', (FW, FH))
    d = ImageDraw.Draw(im)
    box = Box(v['w'], v['d'], v['legs'], v['h'])
    metal = v['metal']
    south_c, east_c, top_c = shade(metal, 1.0), shade(metal, 0.74), shade(metal, 1.22)

    # shadow on the floor
    sh = Image.new('L', (FW, FH))
    ds = ImageDraw.Draw(sh)
    m = 0.12
    ds.polygon([P(-box.w / 2 - m, -box.d / 2 - m, 0), P(box.w / 2 + m, -box.d / 2 - m, 0),
                P(box.w / 2 + m, box.d / 2 + m, 0), P(-box.w / 2 - m, box.d / 2 + m, 0)], fill=90)
    sh = sh.filter(ImageFilter.GaussianBlur(4))
    shadow = Image.new('RGBA', (FW, FH), (0, 0, 0, 0))
    shadow.putalpha(sh)
    im.alpha_composite(shadow)
    d = ImageDraw.Draw(im)

    draw_legs(d, box, v['leg'])

    body = Image.new('RGBA', (FW, FH))
    db = ImageDraw.Draw(body)
    db.polygon(Box.quad(box.south, 0, 0, 1, 1), fill=south_c)
    db.polygon(Box.quad(box.east, 0, 0, 1, 1), fill=east_c)
    # doors are drawn into the body so they get the same grime as the rest
    for door in v['doors']:
        face = box.south if door['face'] == 'south' else box.east
        base = south_c if door['face'] == 'south' else east_c
        draw_door(db, face, *door['rect'], plate=shade(base, door.get('tone', 0.92)), edge=shade(base, 0.55),
                  handle=None, vents=door.get('vents', 0), knob=None)
    body = textured(body, 7, v['noise'])
    stains(body, box, v['stain'], 3, v['stain_amount'])
    im.alpha_composite(body)
    d = ImageDraw.Draw(im)

    # folded seams on the vertical edges and a rim at the bottom
    edge = shade(metal, 0.5)
    d.line([box.south(0, 0), box.south(0, 1)], fill=shade(metal, 1.25))
    d.line([box.south(1, 0), box.south(1, 1)], fill=shade(metal, 1.35))
    d.line([box.east(1, 0), box.east(1, 1)], fill=shade(metal, 0.55))
    d.line([box.south(0, 0), box.south(1, 0), box.east(1, 0)], fill=edge)

    # door hardware on top of the grime
    for door in v['doors']:
        face = box.south if door['face'] == 'south' else box.east
        u0, v0, u1, v1 = door['rect']
        if door.get('handle'):
            draw_bar_handle(d, face, door['face'], u1 - (u1 - u0) * 0.18,
                            v0 + (v1 - v0) * 0.33, v0 + (v1 - v0) * 0.67, v['handle'])
        if door.get('knob'):
            x, y = face(u1 - (u1 - u0) * 0.18, (v0 + v1) / 2)
            d.ellipse((x - 1, y, x + 3, y + 4), fill=(20, 18, 16, 150))
            d.ellipse((x - 2, y - 2, x + 2, y + 2), fill=v['knob'], outline=shade(v['knob'], 0.55))
            d.point((x - 1, y - 1), fill=shade(v['knob'], 1.4))

    draw_screws(d, box.south, [(0.06, 0.06), (0.94, 0.06), (0.06, 0.94), (0.94, 0.94)], shade(metal, 0.4))
    draw_screws(d, box.east, [(0.06, 0.06), (0.94, 0.06), (0.06, 0.94), (0.94, 0.94)], shade(metal, 0.35))

    # lid: a slightly larger, thin slab sitting on top (a small gap shows dark)
    lid = Box(box.w + 0.04, box.d + 0.04, box.z0 + box.h + v['lid_gap'], v['lid_h'])
    if v['lid_gap'] > 0:
        d.polygon(Box.quad(box.top, 0, 0, 1, 1), fill=(25, 22, 20, 255))
    lid_layer = Image.new('RGBA', (FW, FH))
    dl = ImageDraw.Draw(lid_layer)
    dl.polygon(Box.quad(lid.south, 0, 0, 1, 1), fill=shade(top_c, 0.85))
    dl.polygon(Box.quad(lid.east, 0, 0, 1, 1), fill=shade(top_c, 0.62))
    dl.polygon(Box.quad(lid.top, 0, 0, 1, 1), fill=top_c)
    lid_layer = textured(lid_layer, 11, v['noise'] * 0.8)
    im.alpha_composite(lid_layer)
    d = ImageDraw.Draw(im)
    d.line([lid.top(0, 0), lid.top(1, 0), lid.top(1, 1)], fill=shade(top_c, 1.15))
    d.line([lid.south(0, 0), lid.south(1, 0), lid.east(1, 0)], fill=shade(metal, 0.45))
    # knob or handle on the lid
    kx, ky = lid.top(0.5, 0.5)
    if v['lid_knob'] == 'wood':
        d.ellipse((kx - 4, ky - 6, kx + 4, ky + 1), fill=v['knob'], outline=shade(v['knob'], 0.6))
        d.ellipse((kx - 3, ky - 6, kx + 2, ky - 3), fill=shade(v['knob'], 1.25))
    elif v['lid_knob'] == 'bar':
        a, b = lid.top(0.3, 0.5), lid.top(0.7, 0.5)
        post = 4
        for x, y in (a, b):
            d.line([(x, y), (x, y - post)], fill=shade(v['handle'], 0.7), width=2)
        d.line([(a[0], a[1] - post), (b[0], b[1] - post)], fill=v['handle'], width=2)
        d.line([(a[0], a[1] - post + 2), (b[0], b[1] - post + 2)], fill=shade(v['handle'], 0.5))
    # side carry handle on the east face
    if v.get('side_handle'):
        a, b = box.east(0.3, 0.86), box.east(0.7, 0.86)
        d.line([(a[0] + 2, a[1]), (b[0] + 2, b[1])], fill=v['handle'], width=2)
    return im


GALV = (150, 156, 160)
VARIANTS = {
    # tall narrow galvanised box, food door above, fire door with vents below
    'A': dict(w=0.42, d=0.42, legs=14, h=78, metal=GALV, leg=(70, 72, 75, 255), noise=26,
              stain=(70, 45, 25), stain_amount=26, lid_gap=0, lid_h=4, lid_knob='wood',
              knob=(150, 105, 60, 255), handle=(200, 200, 205, 255), side_handle=True,
              doors=[dict(face='south', rect=(0.14, 0.42, 0.86, 0.9), handle=True),
                     dict(face='south', rect=(0.22, 0.08, 0.78, 0.3), vents=4, tone=0.8, knob=True)]),
    # squat "18-litre can" look, one big door, browner heat colour, lid slightly ajar
    'B': dict(w=0.5, d=0.5, legs=10, h=62, metal=(132, 128, 120), leg=(60, 58, 55, 255), noise=30,
              stain=(95, 55, 25), stain_amount=60, lid_gap=3, lid_h=3, lid_knob='bar',
              knob=(120, 85, 50, 255), handle=(175, 175, 178, 255), side_handle=False,
              doors=[dict(face='south', rect=(0.12, 0.3, 0.88, 0.88), handle=True),
                     dict(face='south', rect=(0.3, 0.05, 0.7, 0.2), tone=0.55)]),
    # chosen: B's shape with C's blackened steel
    'D': dict(w=0.5, d=0.5, legs=10, h=62, metal=(92, 90, 88), leg=(45, 44, 43, 255), noise=24,
              stain=(110, 70, 35), stain_amount=55, lid_gap=3, lid_h=3, lid_knob='bar',
              knob=(140, 100, 60, 255), handle=(160, 160, 165, 255), side_handle=False,
              doors=[dict(face='south', rect=(0.12, 0.3, 0.88, 0.88), handle=True, tone=1.05),
                     dict(face='south', rect=(0.3, 0.05, 0.7, 0.2), tone=0.6)]),
    # blackened steel, taller legs, doors split across two faces
    'C': dict(w=0.44, d=0.44, legs=22, h=70, metal=(92, 90, 88), leg=(45, 44, 43, 255), noise=22,
              stain=(110, 70, 35), stain_amount=30, lid_gap=0, lid_h=5, lid_knob='bar',
              knob=(140, 100, 60, 255), handle=(160, 160, 165, 255), side_handle=False,
              doors=[dict(face='south', rect=(0.14, 0.35, 0.86, 0.9), handle=True, tone=1.05),
                     dict(face='east', rect=(0.25, 0.08, 0.75, 0.3), vents=3, tone=0.85, knob=True)]),
}


def main(out_dir, names):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for n in names or VARIANTS:
        smoker(n).save(out / f'smoker_{n}.png')
        print('wrote', out / f'smoker_{n}.png')


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2:])
