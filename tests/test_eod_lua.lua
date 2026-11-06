-- Drives eod.lua's weekly path and Send button in plain Lua, with the Hammerspoon API stubbed.
--
-- eod.lua touches no hs.* at module load, so it can be required outside
-- Hammerspoon and its callbacks invoked directly. That is enough to cover the
-- part that matters here: what showWeekly() does when the engine fails, and
-- what the share button does with the engine's answer.
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
local lastTask, lastCallback, lastJS
local logged = {}
local pasted = {}
local imageLoads, fileExists = true, false
local jsRun = {}                                 -- every evaluateJavaScript call, in order
local msgCallback                                -- the page->Lua bridge eod.lua registers
local timers = {}                                -- every hs.timer.doAfter, so a test can fire one

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
    w.evaluateJavaScript = function(_, js) lastJS = js; jsRun[#jsRun + 1] = js; return w end
    w.asHSWindow = function() return nil end
    return w
  end

  _G.hs = {
    task = {
      new = function(_bin, cb, args)
        lastTask = { cb = cb, started = false, args = args, terminated = false }
        local task = lastTask
        return {
          setEnvironment = function() end,
          terminate = function() task.terminated = true end,
          start = function() lastTask.started = true; return true end,
        }
      end,
    },
    webview = {
      new = function() return webview() end,
      usercontent = { new = function()
        return { setCallback = function(s, cb) lastCallback = cb; msgCallback = cb; return s end }
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
    timer = { doAfter = function(secs, fn)
                local tm = { secs = secs, fn = fn, stopped = false }
                timers[#timers + 1] = tm
                return { stop = function() tm.stopped = true end }
              end,
              doEvery = function() return { stop = function() end } end,
              secondsSinceLastInput = function() return 0 end },
    pasteboard = { setContents = function() end,
                   writeObjects = function(o) pasted[#pasted + 1] = o; return true end },
    image = { imageFromPath = function(p) return imageLoads and { path = p } or nil end },
    json = { encode = function(t) return '["' .. tostring(t[1]) .. '"]' end },
    hotkey = { bind = function() end },
    menubar = { new = function() return {
      setTitle = function(s) return s end, setMenu = function(s) return s end,
      setClickCallback = function(s) return s end, delete = function() end } end },
    application = { frontmostApplication = function()
      return { name = function() return "Test" end } end },
    eventtap = { new = function() return { start = function() end, stop = function() end } end,
                 event = { types = {} } },
    mouse = { absolutePosition = function() return { x = 0, y = 0 } end },
    fs = { attributes = function() return fileExists and {} or nil end, mkdir = function() end },
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

-- 4. the share button: the engine is asked for that day's image, the image
-- itself lands on the clipboard, and a failure says so instead of going quiet
io.write("\neod.lua share image\n")
M.show(false)
check(lastCallback ~= nil, "the panel registers a message handler")
lastCallback({ body = { action = "share" } })
local a = table.concat(lastTask.args or {}, " ")
check(a:find("%-%-share") and a:find("%-%-date %d%d%d%d%-%d%d%-%d%d"), "share runs the engine with --date and --share")
logged, pasted, lastJS = {}, {}, nil
lastTask.cb(0, "SHARE /tmp/cache/2026-08-06-share.png\n", "")
check(#pasted == 1 and pasted[1].path == "/tmp/cache/2026-08-06-share.png", "the PNG is put on the clipboard")
check(lastJS and lastJS:find("2026%-08%-06%-share%.png"), "the toast names the file")
logged, pasted = {}, {}
lastCallback({ body = { action = "share" } })
lastTask.cb(1, "", "EOD: no share image: the share image needs macOS")
check(#pasted == 0, "a failed build copies nothing")
check(table.concat(logged, "\n"):find("share image failed"), "a failed build is logged")
check(lastJS and lastJS:find("No image"), "a failed build is toasted")

-- one drawing at a time: a second press while the first runs only says so
lastCallback({ body = { action = "share" } })
local first = lastTask
lastJS = nil
lastCallback({ body = { action = "share" } })
check(lastTask == first, "a second press does not spawn another engine")
check(lastJS and lastJS:find("Already drawing"), "a second press is toasted")
first.cb(0, "SHARE /tmp/cache/2026-08-06-share.png", "")
lastCallback({ body = { action = "share" } })
check(lastTask ~= first, "the guard clears once the first drawing is back")

-- a PNG that cannot be loaded as an image is still a saved file, and says so
imageLoads, fileExists, pasted, lastJS = false, true, {}, nil
lastTask.cb(0, "SHARE /tmp/cache/2026-08-06-share.png", "")
check(#pasted == 0 and lastJS and lastJS:find("Saved, not copied"), "an unloadable image is saved, not copied")
lastCallback({ body = { action = "share" } })
imageLoads, fileExists, lastJS = false, false, nil
lastTask.cb(0, "SHARE /tmp/cache/2026-08-06-share.png", "")
check(lastJS and lastJS:find("No image"), "a missing file is reported")
imageLoads = true

-- ── the Send button ───────────────────────────────────────────────────────────
io.write("\neod.lua send button\n")

local function hasArg(args, want)
  for _, a in ipairs(args or {}) do if a == want then return true end end
  return false
end

M.show(false)                                    -- builds the brief card and registers the bridge
check(msgCallback ~= nil, "the brief card registers a message handler")

-- 4. pressing Send runs the engine with --send for the day on screen
jsRun = {}
msgCallback({ body = { action = "post" } })
local sendTask = lastTask
check(sendTask and hasArg(sendTask.args, "--send"), "a post message runs the engine with --send")
check(sendTask and hasArg(sendTask.args, "--date"), "it sends the day on screen, not a guess")

-- 5. a second press while the first is in flight does not post twice, and says so
jsRun = {}
msgCallback({ body = { action = "post" } })
check(lastTask == sendTask, "a double press does not start a second send")
check(table.concat(jsRun, "\n"):find("Already sending", 1, true), "a double press is told why")
local function guardFor()
  for i = #timers, 1, -1 do if timers[i].secs == 90 then return timers[i] end end
end
local g1 = guardFor()
check(g1 ~= nil, "a send arms a 90s guard")

-- 6. success is toasted with the destinations the engine named
sendTask.cb(0, "SENT Slack, Linear\n", "")
check(g1 and g1.stopped, "a finished send disarms its guard")
local js = table.concat(jsRun, "\n")
check(js:find("sendResult", 1, true) and js:find("Sent to Slack, Linear", 1, true),
      "success toasts the destinations")

-- 7. failure is toasted and logged, with quotes that cannot break the JS
jsRun = {}; logged = {}
msgCallback({ body = { action = "post" } })
check(lastTask ~= sendTask, "the next press sends again once the first is done")
lastTask.cb(1, "", 'Traceback line with detail\nSlack: HTTP 404 "no_service"\n')
js = table.concat(jsRun, "\n")
check(js:find('Slack: HTTP 404 \\"no_service\\"', 1, true), "the failure reason is toasted, escaped")
local lg = table.concat(logged, "\n")
check(lg:find("send failed (1)", 1, true) and lg:find("no_service", 1, true), "a failed send is logged with its exit code")
check(not lg:find("Traceback line", 1, true), "only the last stderr line is logged")

-- 8. a hung send is killed after 90s and the button is freed
jsRun = {}; logged = {}
msgCallback({ body = { action = "post" } })
local hung = lastTask
local g2 = guardFor()
g2.fn()
check(hung.terminated, "the guard terminates a hung send")
check(table.concat(jsRun, "\n"):find("Send timed out", 1, true), "a timeout is toasted")
msgCallback({ body = { action = "post" } })
local after = lastTask
check(after ~= hung, "after a timeout the next press sends again")
jsRun = {}
hung.cb(15, "", "killed\n")                     -- the killed task's own late callback
check(table.concat(jsRun, "\n") == "", "the killed task does not toast a second time")
msgCallback({ body = { action = "post" } })
check(lastTask == after, "nor does it free the button while a newer send is in flight")

io.write(string.format("\n%d checks, %d failures\n", checks, failures))
os.exit(failures == 0 and 0 or 1)
