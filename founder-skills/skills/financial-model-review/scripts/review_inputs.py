#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Dual-mode review viewer for FMR inputs.

Static mode:
    python review_inputs.py <inputs.json> --static <output.html>
    Writes self-contained HTML file with JS sanity metrics. Submit triggers
    browser download of corrections.json.

Server mode:
    python review_inputs.py <inputs.json> --workspace <dir>
    Starts HTTP server with live Python validation via /api/check.

Both modes produce corrections.json consumable by apply_corrections.py.
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import json
import os
import signal
import subprocess
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

# ---------------------------------------------------------------------------
# HTML template
# ---------------------------------------------------------------------------

_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Financial Model Review</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
    background: #f9fafb; color: #1f2937; line-height: 1.5;
    min-height: 100vh; padding-bottom: 80px;
  }

  /* Header */
  .header { padding: 24px 32px 16px; display: flex; align-items: center; gap: 12px; }
  .header h1 { font-size: 1.5rem; font-weight: 600; margin: 0; }
  .stage-badge {
    display: inline-block; padding: 2px 10px; border-radius: 12px;
    font-size: 0.75rem; font-weight: 600; text-transform: uppercase;
    background: #dbeafe; color: #0d549d; letter-spacing: 0.05em;
  }

  /* Sanity strip */
  .sanity-strip { display: flex; gap: 16px; padding: 0 32px 16px; flex-wrap: wrap; }
  .sanity-card {
    background: #ffffff; border-radius: 8px; padding: 14px 20px;
    min-width: 160px; flex: 1; box-shadow: 0 1px 3px rgba(0,0,0,0.05);
    border-left: 3px solid #e5e7eb;
  }
  .sanity-card.pass { border-left-color: #10b981; }
  .sanity-card.warn { border-left-color: #f59e0b; }
  .sanity-card .label {
    font-size: 0.75rem; color: #6b7280; text-transform: uppercase;
    letter-spacing: 0.04em; margin-bottom: 4px;
  }
  .sanity-card .value {
    font-family: 'SF Mono', 'Fira Code', 'Cascadia Code', monospace;
    font-size: 1.25rem; font-weight: 600;
  }

  /* Warnings container */
  #warnings-container { padding: 0 32px; }
  .warning-card {
    background: #fef3c7; border-left: 4px solid #f59e0b;
    padding: 0.75rem 1rem; margin-bottom: 0.5rem; border-radius: 4px;
    display: flex; justify-content: space-between; align-items: center;
  }
  .warning-card .msg { color: #92400e; font-size: 0.9rem; }
  .warning-card .dismiss-btn {
    background: none; border: 1px solid #d97706; color: #d97706;
    padding: 0.25rem 0.5rem; border-radius: 4px; cursor: pointer; font-size: 0.8rem;
    flex-shrink: 0; margin-left: 12px;
  }
  .warning-card .dismiss-btn:hover { background: #fef3c7; }

  /* Field warning highlight */
  .field-warning { border-color: #f59e0b !important; box-shadow: 0 0 0 2px rgba(245,158,11,0.2); }

  /* Tabs */
  .tab-bar {
    display: flex; gap: 0; padding: 0 32px; border-bottom: 1px solid #e5e7eb;
    margin-bottom: 16px;
  }
  .tab-btn {
    background: transparent; border: none; color: #6b7280;
    padding: 10px 20px; font-size: 0.875rem; font-weight: 500;
    cursor: pointer; border-bottom: 2px solid transparent;
  }
  .tab-btn.active { background: #eef2ff; color: #0d549d; border-bottom-color: #0071e3; }
  .tab-content { padding: 16px 32px; display: none; }
  .tab-content.active { display: block; }

  /* Field groups */
  .field-group { margin-bottom: 16px; }
  .field-group.changed { border-left: 3px solid #21a2e3; padding-left: 8px; }
  .field-label {
    display: block; font-size: 0.8rem; color: #6b7280;
    margin-bottom: 4px; font-weight: 500;
  }
  .field-helper { font-size: 0.75rem; color: #9ca3af; margin-top: 2px; }
  .field-was { color: #9ca3af; font-size: 0.8rem; font-style: italic; }

  .input-field {
    background: #ffffff; border: 1px solid #d1d5db; border-radius: 6px;
    color: #1f2937; padding: 8px 12px;
    font-family: 'SF Mono', 'Fira Code', 'Cascadia Code', monospace;
    font-size: 0.875rem; width: 100%; outline: none;
  }
  .input-field:focus { border-color: #0071e3; }
  .input-field.readonly { background: #f3f4f6; color: #9ca3af; border-color: #e5e7eb; }

  select.input-field { appearance: auto; }

  /* Inline pair */
  .inline-pair { display: flex; gap: 12px; align-items: flex-start; }
  .inline-pair > div { flex: 1; }

  /* Currency toggle */
  .currency-toggle {
    display: inline-flex; border-radius: 6px; overflow: hidden;
    border: 1px solid #d1d5db; flex-shrink: 0;
  }
  .currency-toggle button {
    background: #ffffff; border: none; color: #6b7280;
    padding: 6px 10px; font-size: 0.8rem; cursor: pointer;
  }
  .currency-toggle button.active { background: #0d549d; color: #ffffff; }
  .currency-row { display: flex; gap: 8px; align-items: center; }
  .currency-equiv { font-size: 0.8rem; color: #9ca3af; margin-top: 2px; }

  /* Tag chips */
  .chip-container { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 4px; }
  .chip {
    display: inline-block; padding: 4px 12px; border-radius: 14px;
    font-size: 0.8rem; cursor: pointer; user-select: none;
    border: 1px solid #d1d5db; background: #ffffff; color: #6b7280;
  }
  .chip.selected { border-color: #21a2e3; background: #0d549d; color: #ffffff; }

  /* Section header */
  .section-header {
    font-size: 0.9rem; font-weight: 600; margin: 20px 0 10px;
    padding-bottom: 4px; border-bottom: 1px solid #e5e7eb;
  }

  /* Tables */
  .edit-table { width: 100%; border-collapse: collapse; margin: 8px 0 16px; }
  .edit-table th {
    text-align: left; font-size: 0.75rem; color: #6b7280;
    padding: 6px 8px; border-bottom: 1px solid #e5e7eb;
  }
  .edit-table td { padding: 4px 8px; }
  .edit-table .input-field { width: 100%; }
  .add-row-btn {
    background: #0d549d; border: none; color: #ffffff;
    padding: 6px 16px; border-radius: 4px; cursor: pointer;
    font-size: 0.8rem; margin-top: 4px;
  }
  .remove-row-btn {
    background: transparent; border: none; color: #ef4444;
    cursor: pointer; font-size: 0.8rem;
  }

  /* Accordion */
  .accordion-header {
    font-size: 0.9rem; font-weight: 600; margin: 20px 0 10px;
    padding-bottom: 4px; border-bottom: 1px solid #e5e7eb; cursor: pointer;
  }
  .accordion-body { padding: 8px 0 8px 8px; display: none; }
  .accordion-body.open { display: block; }

  /* Corrections drawer */
  .corrections-bar {
    position: fixed; bottom: 0; left: 0; right: 0;
    background: #ffffff; border-top: 1px solid #e5e7eb;
    z-index: 100; box-shadow: 0 -2px 8px rgba(0,0,0,0.05);
    transition: max-height 0.25s ease;
  }
  .corrections-summary {
    padding: 12px 32px; display: flex; align-items: center;
    gap: 16px; cursor: pointer; user-select: none;
  }
  .corrections-summary:hover { background: #f9fafb; }
  .corrections-count { font-size: 0.875rem; color: #6b7280; }
  .corrections-count strong { color: #0d549d; }
  .corrections-toggle {
    font-size: 0.8rem; color: #6b7280; margin-left: auto;
    display: flex; align-items: center; gap: 4px;
  }
  .corrections-toggle .arrow {
    display: inline-block; transition: transform 0.2s;
    font-size: 0.7rem;
  }
  .corrections-bar.open .corrections-toggle .arrow { transform: rotate(180deg); }
  .corrections-drawer {
    max-height: 0; overflow: hidden; transition: max-height 0.25s ease;
    border-top: 1px solid #e5e7eb;
  }
  .corrections-bar.open .corrections-drawer {
    max-height: 300px; overflow-y: auto;
  }
  .corrections-table {
    width: 100%; border-collapse: collapse; font-size: 0.85rem;
  }
  .corrections-table th {
    text-align: left; padding: 8px 32px; background: #f9fafb;
    color: #6b7280; font-weight: 600; font-size: 0.75rem;
    text-transform: uppercase; letter-spacing: 0.03em;
    position: sticky; top: 0;
  }
  .corrections-table td {
    padding: 8px 32px; border-top: 1px solid #f3f4f6;
  }
  .corrections-table .field-col { color: #1f2937; font-weight: 500; }
  .corrections-table .old-val { color: #9ca3af; text-decoration: line-through; }
  .corrections-table .new-val { color: #0d549d; font-weight: 500; }
  .corrections-table .undo-btn {
    background: none; border: 1px solid #d1d5db; color: #6b7280;
    border-radius: 4px; padding: 2px 8px; cursor: pointer; font-size: 0.75rem;
  }
  .corrections-table .undo-btn:hover { background: #f3f4f6; color: #1f2937; }
  .corrections-empty {
    padding: 16px 32px; color: #9ca3af; font-size: 0.85rem; text-align: center;
  }
  .corrections-actions {
    padding: 12px 32px; display: flex; justify-content: flex-end;
    border-top: 1px solid #e5e7eb;
  }
  .submit-btn {
    background: #0d549d; color: #ffffff; border: none;
    border-radius: 6px; padding: 8px 24px; font-weight: 600;
    font-size: 0.875rem; cursor: pointer;
  }
  .submit-btn:hover { background: #0071e3; }

  /* Overlay */
  .overlay {
    display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.5);
    justify-content: center; align-items: center; z-index: 200;
  }
  .overlay.show { display: flex; }
  .overlay-box {
    background: #ffffff; border-radius: 12px; padding: 2rem; text-align: center;
    max-width: 420px;
  }
  .overlay-box h2 { color: #10b981; margin-bottom: 0.75rem; }
  .overlay-box p { color: #6b7280; font-size: 0.9rem; }

  /* Pct suffix */
  .pct-row { display: flex; align-items: center; gap: 6px; }
  .pct-row .input-field { flex: 1; }
  .pct-suffix { color: #6b7280; font-size: 0.9rem; }
</style>
</head>
<body>

<div class="header">
  <h1 id="header-title"></h1>
  <span class="stage-badge" id="stage-badge"></span>
  <div style="font-size:0.75rem;color:#9ca3af;margin-top:4px;">All values in USD</div>
</div>

<div class="sanity-strip" id="sanity-strip"></div>

<div id="warnings-container"></div>

<div class="tab-bar" id="tab-bar"></div>

<div id="tab-panels"></div>

<div class="corrections-bar" id="corrections-bar">
  <div class="corrections-summary" id="corrections-summary">
    <div class="corrections-count"><strong id="corr-count">0</strong> corrections</div>
    <div class="corrections-toggle"><span>Show changes</span> <span class="arrow">&#9650;</span></div>
  </div>
  <div class="corrections-drawer" id="corrections-drawer">
    <table class="corrections-table" id="corrections-table">
      <thead><tr><th>Field</th><th>Original</th><th>New Value</th><th></th></tr></thead>
      <tbody id="corrections-tbody"></tbody>
    </table>
    <div class="corrections-empty" id="corrections-empty">No changes yet — edit any field above.</div>
    <div class="corrections-actions">
      <button class="submit-btn" id="submit-btn">Submit Corrections</button>
    </div>
  </div>
</div>

<div class="overlay" id="overlay">
  <div class="overlay-box">
    <h2>Feedback Submitted</h2>
    <p id="overlay-msg">Your corrections have been saved.</p>
    <p id="overlay-hint" style="margin-top:1rem;color:#9ca3af;font-size:0.85rem;"></p>
  </div>
</div>

<script>
/*__EMBEDDED_DATA__*/

const ORIGINAL = JSON.parse(JSON.stringify(DATA));
let state = JSON.parse(JSON.stringify(DATA));
const corrections = new Map();
const ilsFields = {};
const warningOverrides = new Map();
const accordionState = {};
let activeTab = "company";

/* ===== Path helpers ===== */
function getByPath(obj, path) {
  const parts = path.split(".");
  let cur = obj;
  for (const part of parts) {
    if (cur == null || typeof cur !== "object") return undefined;
    if (part.indexOf("[") === -1) {
      cur = cur[part];
    } else {
      const name = part.substring(0, part.indexOf("["));
      const sel = part.substring(part.indexOf("[") + 1, part.length - 1);
      const arr = cur[name];
      if (!Array.isArray(arr)) return undefined;
      if (sel.indexOf("=") !== -1) {
        const [k, v] = sel.split("=");
        cur = arr.find(function(item) { return item && String(item[k]) === v; });
      } else {
        cur = arr[parseInt(sel, 10)];
      }
    }
  }
  return cur;
}

function setByPath(obj, path, value) {
  const parts = path.split(".");
  let cur = obj;
  for (let i = 0; i < parts.length - 1; i++) {
    const part = parts[i];
    if (part.indexOf("[") === -1) {
      if (cur[part] == null) cur[part] = {};
      cur = cur[part];
    } else {
      const name = part.substring(0, part.indexOf("["));
      const sel = part.substring(part.indexOf("[") + 1, part.length - 1);
      const arr = cur[name];
      if (!Array.isArray(arr)) return;
      if (sel.indexOf("=") !== -1) {
        const [k, v] = sel.split("=");
        cur = arr.find(function(item) { return item && String(item[k]) === v; });
      } else {
        cur = arr[parseInt(sel, 10)];
      }
      if (cur == null) return;
    }
  }
  const last = parts[parts.length - 1];
  if (last.indexOf("[") === -1 && cur != null) {
    cur[last] = value;
  }
}

/* ===== Update field ===== */
function updateField(path, newVal) {
  setByPath(state, path, newVal);
  const origVal = getByPath(ORIGINAL, path);
  const same = JSON.stringify(origVal) === JSON.stringify(newVal);
  if (same) {
    corrections.delete(path);
  } else {
    corrections.set(path, { path: path, label: path.split(".").pop(), was: origVal, now: newVal });
  }
  refreshSanity();
  refreshCorrectionsBar();
  markChanged(path);
  scheduleCheck();
}

function markChanged(path) {
  var el = document.querySelector('[data-path="' + path + '"]');
  if (!el) return;
  var fg = el.closest('.field-group');
  if (!fg) return;
  var origVal = getByPath(ORIGINAL, path);
  var curVal = getByPath(state, path);
  if (JSON.stringify(origVal) !== JSON.stringify(curVal)) {
    fg.classList.add('changed');
    var wasEl = fg.querySelector('.field-was');
    if (wasEl) wasEl.textContent = 'was ' + (origVal != null ? String(origVal) : '\u2014');
  } else {
    fg.classList.remove('changed');
    var wasEl2 = fg.querySelector('.field-was');
    if (wasEl2) wasEl2.textContent = '';
  }
}

/* ===== Formatting helpers ===== */
function fmtCurrency(v) {
  if (v == null) return "\u2014";
  return "$" + Number(v).toLocaleString("en-US", { maximumFractionDigits: 0 });
}

/* ===== Sanity metrics ===== */
function computeSanity() {
  var cash = getByPath(state, "cash.current_balance") || 0;
  var burn = getByPath(state, "cash.monthly_net_burn") || 0;
  var mrr = getByPath(state, "revenue.mrr.value") || 0;
  var customers = getByPath(state, "revenue.customers") || 0;
  var growthRate = getByPath(state, "revenue.growth_rate_monthly") || 0;
  var arpuInput = getByPath(state, "unit_economics.ltv.inputs.arpu_monthly");

  var runway = burn > 0 ? Math.round(cash / burn * 10) / 10 : null;
  var monthlyNewArr = mrr * growthRate * 12;
  var burnMultiple = monthlyNewArr > 0 ? Math.round(burn / (monthlyNewArr / 12) * 10) / 10 : null;
  var arpu = customers > 0 ? Math.round(mrr / customers * 100) / 100 : null;

  var hc = getByPath(state, "expenses.headcount") || [];
  var opex = getByPath(state, "expenses.opex_monthly") || [];
  var cogsObj = getByPath(state, "expenses.cogs") || {};
  var totalExpenses = 0;
  hc.forEach(function(h) {
    var salary = (h.salary_annual || 0) / 12;
    var burden = salary * (h.burden_pct || 0);
    totalExpenses += (salary + burden) * (h.count || 1);
  });
  opex.forEach(function(o) { totalExpenses += o.amount || 0; });
  Object.values(cogsObj).forEach(function(v) { if (typeof v === "number") totalExpenses += v; });
  var denom = burn + mrr;
  var coverage = denom > 0 ? Math.round(totalExpenses / denom * 100) / 100 : null;

  return {
    runway: { value: runway, warn: runway != null && runway < 6 },
    burnMultiple: { value: burnMultiple, warn: burnMultiple != null && burnMultiple > 3 },
    arpu: {
      value: arpu,
      warn: arpu != null && arpuInput != null && Math.abs(arpu - arpuInput) / arpuInput > 0.2
    },
    coverage: { value: coverage, warn: coverage != null && (coverage < 0.5 || coverage > 1.5) }
  };
}

function refreshSanity() {
  var s = computeSanity();
  updateMetricCard("runway", s.runway.value, " mo", s.runway.warn);
  updateMetricCard("burn-multiple", s.burnMultiple.value, "x", s.burnMultiple.warn);
  updateMetricCard("arpu-check", s.arpu.value != null ? fmtCurrency(s.arpu.value) : null, "", s.arpu.warn);
  updateMetricCard("expense-coverage", s.coverage.value, "", s.coverage.warn);
}

function updateMetricCard(id, value, unit, warn) {
  var card = document.getElementById("sanity-" + id);
  if (!card) return;
  var valEl = card.querySelector(".value");
  if (valEl) valEl.textContent = value != null ? String(value) + (unit || "") : "\u2014";
  card.className = "sanity-card" + (value == null ? "" : (warn ? " warn" : " pass"));
}

function buildSanityStrip() {
  var strip = document.getElementById("sanity-strip");
  var cards = [
    { id: "runway", label: "Runway" },
    { id: "burn-multiple", label: "Burn Multiple" },
    { id: "arpu-check", label: "ARPU Check" },
    { id: "expense-coverage", label: "Expense Coverage" }
  ];
  cards.forEach(function(c) {
    var div = document.createElement("div");
    div.className = "sanity-card";
    div.id = "sanity-" + c.id;
    var lbl = document.createElement("div");
    lbl.className = "label";
    lbl.textContent = c.label;
    var val = document.createElement("div");
    val.className = "value";
    val.textContent = "\u2014";
    div.appendChild(lbl);
    div.appendChild(val);
    strip.appendChild(div);
  });
  refreshSanity();
}

/* ===== Debounced server check ===== */
var checkTimeout = null;
function scheduleCheck() {
  clearTimeout(checkTimeout);
  /* file:// URLs cannot use fetch — just refresh JS sanity */
  if (window.location.protocol === "file:") {
    refreshSanity();
    return;
  }
  checkTimeout = setTimeout(function() {
    fetch("/api/check", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ state: state, ils_fields: ilsFields })
    }).then(function(r) { return r.json(); }).then(function(result) {
      updateWarnings(result.warnings || []);
      if (result.sanity) updateSanityFromServer(result.sanity);
    }).catch(function() {
      refreshSanity();
    });
  }, 800);
}

function updateWarnings(warnings) {
  var container = document.getElementById("warnings-container");
  while (container.firstChild) container.removeChild(container.firstChild);
  /* Clear previous field highlights */
  document.querySelectorAll(".field-warning").forEach(function(el) { el.classList.remove("field-warning"); });

  for (var i = 0; i < warnings.length; i++) {
    var w = warnings[i];
    if (warningOverrides.has(w.code)) continue;
    var card = document.createElement("div");
    card.className = "warning-card";
    var msg = document.createElement("span");
    msg.className = "msg";
    msg.textContent = w.message || w.code || "Warning";
    var btn = document.createElement("button");
    btn.className = "dismiss-btn";
    btn.textContent = "Dismiss";
    btn.addEventListener("click", (function(wRef, cardRef) {
      return function() {
        warningOverrides.set(wRef.code, { code: wRef.code, reason: "founder_dismissed" });
        cardRef.remove();
        var fields = wRef.contributing_fields || [];
        for (var j = 0; j < fields.length; j++) {
          var inp = document.querySelector('[data-path="' + fields[j] + '"]');
          if (inp) inp.classList.remove("field-warning");
        }
      };
    })(w, card));
    card.appendChild(msg);
    card.appendChild(btn);
    container.appendChild(card);
    /* Highlight contributing fields */
    var cfields = w.contributing_fields || [];
    for (var k = 0; k < cfields.length; k++) {
      var input = document.querySelector('[data-path="' + cfields[k] + '"]');
      if (input) input.classList.add("field-warning");
    }
  }
}

function updateSanityFromServer(sanity) {
  if (sanity.runway_months != null) updateMetricCard("runway", sanity.runway_months, " mo", sanity.runway_months < 6);
  if (sanity.burn_multiple != null) updateMetricCard("burn-multiple", sanity.burn_multiple, "x", sanity.burn_multiple > 3);
  if (sanity.arpu_computed != null) {
    var arpuWarn = false;
    if (sanity.arpu_input != null && sanity.arpu_input > 0) {
      arpuWarn = Math.abs(sanity.arpu_computed - sanity.arpu_input) / sanity.arpu_input > 0.2;
    }
    updateMetricCard("arpu-check", fmtCurrency(sanity.arpu_computed), "", arpuWarn);
  }
  if (sanity.expense_coverage != null) {
    var covWarn = sanity.expense_coverage < 0.5 || sanity.expense_coverage > 1.5;
    updateMetricCard("expense-coverage", sanity.expense_coverage, "", covWarn);
  }
}

/* ===== Corrections drawer ===== */
function refreshCorrectionsBar() {
  document.getElementById("corr-count").textContent = String(corrections.size);
  var tbody = document.getElementById("corrections-tbody");
  while (tbody.firstChild) tbody.removeChild(tbody.firstChild);
  var empty = document.getElementById("corrections-empty");
  var table = document.getElementById("corrections-table");
  if (corrections.size === 0) {
    empty.style.display = "block";
    table.style.display = "none";
    return;
  }
  empty.style.display = "none";
  table.style.display = "table";
  corrections.forEach(function(c, path) {
    var tr = document.createElement("tr");
    var tdField = document.createElement("td");
    tdField.className = "field-col";
    tdField.textContent = c.label;
    var tdOld = document.createElement("td");
    tdOld.className = "old-val";
    tdOld.textContent = c.was != null ? String(c.was) : "\u2014";
    var tdNew = document.createElement("td");
    tdNew.className = "new-val";
    tdNew.textContent = c.now != null ? String(c.now) : "\u2014";
    var tdUndo = document.createElement("td");
    var undoBtn = document.createElement("button");
    undoBtn.className = "undo-btn";
    undoBtn.textContent = "Undo";
    undoBtn.addEventListener("click", function() {
      setByPath(state, path, c.was);
      corrections.delete(path);
      /* Update the input field */
      var input = document.querySelector("[data-path=\"" + path + "\"]");
      if (input) {
        input.value = c.was != null ? String(c.was) : "";
        input.classList.remove("changed");
      }
      refreshCorrectionsBar();
      refreshSanity();
      scheduleCheck();
    });
    tdUndo.appendChild(undoBtn);
    tr.appendChild(tdField);
    tr.appendChild(tdOld);
    tr.appendChild(tdNew);
    tr.appendChild(tdUndo);
    tbody.appendChild(tr);
  });
}

function toggleDrawer() {
  document.getElementById("corrections-bar").classList.toggle("open");
  var toggleText = document.querySelector(".corrections-toggle span:first-child");
  var bar = document.getElementById("corrections-bar");
  toggleText.textContent = bar.classList.contains("open") ? "Hide changes" : "Show changes";
}

/* ===== Submit handler ===== */
function triggerDownload(payload) {
  try {
    var blob = new Blob([payload], { type: "application/json" });
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url;
    a.download = "corrections.json";
    document.body.appendChild(a);
    a.click();
    setTimeout(function() {
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    }, 100);
  } catch (e) {
    /* Fallback: data URI if Blob/ObjectURL not supported */
    var a2 = document.createElement("a");
    a2.href = "data:application/json;charset=utf-8," + encodeURIComponent(payload);
    a2.download = "corrections.json";
    document.body.appendChild(a2);
    a2.click();
    document.body.removeChild(a2);
  }
}

function submitFeedback() {
  var btn = document.getElementById("submit-btn");
  btn.disabled = true;
  btn.textContent = "Submitting...";

  var payload = JSON.stringify({
    corrections: Array.from(corrections.values()),
    corrected: state,
    warning_overrides: Array.from(warningOverrides.values()),
    ils_fields: ilsFields
  }, null, 2);

  /* file:// URLs cannot use fetch — go straight to download */
  if (window.location.protocol === "file:") {
    triggerDownload(payload);
    showOverlay(true);
    return;
  }

  fetch("/api/feedback", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: payload
  }).then(function(resp) {
    if (!resp.ok) throw new Error("Server error");
    showOverlay(false);
  }).catch(function() {
    triggerDownload(payload);
    showOverlay(true);
  });
}

function showOverlay(wasDownload) {
  var btn = document.getElementById("submit-btn");
  btn.textContent = "Submitted";
  var hint = document.getElementById("overlay-hint");
  if (wasDownload) {
    hint.textContent = "Go back to your session and upload the corrections.json file.";
  } else {
    hint.textContent = "Go back to your session and tell Claude you\u2019re done.";
  }
  document.getElementById("overlay").classList.add("show");
}

/* ===== Field builders ===== */
function createFieldGroup(path, label, helperText) {
  var div = document.createElement("div");
  div.className = "field-group";
  var lbl = document.createElement("label");
  lbl.className = "field-label";
  lbl.textContent = label;
  div.appendChild(lbl);
  div.dataset.fieldPath = path;
  return { wrapper: div, addHelper: function() {
    if (helperText) {
      var h = document.createElement("div");
      h.className = "field-helper";
      h.textContent = helperText;
      div.appendChild(h);
    }
    var was = document.createElement("span");
    was.className = "field-was";
    div.appendChild(was);
  }};
}

function createTextInput(path, label, opts) {
  opts = opts || {};
  var fg = createFieldGroup(path, label, opts.helper);
  if (opts.readOnly) {
    var ro = document.createElement("div");
    ro.className = "input-field readonly";
    ro.dataset.path = path;
    var v = getByPath(state, path);
    ro.textContent = v != null ? String(v) : "\u2014";
    fg.wrapper.appendChild(ro);
  } else {
    var input = document.createElement("input");
    input.type = "text";
    input.className = "input-field";
    input.dataset.path = path;
    var val = getByPath(state, path);
    input.value = val != null ? String(val) : "";
    if (opts.datalist) {
      var dlId = "dl-" + path.replace(/\./g, "-");
      input.setAttribute("list", dlId);
      var dl = document.createElement("datalist");
      dl.id = dlId;
      opts.datalist.forEach(function(o) {
        var opt = document.createElement("option");
        opt.value = o;
        dl.appendChild(opt);
      });
      fg.wrapper.appendChild(dl);
    }
    input.addEventListener("input", function() {
      updateField(path, this.value || null);
    });
    fg.wrapper.appendChild(input);
  }
  fg.addHelper();
  return fg.wrapper;
}

function createNumberInput(path, label, opts) {
  opts = opts || {};
  var fg = createFieldGroup(path, label, opts.helper);
  var input = document.createElement("input");
  input.type = "text";
  input.className = "input-field";
  input.dataset.path = path;
  var val = getByPath(state, path);
  input.value = val != null ? String(val) : "";
  input.addEventListener("input", function() {
    if (this.value === "") { updateField(path, null); return; }
    var n = Number(this.value);
    if (!isNaN(n)) updateField(path, n);
  });
  fg.wrapper.appendChild(input);
  fg.addHelper();
  return fg.wrapper;
}

function createPctInput(path, label, opts) {
  opts = opts || {};
  var fg = createFieldGroup(path, label, opts.helper);
  var row = document.createElement("div");
  row.className = "pct-row";
  var input = document.createElement("input");
  input.type = "text";
  input.className = "input-field";
  input.dataset.path = path;
  var val = getByPath(state, path);
  input.value = val != null ? String(Math.round(val * 10000) / 100) : "";
  input.addEventListener("input", function() {
    if (this.value === "") { updateField(path, null); return; }
    var n = Number(this.value);
    if (!isNaN(n)) updateField(path, n / 100);
  });
  row.appendChild(input);
  var suf = document.createElement("span");
  suf.className = "pct-suffix";
  suf.textContent = "%";
  row.appendChild(suf);
  fg.wrapper.appendChild(row);
  fg.addHelper();
  return fg.wrapper;
}

function createCurrencyInput(path, label, opts) {
  opts = opts || {};
  var fxRate = getByPath(state, "israel_specific.fx_rate_ils_usd");
  var hasFx = !!fxRate;
  var fg = createFieldGroup(path, label, opts.helper);
  var row = document.createElement("div");
  row.className = "currency-row";
  var input = document.createElement("input");
  input.type = "text";
  input.className = "input-field";
  input.dataset.path = path;
  input.style.flex = "1";
  var val = getByPath(state, path);
  input.value = val != null ? String(val) : "";
  input.addEventListener("input", function() {
    if (this.value === "") { updateField(path, null); return; }
    var n = Number(this.value.replace(/,/g, ""));
    if (!isNaN(n)) updateField(path, n);
  });
  row.appendChild(input);

  if (hasFx) {
    var toggle = document.createElement("div");
    toggle.className = "currency-toggle";
    var btnUsd = document.createElement("button");
    btnUsd.textContent = "$";
    btnUsd.className = ilsFields[path] ? "" : "active";
    var btnIls = document.createElement("button");
    btnIls.textContent = "\u20aa";
    btnIls.className = ilsFields[path] ? "active" : "";
    btnUsd.addEventListener("click", function() {
      delete ilsFields[path];
      btnUsd.className = "active";
      btnIls.className = "";
      refreshEquiv();
    });
    btnIls.addEventListener("click", function() {
      ilsFields[path] = true;
      btnIls.className = "active";
      btnUsd.className = "";
      refreshEquiv();
    });
    toggle.appendChild(btnUsd);
    toggle.appendChild(btnIls);
    row.appendChild(toggle);
  }
  fg.wrapper.appendChild(row);

  var equivEl = document.createElement("div");
  equivEl.className = "currency-equiv";
  fg.wrapper.appendChild(equivEl);

  function refreshEquiv() {
    var curVal = getByPath(state, path);
    var curFx = getByPath(state, "israel_specific.fx_rate_ils_usd");
    if (!curFx || curVal == null) { equivEl.textContent = ""; return; }
    if (ilsFields[path]) {
      equivEl.textContent = "(~" + fmtCurrency(curVal / curFx) + " USD)";
    } else {
      equivEl.textContent = "(~\u20aa" + Math.round(curVal * curFx).toLocaleString("en-US") + ")";
    }
  }
  refreshEquiv();

  fg.addHelper();
  return fg.wrapper;
}

function createMonthInput(path, label) {
  var fg = createFieldGroup(path, label);
  var input = document.createElement("input");
  input.type = "text";
  input.className = "input-field";
  input.dataset.path = path;
  input.placeholder = "YYYY-MM";
  var val = getByPath(state, path);
  input.value = val != null ? String(val) : "";
  input.addEventListener("input", function() {
    updateField(path, this.value || null);
  });
  fg.wrapper.appendChild(input);
  fg.addHelper();
  return fg.wrapper;
}

function createDropdown(path, label, options) {
  var fg = createFieldGroup(path, label);
  var sel = document.createElement("select");
  sel.className = "input-field";
  sel.dataset.path = path;
  var val = getByPath(state, path);
  options.forEach(function(opt) {
    var o = document.createElement("option");
    o.value = opt;
    o.textContent = opt;
    if (String(val) === opt) o.selected = true;
    sel.appendChild(o);
  });
  sel.addEventListener("change", function() {
    updateField(path, this.value || null);
  });
  fg.wrapper.appendChild(sel);
  fg.addHelper();
  return fg.wrapper;
}

function createBoolDropdown(path, label) {
  var fg = createFieldGroup(path, label);
  var sel = document.createElement("select");
  sel.className = "input-field";
  sel.dataset.path = path;
  var val = getByPath(state, path);
  var strVal = val === true ? "true" : val === false ? "false" : "";
  [["", "\u2014"], ["true", "true"], ["false", "false"]].forEach(function(pair) {
    var o = document.createElement("option");
    o.value = pair[0];
    o.textContent = pair[1];
    if (pair[0] === strVal) o.selected = true;
    sel.appendChild(o);
  });
  sel.addEventListener("change", function() {
    var v = this.value === "true" ? true : this.value === "false" ? false : null;
    updateField(path, v);
  });
  fg.wrapper.appendChild(sel);
  fg.addHelper();
  return fg.wrapper;
}

function createTagChips(path, label, options) {
  var fg = createFieldGroup(path, label);
  var container = document.createElement("div");
  container.className = "chip-container";
  container.dataset.path = path;
  var current = getByPath(state, path) || [];

  options.forEach(function(opt) {
    var chip = document.createElement("span");
    chip.className = "chip" + (current.indexOf(opt) !== -1 ? " selected" : "");
    chip.textContent = opt;
    chip.addEventListener("click", function() {
      var arr = getByPath(state, path) || [];
      arr = arr.slice();
      var idx = arr.indexOf(opt);
      if (idx === -1) arr.push(opt);
      else arr.splice(idx, 1);
      updateField(path, arr);
      chip.className = "chip" + (arr.indexOf(opt) !== -1 ? " selected" : "");
    });
    container.appendChild(chip);
  });
  fg.wrapper.appendChild(container);
  fg.addHelper();
  return fg.wrapper;
}

function createArrayTextInput(path, label, opts) {
  opts = opts || {};
  var fg = createFieldGroup(path, label, opts.helper);
  var input = document.createElement("input");
  input.type = "text";
  input.className = "input-field";
  input.dataset.path = path;
  var arr = getByPath(state, path);
  input.value = Array.isArray(arr) ? arr.join(", ") : (arr != null ? String(arr) : "");
  input.addEventListener("input", function() {
    var v = this.value.trim() === "" ? [] :
      this.value.split(",").map(function(s) { return s.trim(); }).filter(Boolean);
    updateField(path, v);
  });
  fg.wrapper.appendChild(input);
  fg.addHelper();
  return fg.wrapper;
}

/* ===== Editable table ===== */
function createEditableTable(arrayPath, columns) {
  var container = document.createElement("div");
  var table = document.createElement("table");
  table.className = "edit-table";
  var thead = document.createElement("thead");
  var hrow = document.createElement("tr");
  columns.forEach(function(col) {
    var th = document.createElement("th");
    th.textContent = col.label;
    hrow.appendChild(th);
  });
  var thEmpty = document.createElement("th");
  hrow.appendChild(thEmpty);
  thead.appendChild(hrow);
  table.appendChild(thead);

  var tbody = document.createElement("tbody");
  table.appendChild(tbody);
  container.appendChild(table);

  function renderRows() {
    while (tbody.firstChild) tbody.removeChild(tbody.firstChild);
    var arr = getByPath(state, arrayPath) || [];
    arr.forEach(function(row, rowIdx) {
      var tr = document.createElement("tr");
      columns.forEach(function(col) {
        var td = document.createElement("td");
        var val = row[col.key];

        if (col.type === "bool") {
          var sel = document.createElement("select");
          sel.className = "input-field";
          sel.style.width = col.width || "auto";
          [["true", "true"], ["false", "false"]].forEach(function(pair) {
            var o = document.createElement("option");
            o.value = pair[0];
            o.textContent = pair[1];
            if (String(val) === pair[0]) o.selected = true;
            sel.appendChild(o);
          });
          sel.addEventListener("change", (function(ri, ck) {
            return function() { updateTableCell(arrayPath, ri, ck, this.value === "true", renderRows); };
          })(rowIdx, col.key));
          td.appendChild(sel);
        } else {
          var inp = document.createElement("input");
          inp.type = "text";
          inp.className = "input-field";
          inp.style.width = col.width || "100%";
          if (col.type === "month") inp.placeholder = "YYYY-MM";
          if (col.type === "pct" && val != null) {
            inp.value = String(Math.round(val * 10000) / 100);
          } else {
            inp.value = val != null ? String(val) : "";
          }
          inp.addEventListener("input", (function(ri, ck, ct) {
            return function() {
              var newVal;
              if (ct === "number" || ct === "currency") {
                newVal = this.value === "" ? null : Number(this.value.replace(/,/g, ""));
                if (this.value !== "" && isNaN(newVal)) return;
              } else if (ct === "pct") {
                if (this.value === "") newVal = null;
                else { newVal = Number(this.value); if (isNaN(newVal)) return; newVal = newVal / 100; }
              } else {
                newVal = this.value || null;
              }
              updateTableCell(arrayPath, ri, ck, newVal, renderRows);
            };
          })(rowIdx, col.key, col.type));
          td.appendChild(inp);
        }
        tr.appendChild(td);
      });
      var tdRm = document.createElement("td");
      var rmBtn = document.createElement("button");
      rmBtn.className = "remove-row-btn";
      rmBtn.textContent = "\u2715";
      rmBtn.addEventListener("click", (function(ri) {
        return function() {
          var nextArr = getByPath(state, arrayPath) || [];
          nextArr.splice(ri, 1);
          setByPath(state, arrayPath, nextArr);
          renderRows();
          refreshSanity();
          scheduleCheck();
        };
      })(rowIdx));
      tdRm.appendChild(rmBtn);
      tr.appendChild(tdRm);
      tbody.appendChild(tr);
    });
  }

  renderRows();

  var addBtn = document.createElement("button");
  addBtn.className = "add-row-btn";
  addBtn.textContent = "+ Add row";
  addBtn.addEventListener("click", function() {
    var arr = getByPath(state, arrayPath) || [];
    var newRow = {};
    columns.forEach(function(col) { newRow[col.key] = null; });
    arr.push(newRow);
    setByPath(state, arrayPath, arr);
    renderRows();
  });
  container.appendChild(addBtn);
  return container;
}

function updateTableCell(arrayPath, rowIdx, colKey, newVal, renderFn) {
  var arr = getByPath(state, arrayPath) || [];
  if (arr[rowIdx]) arr[rowIdx][colKey] = newVal;
  var origArr = getByPath(ORIGINAL, arrayPath) || [];
  var origRow = origArr[rowIdx];
  var origVal = origRow ? origRow[colKey] : undefined;
  var changePath = arrayPath + "[" + rowIdx + "]." + colKey;
  if (JSON.stringify(origVal) === JSON.stringify(newVal)) {
    corrections.delete(changePath);
  } else {
    corrections.set(changePath, { path: changePath, label: colKey, was: origVal, now: newVal });
  }
  refreshSanity();
  refreshCorrectionsBar();
  scheduleCheck();
}

/* ===== Inline pair helper ===== */
function createInlinePair() {
  var div = document.createElement("div");
  div.className = "inline-pair";
  for (var i = 1; i < arguments.length + 1; i++) {
    if (arguments[i - 1]) div.appendChild(arguments[i - 1]);
  }
  return div;
}

/* ===== Section header ===== */
function createSectionHeader(text) {
  var div = document.createElement("div");
  div.className = "section-header";
  div.textContent = text;
  return div;
}

/* ===== Accordion ===== */
function createAccordion(id, title) {
  var wrapper = document.createElement("div");
  var header = document.createElement("div");
  header.className = "accordion-header";
  header.textContent = "\u25b8 " + title;
  var body = document.createElement("div");
  body.className = "accordion-body";
  header.addEventListener("click", function() {
    accordionState[id] = !accordionState[id];
    body.classList.toggle("open");
    header.textContent = (accordionState[id] ? "\u25be " : "\u25b8 ") + title;
  });
  wrapper.appendChild(header);
  wrapper.appendChild(body);
  wrapper._body = body;
  return wrapper;
}

/* ===== Tab rendering ===== */
function renderCompanyTab() {
  var c = document.createElement("div");
  c.appendChild(createTextInput("company.company_name", "Company Name"));
  c.appendChild(createTextInput("company.slug", "Slug", { readOnly: true }));
  c.appendChild(createTextInput("company.sector", "Sector", {
    datalist: ["B2B SaaS", "Fintech", "HealthTech", "EdTech", "Cybersecurity", "AI/ML", "DevTools", "Consumer", "Marketplace", "Hardware"]
  }));
  c.appendChild(createTextInput("company.geography", "Geography", {
    datalist: ["Israel", "US", "Europe", "UK", "APAC", "LATAM", "Global"]
  }));
  c.appendChild(createDropdown("company.stage", "Stage", ["pre-seed", "seed", "series-a", "series-b", "later"]));
  c.appendChild(createDropdown("company.revenue_model_type", "Revenue Model Type", ["saas-plg", "saas-sales-led", "marketplace", "ai-native", "usage-based", "hardware", "hardware-subscription", "consumer-subscription", "transactional-fintech", "annual-contracts"]));
  c.appendChild(createDropdown("company.model_format", "Model Format", ["spreadsheet", "deck", "conversational", "partial"]));
  c.appendChild(createDropdown("company.data_confidence", "Data Confidence", ["exact", "estimated", "mixed"]));
  c.appendChild(createTagChips("company.traits", "Traits", ["multi-currency", "multi-entity", "multi-market", "annual-contracts", "ai-powered"]));
  return c;
}

function renderRevenueTab() {
  var c = document.createElement("div");
  c.appendChild(createInlinePair(
    createCurrencyInput("revenue.mrr.value", "Monthly Recurring Revenue (MRR)"),
    createMonthInput("revenue.mrr.as_of", "As of")
  ));
  c.appendChild(createInlinePair(
    createCurrencyInput("revenue.arr.value", "Annual Recurring Revenue (ARR)"),
    createMonthInput("revenue.arr.as_of", "As of")
  ));
  c.appendChild(createNumberInput("revenue.customers", "Number of Customers", { helper: "Paying customers only" }));
  c.appendChild(createPctInput("revenue.growth_rate_monthly", "Monthly Revenue Growth", { helper: "Month-over-month, e.g. 15%" }));
  c.appendChild(createPctInput("revenue.churn_monthly", "Monthly Churn Rate", { helper: "% of customers lost per month" }));
  c.appendChild(createPctInput("revenue.nrr", "Net Revenue Retention (NRR)", { helper: "Including expansion; >100% = growing from existing" }));
  c.appendChild(createPctInput("revenue.grr", "Gross Revenue Retention (GRR)", { helper: "Excluding expansion; measures pure churn impact" }));
  c.appendChild(createTextInput("revenue.expansion_model", "Expansion Model"));

  /* Monthly time series */
  var monthly = getByPath(state, "revenue.monthly");
  if (Array.isArray(monthly) && monthly.length > 0) {
    c.appendChild(createSectionHeader("Monthly Revenue"));
    c.appendChild(createEditableTable("revenue.monthly", [
      { key: "month", label: "Month", type: "text", width: "100px" },
      { key: "total", label: "Total ($)", type: "number" },
      { key: "arr", label: "ARR ($)", type: "number" },
      { key: "actual", label: "Actual?", type: "bool", width: "60px" }
    ]));
  }

  /* Quarterly time series */
  var quarterly = getByPath(state, "revenue.quarterly");
  if (Array.isArray(quarterly) && quarterly.length > 0) {
    c.appendChild(createSectionHeader("Quarterly Revenue"));
    c.appendChild(createEditableTable("revenue.quarterly", [
      { key: "quarter", label: "Quarter", type: "text", width: "100px" },
      { key: "total", label: "Total ($)", type: "number" },
      { key: "arr", label: "ARR ($)", type: "number" },
      { key: "actual", label: "Actual?", type: "bool", width: "60px" }
    ]));
  }

  return c;
}

function renderCashTab() {
  var c = document.createElement("div");
  c.appendChild(createInlinePair(
    createCurrencyInput("cash.current_balance", "Cash in Bank", { helper: "Current balance across all accounts" }),
    createMonthInput("cash.balance_date", "Balance Date")
  ));
  c.appendChild(createCurrencyInput("cash.monthly_net_burn", "Monthly Burn", { helper: "Net cash outflow per month \u2014 already net of revenue" }));
  c.appendChild(createCurrencyInput("cash.debt", "Outstanding Debt"));
  c.appendChild(createSectionHeader("Fundraising"));
  c.appendChild(createInlinePair(
    createCurrencyInput("cash.fundraising.target_raise", "Target Raise Amount"),
    createMonthInput("cash.fundraising.expected_close", "Expected Close")
  ));
  c.appendChild(createSectionHeader("Government Grants"));
  c.appendChild(createCurrencyInput("cash.grants.iia_approved", "IIA Approved Amount", { helper: "Approved Innovation Authority grant" }));
  c.appendChild(createCurrencyInput("cash.grants.iia_pending", "IIA Pending Amount", { helper: "Pending grant application" }));
  c.appendChild(createNumberInput("cash.grants.iia_disbursement_months", "Disbursement Period (months)", { helper: "Default 12" }));
  c.appendChild(createNumberInput("cash.grants.iia_start_month", "Start Offset (months)", { helper: "Months from balance date, default 1" }));
  c.appendChild(createPctInput("cash.grants.royalty_rate", "Royalty Rate", { helper: "Repayment rate on grant revenue" }));
  return c;
}

function renderTeamCostsTab() {
  var c = document.createElement("div");
  c.appendChild(createSectionHeader("Headcount"));
  c.appendChild(createEditableTable("expenses.headcount", [
    { key: "role", label: "Role", type: "text" },
    { key: "count", label: "Count", type: "number" },
    { key: "start_month", label: "Start Month", type: "month" },
    { key: "salary_annual", label: "Annual Salary ($)", type: "currency" },
    { key: "geography", label: "Geography", type: "text" },
    { key: "burden_pct", label: "Burden %", type: "pct" }
  ]));
  c.appendChild(createSectionHeader("Monthly Operating Expenses"));
  c.appendChild(createEditableTable("expenses.opex_monthly", [
    { key: "category", label: "Category", type: "text" },
    { key: "amount", label: "Amount ($)", type: "currency" },
    { key: "start_month", label: "Start Month", type: "month" }
  ]));
  c.appendChild(createSectionHeader("Cost of Goods Sold (COGS)"));
  c.appendChild(createCurrencyInput("expenses.cogs.hosting", "Hosting"));
  c.appendChild(createCurrencyInput("expenses.cogs.inference_costs", "Inference Costs"));
  c.appendChild(createCurrencyInput("expenses.cogs.support", "Support"));
  c.appendChild(createCurrencyInput("expenses.cogs.other", "Other COGS"));
  return c;
}

function renderUnitEconomicsTab() {
  var c = document.createElement("div");
  c.appendChild(createCurrencyInput("unit_economics.cac.total", "Customer Acquisition Cost (CAC)"));
  c.appendChild(createCurrencyInput("unit_economics.ltv.value", "Customer Lifetime Value (LTV)"));
  c.appendChild(createCurrencyInput("unit_economics.ltv.inputs.arpu_monthly", "Revenue per Customer (monthly)"));
  c.appendChild(createPctInput("unit_economics.ltv.inputs.churn_monthly", "Monthly Churn (for LTV)"));
  c.appendChild(createPctInput("unit_economics.ltv.inputs.gross_margin", "Gross Margin (for LTV)"));
  c.appendChild(createPctInput("unit_economics.gross_margin", "Gross Margin"));
  c.appendChild(createNumberInput("unit_economics.payback_months", "CAC Payback (months)"));
  c.appendChild(createNumberInput("unit_economics.burn_multiple", "Burn Multiple", { helper: "Net burn / net new ARR" }));
  return c;
}

function renderMoreTab() {
  var c = document.createElement("div");

  /* Scenarios */
  var scenAcc = createAccordion("scenarios", "Scenarios");
  ["base", "slow", "crisis"].forEach(function(name) {
    var div = document.createElement("div");
    div.style.marginBottom = "12px";
    var heading = document.createElement("div");
    heading.style.fontWeight = "600";
    heading.style.fontSize = "0.85rem";
    heading.style.marginBottom = "6px";
    heading.textContent = name.charAt(0).toUpperCase() + name.slice(1);
    div.appendChild(heading);
    div.appendChild(createPctInput("scenarios." + name + ".growth_rate", "Growth Rate"));
    div.appendChild(createPctInput("scenarios." + name + ".burn_change", "Burn Change"));
    scenAcc._body.appendChild(div);
  });
  c.appendChild(scenAcc);

  /* Structure */
  var structAcc = createAccordion("structure", "Structure");
  structAcc._body.appendChild(createBoolDropdown("structure.has_assumptions_tab", "Has Assumptions Tab"));
  structAcc._body.appendChild(createBoolDropdown("structure.has_scenarios", "Has Scenarios"));
  structAcc._body.appendChild(createDropdown("structure.formatting_quality", "Formatting Quality", ["good", "acceptable", "poor"]));
  c.appendChild(structAcc);

  /* Israel-Specific */
  var ilAcc = createAccordion("israel", "Israel-Specific");
  ilAcc._body.appendChild(createNumberInput("israel_specific.fx_rate_ils_usd", "FX Rate (ILS/USD)"));
  ilAcc._body.appendChild(createPctInput("israel_specific.ils_expense_fraction", "Expenses Paid in ILS"));
  ilAcc._body.appendChild(createBoolDropdown("israel_specific.iia_grants", "IIA Grants Included"));
  ilAcc._body.appendChild(createBoolDropdown("israel_specific.iia_royalties_modeled", "IIA Royalties Modeled"));
  c.appendChild(ilAcc);

  /* Fundraise Plan */
  var brAcc = createAccordion("bridge", "Fundraise Plan");
  brAcc._body.appendChild(createNumberInput("bridge.runway_target_months", "Runway Target (months)"));
  brAcc._body.appendChild(createArrayTextInput("bridge.milestones", "Milestones", { helper: "Comma-separated list" }));
  brAcc._body.appendChild(createTextInput("bridge.next_round_target", "Next Round Target"));
  c.appendChild(brAcc);

  /* Metadata */
  var metaAcc = createAccordion("metadata", "Metadata");
  metaAcc._body.appendChild(createTextInput("metadata.source_periodicity", "Source Periodicity", { readOnly: true }));
  metaAcc._body.appendChild(createTextInput("metadata.conversion_applied", "Conversion Applied", { readOnly: true }));
  c.appendChild(metaAcc);

  return c;
}

/* ===== Tab setup ===== */
function buildTabs() {
  var tabs = [
    { id: "company", label: "Company", render: renderCompanyTab },
    { id: "revenue", label: "Revenue", render: renderRevenueTab },
    { id: "cash", label: "Cash Position", render: renderCashTab },
    { id: "team", label: "Team & Costs", render: renderTeamCostsTab },
    { id: "unit-economics", label: "Unit Economics", render: renderUnitEconomicsTab },
    { id: "more", label: "More", render: renderMoreTab }
  ];

  var bar = document.getElementById("tab-bar");
  var panels = document.getElementById("tab-panels");

  tabs.forEach(function(tab) {
    var btn = document.createElement("button");
    btn.className = "tab-btn" + (tab.id === activeTab ? " active" : "");
    btn.textContent = tab.label;
    btn.dataset.tab = tab.id;
    btn.addEventListener("click", function() {
      activeTab = tab.id;
      bar.querySelectorAll(".tab-btn").forEach(function(b) { b.className = "tab-btn" + (b.dataset.tab === activeTab ? " active" : ""); });
      panels.querySelectorAll(".tab-content").forEach(function(p) { p.className = "tab-content" + (p.dataset.tab === activeTab ? " active" : ""); });
    });
    bar.appendChild(btn);

    var panel = document.createElement("div");
    panel.className = "tab-content" + (tab.id === activeTab ? " active" : "");
    panel.dataset.tab = tab.id;
    panel.appendChild(tab.render());
    panels.appendChild(panel);
  });
}

/* ===== Init ===== */
function init() {
  var company = getByPath(state, "company") || {};
  document.getElementById("header-title").textContent = (company.company_name || "Unknown") + " \u2014 Financial Model Review";
  document.getElementById("stage-badge").textContent = company.stage || "";
  buildSanityStrip();
  buildTabs();
  document.getElementById("submit-btn").addEventListener("click", submitFeedback);
  document.getElementById("corrections-summary").addEventListener("click", toggleDrawer);
  refreshCorrectionsBar();
  scheduleCheck();
}

init();
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Build / write helpers
# ---------------------------------------------------------------------------


def _build_html(inputs: dict[str, Any]) -> str:
    """Inject embedded data into the HTML template."""
    data_js = f"const DATA = {json.dumps(inputs)};"
    return _HTML_TEMPLATE.replace("/*__EMBEDDED_DATA__*/", data_js)


def _write_static(inputs: dict[str, Any], output_path: str) -> None:
    """Write self-contained HTML to a file, print JSON status to stdout."""
    html = _build_html(inputs)
    with open(output_path, "w") as f:
        f.write(html)
    abs_path = os.path.abspath(output_path)
    print(json.dumps({"mode": "static", "path": abs_path}))


# ---------------------------------------------------------------------------
# Server mode helpers
# ---------------------------------------------------------------------------

# FMR scripts directory — for importing validate_inputs, unit_economics, runway
_scripts_dir = os.path.dirname(os.path.abspath(__file__))


def _deep_get_by_path(data: dict[str, Any], dotted_path: str) -> Any:
    """Navigate nested dict by dotted path like 'cash.monthly_net_burn'."""
    obj: Any = data
    for part in dotted_path.split("."):
        if isinstance(obj, dict):
            obj = obj.get(part)
        else:
            return None
    return obj


def _set_by_path(data: dict[str, Any], dotted_path: str, value: Any) -> None:
    """Set a value in a nested dict by dotted path, creating intermediate dicts."""
    parts = dotted_path.split(".")
    obj: Any = data
    for part in parts[:-1]:
        if not isinstance(obj, dict):
            return
        if part not in obj or not isinstance(obj[part], dict):
            obj[part] = {}
        obj = obj[part]
    if isinstance(obj, dict):
        obj[parts[-1]] = value


def _coerce_state(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Coerce browser form string values back to proper Python types.

    Returns a list of coercion errors (empty if all values coerced cleanly).
    """
    errors: list[dict[str, Any]] = []

    _NUMERIC_PATHS = [
        "cash.current_balance",
        "cash.monthly_net_burn",
        "cash.debt",
        "revenue.mrr.value",
        "revenue.arr.value",
        "revenue.customers",
        "revenue.growth_rate_monthly",
        "revenue.churn_monthly",
        "revenue.nrr",
        "revenue.grr",
        "unit_economics.cac.total",
        "unit_economics.ltv.value",
        "unit_economics.ltv.inputs.arpu_monthly",
        "unit_economics.ltv.inputs.churn_monthly",
        "unit_economics.ltv.inputs.gross_margin",
        "unit_economics.gross_margin",
        "unit_economics.payback_months",
        "cash.fundraising.target_raise",
        "israel_specific.fx_rate_ils_usd",
    ]

    for path in _NUMERIC_PATHS:
        val = _deep_get_by_path(state, path)
        if val is None or isinstance(val, (int, float)):
            continue
        if isinstance(val, str):
            cleaned = val.strip().replace(",", "")
            if cleaned == "" or cleaned == "-":
                _set_by_path(state, path, None)
                continue
            try:
                numeric = float(cleaned)
                if numeric == int(numeric) and "." not in cleaned:
                    _set_by_path(state, path, int(numeric))
                else:
                    _set_by_path(state, path, numeric)
            except ValueError:
                errors.append(
                    {
                        "code": "COERCION_ERROR",
                        "message": f"Cannot convert '{val}' to number for {path}",
                        "field": path,
                        "layer": 0,
                    }
                )

    # Coerce numeric fields inside array entries
    headcount = _deep_get_by_path(state, "expenses.headcount")
    if isinstance(headcount, list):
        for i, entry in enumerate(headcount):
            if not isinstance(entry, dict):
                continue
            for key in ("count", "salary_annual", "burden_pct"):
                val = entry.get(key)
                if val is None or isinstance(val, (int, float)):
                    continue
                if isinstance(val, str):
                    cleaned = val.strip().replace(",", "")
                    if cleaned == "" or cleaned == "-":
                        entry[key] = None
                        continue
                    try:
                        numeric = float(cleaned)
                        entry[key] = int(numeric) if numeric == int(numeric) and "." not in cleaned else numeric
                    except ValueError:
                        errors.append(
                            {
                                "code": "COERCION_ERROR",
                                "message": f"Cannot convert '{val}' to number for expenses.headcount[{i}].{key}",
                                "field": f"expenses.headcount[{i}].{key}",
                                "layer": 0,
                            }
                        )

    opex = _deep_get_by_path(state, "expenses.opex_monthly")
    if isinstance(opex, list):
        for i, entry in enumerate(opex):
            if not isinstance(entry, dict):
                continue
            val = entry.get("amount")
            if val is None or isinstance(val, (int, float)):
                continue
            if isinstance(val, str):
                cleaned = val.strip().replace(",", "")
                if cleaned == "" or cleaned == "-":
                    entry["amount"] = None
                    continue
                try:
                    numeric = float(cleaned)
                    entry["amount"] = int(numeric) if numeric == int(numeric) and "." not in cleaned else numeric
                except ValueError:
                    errors.append(
                        {
                            "code": "COERCION_ERROR",
                            "message": f"Cannot convert '{val}' to number for expenses.opex_monthly[{i}].amount",
                            "field": f"expenses.opex_monthly[{i}].amount",
                            "layer": 0,
                        }
                    )

    # Coerce COGS values
    cogs = _deep_get_by_path(state, "expenses.cogs")
    if isinstance(cogs, dict):
        for key, val in list(cogs.items()):
            if val is None or isinstance(val, (int, float)):
                continue
            if isinstance(val, str):
                cleaned = val.strip().replace(",", "")
                if cleaned == "" or cleaned == "-":
                    cogs[key] = None
                    continue
                try:
                    numeric = float(cleaned)
                    cogs[key] = int(numeric) if numeric == int(numeric) and "." not in cleaned else numeric
                except ValueError:
                    errors.append(
                        {
                            "code": "COERCION_ERROR",
                            "message": f"Cannot convert '{val}' to number for expenses.cogs.{key}",
                            "field": f"expenses.cogs.{key}",
                            "layer": 0,
                        }
                    )

    return errors


def _normalize_to_usd(state: dict[str, Any], ils_fields: dict[str, bool]) -> None:
    """Convert ILS-tagged fields to USD using the fx rate in the state."""
    if not ils_fields:
        return
    fx_rate = _deep_get_by_path(state, "israel_specific.fx_rate_ils_usd")
    if not isinstance(fx_rate, (int, float)) or fx_rate <= 0:
        return
    for field_path, is_ils in ils_fields.items():
        if not is_ils:
            continue
        val = _deep_get_by_path(state, field_path)
        if isinstance(val, (int, float)):
            _set_by_path(state, field_path, round(val / fx_rate, 2))


def _canonicalize_time_series(state: dict[str, Any]) -> None:
    """Ensure time series arrays are sorted by date field."""
    revenue = state.get("revenue")
    if not isinstance(revenue, dict):
        return
    for key, date_field in (("monthly", "month"), ("quarterly", "quarter")):
        series = revenue.get(key)
        if not isinstance(series, list):
            continue
        series.sort(key=lambda e: e.get(date_field, "") if isinstance(e, dict) else "")


# Map warning codes to the fields that contribute to them (for UI highlighting)
_CONTRIBUTING_FIELDS: dict[str, list[str]] = {
    "BURN_REVENUE_SUSPECT": ["cash.monthly_net_burn", "revenue.mrr.value"],
    "BURN_MULTIPLE_SUSPECT": ["cash.monthly_net_burn", "revenue.mrr.value", "revenue.growth_rate_monthly"],
    "ARPU_SUSPECT": ["revenue.mrr.value", "revenue.customers", "unit_economics.ltv.inputs.arpu_monthly"],
    "ARPU_INCONSISTENT": ["revenue.mrr.value", "revenue.customers", "unit_economics.ltv.inputs.arpu_monthly"],
    "GROWTH_RATE_SUSPECT": ["revenue.growth_rate_monthly"],
    "GROWTH_RATE_ZERO_SUSPECT": ["revenue.growth_rate_monthly", "revenue.mrr.value", "revenue.customers"],
    "EXPENSE_COVERAGE_SUSPECT": ["cash.monthly_net_burn", "revenue.mrr.value", "expenses"],
    "CASH_ZERO_SUSPECT": ["cash.current_balance"],
    "ARR_MRR_MISMATCH": ["revenue.mrr.value", "revenue.arr.value"],
    "TIMESERIES_MRR_MISMATCH": ["revenue.mrr.value"],
    "TIMESERIES_ARR_MISMATCH": ["revenue.arr.value"],
}

# Map warning codes to the tab they should display in
_WARNING_TAB: dict[str, str] = {
    "BURN_REVENUE_SUSPECT": "cash",
    "BURN_MULTIPLE_SUSPECT": "cash",
    "ARPU_SUSPECT": "ue",
    "ARPU_INCONSISTENT": "ue",
    "GROWTH_RATE_SUSPECT": "revenue",
    "GROWTH_RATE_ZERO_SUSPECT": "revenue",
    "EXPENSE_COVERAGE_SUSPECT": "team",
    "CASH_ZERO_SUSPECT": "cash",
    "ARR_MRR_MISMATCH": "revenue",
    "MISSING_CASH_BALANCE": "cash",
    "MISSING_MRR": "revenue",
    "MISSING_BURN": "cash",
    "MISSING_RETENTION": "revenue",
    "MISSING_GROSS_MARGIN": "ue",
    "CUSTOMERS_MISSING": "revenue",
    "TYPE_ERROR": "company",
    "BURN_SIGN_ERROR": "cash",
    "DERIVED_METRIC_REDUNDANT": "ue",
    "TIMESERIES_MRR_MISMATCH": "revenue",
    "TIMESERIES_ARR_MISMATCH": "revenue",
}


# ---------------------------------------------------------------------------
# HTTP Server
# ---------------------------------------------------------------------------


def _kill_port(port: int) -> None:
    """Try to kill whatever is listening on the given port."""
    try:
        result = subprocess.run(
            ["lsof", "-ti", f":{port}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        for pid_str in result.stdout.strip().split():
            with contextlib.suppress(ValueError, OSError):
                os.kill(int(pid_str), signal.SIGTERM)
        if result.stdout.strip():
            import time

            time.sleep(0.5)
    except Exception:
        pass


class _Handler(BaseHTTPRequestHandler):
    """Request handler for the review viewer server."""

    workspace: str = ""
    inputs_path: str = ""

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        """Suppress request logging."""

    def _send_json(self, code: int, data: Any) -> None:
        """Send a JSON response."""
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/":
            # Re-read inputs.json on each request for freshness
            try:
                with open(self.inputs_path) as f:
                    inputs = json.load(f)
            except Exception:
                inputs = {}
            html = _build_html(inputs)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html.encode())
        elif self.path == "/api/feedback":
            fb_path = os.path.join(self.workspace, "corrections.json")
            data: dict[str, Any] = {}
            if os.path.exists(fb_path):
                with open(fb_path) as f:
                    data = json.load(f)
            self._send_json(200, data)
        else:
            self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/api/feedback":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length) if length else b"{}"
            try:
                data = json.loads(body)
                fb_path = os.path.join(self.workspace, "corrections.json")
                with open(fb_path, "w") as f:
                    json.dump(data, f, indent=2)
                self._send_json(200, {"ok": True})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
        elif self.path == "/api/check":
            self._handle_check()
        else:
            self.send_error(404)

    def _handle_check(self) -> None:
        """POST /api/check — validate state and return sanity metrics."""
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}

        # Accept both {state, ils_fields} wrapper and bare state
        if "state" in body:
            raw_state = body["state"]
            ils_fields = body.get("ils_fields", {})
        else:
            raw_state = body
            ils_fields = {}

        state = copy.deepcopy(raw_state)

        # Step 1-3: Coerce, normalize, canonicalize
        coercion_errors = _coerce_state(state)
        _normalize_to_usd(state, ils_fields)
        _canonicalize_time_series(state)

        all_errors: list[dict[str, Any]] = list(coercion_errors)

        # Short-circuit if coercion errors
        if coercion_errors:
            self._send_json(
                200,
                {
                    "sanity": {},
                    "errors": all_errors,
                    "warnings": [],
                },
            )
            return

        # Step 4: Run validate_inputs pipeline
        warnings: list[dict[str, Any]] = []
        try:
            if _scripts_dir not in sys.path:
                sys.path.insert(0, _scripts_dir)
            import validate_inputs  # type: ignore[import-not-found]

            validation = validate_inputs.validate(state)
            all_errors.extend(validation.get("errors", []))
            warnings = validation.get("warnings", [])
        except Exception:
            pass

        # Step 5: Compute sanity metrics
        sanity: dict[str, Any] = {}

        try:
            if _scripts_dir not in sys.path:
                sys.path.insert(0, _scripts_dir)
            import unit_economics  # type: ignore[import-not-found]

            ue_result = unit_economics._compute_metrics(state)
            for m in ue_result.get("metrics", []):
                if m.get("id") == "burn_multiple" and m.get("value") is not None:
                    sanity["burn_multiple"] = m["value"]
        except Exception:
            pass

        try:
            if _scripts_dir not in sys.path:
                sys.path.insert(0, _scripts_dir)
            import runway  # type: ignore[import-not-found]

            rw_result = runway._compute_runway(state)
            if not rw_result.get("insufficient_data"):
                for s in rw_result.get("scenarios", []):
                    if s.get("name") == "base" and s.get("runway_months") is not None:
                        sanity["runway_months"] = s["runway_months"]
                        break
        except Exception:
            pass

        # ARPU check
        mrr = _deep_get_by_path(state, "revenue.mrr.value")
        customers = _deep_get_by_path(state, "revenue.customers")
        if isinstance(mrr, (int, float)) and isinstance(customers, (int, float)) and customers > 0:
            sanity["arpu_computed"] = round(mrr / customers, 2)
            arpu_input = _deep_get_by_path(state, "unit_economics.ltv.inputs.arpu_monthly")
            if arpu_input is not None:
                sanity["arpu_input"] = arpu_input

        # Expense coverage
        burn = _deep_get_by_path(state, "cash.monthly_net_burn")
        if isinstance(burn, (int, float)) and burn > 0:
            total_extracted = 0.0
            headcount = _deep_get_by_path(state, "expenses.headcount")
            if isinstance(headcount, list):
                for h in headcount:
                    if not isinstance(h, dict):
                        continue
                    sal = h.get("salary_annual")
                    cnt = h.get("count", 1)
                    if isinstance(sal, (int, float)) and isinstance(cnt, (int, float)):
                        monthly = sal / 12 * cnt
                        total_extracted += monthly
                        burden_pct = h.get("burden_pct")
                        if isinstance(burden_pct, (int, float)) and burden_pct > 0:
                            total_extracted += monthly * burden_pct

            opex_entries = _deep_get_by_path(state, "expenses.opex_monthly")
            if isinstance(opex_entries, list):
                for e in opex_entries:
                    if isinstance(e, dict) and isinstance(e.get("amount"), (int, float)):
                        total_extracted += e["amount"]

            cogs_data = _deep_get_by_path(state, "expenses.cogs")
            if isinstance(cogs_data, dict):
                for v in cogs_data.values():
                    if isinstance(v, (int, float)):
                        total_extracted += v

            rev = mrr if isinstance(mrr, (int, float)) else 0
            expected = burn + rev
            if expected > 0 and total_extracted > 0:
                sanity["expense_coverage"] = round(total_extracted / expected, 2)

        # Annotate warnings with contributing_fields and tab
        for w in warnings:
            code = w.get("code", "")
            if code in _CONTRIBUTING_FIELDS:
                w["contributing_fields"] = _CONTRIBUTING_FIELDS[code]
            if code in _WARNING_TAB:
                w["tab"] = _WARNING_TAB[code]

        self._send_json(
            200,
            {
                "sanity": sanity,
                "errors": all_errors,
                "warnings": warnings,
            },
        )


def _serve(inputs_path: str, workspace: str, port: int = 3117) -> None:
    """Start the HTTP server and open the browser."""
    if port != 0:
        _kill_port(port)

    _Handler.workspace = workspace
    _Handler.inputs_path = inputs_path

    try:
        server = HTTPServer(("127.0.0.1", port), _Handler)
    except OSError:
        server = HTTPServer(("127.0.0.1", 0), _Handler)

    actual_port = server.server_address[1]
    url = f"http://127.0.0.1:{actual_port}"
    print(json.dumps({"mode": "server", "url": url, "port": actual_port, "workspace": workspace}))
    sys.stdout.flush()

    if port != 0:
        with contextlib.suppress(Exception):
            webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Dual-mode review viewer for FMR inputs")
    parser.add_argument("inputs", help="Path to inputs.json")
    parser.add_argument(
        "--static",
        metavar="FILE",
        help="Write self-contained static HTML to FILE",
    )
    parser.add_argument(
        "--workspace",
        metavar="DIR",
        help="Workspace directory for server mode",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=3117,
        help="Server port (default: 3117)",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="No-op; accepted for CLI compatibility",
    )
    parser.add_argument(
        "-o",
        metavar="FILE",
        help="Alias for --static (write HTML to FILE)",
    )
    args = parser.parse_args()

    # Read inputs
    try:
        with open(args.inputs) as f:
            inputs = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"Error reading {args.inputs}: {e}", file=sys.stderr)
        sys.exit(1)

    output = args.static or args.o
    if output:
        _write_static(inputs, output)
    elif args.workspace:
        os.makedirs(args.workspace, exist_ok=True)
        _serve(os.path.abspath(args.inputs), args.workspace, port=args.port)
    else:
        print(
            "Error: provide --static <file> for static mode or --workspace <dir> for server mode",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
