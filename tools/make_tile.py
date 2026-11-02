"""Build the smoker's tile sheet: media/texturepacks/smoker.pack + media/smoker.tiles.

The pack also holds
- Build_Smoker: the build menu icon (48x48, like vanilla Build_CookingPit).
- smoker_icon: the smoker fitted in a 34x34 frame (vanilla container button
  icon size, Container_Campfire) for the loot window button.
- SmokerSmoke_01_0..29: a thin white smoke loop drawn here procedurally (our
  own art), attached to a lit smoker by lua/client/Smoker_Client.lua. Placed in
  the 128x256 frame so that it starts at SMOKE_BASE, the gap under the lid.

Usage: python make_tile.py <frame.png> <mod media dir>
<frame.png> is one 128x256 tile frame (Tiles2x scale). art/smoker.png is our own art
(tools/draw_smoker.py variant D). art/smoker_temp.png is a recolor of a vanilla
sprite, kept for local comparison only; never distribute it.

Formats (read from the vanilla files):
- .pack  : "PZPK", int version=1, int pages; page = str name, int count,
           int hasAlpha, entries (str name, int x,y,w,h, ox,oy, frameW,frameH),
           int pngLength, png bytes. Strings are int length + bytes.
- .tiles : "tdef", int version=1, int sheets; sheet = name\n, image\n,
           int cols, int rows, int id, int tiles; tile = int propCount,
           (key\n value\n)*.
"""
import io
import math
import random
import struct
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

SHEET = 'smoker_01'
# Properties copied from the vanilla Cooking Pit tile (camping_03_19): the game
# makes an object with these an IsoFireplace (fuel, lighting, heats its
# container) even when it is built from an entity's CraftRecipe.
PROPS = [
    ('BlocksPlacement', ''),
    ('ContainerCapacity', '7'),
    ('CustomName', 'Smoker'),
    ('IsoType', 'IsoFireplace'),
    ('Material', 'SmallMetalPlates'),
    ('Material2', 'MetalScrap'),
    ('MaterialType', 'Metal'),
    ('ScrapSize', 'Small'),
    ('container', 'smoker'),
    ('solidtrans', ''),
]


def s(b):
    b = b.encode('latin1')
    return struct.pack('<i', len(b)) + b


ICON_SIZE = 34
FRAME_FOR_ICON = 134      # frame width shrunk into the icon
SMOKE_NAME = 'SmokerSmoke_01'
SMOKE_FRAMES = 30
SMOKE_COLOR = (235, 235, 230)
SMOKE_ALPHA = 150         # densest point (0-255)
# where the smoke starts in the 128x256 frame: the gap under the lid, front edge
# (art/smoker.png drawn by draw_smoker.py variant D)
SMOKE_BASE = (54, 154)


# centre of the smoker's box (without lid and legs) in the 128x256 frame; the
# icon puts this point in its middle, moved down by ICON_SHIFT_Y (in-game the
# button shows the icon higher than the 34x34 frame suggests)
ICON_ANCHOR = (64, 190)
ICON_SHIFT_Y = 2


