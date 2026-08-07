-- Drives eod.lua's weekly path in plain Lua, with the Hammerspoon API stubbed.
--
-- eod.lua touches no hs.* at module load, so it can be required outside
-- Hammerspoon and its callbacks invoked directly. That is enough to cover the
-- part that matters here: what showWeekly() does when the engine fails.
--
-- Before 0df01ac both failure paths ended in silence. The task exit code was
-- accepted and never read, and output that did not parse simply skipped the
-- branch, so a failed weekly build produced no window, no log line and no clue.
--
--   lua tests/test_eod_lua.lua

local ROOT = arg[0]:match("(.*)/tests/[^/]+$") or "."
package.path = ROOT .. "/?.lua;" .. package.path

local failures, checks = 0, 0
local function check(ok, msg)
  checks = checks + 1
  if not ok then
    failures = failures + 1
    io.write("  FAIL  ", msg, "\n")
  else
    io.write("  ok    ", msg, "\n")
  end
end

-- ── the smallest hs that eod.lua's weekly path needs ────────────────────────
local lastTask
local logged = {}

local function stubHs()
  local shownWebviews = {}
  local function webview()
    local w = {}
    local function chain() return w end
    for _, m in ipairs({ "windowStyle", "closeOnEscape", "allowGestures",
                         "transparent", "allowTextEntry", "level", "shadow",
                         "alpha", "behavior", "deleteOnClose", "url", "frame",
                         "bringToFront", "sendToBack", "hide" }) do
      w[m] = chain
    end
    w.show = function() shownWebviews[#shownWebviews + 1] = true; return w end
    w.evaluateJavaScript = chain
    w.asHSWindow = function() return nil end
    return w
  end

  _G.hs = {
    task = {
      new = function(_bin, cb, _args)
        lastTask = { cb = cb, started = false }
        return {
          setEnvironment = function() end,
          start = function() lastTask.started = true; return true end,
        }
      end,
    },
    webview = {
      new = function() return webview() end,
      usercontent = { new = function()
        return { setCallback = function(s) return s end }
      end },
      windowMasks = { borderless = 1 },
    },
    drawing = {
      windowLevels = { floating = 1 },
      -- the module ORs these together, so they must be integers
      windowBehaviors = { canJoinAllSpaces = 1, stationary = 2, fullScreenAuxiliary = 4 },
    },
    screen = { primaryScreen = function()
      return { frame = function() return { x = 0, y = 0, w = 1920, h = 1080 } end }
    end },
    timer = { doAfter = function() return { stop = function() end } end,
              doEvery = function() return { stop = function() end } end,
              secondsSinceLastInput = function() return 0 end },
    pasteboard = { setContents = function() end },
    hotkey = { bind = function() end },
    menubar = { new = function() return {
      setTitle = function(s) return s end, setMenu = function(s) return s end,
      setClickCallback = function(s) return s end, delete = function() end } end },
    application = { frontmostApplication = function()
      return { name = function() return "Test" end } end },
    eventtap = { new = function() return { start = function() end, stop = function() end } end,
                 event = { types = {} } },
    mouse = { absolutePosition = function() return { x = 0, y = 0 } end },
    fs = { attributes = function() return nil end, mkdir = function() end },
    execute = function() return "" end,
    alert = { show = function() end },
    shownWebviews = shownWebviews,
  }
  setmetatable(_G.hs, { __index = function() return function() end end })
end

stubHs()

-- capture the module's log output
local realPrint = print
_G.print = function(s) logged[#logged + 1] = tostring(s); realPrint(s) end

local M = dofile(ROOT .. "/eod.lua")
_G.print = function(s) logged[#logged + 1] = tostring(s) end

-- ── the cases ───────────────────────────────────────────────────────────────
io.write("eod.lua weekly failure handling\n")

-- 1. non-zero exit must be logged, not swallowed
logged = {}
M.showWeekly(false)
check(lastTask ~= nil, "showWeekly spawns the engine")
check(lastTask.started, "the task is actually started")
lastTask.cb(1, "", "Traceback: engine exploded")
local joined = table.concat(logged, "\n")
check(joined:find("weekly build failed"), "a non-zero exit is reported")
check(joined:find("exploded"), "stderr reaches the log")

-- 2. exit 0 but unusable output must also speak up.
-- Note the second case: it parses fine as "<word> <rest>", which the original
-- check accepted and would have tried to load as a file path.
for _, bad in ipairs({ "GARBAGE", "Traceback most recent call last", "" }) do
  logged = {}
  M.showWeekly(false)
  lastTask.cb(0, bad)
  check(table.concat(logged, "\n"):find("no usable path"),
        "unusable engine output is reported: " .. string.format("%q", bad))
end

-- 3. the happy path must still open the panel
logged = {}
local before = #hs.shownWebviews
M.showWeekly(false)
lastTask.cb(0, "WEEKLY /tmp/cache/weekly-2026-08-03.html")
check(#hs.shownWebviews > before, "a good build still shows the recap")
check(table.concat(logged, "\n") == "", "the happy path logs nothing")

io.write(string.format("\n%d checks, %d failures\n", checks, failures))
os.exit(failures == 0 and 0 or 1)
