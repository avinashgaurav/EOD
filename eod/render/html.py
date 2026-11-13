"""The receipt itself, as a self-contained document for hs.webview."""

import functools, html, json, os, time
from datetime import datetime

from ..util import clean_title, fmt_dur, oneline, pretty_date
from ..config import APP_MAX, BRIEF_APPS, BRIEF_WEB, SIG, _sig_html, app_path, brief_web_on
from .text import extra_lines, source_warnings, weekly_source_warnings, weekly_sections, apps_text, display_items, highlights_text, parse_warning, project_text, time_window, to_standup, to_text, to_text_full, to_text_weekly, web_text, work_item_count


CSS = """
@font-face{font-family:'Courier Prime';src:url('../eod/render/fonts/CourierPrime-Regular.ttf') format('truetype');font-weight:400}
@font-face{font-family:'Courier Prime';src:url('../eod/render/fonts/CourierPrime-Bold.ttf') format('truetype');font-weight:700}
/* Carbon-copy brand (audit section 5): white sheet, carbon-blue ink for anything
   you can act on, stamp red for the one signature mark. Every text pair passes
   WCAG AA in both themes. */
:root{
  --surface:#151416;          /* the desk behind the sheet (share image) */
  --paper:#FFFFFF;            /* the sheet */
  --ink:#1B1A18;              /* body text, 17.4:1 */
  --ink2:#5F5B54;             /* secondary text, 6.75:1 */
  --line:#E7DAD6;             /* dotted leaders and dashed rules, decorative only */
  --accent:#C8323C;           /* stamp red: signature only, 5.28:1 */
  --carbon:#24357A;           /* carbon blue: headings, buttons, focus, 11.26:1 */
  --copy:#F6D9DC;             /* carbon copy pink: edited lines, the shared preview */
  --on-carbon:#FFFFFF;
  --mono:'Courier Prime','Courier New',ui-monospace,monospace;
}
@media (prefers-color-scheme:dark){:root{
  --surface:#0F0E10;--paper:#1E1D20;--ink:#EEEBE5;--ink2:#A6A198;--line:#34323A;
  --accent:#E5646C;--carbon:#8FA0E0;--copy:#3A2A2E;--on-carbon:#151416}}
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
html.anim-out .roll{animation:rollUp   .2s cubic-bezier(.45,0,.7,.25) both}
/* Every open after the first of the day is quick (F27): the print-down is a moment, not a wait. */
html.anim-quick .roll{animation:quickIn .16s ease-out both}
@keyframes quickIn{0%{opacity:0;transform:translateY(-4px)}100%{opacity:1;transform:none}}
@keyframes printDown{
  0%{clip-path:inset(0 0 100% 0);transform:translateY(-4px)}
  100%{clip-path:inset(0 0 0 0);transform:translateY(0)}}
@keyframes rollUp{
  0%{clip-path:inset(0 0 0 0)}
  100%{clip-path:inset(0 0 100% 0);transform:translateY(-3px)}}
@media (prefers-reduced-motion:reduce){
  html.anim-in .roll,html.anim-out .roll,html.anim-quick .roll{animation-duration:.001s}}
/* ── carbon-copy layer: hierarchy, icons, accessibility ───────────── */
body,button,input{font-family:var(--mono)}
.receipt{filter:drop-shadow(0 8px 18px rgba(0,0,0,.28))}
.brand{color:var(--carbon)}
.item .t b{color:var(--carbon)}
.sect{color:var(--carbon)}
.depthead{color:var(--ink)}
.tag,.kv .k,.ts,.item .tm,.prov{font-size:11px}
.kv{font-size:12px}.item{font-size:12.5px}
.ic{width:14px;height:14px;display:block;fill:none;stroke:currentColor;stroke-width:1.5;stroke-linecap:round;stroke-linejoin:round}
/* WCAG 2.5.8: every control is at least 24 by 24 px to hit */
button{min-width:24px;min-height:24px;display:inline-flex;align-items:center;justify-content:center;gap:6px;
  border-style:solid;border-color:var(--line);color:var(--carbon);font-size:11px}
button:focus-visible,input:focus-visible,summary:focus-visible{outline:2px solid var(--carbon);outline-offset:2px}
.hide{color:var(--ink2)}
.hide:hover{color:var(--accent)}
/* date bar: arrows, the date as text, refresh; the native picker sits under the text */
.datebar{display:flex;align-items:center;gap:6px;justify-content:space-between;margin:8px 0 2px}
.dwrap{position:relative;flex:1;text-align:center;font-size:12.5px;font-weight:700;color:var(--ink);cursor:pointer}
.dwrap input{position:absolute;inset:0;opacity:0;width:100%;cursor:pointer}
/* WORK tools appear on hover or keyboard focus, and stay while editing (Hick's law) */
.work .tools{display:flex;gap:4px;opacity:0;transition:opacity .12s}
.work:hover .tools,.work:focus-within .tools,.work.editing .tools{opacity:1}
.work .tools .cp{margin:0;opacity:1;border-color:var(--line)}
.htext.editing{outline:1px dashed var(--carbon);background:var(--copy)}
/* source chips: what was read today, and what needs fixing */
.chips{display:flex;flex-wrap:wrap;gap:4px;justify-content:center;margin:6px 0 0}
.chip{font-size:10.5px;border:1px solid var(--line);padding:1px 6px;color:var(--ink2);min-height:0;min-width:0}
.chip.failed{color:var(--accent);border-color:var(--accent);cursor:pointer}
.chip.off{text-decoration:line-through}
/* sticky action bar: the main action never scrolls away */
.actions{position:sticky;bottom:0;background:var(--paper);padding:8px 0 6px;margin:10px 0 0;z-index:3;flex-wrap:wrap}
.copyall{font-size:11.5px;padding:6px 12px}
.copyall.primary{background:var(--carbon);color:var(--on-carbon);border-color:var(--carbon)}
.copyall.primary:hover{background:var(--carbon);color:var(--on-carbon);opacity:.9}
.copyall.sendb{border-color:var(--carbon)}
.more{position:relative}
.more summary{list-style:none;cursor:pointer;border:1px solid var(--line);color:var(--carbon);min-height:24px;min-width:24px;
  display:flex;align-items:center;justify-content:center;padding:6px 10px;font-size:11.5px}
.more summary::-webkit-details-marker{display:none}
.more .menu{position:absolute;right:0;bottom:calc(100% + 6px);background:var(--paper);border:1px solid var(--ink);
  min-width:210px;padding:6px;display:flex;flex-direction:column;gap:2px;z-index:6}
.more .menu button{justify-content:flex-start;border:0;width:100%;text-transform:none;letter-spacing:.2px;font-size:12px;padding:6px 8px}
.more .menu button:hover{background:var(--copy)}
.more .menu .lbl{font-size:10.5px;color:var(--ink2);padding:6px 8px 2px;letter-spacing:1px;text-transform:uppercase}
.more .menu button[aria-pressed="true"]::after{content:"\2713";margin-left:auto;color:var(--carbon)}
.barcode{height:22px;width:60%}
.toast{font-size:11px;letter-spacing:1px}
.sheet .box{border-color:var(--carbon)}
.sheet pre{background:var(--copy);padding:8px;outline-offset:2px}
.sheet .cc{font-size:10.5px;color:var(--ink2);margin:-2px 0 6px}
.stamp{display:none}
.item.plan.done .t{color:var(--ink2);text-decoration:line-through}
/* Controls only the Mac app can act on are hidden in the Hammerspoon widget. */
.app-only{display:none!important}
html.app .app-only{display:flex!important}
.chip.failed{min-height:24px}
.depthead .cp{opacity:1}
@media print{
  :root{--paper:#FFFFFF;--ink:#000;--ink2:#333;--line:#999;--carbon:#000;--accent:#000;--copy:#fff}
  body{background:#fff}
  .actions,.datebar,.hide,.toast,.tools,.chips,.nv,.del,.undo,.sheet,.status,.inc{display:none!important}
  .receipt{filter:none;clip-path:none;width:auto;max-width:72mm;padding:0;background-image:none}
  .surface{padding:0;display:block;min-height:0}
  details.wsec{display:block}details.wsec>*{display:block}
}
.tldr{font-size:13px;font-weight:700;color:var(--ink);border-left:3px solid var(--carbon);padding:4px 0 4px 10px;margin:4px 0 10px}
details.wsec>summary{list-style:none;cursor:pointer}
details.wsec>summary::-webkit-details-marker{display:none}
details.wsec>summary .nm::before{content:"\\25B8 ";color:var(--ink2)}
details.wsec[open]>summary .nm::before{content:"\\25BE "}
@media (prefers-reduced-motion:reduce){.work .tools{transition:none}}

/* ── Carbon copy (design direction 02) ───────────────────────────
   A work order in blue carbon ink on the pink duplicate sheet, with the white
   top copy offset behind it, Archivo Narrow for headings and a red DONE stamp.
   Text pairs pass WCAG AA on the pink in both themes; the stamp is large text. */
@font-face{font-family:'Archivo Narrow';src:url('../eod/render/fonts/ArchivoNarrow.ttf') format('truetype');font-weight:400 700}
:root{
  --paper:#F6D9DC;--ink:#24357A;--ink2:#4A5590;--line:#E0AEB5;--accent:#A82A33;
  --carbon:#24357A;--copy:#FFFFFF;--dup:#FFFFFF;--faint:rgba(36,53,122,.33);--stampc:#C8323C;--on-carbon:#FFFFFF;
  --head:'Archivo Narrow','Arial Narrow',sans-serif}
@media (prefers-color-scheme:dark){:root{
  --paper:#231C21;--ink:#C9D2F5;--ink2:#B7AFC2;--line:#4A3A43;--accent:#F07A82;
  --carbon:#8FA0E0;--copy:#33282E;--dup:#3A3036;--faint:rgba(201,210,245,.3);--stampc:#F07A82;--on-carbon:#231C21}}
.receipt{clip-path:none;filter:none;background-image:none;
  box-shadow:7px 7px 0 var(--dup),7px 7px 0 1px var(--faint);margin-right:7px}
.receipt::after{display:none}
.brand.wo{display:flex;justify-content:space-between;align-items:baseline;text-align:left;
  font:700 15px/1.2 var(--head);letter-spacing:2px;color:var(--carbon);
  border-bottom:2px solid var(--carbon);padding:0 26px 6px 0}
.brand.wo b{color:var(--carbon)}
.brand.wo .no{font-size:13px;letter-spacing:1px}
.tag{text-align:left;letter-spacing:1px;color:var(--ink2)}
.sect,.depthead,.end,.kv.tot .k,.more .menu .lbl{font-family:var(--head)}
.sect{font-size:12px;letter-spacing:2px;text-align:left}
.depthead{font-size:13px;letter-spacing:1px}
.end{font-weight:700;font-size:13px;letter-spacing:4px;color:var(--carbon)}
.rule.solid,.rule.double{border-top-color:var(--carbon)}
.rule{border-top-color:var(--line)}
.kv .dots,.depthead .dots{border-bottom-color:var(--faint)}
.totals{position:relative;border:2px solid var(--carbon);padding:4px 8px;margin:8px 0}
.totals .kv.tot{font-size:12px}
.totals .kv.tot .k{color:var(--carbon);letter-spacing:1.5px;font-size:12.5px}
.stamp{display:block;position:absolute;right:0;top:-8px;margin:0;border:3px solid var(--stampc);border-radius:0;
  color:var(--stampc);font:700 22px/1 var(--head);letter-spacing:3px;padding:3px 10px;transform:rotate(-12deg);
  opacity:.85;pointer-events:none;background:transparent}
.barcode{display:none}
.bcnum{font-size:11px;letter-spacing:2px;color:var(--ink2)}
button{border-color:var(--faint)}
.copyall.seeall{border-color:var(--faint)}
.chip{border-color:var(--faint)}
.more summary{border-color:var(--faint)}
.htext.editing{background:var(--copy)}
.toast,.undo{background:var(--carbon);color:var(--on-carbon)}
.undo button{color:var(--on-carbon);border-color:var(--on-carbon)}
button,.dpick,.more summary,.chip,.shelf button,.warn,.status,.toast{border-radius:0}
input[type=checkbox]{accent-color:var(--carbon)}
@media print{.receipt{box-shadow:none}.stamp{opacity:1}}
"""


