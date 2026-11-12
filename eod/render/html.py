"""The receipt itself, as a self-contained document for hs.webview."""

import html, json, time
from datetime import datetime

from ..util import clean_title, fmt_dur, oneline, pretty_date
from ..config import APP_MAX, BRIEF_APPS, BRIEF_WEB, SIG, _sig_html
from .text import extra_lines, source_warnings, weekly_source_warnings, weekly_sections, apps_text, display_items, highlights_text, parse_warning, project_text, time_window, to_standup, to_text, to_text_full, to_text_weekly, web_text, work_item_count


CSS = """
:root{
  --surface:#14151a;          /* the dark desk the receipt sits on */
  --paper:#f3ecdd;            /* warm thermal paper */
  --ink:#2a2620;              /* warm near-black ink */
  --ink2:#9a8f7c;             /* faded ink */
  --line:#cdc2aa;             /* printed rule */
  --accent:#bf3d1f;           /* stamp red-orange */
  --mono:'SF Mono',ui-monospace,Menlo,'Courier New',monospace;
}
*{box-sizing:border-box}
html,body{margin:0}
body{background:transparent;font-family:var(--mono);-webkit-font-smoothing:antialiased}
/* transparent so only the paper shows on the desktop; padding leaves room for the shadow */
.surface{min-height:100vh;display:flex;justify-content:center;padding:16px 0 30px;background:transparent}
.grip{cursor:grab}
.grip:active{cursor:grabbing}
.hide{position:absolute;top:9px;right:11px;border:none!important;background:transparent!important;
  color:var(--ink2);font-size:13px;line-height:1;letter-spacing:0;padding:3px 5px}
.hide:hover{color:var(--accent)}

/* ── the paper ───────────────────────────────────────────────── */
.receipt{
  width:%W%px;background:var(--paper);color:var(--ink);
  padding:22px 22px 20px;position:relative;
  clip-path:%CLIP%;
  filter:drop-shadow(0 10px 22px rgba(0,0,0,.55));
  background-image:repeating-linear-gradient(0deg, rgba(0,0,0,.022) 0 1px, transparent 1px 3px);
  letter-spacing:.2px;
}
.receipt::after{ /* faint print fade / vignette */
  content:"";position:absolute;inset:0;pointer-events:none;clip-path:inherit;
  background:radial-gradient(120% 80% at 50% 50%, transparent 60%, rgba(120,100,60,.08));}

/* ── masthead ────────────────────────────────────────────────── */
.brand{text-align:center;font-size:20px;font-weight:700;letter-spacing:5px}
.brand b{color:var(--accent)}
.tag{text-align:center;font-size:9.5px;letter-spacing:3px;color:var(--ink2);margin-top:3px}
.stamp{display:block;width:max-content;margin:9px auto 2px;border:1.5px solid var(--accent);
  color:var(--accent);font-size:9px;letter-spacing:2px;padding:2px 8px;border-radius:3px;
  transform:rotate(-3deg);opacity:.9}

.rule{border-top:1px dashed var(--line);margin:11px 0}
.rule.solid{border-top:1.5px solid var(--ink)}
.rule.double{border-top:1.5px double var(--ink)}

/* key/value rows with dotted leaders */
.kv{display:flex;align-items:flex-end;font-size:11px;line-height:1.7}
.kv .k{color:var(--ink2);text-transform:uppercase;letter-spacing:1px;white-space:nowrap}
.kv .dots{flex:1;border-bottom:1px dotted var(--line);margin:0 5px 4px}
.kv .v{white-space:nowrap}
.kv.tot{font-size:11.5px}
.kv.tot .k{color:var(--ink)}
.kv.tot .v{font-weight:700}

/* nav row */
.nav{display:flex;gap:6px;justify-content:center;margin:10px 0 2px}
button{font-family:var(--mono);font-size:9.5px;letter-spacing:1.5px;text-transform:uppercase;
  color:var(--ink);background:transparent;border:1px dashed var(--line);border-radius:4px;
  padding:5px 9px;cursor:pointer;transition:.12s}
button:hover{border-color:var(--ink);background:rgba(0,0,0,.04)}
button:disabled{opacity:.4;cursor:not-allowed}

/* section label (CLAUDE CODE / SCREEN TIME / WEB) */
.sect{font-size:9.5px;letter-spacing:3px;color:var(--accent);text-transform:uppercase;
  font-weight:700;margin:4px 0 2px;text-align:center}

/* departments (= projects) */
.dept{margin:9px 0}
.depthead{display:flex;align-items:flex-end;font-weight:700;font-size:12px;
  text-transform:uppercase;letter-spacing:1px}
.depthead .nm{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:215px}
.depthead .dots{flex:1;border-bottom:1px dotted var(--line);margin:0 6px 4px}
.depthead .qty{color:var(--ink2);font-weight:700;white-space:nowrap}
.depthead .cp{margin-left:7px;padding:1px 5px;font-size:9px;border-style:solid;opacity:.55}
.depthead .cp:hover{opacity:1}
.item{display:flex;gap:8px;font-size:11.5px;line-height:1.45;margin:3px 0 0 2px}
.item .t{flex:1}
.item .t b{color:var(--accent);font-weight:700;margin-right:5px}
.item .tm{color:var(--ink2);font-size:10px;white-space:nowrap;padding-top:1px}
.item.subt{margin-left:14px}
.item.subt .t{color:var(--ink2);font-size:10.5px}
.htext.editing{outline:1px dashed var(--accent);background:rgba(191,61,31,.06);
  border-radius:3px;padding:0 3px;margin-left:-3px}
.edot{color:var(--accent);font-size:9px;margin-left:4px}
.dim{color:var(--ink2);font-size:10px}
.del{display:none;border:none!important;background:transparent!important;color:var(--ink2);
  font-size:11px;line-height:1;padding:0 4px;cursor:pointer;align-self:flex-start;margin-top:2px}
.del:hover{color:var(--accent)}
#workList[data-edit='1'] .del{display:inline-block}
#workList[data-edit='1'] .item{align-items:flex-start}
.dpick{font-family:var(--mono);font-size:9.5px;color:var(--ink);background:transparent;
  border:1px dashed var(--line);border-radius:4px;padding:4px 6px;cursor:pointer}
.dpick:hover{border-color:var(--ink)}

/* footer */
.end{text-align:center;font-size:11px;letter-spacing:3px;color:var(--ink);margin:6px 0 2px}
.barcode{height:46px;width:78%;margin:10px auto 4px;
  background-repeat:repeat-x;background-size:21px 100%;
  background-image:repeating-linear-gradient(90deg,
    var(--ink) 0 2px, transparent 2px 5px, var(--ink) 5px 6px, transparent 6px 11px,
    var(--ink) 11px 14px, transparent 14px 16px, var(--ink) 16px 17px, transparent 17px 21px);}
.bcnum{text-align:center;font-size:10px;letter-spacing:3px;color:var(--ink)}
.actions{display:flex;gap:7px;justify-content:center;margin:12px 0 4px}
.copyall{border-style:solid;border-color:var(--ink);font-weight:700;padding:7px 14px}
.copyall:hover{background:var(--ink);color:var(--paper)}
.copyall.primary{background:var(--ink);color:var(--paper)}
.copyall.primary:hover{opacity:.88}
.copyall.seeall{border-style:solid;border-color:var(--line);color:var(--ink);font-weight:400}
.copyall.seeall:hover{background:transparent;border-color:var(--ink);color:var(--ink)}
/* never show this: a quiet control that appears on hover or keyboard focus */
.inc{font-size:9px;letter-spacing:.5px;color:var(--ink2);display:flex;gap:4px;align-items:center;white-space:nowrap}
.nv{border:0;background:transparent;color:var(--ink2);font-size:10px;padding:0 0 0 6px;opacity:0;cursor:pointer}
.item:hover .nv,.kv:hover .nv,.nv:focus-visible{opacity:1}
.nv:hover{color:var(--accent)}
/* send preview */
.sheet{position:fixed;inset:0;background:rgba(0,0,0,.28);display:flex;align-items:flex-end;justify-content:center;padding:12px}
.sheet .box{background:var(--paper);color:var(--ink);border:1px solid var(--ink);width:100%;max-height:80%;overflow:auto;padding:12px;font-size:10.5px}
.sheet .to{font-weight:700;letter-spacing:1px;text-transform:uppercase;margin-bottom:6px}
.sheet pre{white-space:pre-wrap;font-family:var(--mono);font-size:10.5px;margin:0 0 10px;border-top:1px dashed var(--line);border-bottom:1px dashed var(--line);padding:8px 0}
.sheet .row{display:flex;gap:7px;justify-content:flex-end}
.ts{text-align:center;font-size:9px;letter-spacing:1px;color:var(--ink2);margin-top:8px}
.sig{color:var(--ink);font-weight:700;letter-spacing:2px}
.warn{color:var(--accent);border:1px dashed var(--accent);border-radius:3px;font-size:9.5px;letter-spacing:1px;text-transform:uppercase;text-align:center;padding:4px 6px;margin:6px 0}
.empty{text-align:center;color:var(--ink2);font-size:11px;letter-spacing:2px;padding:34px 0}

.toast{position:fixed;left:50%;bottom:18px;transform:translateX(-50%) translateY(16px);
  background:var(--ink);color:var(--paper);font-size:10px;letter-spacing:2px;text-transform:uppercase;
  padding:8px 16px;border-radius:3px;opacity:0;transition:.22s;pointer-events:none}
.toast.show{opacity:1;transform:translateX(-50%) translateY(0)}
.status{font-size:10px;color:var(--accent);border:1px dashed var(--accent);padding:4px 6px;margin:6px 0;display:flex;gap:6px;align-items:center;justify-content:center}
.status button{padding:2px 6px}
.undo{position:fixed;left:50%;bottom:18px;transform:translateX(-50%);background:var(--ink);color:var(--paper);font-size:10px;
  letter-spacing:1px;padding:6px 8px 6px 14px;display:flex;gap:10px;align-items:center;z-index:5}
.undo button{color:var(--paper);border-color:var(--paper);padding:3px 8px}
.prov{font-size:9.5px;color:var(--ink2);margin:2px 0 4px;letter-spacing:.3px}

/* ── print / unroll animation (paper fed from a slot at the top) ── */
.roll{transform-origin:top center}
html.anim-in  .roll{animation:printDown .85s cubic-bezier(.18,.86,.24,1) both}
html.anim-out .roll{animation:rollUp   .42s cubic-bezier(.45,0,.7,.25) both}
@keyframes printDown{
  0%{clip-path:inset(0 0 100% 0);transform:translateY(-4px)}
  100%{clip-path:inset(0 0 0 0);transform:translateY(0)}}
@keyframes rollUp{
  0%{clip-path:inset(0 0 0 0)}
  100%{clip-path:inset(0 0 100% 0);transform:translateY(-3px)}}
@media (prefers-reduced-motion:reduce){
  html.anim-in .roll,html.anim-out .roll{animation-duration:.001s}}
"""


