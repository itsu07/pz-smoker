"""Static checks for the Smoker mod (runs on the PC, no game needed).

Usage: python tools\\check_mod.py
Exit code 1 if any FAIL. WARN = worth a look, INFO = for reference.

Checks
- files: mod.info (id, pack, tiledef), tile pack / tiles file, icons, folder layout, test code
  guarded by isDebugEnabled, no Japanese in Lua
- Lua: only the globals we mean to define or override, prints outside the test files
- scripts: every vanilla item / model / icon / tag / timedAction / category / evolved recipe we
  reference exists in the game; recipe callbacks and OnCooked exist in Lua; sprites in the pack
- cross references: item names in Lua, textures asked for in Lua are in the pack
- translations: valid JSON, EN and JP have the same keys, every item / recipe / tooltip /
  container title has text
- other mods (Zomboid\\mods and Workshop): same id, same tiledef number or pack name, same Lua
  file paths, same module, same globals, same translation keys
"""
import json
import os
import re
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MOD_ID = 'itsu07_Smoker'            # mod.info id and folder name (public on the Workshop)
MOD = ROOT / 'Contents' / 'mods' / MOD_ID
V42 = MOD / '42'
MEDIA = V42 / 'media'
GAME = Path(r'C:\Program Files (x86)\Steam\steamapps\common\ProjectZomboid\media')
USER_MODS = Path(os.environ.get('USERPROFILE', '')) / 'Zomboid' / 'mods'
WORKSHOP = Path(r'C:\Program Files (x86)\Steam\steamapps\workshop\content\108600')
MODULE = 'Smoker'                  # script module: item names stay Smoker.*
TILEDEF_RANGE = (100, 8189)       # mod tiledef numbers (checked in the game's class files earlier)
# globals this mod defines or deliberately replaces (Smoker_Fuel.lua wraps vanilla functions)
ALLOWED_GLOBALS = {'SmokerRecipe', 'SmokerTests', 'getCampingFuelMax', 'ISCampingMenu', 'ISBBQAddFuel'}
TEST_FILES = ('Smoker_Tests.lua', 'Smoker_ServerTests.lua')

results = {'PASS': 0, 'FAIL': 0, 'WARN': 0, 'INFO': 0}


def report(level, msg):
    results[level] += 1
    print(f'{level:4} {msg}')


def check(ok, msg, detail=''):
    report('PASS' if ok else 'FAIL', msg + ('' if ok or not detail else f'  ({detail})'))
    return ok


def read(p):
    return Path(p).read_text(encoding='utf-8-sig', errors='replace')


# ---------- parsing ----------

def parse_blocks(text, kind):
    """{name: body} for `kind name { ... }` blocks (any nesting level)."""
    out = {}
    for m in re.finditer(r'^\s*' + kind + r'\s+([A-Za-z_]\w*)\s*\{', text, re.M):
        depth, i = 1, m.end()
        while depth and i < len(text):
            depth += {'{': 1, '}': -1}.get(text[i], 0)
            i += 1
        out[m.group(1)] = text[m.end():i - 1]
    return out


def props(body):
    d = {}
    for m in re.finditer(r'^\s*([A-Za-z]\w*)\s*=\s*(.*?),?\s*$', body, re.M):
        d[m.group(1)] = m.group(2).strip().rstrip(',')
    return d


def collect_game():
    items, models, actions, tags, cats, evolved, icons, sounds = set(), set(), set(), set(), set(), set(), set(), set()
    for p in (GAME / 'scripts').rglob('*.txt'):
        t = read(p)
        items.update(re.findall(r'^\s*item\s+([A-Za-z_]\w*)\s*$', t, re.M))
        models.update(re.findall(r'^\s*model\s+([A-Za-z_]\w*)', t, re.M))
        actions.update(re.findall(r'timedAction\s*=\s*(\w+)', t))
        cats.update(re.findall(r'^\s*category\s*=\s*(\w+)', t, re.M))
        icons.update(re.findall(r'^\s*Icon\s*=\s*(\w+)', t, re.M))
        for v in re.findall(r'^\s*Tags\s*=\s*([^,\n]+)', t, re.M):
            tags.update(x.strip() for x in v.split(';'))
        for v in re.findall(r'EvolvedRecipe\s*=\s*([^,\n]+)', t):
            evolved.update(x.split(':')[0].strip() for x in v.split(';'))
    for p in (GAME / 'scripts').rglob('*sounds*.txt'):
        sounds.update(re.findall(r'^\s*sound\s+(\w+)', read(p), re.M))
    return dict(items=items, models=models, actions=actions, tags=tags, cats=cats,
                evolved=evolved, icons=icons, sounds=sounds)