JS = """
function send(m){try{window.webkit.messageHandlers.eod.postMessage(m);return true}catch(e){return false}}
function toast(t,ms){var el=document.getElementById('toast');el.textContent=t;el.classList.add('show');
clearTimeout(window._tt);window._tt=setTimeout(function(){el.classList.remove('show')},ms||3000)}
// Copy the update in the format of where it is going (F37), remembered per Mac.
var _fmt='plain';try{_fmt=localStorage.getItem('eod-fmt')||'plain'}catch(e){}
function setFmt(k){_fmt=k;try{localStorage.setItem('eod-fmt',k)}catch(e){}_markFmt();copyUpdate()}
function _markFmt(){document.querySelectorAll('[data-fmt]').forEach(function(b){b.setAttribute('aria-pressed',b.getAttribute('data-fmt')===_fmt?'true':'false')})}
function closeMore(el){var d=el.closest('details');if(d){d.open=false;var s=d.querySelector('summary');if(s)s.focus()}}
function openSettings(){if(window.EOD_APP)send({action:'settings'});else toast('Fix sources in the EOD app Settings')}
document.addEventListener('click',function(e){var m=document.querySelector('details.more[open]');if(m&&!m.contains(e.target))m.open=false});
function formatUpdate(t,k){var L=t.replace(/\\s+$/,'').split('\\n');var head=L[0],rest=L.slice(1);
  var bul={plain:'\\u2022 ',slack:'\\u2022 ',md:'- ',jira:'* '}[k]||'\\u2022 ';
  var h={md:'**'+head+'**',jira:'*'+head+'*',slack:'*'+head+'*'}[k]||head;
  return [h].concat(rest.map(function(x){return x.indexOf('\\u2022 ')===0?bul+x.slice(2):x})).join('\\n')+'\\n'}
function copyUpdate(){var el=document.getElementById('updText');if(!el||!el.textContent.trim()){toast('Nothing to copy yet');return}
  copyText(formatUpdate(el.textContent,_fmt),'Update copied','updText')}
// Keyboard (F38): left and right arrows change day, Cmd+C copies the update, Esc hides.
document.addEventListener('keydown',function(e){
  var t=e.target,typing=t&&(t.isContentEditable||/INPUT|TEXTAREA|SELECT/.test(t.tagName));
  if(typing||(window.isEditing&&window.isEditing())||document.getElementById('sendSheet'))return;
  if(e.key==='ArrowLeft'){e.preventDefault();nav(-1)}
  else if(e.key==='ArrowRight'){e.preventDefault();nav(1)}
  else if(e.key==='Escape'){var m=document.querySelector('details.more[open]');if(m){m.open=false;var su=m.querySelector('summary');if(su)su.focus();return}send({action:'hide'})}
  else if((e.metaKey||e.ctrlKey)&&e.code==='KeyC'&&!String(window.getSelection()).trim()&&document.getElementById('updText')){e.preventDefault();copyUpdate()}});
document.addEventListener('DOMContentLoaded',_markFmt);
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
function reportText(){var L=[document.getElementById('wkHead').textContent,''];
  document.querySelectorAll('.wsec').forEach(function(sec){var cb=sec.querySelector('input');if(cb&&!cb.checked)return;
    L.push(sec.getAttribute('data-title').toUpperCase());sec.querySelectorAll('.wl').forEach(function(x){L.push('\\u2022 '+x.textContent)});L.push('')});
  return L.join('\\n').replace(/\\n+$/,'\\n')}
function copyReport(){copyText(reportText(),'Weekly report copied','report')}
function nav(d){send({action:'nav',delta:d})}
function goDate(v){if(v)send({action:'goDate',date:v})}
function refresh(){send({action:'refresh'});toast('Refreshing…')}
function regen(){send({action:'regen'});toast('Re-summarizing…')}
function _enterEdit(){
  var list=document.getElementById('workList'),b=document.getElementById('editBtn');
  list.querySelectorAll('.htext').forEach(function(s){s.contentEditable='true';s.classList.add('editing');});
  list.setAttribute('data-edit','1');if(b)b.textContent='Save';
  var w=list.closest('.work');if(w)w.classList.add('editing');
  if(!list._keys){list._keys=true;list.addEventListener('keydown',_editKeys)}
}
// Keyboard model while editing (F16): Enter adds a line, Cmd+Enter or Cmd+S saves,
// Esc throws the edits away, Backspace on an empty line deletes it.
function _editKeys(e){
  var list=document.getElementById('workList');if(!list||list.getAttribute('data-edit')!=='1')return;
  if(e.isComposing||e.keyCode===229)return;                       // IME: Enter confirms text, not a new line
  if(!e.target.classList||!e.target.classList.contains('htext'))return;   // buttons keep their own keys
  var cur=e.target.closest&&e.target.closest('.item');
  if((e.metaKey||e.ctrlKey)&&(e.key==='Enter'||e.key==='s')){e.preventDefault();toggleEdit();return}
  if(e.key==='Escape'){e.preventDefault();send({action:'discard'});return}
  if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();addLine(cur);return}
  if(e.key==='Backspace'&&cur&&!e.target.textContent.trim()){
    e.preventDefault();var prev=cur.previousElementSibling;_removeWithUndo(cur);
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
    if(!items.length){toast('Keep at least one line, or re-summarize with AI');return}
    _undo=[];var ub=document.getElementById('undoBar');if(ub)ub.remove();
    list.querySelectorAll('.htext').forEach(function(s){s.contentEditable='false';s.classList.remove('editing');});
    list.setAttribute('data-edit','0');if(b)b.textContent='Edit';
    var w=list.closest('.work');if(w)w.classList.remove('editing');
    send({action:'saveEdits',items:items});toast('Saved');
  }
}
function addLine(after){
  var list=document.getElementById('workList');if(!list)return;
  if(list.getAttribute('data-edit')!=='1')_enterEdit();
  var d=document.createElement('div');d.className='item';
  d.innerHTML="<span class='t'><b>•</b><span class='htext editing' contenteditable='true'></span></span>"+
    "<button class='del' onclick='delLine(this)' title='Delete line' aria-label='Delete line'><svg class='ic' viewBox='0 0 16 16' aria-hidden='true'><path d='M4 4l8 8M12 4l-8 8'/></svg></button>";
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
// Deleted lines go on a stack, so several deletes can each be undone.
var _undo=[];
function _removeWithUndo(it){var parent=it.parentNode,next=it.nextSibling;it.remove();
  _undo.push(function(){parent.insertBefore(it,next&&next.parentNode===parent?next:null)});
  showUndo(_undoLabel(),_undoOne)}
function _undoLabel(){return _undo.length>1?_undo.length+' lines deleted.':'Line deleted.'}
function _undoOne(){var f=_undo.pop();if(f)f();if(_undo.length)showUndo(_undoLabel(),_undoOne)}
function delLine(el){var it=el.closest('.item');if(it)_removeWithUndo(it)}
function copyWork(){
  var list=document.getElementById('workList');
  if(list&&list.getAttribute('data-edit')==='1'){           // copy straight from your edits + persist
    var items=_collect();
    copyText(items.map(function(t){return '\\u2022 '+t}).join('\\n'),'Work update copied','workText');
    send({action:'saveEdits',items:items});
  }else{copyEl('workText','Work update copied');}
}
function drag(e){if(e.button===0)send({action:'dragStart'})}
window.playOut=function(){var h=document.documentElement;h.classList.remove('anim-in','anim-quick');h.classList.add('anim-out')};
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
  // The carbon copy (B3): the pink sheet is exactly what leaves, and you can edit it first.
  sh.innerHTML="<div class='box' role='dialog' aria-modal='true' aria-label='Send preview'><div class='to'></div>"+
    "<div class='cc'>This copy is what gets sent. Edit it first if you like.</div><pre></pre>"+
    "<div class='row'><button class='copyall seeall' id='sendCancel'>Cancel</button><button class='copyall primary' id='sendGo'>Send now</button></div></div>";
  sh.querySelector('.to').textContent='To: '+((document.getElementById('sendTo')||{}).textContent||'');
  var pre=sh.querySelector('pre');pre.textContent=(document.getElementById('updText')||{}).textContent||'';
  if(window.EOD_APP){pre.contentEditable='true';pre.setAttribute('aria-label','Text to send, editable')}
  document.body.appendChild(sh);
  var close=function(){sh.remove();document.removeEventListener('keydown',esc)};
  var esc=function(e){if(e.key==='Escape')close()};document.addEventListener('keydown',esc);
  sh.querySelector('#sendCancel').onclick=close;
  sh.querySelector('#sendGo').onclick=function(){var t=pre.innerText;close();
    var ok=window.EOD_APP?send({action:'postText',text:t}):send({action:'post'});
    if(ok){b.disabled=true;toast('Sending…')}else toast('Send works from the widget')};
  sh.querySelector('#sendGo').focus()}
// The weekly report: preview the exact composed text, then send that text.
function postWeekly(b){var old=document.getElementById('sendSheet');if(old)old.remove();
  var text=reportText();var sh=document.createElement('div');sh.className='sheet';sh.id='sendSheet';
  sh.innerHTML="<div class='box' role='dialog' aria-modal='true' aria-label='Send preview'><div class='to'></div><pre></pre>"+
    "<div class='row'><button class='copyall seeall' id='sendCancel'>Cancel</button><button class='copyall primary' id='sendGo'>Send now</button></div></div>";
  sh.querySelector('.to').textContent='To: '+((document.getElementById('sendTo')||{}).textContent||'');
  sh.querySelector('pre').textContent=text;var pre=sh.querySelector('pre');pre.contentEditable='true';
  document.body.appendChild(sh);
  var close=function(){sh.remove();document.removeEventListener('keydown',esc);b.focus()};
  var esc=function(e){if(e.key==='Escape'){e.stopPropagation();close()}};document.addEventListener('keydown',esc);
  sh.querySelector('#sendCancel').onclick=close;
  sh.querySelector('#sendGo').onclick=function(){var t=pre.innerText;close();if(send({action:'postText',text:t})){b.disabled=true;toast('Sending…')}};
  sh.querySelector('#sendGo').focus()}
function sendResult(t){var b=document.getElementById('sendBtn');if(b)b.disabled=false;
var el=document.getElementById('toast');el.textContent=t;el.classList.add('show');
clearTimeout(window._tt);window._tt=setTimeout(function(){el.classList.remove('show')},4000)}
"""


