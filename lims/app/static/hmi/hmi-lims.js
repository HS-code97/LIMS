/* hmi-lims.js — LIMS 기록 모드 (설계서 5.2·6.2~6.4·6.9절).
 * HMI의 PLC 전송 대신 [저장]: 프리셋 1클릭 → 조정 → 블랭크(각인번호) N장을 도금 단계로. 프리셋·복제·시리즈·조건부 미리보기.
 * 도금은 번호를 새로 만들지 않습니다: 각인번호 그대로, 전체번호에 조건 꼬리만 붙음 (시편번호 체계 3.1절). */
(function () {
  "use strict";
  const C = window.LIMS_HMI, H = HMICore.init(C.dict), $ = (id) => document.getElementById(id);
  const esc = LIMS.esc;

  const st = {
    sp: null, base: null, presetId: null, presetName: "", coatingSystem: null, bathCode: null,
    sel: "rth", series: [], srcLabel: "",
  };

  /* ── 프리셋·복제 ── */
  function usePreset(p) {
    st.base = H.applyPreset(p.overrides);
    st.sp = H.clone(st.base);
    st.presetId = p.id; st.presetName = p.name; st.coatingSystem = p.coating_system; st.bathCode = p.bath_code;
    st.srcLabel = `${p.scope === "PUBLIC" ? "공용" : p.scope === "TEAM" ? "팀" : "개인"} 프리셋 ${p.name} (계열 ${p.coating_system}${p.bath_code})`;
    drawPresets();
    renderAll();
  }

  function useRun(r) {
    st.base = H.merge(H.defaults(), r.recipe);
    st.sp = H.clone(st.base);
    st.presetId = r.preset_id; st.coatingSystem = r.coating_system;
    const p = C.presets.find((x) => x.id === r.preset_id);
    st.bathCode = p ? p.bath_code : null; st.presetName = p ? p.name : "";
    st.srcLabel = `${r.run_no} 복제 (${r.code})`;
    if (r.coating_weight_target) $("cw").value = r.coating_weight_target;
    if (r.project_code) $("project").value = r.project_code;
    if (r.material_id) $("material").value = r.material_id;
    drawPresets();
    renderAll();
  }

  function drawPresets() {
    const pub = C.presets.filter((p) => p.scope === "PUBLIC");
    $("pub-presets").innerHTML = pub.map((p) =>
      `<button aria-pressed="${p.id === st.presetId}" data-id="${p.id}" title="계열 ${p.coating_system}${p.bath_code}">${esc(p.name)}</button>`).join("");
    $("pub-presets").querySelectorAll("button").forEach((b) => (b.onclick = () => usePreset(C.presets.find((p) => p.id === +b.dataset.id))));
    const mine = C.presets.filter((p) => p.scope !== "PUBLIC");
    $("my-presets").innerHTML = `<option value="">내·팀 프리셋 ▼ (${mine.length})</option>` +
      mine.map((p) => `<option value="${p.id}" ${p.id === st.presetId ? "selected" : ""}>${p.scope === "TEAM" ? "[팀] " : ""}${esc(p.name)} · ${p.coating_system}${p.bath_code}</option>`).join("");
    $("recipe-src").textContent = st.srcLabel ? "레시피: " + st.srcLabel : "";
  }

  /* ── 변경 표시: 프리셋(또는 복제 원본) 대비 ── */
  function changedKeys() {
    const out = [];
    H.S.forEach((s) => {
      const a = st.sp[s.id] || {}, b = st.base[s.id] || {};
      if (s.opt && a.on !== b.on) out.push(`${s.id}.on`);
      s.p.forEach((p) => { if (a[p.k] !== b[p.k]) out.push(`${s.id}.${p.k}`); });
    });
    return out;
  }

  /* ── 입력 패널 ── */
  function drawPanel() {
    const s = H.byId[st.sel], v = st.sp[st.sel], b = st.base[st.sel] || {};
    let h = `<header><h2>설비 조건 입력</h2><span class="meta">${s.nm}</span></header><div class="body">
      <div style="display:flex;gap:8px;align-items:baseline"><b style="font-size:16px">${s.full}</b><span class="mono small muted">${s.nm}</span></div>
      <p class="small" style="color:var(--ink-2);margin:4px 0 8px">${s.desc}</p>`;
    if (s.opt) h += `<label class="small" style="display:flex;gap:6px;align-items:center"><input type="checkbox" id="on-${s.id}" ${v.on ? "checked" : ""}> 이 구간 사용</label>`;
    s.p.forEach((p) => {
      const id = `p-${s.id}-${p.k}`, dis = s.opt && !v.on, chg = v[p.k] !== b[p.k];
      const bad = p.type !== "sel" && p.min !== undefined && !(v[p.k] >= p.min && v[p.k] <= p.max);
      h += `<div class="prow ${chg ? "changed" : ""}"><label for="${id}">${chg ? '<span class="ed">✎ ' + p.l + " (변경됨)</span>" : p.l}</label>`;
      if (p.type === "sel") h += `<select class="in ${chg ? "chg" : ""}" id="${id}" ${dis ? "disabled" : ""}>${p.opts.map((o) => `<option ${o === v[p.k] ? "selected" : ""}>${o}</option>`).join("")}</select>`;
      else h += `<input class="in ${chg ? "chg" : ""} ${bad ? "bad" : ""}" id="${id}" type="number" step="${p.st || 1}" value="${H.fmt(v[p.k], p)}" ${dis ? "disabled" : ""}>`;
      h += `<span class="u">${p.u || ""}</span>`;
      if (p.type !== "sel") h += `<span class="rg">허용 ${p.min} ~ ${p.max} ${p.u}${chg ? ` · 프리셋 <b>${H.fmt(b[p.k], p)}</b>` : ""}${p.actual && p.actual.quick ? " · 실측 입력 항목" : ""}</span>`;
      h += "</div>";
    });
    h += "</div>";
    $("panel").innerHTML = h;
    s.p.forEach((p) => {
      const inp = $(`p-${s.id}-${p.k}`);
      inp.onchange = () => { st.sp[s.id][p.k] = p.type === "sel" ? inp.value : parseFloat(inp.value); renderAll(true); };
    });
    if (s.opt) $(`on-${s.id}`).onchange = (e) => { st.sp[s.id].on = e.target.checked; renderAll(); };
  }

  function drawAlarms() {
    const c = H.checks(st.sp, { coatingSystem: st.coatingSystem });
    $("alarms").innerHTML = c.length ? c.map((a) => `<li><span class="ic ${a.lv}">${a.lv === "err" ? "범위" : "주의"}</span><span>${esc(a.msg)} <a data-id="${a.id}">이동</a></span></li>`).join("")
      : `<li><span class="ic ok">OK</span><span>점검 항목 이상 없음</span></li>`;
    $("alarms").querySelectorAll("a").forEach((a) => (a.onclick = () => select(a.dataset.id)));
    const ne = c.filter((a) => a.lv === "err").length;
    $("acount").textContent = `범위 ${ne} · 주의 ${c.length - ne}`;
  }

  function select(id) { st.sel = id; renderAll(); }

  /* 구간 요약 칩 줄 (Stitch 시안) */
  function drawStrip(zones) {
    $("zstrip").innerHTML = H.S.map((s) => {
      const off = s.opt && !st.sp[s.id].on;
      return `<button type="button" data-id="${s.id}" class="${s.id === st.sel ? "sel" : ""} ${off ? "off" : ""} ${zones.has(s.id) ? "chg" : ""}" title="${s.full}">` +
        `<b>${s.nm}</b><span>${esc(String(H.mainVal(st.sp, s.id)).replace("SET ", ""))}</span></button>`;
    }).join("");
    $("zstrip").querySelectorAll("button").forEach((b) => (b.onclick = () => select(b.dataset.id)));
    const c = H.checks(st.sp, { coatingSystem: st.coatingSystem });
    $("line-status").textContent = c.some((a) => a.lv === "err") ? "STATUS: 범위 밖" : c.length ? `STATUS: 주의 ${c.length}` : "STATUS: NORMAL";
  }

  function renderAll(keepFocus) {
    const f = document.activeElement && document.activeElement.id;
    const ch = changedKeys();
    const zones = new Set(ch.map((k) => k.split(".")[0]));
    drawStrip(zones);
    H.drawMimic($("mimic"), st.sp, { sel: st.sel, changed: zones, onSelect: select, ctx: { coatingSystem: st.coatingSystem } });
    const c = H.drawChart($("chart"), st.sp, { sel: st.sel, onSelect: select });
    $("totalt").textContent = `총 ${Math.round(c.total)} s`;
    drawPanel();
    drawAlarms();
    if (keepFocus && f) { const e = $(f); if (e) e.focus(); }
    preview();
  }

  /* ── 번호·조건부 미리보기 ── */
  let pvTimer = null;
  function payloadBase() {
    const cw = parseFloat($("cw").value);
    const recipe = H.clone(st.sp);
    recipe.out = Object.assign({}, recipe.out || {}, { cw });
    return { recipe, coating_weight_target: cw, preset_id: st.presetId, coating_system: st.coatingSystem };
  }

  /* 'QV3-101~105, QV3-201' → ['QV3-101', …] (범위는 마지막 숫자 자리) */
  function marks() {
    const out = [];
    $("marks").value.toUpperCase().split(/[,\s;]+/).filter(Boolean).forEach((part) => {
      const m = part.match(/^(.*-)(\d+)~(\d+)$/);
      if (!m) return out.push(part);
      const w = m[2].length;
      for (let i = parseInt(m[2], 10); i <= parseInt(m[3], 10) && out.length < 200; i++) out.push(m[1] + String(i).padStart(w, "0"));
    });
    return out;
  }

  function onMarks() { $("count").value = marks().length; showConflicts([]); preview(); }

  async function loadBlanks() {
    const opt = $("material").selectedOptions[0], coil = opt ? opt.dataset.coil : "";
    try {
      const rows = await LIMS.api("GET", `/api/plating/candidates?coil=${encodeURIComponent(coil || "")}`);
      if (!rows.length) return LIMS.toast(`도금 안 한 블랭크가 없습니다${coil ? " (코일 " + coil + ")" : ""}`, "err");
      $("marks").value = rows.map((r) => r.short_id).join(", ");
      onMarks();
      LIMS.toast(`${rows.length}장 불러옴 — 쓸 것만 남기세요`, "ok");
    } catch (e) { LIMS.fail(e); }
  }

  function panelOverrides() {
    const n = marks().length;
    const out = Array.from({ length: n }, () => ({}));
    st.series.forEach((s) => s.values.forEach((v, i) => { if (i < n) out[i][s.key] = v; }));
    return out;
  }

  function preview() {
    clearTimeout(pvTimer);
    pvTimer = setTimeout(async () => {
      if (!st.sp) return;
      try {
        const r = await LIMS.api("POST", "/api/process-runs/preview-code", Object.assign(payloadBase(), { panel_overrides: st.series.length ? panelOverrides() : [] }));
        $("code").textContent = r.code;
        const ms = marks(), proj = $("project").value;
        const full = (m) => { const [coil, ...rest] = m.split("-"); return `${coil}-${proj}-C-${rest.join("-")}-${r.code}`; };
        $("range").textContent = ms.length ? `→ ${full(ms[0])}${ms.length > 1 ? " ~ " + ms[ms.length - 1] + ` (${ms.length}장)` : ""}` : "→ 도금할 각인번호를 넣으세요";
        if (st.series.length) {
          const codes = [...new Set(r.panel_codes)];
          $("series-summary").innerHTML = `<span class="mk-intent">◆</span> 시리즈 ${st.series.map((x) => `${esc(x.key)} = [${x.values.join(", ")}]`).join(" × ")} · 원판별 조건부 ${codes.join(", ")}`;
        } else $("series-summary").textContent = "";
      } catch (e) { /* 미리보기 실패는 조용히 */ }
    }, 220);
  }

  function showConflicts(list) {
    const el = $("conflicts");
    el.classList.toggle("hidden", !list.length);
    el.textContent = list.length ? `도금할 수 없는 시편: ${list.join(" / ")}` : "";
  }

  /* ── 시리즈 설정 ── */
  function labelOf(key) {
    const [sid, k] = key.split("."), s = H.byId[sid], p = s && s.p.find((x) => x.k === k);
    return p ? `${p.l}${p.u ? " (" + p.u + ")" : ""}` : key;
  }
  const numericKeys = [];
  C.dict.sections.forEach((s) => s.p.forEach((p) => { if (p.type !== "sel" && p.min !== undefined) numericKeys.push({ key: `${s.id}.${p.k}`, label: `${s.nm} ${p.l} (${p.u})` }); }));

  function openSeries() {
    const n = marks().length || 1;
    const rows = [0, 1].map((i) => {
      const s = st.series[i] || { key: i === 0 ? "ak.P" : "", values: [] };
      return `<label class="f">키 ${i + 1}<select class="in" id="sk${i}"><option value="">(없음)</option>${numericKeys.map((k) => `<option value="${k.key}" ${k.key === s.key ? "selected" : ""}>${k.label}</option>`).join("")}</select></label>
        <label class="f">값 ${n}개 (쉼표)<input class="in mono" id="sv${i}" value="${s.values.join(", ")}" placeholder="${i === 0 ? "20, 30, 40, 50, 60" : ""}"></label>`;
    }).join("");
    $("series-rows").innerHTML = rows;
    ["sk0", "sv0", "sk1", "sv1"].forEach((id) => ($(id).oninput = seriesPreview));
    seriesPreview();
    $("dlg-series").classList.remove("hidden");
  }

  function readSeries() {
    const n = marks().length || 1, out = [], errs = [];
    [0, 1].forEach((i) => {
      const key = $(`sk${i}`).value, raw = $(`sv${i}`).value.trim();
      if (!key) return;
      const vals = raw.split(/[,\s]+/).filter(Boolean).map(Number);
      if (vals.some(isNaN)) errs.push(`키 ${i + 1}: 숫자가 아닌 값`);
      else if (vals.length !== n) errs.push(`키 ${i + 1}: 값 ${vals.length}개 ≠ 원판 ${n}매`);
      out.push({ key, values: vals });
    });
    return { out, errs };
  }

  function seriesPreview() {
    const { out, errs } = readSeries(), ms = marks();
    let h = `<tr><th>시편</th>${out.map((x) => `<th class="n">${esc(x.key)}</th>`).join("")}</tr>`;
    ms.forEach((m, i) => { h += `<tr><td class="mono">${esc(m)}</td>${out.map((x) => `<td class="n">${x.values[i] ?? ""}</td>`).join("")}</tr>`; });
    if (errs.length) h += `<tr><td colspan="3" class="mk-dev">${errs.join(" / ")}</td></tr>`;
    $("series-preview").innerHTML = h;
  }

  /* ── 저장 ── */
  async function save(confirmRange) {
    const btn = $("btn-save");
    if (!st.sp) return LIMS.toast("프리셋을 고르거나 지난 공정런을 복제하세요", "err");
    if (!marks().length) return LIMS.toast("도금할 시편의 각인번호를 넣으세요 (예: QV3-101~105)", "err");
    btn.disabled = true;
    const body = Object.assign(payloadBase(), {
      source: "manual", dict_version: C.dict.dict_version, project_code: $("project").value,
      material_id: $("material").value ? parseInt($("material").value, 10) : null, run_date: $("run_date").value,
      specimens: marks(),
      series: st.series.length ? st.series : null, changed_from_preset: changedKeys(),
      warnings: H.checks(st.sp, { coatingSystem: st.coatingSystem }).map((a) => a.msg), note: $("note").value,
      confirm_out_of_range: !!confirmRange,
    });
    try {
      const r = await LIMS.api("POST", "/api/process-runs", body);
      done(r);
    } catch (e) {
      if (e.status === 422 && e.data && /도금할 수 없는/.test(e.data.detail || "")) showConflicts(e.data.items || []);
      if (e.status === 422 && e.data && e.data.items && e.data.items.length && /허용 범위/.test(e.data.detail || "")) {
        if (confirm(`허용 범위 밖 값이 있습니다:\n\n${e.data.items.join("\n")}\n\n그대로 저장할까요?`)) { btn.disabled = false; return save(true); }
      } else LIMS.fail(e);
    } finally { btn.disabled = false; }
  }

  function done(r) {
    $("done-title").textContent = `${r.run_no} 저장 완료 — ${r.panels.length}장 도금`;
    $("done-body").innerHTML = `<table class="t"><tr><th>각인번호 (그대로)</th><th>전체번호</th><th>원판별 목표 변경</th></tr>` +
      r.panels.map((p) => `<tr><td class="mono"><a href="/specimens/${p.short_id}">${p.short_id}</a></td><td class="mono"><b>${p.display_id}</b></td>
        <td class="small">${p.target_overrides ? '<span class="mk-intent">◆</span> ' + Object.entries(p.target_overrides).map(([k, v]) => `${esc(labelOf(k))} <b class="mono">${v}</b>`).join(", ") : ""}</td></tr>`).join("") + "</table>" +
      (r.warnings && r.warnings.length ? `<div class="flash warn" style="margin-top:10px">${r.warnings.map(esc).join("<br>")}</div>` : "");
    $("done-csv").href = r.engrave_csv;
    $("done-label").href = r.label_pdf;
    $("done-actuals").href = `/process-runs/${r.run_no}?tab=actuals`;
    $("done-open").href = `/process-runs/${r.run_no}`;
    $("dlg-done").classList.remove("hidden");
  }

  async function saveMyPreset() {
    if (!st.sp) return;
    const name = prompt("프리셋 이름 (예: M2 저이슬점 표준)", st.presetName ? st.presetName + " 변형" : "");
    if (!name) return;
    const team = confirm("팀 프리셋으로 공유할까요?\n[확인] 팀 · [취소] 개인");
    try {
      const p = await LIMS.api("POST", "/api/presets", { name, scope: team ? "TEAM" : "PERSONAL", coating_system: st.coatingSystem || "X",
        bath_code: st.bathCode || "0", recipe: st.sp });
      C.presets.push(p);
      st.presetId = p.id; st.presetName = p.name; st.base = H.applyPreset(p.overrides);
      st.srcLabel = `${team ? "팀" : "개인"} 프리셋 ${p.name}`;
      drawPresets(); renderAll();
      LIMS.toast(`프리셋 '${p.name}' 저장`, "ok");
    } catch (e) { LIMS.fail(e); }
  }

  /* ── 이벤트 연결 ── */
  $("my-presets").onchange = (e) => { const p = C.presets.find((x) => x.id === +e.target.value); if (p) usePreset(p); };
  $("clone-runs").onchange = (e) => { const r = C.recent[+e.target.value]; if (r) useRun(r); e.target.value = ""; };
  $("project").onchange = preview;
  $("marks").oninput = onMarks;
  $("btn-load").onclick = loadBlanks;
  $("cw").oninput = preview;
  $("btn-series").onclick = openSeries;
  $("series-cancel").onclick = () => $("dlg-series").classList.add("hidden");
  $("series-clear").onclick = () => { st.series = []; $("dlg-series").classList.add("hidden"); preview(); };
  $("series-ok").onclick = () => {
    const { out, errs } = readSeries();
    if (errs.length) return LIMS.toast(errs.join(" / "), "err");
    st.series = out; $("dlg-series").classList.add("hidden"); preview();
  };
  $("btn-save").onclick = () => save(false);
  $("btn-mypreset").onclick = saveMyPreset;
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") ["dlg-series"].forEach((id) => $(id).classList.add("hidden")); });

  /* 시작: 복제 요청 → 그 레시피, 아니면 첫 공용 프리셋 */
  if (C.clone) useRun(C.clone);
  else {
    const first = C.presets.find((p) => p.scope === "PUBLIC" && p.name === "M2") || C.presets[0];
    if (first) usePreset(first);
  }
  const q = new URLSearchParams(location.search).get("specimens");   // 시편 상세 [도금] → 각인번호 채움
  if (q) { $("marks").value = q; onMarks(); }
})();
