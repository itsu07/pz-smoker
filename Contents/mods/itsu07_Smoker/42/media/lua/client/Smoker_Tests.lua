-- Debug-mode self test. Right-click a smoker > "Smoker: run tests".
-- Single player only: it calls the server-side smoking code directly
-- (lua/server/Smoker_Smoke.lua, Smoker_Fuel.lua) and feeds it game minutes, so
-- no real waiting. Results go to console.txt as "[SmokerTest] PASS/FAIL ...".
-- Test items are put in the smoker / player inventory and removed afterwards.
if not isDebugEnabled() then return end

require "Smoker_Recipe"

SmokerTests = {}

local results

local function check(name, ok, detail)
    table.insert(results, { name = name, ok = ok and true or false })
    print("[SmokerTest] " .. (ok and "PASS " or "FAIL ") .. name .. (detail and ("  (" .. tostring(detail) .. ")") or ""))
end

local function find(container, fullType)
    local items = container:getItems()
    for i = 0, items:size() - 1 do
        local item = items:get(i)
        if item:getFullType() == fullType then return item end
    end
    return nil
end

local function remove(container, item)
    if item and item:getContainer() == container then
        container:DoRemoveItem(item)
    end
end

-- 1. every item, recipe and model the mod defines is loaded and named
local function testDefinitions()
    local sm = getScriptManager()
    for cured, minutes in pairs(SmokerRecipe.SMOKE_MINUTES) do
        local stem = string.sub(cured, 6)
        local c, s = sm:FindItem("Smoker." .. cured), sm:FindItem("Smoker.Smoked" .. stem)
        check("item Smoker." .. cured, c ~= nil)
        check("item Smoker.Smoked" .. stem, s ~= nil)
        if c then
            check("name of " .. cured .. " is translated", c:getDisplayName() ~= cured, c:getDisplayName())
        end
        check("recipe SH_Cure" .. stem, sm:getCraftRecipe("SH_Cure" .. stem) ~= nil)
        check("fallback for " .. cured, SmokerRecipe.FALLBACK[cured] ~= nil)
    end
    for _, t in ipairs({ "Smoker.BreadedSmallFish", "Smoker.FriedSmallFish" }) do
        local it = sm:FindItem(t)
        check("item " .. t, it ~= nil)
        if it then check("name of " .. t .. " is translated", it:getDisplayName() ~= string.sub(t, 8), it:getDisplayName()) end
    end
    check("recipe SH_BreadSmallFish", sm:getCraftRecipe("SH_BreadSmallFish") ~= nil)
    check("texture smoker_icon", getTexture("smoker_icon") ~= nil)
    check("texture SmokerSmoke_01_0", getTexture("SmokerSmoke_01_0") ~= nil)
    -- loose icon files load by path (media/textures/Item_<Icon>.png)
    for _, n in ipairs({ "Item_SmokerBreadedFish", "Item_SmokerFriedFish" }) do
        check("texture " .. n, getTexture("media/textures/" .. n .. ".png") ~= nil)
    end
end

-- 2. the small fish check used by the cure and breading recipes
local function testSmallFish()
    local small = instanceItem("Base.Bluegill")
    small:setActualWeight(0.4)
    check("small bluegill (0.4) is accepted", SmokerRecipe.isSmallFish(small, nil))
    local big = instanceItem("Base.Bluegill")
    big:setActualWeight(2.0)
    check("big bluegill (2.0) is refused", not SmokerRecipe.isSmallFish(big, nil))
    check("bait fish is refused", not SmokerRecipe.isSmallFish(instanceItem("Base.BaitFish"), nil))
    check("cornmeal passes (not a fish)", SmokerRecipe.isSmallFish(instanceItem("Base.Cornmeal2"), nil))
    check("egg passes (not a fish)", SmokerRecipe.isSmallFish(instanceItem("Base.Egg"), nil))
    check("salt passes (not a fish)", SmokerRecipe.isSmallFish(instanceItem("Base.Salt"), nil))
end