JS = """
function send(m){try{window.webkit.messageHandlers.eod.postMessage(m);return true}catch(e){return false}}
function toast(t){var el=document.getElementById('toast');el.textContent=t;el.classList.add('show');
clearTimeout(window._tt);window._tt=setTimeout(function(){el.classList.remove('show')},1300)}
function copyText(txt,label,what){
  if(!send({action:'copy',text:txt,what:what||''})){ // browser fallback
    var ta=document.createElement('textarea');ta.value=txt;document.body.appendChild(ta);
    ta.select();try{document.execCommand('copy')}catch(e){}ta.remove();}
  toast((label||'Copied')+' ✓');}
function copyEl(id,label){copyText(document.getElementById(id).textContent,label,id)}
// Refresh status from the app (F11): a quiet line that stays until the next good refresh.
window.setStatus=function(msg,retry){var r=document.querySelector('.receipt');if(!r)return;
  var el=document.getElementById('status');if(!msg){if(el)el.remove();return}
  if(!el){el=document.createElement('div');el.id='status';el.className='status';el.setAttribute('role','status');r.insertBefore(el,r.children[2]||null)}
  el.textContent=msg+' ';if(retry){var b=document.createElement('button');b.textContent='Retry';b.onclick=function(){refresh()};el.appendChild(b)}};
window.isEditing=function(){var l=document.getElementById('workList');return !!(l&&l.getAttribute('data-edit')==='1')};
function neverShow(k,v){if(send({action:'neverShow',kind:k,value:v}))toast('Hiding…');else toast('Hiding works from the app')}
function copyReport(){var L=[document.getElementById('wkHead').textContent,''];
  document.querySelectorAll('.wsec').forEach(function(sec){var cb=sec.querySelector('input');if(cb&&!cb.checked)return;
    L.push(sec.getAttribute('data-title').toUpperCase());sec.querySelectorAll('.wl').forEach(function(x){L.push('\\u2022 '+x.textContent)});L.push('')});
  copyText(L.join('\\n').replace(/\\n+$/,'\\n'),'Weekly report copied')}
function nav(d){send({action:'nav',delta:d})}
function goDate(v){if(v)send({action:'goDate',date:v})}
function refresh(){send({action:'refresh'});toast('Refreshing…')}
function regen(){send({action:'regen'});toast('Re-summarizing…')}
function _enterEdit(){
  var list=document.getElementById('workList'),b=document.getElementById('editBtn');
  list.querySelectorAll('.htext').forEach(function(s){s.contentEditable='true';s.classList.add('editing');});
  list.setAttribute('data-edit','1');if(b)b.textContent='Save';
  if(!list._keys){list._keys=true;list.addEventListener('keydown',_editKeys)}
}
// Keyboard model while editing (F16): Enter adds a line, Cmd+Enter or Cmd+S saves,
// Esc throws the edits away, Backspace on an empty line deletes it.
function _editKeys(e){
  var list=document.getElementById('workList');if(!list||list.getAttribute('data-edit')!=='1')return;
  var cur=e.target.closest&&e.target.closest('.item');
  if((e.metaKey||e.ctrlKey)&&(e.key==='Enter'||e.key==='s')){e.preventDefault();toggleEdit();return}
  if(e.key==='Escape'){e.preventDefault();send({action:'refresh'});toast('Edits discarded');return}
  if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();addLine(cur);return}
  if(e.key==='Backspace'&&cur&&!e.target.textContent.trim()){
    e.preventDefault();var prev=cur.previousElementSibling;cur.remove();
    if(prev){var t=prev.querySelector('.htext');if(t){t.focus();document.getSelection().selectAllChildren(t);document.getSelection().collapseToEnd()}}}
}
function _collect(){
  var items=[];document.querySelectorAll('#workList .htext').forEach(function(s){
    var t=s.textContent.replace(/\\s+/g,' ').trim();if(t)items.push(t);});
  return items;
}
function toggleEdit(){
  var list=document.getElementById('workList'),b=document.getElementById('editBtn');
  if(!list)return;
  if(list.getAttribute('data-edit')!=='1'){
    _enterEdit();var f=list.querySelector('.htext');if(f)f.focus();
    toast('Enter adds a line, Cmd+Enter saves, Esc cancels');
  }else{
    var items=_collect();
    list.querySelectorAll('.htext').forEach(function(s){s.contentEditable='false';s.classList.remove('editing');});
    list.setAttribute('data-edit','0');if(b)b.textContent='Edit';
    send({action:'saveEdits',items:items});toast('Saved');
  }
}
function addLine(after){
  var list=document.getElementById('workList');if(!list)return;
  if(list.getAttribute('data-edit')!=='1')_enterEdit();
  var d=document.createElement('div');d.className='item';
  d.innerHTML="<span class='t'><b>•</b><span class='htext editing' contenteditable='true'></span></span>"+
    "<button class='del' onclick='delLine(this)' title='Delete line' aria-label='Delete line'>✕</button>";
  if(after&&after.parentNode===list)list.insertBefore(d,after.nextSibling);else list.appendChild(d);
  d.querySelector('.htext').focus();
}
// Undo (F15): a short bar with an Undo button instead of a silent, final delete.
function showUndo(msg,fn){var old=document.getElementById('undoBar');if(old)old.remove();
  var u=document.createElement('div');u.id='undoBar';u.className='undo';u.setAttribute('role','status');
  u.textContent=msg+' ';var b=document.createElement('button');b.textContent='Undo';
  b.onclick=function(){u.remove();fn()};u.appendChild(b);document.body.appendChild(u);
  clearTimeout(window._ut);window._ut=setTimeout(function(){u.remove()},6000)}
window.showUndo=showUndo;
function delLine(el){var it=el.closest('.item');if(!it)return;var parent=it.parentNode,next=it.nextSibling;it.remove();
  showUndo('Line deleted.',function(){parent.insertBefore(it,next)})}
function copyWork(){
  var list=document.getElementById('workList');
  if(list&&list.getAttribute('data-edit')==='1'){           // copy straight from your edits + persist
    var items=_collect();
    copyText(items.map(function(t){return '\\u2022 '+t}).join('\\n'),'Work update copied');
    send({action:'saveEdits',items:items});
  }else{copyEl('workText','Work update copied');}
}
function drag(e){if(e.button===0)send({action:'dragStart'})}
window.playOut=function(){var h=document.documentElement;h.classList.remove('anim-in');h.classList.add('anim-out')};
"""