def png_size(p):
    with open(p, 'rb') as f:
        head = f.read(24)
    if head[:8] != b'\x89PNG\r\n\x1a\n':
        return None
    return struct.unpack('>II', head[16:24])


def pack_names(p):
    """Texture names in a .pack file (layout as written by tools/make_tile.py:
    'PZPK' ii, then pages: str name, ii (entries, 1), entries: str name + 8 ints, i pngLen + png)."""
    names = set()
    if not p.exists():
        return names
    b = p.read_bytes()
    try:
        assert b[:4] == b'PZPK'
        pos = 12
        while pos < len(b):
            n, = struct.unpack_from('<i', b, pos); pos += 4
            names.add(b[pos:pos + n].decode('latin-1')); pos += n
            entries, _ = struct.unpack_from('<ii', b, pos); pos += 8
            for _ in range(entries):
                n, = struct.unpack_from('<i', b, pos); pos += 4
                names.add(b[pos:pos + n].decode('latin-1')); pos += n + 32
            n, = struct.unpack_from('<i', b, pos); pos += 4 + n
    except (AssertionError, struct.error):
        report('FAIL', f'{p.name}: not in the layout make_tile.py writes')
    return names


def tiles_sheets(p):
    """Sheet names in a .tiles file (text lines after the 'tdef' header)."""
    if not p.exists():
        return set()
    return {m.decode('latin-1') for m in re.findall(rb'([A-Za-z_][A-Za-z0-9_]*)\n\1\.png\n', p.read_bytes())}


def mod_info(p):
    kv = {}
    for l in read(p).splitlines():
        if '=' in l:
            k, v = l.split('=', 1)
            kv[k.strip()] = v.strip()
    return kv


# ---------- checks ----------

def check_files():
    print('\n== files ==')
    info = V42 / 'mod.info'
    kv = {}
    if check(info.exists(), 'mod.info exists'):
        kv = mod_info(info)
        for k in ('name', 'id', 'description'):
            check(bool(kv.get(k, '')), f'mod.info has {k}')
        check(kv.get('id') == MOD_ID, f'mod.info id is {MOD_ID}', kv.get('id'))
        if not kv.get('poster'):
            report('WARN', 'mod.info has no poster (shown in the mod list; optional)')
        pack = kv.get('pack', '')
        check(bool(pack) and (MEDIA / 'texturepacks' / f'{pack}.pack').exists(), f'texture pack {pack}.pack exists')
        td = kv.get('tiledef', '')
        m = re.fullmatch(r'(\w+)\s+(\d+)', td)
        if check(m is not None, 'mod.info tiledef is "<name> <number>"', td):
            name, num = m.group(1), int(m.group(2))
            check((MEDIA / f'{name}.tiles').exists(), f'tiles file {name}.tiles exists')
            check(TILEDEF_RANGE[0] <= num <= TILEDEF_RANGE[1],
                  f'tiledef number {num} is in the mod range {TILEDEF_RANGE[0]}-{TILEDEF_RANGE[1]}')
            report('INFO', f'tiledef number {num}: placed smokers are saved with sprite numbers made from it; '
                           'never change it once a world has one')
    check((MOD / 'common').is_dir(), 'common folder exists (B42 layout)')
    for f in sorted((MEDIA / 'lua').rglob('*.lua')):
        text = read(f)
        bad = [i for i, l in enumerate(text.splitlines(), 1) if any(ord(c) > 127 for c in l)]
        check(not bad, f'{f.name}: ASCII only (Kahlua breaks Japanese literals)', f'lines {bad[:5]}')
        if f.name in TEST_FILES:
            code = [l for l in text.splitlines() if l.strip() and not l.strip().startswith('--')][:3]
            check(any('isDebugEnabled' in l and 'return' in l for l in code),
                  f'{f.name}: returns early outside debug mode', ' | '.join(code))
    for p in sorted((MEDIA / 'textures').glob('Item_*.png')):
        check(png_size(p) == (32, 32), f'icon {p.name} is a 32x32 PNG', str(png_size(p)))
    return kv


