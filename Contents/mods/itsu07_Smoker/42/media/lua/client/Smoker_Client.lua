require "Definitions/ContainerButtonIcons"
require "Smoker_Recipe"

-- Loot window button of the smoker's container (type "smoker"): smoker_icon in
-- smoker.pack, the smoker fitted in the 34x34 vanilla container icon size.
local function setContainerIcon()
    ContainerButtonIcons.smoker = getTexture("smoker_icon") or ContainerButtonIcons.oven
end

-- Thin white smoke over a lit smoker: SmokerSmoke_01_0..29 in smoker.pack (drawn
-- by tools/make_tile.py; the vanilla Smoke_01 frames are dark and a tint cannot
-- lighten them), attached the same way vanilla attaches fire to a campfire
-- (server/Camping/SCampfireGlobalObject.lua). Visual only, so every client does
-- it for itself around its own player.
SmokerRecipe.SMOKE_FRAMES = 30
-- animation frames advanced per update; vanilla fire uses 0.5
-- (IsoFireManager.FIRE_ANIM_DELAY, a Java constant that Lua cannot read)
SmokerRecipe.SMOKE_SPEED = 0.25
-- the frames already start at the gap under the lid (make_tile.py SMOKE_BASE);
-- this shifts them, in 1x tile pixels, negative is up
SmokerRecipe.SMOKE_OFFSET_Y = 0
SmokerRecipe.SMOKE_TINT = { r = 1.0, g = 1.0, b = 1.0, a = 1.0 }  -- density is in the frames

local SCAN_RADIUS = 20
local SCAN_INTERVAL_MS = 1000
local lastScan = 0

-- Index of our smoke in the object's attached animations, or nil. Checked on
-- every scan instead of remembering what we attached: the game may clear the
-- attached animations itself (fire state changes, reloads), and the fire may
-- go out on the server without this client doing anything.
local function smokeIndex(obj)
    local list = obj:getAttachedAnimSprite()
    if not list then return nil end
    for i = 0, list:size() - 1 do
        local parent = list:get(i):getParentSprite()
        local name = parent and parent:getName()
        if name and string.sub(name, 1, 11) == "SmokerSmoke" then return i end
    end
    return nil
end

local function addSmoke(obj)
    local scale = Core.getTileScale()
    local t = SmokerRecipe.SMOKE_TINT
    obj:AttachAnim("SmokerSmoke", "01", SmokerRecipe.SMOKE_FRAMES,
        SmokerRecipe.SMOKE_SPEED,
        0, SmokerRecipe.SMOKE_OFFSET_Y * scale, true, 0, false, 0.7,
        ColorInfo.new(t.r, t.g, t.b, t.a))
end

local function updateSmoke(obj)
    local lit = obj:isLit()
    local index = smokeIndex(obj)
    if lit and not index then
        -- safety net: never stack smoke if the name check ever stops matching
        -- (vanilla names the attached sprite ObjName .. AnimName, "SmokerSmoke01")
        local list = obj:getAttachedAnimSprite()
        if list and list:size() >= 4 then return end
        addSmoke(obj)
    elseif not lit and index then
        -- remove only our smoke, not anything the game attached
        obj:RemoveAttachedAnim(index)
    end
end

-- for lua/client/Smoker_Tests.lua
SmokerRecipe.hasSmoke = function(obj) return smokeIndex(obj) ~= nil end

local function scan()
    local player = getSpecificPlayer(0)
    if not player then return end
    local cell = getCell()
    local px, py, pz = math.floor(player:getX()), math.floor(player:getY()), math.floor(player:getZ())
    for x = px - SCAN_RADIUS, px + SCAN_RADIUS do
        for y = py - SCAN_RADIUS, py + SCAN_RADIUS do
            local sq = cell:getGridSquare(x, y, pz)
            if sq then
                local objects = sq:getObjects()
                for i = 0, objects:size() - 1 do
                    local obj = objects:get(i)
                    if instanceof(obj, "IsoFireplace") and SmokerRecipe.isSmokerObject(obj) then
                        updateSmoke(obj)
                    end
                end
            end
        end
    end
end

local function onTick()
    local now = getTimestampMs()
    if now - lastScan < SCAN_INTERVAL_MS then return end
    lastScan = now
    scan()
end

Events.OnGameStart.Add(setContainerIcon)
Events.OnTick.Add(onTick)