# Added to the page only when send.txt exists, so a receipt without it is
# byte-for-byte what it always was. Send posts to a shared channel, so the first
# press only arms the button; the second, within a few seconds, sends.
# The button then stays disabled until eod.lua reports back through sendResult.
SEND_JS = """
function postUpdate(b){
  var l=document.getElementById('workList');
  if(l&&l.getAttribute('data-edit')==='1'){toast('Save your edits first');return}
  // Show exactly what goes where before anything leaves the Mac (F09).
  var old=document.getElementById('sendSheet');if(old)old.remove();
  var sh=document.createElement('div');sh.className='sheet';sh.id='sendSheet';
  sh.innerHTML="<div class='box' role='dialog' aria-modal='true' aria-label='Send preview'><div class='to'></div><pre></pre>"+
    "<div class='row'><button class='copyall seeall' id='sendCancel'>Cancel</button><button class='copyall primary' id='sendGo'>Send now</button></div></div>";
  sh.querySelector('.to').textContent='To: '+((document.getElementById('sendTo')||{}).textContent||'');
  sh.querySelector('pre').textContent=(document.getElementById('updText')||{}).textContent||'';
  document.body.appendChild(sh);
  var close=function(){sh.remove();document.removeEventListener('keydown',esc)};
  var esc=function(e){if(e.key==='Escape')close()};document.addEventListener('keydown',esc);
  sh.querySelector('#sendCancel').onclick=close;
  sh.querySelector('#sendGo').onclick=function(){close();if(send({action:'post'})){b.disabled=true;toast('Sending…')}else toast('Send works from the widget')};
  sh.querySelector('#sendGo').focus()}
function sendResult(t){var b=document.getElementById('sendBtn');if(b)b.disabled=false;
var el=document.getElementById('toast');el.textContent=t;el.classList.add('show');
clearTimeout(window._tt);window._tt=setTimeout(function(){el.classList.remove('show')},4000)}
"""


