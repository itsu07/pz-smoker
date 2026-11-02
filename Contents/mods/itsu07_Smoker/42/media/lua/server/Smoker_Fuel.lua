require "Camping/camping_fuel"
require "Camping/ISCampingMenu"
require "TimedActions/ISBBQAddFuel"
require "Smoker_Recipe"

-- The fire fuel cap is the sandbox option MaximumFireFuelHours (8h by default),
-- checked only in Lua through the global getCampingFuelMax() (IsoFireplace.addFuel
-- itself does not clamp). A smoking run is 12h, so let the smoker alone take
-- SmokerRecipe.FUEL_MAX_HOURS: while one of the wrapped functions below works on
-- the smoker, getCampingFuelMax() returns the larger value.
SmokerRecipe.FUEL_MAX_HOURS = 12

local smokerTarget = 0

local function withSmoker(obj, fn, ...)
    if not SmokerRecipe.isSmokerObject(obj) then
        return fn(...)
    end
    smokerTarget = smokerTarget + 1
    local ok, a, b = pcall(fn, ...)
    smokerTarget = smokerTarget - 1
    if not ok then error(a) end
    return a, b
end

-- for lua/client/Smoker_Tests.lua
SmokerRecipe.withSmoker = withSmoker

local original_getCampingFuelMax = getCampingFuelMax
function getCampingFuelMax()
    local max = original_getCampingFuelMax()
    if smokerTarget > 0 then
        return math.max(max, SmokerRecipe.FUEL_MAX_HOURS * 60)
    end
    return max
end

-- right-click / loot window "Add fuel" menu (target is the fireplace object)
local original_doAddFuelOption = ISCampingMenu.doAddFuelOption
function ISCampingMenu.doAddFuelOption(context, worldobjects, currentFuel, fuelInfo, target, timedAction, playerObj)
    return withSmoker(target, original_doAddFuelOption, context, worldobjects, currentFuel, fuelInfo, target, timedAction, playerObj)
end

-- "All" / "All that fits" queue one action per item and stop at the cap
local original_onAddAllFuel = ISCampingMenu.onAddAllFuel
ISCampingMenu.onAddAllFuel = function(playerObj, target, timedAction, currentFuel)
    return withSmoker(target, original_onAddAllFuel, playerObj, target, timedAction, currentFuel)
end

local original_onAddMultipleFuel = ISCampingMenu.onAddMultipleFuel
ISCampingMenu.onAddMultipleFuel = function(playerObj, target, fuelType, timedAction, currentFuel, count)
    return withSmoker(target, original_onAddMultipleFuel, playerObj, target, fuelType, timedAction, currentFuel, count)
end

-- each queued add-fuel action re-checks the cap (also on the server in MP)
local original_isValid = ISBBQAddFuel.isValid
function ISBBQAddFuel:isValid()
    return withSmoker(self.fireplace, original_isValid, self)
end