def check_lua():
    print('\n== Lua ==')
    funcs = set()
    for f in sorted((MEDIA / 'lua').rglob('*.lua')):
        text = read(f)
        globals_ = []
        for l in text.splitlines():
            m = re.match(r'^(?:function\s+([A-Za-z_]\w*)\s*[.:(]|([A-Za-z_]\w*)\s*=[^=])', l)
            if m:
                name = m.group(1) or m.group(2)
                if name not in ALLOWED_GLOBALS:
                    globals_.append(name)
        check(not globals_, f'{f.name}: no globals other than {sorted(ALLOWED_GLOBALS)}', ', '.join(globals_))
        if f.name not in TEST_FILES:
            # the [Smoker] diagnostic lines must only print in debug mode (tools/check_logs.py reads them)
            src = text.splitlines()
            prints = [i for i, l in enumerate(src, 1)
                      if 'print(' in l and 'isDebugEnabled' not in l and 'isDebugEnabled' not in src[i - 2]]
            check(not prints, f'{f.name}: every print() is guarded by isDebugEnabled()', f'lines {prints}')
        funcs.update(re.findall(r'function\s+SmokerRecipe\.(\w+)', text))
        funcs.update(re.findall(r'^SmokerRecipe\.(\w+)\s*=\s*function', text, re.M))
    return funcs