# Simple line icons (audit F43, iconography): one 16 px set, 1.5 px stroke, in
# carbon blue, always paired with a label or an aria-label. No glyphs, no emoji.
_ICONS = {
    "copy": "<rect x='5' y='5' width='8' height='9' rx='1'/><path d='M3 11V3a1 1 0 0 1 1-1h6'/>",
    "send": "<path d='M2 8l12-6-4 12-2-5z'/><path d='M8 9l6-7'/>",
    "share": "<path d='M8 2v8'/><path d='M5 5l3-3 3 3'/><path d='M3 9v4a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1V9'/>",
    "edit": "<path d='M11 2l3 3-8 8H3v-3z'/>",
    "plus": "<path d='M8 3v10M3 8h10'/>",
    "refresh": "<path d='M13 8a5 5 0 1 1-1.5-3.5'/><path d='M13 2v3h-3'/>",
    "left": "<path d='M10 3L5 8l5 5'/>",
    "right": "<path d='M6 3l5 5-5 5'/>",
    "close": "<path d='M4 4l8 8M12 4l-8 8'/>",
    "more": "<circle cx='3.5' cy='8' r='.8'/><circle cx='8' cy='8' r='.8'/><circle cx='12.5' cy='8' r='.8'/>",
    "print": "<path d='M4 6V2h8v4'/><rect x='2' y='6' width='12' height='5' rx='1'/><path d='M4 9h8v5H4z'/>",
    "sparkle": "<path d='M8 2v4M8 10v4M2 8h4M10 8h4'/>",
    "list": "<path d='M3 4h10M3 8h10M3 12h7'/>",
}