def clip_path(w=340, step=10, depth=6):
    """A torn-paper silhouette: zigzag top & bottom edges, straight sides."""
    n = w // step
    top = [f"{i*step}px {0 if i % 2 == 0 else depth}px" for i in range(n + 1)]
    bot = [f"{i*step}px " + ("100%" if i % 2 == 0 else f"calc(100% - {depth}px)")
           for i in range(n, -1, -1)]
    return "polygon(" + ", ".join(top + bot) + ")"


def provenance(data):
    """Where the WORK lines came from, in one line (audit F13)."""
    sm = data.get("summary") or {}
    by, at, note = sm.get("by"), sm.get("at", ""), sm.get("note", "")
    if by == "claude":
        return "Summarized by Claude" + (" at " + at if at else "")
    if by == "ollama":
        return "Summarized on this Mac by Ollama" + (" at " + at if at else "")
    if by == "edited":
        return "Edited by you"
    if by == "stale":
        return ("Last summary " + at + ". " if at else "Last summary. ") + note
    if by == "offline":
        return "Offline summary. " + note
    if by == "off":
        return "Offline summary: AI tidy-up is off"
    return ""


def to_html(data, send_to=()):
    """The brief card. `send_to` names the destinations in send.txt; empty
    means no Send button and no trace of it in the page."""
    css = CSS.replace("%CLIP%", clip_path(340)).replace("%W%", "340")
    esc = html.escape
    pcount = data["project_count"]
    icount = work_item_count(data)
    t0, t1 = time_window(data)
    ref = "#" + data["date"].replace("-", "")

    P = [f"<!doctype html><html><head><meta charset='utf-8'>"
         # set the animate-in class before first paint so the paper starts hidden (no flash)
         "<script>if(location.hash.indexOf('in')>=0)document.documentElement.className='anim-in';</script>"
         f"<style>{css}</style></head>"
         "<body><div class='surface'><div class='roll'><div class='receipt'>"]

    # masthead (doubles as the drag handle)
    P.append("<button class='hide' onclick=\"send({action:'hide'})\" title='Hide (⌥⌃⌘W to reopen)'>✕</button>")
    P.append("<div class='grip' onmousedown='drag(event)'>")
    P.append("<div class='brand'>E<b>O</b>D</div>")
    P.append("<div class='tag'>DAILY WORK RECEIPT</div>")
    P.append("<div class='stamp'>WORK · SCREEN · WEB</div>")
    P.append("</div>")
    P.append("<div class='rule'></div>")
    P.append(f"<div class='kv'><span class='k'>Date</span><span class='dots'></span><span class='v'>{esc(pretty_date(data['date']))}</span></div>")
    P.append(f"<div class='kv'><span class='k'>Ref</span><span class='dots'></span><span class='v'>{ref}</span></div>")
    # Injectable so a snapshot is not hostage to the calendar. Production never
    # passes it; the tests always do.
    today_iso = data.get("_today") or datetime.now().astimezone().strftime("%Y-%m-%d")
    P.append("<div class='nav'>"
             "<button onclick='nav(-1)' title='Previous day'>◀</button>"
             f"<input type='date' class='dpick' value='{data['date']}' max='{today_iso}' "
             "onchange='goDate(this.value)' title='Jump to date'>"
             "<button onclick='nav(1)' title='Next day'>▶</button>"
             "<button onclick='refresh()' title='Refresh'>↻</button>"
             "</div>")
    # A contradiction the reader can act on, printed where they cannot miss
    # it, rather than an empty section that looks like a quiet day.
    _w = parse_warning(data)
    if _w:
        P.append("<div class='warn'>! " + esc(_w) + "</div>")
    # A source that was configured and then failed. Printing this is the whole
    # promise of the source contract; leaving it in the JSON only would recreate
    # the exact bug the contract exists to prevent.
    for _sw in source_warnings(data):
        P.append("<div class='warn'>! " + esc(_sw) + "</div>")
    P.append("<div class='rule double'></div>")

    apps = data.get("apps", [])
    web  = data.get("web", [])
    app_total = sum(a["secs"] for a in apps)
    web_total = sum(d["count"] for d in web)

    if not (data["projects"] or apps or web):
        _warn = parse_warning(data)
        if _warn:
            P.append("<div class='empty'>! " + esc(_warn.upper()) +
                     "<br><span style='font-size:9px'>EOD couldn't read today's sessions. Update EOD, or report it on GitHub.</span></div>")
        else:
            P.append("<div class='empty'>— NO ACTIVITY LOGGED —</div>")
    else:
        # ── Work: curated AI highlights (the manager-ready update; editable) ──
        if data.get("highlights"):
            edited_note = " <span class='edot' title='hand-edited'>✎</span>" if data.get("edited") else ""
            P.append("<div class='depthead'><span class='nm'>WORK" + edited_note + "</span>"
                     "<span class='dots'></span>"
                     f"<span class='qty'>×{len(data['highlights'])}</span>"
                     "<button class='cp' onclick='copyWork()' title='Copy work update'>⧉</button>"
                     "<button class='cp' id='editBtn' onclick='toggleEdit()' title='Edit lines' aria-label='Edit lines'>Edit</button>"
                     "<button class='cp' onclick='addLine()' title='Add a line'>＋</button>"
                     "<button class='cp' onclick='regen()' title='Re-summarize with AI'>⟳</button>"
                     "</div>")
            _pv = provenance(data)
            if _pv:
                P.append(f"<div class='prov' role='note'>{esc(_pv)}</div>")
            P.append("<div class='dept' id='workList' data-edit='0'>")
            for h in data["highlights"]:
                P.append("<div class='item'>"
                         f"<span class='t'><b>•</b><span class='htext'>{esc(h)}</span></span>"
                         "<button class='del' onclick='delLine(this)' title='Delete line'>✕</button>"
                         f"<button class='nv' onclick=\"neverShow('line',{esc(json.dumps(h))})\" "
                         "title='Never show lines like this' aria-label='Never show this line'>hide</button></div>")
            P.append("</div>")
            P.append(f"<div id='workText' style='display:none'>{esc(highlights_text(data))}</div>")
        # ── Fallback: per-project view (only when AI polish unavailable) ──
        elif data["projects"]:
            P.append("<div class='sect'>WORK</div>")
            _pv = provenance(data)
            if _pv:
                P.append(f"<div class='prov' role='note'>{esc(_pv)}</div>")
            for i, p in enumerate(data["projects"]):
                pid = f"p{i}"
                items = display_items(p)
                P.append("<div class='dept'><div class='depthead'>")
                P.append(f"<span class='nm'>{esc(p['name'])}</span>")
                P.append("<span class='dots'></span>")
                P.append(f"<span class='qty'>×{len(items)}</span>")
                P.append(f"<button class='cp' onclick=\"copyEl('{pid}','{esc(p['name'])} copied')\">⧉</button>")
                P.append("</div>")
                for it in items:
                    tm = f"<span class='tm'>{it['time']}</span>" if it.get("time") else ""
                    P.append("<div class='item'>"
                             f"<span class='t'><b>•</b>{esc(it['text'])}</span>{tm}</div>")
                P.append("</div>")
                P.append(f"<div id='{pid}' style='display:none'>{esc(project_text(p))}</div>")

        # ── Screen time (app usage) ──
        if apps:
            P.append("<div class='rule'></div>")
            P.append("<div class='depthead'><span class='nm'>SCREEN TIME</span>"
                     "<span class='dots'></span>"
                     f"<span class='qty'>{fmt_dur(app_total)}</span>"
                     "<button class='cp' onclick=\"copyEl('appsText','Screen time copied')\">⧉</button></div>")
            for a in apps[:BRIEF_APPS]:
                P.append(f"<div class='kv'><span class='k'>{esc(a['name'])}</span>"
                         "<span class='dots'></span>"
                         f"<span class='v'>{fmt_dur(a['secs'])}</span>"
                         f"<button class='nv' onclick=\"neverShow('app',{esc(json.dumps(a['name']))})\" "
                         f"title='Never show this app' aria-label='Never show {esc(a['name'])}'>hide</button></div>")
            P.append(f"<div id='appsText' style='display:none'>{esc(apps_text(data))}</div>")

        # ── Web (browser history) ──
        if web:
            P.append("<div class='rule'></div>")
            P.append("<div class='depthead'><span class='nm'>WEB</span>"
                     "<span class='dots'></span>"
                     f"<span class='qty'>×{web_total}</span>"
                     "<button class='cp' onclick=\"copyEl('webText','Web activity copied')\">⧉</button></div>")
            for d in web[:BRIEF_WEB]:
                P.append("<div class='item'>"
                         f"<span class='t'><b>•</b>{esc(d['host'])}</span>"
                         f"<span class='tm'>×{d['count']}</span>"
                         f"<button class='nv' onclick=\"neverShow('site',{esc(json.dumps(d['host']))})\" "
                         f"title='Never show this site' aria-label='Never show {esc(d['host'])}'>hide</button></div>")
            P.append(f"<div id='webText' style='display:none'>{esc(web_text(data))}</div>")

    # totals
    # A plugin's own items. Without this they reached the document only inside the
    # hidden copy block, i.e. invisible on the card unless you pasted it somewhere,
    # which is not what "it shows on the receipt" means.
    _extra = extra_lines(data)
    if _extra:
        _seen = None
        for _label, _txt in _extra:
            if _label != _seen:
                P.append("<div class='rule'></div><div class='sect'>" + esc(_label) + "</div>")
                _seen = _label
            P.append("<div class='item'><span class='t'><b>&bull;</b>" + esc(_txt) + "</span></div>")
    P.append("<div class='rule'></div>")
    P.append(f"<div class='kv tot'><span class='k'>Projects</span><span class='dots'></span><span class='v'>{pcount}</span></div>")
    P.append(f"<div class='kv tot'><span class='k'>Work items</span><span class='dots'></span><span class='v'>{icount}</span></div>")
    if apps:
        P.append(f"<div class='kv tot'><span class='k'>Screen</span><span class='dots'></span><span class='v'>{fmt_dur(app_total)}</span></div>")
    if web:
        P.append(f"<div class='kv tot'><span class='k'>Sites</span><span class='dots'></span><span class='v'>{len(web)}</span></div>")
    P.append(f"<div class='kv tot'><span class='k'>From</span><span class='dots'></span><span class='v'>{t0}</span></div>")
    P.append(f"<div class='kv tot'><span class='k'>To</span><span class='dots'></span><span class='v'>{t1}</span></div>")
    P.append("<div class='rule double'></div>")

    P.append("<div class='end'>END OF DAY</div>")
    P.append("<div class='barcode'></div>")
    P.append(f"<div class='bcnum'>{data['date'].replace('-','')}{' · ' + esc(SIG) if SIG else ''}</div>")
    # Four buttons do not fit one 340px row: let the row wrap rather than break
    # labels across lines. Only when Send is there, so other receipts are unchanged.
    P.append(("<div class='actions' style='flex-wrap:wrap;row-gap:7px;white-space:nowrap'>"
              if send_to else "<div class='actions'>") +
             "<button class='copyall primary' onclick=\"copyEl('updText','Update copied')\" "
             + ("disabled title='Nothing to copy yet: no work recorded' " if to_standup(data) is None else "") +
             "title='Copy the work update: work lines only, no screen time or sites'>⎙ Copy update</button>"
             "<button class='copyall seeall' onclick=\"send({action:'full'})\" title='Everything from today'>Full day</button>"
             "<button class='copyall' onclick=\"send({action:'share'});toast('Drawing the image…')\" "
             "title='Copy the day as an image for X / LinkedIn' aria-label='Share as image'>⇪</button>"
             + (f"<button id='sendBtn' onclick='postUpdate(this)' "
                f"title='Post the work update to {esc(', '.join(send_to))}'"
                + (" disabled" if to_standup(data) is None else "") + ">↗ Send</button>"
                if send_to else "") +
             "</div>")
    P.append(f"<div class='ts'>updated {esc(data['generated_at'][11:16])} · ~/.claude{_sig_html()}</div>")

    P.append(f"<div id='allText' style='display:none'>{esc(to_text(data))}</div>")
    # What "Copy update" and Send share: work lines only (F01). Screen time and
    # browsing stay on the Mac unless you copy them on purpose.
    P.append(f"<div id='updText' style='display:none'>{esc(to_standup(data) or '')}</div>")
    if send_to:
        P.append(f"<div id='sendTo' style='display:none'>{esc(', '.join(send_to))}</div>")
    P.append("</div></div></div>")  # receipt, roll, surface
    P.append("<div class='toast' id='toast'></div>")
    P.append(f"<script>{JS}</script>" + (f"<script>{SEND_JS}</script>" if send_to else "")
             + "</body></html>")
    out = "".join(P)
    return out


