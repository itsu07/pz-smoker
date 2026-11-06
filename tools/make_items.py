"""Generate cured / smoked food items, curing recipes, the Lua lookup table
and translations.

Usage: python make_items.py [game dir]
Nutrition, icons and models are copied from the vanilla source item in
media/scripts/generated/items/food.txt, so re-run this after game updates.

Flow in game:
  raw food + salt  --(SH_Cure* recipe)-->  Smoker.Cured*  (raw, cookable)
  Cured* MINUTES in a lit smoker         -->  Smoker.Smoked*
                                             (lua/server/Smoker_Smoke.lua)
  Cured* heated anywhere else            -->  plain cooked vanilla food
                                             (SmokerRecipe.onCooked, Lua)
Every step keeps the food's own hunger, nutrition, poison and freshness
(InheritFood in the recipe, SmokerRecipe.replaceItem for the swaps).

Writes (under Contents/mods/itsu07_Smoker/42/media):
  scripts/Smoker_items.txt        module Smoker
  scripts/Smoker_recipes.txt      module Base
  lua/shared/Smoker_Data.lua      cured/smoked -> vanilla source table
  lua/shared/Translate/{EN,JP}/ItemName.json, Recipes.json, Tooltip.json
"""
import json
import re
import sys
from pathlib import Path

GAME = Path(sys.argv[1] if len(sys.argv) > 1 else
            r'C:\Program Files (x86)\Steam\steamapps\common\ProjectZomboid')
ROOT = Path(__file__).resolve().parent.parent
MEDIA = ROOT / 'Contents/mods/itsu07_Smoker/42/media'

# Minutes of lit fire in the smoker, counted by lua/server/Smoker_Smoke.lua.
# A bit under 12h so that a full load of fuel (12h cap) always finishes a run.
SMOKE_MINUTES = 690
CHEESE_MINUTES = 240

# id stem, vanilla source, EN name, JP name (smoked)
MEAT = [
    ('FishFillet', 'FishFillet', 'Fish Fillet', '魚の切身'),
    ('Pork', 'Pork', 'Pork', '豚肉'),
    ('PorkChop', 'PorkChop', 'Pork Chop', '豚肉の切り身'),
    ('Beef', 'Beef', 'Beef', '牛肉'),
    ('Steak', 'Steak', 'Steak', 'ステーキ肉'),
    ('Chicken', 'Chicken', 'Chicken Leg', '鶏もも肉'),
    ('ChickenFillet', 'ChickenFillet', 'Chicken Fillet', '鶏肉の切り身'),
    ('ChickenWings', 'ChickenWings', 'Chicken Wing', '鶏手羽'),
    ('TurkeyFillet', 'TurkeyFillet', 'Turkey Fillet', 'ターキーの切り身'),
    ('TurkeyLegs', 'TurkeyLegs', 'Turkey Leg', 'ターキーの脚'),
    ('TurkeyWings', 'TurkeyWings', 'Turkey Wing', 'ターキーの手羽'),
    ('MuttonChop', 'MuttonChop', 'Mutton Chop', '骨付ラム'),
    ('Venison', 'Venison', 'Venison', '鹿肉'),
    ('Rabbitmeat', 'Rabbitmeat', 'Rabbit Meat', 'ウサギ肉'),
    ('Smallanimalmeat', 'Smallanimalmeat', 'Rodent Meat', 'げっ歯類の肉'),
    ('Smallbirdmeat', 'Smallbirdmeat', 'Small Bird Meat', '小鳥の肉'),
]
CHEESE = [
    ('Cheese', 'Cheese', 'Cheese', 'チーズ'),
]
# Whole fish too small to fillet. These values only show for a spawned item:
# the caught fish's own (they vary by size) are inherited by the cure recipe.
SMALL_FISH = ('SmallFish', 'Bluegill', 'Small Fish', '小魚')
SMALL_FISH_VALUES = {'HungerChange': '-10.0', 'Calories': '110.0', 'Carbohydrates': '0.0',
                     'Lipids': '2.0', 'Proteins': '22.0', 'Weight': '0.25'}

