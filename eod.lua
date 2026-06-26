-- avinash · EOD
-- A desktop panel that shows everything you did in Claude Code on a given day,
-- grouped by project, ready to copy-paste into a task sheet. It rebuilds itself
-- from the session transcripts under ~/.claude (via extract.py) — no network.
--
--   • auto-refreshes during the day, and rolls over to the new day at midnight
--   • ◀ ▶ to browse previous days (for back-filling the sheet)
--   • "Copy all" or per-project "copy" → straight to the clipboard
--   • menu-bar ▤ toggles the panel; ⌥⌃⌘W also toggles
--
-- Loaded isolated + pcall-guarded from hs-init.lua, exactly like claude_usage,
-- so nothing here can affect the shutter unlock animation.

local M = {}

-- ── config ───────────────────────────────────────────────────────────────────
-- Resolve our own folder + a python3 so this works wherever it's dropped, on any Mac.
local DIR = (debug.getinfo(1, "S").source:match("^@(.*)/") or ".")
local function findPython()
  for _, p in ipairs({ "/opt/homebrew/bin/python3", "/usr/local/bin/python3", "/usr/bin/python3" }) do
    local f = io.open(p); if f then f:close(); return p end
  end
  return "/usr/bin/python3"
end
local CFG  = {
  python        = findPython(),
  script        = DIR .. "/extract.py",
  env           = { PATH = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
                    HOME = os.getenv("HOME"),
                    LANG = "en_US.UTF-8" },
  refreshEvery  = 600,                       -- re-scan today every 10 min
  size          = { w = 396, h = 660 },      -- panel size (snug around the 340px receipt)
  margin        = 24,                         -- inset from top-right of screen
  hotkey        = { mods = { "alt", "ctrl", "cmd" }, key = "W" },
  showAtStart   = true,
  usagePoll     = 15,                        -- sample the active app every 15s
  usageIdle     = 120,                       -- don't count time while idle > 120s (away)
  reminderHour  = 18,                         -- end-of-day reminder time (24h)
  reminderMin   = 30,
  reminderOn    = true,                       -- weekdays only
}

