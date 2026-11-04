if isClient() then return end

require "Smoker_Recipe"

-- Smoking runs here (server, or the game itself in single player), not through
-- vanilla cooking: every game minute, Cured* items in a smoker get their cooking
-- time reset (so the fire never cooks them into plain food) and, while the fire
-- is lit, gain smoking minutes kept in the item's modData. At
-- SmokerRecipe.SMOKE_MINUTES they are replaced by the Smoked* item. Smoked*
-- items left in a lit smoker keep counting and burn after BURN_MINUTES (so a
-- second batch on top of a finished one ruins the first).

SmokerRecipe.BURN_MINUTES = 120

local smokers = {}
local lastHours = nil

-- how: which hook found it ("new" = just built, "load" = loaded with the map,
-- "added" = the OnObjectAdded fallback); tools/check_logs.py reads it
local function register(obj, how)
    if smokers[obj] then return end
    smokers[obj] = true
    -- diagnostic, debug mode only (tools/check_logs.py reads these lines)
    if isDebugEnabled() then
        print("[Smoker] smoker registered (" .. tostring(how) .. ") at " .. obj:getX() .. "," .. obj:getY() .. "," .. obj:getZ())
    end
end

-- called with the IsoObject whenever an object with this sprite is built or loaded
-- (same hooks as vanilla server/Map/MapObjects/MOButcherHook.lua)
MapObjects.OnNewWithSprite(SmokerRecipe.SPRITE, function(obj) register(obj, "new") end, 5)
MapObjects.OnLoadWithSprite(SmokerRecipe.SPRITE, function(obj) register(obj, "load") end, 5)
-- fallback in case building it does not go through OnNewWithSprite (unverified)
Events.OnObjectAdded.Add(function(obj)
    if SmokerRecipe.isSmokerObject(obj) then register(obj, "added") end
end)

local function isLit(obj)
    return instanceof(obj, "IsoFireplace") and obj:isLit()
end

-- the swap keeps the food as it is (SmokerRecipe.replaceItem)
local replace = SmokerRecipe.replaceItem

local function finish(container, item, target)
    if isDebugEnabled() then print("[Smoker] smoked " .. item:getFullType()) end
    return replace(container, item, "Smoker.Smoked" .. string.sub(item:getType(), 6), function(smoked)
        -- minutes past the target count toward burning
        smoked:getModData().smokerOver = math.max(0, (item:getModData().smokerMinutes or 0) - target)
    end)
end

local function burn(container, item)
    if isDebugEnabled() then print("[Smoker] burnt " .. item:getFullType()) end
    return replace(container, item, item:getFullType(), function(burnt)
        burnt:getModData().smokerOver = item:getModData().smokerOver
        burnt:setBurnt(true)
    end)
end

-- lit: nil = the smoker's real state (tests pass true/false)
local function updateSmoker(obj, minutes, lit)
    local container = obj:getContainer()
    if not container then return end
    if lit == nil then lit = isLit(obj) end
    local items = container:getItems()
    local done, burning = {}, {}
    for i = 0, items:size() - 1 do
        local item = items:get(i)
        local target = item:getModule() == "Smoker" and SmokerRecipe.SMOKE_MINUTES[item:getType()]
        if target and not item:isCooked() then
            if item:isCookable() then
                item:setCookingTime(0)
            end
            if lit and minutes > 0 then
                local md = item:getModData()
                md.smokerMinutes = (md.smokerMinutes or 0) + minutes
                if md.smokerMinutes >= target then
                    table.insert(done, { item, target })
                end
            end
        elseif lit and minutes > 0 and item:getModule() == "Smoker"
                and string.sub(item:getType(), 1, 6) == "Smoked" and not item:isBurnt() then
            local md = item:getModData()
            md.smokerOver = (md.smokerOver or 0) + minutes
            if md.smokerOver >= SmokerRecipe.BURN_MINUTES then
                table.insert(burning, item)
            end
        end
    end
    for _, pair in ipairs(done) do
        finish(container, pair[1], pair[2])
    end
    for _, item in ipairs(burning) do
        burn(container, item)
    end
end

local function everyOneMinute()
    -- real elapsed game time, so skipped minutes while fast-forwarding still count
    local now = getGameTime():getWorldAgeHours()
    local minutes = lastHours and math.min((now - lastHours) * 60, 60) or 0
    lastHours = now
    for obj in pairs(smokers) do
        if obj:getObjectIndex() == -1 then
            smokers[obj] = nil
        else
            updateSmoker(obj, minutes)
        end
    end
end

local function processPending()
    local pending = SmokerRecipe.pendingCooked
    if #pending == 0 then return end
    SmokerRecipe.pendingCooked = {}
    for _, item in ipairs(pending) do
        SmokerRecipe.swapCooked(item)
    end
end

-- for lua/client/Smoker_Tests.lua (single player debug only)
SmokerRecipe.updateSmoker = updateSmoker
SmokerRecipe.processPending = processPending
SmokerRecipe.registerSmoker = function(obj) register(obj, "test") end
SmokerRecipe.isRegistered = function(obj) return smokers[obj] == true end

Events.EveryOneMinute.Add(everyOneMinute)
Events.OnTick.Add(processPending)