def to_html_full(data):
    """The 'See full bill' card: everything, in detail (opened as a second window)."""
    css = CSS.replace("%CLIP%", clip_path(520)).replace("%W%", "520")
    esc = html.escape
    apps = data.get("apps", [])
    web  = data.get("web", [])

    P = [f"<!doctype html><html><head><meta charset='utf-8'>",
         "<script>if(location.hash.indexOf('in')>=0)document.documentElement.className='anim-in';</script>",
         f"<style>{css}</style></head>",
         "<body><div class='surface'><div class='roll'><div class='receipt'>"]

    P.append("<button class='hide' onclick=\"send({action:'hide'})\" title='Close'>✕</button>")
    P.append("<div class='grip' onmousedown='drag(event)'>")
    P.append("<div class='brand'>E<b>O</b>D</div>")
    P.append("<div class='tag'>FULL BILL · ALL ACTIVITY</div>")
    P.append("</div>")
    P.append("<div class='rule'></div>")
    P.append(f"<div class='kv'><span class='k'>Date</span><span class='dots'></span><span class='v'>{esc(pretty_date(data['date']))}</span></div>")
    # A contradiction the reader can act on, printed where they cannot miss
    # it, rather than an empty section that looks like a quiet day.
    _w = parse_warning(data)
    if _w:
        P.append("<div class='warn'>! " + esc(_w) + "</div>")
    # A source that was configured and then failed. Printing this is the whole
    # promise of the source contract; leaving it in the JSON only would recreate
    # the exact bug the contract exists to prevent.
    for _sw in source_warnings(data):
        P.append("<div class='warn'>! " + esc(_sw) + "</div>")
    P.append("<div class='rule double'></div>")

    if not (data["projects"] or apps or web or data.get("commits") or data.get("meetings")):
        _warn = parse_warning(data)
        if _warn:
            P.append("<div class='empty'>! " + esc(_warn.upper()) +
                     "<br><span style='font-size:9px'>SEE cache/polish-error.log</span></div>")
        else:
            P.append("<div class='empty'>— NO ACTIVITY LOGGED —</div>")
    else:
        # Curated, readable detailed breakdown (same voice as the brief, just more granular).
        if data.get("detailed"):
            P.append("<div class='sect'>WORK — DETAILED</div>")
            for g in data["detailed"]:
                P.append("<div class='dept'><div class='depthead'>")
                P.append(f"<span class='nm'>{esc(g['area'])}</span><span class='dots'></span>")
                P.append(f"<span class='qty'>×{len(g['items'])}</span></div>")
                for it in g["items"]:
                    P.append("<div class='item'>"
                             f"<span class='t'><b>•</b>{esc(it)}</span></div>")
                P.append("</div>")
        # Fallback: only if AI detail isn't available — raw per-session view.
        elif data["projects"]:
            P.append("<div class='sect'>CLAUDE CODE</div>")
            for p in data["projects"]:
                P.append("<div class='dept'><div class='depthead'>")
                P.append(f"<span class='nm'>{esc(p['name'])}</span><span class='dots'></span>")
                P.append(f"<span class='qty'>×{len(p['sessions'])}</span></div>")
                for s in p["sessions"]:
                    P.append("<div class='item'>"
                             f"<span class='t'><b>•</b>{esc(clean_title(oneline(s['title'], 90)))}</span>"
                             f"<span class='tm'>{s['start']}</span></div>")
                    for pr in s["prompts"]:
                        P.append("<div class='item subt'>"
                                 f"<span class='t'>{esc(oneline(pr['text'], 150))}</span>"
                                 f"<span class='tm'>{pr['t']}</span></div>")
                P.append("</div>")
        if data.get("commits") or data.get("prs"):
            P.append("<div class='rule'></div><div class='sect'>SHIPPED</div>")
            for p in data.get("prs", []):
                P.append("<div class='item'>"
                         f"<span class='t'><b>•</b>PR #{p['number']} — {esc(p['title'])} "
                         f"<span class='dim'>{esc(p['repo'])}</span></span>"
                         f"<span class='tm'>{esc(p['state'])}</span></div>")
            byrepo = {}
            for c in data.get("commits", []):
                byrepo.setdefault(c["repo"], []).append(c)
            for repo, cs in byrepo.items():
                P.append("<div class='dept'><div class='depthead'>")
                P.append(f"<span class='nm'>{esc(repo)}</span><span class='dots'></span>")
                P.append(f"<span class='qty'>×{len(cs)}</span></div>")
                for c in cs:
                    P.append("<div class='item'>"
                             f"<span class='t'><b>•</b>{esc(c['subject'])}</span></div>")
                P.append("</div>")
        if data.get("meetings"):
            P.append("<div class='rule'></div><div class='sect'>MEETINGS</div>")
            for m in data["meetings"]:
                att = f" · {esc(m['attendees'])}" if m.get("attendees") else ""
                P.append("<div class='item'>"
                         f"<span class='t'><b>•</b>{esc(m['title'])}{att}</span>"
                         f"<span class='tm'>{esc(m['time'])}</span></div>")
        if data.get("docs"):
            P.append("<div class='rule'></div><div class='sect'>DOCUMENTS</div>")
            for d in data["docs"]:
                P.append("<div class='item'>"
                         f"<span class='t'><b>•</b>{esc(d['name'])}</span>"
                         f"<span class='tm'>{esc(d['folder'])}</span></div>")
        if apps:
            P.append("<div class='rule'></div><div class='sect'>SCREEN TIME</div>")
            for a in apps[:APP_MAX]:
                P.append(f"<div class='kv'><span class='k'>{esc(a['name'])}</span>"
                         "<span class='dots'></span>"
                         f"<span class='v'>{fmt_dur(a['secs'])}</span></div>")
        if web:
            P.append("<div class='rule'></div><div class='sect'>WEB</div>")
            for d in web:
                P.append("<div class='item'>"
                         f"<span class='t'><b>•</b>{esc(d['host'])}</span>"
                         f"<span class='tm'>×{d['count']}</span></div>")
                for t in d["titles"]:
                    P.append("<div class='item subt'>"
                             f"<span class='t'>{esc(t['title'])}</span>"
                             f"<span class='tm'>{t['t']}</span></div>")

    # A plugin's own items. Without this they reached the document only inside the
    # hidden copy block, i.e. invisible on the card unless you pasted it somewhere,
    # which is not what "it shows on the receipt" means.
    _extra = extra_lines(data)
    if _extra:
        _seen = None
        for _label, _txt in _extra:
            if _label != _seen:
                P.append("<div class='rule'></div><div class='sect'>" + esc(_label) + "</div>")
                _seen = _label
            P.append("<div class='item'><span class='t'><b>&bull;</b>" + esc(_txt) + "</span></div>")
    P.append("<div class='rule double'></div>")
    P.append("<div class='actions'><button class='copyall' onclick=\"copyEl('fullText','Full bill copied')\">⎙ Copy full bill</button></div>")
    P.append(f"<div class='ts'>updated {esc(data['generated_at'][11:16])} · ~/.claude + browser + apps{_sig_html()}</div>")
    P.append(f"<div id='fullText' style='display:none'>{esc(to_text_full(data))}</div>")
    P.append("</div></div></div>")
    P.append("<div class='toast' id='toast'></div>")
    P.append(f"<script>{JS}</script></body></html>")
    out = "".join(P)
    return out


