-- Multiplayer self test, server half. Only on a server started with -debug.
-- A debug client asks for it from the smoker's right-click menu
-- (lua/client/Smoker_Tests.lua). The server changes items in the real smoker
-- step by step and, after each step, tells every client what it should now
-- see ("expect"); each client checks its own copy and answers ("seen"). So
-- this checks both the server logic and that the changes reach every player.
-- Results: "[SmokerTest] ..." lines in the server console.txt (and a summary
-- spoken by the player who started it). tools/check_logs.py collects them.
--
-- Commands (client right-click menu):
--   run        fire out: registration, container, fuel cap, smoking / burning /
--              outside-cooking swaps with simulated minutes, and the fire being
--              lit and put out by the server (lit state + smoke on every client)
--   watch      fire lit: real game minutes, prep must not cook in the smoker
--   cookwatch  a lit campfire / fireplace / running oven within HEAT_RADIUS of
--              the smoker: prep put there must cook into plain food for real
--              (OnCooked called on the server, swap reaches every client)
if isClient() then return end
if not isDebugEnabled() then return end

require "Smoker_Recipe"

local MODULE = "SmokerTest"
local STEP_WAIT_MS = 4000          -- real time between steps; clients check 2.5 s after each
local FINAL_WAIT_TICKS = 150       -- ~15 s at the server's 10 ticks/s: give up waiting for the last answer
local WATCH_MINUTES = 70           -- cooking watch: longer than pork's 50 min cook time
local COOK_WATCH_MINUTES = 90      -- outside cooking: pork cooks in 50 min, allow for a slow fire
local HEAT_RADIUS = 6              -- how far from the smoker to look for a lit heat source
local FIRE_TEST_MINUTES = 60       -- fuel given to the smoker for the lit / put out steps

local run = nil

local function now()
    if getTimestampMs then return getTimestampMs() end
    return os.time() * 1000
end

local function check(name, ok, detail)
    run.total = run.total + 1
    if ok then run.passed = run.passed + 1 end
    print("[SmokerTest] server " .. (ok and "PASS " or "FAIL ") .. name
        .. (detail ~= nil and ("  (" .. tostring(detail) .. ")") or ""))
end

local function findSmoker(x, y, z)
    local sq = getCell():getGridSquare(x, y, z)
    if not sq then return nil end
    local objects = sq:getObjects()
    for i = 0, objects:size() - 1 do
        local obj = objects:get(i)
        if SmokerRecipe.isSmokerObject(obj) then return obj end
    end
    return nil
end

local function findType(container, fullType, exclude)
    local items = container:getItems()
    for i = 0, items:size() - 1 do
        local it = items:get(i)
        if it:getFullType() == fullType and not (exclude and exclude[it:getID()]) then return it end
    end
    return nil
end

local function idSet(container)
    local set = {}
    local items = container:getItems()
    for i = 0, items:size() - 1 do set[items:get(i):getID()] = true end
    return set
end

local function add(container, fullType)
    local item = container:AddItem(fullType)
    if item then sendAddItemToContainer(container, item) end
    return item
end

local function removeItem(container, item)
    if item and item:getContainer() == container then
        container:DoRemoveItem(item)
        sendRemoveItemFromContainer(container, item)
    end
end

