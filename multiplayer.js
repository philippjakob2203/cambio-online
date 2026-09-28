const connection = {
  code: null,
  playerId: null,
  snapshot: null,
  pendingMatch: null,
  renderKey: null,
  polling: false,
  pollTimer: null,
};

const screens = {
  connect: document.getElementById('connect-view'),
  lobby: document.getElementById('lobby-view'),
  game: document.getElementById('game-view'),
};

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (character) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  })[character]);
}

function showScreen(screenName) {
  Object.entries(screens).forEach(([name, screen]) => {
    screen.hidden = name !== screenName;
  });
}

function showMessage(message, isError = false) {
  const messageBox = document.getElementById('message');
  messageBox.textContent = message;
  messageBox.classList.toggle('error', isError);
  messageBox.hidden = false;
  clearTimeout(showMessage.timer);
  showMessage.timer = setTimeout(() => { messageBox.hidden = true; }, 4000);
}

async function request(path, options = {}) {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || 'Die Anfrage ist fehlgeschlagen.');
  return payload;
}

function saveConnection() {
  sessionStorage.setItem('cambio-room', connection.code);
  sessionStorage.setItem('cambio-player', connection.playerId);
}

function clearConnection() {
  sessionStorage.removeItem('cambio-room');
  sessionStorage.removeItem('cambio-player');
  connection.code = null;
  connection.playerId = null;
  connection.snapshot = null;
  connection.pendingMatch = null;
  connection.renderKey = null;
  clearTimeout(connection.pollTimer);
  showScreen('connect');
}

function roomPath(suffix = '') {
  return `/api/room/${encodeURIComponent(connection.code)}${suffix}`;
}

async function joinCreatedRoom(result) {
  connection.code = result.code;
  connection.playerId = result.playerId;
  saveConnection();
  await refreshRoom();
  pollRoom();
}

async function createRoom() {
  const name = document.getElementById('create-name').value.trim();
  const result = await request('/api/rooms', {
    method: 'POST',
    body: JSON.stringify({ name }),
  });
  await joinCreatedRoom(result);
}

async function joinRoom() {
  const code = document.getElementById('join-code').value.trim().toUpperCase();
  const name = document.getElementById('join-name').value.trim();
  if (!code) throw new Error('Gib einen Raumcode ein.');
  const result = await request(`/api/room/${encodeURIComponent(code)}/join`, {
    method: 'POST',
    body: JSON.stringify({ name }),
  });
  await joinCreatedRoom(result);
}

async function refreshRoom() {
  const snapshot = await request(`${roomPath()}?player_id=${encodeURIComponent(connection.playerId)}`);
  if (snapshot.phase !== 'reaction') connection.pendingMatch = null;
  connection.snapshot = snapshot;
  renderRoom(snapshot);
  if (snapshot.phase === 'lobby') showScreen('lobby');
  else showScreen('game');
}

function pollRoom() {
  if (connection.polling) return;
  connection.polling = true;
  const poll = async () => {
    if (!connection.code || !connection.playerId) {
      connection.polling = false;
      return;
    }
    try {
      await refreshRoom();
    } catch (error) {
      connection.polling = false;
      clearConnection();
      showMessage(error.message, true);
      return;
    }
    connection.pollTimer = setTimeout(poll, 450);
  };
  poll();
}

function inviteUrl(code) {
  const url = new URL(window.location.href);
  url.search = '';
  url.searchParams.set('room', code);
  return url.toString();
}

function renderRoom(snapshot) {
  const renderKey = JSON.stringify({ ...snapshot, reactionRemaining: 0, specialRevealRemaining: 0 });
  if (connection.renderKey === renderKey) {
    if (snapshot.phase === 'reaction') {
      document.getElementById('game-status').textContent = `Reaktionsfenster: ${snapshot.reactionRemaining.toFixed(1)} s`;
    }
    if (snapshot.specialRevealRemaining > 0) updateSpecialTimer(snapshot.specialRevealRemaining);
    return;
  }
  connection.renderKey = renderKey;
  const host = snapshot.players.find((player) => player.id === snapshot.hostId);
  const invite = inviteUrl(snapshot.code);
  document.querySelectorAll('.room-code').forEach((element) => {
    element.textContent = snapshot.code;
  });
  document.querySelectorAll('.invite-link').forEach((element) => {
    element.value = invite;
  });
  renderSeats(snapshot, host);
  if (snapshot.phase === 'lobby') return;
  renderGame(snapshot);
}