# The share card is drawn once, at a fixed size, by a WebKit nobody is looking at
# (see image.py). 16:9 is the one shape both X and LinkedIn show whole in the
# feed without cropping; a portrait card would be cut to a strip on X.
SHARE_W, SHARE_H = 1200, 675
SHARE_MAX_LINES = 5              # six two-line highlights outgrow the card (measured)

SHARE_CSS = """
:root{--surface:#14151a;--paper:#f3ecdd;--ink:#2a2620;--ink2:#9a8f7c;--line:#cdc2aa;--accent:#bf3d1f;
  --mono:'SF Mono',ui-monospace,Menlo,'Courier New',monospace}
*{box-sizing:border-box}
html,body{margin:0;width:%CW%px;height:%CH%px;overflow:hidden}
body{background:var(--surface);font-family:var(--mono);-webkit-font-smoothing:antialiased;
  display:flex;align-items:center;justify-content:center;position:relative}
.receipt{width:%W%px;max-height:%MH%px;overflow:hidden;background:var(--paper);color:var(--ink);
  padding:26px 34px 22px;clip-path:%CLIP%;letter-spacing:.2px;
  background-image:repeating-linear-gradient(0deg, rgba(0,0,0,.022) 0 1px, transparent 1px 3px)}
.brand{text-align:center;font-size:30px;font-weight:700;letter-spacing:7px}
.brand b{color:var(--accent)}
.tag{text-align:center;font-size:12px;letter-spacing:4px;color:var(--ink2);margin-top:4px}
.rule{border-top:1px dashed var(--line);margin:10px 0}
.rule.double{border-top:2px double var(--ink)}
.kv{display:flex;align-items:flex-end;font-size:14px;line-height:1.6}
.kv .k{color:var(--ink2);text-transform:uppercase;letter-spacing:1px;white-space:nowrap}
.kv .dots{flex:1;border-bottom:1px dotted var(--line);margin:0 6px 5px}
.kv .v{white-space:nowrap;font-weight:700}
.tots{display:grid;grid-template-columns:1fr 1fr;column-gap:28px}
.sect{font-size:12px;letter-spacing:4px;color:var(--accent);font-weight:700;text-align:center;margin:0 0 6px}
.item{display:flex;gap:10px;font-size:16px;line-height:1.4;margin:5px 0 0}
.item b{color:var(--accent)}
.item .t{flex:1;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.more{color:var(--ink2);font-size:13px;letter-spacing:1px;margin:6px 0 0 20px}
.empty{text-align:center;color:var(--ink2);font-size:15px;letter-spacing:3px;padding:40px 0}
.end{text-align:center;font-size:13px;letter-spacing:4px;margin:4px 0 0}
.barcode{height:30px;width:60%;margin:9px auto 4px;background-repeat:repeat-x;background-size:21px 100%;
  background-image:repeating-linear-gradient(90deg,
    var(--ink) 0 2px, transparent 2px 5px, var(--ink) 5px 6px, transparent 6px 11px,
    var(--ink) 11px 14px, transparent 14px 16px, var(--ink) 16px 17px, transparent 17px 21px)}
.bcnum{text-align:center;font-size:11px;letter-spacing:3px}
.madewith{position:absolute;right:26px;bottom:18px;color:var(--line);font-size:12px;letter-spacing:3px}
.madewith b{color:var(--paper);letter-spacing:4px}
"""