def ic(name):
    return "<svg class='ic' viewBox='0 0 16 16' aria-hidden='true'>" + _ICONS[name] + "</svg>"


def masthead(no, cls="brand wo"):
    """The work-order header: what this is on the left, its number on the right."""
    return f"<div class='{cls}'><span>WORK ORDER · E<b>O</b>D</span><span class='no'>No. {html.escape(no)}</span></div>"


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
    later = " (newer work is added within 30 min)" if sm.get("pending") else ""
    if by == "claude":
        return "Summarized by Claude" + (" at " + at if at else "") + later
    if by == "ollama":
        return "Summarized on this Mac by Ollama" + (" at " + at if at else "") + later
    if by == "edited":
        return "Edited by you"
    if by == "stale":
        return ("Last summary " + at + ". " if at else "Last summary. ") + note
    if by == "offline":
        return "Offline summary. " + note
    if by == "off":
        return "Offline summary: AI tidy-up is off"
    return ""


def render_id():
    """A fingerprint of how the receipt is drawn. Stamped into each page so a
    receipt drawn by an older engine is redrawn after an update, even on a day
    whose data has not changed."""
    import hashlib
    return hashlib.sha1((CSS + JS).encode("utf-8")).hexdigest()[:12]


def to_html(data, send_to=()):
    """The brief card. `send_to` names the destinations in send.txt; empty
    means no Send button and no trace of it in the page."""
    css = CSS.replace("%CLIP%", clip_path(340)).replace("%W%", "340")
    esc = html.escape
    pcount = data["project_count"]
    icount = work_item_count(data)
    t0, t1 = time_window(data)
    ref = "#" + data["date"].replace("-", "")

    P = [f"<!doctype html><html><head><meta charset='utf-8'><meta name='eod-render' content='{render_id()}'>"
         # set the animate-in class before first paint so the paper starts hidden (no flash)
         "<script>var _h=location.hash;document.documentElement.className=(_h==='#in'?'anim-in':(_h==='#quick'?'anim-quick':''))+(window.EOD_APP?' app':'');</script>"
         f"<style>{css}</style></head>"
         "<body><div class='surface'><div class='roll'><div class='receipt'>"]

    # masthead (doubles as the drag handle)
    P.append("<button class='hide' onclick=\"send({action:'hide'})\" title='Hide (Esc)' aria-label='Hide the receipt'>" + ic("close") + "</button>")
    P.append("<div class='grip' onmousedown='drag(event)'>")
    P.append(masthead(data["date"][5:].replace("-", "")))
    P.append("<div class='tag'>DAILY WORK RECEIPT · COPY FOR STANDUP</div>")
    P.append("</div>")
    P.append("<div class='rule'></div>")
    # Injectable so a snapshot is not hostage to the calendar. Production never
    # passes it; the tests always do.
    today_iso = data.get("_today") or datetime.now().astimezone().strftime("%Y-%m-%d")
    # The date once, as text, with arrows (F30, #45). The native picker sits
    # invisibly under the text, so clicking the date still opens it.
    P.append("<div class='datebar'>"
             "<button onclick='nav(-1)' title='Previous day (←)' aria-label='Previous day'>" + ic("left") + "</button>"
             f"<label class='dwrap'><span>{esc(pretty_date(data['date']))}</span>"
             f"<input type='date' class='dpick' value='{esc(data['date'])}' max='{esc(today_iso)}' "
             "onchange='goDate(this.value)' aria-label='Jump to a date'></label>"
             "<button onclick='nav(1)' title='Next day (→)' aria-label='Next day'>" + ic("right") + "</button>"
             "<button onclick='refresh()' title='Refresh' aria-label='Refresh'>" + ic("refresh") + "</button>"
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
            P.append("<div class='empty'>NO ACTIVITY LOGGED YET</div>")
    else:
        # ── Work: curated AI highlights (the manager-ready update; editable) ──
        if data.get("highlights"):
            P.append("<section class='work' aria-label='Work'>")
            P.append("<div class='depthead'><span class='nm'>WORK</span>"
                     "<span class='dots'></span>"
                     f"<span class='qty'>×{len(data['highlights'])}</span>"
                     "<span class='tools'>"
                     "<button class='cp' onclick='copyWork()' title='Copy these lines' aria-label='Copy work lines'>" + ic("copy") + "</button>"
                     "<button class='cp' id='editBtn' onclick='toggleEdit()' title='Edit lines' aria-label='Edit lines'>Edit</button>"
                     "<button class='cp' onclick='addLine()' title='Add a line' aria-label='Add a line'>" + ic("plus") + "</button>"
                     "<button class='cp' onclick='regen()' title='Re-summarize with AI' aria-label='Re-summarize with AI'>" + ic("sparkle") + "</button>"
                     "</span></div>")
            _pv = provenance(data)
            if _pv:
                P.append(f"<div class='prov' role='note'>{esc(_pv)}</div>")
            P.append("<div class='dept' id='workList' data-edit='0'>")
            for h in data["highlights"]:
                P.append("<div class='item'>"
                         f"<span class='t'><b>•</b><span class='htext'>{esc(h)}</span></span>"
                         "<button class='del' onclick='delLine(this)' title='Delete line' aria-label='Delete line'>" + ic("close") + "</button>"
                         f"<button class='nv' onclick=\"neverShow('line',{esc(json.dumps(h))})\" "
                         "title='Never show lines like this' aria-label='Never show this line'>hide</button></div>")
            P.append("</div>")
            P.append(f"<div id='workText' style='display:none'>{esc(highlights_text(data))}</div>")
            P.append("</section>")
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
                P.append(f"<button class='cp' onclick=\"copyEl('{pid}','{esc(p['name'])} copied')\" aria-label='Copy {esc(p['name'])}'>" + ic("copy") + "</button>")
                P.append("</div>")
                for it in items:
                    tm = f"<span class='tm'>{it['time']}</span>" if it.get("time") else ""
                    P.append("<div class='item'>"
                             f"<span class='t'><b>•</b>{esc(it['text'])}</span>{tm}</div>")
                P.append("</div>")
                P.append(f"<div id='{pid}' style='display:none'>{esc(project_text(p))}</div>")

        # B6: the morning plan against what happened.
        from ..features import plan_status
        _plan = plan_status(data["date"], data.get("highlights") or [])
        if not data.get("highlights"):          # nothing summarised yet: list the plan, don't judge it
            _plan = [(line, "open") for line, _ in _plan]
        if _plan:
            P.append("<div class='rule'></div><div class='depthead'><span class='nm'>PLANNED</span><span class='dots'></span>"
                     f"<span class='qty'>{sum(1 for _, st in _plan if st == 'done')}/{len(_plan)}</span></div>")
            for line, st in _plan:
                mark = "&#10003;" if st == "done" else "&bull;"
                P.append(f"<div class='item plan {st}'><span class='t'><b>{mark}</b>{esc(line)}</span>"
                         f"<span class='tm'>{'done' if st == 'done' else 'open'}</span></div>")

        # ── Screen time (app usage) ──
        if apps:
            P.append("<div class='rule'></div>")
            P.append("<div class='depthead'><span class='nm'>SCREEN TIME</span>"
                     "<span class='dots'></span>"
                     f"<span class='qty'>{fmt_dur(app_total)}</span>"
                     "<button class='cp' onclick=\"copyEl('appsText','Screen time copied')\" aria-label='Copy screen time'>" + ic("copy") + "</button></div>")
            for a in apps[:BRIEF_APPS]:
                P.append(f"<div class='kv'><span class='k'>{esc(a['name'])}</span>"
                         "<span class='dots'></span>"
                         f"<span class='v'>{fmt_dur(a['secs'])}</span>"
                         f"<button class='nv' onclick=\"neverShow('app',{esc(json.dumps(a['name']))})\" "
                         f"title='Never show this app' aria-label='Never show {esc(a['name'])}'>hide</button></div>")
            P.append(f"<div id='appsText' style='display:none'>{esc(apps_text(data))}</div>")

        # ── Web (browser history): on the full day view; on the brief only if asked (F36) ──
        if web and brief_web_on():
            P.append("<div class='rule'></div>")
            P.append("<div class='depthead'><span class='nm'>WEB</span>"
                     "<span class='dots'></span>"
                     f"<span class='qty'>×{web_total}</span>"
                     "<button class='cp' onclick=\"copyEl('webText','Web activity copied')\" aria-label='Copy sites'>" + ic("copy") + "</button></div>")
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
    P.append("<div class='totals'>")
    P.append(f"<div class='kv tot'><span class='k'>Projects</span><span class='dots'></span><span class='v'>{pcount}</span></div>")
    P.append(f"<div class='kv tot'><span class='k'>Work items</span><span class='dots'></span><span class='v'>{icount}</span></div>")
    if apps:
        P.append(f"<div class='kv tot'><span class='k'>Screen</span><span class='dots'></span><span class='v'>{fmt_dur(app_total)}</span></div>")
    if web and brief_web_on():
        P.append(f"<div class='kv tot'><span class='k'>Sites</span><span class='dots'></span><span class='v'>{len(web)}</span></div>")
    # First and last activity seen, not hours worked (F48): a session with one
    # prompt has no length, and breaks are not visible.
    P.append(f"<div class='kv tot'><span class='k'>First activity</span><span class='dots'></span><span class='v'>{t0}</span></div>")
    P.append(f"<div class='kv tot'><span class='k'>Last activity</span><span class='dots'></span><span class='v'>{t1}</span></div>")
    P.append("</div>")
    # B13: one gentle line about the day, off by default (insight.on).
    from ..features import daily_insight
    _ins = daily_insight(data)
    if _ins:
        P.append(f"<div class='prov' role='note'>{esc(_ins)}</div>")
    P.append("<div class='rule double'></div>")

    P.append("<div class='end' style='position:relative'>END OF DAY"
             + ("<div class='stamp' aria-hidden='true'>DONE</div>" if icount else "") + "</div>")
    P.append(f"<div class='bcnum'>{data['date'].replace('-','')}{' · ' + esc(SIG) if SIG else ''}</div>")
    # Sources read today (F32): a failed one is a button that opens Settings.
    chips = []
    for st in data.get("sources_status") or []:
        if st.get("state") == "missing":
            continue
        label = {"claude-code": "Claude Code", "codex": "Codex", "git": "Git", "github": "GitHub", "docs": "Docs",
                 "web": "Web", "meetings": "Calendar", "apps": "Screen"}.get(st["name"], st["name"])
        if st["state"] == "failed":
            chips.append(f"<button class='chip failed' onclick=\"openSettings()\" "
                         f"title='{esc(label)} could not be read today. Open Settings.'>{esc(label)}: fix</button>")
        else:
            chips.append(f"<span class='chip {esc(st['state'])}' title='{esc(label)}: {esc(st['state'])}'>{esc(label)}</span>")
    # One primary action, one quiet secondary, the rest in More (F31). Sticky, so
    # it never scrolls out of view (F28).
    none = to_standup(data) is None
    P.append("<div class='actions'>"
             "<button class='copyall primary' onclick='copyUpdate()' "
             + ("disabled title='Nothing to copy yet: no work recorded' " if none else
                "title='Copy the work update (⌘C): work lines only, no screen time or sites' ") +
             ">" + ic("copy") + "Copy update</button>"
             + (f"<button id='sendBtn' class='copyall sendb' onclick='postUpdate(this)' "
                f"title='Post the work update to {esc(', '.join(send_to))}'"
                + (" disabled" if none else "") + ">" + ic("send") + "Send</button>"
                if send_to else "") +
             "<details class='more'><summary aria-label='More actions'>" + ic("more") + "</summary><div class='menu'>"
             "<button onclick=\"closeMore(this);send({action:'full'})\">" + ic("list") + "Full day</button>"
             "<button onclick=\"closeMore(this);send({action:'share'});toast('Drawing the image…')\">" + ic("share") + "Share as image</button>"
             "<button class='app-only' onclick=\"closeMore(this);send({action:'print'})\">" + ic("print") + "Print receipt</button>"
             "<button onclick=\"closeMore(this);copyEl('allText','Full day copied')\">" + ic("copy") + "Copy full day</button>"
             "<div class='lbl'>Copy update as</div>"
             + "".join(f"<button data-fmt='{k}' aria-pressed='false' onclick=\"closeMore(this);setFmt('{k}')\">{v}</button>"
                       for k, v in (("plain", "Plain text"), ("slack", "Slack"), ("md", "Markdown"), ("jira", "Jira")))
             + "</div></details>"
             "</div>")
    if chips:
        P.append("<div class='chips' aria-label='Sources read today'>" + "".join(chips) + "</div>")
    P.append(f"<div class='ts'>updated {esc(data['generated_at'][11:16])}{_sig_html()}</div>")

    P.append(f"<div id='allText' style='display:none'>{esc(to_text(data))}</div>")
    # What "Copy update" and Send share: work lines only (F01). Screen time and
    # browsing stay on the Mac unless you copy them on purpose.
    P.append(f"<div id='updText' style='display:none'>{esc(to_standup(data) or '')}</div>")
    if send_to:
        P.append(f"<div id='sendTo' style='display:none'>{esc(', '.join(send_to))}</div>")
    P.append("</div></div></div>")  # receipt, roll, surface
    P.append("<div class='toast' id='toast' role='status' aria-live='polite'></div>")
    P.append(f"<script>{JS}</script>" + (f"<script>{SEND_JS}</script>" if send_to else "")
             + "</body></html>")
    out = "".join(P)
    return out


def _mins(hm):
    try:
        h, m = str(hm).split(":")[:2]
        return int(h) * 60 + int(m)
    except (ValueError, AttributeError):
        return None


def timeline_svg(data, width=476):
    """Work sessions (carbon) and meetings (stamp red) on one hour-ruled strip,
    with each block titled for hover and screen readers. Read-only."""
    blocks = []
    for p in data.get("projects") or []:
        for s in p.get("sessions") or []:
            a, b = _mins(s.get("start")), _mins(s.get("end"))
            if a is not None:
                blocks.append(("work", a, max(b or a, a + 10), "%s: %s" % (p.get("name", ""), s.get("title", "")),
                               s.get("start", ""), s.get("title", "")))
    for m in data.get("meetings") or []:
        a = _mins(m.get("time"))
        if a is not None:
            blocks.append(("meet", a, a + 30, "Meeting: %s" % m.get("title", ""), "", ""))
    if not blocks:
        return ""
    lo = max(0, (min(b[1] for b in blocks) // 60) * 60)
    hi = min(24 * 60, ((max(b[2] for b in blocks) + 59) // 60) * 60)
    span = max(60, hi - lo)
    x = lambda v: round((v - lo) * width / span, 1)
    esc = html.escape
    out = [f"<svg class='tl' viewBox='0 0 {width} 46' width='100%' role='img' aria-label='Timeline of the day, {len(blocks)} blocks'>"]
    for h in range(lo, hi + 1, 60):
        out.append(f"<line x1='{x(h)}' y1='0' x2='{x(h)}' y2='34' stroke='var(--line)'/>"
                   f"<text x='{x(h)}' y='44' font-size='9' text-anchor='middle' fill='var(--ink2)'>{h // 60:02d}</text>")
    for kind, a, b, title, start, stitle in blocks:
        y, fill = (4, "var(--carbon)") if kind == "work" else (20, "var(--accent)")
        click = ""
        if kind == "work" and start:
            # Clicking a work block moves that session to another project (B9).
            act = f"send({{action:'assign',start:{esc(json.dumps(start))},title:{esc(json.dumps(stitle))}}})"
            click = (f" class='tlw' tabindex='0' role='button' aria-label='{esc(title)}. Assign to a project' "
                     f"onclick=\"{act}\" onkeydown=\"if(event.key==='Enter'||event.key===' '){{event.preventDefault();{act}}}\"")
        out.append(f"<rect x='{x(a)}' y='{y}' width='{max(2, x(b) - x(a))}' height='12' fill='{fill}' opacity='.85'{click}>"
                   f"<title>{esc(title)}</title></rect>")
    out.append("</svg><div class='prov'>Top row: work sessions (click one to assign it to a project for timesheets). "
               "Bottom row: meetings.</div>")
    return "".join(out)


def to_html_full(data):
    """The 'See full bill' card: everything, in detail (opened as a second window)."""
    css = CSS.replace("%CLIP%", clip_path(520)).replace("%W%", "520")
    esc = html.escape
    apps = data.get("apps", [])
    web  = data.get("web", [])

    P = [f"<!doctype html><html><head><meta charset='utf-8'>",
         "<script>var _h=location.hash;document.documentElement.className=(_h==='#in'?'anim-in':(_h==='#quick'?'anim-quick':''))+(window.EOD_APP?' app':'');</script>",
         f"<style>{css}</style></head>",
         "<body><div class='surface'><div class='roll'><div class='receipt'>"]

    P.append("<button class='hide' onclick=\"send({action:'hide'})\" title='Close (Esc)' aria-label='Close the full day'>" + ic("close") + "</button>")
    P.append("<div class='grip' onmousedown='drag(event)'>")
    P.append(masthead(data["date"][5:].replace("-", "")))
    P.append("<div class='tag'>FULL DAY · ALL ACTIVITY</div>")
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
    # B9: the day as a timeline: work sessions and meetings on one strip.
    _tl = timeline_svg(data)
    if _tl:
        P.append("<div class='rule'></div><div class='sect'>DAY TIMELINE</div>" + _tl)
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
    P.append("<div class='actions'><button class='copyall primary' onclick=\"copyEl('fullText','Full day copied')\">" + ic("copy") + "Copy full day</button>"
             "<button class='copyall' onclick=\"send({action:'print'})\" aria-label='Print'>" + ic("print") + "Print</button></div>")
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
%FONTS%
:root{--surface:#E9E4F0;--paper:#F6D9DC;--dup:#FFFFFF;--ink:#24357A;--ink2:#4A5590;--line:#E0AEB5;--accent:#A82A33;
  --carbon:#24357A;--faint:rgba(36,53,122,.33);--stampc:#C8323C;
  --mono:'Courier Prime','Courier New',ui-monospace,monospace;--head:'Archivo Narrow','Arial Narrow',sans-serif}
*{box-sizing:border-box}
html,body{margin:0;width:%CW%px;height:%CH%px;overflow:hidden}
body{background:var(--surface);font-family:var(--mono);-webkit-font-smoothing:antialiased;
  display:flex;align-items:center;justify-content:center;position:relative}
/* The carbon copy: the pink duplicate on top, the white original offset behind it. */
.stack{position:relative}
.stack::before{content:"";position:absolute;inset:0;transform:translate(10px,10px);background:var(--dup);
  box-shadow:0 0 0 1px var(--faint)}
.receipt{position:relative;width:%W%px;max-height:%MH%px;overflow:hidden;background:var(--paper);color:var(--ink);
  padding:24px 34px 22px;letter-spacing:.2px}
.brand{display:flex;justify-content:space-between;align-items:baseline;font:700 24px/1.2 var(--head);letter-spacing:3px;
  color:var(--carbon);border-bottom:2px solid var(--carbon);padding-bottom:8px}
.brand b{color:var(--carbon)}.brand .no{font-size:20px;letter-spacing:1px}
.tag{font-size:13px;letter-spacing:1px;color:var(--ink2);margin-top:6px}
.rule{border-top:1px dashed var(--line);margin:10px 0}
.rule.double{border-top:2px solid var(--carbon)}
.kv{display:flex;align-items:flex-end;font-size:14px;line-height:1.6}
.kv .k{color:var(--carbon);text-transform:uppercase;letter-spacing:1.5px;white-space:nowrap;font:700 15px/1.6 var(--head)}
.kv .dots{flex:1;border-bottom:1px dotted var(--faint);margin:0 6px 5px}
.kv .v{white-space:nowrap;font-weight:700}
.tots{position:relative;display:grid;grid-template-columns:1fr 1fr;column-gap:28px;border:2px solid var(--carbon);padding:6px 12px}
.sect{font:700 15px var(--head);letter-spacing:3px;color:var(--carbon);margin:0 0 6px}
.item{display:flex;gap:10px;font-size:16px;line-height:1.4;margin:5px 0 0}
.item b{color:var(--carbon)}
.item .t{flex:1;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.more{color:var(--ink2);font-size:13px;letter-spacing:1px;margin:6px 0 0 20px}
.empty{text-align:center;color:var(--ink2);font-size:15px;letter-spacing:3px;padding:40px 0}
.end{text-align:center;font:700 15px var(--head);letter-spacing:5px;color:var(--carbon);margin:8px 0 0}
.bcnum{text-align:center;font-size:11px;letter-spacing:3px;color:var(--ink2)}
.stamp{position:absolute;right:0;top:-14px;border:4px solid var(--stampc);color:var(--stampc);font:700 30px/1 var(--head);
  letter-spacing:4px;padding:4px 14px;transform:rotate(-12deg);opacity:.85}
.madewith{position:absolute;right:30px;bottom:22px;color:var(--ink2);font-size:13px;letter-spacing:3px;display:flex;gap:8px;align-items:center}
.madewith b{color:var(--carbon);letter-spacing:4px}
.madewith i{display:inline-block;width:10px;height:10px;border-radius:50%;background:var(--stampc)}
"""


@functools.lru_cache(maxsize=1)
def _font_faces():
    """The bundled faces as data URIs: the share card's CSP allows no file loads."""
    import base64
    d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
    out = []
    for fam, fn, wt in (("Courier Prime", "CourierPrime-Regular.ttf", "400"), ("Courier Prime", "CourierPrime-Bold.ttf", "700"),
                        ("Archivo Narrow", "ArchivoNarrow.ttf", "400 700")):
        try:
            with open(os.path.join(d, fn), "rb") as fh:
                b64 = base64.b64encode(fh.read()).decode()
        except OSError:
            continue
        out.append(f"@font-face{{font-family:'{fam}';src:url(data:font/ttf;base64,{b64}) format('truetype');font-weight:{wt}}}")
    return "\n".join(out)



def to_html_share_week(wd):
    """The week as a share card (B7): the one-line summary and the top lines."""
    from ..features import redact
    d = {"date": wd.get("week_end") or wd["week_start"], "projects": [], "project_count": 0,
         "highlights": [redact(h) for h in (wd.get("highlights") or [])], "apps": [], "web": [],
         "sessions_seen": 0, "commits": [], "meetings": []}
    page = to_html_share(d)
    tl = ((wd.get("report") or {}).get("tldr")) or ""
    page = page.replace("DAILY WORK RECEIPT", "WEEK IN A RECEIPT", 1)
    page = page.replace("<span class='k'>Date</span>", "<span class='k'>Week</span>", 1)
    page = page.replace(f"<span class='v'>{html.escape(pretty_date(d['date']))}</span>",
                        f"<span class='v'>{html.escape(pretty_date(wd['week_start']))} → {html.escape(pretty_date(d['date']))}</span>", 1)
    if tl:
        page = page.replace("<div class='sect'>WORK</div>",
                            f"<div class='item'><span class='t'><b>&rarr;</b>{html.escape(redact(tl))}</span></div><div class='sect'>WORK</div>", 1)
    return page


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
    css = (SHARE_CSS.replace("%FONTS%", _font_faces()).replace("%W%", str(w))
           .replace("%CW%", str(SHARE_W)).replace("%CH%", str(SHARE_H))
           .replace("%MH%", str(SHARE_H - 60)))
    esc = html.escape
    apps = data.get("apps", [])
    t0, t1 = time_window(data)

    P = ["<!doctype html><html><head><meta charset='utf-8'>",
         "<meta http-equiv='Content-Security-Policy' content=\"default-src 'none'; style-src 'unsafe-inline'; font-src data:\">",
         f"<style>{css}</style></head><body><div class='stack'><div class='receipt'>",
         masthead(data["date"][5:].replace("-", ""), cls="brand"),
         "<div class='tag'>DAILY WORK RECEIPT</div>",
         "<div class='rule'></div>",
         f"<div class='kv'><span class='k'>Date</span><span class='dots'></span>"
         f"<span class='v'>{esc(pretty_date(data['date']))}</span></div>",
         "<div class='rule double'></div>"]

    # Work lines are on by default; Settings can leave them out (share-lines.off).
    lines = [] if os.path.exists(app_path("share-lines.off")) else (data.get("highlights") or [])
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
    P.append("<div class='end' style='position:relative'>END OF DAY" + ("<div class='stamp'>DONE</div>" if lines else "") + "</div>")
    P.append(f"<div class='bcnum'>{esc(data['date'].replace('-',''))}{' · ' + esc(SIG) if SIG else ''}</div>")
    P.append("</div></div><div class='madewith'><i></i>made with <b>EOD</b></div></body></html>")
    return "".join(P)


WEEKLY_COPY_OFF = {"Time by app"}


def to_html_weekly(data, send_to=()):
    css = CSS.replace("%CLIP%", clip_path(520)).replace("%W%", "520")
    esc = html.escape
    P = ["<!doctype html><html><head><meta charset='utf-8'>",
         "<script>var _h=location.hash;document.documentElement.className=(_h==='#in'?'anim-in':(_h==='#quick'?'anim-quick':''))+(window.EOD_APP?' app':'');</script>",
         f"<style>{css}</style></head>",
         "<body><div class='surface'><div class='roll'><div class='receipt'>"]
    P.append("<button class='hide' onclick=\"send({action:'hide'})\" title='Close (Esc)' aria-label='Close the weekly report'>" + ic("close") + "</button>")
    P.append("<div class='grip' onmousedown='drag(event)'>")
    P.append(masthead("W" + str(data.get("week_start") or "")[5:].replace("-", "")))
    P.append("<div class='tag'>WEEKLY RECAP · COPY FOR YOUR MANAGER</div>")
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
        P.append("<div class='empty'>NO ACTIVITY THIS WEEK YET</div>")
    else:
        # One sentence a manager reads on a phone (F35), then the achievements, biggest.
        tldr = (data.get("report") or {}).get("tldr")
        if tldr:
            P.append(f"<div class='tldr' role='note'>{esc(tldr)}</div>")
        P.append("<section class='work' aria-label='Key achievements'>")
        P.append("<div class='depthead'><span class='nm'>KEY ACHIEVEMENTS</span><span class='dots'></span>"
                 f"<span class='qty'>×{len(data['highlights'])}</span><span class='tools'>"
                 "<button class='cp' onclick='copyWork()' title='Copy these lines' aria-label='Copy achievements'>" + ic("copy") + "</button>"
                 "<button class='cp' id='editBtn' onclick='toggleEdit()' title='Edit lines' aria-label='Edit lines'>Edit</button>"
                 "<button class='cp' onclick='addLine()' title='Add a line' aria-label='Add a line'>" + ic("plus") + "</button>"
                 "<button class='cp' onclick='regen()' title='Re-summarize the week' aria-label='Re-summarize the week'>" + ic("sparkle") + "</button>"
                 "</span></div>")
        P.append("<div class='dept' id='workList' data-edit='0'>")
        for h in data["highlights"]:
            P.append("<div class='item'><span class='t'><b>•</b>"
                     f"<span class='htext'>{esc(h)}</span></span>"
                     "<button class='del' onclick='delLine(this)' title='Delete line' aria-label='Delete line'><svg class='ic' viewBox='0 0 16 16' aria-hidden='true'><path d='M4 4l8 8M12 4l-8 8'/></svg></button></div>")
        P.append("</div></section>")
        P.append(f"<div id='workText' style='display:none'>{esc(chr(10).join('• ' + h for h in data['highlights']))}</div>")
        # The rest of the report. Key achievements are the editable list above.
        # Every section has an "include in copy" switch (F08). Time by app is
        # off by default: app hours read as surveillance in a manager update.
        secs = weekly_sections(data)
        if tldr:
            P.append(f"<div class='wsec' data-title='Summary'><label class='inc'><input type='checkbox' id='incTldr' checked> include the summary in copy</label>"
                     f"<span class='wl' style='display:none'>{esc(tldr)}</span></div>")
        if secs:
            t0, l0 = secs[0]
            P.append(f"<div class='wsec' data-title='{esc(t0)}' style='display:none'>"
                     + "".join(f"<span class='wl'>{esc(x)}</span>" for x in l0) + "</div>")
        # The rest folds away in the panel (Miller's law); copy still takes every
        # section that is switched on.
        for i, (title, lines) in enumerate(secs[1:], 1):
            on = "" if title in WEEKLY_COPY_OFF else " checked"
            P.append(f"<div class='rule'></div><details class='dept wsec' data-title='{esc(title)}'>"
                     f"<summary class='depthead'><span class='nm'>{esc(title.upper())}</span><span class='dots'></span>"
                     f"<label class='inc' onclick='event.stopPropagation()'><input type='checkbox' id='inc{i}'{on}> include in copy</label></summary>")
            for it in lines:
                P.append(f"<div class='item'><span class='t'><b>•</b><span class='wl'>{esc(it)}</span></span></div>")
            P.append("</details>")
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
    P.append("<div class='end' style='position:relative'>END OF WEEK"
             + ("<div class='stamp' aria-hidden='true'>FILED</div>" if data.get("highlights") else "") + "</div>")
    if data.get("highlights"):
        # Same action set as the daily (F33): Copy, Send, and More.
        P.append("<div class='actions'><button class='copyall primary' onclick='copyReport()' "
                 "title='Copy the sections switched on above'>" + ic("copy") + "Copy report</button>"
                 + (f"<button id='sendBtn' class='copyall sendb app-only' onclick='postWeekly(this)' "
                    f"title='Post the report to {esc(', '.join(send_to))}'>" + ic("send") + "Send</button>" if send_to else "")
                 + "<details class='more app-only'><summary aria-label='More actions'>" + ic("more") + "</summary><div class='menu'>"
                 "<button onclick=\"closeMore(this);send({action:'shareWeek'});toast('Drawing the week…')\">" + ic("share") + "Share week as image</button>"
                 "<button onclick=\"closeMore(this);send({action:'timesheet'})\">" + ic("list") + "Export timesheet (CSV)</button>"
                 "<button onclick=\"closeMore(this);send({action:'print'})\">" + ic("print") + "Print report</button>"
                 "</div></details></div>")
        P.append(f"<div id='wkHead' style='display:none'>Weekly update: {esc(pretty_date(data['week_start']))} → {esc(pretty_date(data['week_end']))}</div>")
    P.append(f"<div id='wkText' style='display:none'>{esc(to_text_weekly(data))}</div>")
    P.append(f"<div class='ts'>updated {esc(data['generated_at'][11:16])}{_sig_html()}</div>")
    if send_to:
        P.append(f"<div id='sendTo' style='display:none'>{esc(', '.join(send_to))}</div>")
    P.append("</div></div></div><div class='toast' id='toast' role='status' aria-live='polite'></div>")
    P.append(f"<script>{JS}</script>" + (f"<script>{SEND_JS}</script>" if send_to else "") + "</body></html>")
    out = "".join(P)
    return out
