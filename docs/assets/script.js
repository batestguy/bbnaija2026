/* BBNaija 2026 predictor — dashboard engine (zero dependencies).
   Consumes predictions.json (see PLAN.md §5 schema): podium, pairwise,
   housemates[] (status, gambit_flag, history[], p_rank_1/top3/top5,
   hdi_89, statistical_tie_with), trend_projection, at_risk, precision,
   placeholder, rhat_max, generated_at. */
(async function () {
  "use strict";
  const P = await (await fetch("predictions.json", { cache: "no-store" })).json();

  const $ = (id) => document.getElementById(id);
  const pct = (v, d = 1) => (100 * v).toFixed(d) + "%";
  const PALETTE = ["#f5b301", "#3dd6c3", "#e5484d", "#c8ccd6", "#c98a5e", "#9a8cf5",
    "#7cc95e", "#f07ac0", "#5eb8f0", "#d6c25a"];
  const active = P.housemates.filter((h) => h.status === "active");
  const byName = Object.fromEntries(P.housemates.map((h) => [h.name, h]));

  /* ---------- badges + banner ---------- */
  const badges = [];
  if (P.placeholder) badges.push(["DEMO — PRIOR PREDICTIVE, NOT REAL INFERENCE", "demo"]);
  badges.push([`precision: ${P.precision}`, "warn"]);
  badges.push([P.rhat_max == null ? "rhat: n/a" : `rhat max: ${P.rhat_max}`,
    P.rhat_max != null && P.rhat_max < 1.01 ? "ok" : "warn"]);
  const genMs = P.generated_at ? Date.now() - new Date(P.generated_at) : null;
  const genDays = genMs == null ? null : genMs / 864e5;
  badges.push([genDays == null ? "generated: ?" :
    `updated ${genDays < 1 ? "today" : genDays.toFixed(0) + "d ago"}`, genDays != null && genDays > 9 ? "warn" : ""]);
  $("badges").innerHTML = badges.map(([t, c]) =>
    `<span class="badge ${c}">${t}</span>`).join("");

  const flagged = active.filter((h) => h.gambit_flag === 1).map((h) => h.name);
  if (flagged.length) {
    $("gambitBanner").classList.add("on");
    $("gambitBanner").insertAdjacentHTML("beforeend",
      `<div style="margin-top:4px;color:var(--muted)">Flagged: ${flagged.join(", ")}</div>`);
  }

  /* ---------- podium ---------- */
  const slots = [["w1", "1", P.podium.winner, "winner"],
  ["w2", "2", P.podium.runner_up, "runner-up"],
  ["w3", "3", P.podium.second_runner_up, "2nd runner-up"]];
  $("podium").innerHTML = slots.map(([cls, n, s, lbl]) => {
    const hm = byName[s.name] || {};
    const ties = (hm.statistical_tie_with || []);
    return `<div class="slot ${cls}">
      <div class="medal">${n}</div>
      <div class="who"><div class="lbl">${lbl}</div><div class="nm">${s.name}</div>
        <div class="tie">${ties.length ? "statistical tie w/ " + ties.join(", ") :
        (hm.gambit_flag === 1 ? "gambit — cannot win the prize" : "")}</div></div>
      <div class="prob"><div class="v">${pct(s.prob, 0)}</div><div class="tie">slot prob</div></div>
    </div>`;
  }).join("");

  /* ---------- chips ---------- */
  const chips = [...active].sort((a, b) => b.p_rank_1 - a.p_rank_1);
  $("chips").innerHTML = chips.map((h) => {
    const tied = (h.statistical_tie_with || []).length ? " ≈" : "";
    return `<div class="chip-row ${h.gambit_flag ? "gambit" : ""}" title="${tied ? "statistical tie with " + h.statistical_tie_with.join(", ") : ""}">
      <span class="nm">${h.name}${tied}</span>
      ${h.gambit_flag ? '<span class="g">GAMBIT</span>' : ""}
      <span class="pill ${h.gambit_flag ? "dim" : ""}"><b>${pct(h.p_rank_1, 0)}</b> #1</span>
      <span class="pill"><b>${pct(h.p_top3, 0)}</b> T3</span>
      <span class="pill"><b>${pct(h.p_top5, 0)}</b> T5</span>
    </div>`;
  }).join("");

  /* ---------- trend + at-risk ---------- */
  const T = P.trend_projection || {};
  $("trendList").innerHTML = (T.podium || []).map((n, i) =>
    `<li><span class="pos">${i + 1}</span><span>${n}</span></li>`).join("");
  $("trendNote").textContent = T.method ? `${T.method} → week ${T.horizon_week}. ${T.uncertainty}. Secondary readout — never merged into the headline snapshot.` : "";

  const risk = P.at_risk || [];
  $("risk").innerHTML = risk.length ? risk.map((r) => `
    <div class="row"><span>${r.name}${r.nominated ? "" : ' <span class="pill dim">former</span>'}</span>
      <span class="hz">×${r.relative_hazard.toFixed(2)}</span>
      <span class="bar"><i style="width:${Math.min(100, (r.relative_hazard / 1.6) * 100).toFixed(0)}%"></i></span>
    </div>`).join("") : '<div class="empty">No nominations recorded this week.</div>';

  /* ---------- pairwise ---------- */
  const pA = $("pairA"), pB = $("pairB");
  const namesA = chips.map((h) => h.name);
  pA.innerHTML = pB.innerHTML = namesA.map((n) => `<option>${n}</option>`).join("");
  pB.selectedIndex = Math.min(1, namesA.length - 1);
  function renderPair() {
    const a = pA.value, b = pB.value;
    if (a === b || !P.pairwise || !P.pairwise[a]) { $("pairP").textContent = "—"; return; }
    const p = P.pairwise[a][b];
    const fav = p >= 0.5 ? a : b;
    $("pairP").textContent = pct(p, 0);
    $("pairCap").textContent = `P(${a} finishes above ${b})`;
    const diff = Math.round(100 * ((byName[a].win_prob_median || 0) - (byName[b].win_prob_median || 0)));
    $("pairDiff").innerHTML = `${fav} favoured · Δmedian = ${diff > 0 ? "+" : ""}${diff} pp`;
  }
  pA.onchange = pB.onchange = renderPair;
  renderPair();

  /* ---------- roster ---------- */
  const initials = (n) => n.split(/\s+/).map((w) => w[0]).slice(0, 2).join("").toUpperCase();
  const color = (n) => PALETTE[[...n].reduce((s, c) => s + c.charCodeAt(0), 0) % PALETTE.length];
  function avatarHTML(hm, cls) {
    const fallback = `<div class="avatar ${cls || ""}" style="background:${color(hm.name)}">${initials(hm.name)}</div>`;
    if (!hm.photo) return fallback;
    return `<div class="avatar ${cls || ""}"><img src="${hm.photo}" alt=""
      onerror="this.parentNode.outerHTML=${JSON.stringify(fallback).replace(/"/g, "&quot;")}"></div>`;
  }
  $("roster").innerHTML = P.housemates.map((h) => {
    const st = h.status === "active" ? "active" :
      `${h.status} wk ${h.evicted_week ?? "?"}`;
    return `<div class="hcard ${h.status !== "active" ? "out" : ""}">
      ${avatarHTML(h)}
      <div style="min-width:0"><div class="nm">${h.name}</div>
        <div class="st ${h.status}">${st}</div></div>
      ${h.gambit_flag ? '<span class="g" style="font-size:9px;color:var(--red);margin-left:auto;border:1px solid var(--red);border-radius:2px;padding:1px 4px">G</span>' : ""}
    </div>`;
  }).join("");

  /* ---------- trajectory chart (canvas) ---------- */
  const cv = $("chart"), ctx = cv.getContext("2d");
  let series = [];                    // {name, color, pts:[{w, m, lo, hi}]}
  const top5 = chips.slice(0, 5).map((h) => h.name);
  const extra = new Set();
  const sel = $("addSel");
  sel.innerHTML = namesA.filter((n) => !top5.includes(n))
    .map((n) => `<option>${n}</option>`).join("");
  const photos = {};                  // name -> Image (may fail -> initials)
  P.housemates.forEach((h) => {
    if (!h.photo) return;
    const im = new Image();
    im.onload = () => { photos[h.name] = im; draw(); };
    im.src = h.photo;
  });

  function rebuild() {
    const want = [...top5, ...extra];
    series = want.map((n, i) => {
      const h = byName[n];
      if (!h || !h.history) return null;
      return { name: n, color: PALETTE[i % PALETTE.length],
        pts: h.history.map((p) => ({ w: p.week, m: p.median, lo: p.hdi_89[0], hi: p.hdi_89[1] })) };
    }).filter(Boolean);
    $("legend").innerHTML = series.map((s) =>
      `<span class="lchip" data-n="${s.name}"><span class="sw" style="background:${s.color}"></span>${s.name}</span>`).join("");
    $("legend").querySelectorAll(".lchip").forEach((el) =>
      el.onclick = () => {
        const n = el.dataset.n;
        if (top5.includes(n)) top5.splice(top5.indexOf(n), 1); else extra.delete(n);
        rebuild(); draw();
      });
  }
  rebuild();
  sel.onchange = () => { if (sel.value) { extra.add(sel.value); rebuild(); draw(); sel.selectedIndex = 0; } };

  function draw() {
    const dpr = window.devicePixelRatio || 1;
    const W = cv.clientWidth, H = cv.clientHeight;
    cv.width = W * dpr; cv.height = H * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);
    const padL = 34, padR = 96, padT = 12, padB = 26;
    const iw = W - padL - padR, ih = H - padT - padB;
    if (!series.length || !iw) return;
    const weeks = [...new Set(series.flatMap((s) => s.pts.map((p) => p.w)))].sort((a, b) => a - b);
    const X = (w) => padL + ((w - weeks[0]) / Math.max(1, weeks[weeks.length - 1] - weeks[0])) * iw;
    const Y = (v) => padT + (1 - v) * ih;

    ctx.font = "10px 'IBM Plex Mono', monospace"; ctx.fillStyle = "#5a6175";
    for (let g = 0; g <= 4; g++) {
      const v = g / 4, y = Y(v);
      ctx.strokeStyle = "#1b2130"; ctx.beginPath();
      ctx.moveTo(padL, y); ctx.lineTo(W - padR, y); ctx.stroke();
      ctx.fillText(v * 100 + "%", 6, y + 3);
    }
    weeks.forEach((w) => {
      const x = X(w);
      ctx.fillText("W" + w, x - 6, H - 8);
      ctx.strokeStyle = "#151a26"; ctx.beginPath();
      ctx.moveTo(x, padT); ctx.lineTo(x, padT + ih); ctx.stroke();
    });

    series.forEach((s) => {
      // 89% CrI band
      ctx.beginPath();
      s.pts.forEach((p, i) => i ? ctx.lineTo(X(p.w), Y(p.hi)) : ctx.moveTo(X(p.w), Y(p.hi)));
      for (let i = s.pts.length - 1; i >= 0; i--) ctx.lineTo(X(s.pts[i].w), Y(s.pts[i].lo));
      ctx.closePath(); ctx.globalAlpha = 0.16; ctx.fillStyle = s.color; ctx.fill();
      ctx.globalAlpha = 1;
      // median line
      ctx.strokeStyle = s.color; ctx.lineWidth = 2; ctx.beginPath();
      s.pts.forEach((p, i) => i ? ctx.lineTo(X(p.w), Y(p.m)) : ctx.moveTo(X(p.w), Y(p.m)));
      ctx.stroke(); ctx.lineWidth = 1;
      // end marker + photo/initials avatar + name label (clamped, never clipped)
      const last = s.pts[s.pts.length - 1], lx = X(last.w), ly = Y(last.m);
      ctx.fillStyle = s.color; ctx.beginPath(); ctx.arc(lx, ly, 3.2, 0, 7); ctx.fill();
      const r = 8, cx = Math.min(Math.max(lx + 14, padL + r + 2), W - r - 2);
      const iy = Math.min(Math.max(ly - 9, padT + r + 2), H - padB - r - 14);
      ctx.beginPath(); ctx.arc(cx, iy, r, 0, 7);
      ctx.fillStyle = "#0b0d12"; ctx.fill(); ctx.strokeStyle = s.color; ctx.stroke();
      const im = photos[s.name];
      if (im) { ctx.save(); ctx.beginPath(); ctx.arc(cx, iy, r - 1, 0, 7); ctx.clip();
        ctx.drawImage(im, cx - r, iy - r, 2 * r, 2 * r); ctx.restore(); }
      else { ctx.fillStyle = s.color; ctx.font = "600 7.5px Archivo, sans-serif";
        ctx.textAlign = "center"; ctx.textBaseline = "middle";
        ctx.fillText(initials(s.name), cx, iy + 0.5); }
      ctx.font = "600 10px Archivo, sans-serif";
      const tw = ctx.measureText(s.name).width;
      const tx = Math.min(Math.max(cx, tw / 2 + 2), W - tw / 2 - 2);
      ctx.textAlign = "center"; ctx.fillStyle = "#ece9e1";
      ctx.fillText(s.name, tx, iy + r + 12);
      ctx.textAlign = "left"; ctx.textBaseline = "alphabetic";
      ctx.font = "10px 'IBM Plex Mono', monospace";
    });
  }
  new ResizeObserver(draw).observe(cv);
  draw();

  /* ---------- footer ---------- */
  $("foot").innerHTML = `
    <b>Methodology.</b> Zero-inflated negative-binomial engagement counts with Cox
    eviction frailty, fit locally (PyMC, 4 chains) per candidate; three BMA-weighted
    variants; 10,000 Dirichlet-multinomial posterior-predictive draws → medians,
    89% credible bands, slot probabilities. Gambit pair: P(#1) ≡ 0, prize-disqualified.
    Trend podium is a secondary β-projection, never merged into the headline.
    <b>Limitation.</b> Cross-blog engagement cannot be deduplicated at $0 — the CPI is
    a correlated engagement index; win probabilities are model shares, not vote counts.
    <b>Status.</b> ${P.placeholder ? "DEMO: numbers shown are prior-predictive placeholders (no data information) — the MCMC gate has not yet certified a run." :
    `Live run · precision ${P.precision} · R-hat ${P.rhat_max}.`}
    Probabilities ≠ votes.`;
})();