def to_html_share(data):
    """The day as a social image: highlights and totals only, no controls.

    Deliberately narrower than the brief receipt. The image leaves your Mac the
    moment you post it, so it carries the curated highlights and nothing typed
    by you: no prompts, no session titles (an untitled session is titled by its
    first prompt), no sites, no app names, no warnings. Without highlights it
    shows the totals alone: project names are folder paths, and a path can
    carry your macOS username. No timestamp either, so the same day always
    draws the same picture. No script runs on it, and the CSP says so."""
    w = 700
    css = (SHARE_CSS.replace("%CLIP%", clip_path(w)).replace("%W%", str(w))
           .replace("%CW%", str(SHARE_W)).replace("%CH%", str(SHARE_H))
           .replace("%MH%", str(SHARE_H - 60)))
    esc = html.escape
    apps = data.get("apps", [])
    t0, t1 = time_window(data)

    P = ["<!doctype html><html><head><meta charset='utf-8'>",
         "<meta http-equiv='Content-Security-Policy' content=\"default-src 'none'; style-src 'unsafe-inline'\">",
         f"<style>{css}</style></head><body><div class='receipt'>",
         "<div class='brand'>E<b>O</b>D</div>",
         "<div class='tag'>DAILY WORK RECEIPT</div>",
         "<div class='rule'></div>",
         f"<div class='kv'><span class='k'>Date</span><span class='dots'></span>"
         f"<span class='v'>{esc(pretty_date(data['date']))}</span></div>",
         "<div class='rule double'></div>"]

    lines = data.get("highlights") or []
    if lines:
        P.append("<div class='sect'>WORK</div>")
        for txt in lines[:SHARE_MAX_LINES]:
            P.append(f"<div class='item'><b>•</b><span class='t'>{esc(txt)}</span></div>")
        if len(lines) > SHARE_MAX_LINES:
            P.append(f"<div class='more'>+ {len(lines) - SHARE_MAX_LINES} more</div>")
    elif not data["projects"]:
        P.append("<div class='empty'>NO ACTIVITY LOGGED</div>")

    tots = [("Projects", str(data["project_count"])), ("Work items", str(work_item_count(data)))]
    if apps:
        tots.append(("Screen", fmt_dur(sum(a["secs"] for a in apps))))
    tots.append(("Hours", f"{t0}–{t1}"))
    P.append("<div class='rule'></div><div class='tots'>")
    for k, v in tots:
        P.append(f"<div class='kv'><span class='k'>{k}</span><span class='dots'></span>"
                 f"<span class='v'>{esc(v)}</span></div>")
    P.append("</div><div class='rule double'></div>")
    P.append("<div class='end'>END OF DAY</div><div class='barcode'></div>")
    P.append(f"<div class='bcnum'>{esc(data['date'].replace('-',''))}{' · ' + esc(SIG) if SIG else ''}</div>")
    P.append("</div><div class='madewith'>made with <b>EOD</b></div></body></html>")
    return "".join(P)