-- ── state ────────────────────────────────────────────────────────────────────
local wv, ucc, bar, refreshTimer, midnightTimer, hideTimer, reminderTimer
local usageTimer, usageFlushTimer            -- app-usage (SCREEN TIME) tracking
local wvFull, uccFull, fullShown             -- the detail card (2nd window: full bill / weekly)
local makeFullWebview, onMessageFull          -- forward decls (used before defined)
local dragTap, dragOff                        -- frameless-window dragging
local loadN = 0                                -- cache-buster: a fragment-only (#in) change does NOT
                                               -- reload the webview, so the print-down animation would
                                               -- never replay. A changing ?n= query forces a real reload.
local ROLL_OUT = 0.46                          -- seconds: roll-up before the window hides
local curDate                                -- "YYYY-MM-DD" currently shown
local shown = false                          -- our own visibility flag (hswindow() is unreliable for webviews)
local function log(s) print("[eod] " .. tostring(s)) end

local function today() return os.date("%Y-%m-%d") end

-- ── app-usage tracker (SCREEN TIME) ──────────────────────────────────────────────
-- Samples the frontmost app on a timer and accumulates active seconds per app per
-- day into cache/usage-YYYY-MM-DD.json, which extract.py reads back. Time while the
-- machine is idle (no input for > usageIdle) is not counted. Fully local; no network.
local usage = { date = nil, secs = {} }
local function usagePath(d) return DIR .. "/cache/usage-" .. d .. ".json" end

local function usageLoad(d)
  local f = io.open(usagePath(d), "r")
  if not f then return {} end
  local raw = f:read("*a"); f:close()
  local ok, t = pcall(hs.json.decode, raw)
  return (ok and type(t) == "table") and t or {}
end

local function usageFlush()
  if not usage.date then return end
  local ok, raw = pcall(hs.json.encode, usage.secs)
  if not ok then return end
  local f = io.open(usagePath(usage.date), "w")
  if f then f:write(raw); f:close() end
end

local function usageSample()
  local d = today()
  if usage.date ~= d then            -- first sample, or we just crossed midnight
    usageFlush()                     -- persist the day that just ended
    usage.date = d
    usage.secs = usageLoad(d)        -- resume any counts already saved today
  end
  if hs.host.idleTime() > CFG.usageIdle then return end   -- away from keyboard — skip
  local app  = hs.application.frontmostApplication()
  local name = app and app:name()
  if name and name ~= "" then
    usage.secs[name] = (usage.secs[name] or 0) + CFG.usagePoll
  end
end

-- ── engine runner ──────────────────────────────────────────────────────────────
-- Runs extract.py for `date`; on success loads the produced HTML into the webview.
local function rebuild(date, force, animate, repolish)
  date = date or curDate or today()
  local args = { CFG.script, "--date", date }
  if repolish then args[#args + 1] = "--repolish" end   -- force a fresh AI summary (Regenerate)
  local t = hs.task.new(CFG.python, function(code, out, err)
    if code ~= 0 then
      log("extract failed (" .. tostring(code) .. "): " .. tostring(err))
      return
    end
    out = (out or ""):gsub("%s+$", "")
    local tag, path = out:match("^(%S+)%s+(.+)$")
    -- reload the page unless the engine said nothing changed (avoids scroll reset on the timer).
    -- ?n= forces a real reload (fragment-only changes don't); #in plays the print-down animation.
    if wv and path and (force or tag ~= "UNCHANGED") then
      loadN = loadN + 1
      wv:url("file://" .. path .. "?n=" .. loadN .. (animate and "#in" or ""))
      -- keep the full bill in sync if it's open (its file is built in the same run)
      if fullShown and wvFull then
        wvFull:url("file://" .. path:gsub("%.html$", "-full.html") .. "?n=" .. loadN)
      end
    end
  end, args)
  if not t then log("could not spawn python"); return end
  t:setEnvironment(CFG.env)
  t:start()
end

-- persist user-edited work lines so they survive refreshes (extract.py honours the 'edited' flag)
local function saveEdits(items)
  if type(items) ~= "table" or not curDate then return end
  local hl = {}
  for _, v in ipairs(items) do if type(v) == "string" and v ~= "" then hl[#hl + 1] = v end end
  local path = DIR .. "/cache/polish-" .. curDate .. ".json"
  local detailed                                  -- preserve the detailed breakdown across an edit
  local rf = io.open(path, "r")
  if rf then
    local prev = hs.json.decode(rf:read("*a")); rf:close()
    if type(prev) == "table" then detailed = prev.detailed end
  end
  local ok, raw = pcall(hs.json.encode, { key = "edited", highlights = hl, detailed = detailed, edited = true })
  if ok then
    local f = io.open(path, "w")
    if f then f:write(raw); f:close() end
  end
  rebuild(curDate, true, false)
end

-- ── clipboard / nav bridge (messages posted from the page's JS) ──────────────────
-- Drag a borderless window by following the mouse (no native title bar to grab).
local function startDrag(win)
  win = win or wv
  if not win then return end
  local m, f = hs.mouse.absolutePosition(), win:frame()
  dragOff = { dx = m.x - f.x, dy = m.y - f.y }
  if dragTap then dragTap:stop() end
  local T = hs.eventtap.event.types
  dragTap = hs.eventtap.new({ T.leftMouseDragged, T.leftMouseUp }, function(e)
    if e:getType() == T.leftMouseUp then
      if dragTap then dragTap:stop(); dragTap = nil end
      return false
    end
    if win and dragOff then
      local mm, fr = hs.mouse.absolutePosition(), win:frame()
      fr.x, fr.y = mm.x - dragOff.dx, mm.y - dragOff.dy
      win:frame(fr)
    end
    return false
  end)
  dragTap:start()
end

local function onMessage(msg)
  local b = msg.body
  if type(b) ~= "table" then return end
  local action = b.action
  if action == "copy" then
    hs.pasteboard.setContents(b.text or "")
  elseif action == "dragStart" then
    startDrag(wv)
  elseif action == "hide" then
    M.hide()
  elseif action == "full" then
    M.showFull()
  elseif action == "refresh" then
    rebuild(curDate, true, false)
  elseif action == "regen" then
    rebuild(curDate, true, false, true)        -- force a fresh AI summary
  elseif action == "saveEdits" then
    saveEdits(b.items)
  elseif action == "nav" then
    local delta = tonumber(b.delta) or 0
    -- shift curDate by delta days, but never past today
    local y, m, d = curDate:match("(%d+)-(%d+)-(%d+)")
    local t = os.time({ year = y, month = m, day = d, hour = 12 })
    local nt = t + delta * 86400
    local cand = os.date("%Y-%m-%d", nt)
    if cand <= today() then curDate = cand; rebuild(curDate, true, false) end
  elseif action == "goDate" then
    local cand = tostring(b.date or "")
    if cand:match("^%d%d%d%d%-%d%d%-%d%d$") and cand <= today() then
      curDate = cand; rebuild(curDate, true, false)
    end
  end
end

-- messages from the full-bill card: just copy / drag / close (no nav)
onMessageFull = function(msg)
  local b = msg.body
  if type(b) ~= "table" then return end
  if b.action == "copy" then
    hs.pasteboard.setContents(b.text or "")
  elseif b.action == "dragStart" then
    startDrag(wvFull)
  elseif b.action == "hide" then
    M.hideFull()
  end
end

-- ── panel ────────────────────────────────────────────────────────────────────
local function frame()
  local s = hs.screen.primaryScreen():frame()
  return {
    x = s.x + s.w - CFG.size.w - CFG.margin,
    y = s.y + CFG.margin,
    w = CFG.size.w, h = CFG.size.h,
  }
end

local function makeWebview()
  ucc = hs.webview.usercontent.new("eod")
  ucc:setCallback(onMessage)
  local masks = hs.webview.windowMasks
  wv = hs.webview.new(frame(), { developerExtrasEnabled = false }, ucc)
  -- frameless: no title bar / chrome. Drag via the receipt masthead (see startDrag).
  wv:windowStyle(masks.borderless)
  wv:transparent(true)                 -- only the cream paper shows; desktop behind it
  wv:shadow(false)                     -- the paper's own shadow is drawn in CSS (follows the torn edge)
  wv:level(hs.drawing.windowLevels.floating)
  -- canJoinAllSpaces: show on every Space. fullScreenAuxiliary: also show OVER another
  -- app's full-screen Space (e.g. full-screen Claude/VS Code) so it's never hidden behind it.
  wv:behavior(hs.drawing.windowBehaviors.canJoinAllSpaces
            | hs.drawing.windowBehaviors.stationary
            | hs.drawing.windowBehaviors.fullScreenAuxiliary)
  wv:allowTextEntry(true)   -- needed so WORK lines can be edited in place
end

-- the full bill is wider (520px receipt) + taller (scrolls), and sits left of the brief card
local function fullFrame()
  local s = hs.screen.primaryScreen():frame()
  local w = 580                                            -- fits the 520px wide receipt + shadow
  local x = s.x + s.w - CFG.size.w - CFG.margin - w - 16   -- left of the brief card
  if x < s.x + CFG.margin then x = s.x + CFG.margin end
  return { x = x, y = s.y + CFG.margin, w = w, h = s.h - CFG.margin * 2 }
end

makeFullWebview = function()
  uccFull = hs.webview.usercontent.new("eod")
  uccFull:setCallback(onMessageFull)
  local masks = hs.webview.windowMasks
  wvFull = hs.webview.new(fullFrame(), { developerExtrasEnabled = false }, uccFull)
  wvFull:windowStyle(masks.borderless)
  wvFull:transparent(true)
  wvFull:shadow(false)
  wvFull:level(hs.drawing.windowLevels.floating)
  wvFull:behavior(hs.drawing.windowBehaviors.canJoinAllSpaces
                | hs.drawing.windowBehaviors.stationary
                | hs.drawing.windowBehaviors.fullScreenAuxiliary)
  wvFull:allowTextEntry(false)
end

function M.show(animate)
  if hideTimer then hideTimer:stop(); hideTimer = nil end  -- cancel a pending roll-up→hide
  if not wv then makeWebview() end
  curDate = curDate or today()
  -- Load the *already-cached* page immediately so the print-down plays at once
  -- (re-scanning ~/.claude takes ~1s and would make the toggle feel laggy).
  local path = DIR .. "/cache/" .. curDate .. ".html"
  if hs.fs.attributes(path) then
    loadN = loadN + 1
    wv:url("file://" .. path .. "?n=" .. loadN .. (animate and "#in" or ""))
  else
    rebuild(curDate, true, animate)        -- no cache yet (first ever run): build it
  end
  wv:show()
  shown = true
  -- then quietly refresh the content in the background, after the animation, if still up
  if curDate == today() then
    hs.timer.doAfter(1.3, function()
      if shown and wv then rebuild(curDate, false, false) end
    end)
  end
end

function M.showFull()
  if not wvFull then makeFullWebview() end
  curDate = curDate or today()
  fullShown = true
  local fp = DIR .. "/cache/" .. curDate .. "-full.html"
  if hs.fs.attributes(fp) then
    loadN = loadN + 1
    wvFull:url("file://" .. fp .. "?n=" .. loadN .. "#in")
  else
    rebuild(curDate, true, false)   -- not cached yet → build (loads via the fullShown path)
  end
  wvFull:frame(fullFrame())         -- re-place in case the screen changed
  wvFull:show()
end

function M.hideFull()
  if wvFull and fullShown then
    wvFull:evaluateJavaScript("window.playOut&&playOut()")
    hs.timer.doAfter(ROLL_OUT, function() if wvFull then wvFull:hide() end end)
  elseif wvFull then
    wvFull:hide()
  end
  fullShown = false
end

-- Weekly recap — built on demand (extract --weekly) and shown in the detail window.
function M.showWeekly()
  if not wvFull then makeFullWebview() end
  fullShown = true
  local t = hs.task.new(CFG.python, function(code, out)
    out = (out or ""):gsub("%s+$", "")
    local _, path = out:match("^(%S+)%s+(.+)$")
    if path and wvFull then
      loadN = loadN + 1
      wvFull:url("file://" .. path .. "?n=" .. loadN .. "#in")
      wvFull:frame(fullFrame()); wvFull:show()
    end
  end, { CFG.script, "--date", curDate or today(), "--weekly" })
  if t then t:setEnvironment(CFG.env); t:start() end
end

function M.hide()
  if hideTimer then hideTimer:stop(); hideTimer = nil end
  M.hideFull()                                            -- close the detail card too
  if wv and shown then
    wv:evaluateJavaScript("window.playOut&&playOut()")  -- roll the paper back up...
    hideTimer = hs.timer.doAfter(ROLL_OUT, function()    -- ...then hide once it's gone
      if wv then wv:hide() end
      hideTimer = nil
    end)
  elseif wv then
    wv:hide()
  end
  shown = false
end

function M.toggle()
  if shown then M.hide() else M.show(true) end
end

-- ── lifecycle ──────────────────────────────────────────────────────────────────
local function scheduleMidnight()
  -- fire just after 00:00 to roll the panel onto the new day, then re-arm
  local now = os.time()
  local n = os.date("*t", now + 86400); n.hour, n.min, n.sec = 0, 0, 30
  local secs = os.difftime(os.time(n), now)
  midnightTimer = hs.timer.doAfter(secs, function()
    curDate = today()
    if shown then rebuild(curDate, true, false) end  -- if hidden, next show rebuilds anyway
    scheduleMidnight()
  end)
end

-- end-of-day reminder (weekdays): build today fresh, then notify; clicking opens the panel
local function scheduleReminder()
  if not CFG.reminderOn then return end
  local now = os.time()
  local n = os.date("*t", now); n.hour, n.min, n.sec = CFG.reminderHour, CFG.reminderMin, 0
  local fire = os.time(n)
  if fire <= now then fire = fire + 86400 end          -- already past → tomorrow
  reminderTimer = hs.timer.doAt(os.date("%H:%M:%S", fire), "1d", function()
    local wd = tonumber(os.date("%w"))                 -- 0=Sun … 6=Sat
    if wd == 0 or wd == 6 then return end              -- weekdays only
    rebuild(today(), true, false)                      -- make sure today's summary is fresh
    hs.notify.new(function() M.show(true) end, {
      title = "EOD", subTitle = "Your work update is ready — review & send",
      hasActionButton = true, actionButtonTitle = "Open",
    }):send()
  end, true)
end

function M.start()
  if bar then M.stop() end
  curDate = today()

  bar = hs.menubar.new()
  if bar then
    bar:setTitle(hs.styledtext.new("▤", { font = { name = "Menlo", size = 14 } }))
    bar:setTooltip("EOD — today's work")
    bar:setMenu(function() return {
      { title = "Show / hide panel", fn = M.toggle },
      { title = "Jump to today",     fn = function() curDate = today(); M.show(true) end },
      { title = "Refresh now",       fn = function() rebuild(curDate, true, false) end },
      { title = "-" },
      { title = "This week's summary", fn = M.showWeekly },
      { title = "Open work history",   fn = function() hs.execute("open '" .. DIR .. "/cache/worklog-history.md'") end },
      { title = "-" },
      { title = "Reveal cache folder", fn = function() hs.execute("open " .. DIR .. "/cache") end },
    } end)
  end

  if CFG.hotkey then
    hs.hotkey.bind(CFG.hotkey.mods, CFG.hotkey.key, M.toggle)
  end

  refreshTimer = hs.timer.doEvery(CFG.refreshEvery, function()
    -- only auto-refresh while visible and viewing the live (today) page
    if shown and curDate == today() then rebuild(curDate, false, false) end
  end)
  scheduleMidnight()
  scheduleReminder()

  -- begin app-usage tracking (runs whether or not the panel is visible)
  usage.date = today()
  usage.secs = usageLoad(usage.date)
  usageTimer      = hs.timer.doEvery(CFG.usagePoll, usageSample)
  usageFlushTimer = hs.timer.doEvery(60, usageFlush)   -- persist at most once/min

  if CFG.showAtStart then M.show(true) end
  log("started")
end

function M.stop()
  if usageTimer then usageTimer:stop(); usageTimer = nil end
  if usageFlushTimer then usageFlushTimer:stop(); usageFlushTimer = nil end
  usageFlush()
  if refreshTimer then refreshTimer:stop(); refreshTimer = nil end
  if midnightTimer then midnightTimer:stop(); midnightTimer = nil end
  if reminderTimer then reminderTimer:stop(); reminderTimer = nil end
  if hideTimer then hideTimer:stop(); hideTimer = nil end
  if dragTap then dragTap:stop(); dragTap = nil end
  if wvFull then wvFull:delete(); wvFull = nil end
  if uccFull then uccFull = nil end
  fullShown = false
  if wv then wv:delete(); wv = nil end
  if ucc then ucc = nil end
  if bar then bar:delete(); bar = nil end
end

return M
