-- ~/.hammerspoon/init.lua — EOD standalone loader.
-- If you ALREADY use Hammerspoon, do NOT overwrite your init.lua. Instead copy the
-- two non-comment lines below into it, pointing the path at wherever this folder lives.
local here = (debug.getinfo(1, "S").source:match("^@(.*)/") or ".")
package.path = package.path .. ";" .. here .. "/?.lua"
local ok, wl = pcall(require, "eod")
if ok and wl then wl.start() else hs.alert("eod load failed: " .. tostring(wl)) end
