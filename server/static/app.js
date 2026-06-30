"use strict";

// --- state ------------------------------------------------------------------
let gameId = null;
let mySeat = null;       // assigned on join; also synced from snapshot.view.me
let playerToken = null;
let ws = null;
let snap = null;
let logLines = [];
let catalog = {};        // card id -> info, for tooltips
let catalogList = [];    // ordered, for the rules modal
let rulesSections = [];
let prevTopKey = null;   // discard top, to animate when it changes
let chatMsgs = [];       // chat history
let me = null;           // /api/me: auth status

const $ = (id) => document.getElementById(id);

// --- bootstrap --------------------------------------------------------------
$("newGameBtn").onclick = () =>
  newGame(parseInt($("numPlayers").value, 10), parseInt($("numHumans").value, 10));
$("rulesBtn").onclick = openRules;
$("nameInput").value = localStorage.getItem("hdu_name") || "";
$("nameInput").onchange = () => localStorage.setItem("hdu_name", $("nameInput").value.trim());
$("chatForm").onsubmit = (e) => {
  e.preventDefault();
  const text = $("chatInput").value.trim();
  if (text && ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "chat", text }));
  $("chatInput").value = "";
};
$("rulesClose").onclick = closeRules;
$("rulesModal").onclick = (e) => { if (e.target.id === "rulesModal") closeRules(); };
document.addEventListener("click", (e) => { if (!e.target.closest(".badge")) hideTip(true); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") { closeRules(); hideTip(true); } });

window.addEventListener("load", async () => {
  loadCatalog();
  await loadAuth();
  try {
    const cfg = await (await fetch("/api/config")).json();
    if (cfg.passcode_required) {
      const el = $("passcode");
      el.hidden = false;
      el.value = localStorage.getItem("hdu_passcode") || "";
    }
  } catch (e) { /* config is best-effort */ }

  if (location.search.includes("login=denied")) setConn("that account isn't allowed", "bad");
  else if (location.search.includes("login=failed")) setConn("sign-in failed", "bad");

  const m = location.hash.match(/game=([\w-]+)/);
  if (m) { gameId = m[1]; joinAndConnect(); }
});

// Pull auth status; render the sign-in control and adapt the name field.
async function loadAuth() {
  try { me = await (await fetch("/api/me")).json(); }
  catch (e) { me = { oauth_enabled: false, authenticated: false }; }
  renderAuth();
}

function renderAuth() {
  const el = $("auth");
  const name = $("nameInput");
  if (!el) return;
  if (!me || !me.oauth_enabled) { el.innerHTML = ""; name.hidden = false; name.disabled = false; return; }
  if (me.authenticated) {
    el.innerHTML = `<span>Hi, <b>${esc(me.name)}</b></span> <a href="/auth/logout">Sign out</a>`;
    name.value = me.name || "";
    name.hidden = true;          // identity comes from the Google profile
    name.disabled = true;
  } else {
    el.innerHTML = `<a class="signin" href="/auth/login">Sign in with Google</a>`;
    name.hidden = !!me.require_login;   // must sign in — hide the manual name field
    name.disabled = false;
  }
}

async function loadCatalog() {
  try {
    const data = await (await fetch("/api/cards")).json();
    catalogList = data.cards;
    rulesSections = data.sections;
    catalog = {};
    for (const c of data.cards) catalog[c.id] = c;
  } catch (e) { /* catalog is best-effort */ }
}

async function newGame(numPlayers, numHumans) {
  if (needsLogin()) { setConn("sign in to play", "bad"); return; }
  numHumans = Math.min(numHumans, numPlayers);
  const headers = { "Content-Type": "application/json" };
  const pc = $("passcode");
  if (!pc.hidden) {
    headers["X-HDU-Passcode"] = pc.value;
    localStorage.setItem("hdu_passcode", pc.value);
  }
  const r = await fetch("/api/games", {
    method: "POST", headers,
    body: JSON.stringify({ num_players: numPlayers, num_humans: numHumans, name: myName() }),
  });
  if (r.status === 401) { localStorage.removeItem("hdu_passcode"); setConn("wrong passcode", "bad"); return; }
  if (!r.ok) { setConn("create failed", "bad"); return; }
  const data = await r.json();
  setupSeat(data.game_id, data.seat, data.player_token);
}

// Join an existing game — fresh, or reconnect with a stored token — then connect.
async function joinAndConnect() {
  const stored = localStorage.getItem("hdu_token_" + gameId);
  let r;
  try {
    r = await fetch(`/api/games/${gameId}/join`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ player_token: stored || undefined, name: myName() }),
    });
  } catch (e) { setConn("join failed", "bad"); return; }
  if (r.status === 401) { setConn("sign in to play", "bad"); showIntro("Sign in with Google to join this game."); return; }
  if (r.status === 404) { setConn("game not found", "bad"); showIntro("That game no longer exists."); return; }
  if (r.status === 409) { setConn("game full", "bad"); showIntro("This game is full — every human seat is taken."); return; }
  if (!r.ok) { setConn("join failed", "bad"); return; }
  const data = await r.json();
  setupSeat(gameId, data.seat, data.player_token);
}