WEIGHT_FACTOR = 0.8       # water lost while smoking
FRESH = {'cured': (4, 8), 'meat': (14, 21), 'cheese': (30, 45)}
# Icon tints: the game multiplies the vanilla icon by this color when drawing
# it (same mechanism as vanilla Popsicle_Melted tinting Puddle_Generic).
TINT_SMOKED = (200, 150, 105)
TINT_CURED = (235, 225, 215)


def parse_items(path):
    items = {}
    text = path.read_text(encoding='utf-8', errors='replace')
    for m in re.finditer(r'\n    item (\w+)\s*\{(.*?)\n    \}', text, re.S):
        props = {}
        for line in m.group(2).splitlines():
            line = line.strip().rstrip(',')
            if ' = ' in line:
                k, v = line.split(' = ', 1)
                props[k.strip()] = v.strip()
        items[m.group(1)] = props
    return items


def ready_evolved(s):
    """Smoked food is ready to eat: drop '|Cooked' requirements and chum bait."""
    return ';'.join(p.split('|')[0] for p in s.split(';') if p and not p.startswith('AddBaitToChum'))


def block(item_id, lines):
    body = ''.join(f'        {l},\n' for l in lines)
    return f'    item {item_id}\n    {{\n{body}    }}\n'


def food_lines(v, weight, fresh, tint, evolved):
    lines = ['DisplayCategory = Food', 'ItemType = base:food', f'Weight = {weight:.2f}',
             f'Icon = {v["Icon"]}']
    if evolved and 'EvolvedRecipe' in v:
        lines.append(f'EvolvedRecipe = {evolved(v["EvolvedRecipe"])}')
        if 'EvolvedRecipeName' in v:
            lines.append(f'EvolvedRecipeName = {v["EvolvedRecipeName"]}')
    lines.append(f'FoodType = {v.get("FoodType", "Fish")}')
    lines += [f'DaysFresh = {fresh[0]}', f'DaysTotallyRotten = {fresh[1]}']
    for k in ('HungerChange', 'Calories', 'Carbohydrates', 'Lipids', 'Proteins'):
        if k in v:
            lines.append(f'{k} = {v[k]}')
    return lines, [f'ColorRed = {tint[0]}', f'ColorGreen = {tint[1]}', f'ColorBlue = {tint[2]}']


def tail_lines(v, tags):
    lines = [f'{k} = {v[k]}' for k in ('StaticModel', 'WorldStaticModel') if k in v]
    if tags:
        lines.append(f'Tags = {tags}')
    return lines


def cured_item(stem, v, kind):
    fresh = (int(v['DaysFresh']), int(v['DaysTotallyRotten'])) if kind == 'cheese' else FRESH['cured']
    lines, tint = food_lines(v, float(v['Weight']), fresh, TINT_CURED, None)
    # Meat cooks like the raw food anywhere (the smoker keeps resetting its
    # cooking time); OnCooked swaps it for the plain vanilla food, cooked.
    # Cheese is not cookable, same as vanilla cheese.
    if kind != 'cheese':
        lines += ['IsCookable = true', f'MinutesToCook = {v["MinutesToCook"]}',
                  f'MinutesToBurn = {v["MinutesToBurn"]}', 'OnCooked = SmokerRecipe.onCooked',
                  'DangerousUncooked = true']
    lines += tint + tail_lines(v, 'base:cheese' if kind == 'cheese' else '')
    return block('Cured' + stem, lines)