-- 3. smoking, burning and the lit/unlit rule, with simulated minutes
local function testSmoking(smoker)
    local container = smoker:getContainer()
    local update = SmokerRecipe.updateSmoker
    -- the simulated minutes apply to everything inside, so keep real food out
    local items = container:getItems()
    for i = 0, items:size() - 1 do
        if items:get(i):getModule() == "Smoker" then
            check("smoker is empty of prep/smoked food (take it out and run again)", false, items:get(i):getFullType())
            return
        end
    end
    local pork = container:AddItem("Smoker.CuredPork")
    local cheese = container:AddItem("Smoker.CuredCheese")
    check("test items fit in the smoker", pork ~= nil and cheese ~= nil)
    if not (pork and cheese) then return end
    local porkTarget = SmokerRecipe.SMOKE_MINUTES.CuredPork
    local cheeseTarget = SmokerRecipe.SMOKE_MINUTES.CuredCheese

    pork:setCookingTime(30)
    update(smoker, 0, false)
    check("fire heat does not cook prep (cooking time reset)", pork:getCookingTime() == 0, pork:getCookingTime())

    update(smoker, 600, false)
    check("unlit smoker does not smoke", (pork:getModData().smokerMinutes or 0) == 0)

    update(smoker, cheeseTarget - 1, true)
    check("cheese not done 1 min early", find(container, "Smoker.SmokedCheese") == nil)
    update(smoker, 1, true)
    local smokedCheese = find(container, "Smoker.SmokedCheese")
    check("cheese smoked at " .. cheeseTarget .. " min", smokedCheese ~= nil and find(container, "Smoker.CuredCheese") == nil)

    update(smoker, porkTarget - cheeseTarget - 1, true)
    check("pork not done 1 min early", find(container, "Smoker.SmokedPork") == nil)
    update(smoker, 1, true)
    local smokedPork = find(container, "Smoker.SmokedPork")
    check("pork smoked at " .. porkTarget .. " min", smokedPork ~= nil and find(container, "Smoker.CuredPork") == nil)
    if not smokedPork then
        remove(container, find(container, "Smoker.SmokedCheese")); remove(container, find(container, "Smoker.CuredPork"))
        return
    end
    -- burning replaces the item (so clients get it whole): look items up again
    local function porkNow() return find(container, "Smoker.SmokedPork") end
    local function burntNow() local p = porkNow(); return p ~= nil and p:isBurnt() end
    check("smoked pork is not burnt yet", not burntNow())

    update(smoker, SmokerRecipe.BURN_MINUTES * 3, false)
    check("unlit smoker does not burn smoked food", not burntNow())
    update(smoker, SmokerRecipe.BURN_MINUTES - 1, true)
    check("smoked pork not burnt 1 min early", not burntNow())
    update(smoker, 1, true)
    check("smoked pork burnt after " .. SmokerRecipe.BURN_MINUTES .. " more min", burntNow())
    check("burnt pork is a new item (sent whole to clients)", porkNow() ~= smokedPork)
    local cheeseNow = find(container, "Smoker.SmokedCheese")
    check("smoked cheese (left in longer) burnt too", cheeseNow ~= nil and cheeseNow:isBurnt())
    local burntItem = porkNow()
    update(smoker, SmokerRecipe.BURN_MINUTES * 2, true)
    check("burnt food is not replaced again", porkNow() == burntItem and burntNow())

    remove(container, porkNow())
    remove(container, find(container, "Smoker.SmokedCheese"))
end

-- 4. fuel cap: 12h for the smoker only
local function testFuel(smoker)
    local base = getSandboxOptions():getOptionByName("MaximumFireFuelHours"):getValue() * 60
    check("normal fire keeps the sandbox cap", getCampingFuelMax() == base, getCampingFuelMax())
    local inSmoker = SmokerRecipe.withSmoker(smoker, getCampingFuelMax)
    local want = math.max(base, SmokerRecipe.FUEL_MAX_HOURS * 60)
    check("smoker cap is " .. want .. " min", inSmoker == want, inSmoker)
    check("cap is back to normal afterwards", getCampingFuelMax() == base)
end