function renderSeats(snapshot, host) {
  const isHost = connection.playerId === snapshot.hostId;
  const canStart = isHost && snapshot.players.length >= 2;
  document.getElementById('lobby-count').textContent = `${snapshot.players.length} / 13 Plätze`;
  document.getElementById('lobby-seats').innerHTML = snapshot.players.map((player) => `
    <li class="seat-row">
      <span class="seat-type ${player.type}">${player.type === 'cpu' ? 'CPU' : 'Mensch'}</span>
      <strong>${escapeHtml(player.name)}</strong>
      ${player.id === snapshot.hostId ? '<span class="host-tag">Spielleitung</span>' : ''}
      ${isHost && player.type === 'cpu' ? `<button class="icon-button remove-cpu" data-player-id="${escapeHtml(player.id)}" aria-label="${escapeHtml(player.name)} entfernen" title="CPU entfernen">×</button>` : ''}
    </li>
  `).join('');
  document.getElementById('add-cpu').disabled = !isHost || snapshot.players.length >= 13;
  document.getElementById('start-game').hidden = !isHost;
  document.getElementById('start-game').disabled = !canStart;
  document.getElementById('lobby-waiting').hidden = isHost;
  document.getElementById('lobby-host-status').textContent = isHost
    ? `Du leitest den Raum${host ? ` als ${escapeHtml(host.name)}` : ''}. Füge CPUs hinzu oder teile den Einladungslink.`
    : 'Warte auf den Start durch die Spielleitung.';
}

function cardMarkup(card, playerIndex, cardIndex, snapshot) {
  const isHidden = !card;
  const canMatch = snapshot.phase === 'reaction' && snapshot.players.some((player) => player.id === connection.playerId && player.type === 'human');
  const canSwap = Boolean(snapshot.drawnCard) && snapshot.currentPlayerId === connection.playerId && snapshot.phase === 'turn';
  const ownIndex = snapshot.players.findIndex((player) => player.id === connection.playerId);
  const specialStep = snapshot.special?.step;
  const selectingOwn = ['peek_own', 'trade_own', 'queen_own', 'select_gift'].includes(specialStep);
  const selectingTarget = ['peek_target', 'trade_target', 'queen_target'].includes(specialStep);
  const specialSelectable = snapshot.phase === 'special'
    && (selectingOwn ? playerIndex === ownIndex : selectingTarget && playerIndex !== ownIndex);
  const active = canMatch || specialSelectable || (canSwap && playerIndex === ownIndex);
  const short = card ? `${card.short}${card.suit}` : 'Verdeckte Karte';
  return `<button class="card ${card && card.color === 'red' ? 'red' : 'black'} ${isHidden ? 'hidden' : ''}" data-player-index="${playerIndex}" data-card-index="${cardIndex}" aria-label="${escapeHtml(short)}" ${active ? '' : 'disabled'}>
    <span class="rank">${card ? escapeHtml(card.short) : '?'}</span>
    <span class="suit">${card ? escapeHtml(card.suit) : '?'}</span>
    <span class="small">${card ? escapeHtml(card.short) : '?'}</span>
  </button>`;
}

