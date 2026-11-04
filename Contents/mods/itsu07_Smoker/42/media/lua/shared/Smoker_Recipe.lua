require "Smoker_Data"

SmokerRecipe = SmokerRecipe or {}
SmokerRecipe.SPRITE = "smoker_01_0"

-- Only whole fish that the game refuses to fillet ("Too small for slicing").
-- RecipeCodeOnTest.cutFish is the same check vanilla uses in Fishing/Fish.lua.
-- The recipe input already limits items to tags[base:uncutfish].
function SmokerRecipe.isSmallFish(item, character)
    if not item then return true end
    -- bait fish has no base:uncutfish tag already; keep it out even if that changes
    if item:getType() == "BaitFish" then return false end
    -- OnTest sees every input (salt, cornmeal, egg...); only judge the fish
    if not item:hasTag(ItemTag.UNCUT_FISH) then return true end
    return not RecipeCodeOnTest.cutFish(item, nil)
end

function SmokerRecipe.isSmokerObject(obj)
    if not obj or not instanceof(obj, "IsoObject") then return false end
    local sprite = obj:getSprite()
    return sprite ~= nil and sprite:getName() == SmokerRecipe.SPRITE
end

function SmokerRecipe.isSmoker(container)
    return SmokerRecipe.isSmokerObject(container and container:getParent())
end

-- OnCooked of the Cured* meat and fish (Food.update calls it when the item
-- finishes cooking; the smoker resets their cooking time, so this only happens
-- outside it). The swap for the plain vanilla food, cooked, is queued and done
-- by lua/server/Smoker_Smoke.lua so the container is not changed while the
-- game is still updating its items.
SmokerRecipe.pendingCooked = SmokerRecipe.pendingCooked or {}

function SmokerRecipe.onCooked(item)
    if not item or isClient() then return end
    -- diagnostic, debug mode only (tools/check_logs.py reads this line)
    if isDebugEnabled() then print("[Smoker] onCooked " .. tostring(item:getFullType())) end
    table.insert(SmokerRecipe.pendingCooked, item)
end

-- Swap an item for a new one of fullType, the way vanilla ReplaceOnCooked does.
-- The new item takes over the old one's food with Food.copyFoodFromSplit (what
-- the InheritFood recipe flag does): the hunger and nutrition left in it (a
-- poor cut or a half eaten item stays that way), poison, frozen, cooked/burnt,
-- heat, and its age moved so it is just as fresh, stale or rotten. Mood values
-- stay the new item's own (the smoked food's bonus from its script): the copy
-- would take the old item's, with the stale/burnt modifiers already applied.
-- A new item is sent to every client as a whole, so its state (burnt flag,
-- modData) reaches them without relying on per-field sync.
function SmokerRecipe.replaceItem(container, item, fullType, setup)
    local new = container:AddItem(fullType)
    if not new then return nil end
    local unhappy, boredom = new:getUnhappyChangeUnmodified(), new:getBoredomChangeUnmodified()
    new:copyFoodFromSplit(item, 1)
    new:setUnhappyChange(unhappy)
    new:setBoredomChange(boredom)
    if setup then setup(new) end
    container:DoRemoveItem(item)
    if isServer() then
        sendAddItemToContainer(container, new)
        sendRemoveItemFromContainer(container, item)
    end
    return new
end

function SmokerRecipe.swapCooked(item)
    local container = item:getContainer()
    if not container or SmokerRecipe.isSmoker(container) then return end
    local fallback = SmokerRecipe.FALLBACK[item:getType()]
    if not fallback then return end
    SmokerRecipe.replaceItem(container, item, fallback, function(plain)
        plain:setCooked(true)
    end)
end
