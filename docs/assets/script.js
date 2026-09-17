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

  /* ---------- shared avatar helpers (defined before any renderer uses them) ---------- */
  const initials = (n) => n.split(/\s+/).map((w) => w[0]).slice(0, 2).join("").toUpperCase();
  const color = (n) => PALETTE[[...n].reduce((s, c) => s + c.charCodeAt(0), 0) % PALETTE.length];
  function avatarHTML(hm, cls) {
    const fallback = `<div class="avatar ${cls || ""}" style="background:${color(hm.name)}">${initials(hm.name)}</div>`;
    if (!hm.photo) return fallback;
    return `<div class="avatar ${cls || ""}"><img src="${hm.photo}" alt=""
      onerror="this.parentNode.outerHTML=${JSON.stringify(fallback).replace(/"/g, "&quot;")}"></div>`;
  }

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

  /* ---------- freshness line + share ---------- */
  const nextSat = (() => { const d = new Date(); d.setDate(d.getDate() + ((6 - d.getDay() + 7) % 7 || 7)); return d; })();
  $("fresh").textContent = `refresh: every Saturday after the weekly run · next update ` +
    nextSat.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
  $("shareBtn").onclick = async () => {
    if (navigator.share) { try { await navigator.share({ title: document.title, url: location.href }); return; } catch (e) { /* user cancelled */ } }
    try { await navigator.clipboard.writeText(location.href);
      $("shareBtn").textContent = "Link copied"; setTimeout(() => ($("shareBtn").textContent = "Share"), 1600);
    } catch (e) { /* clipboard unavailable */ }
  };

  const flagged = active.filter((h) => h.gambit_flag === 1).map((h) => h.name);
  if (flagged.length) {
    $("gambitBanner").classList.add("on");
    $("gambitBanner").insertAdjacentHTML("beforeend",
      `<div style="margin-top:4px;color:var(--muted)">Flagged: ${flagged.join(", ")}</div>`);
  }

  /* ---------- hero headline ---------- */
  const nowWeek = Math.max(1, ...active.flatMap((h) => (h.history || []).map((p) => p.week)));
  const W0 = P.podium.winner, W0hm = byName[W0.name] || {};
  $("hero").innerHTML = `${avatarHTML(W0hm, "big")}
    <div style="min-width:0"><div class="k">The model's call after week ${nowWeek}</div>
      <div class="line">${W0.name} <span class="pc">${pct(W0.prob, 0)}</span> to win</div>
      <div class="muted">Runner-up projection: ${P.podium.runner_up.name} · from 10,000 season simulations ·
        ${genDays != null && genDays < 1 ? "updated today" : "updated " + (genDays == null ? "?" : Math.round(genDays) + "d ago")}</div></div>`;

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
  // literal 3D podium with faces, ordered by position
  const TP = T.podium || [];
  const heights = ["84px", "56px", "42px"], cls3d = ["p1", "p2", "p3"];
  $("tp3d").innerHTML = TP.slice(0, 3).map((n, i) => {
    const hm = byName[n] || {};
    return `<div class="box ${cls3d[i]}" style="height:${heights[i]}">
      <div class="top"></div><div class="side"></div>
      <div class="face">${avatarHTML(hm)}<div class="nm">${n}</div><div class="num">${i + 1}</div></div>
    </div>`;
  }).join("");
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
  let hoverIdx = -1;                  // hovered series index (-1 = none); read inside draw()
  let series = [];                    // {name, color, pts:[{w, m, lo, hi}]}
  let X = () => 0, Y = () => 0;       // week/value -> canvas coords (refreshed each draw; shared with hover)
  const top5 = chips.slice(0, 5).map((h) => h.name);
  const extra = new Set();
  const sel = $("addSel");
  sel.innerHTML = namesA.filter((n) => !top5.includes(n))
    .map((n) => `<option>${n}</option>`).join("");

  function rebuild() {
    const want = [...top5, ...extra];
    series = want.map((n, i) => {
      const h = byName[n];
      if (!h || !h.history) return null;
      return { name: n, color: PALETTE[i % PALETTE.length],
        pts: h.history.map((p) => ({ w: p.week, m: p.median, lo: p.hdi_89[0], hi: p.hdi_89[1] })) };
    }).filter(Boolean);
    $("legend").innerHTML = series.map((s) => {
      const hm = byName[s.name] || {};
      const av = hm.photo
        ? `<img class="lav" src="${hm.photo}" alt="" onerror="this.remove()">`
        : `<span class="lav" style="display:inline-flex;align-items:center;justify-content:center;background:${s.color};color:#0b0d12;font-weight:700;font-size:8px">${initials(s.name)}</span>`;
      return `<span class="lchip" data-n="${s.name}" title="Click to remove">
        <span class="sw" style="background:${s.color}"></span>${av}${s.name}</span>`;
    }).join("");
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
    X = (w) => padL + ((w - weeks[0]) / Math.max(1, weeks[weeks.length - 1] - weeks[0])) * iw;
    Y = (v) => padT + (1 - v) * ih;

    ctx.font = "10px 'IBM Plex Mono', monospace"; ctx.fillStyle = "#5a6175";
    for (let g = 0; g <= 4; g++) {
      const v = g / 4, y = Y(v);
      ctx.strokeStyle = "#1b2130"; ctx.beginPath();
      ctx.moveTo(padL, y); ctx.lineTo(W - padR, y); ctx.stroke();
    }
    weeks.forEach((w) => {
      const x = X(w);
      ctx.strokeStyle = "#151a26"; ctx.beginPath();
      ctx.moveTo(x, padT); ctx.lineTo(x, padT + ih); ctx.stroke();
    });

    series.forEach((s, si) => {
      const focus = hoverIdx === -1 || hoverIdx === si;   // hovered line pops, others fade
      ctx.globalAlpha = focus ? 1 : 0.22;
      // 89% CrI band
      ctx.beginPath();
      s.pts.forEach((p, i) => i ? ctx.lineTo(X(p.w), Y(p.hi)) : ctx.moveTo(X(p.w), Y(p.hi)));
      for (let i = s.pts.length - 1; i >= 0; i--) ctx.lineTo(X(s.pts[i].w), Y(s.pts[i].lo));
      ctx.closePath(); ctx.globalAlpha = focus ? 0.16 : 0.05; ctx.fillStyle = s.color; ctx.fill();
      ctx.globalAlpha = focus ? 1 : 0.22;
      // median line (bolder for clarity)
      ctx.strokeStyle = s.color; ctx.lineWidth = focus && hoverIdx === si ? 3.5 : 3; ctx.beginPath();
      s.pts.forEach((p, i) => i ? ctx.lineTo(X(p.w), Y(p.m)) : ctx.moveTo(X(p.w), Y(p.m)));
      ctx.stroke(); ctx.lineWidth = 1;
      // end marker + color-keyed name label (no avatar on the line — photos live in the legend)
      const last = s.pts[s.pts.length - 1], lx = X(last.w), ly = Y(last.m);
      ctx.fillStyle = s.color; ctx.beginPath(); ctx.arc(lx, ly, 4.5, 0, 7); ctx.fill();
      ctx.font = "600 14px Archivo, sans-serif";
      const tw = ctx.measureText(s.name).width;
      const tx = Math.min(lx + 10, W - tw - 4);
      const ty = Math.min(Math.max(ly + 5, padT + 14), H - padB - 4);
      ctx.fillStyle = s.color; ctx.textAlign = "left"; ctx.textBaseline = "alphabetic";
      ctx.fillText(s.name, tx, ty);
      ctx.font = "10px 'IBM Plex Mono', monospace";
    });
    ctx.globalAlpha = 1;
  }
  new ResizeObserver(draw).observe(cv);
  draw();

  /* ---------- hover: tooltip + line focus (annotations live here, not on the canvas) ---------- */
  function onMove(ev) {
    const rect = cv.getBoundingClientRect();
    const mx = ev.clientX - rect.left, my = ev.clientY - rect.top;
    let best = -1, bestD = 28 * 28;                       // generous 28px hover radius
    series.forEach((s, si) => s.pts.forEach((p) => {
      const dx = X(p.w) - mx, dy = Y(p.m) - my, d = dx * dx + dy * dy;
      if (d < bestD) { bestD = d; best = si; }
    }));
    if (best !== hoverIdx) { hoverIdx = best; draw(); }
    if (best === -1) { tip.style.opacity = 0; return; }
    const s = series[best];
    let bp = s.pts[0], bd = 1e9;
    s.pts.forEach((p) => { const d = Math.abs(X(p.w) - mx); if (d < bd) { bd = d; bp = p; } });
    tip.innerHTML = `<b style="color:${s.color}">${s.name}</b> · wk ${bp.w}<br>` +
      `median ${pct(bp.m)} · 89% CrI ${pct(bp.lo)}–${pct(bp.hi)}`;
    const tw2 = cv.clientWidth, px = Math.min(Math.max(mx + 14, 8), tw2 - 190);
    tip.style.left = px + "px";
    tip.style.top = Math.max(4, my - 46) + "px";
    tip.style.opacity = 1;
  }
  const tip = document.createElement("div");
  tip.id = "chartTip";
  cv.parentNode.appendChild(tip);
  const onLeave = () => { hoverIdx = -1; tip.style.opacity = 0; draw(); };
  cv.addEventListener("mousemove", onMove);
  cv.addEventListener("mouseleave", onLeave);
  cv.addEventListener("touchstart", (e) => onMove(e.touches[0]), { passive: true });

  /* ---------- prediction vs outcome tracker ---------- */
  fetch("track_record.json", { cache: "no-store" })
    .then((r) => (r.ok ? r.json() : Promise.reject()))
    .then((TR) => {
      if (!TR.weeks || !TR.weeks.length) return;
      $("trackPanel").style.display = "";
      $("track").innerHTML = TR.weeks.map((t) => `
        <div class="trow"><span class="wk">Wk ${t.week}</span>
          <span>called <b>${t.predicted_winner}</b> (${pct(t.predicted_prob, 0)}) · evicted <b>${t.evicted}</b></span>
          <span class="${t.hit ? "ok" : "miss"}">${t.hit ? "HIT" : "MISS"}</span>
          <span class="wk" title="Brier score on predicted-vs-actual eviction outcome; lower is better">Brier ${t.brier != null ? t.brier.toFixed(3) : "—"}</span>
        </div>`).join("") +
        (TR.summary ? `<div class="trow" style="border:none"><span class="wk">season to date</span>
          <span>${TR.summary.hits}/${TR.summary.scored} called winners survived their week · mean Brier ${TR.summary.mean_brier.toFixed(3)}</span></div>` : "");
    })
    .catch(() => { /* no track_record.json yet — panel stays hidden */ });

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