def make_icon(frame):
    """The smoker at 1/4 scale (fits 34x34) with its box centred in the icon."""
    k = (ICON_SIZE - 2) / FRAME_FOR_ICON
    im = frame.resize((round(frame.width * k), round(frame.height * k)), Image.LANCZOS)
    icon = Image.new('RGBA', (ICON_SIZE, ICON_SIZE))
    ax, ay = round(ICON_ANCHOR[0] * k), round(ICON_ANCHOR[1] * k)
    icon.paste(im, (ICON_SIZE // 2 - ax, ICON_SIZE // 2 + ICON_SHIFT_Y - ay), im)
    return icon


BUILD_ICON_SIZE = 48       # vanilla build menu icons (Build_CookingPit) are 48x48


def make_build_icon(sprite):
    """Build menu icon: the whole smoker fitted in 48x48 with a 1px margin, centred."""
    side = BUILD_ICON_SIZE - 2
    k = min(side / sprite.width, side / sprite.height)
    im = sprite.resize((max(1, round(sprite.width * k)), max(1, round(sprite.height * k))), Image.LANCZOS)
    icon = Image.new('RGBA', (BUILD_ICON_SIZE, BUILD_ICON_SIZE))
    icon.paste(im, ((BUILD_ICON_SIZE - im.width) // 2, (BUILD_ICON_SIZE - im.height) // 2), im)
    return icon


def make_smoke_frames(fw, fh):
    """A looping thin wisp: soft puffs rise from the stem, sway, widen and fade."""
    rng = random.Random(42)
    puffs = [(i / 24, rng.uniform(0, 2 * math.pi), rng.uniform(0.8, 1.2)) for i in range(24)]
    (base_x, base_y), height = SMOKE_BASE, 150
    frames = []
    for f in range(SMOKE_FRAMES):
        layer = Image.new('L', (fw, fh))
        d = ImageDraw.Draw(layer)
        for start, phase, size in puffs:
            t = (start + f / SMOKE_FRAMES) % 1.0          # 0 at the stem, 1 at the top
            y = base_y - t * height
            x = base_x + math.sin(t * 5.0 + phase * 0.3) * (2 + 10 * t)
            r = (2 + 9 * t) * size
            a = SMOKE_ALPHA * (1 - t) ** 1.3 * min(1.0, t * 8)
            d.ellipse((x - r, y - r, x + r, y + r), fill=int(a))
        layer = layer.filter(ImageFilter.GaussianBlur(2.5))
        im = Image.new('RGBA', (fw, fh), SMOKE_COLOR + (0,))
        im.putalpha(layer)
        frames.append(im)
    return frames


def page(name, entries):
    """entries: list of (name, image, ox, oy, fw, fh); packed side by side in one PNG."""
    atlas = Image.new('RGBA', (sum(e[1].width for e in entries), max(e[1].height for e in entries)))
    out, x = b'', 0
    for en, im, ox, oy, fw, fh in entries:
        atlas.paste(im, (x, 0))
        out += s(en) + struct.pack('<8i', x, 0, im.width, im.height, ox, oy, fw, fh)
        x += im.width
    buf = io.BytesIO()
    atlas.save(buf, 'PNG')
    png = buf.getvalue()
    return s(name) + struct.pack('<ii', len(entries), 1) + out + struct.pack('<i', len(png)) + png


def cropped(name, im):
    box = im.getbbox()
    return (name, im.crop(box), box[0], box[1], im.width, im.height)


def main(frame_path, media):
    media = Path(media)
    frame = Image.open(frame_path).convert('RGBA')
    fw, fh = frame.size
    sprite_entry = cropped(SHEET + '_0', frame)
    w, h, ox, oy = sprite_entry[1].width, sprite_entry[1].height, sprite_entry[2], sprite_entry[3]
    icon = make_icon(frame)
    smoke = [cropped(f'{SMOKE_NAME}_{i}', im) for i, im in enumerate(make_smoke_frames(fw, fh))]

    pack = b'PZPK' + struct.pack('<ii', 1, 3)
    pack += page(SHEET, [sprite_entry])
    pack += page('smoker_ui', [('smoker_icon', icon, 0, 0, ICON_SIZE, ICON_SIZE),
                               ('Build_Smoker', make_build_icon(sprite_entry[1]), 0, 0,
                                BUILD_ICON_SIZE, BUILD_ICON_SIZE)])
    pack += page('smoker_smoke', smoke)
    (media / 'texturepacks').mkdir(parents=True, exist_ok=True)
    (media / 'texturepacks' / 'smoker.pack').write_bytes(pack)

    tiles = b'tdef' + struct.pack('<ii', 1, 1)
    tiles += (SHEET + '\n' + SHEET + '.png\n').encode('latin1')
    tiles += struct.pack('<iiii', 1, 1, 1, 1)  # cols, rows, tileset id (1-512), tiles
    tiles += struct.pack('<i', len(PROPS))
    for k, v in PROPS:
        tiles += (k + '\n' + v + '\n').encode('latin1')
    (media / 'smoker.tiles').write_bytes(tiles)
    print('sprite', w, h, 'offset', ox, oy, 'frame', fw, fh)


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
