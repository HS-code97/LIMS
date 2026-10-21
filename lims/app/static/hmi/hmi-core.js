/* hmi-core.js — CGL 모사장치 HMI에서 분리한 공통 모듈 (설계서 6.1절).
 * 구간·파라미터 사전(S)은 서버의 /api/param-dictionary(단일 원본)에서 받고,
 * 열사이클 계산 cycle(), 점검 규칙 checks(), 미믹 drawMimic(), 열사이클 차트 drawChart()를
 * HMI와 LIMS가 같은 파일로 씁니다. PLC 전송·인터락·실행 상태는 HMI 전용이라 여기 없습니다.
 */
(function (global) {
  "use strict";
  let DICT = null, S = [], byId = {};

  function init(dict) {
    DICT = dict;
    S = dict.sections.filter((s) => s.setpoint !== false);   // out(출력 특성)은 미믹에 그리지 않음
    byId = Object.fromEntries(dict.sections.map((s) => [s.id, s]));
    return api;
  }

  function clone(o) { return JSON.parse(JSON.stringify(o)); }

  function defaults() {
    const o = {};
    DICT.sections.forEach((s) => {
      o[s.id] = {};
      if (s.opt) o[s.id].on = true;
      s.p.forEach((p) => { if (p.v !== undefined) o[s.id][p.k] = p.v; });
    });
    return o;
  }

  /** 프리셋 = 기본값과 다른 값만. 기존 HMI applyPreset과 같이 NOF는 기본 OFF. */
  function applyPreset(overrides) {
    const sp = defaults();
    for (const id in overrides || {}) Object.assign(sp[id] = sp[id] || {}, overrides[id]);
    if (sp.nof && !(overrides && overrides.nof && "on" in overrides.nof)) sp.nof.on = false;
    return sp;
  }

  function merge(base, ov) {
    const sp = clone(base);
    for (const k in ov || {}) {
      if (typeof ov[k] === "object" && ov[k] !== null) Object.assign(sp[k] = sp[k] || {}, ov[k]);
      else if (k.includes(".")) { const [a, b] = k.split("."); (sp[a] = sp[a] || {})[b] = ov[k]; }
    }
    return sp;
  }

  const isOn = (sp, id) => (byId[id] && byId[id].opt ? !!sp[id].on : true);

  /* ── 열사이클 계산 (원본 cycle()) ── */
  function cycle(sp) {
    const pts = [[0, 25]], bands = [];
    let t = 0, T = 25;
    const go = (id, toT, rate, hold) => {
      const t0 = t;
      if (toT != null && rate) { t += Math.abs(toT - T) / rate; T = toT; pts.push([t, T]); }
      if (hold) { t += hold; pts.push([t, T]); }
      bands.push({ id, t0, t1: t });
    };
    if (isOn(sp, "nof")) go("nof", sp.nof.T, sp.rth.rate, sp.nof.t);
    go("rth", sp.rth.T, sp.rth.rate, 0);
    go("rts", null, 0, sp.rts.t);
    go("sjc", sp.sjc.T, sp.sjc.rate, 0);
    go("rjc", sp.rjc.T, sp.rjc.rate, 0);
    go("oa", null, 0, sp.oa.t);
    go("snout", sp.snout.SET, 10, 1);
    go("pot", sp.pot.T, 20, sp.pot.t);
    go("ak", sp.pot.T - 8, 8, 0);
    if (isOn(sp, "ga")) go("ga", sp.ga.T, sp.ga.rate, sp.ga.t);
    go("apc", sp.apc.T, sp.apc.rate, 0);
    go("wq", sp.wq.T, 100, 1);
    return { pts, bands, total: t };
  }

  function tempAt(c, tt) {
    const p = c.pts;
    for (let i = 1; i < p.length; i++) {
      if (tt <= p[i][0]) { const a = p[i - 1], b = p[i]; const f = b[0] === a[0] ? 1 : (tt - a[0]) / (b[0] - a[0]); return a[1] + (b[1] - a[1]) * f; }
    }
    return p[p.length - 1][1];
  }

  /* ── 점검 규칙 (원본 checks()) — LIMS에서는 경고만, 저장을 막지 않음 ── */
  function checks(sp, ctx) {
    ctx = ctx || {};
    const out = [];
    S.forEach((s) => s.p.forEach((p) => {
      if (p.type === "sel" || (s.opt && !sp[s.id].on) || p.min === undefined) return;
      const v = sp[s.id][p.k];
      if (!(v >= p.min && v <= p.max)) out.push({ lv: "err", id: s.id, msg: `${s.nm} ${p.l} ${v}${p.u} — 허용 범위 ${p.min}~${p.max}${p.u} 밖` });
    }));
    if (sp.sjc.T > sp.rth.T) out.push({ lv: "err", id: "sjc", msg: "서냉 종료 판온이 최고 판온보다 높습니다." });
    if (sp.rjc.T > sp.sjc.T) out.push({ lv: "err", id: "rjc", msg: "급냉 종료 판온이 서냉 종료 판온보다 높습니다." });
    const d = sp.snout.SET - sp.pot.T;
    if (d < 0 || d > 25) out.push({ lv: "warn", id: "snout", msg: `SET − 욕온 = ${d > 0 ? "+" : ""}${d} °C. 권장 0~+25 °C` });
    if (isOn(sp, "ga") && sp.pot.Al > 0.135) out.push({ lv: "warn", id: "pot", msg: `GA 운전인데 욕 Al ${sp.pot.Al}% — GA는 통상 0.11~0.13%` });
    if (!isOn(sp, "ga") && ctx.coatingSystem === "A") out.push({ lv: "warn", id: "ga", msg: "GA 프리셋인데 합금화로가 OFF입니다." });
    if (sp.rth.DP > -30) out.push({ lv: "warn", id: "rth", msg: `이슬점 ${sp.rth.DP} °C — 통상 −30 °C 이하로 관리` });
    if (sp.apc.T > sp.pot.T) out.push({ lv: "err", id: "apc", msg: "탑롤 판온이 욕온보다 높습니다." });
    return out;
  }

  function fmt(v, p) { if (p && p.st && p.st < 1 && typeof v === "number") return v.toFixed(p.st < 0.1 ? 2 : 1); return v; }

  function mainVal(sp, id) {
    const s = sp[id];
    if (byId[id].opt && !s.on) return "OFF";
    return { nof: `${s.T} °C`, rth: `${s.T} °C`, rts: `${s.t} s`, sjc: `${s.T} °C`, rjc: `${s.T} °C`, oa: `${s.t} s`,
      snout: `SET ${s.SET}`, pot: `${s.T} °C`, ak: `${s.P} kPa`, ga: `${s.T} °C`, apc: `${s.rate} °C/s`, wq: `${s.T} °C` }[id];
  }

  /* ── 미믹 (원본 drawMimic()) ──
   * opts: {sel, changed:Set(구간 id), onSelect(id), run:{cur,pos,pvNow}} */
  const ZX = { nof: [60, 150], rth: [150, 290], rts: [290, 390], sjc: [390, 460], rjc: [460, 545], oa: [545, 640] };
  const POS = { nof: [105, 180], rth: [220, 180], rts: [340, 180], sjc: [425, 180], rjc: [502, 180], oa: [592, 180], snout: [754, 260],
    pot: [812, 388], ak: [824, 318], ga: [824, 244], apc: [824, 128], wq: [1022, 380] };

  function drawMimic(svg, sp, opts) {
    opts = opts || {};
    const sel = opts.sel, changed = opts.changed || new Set(), run = opts.run || null;
    const c = checks(sp, opts.ctx), flag = {};
    c.forEach((a) => { if (!flag[a.id] || a.lv === "err") flag[a.id] = a.lv; });
    const zc = (id) => [id === sel ? "sel" : "", byId[id].opt && !sp[id].on ? "off" : "", run && run.cur === id ? "live" : ""].join(" ");
    const tag = (x, y, id, w = 82) => {
      const z = byId[id], ch = changed.has(id), pv = run && run.cur === id ? `${Math.round(run.pvNow)} °C` : "";
      return `<g class="tag ${ch ? "chg" : ""}" transform="translate(${x},${y})"><rect width="${w}" height="${pv ? 44 : 32}" rx="3"/>` +
        `<text class="nm" x="6" y="13">${z.nm}</text>${ch ? `<circle class="dot" cx="${w - 8}" cy="9" r="3.5"/>` : ""}` +
        `<text class="vl" x="6" y="26">${mainVal(sp, id)}</text>${pv ? `<text class="pv" x="6" y="39">PV ${pv}</text>` : ""}</g>`;
    };
    const badge = (lv, x, y) => {
      if (!lv) return "";
      const col = lv === "err" ? "var(--alarm)" : "var(--warn)";
      return `<g transform="translate(${x},${y})"><path d="M0,-8 L8,6 L-8,6 Z" fill="${col}"/><text class="badge" x="0" y="4" text-anchor="middle" fill="#fff">!</text></g>`;
    };
    let h = `<text x="60" y="24" class="dim">소둔로 (수직형) · 분위기 H₂ ${sp.rth.H2}% / 이슬점 ${sp.rth.DP} °C</text>`;
    for (const id in ZX) {
      const [x0, x1] = ZX[id];
      h += `<g class="zone ${zc(id)}" data-id="${id}" tabindex="0" role="button" aria-label="${byId[id].full}">
        <rect class="eqf" x="${x0}" y="36" width="${x1 - x0}" height="290"/><rect class="flame" x="${x0 + 4}" y="300" width="${x1 - x0 - 8}" height="4"/>
        <rect class="hit" x="${x0}" y="36" width="${x1 - x0}" height="370"/>${tag(x0 + 4, 340, id, Math.min(82, x1 - x0 - 8))}${badge(flag[id], x1 - 12, 48)}</g>`;
    }
    let d = "M20,308 L75,308";
    const xs = [];
    for (let x = 75; x <= 610; x += 35) xs.push(x);
    xs.forEach((x, i) => { const up = i % 2 === 0; d += ` L${x},${up ? 62 : 308}`; if (i < xs.length - 1) d += ` L${xs[i + 1]},${up ? 62 : 308}`; });
    const lastUp = (xs.length - 1) % 2 === 0, endY = lastUp ? 62 : 308;
    let rolls = "";
    xs.forEach((x, i) => { rolls += `<circle class="roll" cx="${x + 17.5}" cy="${i % 2 === 0 ? 62 : 308}" r="6"/>`; });
    h += `<g class="zone ${zc("snout")}" data-id="snout" tabindex="0" role="button" aria-label="스나우트">
      <path class="eqf" d="M700,170 L722,160 L810,360 L788,370 Z"/><rect class="hit" x="690" y="150" width="130" height="225"/>${tag(608, 190, "snout", 84)}${badge(flag.snout, 780, 170)}</g>`;
    h += `<g class="zone ${zc("pot")}" data-id="pot" tabindex="0" role="button" aria-label="도금 포트">
      <path class="eqf" d="M735,346 L735,418 L885,418 L885,346"/><rect class="bath" x="737" y="352" width="146" height="64"/>
      <rect class="flame" x="737" y="414" width="146" height="3"/><rect class="hit" x="730" y="340" width="160" height="82"/>${tag(892, 360, "pot", 84)}${badge(flag.pot, 872, 356)}</g>`;
    h += rolls;
    h += `<circle class="roll" cx="660" cy="300" r="9"/><circle class="roll" cx="690" cy="300" r="9"/><text class="dim" x="648" y="330">핫브라이들</text>`;
    h += `<circle class="roll" cx="705" cy="150" r="10"/><text class="dim" x="676" y="134">턴다운롤</text>`;
    h += `<circle class="roll" cx="812" cy="400" r="12"/><circle class="roll" cx="832" cy="368" r="5"/>`;
    d += ` L660,${endY} L660,300 L690,300 L705,150 L804,408 A 12 12 0 0 0 824 400 L824,40 L1000,40 L1022,62 L1022,372 L1185,372`;
    h += `<path class="strip" d="${d}"/>`;
    h += `<g class="zone ${zc("ak")}" data-id="ak" tabindex="0" role="button" aria-label="에어나이프">
      <path class="eqf" d="M780,312 L816,318 L780,324 Z"/><path class="eqf" d="M868,312 L832,318 L868,324 Z"/>
      <rect class="hit" x="772" y="300" width="104" height="34"/>${tag(892, 300, "ak", 84)}${badge(flag.ak, 872, 300)}</g>`;
    h += `<text class="dim" x="830" y="344">↕ ${sp.ak.h} mm</text>`;
    h += `<g class="zone ${zc("ga")}" data-id="ga" tabindex="0" role="button" aria-label="합금화로">
      <rect class="eqf" x="800" y="200" width="48" height="88"/><rect class="flame" x="803" y="204" width="4" height="80"/><rect class="flame" x="841" y="204" width="4" height="80"/>
      <rect class="hit" x="796" y="196" width="56" height="96"/>${tag(892, 218, "ga", 84)}${badge(flag.ga, 852, 200)}</g>`;
    h += `<g class="zone ${zc("apc")}" data-id="apc" tabindex="0" role="button" aria-label="후냉각 APC">
      <rect class="eqf" x="800" y="70" width="48" height="118"/>
      ${[0, 1, 2, 3, 4].map((i) => `<line x1="804" x2="818" y1="${84 + i * 22}" y2="${84 + i * 22}" stroke="var(--eq-stroke)"/><line x1="830" x2="844" y1="${84 + i * 22}" y2="${84 + i * 22}" stroke="var(--eq-stroke)"/>`).join("")}
      <rect class="hit" x="796" y="66" width="56" height="126"/>${tag(892, 110, "apc", 84)}${badge(flag.apc, 852, 70)}</g>`;
    h += `<circle class="roll" cx="824" cy="40" r="14"/><circle class="roll" cx="1010" cy="50" r="14"/><text class="dim" x="880" y="28">탑롤</text>`;
    h += `<g class="zone ${zc("wq")}" data-id="wq" tabindex="0" role="button" aria-label="수냉조">
      <path class="eqf" d="M985,330 L985,404 L1075,404 L1075,330"/><rect class="bath" x="987" y="352" width="86" height="50" style="opacity:.6"/>
      <rect class="hit" x="980" y="320" width="100" height="90"/>${tag(1090, 330, "wq", 84)}${badge(flag.wq, 1062, 336)}</g>`;
    h += `<circle class="roll" cx="1022" cy="372" r="8"/><text class="dim" x="1130" y="392">출측 →</text><text class="dim" x="16" y="296">입측</text>`;
    if (run && run.pos) h += `<circle class="cursor" cx="${run.pos[0]}" cy="${run.pos[1]}" r="6"/>`;
    svg.innerHTML = h;
    svg.querySelectorAll(".zone").forEach((g) => {
      g.onclick = () => opts.onSelect && opts.onSelect(g.dataset.id);
      g.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); opts.onSelect && opts.onSelect(g.dataset.id); } };
    });
  }

  /* ── 열사이클 차트 (원본 drawChart()) ── */
  function drawChart(svg, sp, opts) {
    opts = opts || {};
    const c = cycle(sp), run = opts.run || null;
    const W = 900, H = 300, L = 46, R = 12, T = 26, B = 34;
    const tmax = c.total, Tmax = Math.max(900, Math.ceil(Math.max(...c.pts.map((p) => p[1])) / 100) * 100 + 50);
    const X = (t) => L + (W - L - R) * t / tmax, Y = (v) => T + (H - T - B) * (1 - v / Tmax);
    let h = "";
    for (let v = 0; v <= Tmax; v += 200) h += `<line class="grid-l" x1="${L}" x2="${W - R}" y1="${Y(v)}" y2="${Y(v)}"/><text class="ax" x="${L - 6}" y="${Y(v) + 4}" text-anchor="end">${v}</text>`;
    const step = tmax > 400 ? 100 : tmax > 150 ? 50 : 20;
    for (let t = 0; t <= tmax; t += step) h += `<text class="ax" x="${X(t)}" y="${H - B + 16}" text-anchor="middle">${t}</text>`;
    h += `<text class="ax" x="${W - R}" y="${H - 4}" text-anchor="end">시간 (s)</text><text class="ax" x="${L}" y="14">판온 (°C)</text>`;
    c.bands.forEach((b) => {
      const w = Math.max(X(b.t1) - X(b.t0), 2);
      h += `<g class="band ${b.id === opts.sel ? "sel" : ""}" data-id="${b.id}"><rect x="${X(b.t0)}" y="${T}" width="${w}" height="${H - T - B}"/>
        ${w > 18 ? `<text x="${X(b.t0) + w / 2}" y="${T - 6}" text-anchor="middle">${byId[b.id].nm}</text>` : ""}</g>`;
    });
    h += `<polyline class="sp-line" points="${c.pts.map((p) => X(p[0]) + "," + Y(p[1])).join(" ")}"/>`;
    if (run && run.pv && run.pv.length > 1) h += `<polyline class="pv-line" points="${run.pv.map((p) => X(p[0]) + "," + Y(p[1])).join(" ")}"/>`;
    svg.innerHTML = h;
    svg.querySelectorAll(".band").forEach((g) => (g.onclick = () => opts.onSelect && opts.onSelect(g.dataset.id)));
    return c;
  }

  const api = { init, defaults, applyPreset, merge, clone, isOn, cycle, tempAt, checks, fmt, mainVal, drawMimic, drawChart, POS,
    get S() { return S; }, get byId() { return byId; }, get dict() { return DICT; } };
  global.HMICore = api;
})(window);
