"use strict";

// --- state ------------------------------------------------------------------
const SEAT = 0; // single-player: you are always seat 0
let gameId = null;
let ws = null;
let snap = null;       // latest snapshot for our seat
const logLines = [];

const $ = (id) => document.getElementById(id);

// --- bootstrap --------------------------------------------------------------
$("newGameBtn").onclick = () => newGame(parseInt($("numPlayers").value, 10));

window.addEventListener("load", () => {
  const m = location.hash.match(/game=([\w-]+)/);
  if (m) { gameId = m[1]; connect(); }
});

async function newGame(numPlayers) {
  const r = await fetch("/api/games", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ num_players: numPlayers, human_seats: [SEAT] }),
  });
  const data = await r.json();
  gameId = data.game_id;
  location.hash = "game=" + gameId;
  logLines.length = 0;
  connect();
}

// --- websocket --------------------------------------------------------------
function connect() {
  if (ws) { try { ws.close(); } catch (e) {} }
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/api/games/${gameId}/ws?seat=${SEAT}`);
  setConn("connecting…", "");

  ws.onopen = () => setConn("connected", "ok");
  ws.onclose = () => setConn("disconnected", "bad");
  ws.onerror = () => setConn("error", "bad");
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.type === "snapshot") { snap = msg.snapshot; render(); }
    else if (msg.type === "update") {
      (msg.events || []).forEach(pushEvent);
      snap = msg.snapshot;
      render();
    } else if (msg.type === "error") {
      pushLog("⚠ " + msg.detail, true);
      render();
    }
  };
}

function submit(action) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: "action", action }));
  }
}

function setConn(text, cls) {
  const el = $("conn");
  el.textContent = text;
  el.className = "conn " + cls;
}

// --- rendering --------------------------------------------------------------
function pname(id) { return id === SEAT ? "You" : "P" + id; }

function cardEl(card, small) {
  const div = document.createElement("div");
  div.className = "card " + card.color.toLowerCase() + (small ? " small" : "");
  const lbl = document.createElement("div");
  lbl.className = "lbl";
  lbl.textContent = card.wild ? card.name : (card.name.replace(/^\w+\s/, ""));
  div.appendChild(lbl);
  if (card.number !== null && card.number !== undefined) {
    const n = document.createElement("div");
    n.className = "num";
    n.textContent = card.number;
    div.appendChild(n);
  }
  return div;
}

function render() {
  if (!snap) return;
  $("intro").hidden = true;
  $("game").hidden = false;
  const st = snap.status;

  // status line
  const turn = st.phase === "game_over" ? "—"
    : (st.to_act === SEAT ? "Your turn" : pname(st.to_act) + " to act");
  $("status").innerHTML =
    `<span>Phase: <b>${st.phase}</b></span>` +
    `<span><b>${turn}</b></span>` +
    `<span>Direction: <b>${st.direction === 1 ? "↻" : "↺"}</b></span>` +
    `<span>Draw pile: <b>${snap.view.draw_count}</b></span>` +
    `<span>Scores: ${Object.entries(st.scores).map(([k, v]) => `${pname(+k)} ${v}`).join(" · ")}</span>`;

  // opponents
  const opp = $("opponents");
  opp.innerHTML = "";
  for (const o of snap.view.opponents) {
    const div = document.createElement("div");
    div.className = "opp" + (st.to_act === o.id ? " turn" : "") + (o.eliminated ? " out" : "");
    const tags = [];
    if (o.called_uno) tags.push('<span class="tag-uno">UNO!</span>');
    if (o.eliminated) tags.push("eliminated");
    div.innerHTML = `<div><b>${pname(o.id)}</b> — ${o.hand_count} cards</div>` +
      `<div class="tags">${tags.join(" · ") || "&nbsp;"}</div>`;
    if (o.revealed_hand) {
      const rev = document.createElement("div");
      rev.className = "revealed";
      o.revealed_hand.forEach((c) => rev.appendChild(cardEl(c, true)));
      div.appendChild(rev);
    }
    opp.appendChild(div);
  }

  // discard top
  const disc = $("discard");
  disc.innerHTML = "";
  disc.appendChild(cardEl(snap.view.top.card, false));
  const now = document.createElement("div");
  now.className = "now";
  now.innerHTML = `top of pile<br>active color: <b>${snap.view.top.eff_color}</b>`;
  disc.appendChild(now);

  // pending banner (respond windows)
  $("pending").textContent = describePending(snap.view.pending);

  // collect legal actions
  const cardActions = {};       // hand_index -> action (play_card or reveal)
  const buttons = [];
  for (const a of snap.legal_actions) {
    if (a.type === "play_card" || a.type === "reveal") cardActions[a.hand_index] = a;
    else buttons.push(a);
  }

  // hand
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
    : (st.phase === "game_over" ? "" : "— waiting…");

  // action buttons
  const actions = $("actions");
  actions.innerHTML = "";
  if (snap.your_turn) {
    for (const a of buttons) actions.appendChild(actionButton(a));
  }

  // event log
  const log = $("log");
  log.innerHTML = logLines.map((l) => `<div class="${l.big ? "big" : ""}">${l.text}</div>`).join("");
  log.scrollTop = log.scrollHeight;

  // game over banner
  const banner = $("banner");
  if (st.phase === "game_over") {
    banner.hidden = false;
    const order = Object.entries(st.scores).sort((a, b) => a[1] - b[1]);
    banner.innerHTML = `<h2>Game over — ${pname(st.winner)} wins! 🏆</h2>` +
      `<div>${order.map(([k, v], idx) => `${idx + 1}. ${pname(+k)} — ${v}`).join("<br>")}</div>` +
      `<button id="againBtn">New game</button>`;
    $("againBtn").onclick = () => newGame(snap.view.opponents.length + 1);
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
}

function pushLog(text, big) {
  logLines.push({ text, big: !!big });
  if (logLines.length > 200) logLines.shift();
}
