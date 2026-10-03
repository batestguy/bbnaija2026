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
  // roster passthrough (photo/exit meta) arrives separately from the standings
  // rows — merge it in so hero/podium/legend/roster resolve photos & exit weeks
  const rosterMeta = P.roster || {};
  const byName = Object.fromEntries(P.housemates.map((h) =>
    [h.name, { ...rosterMeta[h.name], ...h }]));
  const isPollEngine = P.engine && P.engine.name === "poll_matrix";

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
  // precision is an MCMC-era run-quality label; the poll engine has no lite
  // mode (spec §9), so the badge is suppressed there like the R-hat badge.
  if (!isPollEngine) badges.push([`precision: ${P.precision}`, "warn"]);
  // R-hat is an MCMC convergence diagnostic — meaningless for the bootstrap
  // poll engine; badge suppressed there so retired-model language stays off
  // the page (owner: "no more Bayesian, plus R-hat too").
  if (!isPollEngine) badges.push([P.rhat_max == null ? "rhat: n/a" : `rhat max: ${P.rhat_max}`,
    P.rhat_max != null && P.rhat_max < 1.01 ? "ok" : "warn"]);
  const genMs = P.generated_at ? Date.now() - new Date(P.generated_at) : null;
  const genDays = genMs == null ? null : genMs / 864e5;
  badges.push([genDays == null ? "generated: ?" :
    `updated ${genDays < 1 ? "today" : genDays.toFixed(0) + "d ago"}`, genDays != null && genDays > 9 ? "warn" : ""]);
  $("badges").innerHTML = badges.map(([t, c]) =>
    `<span class="badge ${c}">${t}</span>`).join("");

  /* ---------- freshness line + share ---------- */
  // (E4.2 note: panels below branch on engine — poll_matrix remaps bands to
  // bootstrap CIs, risk to lowest-share, and drops MCMC-only panels.)
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

  /* ---------- auto-finalists strip (spec §6; poll engine only) ---------- */
  const autoStrip = $("autoFinalists");
  if (autoStrip) {
    if (isPollEngine && (P.auto_finalists || []).length) {
      autoStrip.style.display = "";
      autoStrip.insertAdjacentHTML("beforeend",
        (P.auto_finalists || []).map((g) => {
          const hm = byName[g.name] || g;
          return `<div class="hcard">${avatarHTML(hm)}
            <div style="min-width:0"><div class="nm">${g.name}</div>
            <div class="st active">auto-finalist — no poll numbers</div></div></div>`;
        }).join(""));
    } else {
      autoStrip.style.display = "none";
    }
  }

  /* ---------- hero: the winner alone, 64px photo (owner 09-27, clarified:
     runner-ups belong to the podium block below with their pictures there,
     not beside her at the top of the page) ---------- */
  const nowWeek = Math.max(1, ...active.flatMap((h) => (h.history || []).map((p) => p.week)));
  const W0 = P.podium.winner, W0hm = byName[W0.name] || {};
  const basis = isPollEngine ? "aggregated fan-poll shares" : "10,000 season simulations";
  const runnerUpName = (P.podium.runner_up || {}).name;
  $("hero").innerHTML = `${avatarHTML(W0hm, "big")}
    <div style="min-width:0"><div class="k">The engine's call after week ${nowWeek}</div>
      <div class="line">${W0.name} <span class="pc">${pct(W0.prob, 0)}</span> to win</div>
      <div class="muted">Runner-up projection: ${runnerUpName || "—"} · from ${basis} ·
        ${genDays != null && genDays < 1 ? "updated today" : "updated " + (genDays == null ? "?" : Math.round(genDays) + "d ago")}</div></div>`;

  /* ---------- podium ---------- */
  // 2026-09-26: slot prob + the housemate's aggregated share side by side —
  // three identical slot probs (86/86/86) read as nonsense alone; the share
  // column is the hand-checkable number fans recognise from the polls.
  const slots = [["w1", "1", P.podium.winner, "winner"],
  ["w2", "2", P.podium.runner_up, "runner-up"],
  ["w3", "3", P.podium.second_runner_up, "2nd runner-up"]].filter(([, , s]) => s && s.name);
  $("podium").innerHTML = slots.map(([cls, n, s, lbl]) => {
    const hm = byName[s.name] || {};
    const ties = (hm.statistical_tie_with || []);
    const sharePct = hm.share != null ? pct(hm.share, 1) : null;
    // 2026-09-27: raw slot probs read identical (top-3 set ⇒ 86/86/86) and
    // looked like a bug. Winner card keeps its win prob; runner-up cards show
    // P(top-3) — the claim that slot actually makes. Poll share stays as the
    // hand-checkable number either way.
    const slotProb = lbl === "winner" ? s.prob : (hm.p_top3 != null ? hm.p_top3 : s.prob);
    return `<div class="slot ${cls}">
      <div class="medal">${n}</div>
      ${avatarHTML(hm)}
      <div class="who"><div class="lbl">${lbl}</div><div class="nm">${s.name}</div>
        <div class="tie">${sharePct ? "poll share " + sharePct : ""}${ties.length ? " · tie w/ " + ties.join(", ") : ""}</div></div>
      <div class="prob"><div class="v">${pct(slotProb, 0)}</div><div class="tie">${lbl === "winner" ? "to win" : "P(top-3)"}</div></div>
    </div>`;
  }).join("");

  /* ---------- chips ---------- */
  const chips = [...active].sort((a, b) => b.p_rank_1 - a.p_rank_1);
  $("chips").innerHTML = chips.map((h) => {
    const tied = (h.statistical_tie_with || []).length ? " ≈" : "";
    const momPill = isPollEngine && h.momentum != null
      ? `<span class="pill dim"><b>${h.momentum > 0 ? "+" : ""}${(h.momentum * 100).toFixed(1)}</b> mom</span>`
      : "";
    const carriedTag = isPollEngine && h.carried ? ' <span class="pill dim">carried</span>' : "";
    return `<div class="chip-row ${h.gambit_flag ? "gambit" : ""}" title="${tied ? "statistical tie with " + h.statistical_tie_with.join(", ") : ""}">
      <span class="nm">${h.name}${tied}${carriedTag}</span>
      ${h.gambit_flag ? '<span class="g">GAMBIT</span>' : ""}
      <span class="pill ${h.gambit_flag ? "dim" : ""}"><b>${pct(h.p_rank_1, 0)}</b> #1</span>
      <span class="pill"><b>${pct(h.p_top3, 0)}</b> T3</span>
      <span class="pill"><b>${pct(h.p_top5, 0)}</b> T5</span>
      ${momPill}
    </div>`;
  }).join("");
  const chipsNote = $("chipsNote");
  if (chipsNote && isPollEngine) {
    chipsNote.style.display = "";
    chipsNote.textContent = "share = P(win) · mom = Δ share week-over-week · carried = no poll coverage this week, inherited last week's share";
  }

  /* ---------- trend + at-risk ---------- */
  const trendPanel = $("trendPanel");
  if (isPollEngine) {
    // MCMC-only panels dropped (spec §9): no β-trend exists in the poll engine
    if (trendPanel) trendPanel.style.display = "none";
  }
  const T = P.trend_projection || {};
  $("trendList").innerHTML = (T.podium || []).map((n, i) =>
    `<li><span class="pos">${i + 1}</span><span>${n}</span></li>`).join("");
  // race-to-finale strip: runners on a momentum track, leading runner closest to the checkered finale
  const TP = T.podium || [];
  const fractions = [0.86, 0.62, 0.38];
  const ring = ["w1", "w2", "w3"];
  const ringColor = { w1: "var(--gold)", w2: "var(--silver)", w3: "var(--bronze)" };
  $("race").innerHTML = TP.slice(0, 3).map((n, i) => {
    const hm = byName[n] || {};
    return `<div class="runner" style="left:${Math.round(fractions[i] * 100)}%">
      ${avatarHTML(hm, ring[i])}
      <div class="nm">${n}</div><div class="num">${i + 1}</div>
    </div>`;
  }).join("");
  $("race").insertAdjacentHTML("beforeend",
    '<div class="lane"><i></i></div><div class="finish" title="Finale — week 10"></div>');
  const headWinner = P.podium.winner.name, trendWinner = TP[0];
  const greek = (s) => s.replace(/beta_i/g, "βᵢ").replace(/beta/g, "β")
    .replace(/sigma_week/g, "σ_week").replace(/->/g, "→");
  // bold mini-heading: state the basis, flag disagreement with the headline
  const tnH = $("trendNoteH");
  if (trendWinner && trendWinner !== headWinner) {
    tnH.innerHTML = `BASED ON MOMENTUM ONLY — DISAGREES WITH HEADLINE (SIM KEEPS ${headWinner.toUpperCase()} AHEAD)`;
    tnH.style.color = "var(--red)";
  } else {
    tnH.innerHTML = `BASED ON MOMENTUM → WEEK ${T.horizon_week || "?"}`;
    tnH.style.color = "var(--teal)";
  }
  let noteTxt = T.method ? greek(T.method) + ` → week ${T.horizon_week}. ` : "";
  if (trendWinner && trendWinner !== headWinner) {
    noteTxt = `This is a momentum-only what-if: it extrapolates engagement slopes and ignores eviction risk and ` +
      `current level; the headline podium stays authoritative. ` + noteTxt;
  }
  noteTxt += T.uncertainty ? greek(T.uncertainty) + ". Secondary readout — never merged into the headline." : "";
  $("trendNote").textContent = noteTxt;

  const risk = P.at_risk || [];
  const riskTag = $("riskTag");
  if (riskTag && isPollEngine) riskTag.textContent = "lowest share · * = bottom-N flag";
  $("risk").innerHTML = risk.length ? risk.map((r) => {
    if (isPollEngine) {
      return `<div class="row"><span>${r.name}${r.bottom_n_flag ? ' <span class="pill dim">*</span>' : ""}</span>
        <span class="hz">${(r.share * 100).toFixed(1)}%</span>
        <span class="bar"><i style="width:${Math.max(4, Math.min(100, r.share * 400)).toFixed(0)}%"></i></span>
      </div>`;
    }
    return `<div class="row"><span>${r.name}${r.nominated ? "" : ' <span class="pill dim">former</span>'}</span>
      <span class="hz">×${r.relative_hazard.toFixed(2)}</span>
      <span class="bar"><i style="width:${Math.min(100, (r.relative_hazard / 1.6) * 100).toFixed(0)}%"></i></span>
    </div>`;
  }).join("") : '<div class="empty">No nominations recorded this week.</div>';

  /* ---------- pairwise ---------- */
  const pA = $("pairA"), pB = $("pairB");
  const namesA = chips.map((h) => h.name);
  pA.innerHTML = pB.innerHTML = namesA.map((n) => `<option>${n}</option>`).join("");
  pB.selectedIndex = Math.min(1, namesA.length - 1);
  function renderPair() {
    const a = pA.value, b = pB.value;
    if (a === b || !P.pairwise || !P.pairwise[a]) { $("pairP").textContent = "—"; return; }
    const p = P.pairwise[a][b];
    if (p == null) { $("pairP").textContent = "—"; return; }
    const fav = p >= 0.5 ? a : b;
    $("pairP").textContent = pct(p, 0);
    $("pairCap").textContent = `P(${a} finishes above ${b})`;
    if (isPollEngine) {
      // engine emits the full P(A>B) map from bootstrap replicates
      const pba = P.pairwise[b] ? P.pairwise[b][a] : null;
      $("pairDiff").innerHTML = `${fav} favoured · P(${b}>${a}) = ${pba == null ? "—" : pct(pba, 0)}`;
    } else {
      const diff = Math.round(100 * ((byName[a].win_prob_median || 0) - (byName[b].win_prob_median || 0)));
      $("pairDiff").innerHTML = `${fav} favoured · Δmedian = ${diff > 0 ? "+" : ""}${diff} pp`;
    }
  }
  pA.onchange = pB.onchange = renderPair;
  renderPair();

  /* ---------- roster ---------- */
  // 2026-09-27: full 24-person roster — evicted/walked/DQ housemates stay on
  // the board as blurred cards (owner: "include them but shade or blur").
  // P.housemates carries only share-eligible actives, so eliminated names are
  // rebuilt from the roster passthrough (exit_type drives the status label).
  const exited = Object.entries(rosterMeta)
    .filter(([n]) => !byName[n])
    .map(([n, m]) => ({ name: n, status: m.exit_type || "evicted",
      photo: m.photo, exit_week: m.exit_week }));
  // active cards go through the merged rows so their photos resolve too
  const fullRoster = [...P.housemates.map((h) => byName[h.name] || h), ...exited]
    .sort((a, b) => ((a.status === "active" ? 0 : 1) - (b.status === "active" ? 0 : 1))
      || ((a.exit_week ?? 99) - (b.exit_week ?? 99))
      || a.name.localeCompare(b.name));
  $("roster").innerHTML = fullRoster.map((h) => {
    const st = h.status === "active" ? "active" :
      `${h.status} wk ${h.exit_week ?? "?"}`;
    return `<div class="hcard ${h.status !== "active" ? "out" : ""}" title="${h.status !== "active" ? "Exited the house — hover to sharpen" : ""}">
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
  let yMax = 1;                       // tight y-axis top, recomputed per draw (see draw())
  let finalX = {};                    // name -> dodged end-marker x (position-dodge: each series gets its
                                      // own lane in the final-week gutter; the axis widens to make room)
  const imgCache = {};                // name -> Image for the on-chart photo chips
  function getPhoto(name) {
    if (imgCache[name] !== undefined) return imgCache[name];
    const hm = byName[name];
    if (!hm || !hm.photo) { imgCache[name] = null; return null; }
    const im = new Image();
    im.onload = () => draw();          // repaint once the face arrives
    im.onerror = () => { im.failed = true; draw(); };   // fall back to initials
    im.src = hm.photo;
    imgCache[name] = im;
    return im;
  }
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
    // poll engine may emit ci_89 as the band twin of hdi_89 — accept both
    series.forEach((s) => { if (!s.pts.some((p) => p.hi != null)) s.pts = s.pts.map((p) => ({ ...p, lo: p.lo ?? 0, hi: p.hi ?? 0 })); });
    // chart key — explains dot-vs-whisker encoding in plain words (09-27:
    // owner found the point/interval pairing confusing without a label)
    $("legend").innerHTML = `<span class="chart-key" title="The dot is the aggregated share; the capped line through it is the 89% bootstrap interval">
      <span class="key-line"><i class="key-whisk"></i><i class="key-dot"></i></span>
      dot = share · whisker = 89% interval — end markers are side-by-side (dodged); the thin leader ties each back to its line — click a name to remove it
    </span>` + series.map((s) => {
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
    const padL = 40, padR = 30, padT = 12, padB = 26;
    const iw = W - padL - padR, ih = H - padT - padB;
    if (!series.length || !iw) return;
    // x-domain = plotted weeks + ONE runway slot for the upcoming week.
    // Owner 09-27 (revised): wk 8 showed as an empty tick (cold-start
    // histories only carry wk-9 points) and read as missing data — window
    // weeks with no plotted rows stay OFF the axis; the next week (wk 10,
    // finale) gets a slot so the runway to the finale is visible.
    const lastWk = Math.max(...series.flatMap((s) => s.pts.map((p) => p.w)));
    const weeks = [...new Set([...series.flatMap((s) => s.pts.map((p) => p.w)),
      (P.week ?? lastWk) + 1])].sort((a, b) => a - b);
    // single-week history (cold start): pad the x-domain one week each side so
    // the point renders centred instead of an empty axis
    const wLo = weeks[0] - (weeks.length < 2 ? 1 : 0);
    const wHi = weeks[weeks.length - 1] + (weeks.length < 2 ? 1 : 0);
    // dodge gutter (position_dodge equivalent, 09-27): the final-week lane gets
    // (n-1)*SLOT px of side-by-side room by WIDENING the week domain — the axis
    // itself grows, the linear scale is untouched, nothing is capped/truncated.
    const SLOT = 34;                                   // px per dodge lane (photo chip 28 + air)
    const nSer = series.length;
    const spread = (nSer - 1) * SLOT;
    const pxPerWeek0 = iw / Math.max(1, wHi - wLo);
    const gutterWk = nSer > 1 ? (spread / 2) / pxPerWeek0 : 0;
    const wLoD = wLo - gutterWk, wHiD = wHi + gutterWk;
    X = (w) => padL + ((w - wLoD) / Math.max(1e-9, wHiD - wLoD)) * iw;
    // Tight y-axis: baseline stays 0, but the top sits just above the tallest visible
    // interval bound (3% headroom) instead of reserving dead space up to 100% — with
    // medians topping out near 40%, a fixed 0-100% axis wasted most of the plot.
    const dataMax = Math.max(...series.flatMap((s) => s.pts.map((p) => Math.max(p.hi, p.m))));
    yMax = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.8, 1].find((c) => c >= dataMax * 1.03) || 1;
    Y = (v) => padT + (1 - v / yMax) * ih;

    ctx.font = "10px 'IBM Plex Mono', monospace"; ctx.fillStyle = "#5a6175";
    ctx.textAlign = "right";
    for (let g = 0; g <= 4; g++) {
      const v = (g / 4) * yMax, y = Y(v);
      ctx.strokeStyle = "#1b2130"; ctx.beginPath();
      ctx.moveTo(padL, y); ctx.lineTo(W - padR, y); ctx.stroke();
      const pv = Math.round(1000 * v) / 10;   // snap to 0.1% — kills float dust (0.15*100 = 15.000000000000002)
      ctx.fillText((pv % 1 ? pv.toFixed(1) : pv.toFixed(0)) + "%", padL - 5, y + 3);
    }
    ctx.textAlign = "start";
    weeks.forEach((w) => {
      if (weeks.length < 2) return;   // single point: skip gridline at the lone x
      const x = X(w);
      ctx.strokeStyle = "#151a26"; ctx.beginPath();
      ctx.moveTo(x, padT); ctx.lineTo(x, padT + ih); ctx.stroke();
    });
    // explicit week tick labels ("wk 8", "wk 9", ...) under every axis week —
    // the chart was previously unlabeled, so the window's weeks were invisible
    ctx.textAlign = "center"; ctx.fillStyle = "#5a6175";
    weeks.forEach((w) => { ctx.fillText("wk " + w, X(w), H - 8); });
    ctx.textAlign = "start";

    // --- dodge offsets: one lane per series, deterministic ordering ----------
    const mid = (nSer - 1) / 2;
    series.forEach((s, i) => {
      finalX[s.name] = X(s.pts[s.pts.length - 1].w) + (i - mid) * SLOT;
    });

    series.forEach((s, si) => {
      const focus = hoverIdx === -1 || hoverIdx === si;   // hovered line pops, others fade
      ctx.globalAlpha = focus ? 1 : 0.22;
      // hover-only band: one fill at a time — five simultaneous bands overlapped
      // into mud, so the interval shows either as this single hovered band or as
      // the end whiskers, never as five stacked fills (owner feedback 09-27)
      if (hoverIdx === si) {
        ctx.beginPath();
        s.pts.forEach((p, i) => i ? ctx.lineTo(X(p.w), Y(p.hi)) : ctx.moveTo(X(p.w), Y(p.hi)));
        for (let i = s.pts.length - 1; i >= 0; i--) ctx.lineTo(X(s.pts[i].w), Y(s.pts[i].lo));
        ctx.closePath(); ctx.globalAlpha = 0.15; ctx.fillStyle = s.color; ctx.fill();
        ctx.globalAlpha = 1;
      }
      // median line (bolder for clarity)
      ctx.strokeStyle = s.color; ctx.lineWidth = focus && hoverIdx === si ? 3.5 : 3; ctx.beginPath();
      s.pts.forEach((p, i) => i ? ctx.lineTo(X(p.w), Y(p.m)) : ctx.moveTo(X(p.w), Y(p.m)));
      ctx.stroke(); ctx.lineWidth = 1;
      // end marker — dodged whisker + dot + photo chip. The whisker sits in
      // the series' own dodge lane (lane width > chip width ⇒ no overlap);
      // the photo rides ABOVE the whisker top inside that lane, initials
      // fallback if the image fails; the leader ties the lane back to the
      // line's true endpoint so attribution stays honest.
      const last = s.pts[s.pts.length - 1], ly = Y(last.m);
      const lx = finalX[s.name] ?? X(last.w);   // dodged x (position-dodge lane)
      ctx.strokeStyle = s.color; ctx.globalAlpha = focus ? 0.5 : 0.10; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(X(last.w), Y(last.m)); ctx.lineTo(lx, ly); ctx.stroke();   // leader: lane -> true endpoint
      ctx.globalAlpha = focus ? 1 : 0.22;
      // I-shaped whisker (with caps) at the dodged x
      ctx.strokeStyle = s.color; ctx.lineWidth = 2;
      const yHi = Y(last.hi), yLo = Y(last.lo);
      ctx.beginPath(); ctx.moveTo(lx, yHi); ctx.lineTo(lx, yLo); ctx.stroke();
      const capW = 5;   // whisker caps: mark the interval ends
      ctx.beginPath(); ctx.moveTo(lx - capW, yHi); ctx.lineTo(lx + capW, yHi);
      ctx.moveTo(lx - capW, yLo); ctx.lineTo(lx + capW, yLo); ctx.stroke();
      ctx.lineWidth = 1;
      // ringed dot = the estimate (aggregated share)
      ctx.fillStyle = "#0b0d12";
      ctx.beginPath(); ctx.arc(lx, ly, 7, 0, 7); ctx.fill();
      ctx.fillStyle = s.color;
      ctx.beginPath(); ctx.arc(lx, ly, 4.5, 0, 7); ctx.fill();
      // photo chip above the whisker top — inside the series' dodge lane
      const CHIP = 28, yChip = Math.max(2, yHi - CHIP - 6);
      const im = getPhoto(s.name);
      ctx.save();
      ctx.beginPath(); ctx.arc(lx, yChip + CHIP / 2, CHIP / 2, 0, 7);
      ctx.fillStyle = "#0b0d12"; ctx.fill();
      ctx.strokeStyle = (focus || hoverIdx === -1) ? s.color : "#232a3a";
      ctx.lineWidth = 1.5; ctx.stroke();
      ctx.clip();
      if (im && im.complete && im.naturalWidth > 0) {
        ctx.drawImage(im, lx - CHIP / 2, yChip, CHIP, CHIP);
      } else {
        ctx.fillStyle = s.color; ctx.fillRect(lx - CHIP / 2, yChip, CHIP, CHIP);
        ctx.fillStyle = "#0b0d12"; ctx.font = "bold 9px 'Archivo', sans-serif"; ctx.textAlign = "center";
        ctx.fillText(initials(s.name), lx, yChip + CHIP / 2 + 3);
      }
      ctx.restore();
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
    series.forEach((s, si) => s.pts.forEach((p, pi) => {
      // hit-test the DODGED end-marker x for the final point (matches what is
      // drawn); raw week x for earlier points
      const px = pi === s.pts.length - 1 ? (finalX[s.name] ?? X(p.w)) : X(p.w);
      const dx = px - mx, dy = Y(p.m) - my, d = dx * dx + dy * dy;
      if (d < bestD) { bestD = d; best = si; }
    }));
    if (best !== hoverIdx) { hoverIdx = best; draw(); }
    if (best === -1) { tip.style.opacity = 0; return; }
    // hover = the only moment a band is drawn: one fill, zero overlap
    const s = series[best];
    let bp = s.pts[0], bd = 1e9;
    s.pts.forEach((p) => { const d = Math.abs(X(p.w) - mx); if (d < bd) { bd = d; bp = p; } });
    tip.innerHTML = `<b style="color:${s.color}">${s.name}</b> · wk ${bp.w}<br>` +
      `share ${pct(bp.m)} · 89% interval ${pct(bp.lo)}–${pct(bp.hi)}`;
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

  /* ---------- data sources (below the chart) ---------- */
  // Full configured source registry (engine grades keys), 09-27: sources WITH
  // rows in the window are lit; the rest show dimmed so the registry itself
  // is visible — which sources exist, their grade, and which actually fed
  // this run. Straight from predictions.json; nothing hardcoded.
  const DS = P.data_sufficiency || {};
  const grades = (P.engine && P.engine.grades) || {};
  const gradeClass = (g) => (g >= 0.9 ? "gr-a" : g >= 0.6 ? "gr-b" : "gr-c");
  const srcHost = $("sources");
  if (srcHost) {
    const inWin = new Set(DS.sources_reporting || []);
    const registry = Object.keys(grades).sort();
    srcHost.innerHTML = (registry.length ? registry : inWin).map((s) => {
      const g = grades[s];
      const live = inWin.has(s);
      return `<span class="src-chip ${live ? "" : "off"}" title="${live ? "Fed this run" : "Configured but no rows in this window"}">` +
        `<b>${s}</b>${g != null ? `<i class="${gradeClass(g)}">grade ${g.toFixed(1)}</i>` : ""}` +
        `${live ? "" : "<em>no rows in window</em>"}</span>`;
    }).join("") +
      `<span class="src-meta">window wk ${(DS.weeks_in_window || []).join(", ") || "?"} · ` +
      `${DS.full_share_rows ?? "?"} share rows · ${DS.constraint_rows ?? "?"} constraint rows · ${DS.rows_in_window ?? "?"} total</span>`;
  }

  /* ---------- prediction vs outcome tracker ---------- */
  fetch("track_record.json", { cache: "no-store" })
    .then((r) => (r.ok ? r.json() : Promise.reject()))
    .then((TR) => {
      const scorable = (TR.weeks || []).filter((t) => t.scored && t.predicted_winner);
      if (!scorable.length) return;   // tombstone-only log: panel stays hidden
      $("trackPanel").style.display = "";
      $("track").innerHTML = scorable.map((t) => `
        <div class="trow"><span class="wk">Wk ${t.week}</span>
          <span>called <b>${t.predicted_winner}</b> (${pct(t.predicted_prob, 0)}) · evicted <b>${t.evicted}</b></span>
          <span class="${t.hit ? "ok" : "miss"}">${t.hit ? "HIT" : "MISS"}</span>
          <span class="wk" title="Brier score on predicted-vs-actual eviction outcome; lower is better">Brier ${t.brier != null ? t.brier.toFixed(3) : "—"}</span>
        </div>`).join("") +
        (TR.summary && TR.summary.weeks_scored ? `<div class="trow" style="border:none"><span class="wk">season to date</span>
          <span>${TR.summary.winner_survived_hits ?? TR.summary.hits ?? 0}/${TR.summary.weeks_scored} called winners survived their week · mean Brier ${TR.summary.mean_brier != null ? TR.summary.mean_brier.toFixed(3) : "—"}</span></div>` : "");
    })
    .catch(() => { /* no track_record.json yet — panel stays hidden */ });

  /* ---------- footer ---------- */
  $("foot").innerHTML = isPollEngine ? `
    <b>Methodology.</b> Weekly fan-poll observations (bbnaijadaily vote widget,
    hand-logged rows) are aggregated with source-grade, sample-size and recency
    weights; official bottom-N/top-N reports act as constraints; 1,000 bootstrap
    replicates give the 89% intervals, rank probabilities and podium odds.
    Share = win probability — every number is hand-checkable from the poll log.
    Gambit auto-finalists appear in their own strip with no numbers.
    <b>Limitation.</b> Fan polls share the same repeat-votable mechanics and
    recurring voters across sites — treat this as a correlated fan-intensity
    index, not independent one-person-one-vote sampling. Standings numbers are
    shares, never vote counts.
    <b>Status.</b> Live poll-engine run · window weeks
    ${(P.data_sufficiency || {}).weeks_in_window || "?"} · rows ${(P.data_sufficiency || {}).rows_in_window || "?"}.
    Probabilities ≠ votes.` :
    `<b>Methodology.</b> Legacy archived run — retired model, shown only if stale
    legacy products are ever loaded. Current methodology is the poll-matrix
    bootstrap described above.
    <b>Status.</b> ${P.placeholder ? "DEMO: placeholder numbers, not a certified run." :
    `Archived run · precision ${P.precision}.`}
    Probabilities ≠ votes.`;
})();