function setupSeat(gid, seat, token) {
  gameId = gid;
  mySeat = seat;
  playerToken = token;
  localStorage.setItem("hdu_token_" + gameId, token);
  location.hash = "game=" + gameId;
  logLines = [];
  connect();
}

function showIntro(text) {
  $("intro").hidden = false;
  $("intro").textContent = text;
  $("game").hidden = true;
}

// --- websocket --------------------------------------------------------------
function connect() {
  if (ws) { try { ws.close(); } catch (e) {} }
  chatMsgs = [];
  renderChat();
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/api/games/${gameId}/ws?token=${encodeURIComponent(playerToken)}`);
  setConn("connecting…", "");

  ws.onopen = () => setConn("connected", "ok");
  ws.onclose = () => setConn("disconnected", "bad");
  ws.onerror = () => setConn("error", "bad");
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.type === "snapshot") { snap = msg.snapshot; mySeat = snap.view.me; render(); }
    else if (msg.type === "update") {
      (msg.events || []).forEach(pushEvent);
      snap = msg.snapshot; mySeat = snap.view.me; render();
    } else if (msg.type === "chat") { chatMsgs.push(msg.message); renderChat(); }
    else if (msg.type === "chat_history") { chatMsgs = msg.messages || []; renderChat(); }
    else if (msg.type === "error") { pushLog("⚠ " + msg.detail, true); render(); }
  };
}

function myName() {
  if (me && me.authenticated && me.name) return me.name;
  return $("nameInput").value.trim();
}
function needsLogin() { return !!(me && me.require_login && !me.authenticated); }
function esc(s) { const d = document.createElement("div"); d.textContent = s == null ? "" : s; return d.innerHTML; }

function renderChat() {
  const el = $("chatLog");
  el.innerHTML = chatMsgs
    .map((m) => `<div class="msg${m.seat === mySeat ? " me" : ""}"><b>${esc(m.name)}:</b> ${esc(m.text)}</div>`)
    .join("");
  el.scrollTop = el.scrollHeight;
}

function submit(action) {
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "action", action }));
}
function continueHand() {
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "continue" }));
}
function setConn(text, cls) { const el = $("conn"); el.textContent = text; el.className = "conn " + cls; }

let toastTimer = null;
function flashToast(text) {
  const t = $("toast");
  t.textContent = text;
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, 1400);
}

// --- rendering --------------------------------------------------------------
function pname(id) {
  if (id === mySeat) return "You";
  const names = snap && snap.status && snap.status.names;
  return names && names[id] ? esc(names[id]) : "P" + id;
}

function cardEl(card, small) {
  const div = document.createElement("div");
  div.className = "card " + card.color.toLowerCase() + (small ? " small" : "");
  const lbl = document.createElement("div");
  lbl.className = "lbl";
  lbl.textContent = card.wild ? card.name : card.name.replace(/^\w+\s/, "");
  div.appendChild(lbl);
  if (card.number !== null && card.number !== undefined) {
    const n = document.createElement("div");
    n.className = "num";
    n.textContent = card.number;
    div.appendChild(n);
    if (!small) for (const pos of ["tl", "br"]) {
      const p = document.createElement("div");
      p.className = "pip " + pos;
      p.textContent = card.number;
      div.appendChild(p);
    }
  }
  attachTip(div, card, small);
  return div;
}

function backEl(small) {
  const d = document.createElement("div");
  d.className = "back" + (small ? " small" : "");
  return d;
}

function topKey(top) {
  return [top.card.id, top.card.color, top.card.number, top.eff_color].join("|");
}

// --- card tooltips ----------------------------------------------------------
let tipPinned = false;

function attachTip(el, card, small) {
  el.addEventListener("mouseenter", () => { if (!tipPinned) showTip(card, el, false); });
  el.addEventListener("mouseleave", () => hideTip(false));
  if (!small) {
    const badge = document.createElement("span");
    badge.className = "badge";
    badge.textContent = "?";
    badge.addEventListener("click", (e) => { e.stopPropagation(); showTip(card, el, true); });
    el.appendChild(badge);
  }
}

function showTip(card, anchor, pin) {
  const info = catalog[card.id];
  const tip = $("tip");
  let h = `<b>${card.name}</b>`;
  if (card.points !== undefined && card.points !== null) h += ` <span class="tip-worth">· worth ${card.points} now</span>`;
  if (info) {
    h += `<div class="tip-eff">${info.effect}</div>`;
    if (info.defense) h += `<div class="tip-def">${info.defense}</div>`;
  }
  tip.innerHTML = h;
  tip.hidden = false;
  const r = anchor.getBoundingClientRect();
  tip.style.left = Math.max(8, Math.min(r.left, window.innerWidth - tip.offsetWidth - 8)) + "px";
  tip.style.top = Math.max(8, r.top - tip.offsetHeight - 8) + "px";
  tipPinned = !!pin;
}

function hideTip(force) {
  if (tipPinned && !force) return;
  tipPinned = false;
  $("tip").hidden = true;
}

// --- rules modal ------------------------------------------------------------
function closeRules() { $("rulesModal").hidden = true; }

async function openRules() {
  if (!catalogList.length) await loadCatalog();  // ensure it's loaded on demand
  const groups = {}, order = [];
  for (const c of catalogList) {
    if (!groups[c.category]) { groups[c.category] = []; order.push(c.category); }
    groups[c.category].push(c);
  }
  let html = "<h2>How to play</h2>";
  for (const s of rulesSections) html += `<p><b>${s.title}.</b> ${s.body}</p>`;
  html += "<h2>Cards</h2>";
  for (const cat of order) {
    html += `<h3>${cat}</h3>`;
    for (const c of groups[cat]) {
      html += `<div class="rule-card"><b>${c.name}</b> <span class="rv">${c.value}</span><br>${c.effect}` +
        (c.defense ? `<br><i>${c.defense}</i>` : "") + `</div>`;
    }
  }
  $("rulesBody").innerHTML = html;
  $("rulesModal").hidden = false;
}

function renderLobby(st) {
  const humans = new Set(st.human_seats);
  const claimed = new Set(st.claimed_seats);
  const total = Object.keys(st.scores).length;
  const names = (snap && snap.status && snap.status.names) || {};
  const roles = [];
  for (let i = 0; i < total; i++) {
    let role;
    if (i === mySeat) role = "you";
    else if (!humans.has(i)) role = "AI";
    else role = claimed.has(i) ? "joined" : "waiting…";
    const label = names[i] ? esc(names[i]) : "P" + i;
    roles.push(`<span class="${role === "waiting…" ? "wait" : ""}">${label}: ${role}</span>`);
  }
  $("lobby").innerHTML =
    `<span>You are <b>${esc(names[mySeat] || "Player " + mySeat)}</b></span>` +
    `<span class="seats">${roles.join(" · ")}</span>` +
    `<button id="copyBtn" class="copy">Copy invite link</button>`;
  $("copyBtn").onclick = () => {
    if (navigator.clipboard) {
      navigator.clipboard.writeText(location.href);
      $("copyBtn").textContent = "Copied!";
      setTimeout(() => { const b = $("copyBtn"); if (b) b.textContent = "Copy invite link"; }, 1500);
    }
  };
}

function render() {
  if (!snap) return;
  $("intro").hidden = true;
  $("game").hidden = false;
  const st = snap.status;

  renderLobby(st);

  const turn = st.to_act === null ? "—"
    : (st.to_act === mySeat ? "Your turn" : pname(st.to_act) + " to act");
  $("status").innerHTML =
    `<span>Phase: <b>${st.phase}</b></span>` +
    `<span><b>${turn}</b></span>` +
    `<span>Direction: <b>${st.direction === 1 ? "↻" : "↺"}</b></span>` +
    `<span>Draw pile: <b>${snap.view.draw_count}</b></span>` +
    `<span>Scores: ${Object.entries(st.scores).map(([k, v]) => `${pname(+k)} ${v}`).join(" · ")}</span>`;

  // opponents — name, flags, and a little fan of face-down cards
  const opp = $("opponents");
  opp.innerHTML = "";
  for (const o of snap.view.opponents) {
    const div = document.createElement("div");
    div.className = "opp" + (st.to_act === o.id ? " turn" : "") + (o.eliminated ? " out" : "");
    const tags = [];
    if (o.called_uno) tags.push('<span class="tag-uno">UNO!</span>');
    if (o.eliminated) tags.push("eliminated");
    div.innerHTML =
      `<div class="who">${pname(o.id)} · ${o.hand_count}</div>` +
      `<div class="tags">${tags.join(" · ") || "&nbsp;"}</div>`;
    if (o.revealed_hand) {
      const rev = document.createElement("div");
      rev.className = "revealed";
      o.revealed_hand.forEach((c) => rev.appendChild(cardEl(c, true)));
      div.appendChild(rev);
    } else {
      const fan = document.createElement("div");
      fan.className = "fan";
      for (let i = 0; i < Math.min(o.hand_count, 7); i++) fan.appendChild(backEl(true));
      div.appendChild(fan);
    }
    opp.appendChild(div);
  }

  // legal actions -> clickable cards, draw-pile, buttons
  const cardActions = {};
  const buttons = [];
  let canDraw = false;
  for (const a of snap.legal_actions) {
    if (a.type === "play_card" || a.type === "reveal") cardActions[a.hand_index] = a;
    else if (a.type === "draw_card") canDraw = true;
    else buttons.push(a);
  }

  // draw pile — a face-down deck; click to draw when it's your turn
  const draw = $("drawpile");
  draw.innerHTML = "";
  const deckN = Math.min(snap.view.draw_count, 4);
  for (let i = 0; i < Math.max(deckN, 1); i++) {
    const b = backEl(false);
    b.style.transform = `translate(${i}px, ${-i}px)`;
    draw.appendChild(b);
  }
  const dlbl = document.createElement("div");
  dlbl.className = "label";
  dlbl.textContent = (canDraw && snap.your_turn) ? "Draw" : `${snap.view.draw_count} left`;
  draw.appendChild(dlbl);
  draw.classList.toggle("drawable", canDraw && snap.your_turn);
  draw.onclick = (canDraw && snap.your_turn) ? () => submit({ type: "draw_card" }) : null;

  // discard pile — top card, ringed in the active color, dealt-in when it changes
  const disc = $("discard");
  const key = topKey(snap.view.top);
  const changed = key !== prevTopKey;
  prevTopKey = key;
  disc.innerHTML = "";
  disc.className = "pile discard ring-" + snap.view.top.eff_color.toLowerCase();
  const topCard = cardEl(snap.view.top.card, false);
  if (changed) topCard.classList.add("played");
  disc.appendChild(topCard);

  $("pending").textContent = describePending(snap.view.pending);

  const hand = $("hand");
  hand.innerHTML = "";
  snap.view.hand.forEach((card, i) => {
    const el = cardEl(card, false);
    const act = cardActions[i];
    if (act && snap.your_turn) {
      el.classList.add("playable");
      el.title = act.type === "reveal" ? "Reveal" : "Play";
      el.onclick = () => submit(act);
    }
    hand.appendChild(el);
  });
  $("turnHint").textContent = snap.your_turn
    ? "— click a highlighted card or pick an action below"
    : (st.to_act === null ? "" : "— waiting…");

  const actions = $("actions");
  actions.innerHTML = "";
  if (snap.your_turn) for (const a of buttons) actions.appendChild(actionButton(a));

  const log = $("log");
  log.innerHTML = logLines.map((l) => `<div class="${l.big ? "big" : ""}">${l.text}</div>`).join("");
  log.scrollTop = log.scrollHeight;

  // banner: end-of-hand pause, or game over
  const banner = $("banner");
  if (st.phase === "game_over") {
    banner.hidden = false;
    const order = Object.entries(st.scores).sort((a, b) => a[1] - b[1]);
    banner.innerHTML = `<h2>Game over — ${pname(st.winner)} wins! 🏆</h2>` +
      `<div>${order.map(([k, v], idx) => `${idx + 1}. ${pname(+k)} — ${v}`).join("<br>")}</div>` +
      `<button id="againBtn">New game</button>`;
    $("againBtn").onclick = () =>
      newGame(parseInt($("numPlayers").value, 10), parseInt($("numHumans").value, 10));
  } else if (st.phase === "hand_over" && snap.hand_result) {
    banner.hidden = false;
    const hr = snap.hand_result;
    const who = hr.winner === null ? "No winner (all eliminated)" : `${pname(hr.winner)} won the hand`;
    const gains = Object.entries(hr.gains)
      .map(([k, v]) => `${pname(+k)} ${v >= 0 ? "+" : ""}${v}`).join(" · ");
    banner.innerHTML = `<h2>Hand over — ${who}</h2>` +
      `<div>this hand: ${gains}</div>` +
      `<button id="nextBtn">Next hand →</button>`;
    $("nextBtn").onclick = continueHand;
  } else {
    banner.hidden = true;
  }
}

function actionButton(a) {
  const b = document.createElement("button");
  if (a.type === "draw_card") b.textContent = "Draw a card";
  else if (a.type === "pass") b.textContent = "Pass";
  else if (a.type === "decline") b.textContent = "Take it / Decline";
  else if (a.type === "choose_color") { b.textContent = a.color; b.className = "c-" + a.color.toLowerCase(); }
  else if (a.type === "choose_victim") b.textContent = "Target " + pname(a.player);
  else b.textContent = a.type;
  b.onclick = () => submit(a);
  return b;
}

function describePending(p) {
  if (!p) return "";
  if (p.kind === "draw_stack")
    return `Draw stack: ${p.draw_total} cards${p.undefendable ? " (undefendable!)" : ""} — decline or respond`;
  if (p.kind === "spreader") return "Spreader — reveal Penn State or take 2";
  if (p.kind === "quitter") return "Quitter — you're being eliminated unless you respond";
  if (p.kind === "glasnost") return "Glasnost — reveal your hand or defend";
  if (p.kind === "glasnost_choose") return "Glasnost — choose whose hand to expose";
  return p.kind;
}

// --- event log text ---------------------------------------------------------
function pushEvent(e) {
  const P = (id) => pname(id);
  const map = {
    CardPlayed: () => `${P(e.player)} played ${e.card.name}`,
    PlayerDrew: () => `${P(e.player)} drew ${e.count}`,
    PlayerSkipped: () => `${P(e.player)} was skipped`,
    DirectionReversed: () => `direction reversed`,
    ColorChosen: () => `${P(e.player)} chose ${e.color}`,
    DeckReshuffled: () => `deck reshuffled (${e.new_draw_count})`,
    UnoCalled: () => `${P(e.player)} — UNO!`,
    PlayerWonHand: () => `★ ${P(e.player)} went out and won the hand`,
    TurnPassed: () => `${P(e.player)} passed`,
    PlayerEliminated: () => `✖ ${P(e.player)} eliminated`,
    QuitterStarted: () => `${P(e.origin)} played Quitter on ${P(e.target)}`,
    GlasnostStarted: () => `${P(e.origin)} played Glasnost on ${P(e.target)}`,
    HandRevealed: () => `${P(e.player)} revealed their hand`,
    SpreaderStarted: () => `${P(e.origin)} played Spreader`,
    PennStateRevealed: () => `${P(e.player)} revealed Penn State`,
    LuckRevealed: () => `${P(e.player)} used Luck o' the Irish`,
    BastardHand: () => `☠ ${P(e.holder)} held all four bastard cards!`,
    HandScored: () => `Hand scored — ${e.gains.map((g) => `${P(g[0])}+${g[1]}`).join(", ")}`,
    GameOver: () => `GAME OVER — ${P(e.winner)} wins`,
  };
  const fn = map[e.type];
  const big = ["PlayerWonHand", "HandScored", "GameOver", "BastardHand", "PlayerEliminated"].includes(e.type);
  pushLog(fn ? fn() : e.type, big);
  if (e.type === "DirectionReversed") flashToast("↺ Direction reversed");
  else if (e.type === "UnoCalled") flashToast(`${P(e.player)} — UNO!`);
  else if (e.type === "BastardHand") flashToast("☠ Bastard hand!");
}

function pushLog(text, big) {
  logLines.push({ text, big: !!big });
  if (logLines.length > 200) logLines.shift();
}