def smoked_item(stem, v, kind, fixed=False):
    weight = float(v['Weight']) if fixed else float(v['Weight']) * WEIGHT_FACTOR
    lines, tint = food_lines(v, weight, FRESH[kind], TINT_SMOKED, ready_evolved)
    # better for mood than plain cooked food (vanilla cooked fish/meat: 0, plus a
    # small bonus only while hot). Hunger and nutrition are the prep's own, copied
    # by the smoker (SmokerRecipe.replaceItem); these mood values are kept.
    unhappy = -10 if kind == 'meat' else -15
    lines += [f'UnhappyChange = {unhappy}', 'BoredomChange = -10']
    tags = 'base:cheese' if kind == 'cheese' else ('base:fishmeat' if 'fishmeat' in v.get('Tags', '') or fixed else '')
    lines += tint + tail_lines(v, tags)
    return block('Smoked' + stem, lines)


def cure_recipe(stem, inp, kind, extra=''):
    salt = '' if kind == 'cheese' else '            item 1 [Base.Salt;Base.SeasoningSalt],\n'
    return (f'    craftRecipe SH_Cure{stem}\n    {{\n'
            f'        timedAction = SliceMeat_Surface,\n'
            f'        time = 80,\n'
            f'        Tags = AnySurfaceCraft;Cooking,\n'
            f'        category = Cooking,\n'
            f'        xpAward = Cooking:3,\n'
            f'{extra}'
            f'        inputs\n        {{\n'
            # InheritFood: the prep keeps the input's hunger, nutrition, poison
            # and freshness (Food.copyFoodFromSplit), not the script's full values.
            # IsUncookedFoodItem: raw only; it would also copy the cooked/burnt
            # state, and a cooked prep never smokes, it only burns
            f'            item 1 {inp} flags[IsUncookedFoodItem;InheritFood;ItemCount],\n'
            f'{salt}'
            f'        }}\n'
            f'        outputs\n        {{\n'
            f'            item 1 Smoker.Cured{stem},\n'
            f'        }}\n    }}\n\n')


# Cornmeal fried whole small fish (Southern US style): a small fish that cannot
# be filleted, scored and dredged in egg, cornmeal and garlic, fried in oil.
# Art: tools/draw_fish.py (icons + a crust texture for the vanilla small fish
# mesh, see scripts/Smoker_models.txt).
FRY_ITEMS = """    item BreadedSmallFish
    {
        DisplayCategory = Food,
        ItemType = base:food,
        Weight = 0.3,
        Icon = SmokerBreadedFish,
        FoodType = Fish,
        DangerousUncooked = true,
        BadInMicrowave = true,
        IsCookable = true,
        MinutesToCook = 15,
        MinutesToBurn = 35,
        ReplaceOnCooked = Smoker.FriedSmallFish,
        DaysFresh = 2,
        DaysTotallyRotten = 4,
        HungerChange = -15,
        Calories = 200,
        Carbohydrates = 14,
        Lipids = 6,
        Proteins = 27,
        CookingSound = FryingFood,
        StaticModel = SmokerBreadedFish_Ground,
        WorldStaticModel = SmokerBreadedFish_Ground,
    }

    item FriedSmallFish
    {
        DisplayCategory = Food,
        ItemType = base:food,
        Weight = 0.3,
        Icon = SmokerFriedFish,
        EvolvedRecipe = Sandwich:5;Burger:10;Salad:10;Rice:15;Pasta:15;Burrito:10;Taco:5,
        EvolvedRecipeName = Fish,
        FoodType = Fish,
        GoodHot = true,
        BadInMicrowave = true,
        IsCookable = true,
        MinutesToCook = 1,
        MinutesToBurn = 25,
        DaysFresh = 2,
        DaysTotallyRotten = 4,
        HungerChange = -15,
        Calories = 270,
        Carbohydrates = 14,
        Lipids = 16,
        Proteins = 27,
        UnhappyChange = -5,
        BoredomChange = -10,
        CookingSound = FryingFood,
        StaticModel = SmokerFriedFish_Ground,
        WorldStaticModel = SmokerFriedFish_Ground,
        Tags = base:hidecooked;base:fishmeat,
    }
"""

