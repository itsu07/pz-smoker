"""Draw the cornmeal fried small fish art procedurally (our own art).

Usage: python draw_fish.py <mod media dir> [preview.png]
Writes
- textures/Item_SmokerBreadedFish.png, textures/Item_SmokerFriedFish.png:
  32x32 inventory icons. A whole panfish: head and tail bare (skin only), the
  scored body in a patchy cornmeal crust with paprika specks, skin showing
  through the gaps.
- textures/WorldItems/SmokerBreadedFish.png, .../SmokerFriedFish.png: 64x64
  textures for the vanilla small fish mesh (WorldItems/Fish_Bluegill_Sunfish),
  laid out like that mesh's UVs: head at the top, body in the middle, tail at
  the bottom, fins on both sides.
"""
import random
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

# per state: skin (bare head/tail/gaps), dark skin (fins, bars), crust,
# crust shadow, crust highlight, outline
STYLES = {
    'Breaded': dict(skin=(128, 136, 112), skin_dark=(88, 96, 78), crust=(226, 206, 142),
                    crust_dark=(196, 172, 108), crust_light=(244, 230, 182), outline=(58, 62, 48),
                    eye=(30, 30, 26)),
    'Fried': dict(skin=(150, 106, 62), skin_dark=(96, 60, 30), crust=(212, 148, 58),
                  crust_dark=(160, 98, 34), crust_light=(240, 190, 100), outline=(62, 34, 14),
                  eye=(200, 190, 170)),
}
PAPRIKA = [(176, 48, 28), (150, 36, 22), (196, 70, 36)]


def blobs(size, seed, coverage, blur):
    """Irregular patch mask (255 = crust) covering about `coverage` of the area."""
    rng = random.Random(seed)
    w, h = size
    noise = Image.new('L', (w, h))
    px = noise.load()
    for y in range(h):
        for x in range(w):
            px[x, y] = rng.randint(0, 255)
    noise = noise.filter(ImageFilter.GaussianBlur(blur))
    hist = noise.histogram()
    target, acc, cut = w * h * (1 - coverage), 0, 0
    for v, n in enumerate(hist):
        acc += n
        if acc >= target:
            cut = v
            break
    return noise.point(lambda v: 255 if v > cut else 0)


def speckle(im, mask, colors, seed, density):
    rng = random.Random(seed)
    px, mk = im.load(), mask.load()
    w, h = im.size
    for y in range(h):
        for x in range(w):
            if mk[x, y] and rng.random() < density:
                px[x, y] = rng.choice(colors) + (255,)


def crust_layer(size, st, seed, coverage, blur, speck_density, paprika_density):
    """Crust colour with crumbs and paprika, alpha = patchy coverage mask."""
    crust = Image.new('RGBA', size, st['crust'] + (255,))
    full = Image.new('L', size, 255)
    speckle(crust, full, [st['crust_dark'], st['crust_light']], seed, speck_density)
    speckle(crust, full, PAPRIKA, seed + 1, paprika_density)
    mask = blobs(size, seed + 2, coverage, blur)
    crust.putalpha(mask)
    return crust, mask


# ---- icon ------------------------------------------------------------------

BODY = (4, 9, 24, 25)                     # ellipse of the body
TAIL = [(22, 17), (30, 9), (28, 17), (30, 26)]
DORSAL = [(9, 10), (13, 6), (19, 6), (22, 10)]
BELLY = [(11, 23), (15, 28), (19, 23)]
HEAD_X = 10                               # the head is left of this