def check_scripts(game, funcs, kv):
    print('\n== scripts ==')
    items_txt = read(MEDIA / 'scripts/Smoker_items.txt')
    rec_txt = read(MEDIA / 'scripts/Smoker_recipes.txt')
    ent_txt = read(MEDIA / 'scripts/Smoker_entity.txt')
    mod_txt = read(MEDIA / 'scripts/Smoker_models.txt')
    for name, t in (('items', items_txt), ('recipes', rec_txt), ('entity', ent_txt), ('models', mod_txt)):
        check(t.count('{') == t.count('}'), f'{name}: braces balanced')
    check(re.search(r'^module\s+' + MODULE + r'\b', items_txt, re.M) is not None, f'items: module {MODULE}')
    items = {k: props(v) for k, v in parse_blocks(items_txt, 'item').items()}
    own_models = set()
    for name, body in parse_blocks(mod_txt, 'model').items():
        own_models.add(name)
        p = props(body)
        mesh = p.get('mesh', '')
        tex = p.get('texture', '')
        mesh_ok = any((base / (mesh + ext)).exists()
                      for base in (MEDIA / 'models_X', GAME / 'models_X', GAME / 'models')
                      for ext in ('.x', '.fbx'))
        check(mesh_ok, f'model {name}: mesh {mesh} exists (ours or vanilla)')
        check((MEDIA / 'textures' / (tex + '.png')).exists() or (GAME / 'textures' / (tex + '.png')).exists(),
              f'model {name}: texture {tex} exists (ours or vanilla)')
    recipes = parse_blocks(rec_txt, 'craftRecipe')
    own = {f'{MODULE}.{k}' for k in items}
    known = own | {f'Base.{k}' for k in game['items']}
    own_icons = {p.stem[5:] for p in (MEDIA / 'textures').glob('Item_*.png')}

    for name, p in items.items():
        icon = p.get('Icon', '')
        check(icon in own_icons or icon in game['icons'], f'item {name}: icon {icon} exists (ours or used by vanilla)')
        for k in ('StaticModel', 'WorldStaticModel'):
            if k in p:
                check(p[k] in game['models'] or p[k] in own_models, f'item {name}: {k} {p[k]} exists')
        for e in [x.split(':')[0] for x in p.get('EvolvedRecipe', '').split(';') if x]:
            check(e in game['evolved'], f'item {name}: evolved recipe {e} exists')
        for tag in [x.strip() for x in p.get('Tags', '').split(';') if x.strip()]:
            check(tag in game['tags'], f'item {name}: tag {tag} exists')
        for key in ('OnCooked', 'OnEat'):
            if key in p:
                fn = p[key].split('.', 1)[-1]
                check(fn in funcs, f'item {name}: {key} {p[key]} is defined in Lua')
        if 'ReplaceOnCooked' in p:
            check(p['ReplaceOnCooked'] in known, f'item {name}: ReplaceOnCooked {p["ReplaceOnCooked"]} exists')

    for name, body in recipes.items():
        p = props(body)
        check(p.get('timedAction') in game['actions'], f'recipe {name}: timedAction {p.get("timedAction")} exists')
        check(p.get('category') in game['cats'], f'recipe {name}: category {p.get("category")} exists')
        for tag in p.get('Tags', '').split(';'):
            check(tag.strip() in game['tags'], f'recipe {name}: tag {tag.strip()} exists')
        for key in ('OnTest', 'OnCreate'):
            if key in p:
                fn = p[key].split('.', 1)[-1]
                check(fn in funcs, f'recipe {name}: {key} {p[key]} is defined in Lua')
        for lst in re.findall(r'^\s*item\s+\d+\s+\[([^\]]+)\]', body, re.M):
            for it in lst.split(';'):
                it = it.strip()
                if it != '*':
                    check(it in known, f'recipe {name}: input {it} exists')
        for tg in re.findall(r'tags\[([^\]]+)\]', body):
            for tag in tg.split(';'):
                check(tag.strip() in game['tags'], f'recipe {name}: input tag {tag.strip()} exists')
        for it in re.findall(r'^\s*item\s+\d+\s+([A-Za-z_][\w.]*)\s*,', body, re.M):
            full = it if '.' in it else f'{MODULE}.{it}'
            check(full in known, f'recipe {name}: output {full} exists')

    # entity (the smoker itself): sprite in the tiles file, build icon in the pack, inputs exist
    tiles = tiles_sheets(MEDIA / (kv.get('tiledef', ' ').split()[0] + '.tiles'))
    pack = pack_names(MEDIA / 'texturepacks' / (kv.get('pack', '') + '.pack'))
    sprite = re.search(r'row\s*=\s*(\w+)', ent_txt)
    sheet = sprite and sprite.group(1).rsplit('_', 1)[0]
    check(sheet in tiles, 'entity sprite sheet is in the tiles file', f'{sprite and sprite.group(1)} -> {sheet} in {sorted(tiles)}')
    check(sprite is not None and sprite.group(1) in pack, 'entity sprite is in the texture pack', sprite and sprite.group(1))
    lua_sprite = re.search(r'SmokerRecipe\.SPRITE\s*=\s*"(\w+)"', read(MEDIA / 'lua/shared/Smoker_Recipe.lua'))
    check(sprite is not None and lua_sprite is not None and sprite.group(1) == lua_sprite.group(1),
          'Lua SmokerRecipe.SPRITE matches the entity sprite')
    icon = re.search(r'Icon\s*=\s*(\w+)', ent_txt)
    check(icon is not None and icon.group(1) in pack, 'entity build icon is in the texture pack', icon and icon.group(1))
    ent_recipes = parse_blocks(ent_txt, 'component')
    cr = ent_recipes.get('CraftRecipe', '')
    for lst in re.findall(r'^\s*item\s+\d+\s+\[([^\]]+)\]', cr, re.M):
        for it in lst.split(';'):
            check(it.strip() in known, f'smoker build: input {it.strip()} exists')
    for tg in re.findall(r'tags\[([^\]]+)\]', cr):
        for tag in tg.split(';'):
            check(tag.strip() in game['tags'], f'smoker build: input tag {tag.strip()} exists')
    ta = re.search(r'timedAction\s*=\s*(\w+)', cr)
    check(ta is not None and ta.group(1) in game['actions'], 'smoker build: timedAction exists', ta and ta.group(1))
    for snd in re.findall(r'=\s*(\w+),', ent_recipes.get('CraftBenchSounds', '')):
        check(snd in game['sounds'], f'smoker build: sound {snd} exists')
    tooltip = re.search(r'Tooltip\s*=\s*(\w+)', cr)
    return items, recipes, known, pack, tooltip and tooltip.group(1)