FRY_RECIPE = """    craftRecipe SH_BreadSmallFish
    {
        timedAction = MixingBowl,
        time = 100,
        Tags = AnySurfaceCraft;Cooking,
        category = Cooking,
        xpAward = Cooking:5,
        OnTest = SmokerRecipe.isSmallFish,
        inputs
        {
            item 1 tags[base:uncutfish] flags[InheritFoodAge;ItemCount],
            item 2 [Base.Cornmeal2],
            item 1 tags[base:egg] flags[IsUncookedFoodItem;ItemCount],
            item 1 [Base.Garlic;Base.PowderedGarlic;Base.WildGarlic2;Base.WildGarlicDried],
            item 3 [Base.OilVegetable;Base.OilOlive;Base.Lard],
        }
        outputs
        {
            item 1 Smoker.BreadedSmallFish,
        }
    }

"""

FRY_MODELS = """module Smoker
{
    model SmokerBreadedFish_Ground
    {
        mesh = WorldItems/Fish_Bluegill_Sunfish,
        texture = WorldItems/SmokerBreadedFish,
        scale = 0.195,
        attachment Bip01_Prop2
        {
            offset = -0.0302 0.0671 0.0232,
            rotate = 46.6017 -51.107 -143.5337,
            scale = 0.5358,
        }
    }

    model SmokerFriedFish_Ground
    {
        mesh = WorldItems/Fish_Bluegill_Sunfish,
        texture = WorldItems/SmokerFriedFish,
        scale = 0.195,
        attachment Bip01_Prop2
        {
            offset = -0.0302 0.0671 0.0232,
            rotate = 46.6017 -51.107 -143.5337,
            scale = 0.5358,
        }
    }
}
"""