-- 5. prep cooked outside the smoker becomes plain cooked food
local function testOutsideCooking(player)
    -- the player may carry real pork / prep: only look at what this test adds
    local inv = player:getInventory()
    local before = {}
    local items = inv:getItems()
    for i = 0, items:size() - 1 do before[items:get(i):getID()] = true end
    local cured = inv:AddItem("Smoker.CuredPork")
    SmokerRecipe.onCooked(cured)
    SmokerRecipe.processPending()
    local plain = nil
    items = inv:getItems()
    for i = 0, items:size() - 1 do
        local it = items:get(i)
        if not before[it:getID()] and it:getFullType() == "Base.Pork" then plain = it end
    end
    check("cured pork cooked outside -> plain pork", plain ~= nil and cured:getContainer() ~= inv)
    check("plain pork is cooked", plain ~= nil and plain:isCooked())
    remove(inv, plain)
    remove(inv, cured)
end

local function run(player, smoker)
    results = {}
    print("[SmokerTest] ---- start ----")
    if isClient() then
        print("[SmokerTest] multiplayer client: only the checks that need no server run")
    end
    local tests = {
        { "definitions", function() testDefinitions() end },
        { "small fish", function() testSmallFish() end },
    }
    if not isClient() then
        table.insert(tests, { "smoking", function() testSmoking(smoker) end })
        table.insert(tests, { "fuel", function() testFuel(smoker) end })
        table.insert(tests, { "outside cooking", function() testOutsideCooking(player) end })
    end
    for _, t in ipairs(tests) do
        local ok, err = pcall(t[2])
        if not ok then check(t[1] .. " (error)", false, err) end
    end
    local failed = 0
    for _, r in ipairs(results) do
        if not r.ok then failed = failed + 1 end
    end
    local summary = "[SmokerTest] ---- done: " .. (#results - failed) .. "/" .. #results .. " passed ----"
    print(summary)
    player:Say(string.sub(summary, 14))
end

local function findSmoker(worldobjects)
    for _, o in ipairs(worldobjects) do
        local sq = o:getSquare()
        if sq then
            local objects = sq:getObjects()
            for i = 0, objects:size() - 1 do
                local obj = objects:get(i)
                if SmokerRecipe.isSmokerObject(obj) then return obj end
            end
        end
    end
    return nil
end

-- ---- multiplayer: client half (server half: lua/server/Smoker_ServerTests.lua) ----
-- The server runs the steps and sends "expect" after each; this client checks
-- its own copy of the smoker / its inventory a moment later and answers "seen".
-- Every debug client connected answers, so start a second client near the
-- smoker to check that changes reach other players too.

-- after "expect": time for the change to arrive and for the smoke scan
-- (Smoker_Client.lua, every 1 s) to follow a lit/unlit change. The server
-- waits 4 s between steps (Smoker_ServerTests.lua STEP_WAIT_MS).
local CHECK_DELAY_MS = 2500
local ANSWER_TIMEOUT_MS = 10000
local pendingChecks = {}
local waitingSince = nil        -- set when we asked the server, cleared on any answer

local function findSmokerAt(x, y, z)
    local sq = getCell():getGridSquare(x, y, z)
    if not sq then return nil end
    local objects = sq:getObjects()
    for i = 0, objects:size() - 1 do
        local obj = objects:get(i)
        if SmokerRecipe.isSmokerObject(obj) then return obj end
    end
    return nil
end

local function report(player, step, ok, detail)
    print("[SmokerTest] " .. (ok == nil and "SKIP " or (ok and "PASS " or "FAIL ")) .. step
        .. (detail and ("  (" .. tostring(detail) .. ")") or ""))
    sendClientCommand(player, "SmokerTest", "seen", { step = step, ok = ok, detail = detail })
end

local function runCheck(args)
    local player = getSpecificPlayer(0)
    if not player then return end
    local container, obj
    if args.where == "inventory" then
        container = player:getInventory()
    elseif args.where == "heat" then
        -- the heat source the server's cookwatch picked: any object with a
        -- container on that square that is not the smoker
        local sq = getCell():getGridSquare(args.x, args.y, args.z)
        local objects = sq and sq:getObjects()
        for i = 0, (objects and objects:size() or 0) - 1 do
            local o = objects:get(i)
            if o:getContainer() and not SmokerRecipe.isSmokerObject(o) then
                container = o:getContainer()
                break
            end
        end
        if not container then
            report(player, args.step, nil, "heat source not loaded on this client")
            return
        end
    else
        obj = findSmokerAt(args.x, args.y, args.z)
        if not obj then
            report(player, args.step, nil, "smoker not loaded on this client")
            return
        end
        container = obj:getContainer()
    end
    local problems = {}
    for i = 1, args.n or 0 do
        local id = args["id" .. i]
        local item = container:getItemById(id)
        if args["absent" .. i] then
            if item then table.insert(problems, "still has " .. item:getFullType() .. " #" .. tostring(id)) end
        elseif not item then
            table.insert(problems, "missing " .. tostring(args["type" .. i]) .. " #" .. tostring(id))
        else
            if args["type" .. i] and item:getFullType() ~= args["type" .. i] then
                table.insert(problems, "#" .. tostring(id) .. " is " .. item:getFullType())
            end
            if args["burnt" .. i] ~= nil and item:isBurnt() ~= args["burnt" .. i] then
                table.insert(problems, item:getFullType() .. " burnt=" .. tostring(item:isBurnt()))
            end
            if args["cooked" .. i] ~= nil and item:isCooked() ~= args["cooked" .. i] then
                table.insert(problems, item:getFullType() .. " cooked=" .. tostring(item:isCooked())
                    .. " cookingTime=" .. tostring(item:getCookingTime()))
            end
        end
    end
    if args.lit ~= nil and obj then
        if obj:isLit() ~= args.lit then table.insert(problems, "lit=" .. tostring(obj:isLit())) end
        if SmokerRecipe.hasSmoke and SmokerRecipe.hasSmoke(obj) ~= args.lit then
            table.insert(problems, "smoke shown=" .. tostring(SmokerRecipe.hasSmoke(obj)))
        end
    end
    report(player, args.step, #problems == 0, #problems > 0 and table.concat(problems, "; ") or nil)
end

local function onServerCommand(module, command, args)
    if module ~= "SmokerTest" then return end
    waitingSince = nil
    if command == "expect" then
        table.insert(pendingChecks, { at = getTimestampMs() + CHECK_DELAY_MS, args = args })
    elseif command == "done" then
        print("[SmokerTest] ---- server says: " .. tostring(args.text) .. " ----")
        local player = getSpecificPlayer(0)
        if player then player:Say("SmokerTest: " .. tostring(args.text)) end
    end
end

local function onTick()
    local t = getTimestampMs()
    if waitingSince and t - waitingSince > ANSWER_TIMEOUT_MS then
        waitingSince = nil
        local msg = "server did not answer - start the server with -debug (test_server.bat -DebugMode)"
        print("[SmokerTest] " .. msg)
        local player = getSpecificPlayer(0)
        if player then player:Say("SmokerTest: " .. msg) end
    end
    if #pendingChecks == 0 then return end
    while pendingChecks[1] and pendingChecks[1].at <= t do
        local c = table.remove(pendingChecks, 1)
        local ok, err = pcall(runCheck, c.args)
        if not ok then
            local player = getSpecificPlayer(0)
            if player then report(player, tostring(c.args.step), false, "client error: " .. tostring(err)) end
        end
    end
end

local function askServer(player, smoker, command)
    waitingSince = getTimestampMs()
    sendClientCommand(player, "SmokerTest", command, { x = smoker:getX(), y = smoker:getY(), z = smoker:getZ() })
    print("[SmokerTest] asked the server: " .. command)
end

local function onFillWorldObjectContextMenu(playerNum, context, worldobjects, test)
    if test then return end
    local smoker = findSmoker(worldobjects)
    if not smoker then return end
    local player = getSpecificPlayer(playerNum)
    context:addOption("Smoker: run tests", player, run, smoker)
    if isClient() then
        context:addOption("Smoker: MP test (fire out)", player, askServer, smoker, "run")
        context:addOption("Smoker: MP cooking watch (fire lit, 70 game min)", player, askServer, smoker, "watch")
        context:addOption("Smoker: MP outside cooking watch (lit campfire/oven within 6 tiles, up to 90 game min)", player, askServer, smoker, "cookwatch")
    end
end

SmokerTests.run = run
Events.OnFillWorldObjectContextMenu.Add(onFillWorldObjectContextMenu)
Events.OnServerCommand.Add(onServerCommand)
Events.OnTick.Add(onTick)