def icon(style, seed):
    st = STYLES[style]
    shape = Image.new('L', (32, 32))
    ds = ImageDraw.Draw(shape)
    ds.ellipse(BODY, fill=255)
    for poly in (TAIL, DORSAL, BELLY):
        ds.polygon(poly, fill=255)

    im = Image.new('RGBA', (32, 32))
    d = ImageDraw.Draw(im)
    # bare fish first: skin, darker fins/tail with rays, faint bars on the body
    d.ellipse(BODY, fill=st['skin'] + (255,))
    for poly in (TAIL, DORSAL, BELLY):
        d.polygon(poly, fill=st['skin_dark'] + (255,))
    for y in (11, 14, 20, 23):
        d.line([(28, 17), (30, y + (0 if y < 17 else 2))], fill=st['skin'] + (255,))
    for x in (12, 16, 20):
        d.line([(x, 11), (x - 1, 22)], fill=st['skin_dark'] + (255,))
    # head: gill arc, mouth and a small eye, no crust
    d.arc((3, 11, 13, 23), 300, 60, fill=st['skin_dark'] + (255,))
    d.point((4, 17), fill=st['outline'] + (255,))
    d.point((6, 14), fill=st['eye'] + (255,))

    # patchy crust on the body only (not on head, fins or tail)
    crust, _ = crust_layer((32, 32), st, seed, 0.68, 0.8, 0.3, 0.06)
    body_only = Image.new('L', (32, 32))
    ImageDraw.Draw(body_only).ellipse(BODY, fill=255)
    ImageDraw.Draw(body_only).rectangle((0, 0, HEAD_X - 1, 31), fill=0)
    crust.putalpha(ImageChops.multiply(crust.split()[3], body_only))
    im.alpha_composite(crust)
    d = ImageDraw.Draw(im)
    # score cuts show through the crust
    for x in (13, 17, 21):
        for y in range(11, 23):
            if (x * 7 + y * 3) % 5:          # broken lines: the crust covers parts of the cuts
                d.point((x - (y - 11) // 9, y), fill=st['crust_dark'] + (255,))
    # light from the upper left
    d.arc((5, 10, 22, 22), 200, 260, fill=st['crust_light'] + (255,))

    edge = shape.filter(ImageFilter.MaxFilter(3))
    out = Image.new('RGBA', (32, 32))
    out.paste(Image.new('RGBA', (32, 32), st['outline'] + (255,)), (0, 0), edge)
    out.alpha_composite(Image.composite(im, Image.new('RGBA', (32, 32)), shape))
    return out


# ---- model texture ---------------------------------------------------------

def model_texture(style, seed):
    """64x64 for the small fish mesh: head rows 0-14, body 14-50, tail 50-64,
    fins along both sides. Bare skin on head, fins and tail."""
    st = STYLES[style]
    im = Image.new('RGBA', (64, 64), st['skin'] + (255,))
    full = Image.new('L', (64, 64), 255)
    speckle(im, full, [st['skin_dark']], seed, 0.12)
    d = ImageDraw.Draw(im)
    # fins (sides) and tail (bottom) darker with rays
    fin = Image.new('L', (64, 64))
    df = ImageDraw.Draw(fin)
    df.ellipse((-8, 12, 14, 44), fill=170)
    df.ellipse((50, 12, 72, 44), fill=170)
    df.rectangle((0, 52, 64, 64), fill=170)
    fin = fin.filter(ImageFilter.GaussianBlur(2))
    shade = Image.new('RGBA', (64, 64), st['skin_dark'] + (0,))
    shade.putalpha(fin)
    im.alpha_composite(shade)
    d = ImageDraw.Draw(im)
    for x in range(2, 64, 4):
        d.line([(x, 54), (x + 1, 63)], fill=st['skin'] + (255,))
    # head: a small, cooked-looking eye (no big white ring) and the gill line
    d.arc((18, -6, 46, 16), 20, 160, fill=st['skin_dark'] + (255,))
    d.ellipse((30, 6, 33, 9), fill=st['eye'] + (255,))
    d.point((31, 7), fill=st['skin_dark'] + (255,))

    # patchy crust over the body band only
    crust, _ = crust_layer((64, 64), st, seed, 0.66, 1.4, 0.35, 0.05)
    band = Image.new('L', (64, 64))
    ImageDraw.Draw(band).ellipse((8, 13, 56, 52), fill=255)
    band = band.filter(ImageFilter.GaussianBlur(2.5))
    crust.putalpha(ImageChops.multiply(crust.split()[3], band))
    im.alpha_composite(crust)
    d = ImageDraw.Draw(im)
    # score cuts across the body
    rng = random.Random(seed + 5)
    for y in (23, 30, 37, 44):
        for x in range(18, 47):
            if rng.random() < 0.7:
                yy = y + (x - 18) // 16
                d.point((x, yy), fill=st['outline'] + (255,))
                d.point((x, yy - 1), fill=st['crust_light'] + (255,))
    return im.convert('RGB')


def preview(media, out):
    icons = [Image.open(media / f'textures/Item_Smoker{s}Fish.png') for s in STYLES]
    tex = [Image.open(media / f'textures/WorldItems/Smoker{s}Fish.png') for s in STYLES]
    sheet = Image.new('RGBA', (36 * 2 + 70 * 2, 70), (60, 60, 60, 255))
    for i, im in enumerate(icons):
        sheet.alpha_composite(im, (2 + i * 36, 2))
    for i, im in enumerate(tex):
        sheet.paste(im, (76 + i * 68, 3))
    sheet.resize((sheet.width * 4, sheet.height * 4), Image.NEAREST).save(out)


def main(media, preview_path=None):
    media = Path(media)
    (media / 'textures/WorldItems').mkdir(parents=True, exist_ok=True)
    for i, style in enumerate(STYLES):
        icon(style, 10 + i).save(media / f'textures/Item_Smoker{style}Fish.png')
        model_texture(style, 20 + i).save(media / f'textures/WorldItems/Smoker{style}Fish.png')
    if preview_path:
        preview(media, preview_path)
    print('wrote', ', '.join(STYLES))


if __name__ == '__main__':
    main(*sys.argv[1:3])
