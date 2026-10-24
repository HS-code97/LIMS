/* 시편체계 안내 화면 (numbering_guide.html) — 번호 색칠, 흐름 스텝퍼, 하이픈 토글, 번호 체험기, 계보 트리, 목차.
   규칙은 `시편번호 체계.md` v3.1 · app/services/marking.py와 같게 둡니다. 외부 라이브러리 없음. */
(function () {
  "use strict";
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => Array.from(el.querySelectorAll(s));
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const REDUCED = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;
  // 가로 목록 안에서만 스크롤 (scrollIntoView는 페이지 전체를 움직임)
  const hscroll = (box, el) => {
    const l = el.getBoundingClientRect().left - box.getBoundingClientRect().left + box.scrollLeft, r = l + el.offsetWidth;
    if (l < box.scrollLeft || r > box.scrollLeft + box.clientWidth)
      box.scrollTo({ left: Math.max(0, l - (box.clientWidth - el.offsetWidth) / 2), behavior: REDUCED ? "auto" : "smooth" });
  };
  const KIND_NAME = { coil: "코일", proj: "과제", stage: "단계", branch: "가지", cut: "후절단", piece: "분석조각", tail: "조건 꼬리" };
  const STAGE_NAME = { A: "전폭시편", B: "전단 블랭크", C: "도금", D: "열처리", E: "도장" };

  // ── 번호 → 구간 ────────────────────────────────────────
  // 각인: 코일-가지[-후절단][-분석조각] · 전체: 코일-과제-단계-가지[-후절단][-분석조각][-꼬리…]
  function parse(str, kind) {
    if (!/^[A-Z]{2}\d(-|$)/.test(str)) return null;
    const t = str.split("-");
    const out = [{ k: "coil", v: t.shift() }];
    if (kind === "full") {
      if (t.length < 3) return null;
      out.push({ k: "proj", v: t.shift() }, { k: "stage", v: t.shift() });
    }
    if (t.length) out.push({ k: "branch", v: t.shift() });
    if (t.length && /^[A-Z]$/.test(t[0])) out.push({ k: "cut", v: t.shift() });
    if (t.length && /^\d$/.test(t[0])) out.push({ k: "piece", v: t.shift() });
    t.forEach((v) => out.push({ k: "tail", v }));
    return out;
  }
  function segKeys(segs) {
    const n = {};
    return segs.map((s) => { n[s.k] = (n[s.k] || 0) + 1; return s.k + n[s.k]; });
  }
  function numHTML(str, kind, prev) {
    const segs = parse(str, kind);
    if (!segs) return esc(str);
    const old = {};
    if (prev) { const ps = parse(prev, kind) || []; segKeys(ps).forEach((key, i) => (old[key] = ps[i].v)); }
    return segKeys(segs).map((key, i) => {
      const s = segs[i], chg = prev !== undefined && old[key] !== s.v;
      return `<span class="sg k-${s.k}${chg ? " chg" : ""}" title="${KIND_NAME[s.k]}">${esc(s.v)}</span>`;
    }).join('<i class="hy">-</i>');
  }
  function paint(el, str, kind, prev) {
    if (!str) { el.innerHTML = '<span class="none">아직 없음</span>'; return; }
    el.innerHTML = `<code class="num-t">${numHTML(str, kind, prev === null ? "" : prev)}</code>`;
  }
  $$("[data-num]").forEach((el) => { el.innerHTML = numHTML(el.textContent.trim(), el.dataset.num); });
  $$("[data-legend]").forEach((el) => {
    el.innerHTML = ["coil", "proj", "stage", "branch", "cut", "piece", "tail"].map((k) => `<span class="k-${k}">${KIND_NAME[k]}</span>`).join("");
  });

  // ── DataMatrix 모양(장식) ───────────────────────────────
  $$("[data-dm]").forEach((el) => {
    let h = 7;
    const N = 12, cells = [];
    for (let y = 0; y < N; y++) for (let x = 0; x < N; x++) {
      let on;
      if (x === 0 || y === N - 1) on = true;                       // L자 기준선
      else if (y === 0) on = x % 2 === 0;                          // 위 · 오른쪽 점선
      else if (x === N - 1) on = y % 2 === 1;
      else { h = (h * 31 + x * 7 + y * 13) % 97; on = h % 3 !== 0; }
      cells.push(`<i class="${on ? "" : "o"}"></i>`);
    }
    el.innerHTML = cells.join("");
  });

  // ── 01 흐름 스텝퍼 ──────────────────────────────────────
  const PROCS = ["전단", "도금", "열처리", "전처리", "도장"];
  const FLOW = [
    { s: "코일", label: "현장 코일", act: "none", actText: "출발점", title: "현장 코일",
      desc: "과제 목적으로 현장 코일에서 시편을 가져옵니다. 코일 자체는 시편이 아니어서 시편번호가 없고, 현장 코일번호 CQV3141T에서 3자리 코일코드 QV3를 만듭니다.",
      mark: null, full: null, procs: [], art: "coil", layers: ["steel"] },
    { s: "A", label: "전폭시편", act: "cut", actText: "✂ 입고 · 새 시편", title: "전폭시편 — A 입고",
      desc: "1200×600 mm 전폭시편 2~3장을 시편보관함에 둡니다. 아직 GA·GI 같은 실험 조건은 정해지지 않았습니다. 전폭마다 영문 1자(A, B, C…)를 받고, 이때 처음 시편번호가 생깁니다.",
      mark: "QV3-A", full: "QV3-A6-A-A", procs: [], art: "sheet", layers: ["steel"] },
    { s: "B", label: "전단", act: "cut", actText: "✂ 처음 자르기 · 새 시편", title: "전단 블랭크 — B",
      desc: "전폭을 잘라 200×300 mm 블랭크를 만듭니다. 조각마다 새 레코드가 생기고 각인번호에 조각 번호 2자리가 붙습니다. 처음 자를 때만 단계가 A → B로 바뀝니다.",
      mark: "QV3-A02", full: "QV3-A6-B-A02", procs: ["전단"], art: "shear", layers: ["steel"] },
    { s: "C", label: "도금", act: "treat", actText: "⚗ 처리 · 같은 시편", title: "도금 — C",
      desc: "블랭크를 도금합니다. 모양은 그대로지만 도금층이 생겨 성질이 완전히 달라지므로 단계가 C로 오릅니다. 각인번호는 그대로이고, 전체번호 꼬리에 도금 조건 M206K가 붙습니다.",
      mark: "QV3-A02", full: "QV3-A6-C-A02-M206K", procs: ["전단", "도금"], art: "blank", layers: ["steel", "zinc"] },
    { s: "D", label: "열처리", act: "treat", actText: "⚗ 처리 · 같은 시편", title: "열처리 — D",
      desc: "도금판을 열처리하면 도금층이 합금화되는 등 성질이 바뀝니다. 단계가 D로 오르고 꼬리에 H03이 붙습니다. 이번에도 각인은 그대로입니다.",
      mark: "QV3-A02", full: "QV3-A6-D-A02-M206K-H03", procs: ["전단", "도금", "열처리"], art: "blank", layers: ["steel", "alloy"] },
    { s: "T", label: "전처리", act: "treat", actText: "⚗ 처리 · 같은 시편", title: "전처리(화성) — 단계 그대로",
      desc: "화성처리 같은 전처리는 단계를 바꾸지 않습니다. 단계는 D 그대로이고, 꼬리에 T02만 붙습니다.",
      mark: "QV3-A02", full: "QV3-A6-D-A02-M206K-H03-T02", procs: ["전단", "도금", "열처리", "전처리"], art: "blank", layers: ["steel", "alloy", "conv"] },
    { s: "E", label: "도장", act: "treat", actText: "⚗ 처리 · 같은 시편", title: "도장 — E",
      desc: "도막이 생기므로 단계가 E로 오르고 꼬리에 P12가 붙습니다. 입고 뒤 처음 자를 때 말고는 각인번호가 한 번도 바뀌지 않았습니다.",
      mark: "QV3-A02", full: "QV3-A6-E-A02-M206K-H03-T02-P12", procs: PROCS, art: "blank", layers: ["steel", "alloy", "conv", "paint"] },
    { s: "✂", label: "실험편", act: "cut", actText: "✂ 다시 자르기 · 새 시편", title: "후절단 실험편",
      desc: "판을 다시 잘라 70×150 mm 실험편을 만듭니다. 각인번호에 영문 1자(A, B…)가 붙습니다. 처음 자르는 것이 아니므로 단계는 E 그대로이고, 꼬리도 그대로 물려받습니다.",
      mark: "QV3-A02-A", full: "QV3-A6-E-A02-A-M206K-H03-T02-P12", procs: PROCS, art: "coupon", layers: ["steel", "alloy", "conv", "paint"] },
    { s: "▪", label: "분석조각", act: "cut", actText: "✂ 자르기 · 새 시편", title: "분석조각",
      desc: "실험편을 잘라 20×20 mm 분석조각을 만듭니다(SEM 단면, GDS 등). 숫자 1자(1~9)가 붙습니다. 작은 조각에는 두 줄로 QV3 / A02A3처럼 새길 수 있습니다.",
      mark: "QV3-A02-A-3", full: "QV3-A6-E-A02-A-3-M206K-H03-T02-P12", procs: PROCS, art: "piece", layers: ["steel", "alloy", "conv", "paint"] },
  ];

  const DEFS = `<defs>
    <linearGradient id="gSteel" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#dfe3e8"/><stop offset=".45" stop-color="#b3bbc4"/><stop offset=".6" stop-color="#cdd3da"/><stop offset="1" stop-color="#9ea7b1"/></linearGradient>
    <linearGradient id="gZinc" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#e9f1f7"/><stop offset=".5" stop-color="#bccfdd"/><stop offset="1" stop-color="#d5e2ec"/></linearGradient>
    <linearGradient id="gAlloy" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#a7b0b9"/><stop offset="1" stop-color="#76828e"/></linearGradient>
    <linearGradient id="gPaint" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#4c9a86"/><stop offset="1" stop-color="#2a6c5c"/></linearGradient>
    <pattern id="pConv" width="6" height="6" patternUnits="userSpaceOnUse"><rect width="6" height="6" fill="#ead796"/><path d="M0 6 6 0" stroke="#c9b25a" stroke-width="1"/></pattern>
  </defs>`;
  const SURF = { steel: "url(#gSteel)", zinc: "url(#gZinc)", alloy: "url(#gAlloy)", conv: "url(#pConv)", paint: "url(#gPaint)" };
  const top = (layers) => SURF[layers[layers.length - 1]];
  const engr = (x, y, t, size = 13, anchor = "start") =>
    `<text x="${x}" y="${y}" font-family="JetBrains Mono,Consolas,monospace" font-weight="700" font-size="${size}" fill="#2f363d" text-anchor="${anchor}" style="paint-order:stroke" stroke="rgba(255,255,255,.7)" stroke-width="2">${esc(t)}</text>`;
  const label = (x, y, t, o = {}) =>
    `<text x="${x}" y="${y}" font-size="${o.size || 12}" fill="${o.fill || "#727781"}" font-weight="${o.w || 500}" text-anchor="${o.a || "start"}">${esc(t)}</text>`;

  function topView(step) {
    const L = step.layers, f = top(L);
    switch (step.art) {
      case "coil":
        return `<g class="fade">
          <rect x="150" y="96" width="250" height="34" fill="url(#gSteel)" stroke="#8a939d"/>
          ${label(400, 90, "→ 시편 채취", { a: "end", fill: "#2f6ba8", w: 600 })}
          <circle cx="150" cy="196" r="100" fill="url(#gSteel)" stroke="#8a939d"/>
          ${[86, 72, 58, 44].map((r) => `<circle cx="150" cy="196" r="${r}" fill="none" stroke="#8a939d" stroke-width=".8" opacity=".7"/>`).join("")}
          <circle cx="150" cy="196" r="30" fill="#f0f4fb" stroke="#8a939d"/>
          ${label(150, 322, "현장 코일 CQV3141T", { a: "middle", fill: "#414750", w: 600, size: 13 })}
          <g transform="translate(278 166)"><rect width="122" height="56" rx="8" fill="#e3eefa" stroke="#05528e"/>
          ${label(61, 22, "코일코드", { a: "middle", fill: "#05528e", size: 11 })}<text x="61" y="45" text-anchor="middle" font-family="JetBrains Mono,monospace" font-weight="700" font-size="20" fill="#05528e">QV3</text></g></g>`;
      case "sheet":
        return `<g class="fade">
          ${["C", "B"].map((c, i) => `<rect x="${92 - i * 18}" y="${44 + i * 18}" width="300" height="150" fill="url(#gSteel)" stroke="#8a939d" opacity="${0.55 + i * 0.2}"/>${engr(380 - i * 18, 60 + i * 18, c, 12, "end")}`).join("")}
          <rect x="56" y="80" width="300" height="150" fill="url(#gSteel)" stroke="#5f6872" stroke-width="1.5"/>
          ${engr(66, 220, "QV3-A", 15)}
          <path d="M56 252h300M56 246v12M356 246v12" stroke="#727781"/>${label(206, 272, "1200 mm", { a: "middle" })}
          <path d="M370 80v150M364 80h12M364 230h12" stroke="#727781"/>${label(380, 160, "600", {})}
          ${label(206, 318, "전폭시편 2~3장 · 영문 1자씩 (A, B, C…)", { a: "middle", fill: "#414750", w: 600, size: 13 })}</g>`;
      case "shear": {
        const cw = 50, ch = 75, x0 = 50, y0 = 70;
        let cells = "";
        for (let r = 0; r < 2; r++) for (let c = 0; c < 6; c++) {
          const n = r * 6 + c + 1, hit = n === 2, x = x0 + c * cw, y = y0 + r * ch;
          cells += `<rect x="${x + 2}" y="${y + 2}" width="${cw - 4}" height="${ch - 4}" fill="url(#gSteel)" stroke="${hit ? "#05528e" : "#8a939d"}" stroke-width="${hit ? 2.5 : 1}" opacity="${hit ? 1 : 0.6}"/>`
            + engr(x + cw / 2, y + ch / 2 + 4, String(n).padStart(2, "0"), hit ? 13 : 11, "middle");
        }
        return `<g class="fade">
          <rect x="${x0}" y="${y0}" width="300" height="150" fill="none" stroke="#5f6872" stroke-dasharray="5 4"/>
          ${cells}
          <g transform="translate(366 70)"><rect width="76" height="114" fill="url(#gSteel)" stroke="#05528e" stroke-width="2"/>${engr(6, 106, "QV3-A02", 11)}</g>
          <path d="M${x0 + 75} ${y0 - 4} C 200 30, 330 40, 400 66" fill="none" stroke="#2f6ba8" stroke-width="1.5" marker-end="url(#arr)"/>
          ${label(404, 204, "블랭크 200×300", { a: "middle", fill: "#05528e", w: 600 })}
          ${label(200, 260, "✂ 전폭 A를 자름 → 조각마다 새 시편 (01~99)", { a: "middle", fill: "#414750", w: 600, size: 13 })}
          ${label(200, 282, "각인 = 전폭 영문 + 조각 숫자 2자리", { a: "middle" })}</g>`;
      }
      case "blank":
        return `<g class="fade">
          <rect x="120" y="40" width="170" height="255" rx="2" fill="${f}" stroke="#5f6872" stroke-width="1.5"/>
          ${engr(130, 284, "QV3-A02", 15)}
          <g transform="translate(305 250)"><rect width="104" height="40" rx="6" fill="#e3f4e6" stroke="#38744a"/>
          ${label(52, 17, "각인 그대로", { a: "middle", fill: "#1e5b33", w: 700 })}${label(52, 32, "같은 시편 · 같은 레코드", { a: "middle", fill: "#1e5b33", size: 10.5 })}</g>
          ${label(205, 322, step.title.split(" — ")[0] + " 후 블랭크", { a: "middle", fill: "#414750", w: 600, size: 13 })}</g>`;
      case "coupon": {
        let parts = "";
        ["A", "B", "C", "D"].forEach((c, i) => {
          const x = 128 + (i % 2) * 78, y = 46 + Math.floor(i / 2) * 124, hit = i === 0;
          parts += `<rect x="${x}" y="${y}" width="74" height="118" fill="${f}" stroke="${hit ? "#0e6e74" : "#8a939d"}" stroke-width="${hit ? 2.5 : 1}" opacity="${hit ? 1 : 0.55}"/>`
            + engr(x + 6, y + 110, hit ? "QV3-A02-A" : "…" + c, hit ? 9.5 : 11);
        });
        return `<g class="fade">
          <rect x="120" y="40" width="170" height="255" fill="none" stroke="#5f6872" stroke-dasharray="5 4"/>
          ${parts}
          ${label(330, 80, "실험편 70×150", { fill: "#0e6e74", w: 700 })}
          ${label(330, 100, "영문 1자 (A~Y)", {})}
          ${label(330, 130, "단계·꼬리는", {})}${label(330, 148, "부모에게서 물려받음", {})}
          ${label(205, 322, "✂ 판을 다시 자름 → 실험편마다 새 시편", { a: "middle", fill: "#414750", w: 600, size: 13 })}</g>`;
      }
      case "piece":
        return `<g class="fade">
          <rect x="120" y="50" width="96" height="232" fill="${f}" stroke="#5f6872" stroke-width="1.5"/>
          ${engr(126, 272, "QV3-A02-A", 10)}
          ${[1, 2, 3].map((n) => `<rect x="${136}" y="${62 + (n - 1) * 34}" width="28" height="28" fill="none" stroke="${n === 3 ? "#8a6400" : "#8a939d"}" stroke-dasharray="3 3" stroke-width="${n === 3 ? 2 : 1}"/>`).join("")}
          <path d="M166 144 L 270 150" stroke="#8a6400" stroke-width="1.5" stroke-dasharray="4 3"/>
          <g transform="translate(270 92)"><rect width="120" height="120" fill="${f}" stroke="#8a6400" stroke-width="2.5"/>
            ${engr(60, 54, "QV3", 20, "middle")}${engr(60, 82, "A02A3", 20, "middle")}</g>
          ${label(330, 232, "분석조각 20×20 (확대)", { a: "middle", fill: "#8a6400", w: 700 })}
          ${label(330, 250, "작은 조각은 두 줄 각인", { a: "middle" })}
          ${label(205, 322, "✂ 실험편을 자름 → 숫자 1자 (1~9)", { a: "middle", fill: "#414750", w: 600, size: 13 })}</g>`;
    }
    return "";
  }

  function sectionView(layers) {
    // 아래에서 위로: 강판 소지 → (도금 또는 합금화층) → 화성피막 → 도막
    const x = 470, w = 120;
    const coat = layers.includes("alloy") ? "alloy" : layers.includes("zinc") ? "zinc" : null;
    const NAME = { zinc: "도금층 (Zn계)", alloy: "합금화층 (Fe-Zn 등)", conv: "화성피막", paint: "도막" };
    let y = 300, out = "";
    const tags = [];
    const band = (h, fill, name, key) => {
      y -= h;
      out += `<rect class="fade" x="${x}" y="${y}" width="${w}" height="${h}" fill="${fill}" stroke="#5f6872" stroke-width=".8"/>`;
      if (name) tags.push({ at: y + h / 2, name, key });
    };
    if (coat) band(12, SURF[coat], "", false);            // 아랫면 도금
    band(90, "url(#gSteel)", "강판 소지", false);
    if (coat) band(14, SURF[coat], NAME[coat], true);
    if (layers.includes("conv")) band(6, SURF.conv, NAME.conv, true);
    if (layers.includes("paint")) band(22, SURF.paint, NAME.paint, true);
    // 얇은 층의 이름이 겹치지 않게 위에서부터 15px씩 띄우고 가는 선으로 잇기
    tags.sort((p, q) => p.at - q.at);
    let last = -Infinity;
    tags.forEach((t) => {
      const ty = Math.max(t.at, last + 15); last = ty;
      out += `<path d="M${x + w} ${t.at}H${x + w + 6}L${x + w + 12} ${ty}H${x + w + 14}" fill="none" stroke="#a0a6ae" stroke-width=".8"/>`
        + label(x + w + 16, ty + 4, t.name, { size: 11, fill: t.key ? "#171c21" : "#727781", w: t.key ? 600 : 500 });
    });
    return `${label(x, 126, "단면 (층 구조)", { fill: "#414750", w: 700, size: 12.5 })}
      ${label(x, 143, layers.length === 1 ? "아직 소지강판만" : "층이 생겨도 모양은 그대로", { size: 11 })}${out}`;
  }

  const flow = $("[data-flow]");
  if (flow) {
    const stepsEl = $("[data-steps]", flow), art = $("[data-art]", flow);
    let cur = 0, timer = null;
    stepsEl.innerHTML = FLOW.map((s, i) => `<li><button type="button" role="tab" id="fl-${i}" class="${s.act === "cut" ? "cut" : ""}" aria-selected="false" data-i="${i}"><b>${esc(s.s)}</b>${esc(s.label)}</button></li>`).join("");
    const show = (i, user) => {
      if (user) stop();
      const prev = FLOW[cur], s = FLOW[i], first = i === cur;
      cur = i;
      $$("button", stepsEl).forEach((b, j) => {
        b.setAttribute("aria-selected", j === i ? "true" : "false");
        b.classList.toggle("done", j < i);
      });
      hscroll(stepsEl, $(`#fl-${i}`));
      // 위에서 본 모양과 단면을 따로 그려, 좁은 화면에서는 위아래로 쌓아 글자가 작아지지 않게 함
      art.innerHTML = `<svg class="tv" viewBox="0 0 450 340" role="img" aria-label="${esc(s.title)} — 위에서 본 모양">${DEFS}
        <defs><marker id="arr" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0 10 5 0 10z" fill="#2f6ba8"/></marker></defs>
        ${label(20, 24, "위에서 본 모양", { fill: "#414750", w: 700, size: 12.5 })}${topView(s)}</svg>
        <svg class="sv" viewBox="455 106 265 204" role="img" aria-label="${esc(s.title)} — 단면">${DEFS}${sectionView(s.layers)}</svg>`;
      const act = $("[data-act]", flow);
      act.className = "g-act " + s.act;
      act.textContent = s.actText;
      $("[data-title]", flow).textContent = s.title;
      $("[data-desc]", flow).textContent = s.desc;
      const mk = $("[data-mark]", flow), fu = $("[data-full]", flow);
      paint(mk, s.mark, "mark", first ? undefined : prev.mark);
      if (s.mark && !first && prev.mark === s.mark) mk.insertAdjacentHTML("beforeend", '<span class="same-tag">✓ 그대로</span>');
      paint(fu, s.full, "full", first ? undefined : prev.full);
      $("[data-procs]", flow).innerHTML = PROCS.map((p) => `<span class="${s.procs.includes(p) ? "y" : ""}">${s.procs.includes(p) ? "✓" : "–"} ${p}</span>`).join("");
      $("[data-prev]", flow).disabled = i === 0;
      $("[data-next]", flow).disabled = i === FLOW.length - 1;
    };
    const stop = () => { if (timer) { clearInterval(timer); timer = null; $("[data-play]", flow).textContent = "▶ 자동 재생"; } };
    stepsEl.addEventListener("click", (e) => { const b = e.target.closest("button[data-i]"); if (b) show(+b.dataset.i, true); });
    stepsEl.addEventListener("keydown", (e) => {
      if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
      e.preventDefault();
      const n = Math.max(0, Math.min(FLOW.length - 1, cur + (e.key === "ArrowRight" ? 1 : -1)));
      show(n, true); $(`#fl-${n}`).focus();
    });
    $("[data-prev]", flow).addEventListener("click", () => cur > 0 && show(cur - 1, true));
    $("[data-next]", flow).addEventListener("click", () => cur < FLOW.length - 1 && show(cur + 1, true));
    $("[data-play]", flow).addEventListener("click", (e) => {
      if (timer) return stop();
      if (cur === FLOW.length - 1) show(0);
      e.currentTarget.textContent = "❚❚ 멈춤";
      timer = setInterval(() => { if (cur >= FLOW.length - 1) stop(); else show(cur + 1); }, 2800);
    });
    let tx = null;
    art.addEventListener("touchstart", (e) => (tx = e.touches[0].clientX), { passive: true });
    art.addEventListener("touchend", (e) => {
      if (tx === null) return;
      const dx = e.changedTouches[0].clientX - tx; tx = null;
      if (Math.abs(dx) > 40) show(Math.max(0, Math.min(FLOW.length - 1, cur + (dx < 0 ? 1 : -1))), true);
    });
    show(0);
  }

  // ── 03 하이픈 지우기 ───────────────────────────────────
  $$("[data-alt]").forEach((el) => {
    el.innerHTML = el.textContent.trim().split("").map((c) =>
      c === "-" ? '<span class="h">-</span><span class="gap"></span>' : `<span class="${/\d/.test(c) ? "ch-d" : "ch-l"}">${c}</span>`).join("");
  });
  const hy = $("[data-hyph]");
  if (hy) {
    const btn = $("[data-hyph-btn]", hy);
    btn.addEventListener("click", () => {
      const off = hy.classList.toggle("off");
      btn.setAttribute("aria-pressed", off ? "true" : "false");
      btn.textContent = off ? "하이픈 되돌리기" : "하이픈 지우기";
    });
  }

  // ── 04 번호 체험기 ─────────────────────────────────────
  const sim = $("[data-sim]");
  if (sim) {
    const ORDER = "ABCDE";
    let st, busy = false;
    const reset = () => (st = { proj: "A6", stage: "A", branch: "A", cut: null, piece: null, tail: [], procs: [], log: [], plate: "M206K" });
    const markOf = () => ["QV3", st.branch, st.cut, st.piece].filter(Boolean).join("-");
    const fullOf = () => ["QV3", st.proj, st.stage, st.branch, st.cut, st.piece, ...st.tail].filter(Boolean).join("-");
    const raise = (to) => { const was = st.stage; if (ORDER.indexOf(to) > ORDER.indexOf(was)) { st.stage = to; return `단계 ${was} → ${to}`; } return null; };
    const addProc = (p) => { if (!st.procs.includes(p)) st.procs.push(p); };
    const ACTIONS = {
      cut: {
        label: () => st.branch.length === 1 ? ["✂", "자르기", "전단 → 블랭크"] : !st.cut ? ["✂", "자르기", "후절단 → 실험편"] : !st.piece ? ["✂", "자르기", "분석조각"] : ["✂", "자르기", "더 자를 수 없음 (예시)"],
        ok: () => !st.piece,
        run: (o = {}) => {
          if (st.branch.length === 1) {
            st.branch += o.no || "02"; addProc("전단"); raise("B");
            return ["처음 자르기: 새 시편(자식)이 생기고 조각 번호가 붙음", "단계 A → B · 처음 자를 때만 단계가 바뀝니다"];
          }
          if (!st.cut) {
            st.cut = "A";
            return ["후절단: 새 시편(실험편), 영문 1자 붙음", `단계 ${st.stage} 그대로 · 꼬리는 부모에게서 물려받음${st.stage === "B" ? " (도금 전 재절단은 드문 경우)" : ""}`];
          }
          st.piece = "3";
          return ["분석조각: 새 시편, 숫자 1자 붙음", `단계 ${st.stage} 그대로`];
        },
      },
      PLATE: { label: () => ["⚗", "도금", "단계 C · 꼬리 " + st.plate], ok: () => st.stage !== "A" && !st.procs.includes("도금"),
        run: () => { st.tail.push(st.plate); addProc("도금"); const r = raise("C"); return ["도금: 같은 시편, 꼬리 " + st.plate, r || `단계는 내려가지 않음 · ${st.stage} 유지`, !r]; } },
      HEAT: { label: () => ["⚗", "열처리", "단계 D · 꼬리 H03"], ok: () => st.stage !== "A",
        run: () => { st.tail.push("H03"); addProc("열처리"); const r = raise("D"); return ["열처리: 같은 시편, 꼬리 H03", r || `단계는 내려가지 않음 · ${st.stage} 유지, 꼬리와 이력에만 남음`, !r]; } },
      PRETREAT: { label: () => ["⚗", "전처리(화성)", "단계 그대로 · 꼬리 T02"], ok: () => st.stage !== "A",
        run: () => { st.tail.push("T02"); addProc("전처리"); return ["전처리: 같은 시편, 꼬리 T02", `단계 ${st.stage} 그대로 · 전처리는 단계를 바꾸지 않음`]; } },
      PAINT: { label: () => ["⚗", "도장", "단계 E · 꼬리 P12"], ok: () => st.stage !== "A",
        run: () => { const c = st.procs.includes("도장") ? "P15" : "P12"; st.tail.push(c); addProc("도장"); const r = raise("E");
          return [`도장: 같은 시편, 꼬리 ${c}${c === "P15" ? " (두 번째 도장도 블록으로 남음)" : ""}`, r || `단계 ${st.stage} 유지`]; } },
      USE: { label: () => ["⇄", "다른 과제가 사용", "과제 A6 → B6"], ok: () => st.proj === "A6",
        run: () => { st.proj = "B6"; st.plate = "A106K"; return ["B6 과제 연구원이 가져가 씀: 과제코드 A6 → B6", "이전 과제·담당은 이력(USE)에 남음 · 각인번호는 그대로"]; } },
    };
    const btns = $("[data-sim-btns]", sim);
    const render = (prevMark, prevFull) => {
      btns.innerHTML = ["cut", "sep", "PLATE", "HEAT", "PRETREAT", "PAINT", "sep", "USE", "reset"].map((k) => {
        if (k === "sep") return '<div class="sep"></div>';
        if (k === "reset") return '<button class="btn ghost" type="button" data-a="reset">↺ 처음부터 (전폭시편 QV3-A)</button>';
        const [ico, name, sub] = ACTIONS[k].label();
        return `<button class="btn" type="button" data-a="${k}" ${ACTIONS[k].ok() && !busy ? "" : "disabled"}><span class="k">${ico}</span><span>${name}<small>${esc(sub)}</small></span></button>`;
      }).join("");
      paint($("[data-sim-mark]", sim), markOf(), "mark", prevMark);
      paint($("[data-sim-full]", sim), fullOf(), "full", prevFull);
      $("[data-sim-procs]", sim).innerHTML = PROCS.map((p) => `<span class="${st.procs.includes(p) ? "y" : ""}">${st.procs.includes(p) ? "✓" : "–"} ${p}</span>`).join("");
      $("[data-sim-log]", sim).innerHTML = st.log.length
        ? st.log.map((l, i) => `<li class="${l[2] ? "warn" : ""}"><span class="i">${i + 1}</span><span>${esc(l[0])}<em>${esc(l[1])}</em></span></li>`).join("")
        : '<li><span class="i">·</span><span>전폭시편 QV3-A에서 시작합니다.<em>왼쪽 버튼을 누르는 순서대로 번호가 만들어집니다.</em></span></li>';
    };
    const act = (k, o) => {
      const pm = markOf(), pf = fullOf();
      st.log.push(ACTIONS[k].run(o));
      render(pm, pf);
    };
    btns.addEventListener("click", (e) => {
      const b = e.target.closest("button[data-a]");
      if (!b || busy) return;
      if (b.dataset.a === "reset") { reset(); render(); } else act(b.dataset.a);
    });
    const PRESETS = {
      std: [["cut", { no: "03" }], ["PLATE"], ["HEAT"], ["PRETREAT"], ["PAINT"]],
      paint: [["cut", { no: "06" }], ["PAINT"]],
      noplate: [["cut", { no: "05" }], ["PRETREAT"], ["PAINT"]],
      other: [["cut", { no: "04" }], ["USE"], ["PLATE"]],
    };
    $$("[data-preset]", sim).forEach((b) => b.addEventListener("click", () => {
      if (busy) return;
      reset(); render();
      const seq = PRESETS[b.dataset.preset].slice();
      busy = !REDUCED;
      const next = () => {
        const s = seq.shift();
        if (!s) { busy = false; render(); return; }
        act(s[0], s[1]);
        if (REDUCED) next(); else setTimeout(next, 650);
      };
      if (REDUCED) next(); else setTimeout(next, 250);
    }));
    reset(); render();
  }

  // ── 06 계보 트리 ───────────────────────────────────────
  const TREE = { mark: "QV3", lv: "코일", name: "현장 코일 CQV3141", tag: "590DP",
    note: "코일 자체는 시편이 아니어서 번호가 없고 코일코드만 있습니다. 강종과 현장 코일번호를 기록합니다.", children: [
      { mark: "QV3-A", lv: "전폭", full: "QV3-A6-A-A", tag: "채취 T", note: "잘라 쓴 뒤에도 레코드는 남아 계보의 뿌리가 됩니다.", children: [
        { mark: "QV3-A01", lv: "블랭크", full: "QV3-A6-B-A01", tag: "보관 중" },
        { mark: "QV3-A02", lv: "블랭크", full: "QV3-A6-C-A02-M206K", tag: "도금 M206K", note: "도금했지만 같은 레코드입니다. 번호가 새로 생기지 않고 단계가 C로, 꼬리에 M206K가 붙었습니다.", children: [
          { mark: "QV3-A02-A", lv: "실험편", full: "QV3-A6-C-A02-A-M206K", tag: "CCT 분석런", note: "도금판을 자른 실험편도 C입니다. C는 언제나 도금된 시편이라는 뜻입니다.", children: [
            { mark: "QV3-A02-A-1", lv: "분석조각", full: "QV3-A6-C-A02-A-1-M206K", tag: "GDS" },
            { mark: "QV3-A02-A-2", lv: "분석조각", full: "QV3-A6-C-A02-A-2-M206K", tag: "보관" },
            { mark: "QV3-A02-A-3", lv: "분석조각", full: "QV3-A6-C-A02-A-3-M206K", tag: "SEM 단면", note: "번호만 봐도 경로가 보입니다: 코일 QV3 → 전폭 A → 블랭크 02 → 실험편 A → 분석조각 3." },
          ] },
          { more: "QV3-A02-B ~ E", lv: "실험편", note: "같은 블랭크에서 같은 조건으로 만든 형제 실험편입니다. 같은 꼬리 M206K = 같은 조건이라는 뜻이고, 번호는 B, C, D, E로 차례로 늘어납니다." },
        ] },
        { mark: "QV3-A03", lv: "블랭크", full: "QV3-A6-E-A03-M206K-H03-T02-P12", tag: "도금→열처리→화성→도장", note: "네 공정을 모두 거쳐 E. 거친 순서대로 꼬리 블록이 이어졌습니다." },
        { mark: "QV3-A04", lv: "블랭크", full: "QV3-B6-C-A04-A106K", tag: "B6 과제", use: true, note: "다른 과제(B6) 연구원이 가져가 GA 도금했습니다. 과제·담당이 B6 쪽으로 넘어가고, 이전 과제는 사용(USE) 이력에 남습니다. 각인번호는 그대로입니다." },
        { mark: "QV3-A05", lv: "블랭크", full: "QV3-A6-E-A05-T02-P12", tag: "도금 없이 화성→도장", note: "도금 블록 없이 T·P 블록만 붙었습니다. B에서 E로 건너뛰었습니다." },
        { mark: "QV3-A06", lv: "블랭크", full: "QV3-A6-E-A06-P12", tag: "바로 도장", note: "E지만 도금·열처리는 거치지 않았습니다. 무엇을 거쳤는지는 꼬리로 봅니다." },
      ] },
      { mark: "QV3-B", lv: "전폭", full: "QV3-A6-A-B", tag: "채취 T · 보관 중" },
      { mark: "QV3-C", lv: "전폭", full: "QV3-A6-A-C", tag: "재입고 · 채취 H", note: "같은 코일을 다시 입고해 같은 코일코드를 쓰고 전폭번호가 C로 이어졌습니다." },
    ] };
  const treeEl = $("[data-tree]"), detail = $("[data-tree-detail]");
  if (treeEl && detail) {
    const nodes = [];
    const walk = (n, path) => {
      const id = nodes.length, p = path.concat(n.mark || n.more);
      nodes.push(Object.assign({ path: p }, n));
      const stage = n.full ? n.full.split("-")[2] : "";
      const btn = `<button type="button" class="g-node${n.more ? " more" : ""}" role="treeitem" aria-selected="false" data-n="${id}">
        <span class="lv">${esc(n.lv)}</span>${stage ? `<span class="st">${stage}</span>` : n.more ? "" : '<span class="st s0">–</span>'}
        <span class="nm">${n.mark ? numHTML(n.mark, "mark") : esc(n.more)}</span>${n.tag ? `<span class="tg">${esc(n.tag)}</span>` : ""}${n.use ? '<span class="use">USE</span>' : ""}</button>`;
      const kids = (n.children || []).map((c) => walk(c, p)).join("");
      return `<li>${btn}${kids ? `<ul role="group">${kids}</ul>` : ""}</li>`;
    };
    treeEl.innerHTML = `<ul>${walk(TREE, [])}</ul>`;
    const pick = (id) => {
      const n = nodes[id];
      $$(".g-node", treeEl).forEach((b) => b.setAttribute("aria-selected", b.dataset.n == id ? "true" : "false"));
      const stage = n.full ? n.full.split("-")[2] : null;
      detail.innerHTML = `<h4>${esc(n.lv)}</h4><div class="t">${n.mark ? `<code class="num-t">${numHTML(n.mark, "mark")}</code>` : esc(n.more)}</div>
        <dl>${n.name ? `<div><dt>현장</dt><dd>${esc(n.name)}</dd></div>` : ""}
        ${n.full ? `<div><dt>전체번호</dt><dd><code class="num-t">${numHTML(n.full, "full")}</code></dd></div>
        <div><dt>단계</dt><dd>${stage} · ${STAGE_NAME[stage]}</dd></div>` : ""}
        <div><dt>계보 (부모 → 나)</dt><dd class="small">${n.path.map(esc).join(" → ")}</dd></div></dl>
        ${n.note ? `<div class="note">${esc(n.note)}</div>` : ""}`;
    };
    treeEl.addEventListener("click", (e) => { const b = e.target.closest(".g-node"); if (b) pick(+b.dataset.n); });
    pick(nodes.findIndex((n) => n.mark === "QV3-A02-A-3"));
  }

  // ── 목차 현재 위치 ─────────────────────────────────────
  const toc = $(".g-toc");
  if (toc && "IntersectionObserver" in window) {
    const links = $$("a", toc);
    const io = new IntersectionObserver((ents) => {
      ents.forEach((en) => {
        if (!en.isIntersecting) return;
        links.forEach((a) => {
          const on = a.getAttribute("href") === "#" + en.target.id;
          a.classList.toggle("on", on);
          if (on) hscroll(toc, a);
        });
      });
    }, { rootMargin: "-35% 0px -60% 0px" });
    links.forEach((a) => { const s = document.querySelector(a.getAttribute("href")); if (s) io.observe(s); });
  }
  // 인쇄할 때는 접힌 내용을 모두 펼침
  window.addEventListener("beforeprint", () => $$(".gd details").forEach((d) => (d.dataset.wasOpen = d.open, d.open = true)));
  window.addEventListener("afterprint", () => $$(".gd details").forEach((d) => (d.open = d.dataset.wasOpen === "true")));
})();