def check_crossrefs(known, pack):
    print('\n== Lua <-> scripts / pack ==')
    lua_all = '\n'.join(read(f) for f in (MEDIA / 'lua').rglob('*.lua'))
    # a quoted name followed by .. is a prefix being concatenated ("Smoker.Smoked" .. stem)
    for ref in sorted(set(re.findall(r'"((?:Smoker|Base)\.\w+)"(?!\s*\.\.)', lua_all))):
        check(ref in known, f'Lua item name {ref} exists')
    for tex in sorted(set(re.findall(r'getTexture\("(\w+)"\)', lua_all))):
        check(tex in pack, f'Lua getTexture("{tex}") is in the texture pack')
    anim = re.search(r'AttachAnim\("(\w+)",\s*"(\w+)",\s*SmokerRecipe\.SMOKE_FRAMES', lua_all)
    frames = re.search(r'SmokerRecipe\.SMOKE_FRAMES\s*=\s*(\d+)', lua_all)
    if check(anim is not None and frames is not None, 'smoke animation call found in Smoker_Client.lua'):
        missing = [i for i in range(int(frames.group(1))) if f'{anim.group(1)}_{anim.group(2)}_{i}' not in pack]
        check(not missing, f'all {frames.group(1)} smoke frames {anim.group(1)}_{anim.group(2)}_N are in the pack',
              f'missing {missing[:5]}')


def load_json(p):
    try:
        return json.loads(read(p)), None
    except Exception as e:  # noqa: BLE001
        return None, str(e)


def check_translations(items, recipes, tooltip_key):
    print('\n== translations ==')
    tr = MEDIA / 'lua/shared/Translate'
    data = {}
    for lang in ('EN', 'JP'):
        for f in sorted((tr / lang).glob('*.json')):
            d, err = load_json(f)
            check(d is not None, f'{lang}/{f.name}: valid JSON', err or '')
            data[(lang, f.name)] = d or {}
            if f.read_bytes().startswith(b'\xef\xbb\xbf'):
                report('WARN', f'{lang}/{f.name}: has a BOM (vanilla files have none)')
    en_files = {n for (l, n) in data if l == 'EN'}
    jp_files = {n for (l, n) in data if l == 'JP'}
    check(en_files == jp_files, 'EN and JP have the same translation files', f'{en_files ^ jp_files}')
    for (lang, name), d in data.items():
        if lang == 'EN':
            other = data.get(('JP', name), {})
            check(set(d) == set(other), f'{name}: EN and JP have the same keys',
                  f'EN only {sorted(set(d) - set(other))[:3]} JP only {sorted(set(other) - set(d))[:3]}')
    container = re.search(r'container\s*=\s*(\w+)', (MEDIA / 'smoker.tiles').read_bytes().decode('latin-1'))
    for lang in ('EN', 'JP'):
        names = data.get((lang, 'ItemName.json'), {})
        rec = data.get((lang, 'Recipes.json'), {})
        tips = data.get((lang, 'Tooltip.json'), {})
        ui = data.get((lang, 'IG_UI.json'), {})
        for i in items:
            check(f'{MODULE}.{i}' in names, f'{lang}: name for {i}')
        for r in recipes:
            check(r in rec, f'{lang}: recipe name for {r}')
        if tooltip_key:
            check(tooltip_key in tips, f'{lang}: smoker build tooltip {tooltip_key}')
        if container:
            check(f'IGUI_ContainerTitle_{container.group(1)}' in ui,
                  f'{lang}: container title IGUI_ContainerTitle_{container.group(1)}')
    return {k for d in data.values() for k in d}


# ---------- other mods ----------

