/* LIMS 공통 스크립트: JSON API 호출, 알림, 상단 검색(바코드 스캐너), 드래그&드롭 업로드. */
(function () {
  const LIMS = (window.LIMS = window.LIMS || {});

  LIMS.toast = function (msg, kind) {
    const wrap = document.getElementById("toasts");
    if (!wrap) return alert(msg);
    const el = document.createElement("div");
    el.className = "toast " + (kind || "");
    el.textContent = msg;
    wrap.appendChild(el);
    setTimeout(() => el.remove(), kind === "err" ? 7000 : 3500);
  };

  /** JSON API. 오류면 detail을 알림으로 띄우고 예외를 던집니다. */
  LIMS.api = async function (method, url, body) {
    const opt = { method, headers: {} };
    if (body !== undefined) {
      opt.headers["Content-Type"] = "application/json";
      opt.body = JSON.stringify(body);
    }
    const res = await fetch(url, opt);
    let data = null;
    try { data = await res.json(); } catch (e) { /* 빈 응답 */ }
    if (!res.ok) {
      const err = new Error(LIMS.errText(data) || res.statusText);
      err.status = res.status;
      err.data = data;
      throw err;
    }
    return data;
  };

  LIMS.errText = function (data) {
    if (!data) return "";
    const d = data.detail;
    if (typeof d === "string") {
      const extra = (data.conflicts || data.items || []).join(", ");
      return extra ? `${d} (${extra})` : d;
    }
    if (d && d.errors) return d.errors.join("\n");
    if (Array.isArray(d)) return d.map((x) => `${(x.loc || []).slice(1).join(".")}: ${x.msg}`).join("\n");
    return JSON.stringify(d);
  };

  LIMS.fail = function (e) { LIMS.toast(e.message || String(e), "err"); };

  /* ── 상단 검색: 자동완성 키보드 이동 (Alpine 컴포넌트) ── */
  window.suggestBox = function () {
    return {
      idx: -1,
      links() { return [...document.querySelectorAll("#suggest a")]; },
      move(d) {
        const ls = this.links();
        if (!ls.length) return;
        this.idx = (this.idx + d + ls.length) % ls.length;
        ls.forEach((a, i) => a.classList.toggle("on", i === this.idx));
      },
      close() { document.getElementById("suggest").innerHTML = ""; this.idx = -1; },
      onSubmit(ev) {
        const ls = this.links();
        if (this.idx >= 0 && ls[this.idx]) { ev.preventDefault(); location.href = ls[this.idx].href; }
      },
    };
  };

  /* ── 전단(자르기) 입력: 시편 상세 대화상자와 시편 › 전단 화면이 같이 씀 (Alpine 하위 상태) ── */
  window.shearForm = function (sid, proj) {
    return {
      sid, count: 1, start: 1, project: proj, range: "", conflicts: [], busy: false,
      size_text: "", sample_position: "", rolling_direction: "", surface_side: "", storage_location: "", consume: false,
      reset(sid, proj, count) {
        Object.assign(this, { sid, project: proj, count: count || 1, range: "", conflicts: [], size_text: "",
          sample_position: "", rolling_direction: "", surface_side: "", storage_location: "", consume: false });
      },
      async suggest() {
        try {
          const r = await LIMS.api("GET", `/api/specimens/${this.sid}/next?count=${this.count || 1}`);
          this.start = r.suggest; this.conflicts = []; this.showRange(r);
        } catch (e) { this.range = ""; LIMS.fail(e); }
      },
      async check() {
        try {
          const r = await LIMS.api("GET", `/api/specimens/${this.sid}/next?count=${this.count || 1}&start=${this.start}`);
          this.conflicts = r.conflicts; this.showRange(r);
        } catch (e) { this.range = ""; LIMS.fail(e); }
      },
      showRange(r) { this.range = r.first === r.last ? r.first : `${r.first} ~ ${r.last} (${this.count}개)`; },
      /** 저장 → split API 응답(children, engrave_csv, label_pdf). 실패하면 알림 후 null */
      async save() {
        this.busy = true;
        try {
          return await LIMS.api("POST", `/api/specimens/${this.sid}/split`, {
            count: this.count, start: this.start, project_code: this.project, size_text: this.size_text || null,
            sample_position: this.sample_position || null, rolling_direction: this.rolling_direction || null,
            surface_side: this.surface_side || null, storage_location: this.storage_location || null,
            mark_parent_consumed: this.consume });
        } catch (e) {
          if (e.data && e.data.conflicts) this.conflicts = e.data.conflicts;
          LIMS.fail(e);
          return null;
        } finally { this.busy = false; }
      },
    };
  };

  /* 어느 화면에서든 스캐너(키보드 입력)가 들어오면 검색창으로 보냅니다. F2 = 검색창 포커스. */
  document.addEventListener("keydown", (e) => {
    const q = document.getElementById("gq");
    if (!q) return;
    if (e.key === "F2") { e.preventDefault(); q.focus(); q.select(); return; }
    const t = e.target;
    const typing = t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable);
    if (typing || e.ctrlKey || e.metaKey || e.altKey) return;
    if (/^[0-9A-Za-z-]$/.test(e.key)) { q.value = ""; q.focus(); }
  });

  /* ── 드래그&드롭 업로드 (다중 파일·폴더) ── */
  async function walk(entry, out) {
    if (entry.isFile) {
      await new Promise((ok) => entry.file((f) => { out.push(f); ok(); }, ok));
    } else if (entry.isDirectory) {
      const reader = entry.createReader();
      let batch;
      do {
        batch = await new Promise((ok) => reader.readEntries(ok, () => ok([])));
        for (const e of batch) await walk(e, out);
      } while (batch.length);
    }
  }

  async function filesFromDrop(ev) {
    const items = ev.dataTransfer.items;
    if (items && items.length && items[0].webkitGetAsEntry) {
      const out = [];
      for (const it of items) {
        const en = it.webkitGetAsEntry && it.webkitGetAsEntry();
        if (en) await walk(en, out);
      }
      return out;
    }
    return [...ev.dataTransfer.files];
  }

  const LABEL = { matched: "연결", unmatched: "미분류", duplicate: "중복", error: "오류" };

  /** el: 드롭존 요소. opts: {testRun, list (결과 ul), onDone(summary)} */
  LIMS.uploader = function (el, opts) {
    opts = opts || {};
    const input = document.createElement("input");
    input.type = "file";
    input.multiple = true;
    input.hidden = true;
    el.appendChild(input);
    el.addEventListener("click", (e) => { if (e.target !== input && !e.target.closest("a,button")) input.click(); });
    input.addEventListener("change", () => send([...input.files]));
    ["dragenter", "dragover"].forEach((t) => el.addEventListener(t, (e) => { e.preventDefault(); el.classList.add("over"); }));
    ["dragleave", "drop"].forEach((t) => el.addEventListener(t, (e) => { e.preventDefault(); el.classList.remove("over"); }));
    el.addEventListener("drop", async (e) => send(await filesFromDrop(e)));

    async function send(files) {
      files = files.filter((f) => !/^(\.|Thumbs\.db$|desktop\.ini$)/i.test(f.name));
      if (!files.length) return;
      const list = opts.list;
      if (list) list.innerHTML = `<li class="muted">${files.length}개 파일 올리는 중…</li>`;
      const all = [];
      const sum = { matched: 0, unmatched: 0, duplicate: 0, error: 0 };
      for (let i = 0; i < files.length; i += 20) {
        const fd = new FormData();
        files.slice(i, i + 20).forEach((f) => fd.append("files", f, f.name));
        if (opts.testRun) fd.append("test_run_no", opts.testRun);
        if (opts.shortId) fd.append("short_id", opts.shortId);
        try {
          const res = await fetch("/api/files", { method: "POST", body: fd });
          const data = await res.json();
          if (!res.ok) throw new Error(LIMS.errText(data));
          all.push(...data.results);
          for (const k in data.summary) sum[k] += data.summary[k];
        } catch (e) { LIMS.fail(e); break; }
        if (list) list.innerHTML = `<li class="muted">${Math.min(i + 20, files.length)} / ${files.length}</li>`;
      }
      if (list) {
        list.innerHTML = all.map((r) =>
          `<li><span class="s ${r.status}">${LABEL[r.status] || r.status}</span><span class="mono">${esc(r.name)}</span>` +
          `<span class="muted">${r.short_id ? esc(r.short_id) + (r.cycle != null ? " · W" + String(r.cycle).padStart(2, "0") : "") : ""} ${esc(r.message || "")}</span></li>`).join("");
      }
      LIMS.toast(`연결 ${sum.matched} · 미분류 ${sum.unmatched} · 중복 ${sum.duplicate}${sum.error ? " · 오류 " + sum.error : ""}`,
        sum.error ? "err" : "ok");
      if (opts.onDone) opts.onDone(sum, all);
    }
  };

  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }
  LIMS.esc = esc;

  LIMS.download = function (url) { const a = document.createElement("a"); a.href = url; a.download = ""; document.body.appendChild(a); a.click(); a.remove(); };
})();