WEEKLY_COPY_OFF = {"Time by app"}


def to_html_weekly(data):
    css = CSS.replace("%CLIP%", clip_path(520)).replace("%W%", "520")
    esc = html.escape
    P = ["<!doctype html><html><head><meta charset='utf-8'>",
         "<script>if(location.hash.indexOf('in')>=0)document.documentElement.className='anim-in';</script>",
         f"<style>{css}</style></head>",
         "<body><div class='surface'><div class='roll'><div class='receipt'>"]
    P.append("<button class='hide' onclick=\"send({action:'hide'})\" title='Close'>✕</button>")
    P.append("<div class='grip' onmousedown='drag(event)'>")
    P.append("<div class='brand'>E<b>O</b>D</div>")
    P.append("<div class='tag'>WEEKLY RECAP</div>")
    P.append("</div>")
    P.append("<div class='rule'></div>")
    P.append(f"<div class='kv'><span class='k'>Week</span><span class='dots'></span>"
             f"<span class='v'>{esc(pretty_date(data['week_start']))} → {esc(pretty_date(data['week_end']))}</span></div>")
    # Same promise as the daily: a source that failed this week is said out loud,
    # not left to look like a quiet week.
    for _sw in weekly_source_warnings(data):
        P.append("<div class='warn'>! " + esc(_sw) + "</div>")
    P.append("<div class='rule double'></div>")
    if not data.get("highlights"):
        P.append("<div class='empty'>— NO ACTIVITY THIS WEEK —</div>")
    else:
        wk_edited = " <span class='edot' title='hand-edited'>✎</span>" if data.get("edited") else ""
        P.append("<div class='depthead'><span class='nm'>KEY ACHIEVEMENTS" + wk_edited + "</span><span class='dots'></span>"
                 f"<span class='qty'>×{len(data['highlights'])}</span>"
                 "<button class='cp' onclick='copyWork()' title='Copy weekly update'>⧉</button>"
                 "<button class='cp' id='editBtn' onclick='toggleEdit()' title='Edit lines' aria-label='Edit lines'>Edit</button>"
                 "<button class='cp' onclick='addLine()' title='Add a line'>＋</button>"
                 "<button class='cp' onclick='regen()' title='Re-summarize the week'>⟳</button></div>")
        P.append("<div class='dept' id='workList' data-edit='0'>")
        for h in data["highlights"]:
            P.append("<div class='item'><span class='t'><b>•</b>"
                     f"<span class='htext'>{esc(h)}</span></span>"
                     "<button class='del' onclick='delLine(this)' title='Delete line'>✕</button></div>")
        P.append("</div>")
        P.append(f"<div id='workText' style='display:none'>{esc(chr(10).join('• ' + h for h in data['highlights']))}</div>")
        # The rest of the report. Key achievements are the editable list above.
        # Every section has an "include in copy" switch (F08). Time by app is
        # off by default: app hours read as surveillance in a manager update.
        secs = weekly_sections(data)
        if secs:
            t0, l0 = secs[0]
            P.append(f"<div class='wsec' data-title='{esc(t0)}' style='display:none'>"
                     + "".join(f"<span class='wl'>{esc(x)}</span>" for x in l0) + "</div>")
        for i, (title, lines) in enumerate(secs[1:], 1):
            on = "" if title in WEEKLY_COPY_OFF else " checked"
            P.append(f"<div class='rule'></div><div class='dept wsec' data-title='{esc(title)}'><div class='depthead'>"
                     f"<span class='nm'>{esc(title.upper())}</span><span class='dots'></span>"
                     f"<label class='inc'><input type='checkbox' id='inc{i}'{on}> include in copy</label></div>")
            for it in lines:
                P.append(f"<div class='item'><span class='t'><b>•</b><span class='wl'>{esc(it)}</span></span></div>")
            P.append("</div>")
        if data.get("detailed"):
            P.append("<div class='rule'></div><div class='sect'>BY AREA</div>")
            for g in data["detailed"]:
                P.append("<div class='dept'><div class='depthead'>")
                P.append(f"<span class='nm'>{esc(g['area'])}</span><span class='dots'></span>"
                         f"<span class='qty'>×{len(g['items'])}</span></div>")
                for it in g["items"]:
                    P.append(f"<div class='item'><span class='t'><b>•</b>{esc(it)}</span></div>")
                P.append("</div>")
    P.append("<div class='rule double'></div>")
    P.append("<div class='end'>END OF WEEK</div>")
    if data.get("highlights"):
        P.append("<div class='actions'><button class='copyall primary' onclick='copyReport()' "
                 "title='Copy the sections switched on above'>⎙ Copy report</button></div>")
        P.append(f"<div id='wkHead' style='display:none'>Weekly update: {esc(pretty_date(data['week_start']))} → {esc(pretty_date(data['week_end']))}</div>")
    P.append(f"<div id='wkText' style='display:none'>{esc(to_text_weekly(data))}</div>")
    P.append(f"<div class='ts'>updated {esc(data['generated_at'][11:16])}{_sig_html()}</div>")
    P.append("</div></div></div><div class='toast' id='toast'></div>")
    P.append(f"<script>{JS}</script></body></html>")
    out = "".join(P)
    return out