function renderGame(snapshot) {
  const current = snapshot.currentPlayerId === connection.playerId;
  const inReaction = snapshot.phase === 'reaction';
  const viewer = snapshot.players.find((player) => player.id === connection.playerId);
  document.getElementById('game-room-code').textContent = snapshot.code;
  document.getElementById('round-label').textContent = `Runde ${snapshot.round}`;
  document.getElementById('scoreboard').innerHTML = snapshot.players.map((player) => `
    <div class="score-pill ${player.id === snapshot.currentPlayerId ? 'active' : ''}">
      <span>${escapeHtml(player.name)}</span>
      <strong>${player.score} Pkt.</strong>
    </div>
  `).join('');
  document.getElementById('deck-count').textContent = snapshot.deckCount;
  const discard = snapshot.discardTop;
  document.getElementById('discard-pile').innerHTML = discard
    ? `<div class="mini-card ${discard.color === 'red' ? 'red' : 'black'}">${escapeHtml(discard.short)}${escapeHtml(discard.suit)}</div>`
    : '<div class="mini-card empty">-</div>';
  const drawn = snapshot.drawnCard;
  renderSpecial(snapshot);
  const drawnBox = document.getElementById('drawn-card-box');
  drawnBox.textContent = drawn ? `${drawn.short}${drawn.suit}` : '-';
  drawnBox.classList.toggle('empty', !drawn);
  drawnBox.classList.toggle('red', Boolean(drawn && drawn.color === 'red'));
  document.getElementById('players').innerHTML = snapshot.players.map((player, playerIndex) => `
    <section class="player ${player.id === snapshot.currentPlayerId ? 'current' : ''}">
      <div class="player-header">
        <strong>${escapeHtml(player.name)}${player.id === connection.playerId ? ' (du)' : ''}</strong>
        <span>${player.score} Pkt. · ${player.cardCount} Karten</span>
      </div>
      <div class="hand">${player.hand.map((card, cardIndex) => cardMarkup(card, playerIndex, cardIndex, snapshot)).join('')}</div>
    </section>
  `).join('');
  document.getElementById('turn-indicator').textContent = snapshot.phase === 'finished'
    ? `Spielende: ${escapeHtml(snapshot.players.find((player) => player.id === snapshot.winnerId)?.name || 'Gewinner')}`
    : snapshot.phase === 'special'
      ? snapshot.currentPlayerId === connection.playerId ? 'Deine Sonderkarte' : `${escapeHtml(snapshot.currentPlayerName)} führt eine Sonderkarte aus.`
    : inReaction
      ? 'Schnell! Lege eine passende Karte auf die Ablage.'
      : current
        ? 'Du bist am Zug.'
        : `${escapeHtml(snapshot.currentPlayerName)} ist am Zug.`;
  document.getElementById('peek-status').textContent = viewer && viewer.hand.some(Boolean)
    ? 'Deine zwei Startkarten sind noch kurz sichtbar.'
    : 'Deine Karten sind verdeckt.';
  document.getElementById('log').innerHTML = snapshot.log.map((entry) => `<div class="log-entry">${escapeHtml(entry)}</div>`).join('');

  const canPlay = snapshot.phase === 'turn' && current;
  document.getElementById('draw-deck').disabled = !canPlay || Boolean(drawn);
  document.getElementById('draw-discard').disabled = !canPlay || Boolean(drawn) || !discard;
  document.getElementById('discard-drawn').disabled = !canPlay || !drawn;
  document.getElementById('schotten').disabled = !canPlay || Boolean(drawn);
  document.getElementById('game-status').textContent = snapshot.phase === 'finished'
    ? 'Partie beendet'
    : snapshot.phase === 'special'
      ? 'Sonderkarte'
    : inReaction
      ? `Reaktionsfenster: ${snapshot.reactionRemaining.toFixed(1)} s`
      : current
        ? 'Dein Zug'
        : 'Warte auf den Zug';
  document.getElementById('game-status').classList.toggle('racing', inReaction);
  document.getElementById('game-message').textContent = connection.pendingMatch
    ? 'Wähle jetzt eine deiner Karten als Ersatz aus.'
    : snapshot.phase === 'finished'
      ? `${snapshot.players.find((player) => player.id === snapshot.winnerId)?.name || 'Eine Person'} gewinnt.`
      : `Raum ${snapshot.code} · ${snapshot.players.length} / 13 Personen`;
}

function renderSpecial(snapshot) {
  const panel = document.getElementById('special-panel');
  const special = snapshot.special;
  const isActor = snapshot.phase === 'special' && Boolean(special);
  panel.hidden = !isActor;
  if (!isActor) return;

  const titles = { 7: '7 · Eigene Karte ansehen', 8: '8 · Eigene Karte ansehen', 9: '9 · Fremde Karte ansehen', 10: '10 · Fremde Karte ansehen', 11: 'Bube · Blind tauschen', 12: 'Dame · Ansehen und entscheiden' };
  const prompts = {
    offer: 'Möchtest du die Sonderfunktion nutzen?',
    peek_own: 'Wähle eine deiner verdeckten Karten.',
    peek_target: 'Wähle die verdeckte Karte einer anderen Person.',
    trade_own: 'Wähle zuerst eine eigene Karte.',
    trade_target: 'Wähle danach eine verdeckte Karte einer anderen Person.',
    queen_own: 'Wähle eine eigene Karte zum Vergleichen.',
    queen_target: 'Wähle die Karte einer anderen Person.',
    queen_decide: 'Du hast beide Karten gesehen. Möchtest du tauschen?',
    viewing: 'Diese Karte ist nur für dich sichtbar.',
  };
  document.getElementById('special-title').textContent = titles[special.rank] || 'Sonderkarte';
  document.getElementById('special-prompt').textContent = prompts[special.step] || '';
  const actions = document.getElementById('special-actions');
  if (special.step === 'offer') {
    actions.innerHTML = '<button type="button" data-special-action="accept">Ausführen</button><button type="button" class="secondary-button" data-special-action="skip">Überspringen</button>';
  } else if (special.step === 'queen_decide') {
    actions.innerHTML = '<button type="button" data-special-action="queen_swap">Tauschen</button><button type="button" class="secondary-button" data-special-action="queen_keep">Nicht tauschen</button>';
  } else {
    actions.innerHTML = '';
  }
  updateSpecialTimer(snapshot.specialRevealRemaining);
}

function updateSpecialTimer(seconds) {
  const timer = document.getElementById('special-timer');
  if (!timer) return;
  timer.textContent = seconds > 0 ? `Noch ${Math.ceil(seconds)} Sekunden` : '';
}