def other_mod_infos():
    out = []
    own = V42.resolve()
    for base in (USER_MODS, WORKSHOP):
        if not base.is_dir():
            continue
        for mi in base.rglob('mod.info'):
            d = mi.parent
            try:
                r = d.resolve()
                if r == own or own in r.parents or r in own.parents:
                    continue
                # junctions / copies of this very mod (same files) are not "other" mods
                if (d / 'media' / 'scripts' / 'Smoker_items.txt').exists():
                    continue
            except OSError:
                continue
            out.append(d)
    return out


def check_other_mods(kv, our_keys):
    print('\n== other mods ==')
    our_lua = {str(p.relative_to(MEDIA)).lower() for p in (MEDIA / 'lua').rglob('*.lua')}
    our_td = kv.get('tiledef', ' ').split()
    our_num = int(our_td[1]) if len(our_td) == 2 and our_td[1].isdigit() else None
    dirs = other_mod_infos()
    report('INFO', f'{len(dirs)} other mod folders scanned (Zomboid\\mods and Workshop)')
    clashes = 0
    seen_ids = {}
    for d in dirs:
        info = mod_info(d / 'mod.info')
        mid = info.get('id', d.name)
        seen_ids.setdefault(mid, []).append(d)
        if mid == MOD_ID:
            report('FAIL', f'{d}: another mod with id {MOD_ID}')
            clashes += 1
        td = info.get('tiledef', '').split()
        if len(td) == 2 and td[1].isdigit() and our_num is not None:
            if int(td[1]) == our_num:
                report('FAIL', f'{mid}: same tiledef number {our_num} (placed objects would swap sprites)')
                clashes += 1
            else:
                report('INFO', f'{mid}: tiledef {td[0]} {td[1]}')
        if info.get('pack') and info.get('pack') == kv.get('pack'):
            report('FAIL', f'{mid}: same texture pack name {info["pack"]}')
            clashes += 1
        media = d / 'media'
        if not media.is_dir():
            continue
        for p in media.rglob('*'):
            if not p.is_file():
                continue
            rel = str(p.relative_to(media)).lower()
            if p.suffix == '.lua':
                if rel in our_lua:
                    report('FAIL', f'{mid}: same Lua file path {rel} (one replaces the other)')
                    clashes += 1
                t = read(p)
                if re.search(r'^\s*(SmokerRecipe|SmokerTests)\s*=', t, re.M):
                    report('FAIL', f'{mid}: defines a global SmokerRecipe / SmokerTests ({p.name})')
                    clashes += 1
                if 'getCampingFuelMax' in t and 'function getCampingFuelMax' in t:
                    report('WARN', f'{mid}: also replaces getCampingFuelMax ({p.name}); load order decides the fuel cap')
            elif p.suffix == '.json' and 'translate' in rel:
                d2, _ = load_json(p)
                dup = our_keys & set(d2 or {})
                if dup:
                    report('FAIL', f'{mid}: same translation keys {sorted(dup)[:3]}')
                    clashes += 1
            elif p.suffix == '.txt' and 'scripts' in rel:
                t = read(p)
                if re.search(r'^module\s+' + MODULE + r'\b', t, re.M):
                    report('FAIL', f'{mid}: also uses module {MODULE} ({p.name})')
                    clashes += 1
                for r, body in parse_blocks(t, 'craftRecipe').items():
                    if 'Smoker.' in body:
                        report('INFO', f'{mid}: recipe {r} uses our items')
    check(clashes == 0, 'no clashes with other mods')


def main():
    try:
        sys.stdout.reconfigure(errors='replace')
    except Exception:  # noqa: BLE001
        pass
    if not GAME.is_dir():
        print('game folder not found:', GAME)
        return 2
    game = collect_game()
    kv = check_files()
    funcs = check_lua()
    items, recipes, known, pack, tooltip_key = check_scripts(game, funcs, kv)
    check_crossrefs(known, pack)
    keys = check_translations(items, recipes, tooltip_key)
    check_other_mods(kv, keys)
    print(f'\n{results["PASS"]} PASS / {results["FAIL"]} FAIL / {results["WARN"]} WARN / {results["INFO"]} INFO')
    return 1 if results['FAIL'] else 0


if __name__ == '__main__':
    sys.exit(main())