-- Tell clients what to look for. list: { {id=, type=, burnt=, cooked=} or {id=, absent=true} }
-- Flattened into plain keys (id1, type1, ...) for the network.
-- where: "smoker" (the smoker's container), "inventory" (the starting player's),
-- "heat" (the container of the heat source found by cookwatch, at run.hx/hy/hz)
local function expect(step, where, list, extra)
    local args = { step = step, where = where, x = run.x, y = run.y, z = run.z, n = #list }
    if where == "heat" then
        args.x, args.y, args.z = run.hx, run.hy, run.hz
    end
    for i, e in ipairs(list) do
        args["id" .. i] = e.id
        args["absent" .. i] = e.absent and true or false
        if e.type then args["type" .. i] = e.type end
        if e.burnt ~= nil then args["burnt" .. i] = e.burnt end
        if e.cooked ~= nil then args["cooked" .. i] = e.cooked end
    end
    for k, v in pairs(extra or {}) do args[k] = v end
    run.lastStep = step
    if where == "inventory" then
        sendServerCommand(run.player, MODULE, "expect", args)
    else
        sendServerCommand(MODULE, "expect", args)
    end
end

local function state(item, wantBurnt, wantCooked)
    return { id = item:getID(), type = item:getFullType(), burnt = wantBurnt, cooked = wantCooked }
end

local function gone(item)
    return { id = item:getID(), absent = true }
end

local function onlineNames()
    local names = {}
    local players = getOnlinePlayers()
    for i = 0, players:size() - 1 do
        table.insert(names, tostring(players:get(i):getUsername()))
    end
    return names
end

local function finishRun()
    -- which players answered at all (a far-away player answers SKIP, which still counts)
    if run.lastStep then
        local online = onlineNames()
        local answered = {}
        for name in pairs(run.answered) do table.insert(answered, name) end
        table.sort(answered)
        check("every online player answered (" .. #answered .. " of " .. #online .. ": "
            .. table.concat(answered, ", ") .. ")", #answered >= #online and #online > 0)
    end
    local msg = "server " .. run.passed .. "/" .. run.total .. " passed"
    print("[SmokerTest] ---- " .. run.name .. " done: " .. msg .. " (client results: lines \"client <name>\") ----")
    sendServerCommand(run.player, MODULE, "done", { text = msg })
    run = nil
end

-- The last expect of a run must be checked by the clients before the test
-- items are removed. The earlier time-based wait fired at once (seen in the
-- 2026-11-01 log: "watch done" 3 ms after the 70 min step), so now the run
-- ends when the starting player answers that step, or after FINAL_WAIT_TICKS.
local function finishAfterSeen(cleanup)
    run.finalStep = run.lastStep
    run.finalTicks = 0
    run.cleanup = cleanup
end

local function doFinish(why)
    if why then print("[SmokerTest] finishing: " .. why) end
    if run.cleanup then
        local ok, err = pcall(run.cleanup)
        if not ok then check("cleanup error", false, err) end
    end
    finishRun()
end

local function syncState(obj)
    -- same call vanilla makes after addFuel / turnOn / extinguish
    -- (shared/TimedActions/ISBBQAddFuel.lua, ISBBQLightFromLiterature.lua, ISBBQExtinguish.lua)
    obj:sendObjectChange(IsoObjectChange.STATE)
end

-- ---- full test: steps run one by one with STEP_WAIT_MS in between ----------

local function stepsFull()
    local s = {}
    local t = {}       -- items made by the test

    table.insert(s, function()
        local obj = run.smoker
        check("smoker is registered on the server", SmokerRecipe.isRegistered(obj))
        check("smoker is an IsoFireplace on the server", instanceof(obj, "IsoFireplace"))
        local c = obj:getContainer()
        check("container type is smoker", c and c:getType() == "smoker", c and c:getType())
        check("container capacity is 7", c and c:getCapacity() == 7, c and c:getCapacity())
        if obj:isLit() then
            check("fire is out (real minutes would mix into the test; put it out and run again)", false)
            return false
        end
        local base = getSandboxOptions():getOptionByName("MaximumFireFuelHours"):getValue() * 60
        check("normal fire keeps the sandbox fuel cap", getCampingFuelMax() == base, getCampingFuelMax())
        local cap = SmokerRecipe.withSmoker(obj, getCampingFuelMax)
        check("smoker fuel cap on the server", cap == math.max(base, SmokerRecipe.FUEL_MAX_HOURS * 60), cap)
        local items = c:getItems()
        for i = 0, items:size() - 1 do
            if items:get(i):getModule() == "Smoker" then
                check("smoker is empty of prep/smoked food (take it out and run again)", false, items:get(i):getFullType())
                return false
            end
        end
        t.pork = add(c, "Smoker.CuredPork")
        t.cheese = add(c, "Smoker.CuredCheese")
        check("test prep added", t.pork ~= nil and t.cheese ~= nil)
        -- whatever step the run stops at, take the test items out again: the
        -- smoker held no Smoker food before, so every Smoker item in it is ours
        run.cleanup = function()
            local inv = run.player:getInventory()
            local ours = {}
            local now_items = c:getItems()
            for i = 0, now_items:size() - 1 do
                if now_items:get(i):getModule() == "Smoker" then table.insert(ours, now_items:get(i)) end
            end
            for _, it in ipairs(ours) do removeItem(c, it) end
            removeItem(inv, t.outside)
            removeItem(inv, t.plain)
        end
        if not (t.pork and t.cheese) then return false end
        expect("prep put in the smoker", "smoker", { state(t.pork, false, false), state(t.cheese, false, false) })
    end)

    table.insert(s, function()
        local c = run.smoker:getContainer()
        t.pork:setCookingTime(30)
        SmokerRecipe.updateSmoker(run.smoker, 0, false)
        check("cooking time reset on the server", t.pork:getCookingTime() == 0, t.pork:getCookingTime())
        SmokerRecipe.updateSmoker(run.smoker, SmokerRecipe.SMOKE_MINUTES.CuredCheese, true)
        t.smokedCheese = findType(c, "Smoker.SmokedCheese")
        check("cheese smoked on the server", t.smokedCheese ~= nil and t.cheese:getContainer() ~= c)
        if not t.smokedCheese then return false end
        expect("cheese smoked", "smoker", { gone(t.cheese), state(t.smokedCheese, false), state(t.pork, false, false) })
    end)

    table.insert(s, function()
        local c = run.smoker:getContainer()
        SmokerRecipe.updateSmoker(run.smoker, SmokerRecipe.SMOKE_MINUTES.CuredPork - SmokerRecipe.SMOKE_MINUTES.CuredCheese, true)
        t.smokedPork = findType(c, "Smoker.SmokedPork")
        t.burntCheese = findType(c, "Smoker.SmokedCheese")
        check("pork smoked on the server", t.smokedPork ~= nil and t.pork:getContainer() ~= c)
        check("cheese left in burnt on the server", t.burntCheese ~= nil and t.burntCheese:isBurnt())
        if not (t.smokedPork and t.burntCheese) then return false end
        expect("pork smoked, cheese burnt", "smoker", { gone(t.pork), state(t.smokedPork, false), gone(t.smokedCheese), state(t.burntCheese, true) })
    end)

    table.insert(s, function()
        local c = run.smoker:getContainer()
        SmokerRecipe.updateSmoker(run.smoker, SmokerRecipe.BURN_MINUTES, true)
        t.burntPork = findType(c, "Smoker.SmokedPork")
        check("pork burnt on the server", t.burntPork ~= nil and t.burntPork:isBurnt())
        if not t.burntPork then return false end
        expect("pork burnt", "smoker", { gone(t.smokedPork), state(t.burntPork, true) })
    end)

    table.insert(s, function()
        local inv = run.player:getInventory()
        local before = idSet(inv)
        t.outside = add(inv, "Smoker.CuredPork")
        SmokerRecipe.onCooked(t.outside)
        SmokerRecipe.processPending()
        t.plain = findType(inv, "Base.Pork", before)
        check("prep cooked outside -> plain pork on the server", t.plain ~= nil and t.outside:getContainer() ~= inv)
        check("plain pork is cooked on the server", t.plain ~= nil and t.plain:isCooked())
        if not t.plain then return false end
        expect("cooked outside the smoker", "inventory", { gone(t.outside), state(t.plain, nil, true) })
    end)

    -- the server lights the smoker and puts it out, the way the vanilla light /
    -- extinguish actions do; every client must see the lit state and the smoke
    -- follow (MP_TESTPLAN 7-1, 7-2, 7-3). The fuel is put back afterwards.
    table.insert(s, function()
        local obj = run.smoker
        t.fuelBefore = obj:getFuelAmount()
        obj:addFuel(FIRE_TEST_MINUTES)
        obj:turnOn()
        syncState(obj)
        check("server lit the smoker (turnOn)", obj:isLit(), "fuel " .. tostring(obj:getFuelAmount()))
        if not obj:isLit() then return false end
        expect("smoker lit by the server", "smoker", {}, { lit = true })
    end)

    table.insert(s, function()
        local obj = run.smoker
        obj:extinguish()
        syncState(obj)
        check("server put the smoker out (extinguish)", not obj:isLit())
        -- setFuelAmount: IsoFireplace method seen in the game's class file, not used by vanilla Lua (unverified)
        local ok, err = pcall(function() obj:setFuelAmount(t.fuelBefore or 0) end)
        check("fuel put back to " .. tostring(t.fuelBefore) .. " min (setFuelAmount)", ok, err)
        syncState(obj)
        expect("smoker put out by the server", "smoker", {}, { lit = false })
    end)

    table.insert(s, function()
        local c = run.smoker:getContainer()
        removeItem(c, t.burntPork)
        removeItem(c, t.burntCheese)
        removeItem(run.player:getInventory(), t.plain)
        expect("test items removed (smoker)", "smoker", { gone(t.burntPork), gone(t.burntCheese) })
        expect("test items removed (inventory)", "inventory", { gone(t.plain) })
        finishAfterSeen(nil)
    end)
    return s
end

-- ---- cooking watch: real game minutes in a lit smoker ----------------------

local function startWatch()
    local c = run.smoker:getContainer()
    if not run.smoker:isLit() then
        check("fire is lit (light it and run the watch again)", false)
        finishRun()
        return
    end
    run.item = add(c, "Smoker.CuredPork")
    run.minutes = 0
    check("watch: prep added to the lit smoker", run.item ~= nil)
    if not run.item then finishRun() return end
    print("[SmokerTest] watch: " .. WATCH_MINUTES .. " game minutes, checking every 10")
    expect("watch start", "smoker", { state(run.item, false, false) }, { lit = true })
end

local function watchMinute()
    if not run or run.name ~= "watch" or not run.item or run.finalStep then return end
    run.minutes = run.minutes + 1
    if run.minutes % 10 ~= 0 then return end
    local item = run.item
    local c = run.smoker:getContainer()
    local here = item:getContainer() == c
    check("watch " .. run.minutes .. " min: prep still in the smoker", here)
    if not here then finishRun() return end
    check("watch " .. run.minutes .. " min: not cooked on the server", not item:isCooked(), item:getCookingTime())
    expect("watch " .. run.minutes .. " min", "smoker", { state(item, false, false) }, { lit = run.smoker:isLit() })
    if run.minutes >= WATCH_MINUTES then
        -- proves the real per-minute smoking tick runs on this server (registered,
        -- EveryOneMinute, elapsed time and isLit all working together)
        local counted = item:getModData().smokerMinutes or 0
        check("watch: the real server tick counted smoking time (about " .. WATCH_MINUTES .. ")",
            counted >= WATCH_MINUTES * 0.7 and counted <= WATCH_MINUTES * 1.3, counted)
        finishAfterSeen(function() removeItem(run.smoker:getContainer(), run.item) end)
    end
end

-- ---- outside cooking watch: prep in a real lit heat source near the smoker --

-- A lit heat source with a container, within HEAT_RADIUS of the smoker:
-- a vanilla fireplace / barbecue (IsoFireplace, lit), a running oven
-- (IsoStove, Activated: B41 Lua name, present in the B42 class file) or a
-- campfire (plain object with a "campfire" container, lit state kept by
-- SCampfireSystem). Returns obj, kind.
local function findHeatSource()
    local cell = getCell()
    for dx = -HEAT_RADIUS, HEAT_RADIUS do
        for dy = -HEAT_RADIUS, HEAT_RADIUS do
            local sq = cell:getGridSquare(run.x + dx, run.y + dy, run.z)
            if sq then
                local objects = sq:getObjects()
                for i = 0, objects:size() - 1 do
                    local obj = objects:get(i)
                    local c = obj:getContainer()
                    if c and not SmokerRecipe.isSmokerObject(obj) then
                        if instanceof(obj, "IsoFireplace") then
                            if obj:isLit() then return obj, "fireplace" end
                        elseif instanceof(obj, "IsoStove") then
                            local ok, on = pcall(function() return obj:Activated() end)
                            if ok and on then return obj, "stove" end
                        elseif c:getType() == "campfire" and SCampfireSystem and SCampfireSystem.instance then
                            local cf = SCampfireSystem.instance:getLuaObjectAt(sq:getX(), sq:getY(), sq:getZ())
                            if cf and cf.isLit then return obj, "campfire" end
                        end
                    end
                end
            end
        end
    end
    return nil
end

local function startCookWatch()
    local heat, kind = findHeatSource()
    check("a lit campfire / fireplace / running oven within " .. HEAT_RADIUS .. " tiles of the smoker", heat ~= nil, kind)
    if not heat then finishRun() return end
    run.heat = heat
    run.hx, run.hy, run.hz = heat:getX(), heat:getY(), heat:getZ()
    print("[SmokerTest] cookwatch: " .. kind .. " at " .. run.hx .. "," .. run.hy .. "," .. run.hz
        .. ", up to " .. COOK_WATCH_MINUTES .. " game minutes, checking every 10")
    local c = heat:getContainer()
    run.before = idSet(c)
    run.item = add(c, "Smoker.CuredPork")
    run.minutes = 0
    check("cookwatch: prep added to the " .. kind, run.item ~= nil)
    if not run.item then finishRun() return end
    expect("cookwatch start", "heat", { state(run.item, false, false) })
end

local function cookWatchMinute()
    if not run or run.name ~= "cookwatch" or not run.item or run.finalStep then return end
    run.minutes = run.minutes + 1
    local c = run.heat:getContainer()
    local item = run.item
    if item:getContainer() ~= c then
        -- the prep is gone: SmokerRecipe.onCooked -> swapCooked should have put plain cooked pork here
        run.plain = findType(c, "Base.Pork", run.before)
        check("cookwatch " .. run.minutes .. " min: prep replaced by plain pork on the server", run.plain ~= nil)
        check("cookwatch: plain pork is cooked on the server", run.plain ~= nil and run.plain:isCooked())
        if run.plain then
            expect("cookwatch cooked", "heat", { gone(item), state(run.plain, nil, true) })
            finishAfterSeen(function() removeItem(run.heat:getContainer(), run.plain) end)
        else
            finishAfterSeen(nil)
        end
        return
    end
    if run.minutes % 10 == 0 then
        check("cookwatch " .. run.minutes .. " min: still cooking (cookingTime " .. tostring(item:getCookingTime()) .. ")",
            item:getCookingTime() > 0 or run.minutes <= 10)
        expect("cookwatch " .. run.minutes .. " min", "heat", { state(item, false, false) })
    end
    if run.minutes >= COOK_WATCH_MINUTES then
        check("cookwatch: OnCooked fired on the server within " .. COOK_WATCH_MINUTES .. " min"
            .. " (if not: the heat source went out, or the game does not cook container food on the server)",
            false, "cookingTime " .. tostring(item:getCookingTime()) .. " cooked=" .. tostring(item:isCooked()))
        finishAfterSeen(function() removeItem(run.heat:getContainer(), run.item) end)
    end
end

-- ---- plumbing ----------------------------------------------------------------

local function onTick()
    if not run then return end
    if run.finalStep then
        run.finalTicks = run.finalTicks + 1
        if run.finalTicks >= FINAL_WAIT_TICKS then
            doFinish("no answer from " .. tostring(run.player:getUsername()) .. " for \"" .. run.finalStep .. "\", giving up")
        end
        return
    end
    if not run.steps then return end
    if now() < run.nextAt then return end
    local step = table.remove(run.steps, 1)
    if not step then finishRun() return end
    local ok, result = pcall(step)
    if not ok then
        check("step error", false, result)
        doFinish("step error, test items taken out")
    elseif result == false then
        doFinish("stopped early, test items taken out")
    else
        run.nextAt = now() + STEP_WAIT_MS
    end
end

local function everyMinute()
    watchMinute()
    cookWatchMinute()
end

local function onClientCommand(module, command, player, args)
    if module ~= MODULE then return end
    if command == "seen" then
        local name = tostring(player:getUsername())
        print("[SmokerTest] client " .. name .. " "
            .. (args.ok == nil and "SKIP " or (args.ok and "PASS " or "FAIL ")) .. tostring(args.step)
            .. (args.detail and ("  (" .. tostring(args.detail) .. ")") or ""))
        if run then
            run.answered[name] = true
            if run.finalStep and args.step == run.finalStep and name == tostring(run.player:getUsername()) then
                doFinish(nil)
            end
        end
        return
    end
    if run then
        sendServerCommand(player, MODULE, "done", { text = "a test is already running" })
        return
    end
    local smoker = findSmoker(args.x, args.y, args.z)
    if not smoker then
        sendServerCommand(player, MODULE, "done", { text = "no smoker at that spot on the server" })
        return
    end
    run = { name = command, player = player, smoker = smoker, x = args.x, y = args.y, z = args.z,
            passed = 0, total = 0, nextAt = now(), answered = {} }
    local online = onlineNames()
    print("[SmokerTest] ---- " .. command .. " start by " .. tostring(player:getUsername()) .. " ----")
    print("[SmokerTest] online players: " .. #online .. " (" .. table.concat(online, ", ") .. ")")
    if command == "run" then
        run.steps = stepsFull()
    elseif command == "watch" then
        startWatch()
    elseif command == "cookwatch" then
        startCookWatch()
    else
        run = nil
    end
end

Events.OnClientCommand.Add(onClientCommand)
Events.OnTick.Add(onTick)
Events.EveryOneMinute.Add(everyMinute)
