"""The share card as a PNG, drawn by the WebKit that already ships with macOS.

No third-party renderer, no screen capture. osascript runs a few lines of
JavaScript for Automation that load the card into an off-screen WKWebView, ask
WebKit for a snapshot, and write it out at a fixed pixel size. Nothing is shown,
nothing is captured from the screen, so it needs no Screen Recording permission,
and it works whether or not the panel is open. Off macOS it reports failure
rather than pretending.
"""

import os
import subprocess
import sys

OSASCRIPT = "/usr/bin/osascript"
SCALE = 2          # 1200x675 points -> 2400x1350 pixels: same 16:9, sharp when zoomed

# Prints OK or FAIL <why>. Fixed pixel size whatever the display's backing scale,
# so a Retina laptop and an external 1x monitor produce the same file.
SNAPSHOT_JXA = r"""
ObjC.import('AppKit'); ObjC.import('WebKit');
function run(argv){
  var src = argv[0], out = argv[1], w = +argv[2], h = +argv[3], scale = +argv[4];
  $.NSApplication.sharedApplication.setActivationPolicy(2);   // prohibited: no Dock icon
  var loop = $.NSRunLoop.currentRunLoop;
  function spin(until){ var t0 = Date.now();
    while (!until() && Date.now() - t0 < 15000) loop.runUntilDate($.NSDate.dateWithTimeIntervalSinceNow(0.05)); }
  var rect = $.NSMakeRect(0, 0, w, h);
  var wv = $.WKWebView.alloc.initWithFrameConfiguration(rect, $.WKWebViewConfiguration.alloc.init);
  var win = $.NSWindow.alloc.initWithContentRectStyleMaskBackingDefer(
    $.NSMakeRect(-20000, -20000, w, h), 0, 2, false);           // never ordered on screen
  win.contentView = wv;
  var url = $.NSURL.fileURLWithPath(src);
  wv.loadFileURLAllowingReadAccessToURL(url, url.URLByDeletingLastPathComponent);
  // isLoading is still false straight after the call, and the blank page that
  // comes first is already 'complete', so wait for OUR document to be complete
  var ready = false, asked = false;
  spin(function(){
    if (!asked) { asked = true;
      wv.evaluateJavaScriptCompletionHandler('location.protocol + document.readyState', function(v){
        ready = !wv.isLoading && v && v.js === 'file:complete'; asked = false; }); }
    return ready; });
  if (!ready) return 'FAIL the card did not load';
  loop.runUntilDate($.NSDate.dateWithTimeIntervalSinceNow(0.3));  // let layout + fonts settle
  var img = null, done = false;
  wv.takeSnapshotWithConfigurationCompletionHandler($(), function(i){ img = i; done = true; });
  spin(function(){ return done; });
  if (!img || img.isNil()) return 'FAIL no snapshot';
  var rep = $.NSBitmapImageRep.alloc.initWithBitmapDataPlanesPixelsWidePixelsHighBitsPerSampleSamplesPerPixelHasAlphaIsPlanarColorSpaceNameBytesPerRowBitsPerPixel(
    null, w * scale, h * scale, 8, 4, true, false, $.NSDeviceRGBColorSpace, 0, 0);
  rep.size = $.NSMakeSize(w, h);
  $.NSGraphicsContext.saveGraphicsState;
  $.NSGraphicsContext.setCurrentContext($.NSGraphicsContext.graphicsContextWithBitmapImageRep(rep));
  img.drawInRect(rect);
  $.NSGraphicsContext.restoreGraphicsState;
  var png = rep.representationUsingTypeProperties($.NSBitmapImageFileTypePNG, $());
  return (png && png.writeToFileAtomically(out, true)) ? 'OK' : 'FAIL could not write ' + out;
}
"""


def html_to_png(html_path, png_path, w, h, scale=SCALE, timeout=60):
    """Draw html_path to png_path at w*scale x h*scale pixels.
    Returns None on success, or a one-line reason it did not happen."""
    if sys.platform != "darwin" or not os.path.exists(OSASCRIPT):
        return "the share image needs macOS (osascript + WebKit)"
    try:
        r = subprocess.run([OSASCRIPT, "-l", "JavaScript", "-",
                            os.path.abspath(html_path), os.path.abspath(png_path),
                            str(w), str(h), str(scale)],
                           input=SNAPSHOT_JXA, capture_output=True, text=True,
                           timeout=timeout)
    except (OSError, subprocess.SubprocessError) as e:
        return "osascript did not run: %s" % e
    said = (r.stdout or "").strip()
    if r.returncode != 0 or said != "OK":
        return (said or (r.stderr or "").strip() or "osascript exited %d" % r.returncode)[:300]
    if not os.path.exists(png_path):
        return "osascript said OK but wrote no file"
    return None
