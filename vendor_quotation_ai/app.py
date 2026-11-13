"""Vercel-compatible web dashboard for vendor quotation analysis."""
from __future__ import annotations

import base64
import binascii
import io
import json
import math
from pathlib import Path
from zipfile import BadZipFile

import pandas as pd
import plotly.io as pio
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from dotenv import load_dotenv
from openpyxl.utils.exceptions import InvalidFileException

load_dotenv()
from vqc import ai_assistant, charts
from vqc.analysis import BASIS_LABELS, build_conclusion, run_analysis, to_facts
from vqc.config import Assumptions, Weights
from vqc.export import build_excel_report
from vqc.loader import load_quotation

SAMPLE = Path(__file__).parent / "data" / "Vendor_Quotation_Comparison.xlsx"
MAX_WORKBOOK_BYTES = 3 * 1024 * 1024
REPORT_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

app = FastAPI(title="Vendor Quotation Comparison")

PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Vendor Quotation Comparison</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
:root{color-scheme:dark;--bg:#0e1621;--panel:#162131;--line:#243247;--text:#e6edf5;--muted:#8fa3b8;--green:#3fcf9b;--blue:#4aa3ff;--amber:#f0b429;--red:#ef6b5b}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px system-ui,-apple-system,"Segoe UI",sans-serif}
button,input,select{font:inherit}button{cursor:pointer;color:var(--text);background:#25364c;border:1px solid #354960;border-radius:7px;padding:9px 13px}button:hover{border-color:var(--green)}
.top{padding:18px 26px;border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;gap:14px}.top h1{font-size:22px;margin:0}.top p{margin:4px 0 0;color:var(--muted);font-size:13px}
.layout{display:grid;grid-template-columns:310px minmax(0,1fr);min-height:calc(100vh - 74px)}aside{padding:18px;border-right:1px solid var(--line);background:#111b28}main{padding:22px;min-width:0}
.panel,.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px;margin-bottom:14px}.panel h2,.panel h3{margin:0 0 12px;font-size:15px}.field{margin:12px 0}.field label{display:block;color:#c3d0de;font-size:13px;margin-bottom:5px}.field input:not([type=checkbox]):not([type=range]),.field select{width:100%;background:#0e1621;color:var(--text);border:1px solid #354960;border-radius:6px;padding:8px}.field input[type=range]{width:100%;accent-color:var(--green)}.checklist{max-height:160px;overflow:auto}.checklist label{display:flex;gap:8px;align-items:center;padding:4px 0;color:var(--text)}.checklist input{accent-color:var(--green)}
.grid2{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:16px 0}.metric{background:var(--panel);border:1px solid var(--line);border-radius:9px;padding:13px}.metric small{display:block;color:var(--muted)}.metric strong{display:block;font-size:19px;margin:5px 0}.hero{border-left:4px solid var(--green);padding:17px 20px;margin-bottom:14px}.hero h2{margin:2px 0 8px;font-size:23px}
.tabs{display:flex;gap:7px;flex-wrap:wrap;border-bottom:1px solid var(--line);margin:18px 0}.tabs button{background:transparent;border:0;border-bottom:2px solid transparent;border-radius:0;color:var(--muted)}.tabs button.active{color:var(--green);border-bottom-color:var(--green)}.tab{display:none}.tab.active{display:block}
.chart{height:390px;min-width:0}.chart.tall{height:480px}h2.section{font-size:19px;margin:7px 0 4px}p.hint{color:var(--muted);font-size:13px;margin:5px 0 12px}
table{width:100%;border-collapse:collapse;font-size:13px}th,td{text-align:left;padding:9px 8px;border-bottom:1px solid var(--line);vertical-align:top}th{color:var(--muted);font-weight:600;position:sticky;top:0;background:var(--panel)}.table-wrap{overflow:auto;max-height:520px}
.flag{border-left:4px solid var(--muted);padding:10px 12px;margin:8px 0;background:#111b28;border-radius:5px}.flag.High{border-color:var(--red)}.flag.Medium{border-color:var(--amber)}.flag.Low{border-color:var(--muted)}.flag.Info{border-color:var(--blue)}.flag small{color:var(--muted)}
.status{color:var(--muted);font-size:13px;min-height:20px;margin:8px 0}.error{color:#ff9187}.primary{background:#17694f;border-color:#228464}.muted{color:var(--muted)}.upload{border:1px dashed #496078;border-radius:8px;padding:12px}.weight{display:grid;grid-template-columns:1fr 40px;gap:8px;align-items:center}.weight output{text-align:right;color:var(--green)}.split{display:flex;gap:8px;align-items:center}.split button{flex:1}
.chat{height:300px;overflow:auto;padding:10px;background:#111b28;border-radius:7px;margin:10px 0}.bubble{padding:9px 12px;margin:8px 0;border-radius:7px;white-space:pre-wrap}.bubble.user{background:#1b3650;margin-left:10%}.bubble.assistant{background:#1c302d;margin-right:10%}
@media(max-width:950px){.layout{grid-template-columns:1fr}aside{border-right:0;border-bottom:1px solid var(--line)}.metrics{grid-template-columns:repeat(2,1fr)}}@media(max-width:620px){main{padding:12px}.grid2{grid-template-columns:1fr}.top{padding:14px}.metrics{grid-template-columns:repeat(2,1fr)}}
</style>
</head>
<body>
<header class="top"><div><h1>Vendor Quotation Comparison</h1><p id="subtitle">Upload a comparative-statement workbook to begin.</p></div><button id="report" hidden>⬇ Download Excel report</button></header>
<div class="layout">
<aside>
  <section class="panel"><h2>Workbook</h2><div class="field upload"><label for="file">Upload comparison (.xlsx)</label><input id="file" type="file" accept=".xlsx"></div><button id="sample" type="button">Load sample workbook</button><div id="filename" class="status"></div></section>
  <section class="panel"><h2>Comparison settings</h2>
    <div class="field"><label for="basis">Price basis</label><select id="basis"><option value="quoted">Quoted price</option><option value="landed" selected>Landed cost at site</option><option value="tco">Landed + financing cost</option></select></div>
    <div class="field"><label for="fx">USD → INR rate</label><input id="fx" type="number" step="0.1" value="90"></div>
    <div class="field"><label>Vendors to include</label><div id="vendors" class="checklist muted">Load a workbook first.</div></div>
    <div class="field"><label><input id="use-tech" type="checkbox"> Enter technical ratings</label><div id="technical"></div></div>
    <h3>Scoring weights</h3>
    <div id="weights"></div>
  </section>
  <details class="panel"><summary>Import cost assumptions</summary>
    <div class="field"><label>Sea freight + insurance (%)</label><input id="freight" type="number" value="5" min="0" max="30" step=".5"></div>
    <div class="field"><label>Customs duty (%)</label><input id="duty" type="number" value="8.25" min="0" max="50" step=".25"></div>
    <div class="field"><label>Port clearing + inland transport (%)</label><input id="clearance" type="number" value="2.5" min="0" max="20" step=".5"></div>
    <div class="field"><label>Ex-works inland transport (%)</label><input id="exworks" type="number" value="2" min="0" max="20" step=".5"></div>
    <div class="field"><label>Cost of money (% per year)</label><input id="capital" type="number" value="10" min="0" max="30" step=".5"></div>
    <div class="field"><label>Import transit (months)</label><input id="transit" type="number" value="1.5" min="0" max="6" step=".5"></div>
  </details>
  <section class="panel"><h2>Claude AI (optional)</h2><div class="field"><label>Anthropic API key</label><input id="api-key" type="password" autocomplete="off" placeholder="Paste for this session only"></div><div class="field"><label>Model</label><input id="model" value="claude-sonnet-5-5"></div><small class="muted">The key is sent only with an AI request and is not saved by this app.</small></section>
  <button id="analyze" class="primary" style="width:100%">Update comparison</button><div id="status" class="status" role="status"></div>
</aside>
<main>
  <div id="empty" class="card">Load the sample workbook or upload your own comparison file.</div>
  <div id="dashboard" hidden>
    <div id="hero" class="card hero"></div><div id="metrics" class="metrics"></div>
    <nav class="tabs">
      <button class="active" data-tab="summary">Summary</button><button data-tab="items">Item prices</button><button data-tab="vendors-tab">Vendors</button><button data-tab="awards">Award options</button><button data-tab="risks">Terms &amp; risks</button><button data-tab="claude">Ask Claude</button>
    </nav>
    <section class="tab active" id="summary"><div class="grid2"><div class="card"><h2 class="section">Who is cheapest?</h2><p class="hint">Full-price totals for vendors who quoted every item.</p><div id="chart-total" class="chart"></div></div><div class="card"><h2 class="section">Who is best overall?</h2><p class="hint">Score mixes price, delivery, payment terms and warranty.</p><div id="chart-score" class="chart"></div></div></div><div class="card"><h2 class="section">Key findings</h2><div id="conclusion"></div></div></section>
    <section class="tab" id="items"><div class="card"><h2 class="section">Price of every item, vendor by vendor</h2><p class="hint">Green marks the lowest quote. Premiums are relative to the cheapest offer.</p><div id="chart-heatmap" class="chart tall"></div></div><div class="card"><h2 class="section">Look closer at one item</h2><div class="field"><select id="item-select"></select></div><div id="chart-item" class="chart"></div></div><div class="card"><h2 class="section">Full price table (₹ lakh per unit)</h2><div id="item-table" class="table-wrap"></div></div></section>
    <section class="tab" id="vendors-tab"><div class="card"><h2 class="section">Vendor scorecard</h2><div id="vendor-table" class="table-wrap"></div></div><div class="grid2"><div class="card"><div id="chart-premium" class="chart"></div></div><div class="card"><div id="chart-radar" class="chart"></div></div></div><div class="card"><h2 class="section">Negotiation progress</h2><p class="hint">Quoted totals by negotiation round.</p><div id="chart-negotiation" class="chart"></div><div id="neg-table" class="table-wrap"></div></div></section>
    <section class="tab" id="awards"><div class="card"><h2 class="section">Ways to place the order</h2><div id="chart-scenarios" class="chart"></div><div id="scenario-table" class="table-wrap"></div></div><div class="grid2"><div class="card"><div id="chart-award" class="chart"></div></div><div class="card"><h2 class="section">Who wins each item</h2><div id="award-table" class="table-wrap"></div></div></div></section>
    <section class="tab" id="risks"><div class="card"><h2 class="section">What could go wrong?</h2><div class="field"><label>Show severity</label><select id="severity"><option value="all">All</option><option value="High,Medium" selected>Serious and warning</option><option value="High">Serious only</option><option value="Medium">Warnings only</option><option value="Low,Info">Minor and info</option></select></div><div id="flags"></div><h2 class="section">Manual L1 data check</h2><div id="audit"></div></div><div class="card"><h2 class="section">Commercial terms side by side</h2><div id="terms-table" class="table-wrap"></div></div></section>
    <section class="tab" id="claude"><div class="card"><h2 class="section">Ask Claude about these results</h2><p class="hint">Claude explains computed results; it does not calculate or invent figures.</p><button id="summary-ai">Write executive summary</button><div id="ai-summary" class="card" hidden></div><div id="chat" class="chat"></div><div class="split"><input id="question" placeholder="Ask about the results…" style="flex:1;background:#0e1621;color:var(--text);border:1px solid #354960;border-radius:6px;padding:10px"><button id="ask">Send</button></div><div id="ai-status" class="status"></div></div></section>
  </div>
</main>
</div>
<script>
const $=id=>document.getElementById(id), state={workbook:null,filename:"",result:null,history:[]};
const weightNames=["price","delivery","payment","warranty","technical"], colors={green:"#3fcf9b",muted:"#8fa3b8",text:"#e6edf5"};
function esc(v){return String(v==null?"":v).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]))}
function fmt(v,d=1){return v==null||!Number.isFinite(Number(v))?"–":Number(v).toLocaleString(undefined,{maximumFractionDigits:d,minimumFractionDigits:d})}
function money(v){return v==null||!Number.isFinite(Number(v))?"–":"₹"+Number(v).toLocaleString(undefined,{maximumFractionDigits:0})}
function crore(v){return v==null||!Number.isFinite(Number(v))?"–":"₹"+(Number(v)/1e7).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})+" Cr"}
function table(rows,cols){if(!rows||!rows.length)return '<p class="muted">No data available.</p>';return '<table><thead><tr>'+cols.map(c=>'<th>'+esc(c[1])+'</th>').join('')+'</tr></thead><tbody>'+rows.map(r=>'<tr>'+cols.map(c=>'<td>'+esc(c[2]?c[2](r[c[0]],r):r[c[0]])+'</td>').join('')+'</tr>').join('')+'</tbody></table>'}
function draw(id,spec){const el=$(id);if(!spec){el.innerHTML='<p class="muted">No chart data available.</p>';return}Plotly.newPlot(el,spec.data,spec.layout,{responsive:true,displayModeBar:false})}
function setStatus(text,error=false){$("status").textContent=text;$("status").classList.toggle("error",error)}
function renderWeights(){ $("weights").innerHTML=weightNames.map((n,i)=>'<div class="field"><label>'+n[0].toUpperCase()+n.slice(1)+'</label><div class="weight"><input id="w-'+n+'" type="range" min="0" max="100" step="1" value="'+[50,15,15,10,10][i]+'"><output id="o-'+n+'">'+[50,15,15,10,10][i]+'</output></div></div>').join('');weightNames.forEach(n=>$("w-"+n).addEventListener("input",e=>$("o-"+n).value=e.target.value))}
renderWeights();
function renderVendorControls(vendors){const existing=[...document.querySelectorAll(".vendor-check")].map(x=>x.value);if(existing.length===vendors.length&&existing.every((v,i)=>v===vendors[i]))return;const old=new Set([...document.querySelectorAll(".vendor-check:checked")].map(x=>x.value));const first=!existing.length;const tech=Object.fromEntries([...document.querySelectorAll(".tech-input")].map(x=>[x.dataset.vendor,x.value]));$("vendors").innerHTML=vendors.map(v=>'<label><input class="vendor-check" type="checkbox" value="'+esc(v)+'" '+(first||old.has(v)?"checked":"")+'> '+esc(v)+'</label>').join("");$("technical").innerHTML=vendors.map(v=>'<div class="field tech-field" hidden><label>'+esc(v)+'</label><input class="tech-input" data-vendor="'+esc(v)+'" type="number" min="0" max="100" value="'+esc(tech[v]||"70")+'"></div>').join("");$("use-tech").onchange=()=>document.querySelectorAll(".tech-field").forEach(x=>x.hidden=!$("use-tech").checked);$("use-tech").dispatchEvent(new Event("change"))}
function settings(){const vals={};weightNames.forEach(n=>vals[n]=Number($("w-"+n).value));const technical={};if($("use-tech").checked)document.querySelectorAll(".tech-input").forEach(x=>{if(x.value!=="")technical[x.dataset.vendor]=Number(x.value)});const checks=[...document.querySelectorAll(".vendor-check")];return {basis:$("basis").value,fx_usd_inr:$("fx").value===""?null:Number($("fx").value),vendors:checks.length?checks.filter(x=>x.checked).map(x=>x.value):null,weights:vals,technical,assumptions:{freight_insurance_pct:Number($("freight").value),import_duty_pct:Number($("duty").value),clearance_inland_pct:Number($("clearance").value),exworks_inland_pct:Number($("exworks").value),cost_of_capital_pct:Number($("capital").value),transit_months_import:Number($("transit").value)}}}
async function postJson(url,data){const r=await fetch(url,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(data)});if(!r.ok){let msg="Request failed ("+r.status+")";try{msg=(await r.json()).detail||msg}catch{}throw new Error(msg)}return r}
async function analyze(){if(!state.workbook){setStatus("Choose a workbook first.",true);return}setStatus("Analyzing workbook…");$("analyze").disabled=true;try{const r=await postJson("/api/analyze",{workbook:state.workbook,settings:settings()});state.result=await r.json();render(state.result);setStatus("Comparison updated.")}catch(e){console.error(e);setStatus(e.message,true)}finally{$("analyze").disabled=false}}
function render(r){$("empty").hidden=true;$("dashboard").hidden=false;$("report").hidden=false;$("subtitle").textContent=(r.title||"Vendor comparison")+"  |  "+(r.rfq||"")+"  |  "+r.active.length+" vendors, "+r.item_count+" items";$("filename").textContent=state.filename;$("fx").value=r.fx;renderVendorControls(r.all_vendors);if(r.all_vendors.length){const selected=new Set(r.active);document.querySelectorAll(".vendor-check").forEach(x=>x.checked=selected.has(x.value))}
$("hero").innerHTML='<small class="muted">Best overall vendor</small><h2>'+esc(r.recommended)+'</h2><div>Score '+fmt(r.recommended_score)+' / 100 &nbsp;|&nbsp; Total '+crore(r.recommended_total)+' &nbsp;|&nbsp; '+esc(r.basis_label)+'</div><ul>'+r.reasons.map(x=>'<li>'+esc(x)+'</li>').join("")+'</ul>';
$("metrics").innerHTML=[["Cheapest full bid",crore(r.cheapest_total),r.cheapest_vendor],["Recommended vendor total",crore(r.recommended_total),r.recommended],["Saving if order is split",crore(r.split_saving),r.split_saving_pct==null?"":fmt(r.split_saving_pct)+"% less"],["Serious issues to check",r.high_flags,r.flags.length+" warnings in total"]].map((x,i)=>'<div class="metric"><small>'+x[0]+'</small><strong>'+x[1]+'</strong><small>'+esc(x[2]||"")+'</small></div>').join("");
$("conclusion").innerHTML=r.conclusion.map(x=>'<p>'+esc(x.replace(/\*\*/g,"").replace(/\*/g,""))+'</p>').join("");
draw("chart-total",r.figures.total_cost);draw("chart-score",r.figures.score);draw("chart-heatmap",r.figures.heatmap);
$("item-select").innerHTML=r.items.map(x=>'<option value="'+esc(x.item_no)+'">'+esc(x.item)+'</option>').join("");$("item-select").onchange=()=>draw("chart-item",r.figures.item_bars[$("item-select").value]);if(r.items.length)draw("chart-item",r.figures.item_bars[r.items[0].item_no]);
$("item-table").innerHTML=table(r.price_table,[["item","Item"],["qty","Qty",v=>fmt(v,0)],["l1_vendor","Cheapest vendor"],["l1_rate","L1 rate (₹)",money],["l2_vendor","Next vendor"],["l2_rate","L2 rate (₹)",money],["l2_gap_pct","L2 gap %",v=>fmt(v)+"%"],...r.active.map(v=>[v,v,v=>money(v)])]);
$("vendor-table").innerHTML=table(r.vendors,[["vendor","Vendor"],["origin","Country"],["coverage_pct","Items quoted %",v=>fmt(v,0)],["basis_total","Total price",crore],["premium_pct","More than cheapest %",v=>fmt(v)+"%"],["l1_wins","Items won"],["price_score","Price",v=>fmt(v,0)],["delivery_score","Delivery",v=>fmt(v,0)],["payment_score","Payment",v=>fmt(v,0)],["warranty_score","Warranty",v=>fmt(v,0)],["weighted_score","Overall",v=>fmt(v)],["rank","Rank",v=>v==null?"partial":fmt(v,0)]]);
draw("chart-premium",r.figures.premium);draw("chart-radar",r.figures.radar);draw("chart-negotiation",r.figures.negotiation);
$("neg-table").innerHTML=table(r.negotiation,[["vendor","Vendor"],["label","Round"],["total","Quoted total",crore],["saving_vs_initial_pct","Saving %",v=>fmt(v)+"%"]]);
$("scenario-table").innerHTML=table(r.scenarios,[["scenario","Option"],["vendors","Vendor(s)"],["n_vendors","No. vendors"],["total","Total",crore],["vs_recommended_inr","Difference vs recommended",money],["vs_recommended_pct","Difference %",v=>fmt(v)+"%"]]);
draw("chart-scenarios",r.figures.scenarios);draw("chart-award",r.figures.award);
$("award-table").innerHTML=table(r.award,[["item_no","#"],["item","Item"],["qty","Qty",v=>fmt(v,0)],["vendor","Vendor"],["unit_rate","Rate per unit",money],["amount","Amount",money]]);
$("flags").innerHTML=r.flags.length?r.flags.map(f=>'<div class="flag '+esc(f.severity)+'"><b>'+esc(f.vendor)+'</b> <small>'+esc(f.severity+" · "+f.category)+'</small><br>'+esc(f.message)+'</div>').join(""):'<p class="muted">No flags.</p>';
$("severity").onchange=()=>document.querySelectorAll(".flag").forEach(x=>x.hidden=!$("severity").value.split(",").includes(x.classList[1]));$("severity").dispatchEvent(new Event("change"));
$("audit").innerHTML=table(r.audit,[["item","Item"],["sheet_l1_vendor","Sheet says"],["sheet_l1_rate","Sheet price",money],["true_l1_vendor","Actually cheapest"],["true_l1_rate","Actual price",money],["overstated_by","Sheet is higher by",money],["ok","OK",v=>v?"Yes":"No"]]);
$("terms-table").innerHTML=table(r.terms,[["vendor","Vendor"],["basis_class","Price basis"],["price_basis_text","Original price-basis wording"],["advance_pct","Advance %",v=>v==null?"–":fmt(v,0)],["advance_secured","Bank guarantee"],["payment_text","Original payment wording"],["delivery_full_m","Delivery (months)",v=>fmt(v)],["delivery_to_site_m","Reaches site (months)",v=>fmt(v)],["delivery_text","Original delivery wording"],["warranty_m","Warranty (months)",v=>v==null?"–":fmt(v,0)],["warranty_text","Original warranty wording"],["supervision","Erection & commissioning"],["supervision_text","Original supervision wording"]]);
}
function fileToBase64(file){return new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(",")[1]);reader.onerror=()=>reject(new Error("Could not read the selected workbook."));reader.readAsDataURL(file)})}
$("file").addEventListener("change",async e=>{const f=e.target.files[0];if(!f)return;try{state.workbook=await fileToBase64(f);state.filename=f.name;await analyze()}catch(err){setStatus(err.message,true)}});
$("sample").onclick=async()=>{setStatus("Loading sample workbook…");try{const res=await fetch("/api/sample");if(!res.ok)throw new Error("Sample workbook is not available.");const blob=await res.blob();state.workbook=await fileToBase64(new File([blob],"Vendor_Quotation_Comparison.xlsx"));state.filename="Vendor_Quotation_Comparison.xlsx";await analyze()}catch(e){setStatus(e.message,true)}};
$("analyze").onclick=analyze;
document.querySelectorAll(".tabs button").forEach(b=>b.onclick=()=>{document.querySelectorAll(".tabs button").forEach(x=>x.classList.toggle("active",x===b));document.querySelectorAll(".tab").forEach(x=>x.classList.toggle("active",x.id===b.dataset.tab));setTimeout(()=>document.querySelectorAll(".tab.active .chart").forEach(x=>{if(x.data)Plotly.Plots.resize(x)}),30)});
$("report").onclick=async()=>{setStatus("Preparing Excel report…");try{const r=await postJson("/api/report",{workbook:state.workbook,settings:settings()});const blob=await r.blob();const a=document.createElement("a");a.href=URL.createObjectURL(blob);a.download="Vendor_Comparison_Report.xlsx";a.click();URL.revokeObjectURL(a.href);setStatus("Excel report downloaded.")}catch(e){setStatus(e.message,true)}};
function aiPayload(action,question){return {workbook:state.workbook,settings:settings(),action,question,key:$("api-key").value,model:$("model").value,history:state.history}}
$("summary-ai").onclick=async()=>{const out=$("ai-summary");out.hidden=false;out.textContent="Claude is writing…";$("ai-status").textContent="";try{const r=await postJson("/api/claude",aiPayload("summary",""));const d=await r.json();out.textContent=d.answer}catch(e){out.textContent="";$("ai-status").textContent=e.message;$("ai-status").classList.add("error")}};
function paintChat(){ $("chat").innerHTML=state.history.map(m=>'<div class="bubble '+(m.role==="user"?"user":"assistant")+'">'+esc(m.content)+'</div>').join("");$("chat").scrollTop=$("chat").scrollHeight}
async function ask(){const q=$("question").value.trim();if(!q)return;state.history.push({role:"user",content:q});$("question").value="";paintChat();$("ai-status").textContent="Claude is thinking…";try{const r=await postJson("/api/claude",aiPayload("chat",q));const d=await r.json();state.history.push({role:"assistant",content:d.answer});paintChat();$("ai-status").textContent=""}catch(e){state.history.pop();$("ai-status").textContent=e.message;$("ai-status").classList.add("error");paintChat()}}
$("ask").onclick=ask;$("question").addEventListener("keydown",e=>{if(e.key==="Enter")ask()});
</script>
</body></html>"""


def _number(value, default):
    if value is None or value == "":
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="Settings must contain numeric values.") from None
    if not math.isfinite(number):
        raise HTTPException(status_code=422, detail="Settings must contain finite numeric values.")
    return number


def _decode_workbook(payload: dict) -> bytes:
    encoded = payload.get("workbook")
    if not isinstance(encoded, str) or not encoded:
        raise HTTPException(status_code=422, detail="Upload a comparison workbook first.")
    if len(encoded) > ((MAX_WORKBOOK_BYTES + 2) // 3) * 4 + 8:
        raise HTTPException(status_code=413, detail="Workbook exceeds the 3 MB upload limit.")
    try:
        data = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=422, detail="Workbook upload is not valid base64 data.") from None
    if not data or len(data) > MAX_WORKBOOK_BYTES:
        raise HTTPException(status_code=413, detail="Workbook must be between 1 byte and 3 MB.")
    return data


def _calculate(payload: dict):
    settings = payload.get("settings") or {}
    if not isinstance(settings, dict):
        raise HTTPException(status_code=422, detail="Settings must be an object.")
    basis = settings.get("basis", "landed")
    if basis not in BASIS_LABELS:
        raise HTTPException(status_code=422, detail="Choose a valid comparison basis.")
    assumptions_data = settings.get("assumptions") or {}
    weights_data = settings.get("weights") or {}
    if not isinstance(assumptions_data, dict) or not isinstance(weights_data, dict):
        raise HTTPException(status_code=422, detail="Assumptions and weights must be objects.")
    assumptions = Assumptions(
        fx_usd_inr=_number(settings.get("fx_usd_inr"), None),
        freight_insurance_pct=_number(assumptions_data.get("freight_insurance_pct"), 5),
        import_duty_pct=_number(assumptions_data.get("import_duty_pct"), 8.25),
        clearance_inland_pct=_number(assumptions_data.get("clearance_inland_pct"), 2.5),
        exworks_inland_pct=_number(assumptions_data.get("exworks_inland_pct"), 2),
        cost_of_capital_pct=_number(assumptions_data.get("cost_of_capital_pct"), 10),
        transit_months_import=_number(assumptions_data.get("transit_months_import"), 1.5),
    )
    limits = {
        "freight_insurance_pct": (0, 30, assumptions.freight_insurance_pct),
        "import_duty_pct": (0, 50, assumptions.import_duty_pct),
        "clearance_inland_pct": (0, 20, assumptions.clearance_inland_pct),
        "exworks_inland_pct": (0, 20, assumptions.exworks_inland_pct),
        "cost_of_capital_pct": (0, 30, assumptions.cost_of_capital_pct),
        "transit_months_import": (0, 6, assumptions.transit_months_import),
    }
    if any(not low <= value <= high for low, high, value in limits.values()):
        raise HTTPException(status_code=422, detail="Import assumptions are outside the allowed ranges.")
    if assumptions.fx_usd_inr is not None and assumptions.fx_usd_inr <= 0:
        raise HTTPException(status_code=422, detail="USD to INR rate must be greater than zero.")
    weights = Weights(**{
        name: _number(weights_data.get(name), default)
        for name, default in Weights().as_dict().items()
    })
    if any(value < 0 or value > 100 for value in weights.as_dict().values()):
        raise HTTPException(status_code=422, detail="Scoring weights must be between 0 and 100.")
    if not any(weights.as_dict().values()):
        raise HTTPException(status_code=422, detail="Set at least one scoring weight above zero.")
    try:
        quotation = load_quotation(io.BytesIO(_decode_workbook(payload)))
    except HTTPException:
        raise
    except (ValueError, KeyError, OSError, BadZipFile, InvalidFileException) as exc:
        raise HTTPException(status_code=422, detail=f"Could not read the workbook: {exc}") from exc

    all_vendors = list(quotation.vendors.vendor)
    selected = settings.get("vendors")
    if selected is not None and not isinstance(selected, list):
        raise HTTPException(status_code=422, detail="Vendors must be a list.")
    if selected is not None and any(v not in all_vendors for v in selected):
        raise HTTPException(status_code=422, detail="The vendor selection does not match this workbook.")
    exclude = [vendor for vendor in all_vendors if selected is not None and vendor not in selected]
    technical = settings.get("technical") or {}
    if not isinstance(technical, dict):
        raise HTTPException(status_code=422, detail="Technical ratings must be an object.")
    if any(vendor not in all_vendors or not 0 <= _number(value, -1) <= 100
           for vendor, value in technical.items()):
        raise HTTPException(status_code=422, detail="Technical ratings must be from 0 to 100 for listed vendors.")
    try:
        result = run_analysis(quotation, assumptions, weights, basis, exclude=exclude, tech_ratings=technical)
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return quotation, result, all_vendors


def _records(frame: pd.DataFrame | None, reset_index=False) -> list:
    if frame is None:
        return []
    df = frame.copy()
    if reset_index:
        df = df.reset_index()
    return json.loads(df.to_json(orient="records", date_format="iso"))


def _figure(fig) -> dict | None:
    return json.loads(pio.to_json(fig, validate=True)) if fig is not None else None


def _dashboard_payload(quotation, result, all_vendors) -> dict:
    vendor_table = result.vendor_table.reset_index()
    recommendation = result.vendor_table.loc[result.recommended]
    full = result.vendor_table[result.vendor_table.full_scope]
    cheapest_vendor = full.basis_total.idxmin() if len(full) else None
    cheapest_total = float(full.basis_total.min()) if len(full) else None
    split = result.scenarios[result.scenarios.scenario.str.contains("all active", case=False)]
    split_total = split.iloc[0].total if len(split) and pd.notna(split.iloc[0].total) else None
    split_saving = max(float(recommendation.basis_total - split_total), 0) if split_total is not None else None
    split_pct = split_saving / float(recommendation.basis_total) * 100 if split_saving is not None and recommendation.basis_total else None
    reasons = []
    if cheapest_vendor:
        if result.recommended == cheapest_vendor:
            reasons.append("Lowest total price among vendors who quoted every item")
        else:
            gap = (recommendation.basis_total / full.basis_total.min() - 1) * 100
            reasons.append(f"Price is {gap:.1f}% above the cheapest full bid ({cheapest_vendor}), but it scores better on other factors")
    if pd.notna(recommendation.delivery_to_site_m):
        fastest = result.vendor_table.delivery_to_site_m.min()
        reasons.append(f"Delivery to site in about {recommendation.delivery_to_site_m:.1f} months (fastest bid: {fastest:.1f} months)")
    if pd.notna(recommendation.advance_pct):
        status = "covered by a bank guarantee" if recommendation.advance_secured else "with no bank guarantee mentioned"
        reasons.append(f"{recommendation.advance_pct:.0f}% advance payment, {status}")
    if pd.notna(recommendation.warranty_m):
        reasons.append(f"Warranty up to {recommendation.warranty_m:.0f} months")
    colors = charts.vendor_colors(result.active)
    item_figures = {
        str(item_no): _figure(charts.item_bar(result, item_no, colors))
        for item_no in result.items.index
    }
    price_table = result.item_table.set_index("item_no").join(result.basis_rates[result.active], how="left").reset_index()
    return {
        "title": quotation.title,
        "rfq": quotation.rfq,
        "fx": result.fx,
        "basis_label": BASIS_LABELS[result.basis],
        "active": result.active,
        "all_vendors": all_vendors,
        "item_count": len(result.items),
        "recommended": result.recommended,
        "recommended_score": float(recommendation.weighted_score),
        "recommended_total": float(recommendation.basis_total),
        "cheapest_vendor": cheapest_vendor,
        "cheapest_total": cheapest_total,
        "split_saving": split_saving,
        "split_saving_pct": split_pct,
        "high_flags": int((result.flags.severity == "High").sum()),
        "reasons": reasons,
        "conclusion": build_conclusion(result),
        "items": _records(result.item_table[["item_no", "item"]]),
        "price_table": _records(price_table),
        "vendors": _records(vendor_table),
        "scenarios": _records(result.scenarios),
        "award": _records(result.award),
        "negotiation": _records(result.negotiation),
        "flags": _records(result.flags),
        "audit": _records(result.audit),
        "terms": _records(vendor_table),
        "figures": {
            "total_cost": _figure(charts.total_cost_bar(result, colors)),
            "score": _figure(charts.score_stack(result)),
            "heatmap": _figure(charts.heatmap(result)),
            "item_bars": item_figures,
            "premium": _figure(charts.premium_bar(result, colors)),
            "radar": _figure(charts.radar(result, colors)),
            "negotiation": _figure(charts.negotiation_line(result, colors)) if len(result.negotiation) else None,
            "scenarios": _figure(charts.scenario_bar(result)),
            "award": _figure(charts.award_donut(result, colors)),
        },
    }


async def _json_body(request: Request) -> dict:
    try:
        data = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="Request body must be valid JSON.") from None
    if not isinstance(data, dict):
        raise HTTPException(status_code=422, detail="Request body must be a JSON object.")
    return data


@app.get("/", response_class=HTMLResponse)
async def home():
    return HTMLResponse(PAGE)


@app.get("/api/sample")
async def sample_workbook():
    if not SAMPLE.is_file():
        raise HTTPException(status_code=404, detail="Sample workbook is not available.")
    return Response(SAMPLE.read_bytes(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.post("/api/analyze")
async def analyze(request: Request):
    payload = await _json_body(request)
    quotation, result, all_vendors = _calculate(payload)
    return _dashboard_payload(quotation, result, all_vendors)


@app.post("/api/report")
async def report(request: Request):
    payload = await _json_body(request)
    quotation, result, _ = _calculate(payload)
    return Response(
        build_excel_report(result, quotation.title),
        media_type=REPORT_MIME,
        headers={"Content-Disposition": 'attachment; filename="Vendor_Comparison_Report.xlsx"'},
    )


@app.post("/api/claude")
async def claude(request: Request):
    payload = await _json_body(request)
    quotation, result, _ = _calculate(payload)
    action = payload.get("action")
    if action not in ("summary", "chat"):
        raise HTTPException(status_code=422, detail="Choose summary or chat.")
    key = payload.get("key") or None
    model = payload.get("model") or None
    if not ai_assistant.available(key):
        raise HTTPException(status_code=400, detail="Enter an Anthropic API key to use Claude.")
    try:
        facts = to_facts(result)
        if action == "summary":
            answer = ai_assistant.executive_summary(facts, key, model)
        else:
            question = payload.get("question")
            if not isinstance(question, str) or not question.strip():
                raise HTTPException(status_code=422, detail="Enter a question for Claude.")
            history = payload.get("history") or []
            if not isinstance(history, list):
                raise HTTPException(status_code=422, detail="Chat history must be a list.")
            answer = ai_assistant.ask(question, facts, history, key, model)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Claude request failed: {exc}") from exc
    return {"answer": answer}