def main():
    food = parse_items(GAME / 'media/scripts/generated/items/food.txt')
    items, recipes, lua_rows, minutes_rows = [], [], [], []
    names = {'EN': {}, 'JP': {}}
    recs = {'EN': {}, 'JP': {}}

    def add(stem, src, en, jp, kind, inp=None, values=None, extra=''):
        v = dict(food[src])
        if values:
            v.update(values)
        items.append(cured_item(stem, v, kind))
        items.append(smoked_item(stem, v, kind, fixed=bool(values)))
        recipes.append(cure_recipe(stem, inp or f'[Base.{src}]', kind, extra))
        lua_rows.append(f'    Cured{stem} = "Base.{src}",')
        minutes_rows.append(f'    Cured{stem} = {CHEESE_MINUTES if kind == "cheese" else SMOKE_MINUTES},')
        names['EN'][f'Smoker.Cured{stem}'] = f'{en} (Ready to Smoke)'
        names['JP'][f'Smoker.Cured{stem}'] = f'{jp}（燻製の仕込み）'
        names['EN'][f'Smoker.Smoked{stem}'] = f'Smoked {en}'
        names['JP'][f'Smoker.Smoked{stem}'] = ('スモーク' + jp) if kind == 'cheese' else f'{jp}の燻製'
        recs['EN'][f'SH_Cure{stem}'] = f'Prepare {en} for Smoking'
        recs['JP'][f'SH_Cure{stem}'] = f'{jp}を燻製用に仕込む'

    for stem, src, en, jp in MEAT:
        add(stem, src, en, jp, 'meat')
    for stem, src, en, jp in CHEESE:
        add(stem, src, en, jp, 'cheese')
    stem, src, en, jp = SMALL_FISH
    add(stem, src, en, jp, 'meat', inp='tags[base:uncutfish]', values=SMALL_FISH_VALUES,
        extra='        OnTest = SmokerRecipe.isSmallFish,\n')
    # a cooked small fish outside the smoker falls back to the source species
    lua_rows[-1] = '    CuredSmallFish = "Base.Bluegill",'

    items.append(FRY_ITEMS)
    recipes.append(FRY_RECIPE)
    names['EN']['Smoker.BreadedSmallFish'] = 'Cornmeal Breaded Small Fish'
    names['JP']['Smoker.BreadedSmallFish'] = '衣を付けた小魚'
    names['EN']['Smoker.FriedSmallFish'] = 'Cornmeal Fried Small Fish'
    names['JP']['Smoker.FriedSmallFish'] = '小魚のコーンミール揚げ'
    recs['EN']['SH_BreadSmallFish'] = 'Bread Small Fish in Cornmeal'
    recs['JP']['SH_BreadSmallFish'] = '小魚にコーンミールの衣を付ける'
    (MEDIA / 'scripts/Smoker_models.txt').write_text(FRY_MODELS, encoding='utf-8')

    (MEDIA / 'scripts/Smoker_items.txt').write_text(
        'module Smoker\n{\n    imports\n    {\n        Base\n    }\n\n' + '\n'.join(items) + '}\n',
        encoding='utf-8')
    (MEDIA / 'scripts/Smoker_recipes.txt').write_text(
        'module Base\n{\n' + ''.join(recipes).rstrip('\n') + '\n}\n', encoding='utf-8')
    (MEDIA / 'lua/shared/Smoker_Data.lua').write_text(
        '-- Generated by tools/make_items.py\n'
        '-- Cured item type -> vanilla food it falls back to when cooked outside the smoker.\n'
        'SmokerRecipe = SmokerRecipe or {}\nSmokerRecipe.FALLBACK = {\n' + '\n'.join(lua_rows) + '\n}\n'
        '-- Cured item type -> minutes of lit fire in the smoker to become Smoked.\n'
        'SmokerRecipe.SMOKE_MINUTES = {\n' + '\n'.join(minutes_rows) + '\n}\n',
        encoding='utf-8')

    recs['EN']['Smoker'] = 'Smoker'
    recs['JP']['Smoker'] = '燻製器'
    tips = {
        'EN': {'Tooltip_craft_smokerDesc': 'Add fuel and light it like a campfire. Food prepared for smoking (salt-cured meat or fish, or cheese) turns into smoked food after about 11.5 hours of fire (cheese: 4 hours). It holds up to 12 hours of fuel, so one load lasts a whole run. Smoked food left in the burning smoker for 2 more hours gets burnt.<br>Smoked food keeps for weeks and is ready to eat. Heated anywhere else, prepared meat or fish just gets cooked.'},
        'JP': {'Tooltip_craft_smokerDesc': '焚き火と同じように燃料を入れて火をつけます。燻製の仕込み（塩をした肉や魚、チーズ）を入れて火を約11時間半（チーズは4時間）保つと燻製になります。燃料は12時間分まで入るので、一度入れれば最後までもちます。燻製になった後も火の中に2時間以上置くと焦げます。<br>燻製は数週間もち、そのまま食べられます。肉や魚の仕込みは、燻製器以外で加熱すると普通に焼けるだけです。'},
    }
    # loot window title of the smoker's container (container type "smoker")
    ui = {'EN': {'IGUI_ContainerTitle_smoker': 'Smoker'}, 'JP': {'IGUI_ContainerTitle_smoker': '燻製器'}}
    # name of the placed smoker (tile CustomName) when picking it up / disassembling
    movs = {'EN': {'Smoker': 'Smoker'}, 'JP': {'Smoker': '燻製器'}}
    for lang in ('EN', 'JP'):
        d = MEDIA / 'lua/shared/Translate' / lang
        d.mkdir(parents=True, exist_ok=True)
        for fname, obj in (('ItemName.json', names[lang]), ('Recipes.json', recs[lang]), ('Tooltip.json', tips[lang]),
                           ('IG_UI.json', ui[lang]), ('Moveables.json', movs[lang])):
            (d / fname).write_text(json.dumps(obj, ensure_ascii=False, indent=4) + '\n', encoding='utf-8')
    print(len(items), 'items,', len(recipes), 'recipes')


if __name__ == '__main__':
    main()