async function sendAction(action, extra = {}) {
  try {
    await request(roomPath('/action'), {
      method: 'POST',
      body: JSON.stringify({ playerId: connection.playerId, action, ...extra }),
    });
    await refreshRoom();
  } catch (error) {
    showMessage(error.message, true);
    await refreshRoom();
  }
}

async function hostRequest(suffix, body = {}) {
  try {
    await request(roomPath(suffix), {
      method: 'POST',
      body: JSON.stringify({ playerId: connection.playerId, ...body }),
    });
    await refreshRoom();
  } catch (error) {
    showMessage(error.message, true);
  }
}

function attachEvents() {
  document.getElementById('create-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    try { await createRoom(); } catch (error) { showMessage(error.message, true); }
  });
  document.getElementById('join-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    try { await joinRoom(); } catch (error) { showMessage(error.message, true); }
  });
  document.getElementById('add-cpu').addEventListener('click', () => hostRequest('/cpu'));
  document.getElementById('start-game').addEventListener('click', () => hostRequest('/start'));
  document.getElementById('lobby-copy-link').addEventListener('click', copyInvite);
  document.getElementById('game-copy-link').addEventListener('click', copyInvite);
  document.getElementById('draw-deck').addEventListener('click', () => sendAction('draw_deck'));
  document.getElementById('draw-discard').addEventListener('click', () => sendAction('draw_discard'));
  document.getElementById('discard-drawn').addEventListener('click', () => sendAction('discard_drawn'));
  document.getElementById('schotten').addEventListener('click', () => sendAction('schotten'));
  document.getElementById('leave-room').addEventListener('click', clearConnection);
  document.getElementById('players').addEventListener('click', (event) => {
    const card = event.target.closest('.card');
    if (!card || !connection.snapshot) return;
    const playerIndex = Number(card.dataset.playerIndex);
    const cardIndex = Number(card.dataset.cardIndex);
    if (connection.snapshot.phase === 'special' && connection.snapshot.special) {
      const ownIndex = connection.snapshot.players.findIndex((player) => player.id === connection.playerId);
      const step = connection.snapshot.special.step;
      if (['peek_own', 'trade_own', 'queen_own'].includes(step) && playerIndex === ownIndex) {
        sendAction('special_action', { specialAction: 'select_own', cardIndex });
      } else if (['peek_target', 'trade_target', 'queen_target'].includes(step) && playerIndex !== ownIndex) {
        sendAction('special_action', { specialAction: 'select_target', targetPlayerIndex: playerIndex, cardIndex });
      }
    } else if (connection.snapshot.phase === 'reaction') {
      const ownIndex = connection.snapshot.players.findIndex((player) => player.id === connection.playerId);
      if (connection.pendingMatch) {
        if (playerIndex !== ownIndex) return;
        const target = connection.pendingMatch;
        connection.pendingMatch = null;
        sendAction('match', {
          targetPlayerIndex: target.playerIndex,
          targetCardIndex: target.cardIndex,
          giftCardIndex: cardIndex,
        });
      } else if (playerIndex === ownIndex) {
        sendAction('match', { targetPlayerIndex: ownIndex, targetCardIndex: cardIndex });
      } else {
        connection.pendingMatch = { playerIndex, cardIndex };
        document.getElementById('game-message').textContent = 'Wähle jetzt eine deiner Karten als Ersatz aus.';
      }
    } else if (connection.snapshot.drawnCard && connection.snapshot.currentPlayerId === connection.playerId) {
      const ownIndex = connection.snapshot.players.findIndex((player) => player.id === connection.playerId);
      if (playerIndex === ownIndex) sendAction('swap', { cardIndex });
    }
  });
  document.getElementById('lobby-seats').addEventListener('click', (event) => {
    const button = event.target.closest('.remove-cpu');
    if (button) hostRequest('/cpu/remove', { cpuId: button.dataset.playerId });
  });
  document.getElementById('special-actions').addEventListener('click', (event) => {
    const button = event.target.closest('[data-special-action]');
    if (button) sendAction('special_action', { specialAction: button.dataset.specialAction });
  });
}

async function copyInvite() {
  if (!connection.code) return;
  try {
    await navigator.clipboard.writeText(inviteUrl(connection.code));
    showMessage('Einladungslink kopiert.');
  } catch (_error) {
    showMessage('Der Einladungslink steht im Feld bereit.');
  }
}

function initialize() {
  attachEvents();
  const queryRoom = new URLSearchParams(window.location.search).get('room');
  if (queryRoom) document.getElementById('join-code').value = queryRoom.toUpperCase();
  const savedCode = sessionStorage.getItem('cambio-room');
  const savedPlayer = sessionStorage.getItem('cambio-player');
  if (savedCode && savedPlayer) {
    connection.code = savedCode;
    connection.playerId = savedPlayer;
    pollRoom();
  }
}

initialize();
