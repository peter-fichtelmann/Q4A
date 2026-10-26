let lobbySocket = null;
let currentRoom = null;
let currentPlayerId = null;
let isCreator = false;
let roomPlayers = [];
let roomSlots = {};
let teamNames = ['Team A', 'Team B'];

function getRequiredParams() {
    const params = new URLSearchParams(window.location.search);
    const roomId = params.get('room_id');
    const playerId = params.get('player_id');
    const creatorFlag = params.get('creator') === '1';
    return { roomId, playerId, creatorFlag };
}

function connectLobby() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    lobbySocket = new WebSocket(`${protocol}//${window.location.host}/ws/lobby`);

    lobbySocket.onopen = () => {
        lobbySocket.send(JSON.stringify({
            type: 'attach_room_lobby',
            room_id: currentRoom,
            player_id: currentPlayerId
        }));
    };

    lobbySocket.onmessage = (event) => {
        const message = JSON.parse(event.data);
        handleLobbyMessage(message);
    };

    lobbySocket.onerror = (error) => {
        console.error('Lobby WebSocket error:', error);
        updateStatus('Connection error. Please refresh the page.', 'error');
    };
}

function handleLobbyMessage(message) {
    if (message.type === 'attach_successful') {
        currentRoom = message.room_id;
        currentPlayerId = message.player_id;
        isCreator = Boolean(message.is_creator);
        renderRoomHeader();
        applyRoomState(message.players || [], message.slots || {}, message.team_names);
        toggleStartButton();
        updateStatus('Connected to room lobby.', 'success');
    } else if (message.type === 'players_updated') {
        applyRoomState(message.players || [], message.slots || {}, message.team_names);
    } else if (message.type === 'attach_failed') {
        updateStatus(`Unable to attach to room: ${message.error}`, 'error');
    } else if (message.type === 'update_failed') {
        updateStatus(message.error || 'Failed to update room assignment.', 'error');
        // A rejected name: put the accepted one back into the input.
        if (message.field === 'name') renderBoard();
        if (message.field === 'team_name') renderTeamNames(true);
    } else if (message.type === 'start_failed') {
        updateStatus(message.error || 'Failed to start game.', 'error');
    } else if (message.type === 'start_successful') {
        const roomId = message.room_id || currentRoom;
        const playerId = message.player_id || currentPlayerId;
        if (roomId && playerId) {
            window.location.href = `/game?room=${encodeURIComponent(roomId)}&player=${encodeURIComponent(playerId)}`;
        } else {
            updateStatus('Game started, but no player id was provided.', 'error');
        }
    }
}

function renderRoomHeader() {
    const roomIdEl = document.getElementById('roomId');
    if (roomIdEl) roomIdEl.textContent = currentRoom || '';
}

function applyRoomState(players, slots, names) {
    roomPlayers = players;
    roomSlots = slots;
    if (Array.isArray(names) && names.length === 2) teamNames = names;
    renderTeamNames(false);
    renderBoard();
    document.dispatchEvent(new CustomEvent('q4a:room_state', {
        detail: { players, slots, playerId: currentPlayerId }
    }));
}

function canRenameTeam(team) {
    if (isCreator) return true;
    const me = roomPlayers.find((p) => p.id === currentPlayerId);
    return Boolean(me) && Number(me.team) === team && me.role !== 'spectator';
}

// The team headings: an input for the teams this player may rename, plain text otherwise.
// An input that has focus is left alone unless `force`, so other players' updates do not
// wipe what is being typed.
function renderTeamNames(force) {
    ['teamAName', 'teamBName'].forEach((elementId, team) => {
        const heading = document.getElementById(elementId);
        if (!heading) return;
        const existing = heading.querySelector('.team-name-input');
        if (!force && existing && document.activeElement === existing) return;

        heading.innerHTML = '';
        if (!canRenameTeam(team)) {
            heading.textContent = teamNames[team];
            return;
        }
        const input = document.createElement('input');
        input.type = 'text';
        input.className = 'team-name-input';
        input.maxLength = 24;
        input.value = teamNames[team];
        input.title = 'Rename team';

        const submit = () => {
            const newName = (input.value || '').trim();
            if (!newName) {
                input.value = teamNames[team];
                return;
            }
            if (newName === teamNames[team]) return;
            updateTeamName(team, newName);
        };
        input.addEventListener('keydown', (event) => {
            if (event.key === 'Enter') {
                event.preventDefault();
                input.blur();
            }
        });
        input.addEventListener('blur', submit);
        heading.appendChild(input);
    });
}

function renderBoard() {
    const teamAEl = document.getElementById('teamASlots');
    const teamBEl = document.getElementById('teamBSlots');
    const spectatorEl = document.getElementById('spectatorDropzone');
    if (!teamAEl || !teamBEl || !spectatorEl) return;

    teamAEl.innerHTML = '';
    teamBEl.innerHTML = '';
    spectatorEl.innerHTML = '';

    const playersById = {};
    roomPlayers.forEach((p) => {
        playersById[p.id] = p;
    });

    Object.keys(roomSlots)
        .filter((slotId) => slotId.startsWith('team_a_'))
        .sort()
        .forEach((slotId) => teamAEl.appendChild(buildSlotElement(slotId, playersById)));

    Object.keys(roomSlots)
        .filter((slotId) => slotId.startsWith('team_b_'))
        .sort()
        .forEach((slotId) => teamBEl.appendChild(buildSlotElement(slotId, playersById)));

    const slottedPlayerIds = new Set(Object.values(roomSlots).filter((pid) => pid));
    roomPlayers
        .filter((p) => !slottedPlayerIds.has(p.id))
        .forEach((p) => spectatorEl.appendChild(buildPlayerCard(p)));
}

function buildSlotElement(slotId, playersById) {
    const wrapper = document.createElement('div');
    wrapper.className = 'slot-box role-slot';
    wrapper.dataset.slotId = slotId;

    const role = getRoleForSlot(slotId);
    const roleColor = getRoleColor(role);
    if (roleColor) {
        wrapper.style.setProperty('--slot-role-color', roleColor);
    }

    const label = document.createElement('div');
    label.className = 'slot-label';
    label.textContent = formatSlotLabel(slotId);
    wrapper.appendChild(label);

    const assignedPlayerId = roomSlots[slotId];
    if (assignedPlayerId && playersById[assignedPlayerId]) {
        wrapper.appendChild(buildPlayerCard(playersById[assignedPlayerId]));
    } else {
        const empty = document.createElement('div');
        empty.className = 'slot-empty';
        empty.textContent = 'Drop here';
        wrapper.appendChild(empty);
    }

    return wrapper;
}

function buildPlayerCard(player) {
    const card = document.createElement('div');
    card.className = 'player-card';
    if (player.id === currentPlayerId) card.classList.add('me');

    const draggable = player.id === currentPlayerId;

    if (draggable) {
        const nameInput = document.createElement('input');
        nameInput.type = 'text';
        nameInput.className = 'player-name-input';
        nameInput.maxLength = 32;
        nameInput.value = player.name || '';
        nameInput.placeholder = 'Enter name';

        const submitName = () => {
            const newName = (nameInput.value || '').trim();
            if (!newName) {
                nameInput.value = player.name || '';
                return;
            }
            if (newName === (player.name || '')) return;
            updatePlayerName(newName);
        };

        nameInput.addEventListener('click', (event) => event.stopPropagation());
        nameInput.addEventListener('mousedown', (event) => event.stopPropagation());
        nameInput.addEventListener('keydown', (event) => {
            event.stopPropagation();
            if (event.key === 'Enter') {
                event.preventDefault();
                submitName();
                nameInput.blur();
            }
        });
        nameInput.addEventListener('blur', submitName);
        card.appendChild(nameInput);
    } else {
        card.textContent = player.name;
    }

    if (draggable) {
        card.addEventListener('pointerdown', (event) => beginCardDrag(event, card));
    }

    return card;
}

// --- Pointer-based drag and drop (works with both mouse and touch) ---

const DRAG_THRESHOLD_PX = 6;
let dragState = null;

// --- Auto-scroll while dragging near the top/bottom edge of the screen ---

const EDGE_SCROLL_ZONE_PX = 60;
const EDGE_SCROLL_MAX_SPEED = 16;
let autoScrollSpeed = 0;
let autoScrollRAF = null;

function updateAutoScroll(clientY) {
    const viewportHeight = window.innerHeight;
    let speed = 0;
    if (clientY < EDGE_SCROLL_ZONE_PX) {
        speed = -EDGE_SCROLL_MAX_SPEED * (1 - clientY / EDGE_SCROLL_ZONE_PX);
    } else if (clientY > viewportHeight - EDGE_SCROLL_ZONE_PX) {
        speed = EDGE_SCROLL_MAX_SPEED * (1 - (viewportHeight - clientY) / EDGE_SCROLL_ZONE_PX);
    }
    autoScrollSpeed = speed;

    if (speed !== 0 && !autoScrollRAF) {
        autoScrollRAF = requestAnimationFrame(runAutoScroll);
    } else if (speed === 0 && autoScrollRAF) {
        cancelAnimationFrame(autoScrollRAF);
        autoScrollRAF = null;
    }
}

function runAutoScroll() {
    if (!dragState || autoScrollSpeed === 0) {
        autoScrollRAF = null;
        return;
    }
    window.scrollBy(0, autoScrollSpeed);
    if (dragState.lastClientX !== undefined) {
        updateDropTarget(findDropTargetAt(dragState.lastClientX, dragState.lastClientY));
    }
    autoScrollRAF = requestAnimationFrame(runAutoScroll);
}

function stopAutoScroll() {
    if (autoScrollRAF) {
        cancelAnimationFrame(autoScrollRAF);
        autoScrollRAF = null;
    }
    autoScrollSpeed = 0;
}

function beginCardDrag(event, card) {
    if (event.pointerType === 'mouse' && event.button !== 0) return;
    if (event.target.closest('.player-name-input')) return;
    if (dragState) return;
    event.preventDefault();

    const rect = card.getBoundingClientRect();
    dragState = {
        pointerId: event.pointerId,
        startX: event.clientX,
        startY: event.clientY,
        offsetX: event.clientX - rect.left,
        offsetY: event.clientY - rect.top,
        width: rect.width,
        card,
        ghost: null,
        active: false,
        dropTarget: null
    };
    window.addEventListener('pointermove', onCardDragMove);
    window.addEventListener('pointerup', onCardDragEnd);
    window.addEventListener('pointercancel', onCardDragCancel);
}

function onCardDragMove(event) {
    if (!dragState || event.pointerId !== dragState.pointerId) return;
    if (!dragState.active) {
        const dist = Math.hypot(event.clientX - dragState.startX, event.clientY - dragState.startY);
        if (dist < DRAG_THRESHOLD_PX) return;
        activateCardDrag();
    }
    dragState.lastClientX = event.clientX;
    dragState.lastClientY = event.clientY;
    positionDragGhost(event.clientX, event.clientY);
    updateDropTarget(findDropTargetAt(event.clientX, event.clientY));
    updateAutoScroll(event.clientY);
}

function activateCardDrag() {
    const ghost = dragState.card.cloneNode(true);
    ghost.classList.add('drag-ghost');
    ghost.classList.remove('dragging');
    ghost.style.width = `${dragState.width}px`;
    document.body.appendChild(ghost);
    dragState.ghost = ghost;
    dragState.active = true;
    dragState.card.classList.add('dragging');
}

function positionDragGhost(clientX, clientY) {
    if (!dragState.ghost) return;
    dragState.ghost.style.left = `${clientX - dragState.offsetX}px`;
    dragState.ghost.style.top = `${clientY - dragState.offsetY}px`;
}

function findDropTargetAt(clientX, clientY) {
    const el = document.elementFromPoint(clientX, clientY);
    if (!el) return null;
    return el.closest('.slot-box[data-slot-id]') || el.closest('#spectatorDropzone');
}

function updateDropTarget(target) {
    if (dragState.dropTarget === target) return;
    if (dragState.dropTarget) dragState.dropTarget.classList.remove('slot-hover');
    dragState.dropTarget = target;
    if (target) target.classList.add('slot-hover');
}

function onCardDragEnd(event) {
    if (!dragState || event.pointerId !== dragState.pointerId) return;
    const wasActive = dragState.active;
    const target = wasActive ? findDropTargetAt(event.clientX, event.clientY) : null;
    cleanupCardDrag();
    if (!target) return;

    if (target.id === 'spectatorDropzone') {
        setPlayerSlot(null);
        return;
    }
    const slotId = target.dataset.slotId;
    if (roomSlots[slotId] === currentPlayerId) return;
    if (roomSlots[slotId]) {
        updateStatus('That slot is already occupied.', 'error');
        return;
    }
    setPlayerSlot(slotId);
}

function onCardDragCancel(event) {
    if (!dragState || event.pointerId !== dragState.pointerId) return;
    cleanupCardDrag();
}

function cleanupCardDrag() {
    window.removeEventListener('pointermove', onCardDragMove);
    window.removeEventListener('pointerup', onCardDragEnd);
    window.removeEventListener('pointercancel', onCardDragCancel);
    stopAutoScroll();
    if (dragState.ghost) dragState.ghost.remove();
    if (dragState.dropTarget) dragState.dropTarget.classList.remove('slot-hover');
    dragState.card.classList.remove('dragging');
    dragState = null;
}

function updatePlayerName(name) {
    if (!currentRoom || !currentPlayerId || !lobbySocket) return;

    lobbySocket.send(JSON.stringify({
        type: 'update_player',
        room_id: currentRoom,
        player_id: currentPlayerId,
        name
    }));
}

function updateTeamName(team, name) {
    if (!currentRoom || !currentPlayerId || !lobbySocket) return;

    lobbySocket.send(JSON.stringify({
        type: 'update_team_name',
        room_id: currentRoom,
        player_id: currentPlayerId,
        team,
        name
    }));
}

function formatSlotLabel(slotId) {
    const parts = slotId.split('_');
    if (parts.length !== 4) return slotId;
    const role = parts[2];
    const idx = parts[3];
    return `${role.charAt(0).toUpperCase()}${role.slice(1)} ${idx}`;
}

function getRoleForSlot(slotId) {
    const parts = slotId.split('_');
    if (parts.length !== 4) return '';
    return parts[2];
}

function getRoleColor(role) {
    const palette = window.CLIENT_COLORS || {};
    const roles = palette.roles || {};
    const fallback = {
        keeper: '#7cfc00',
        chaser: '#ffffff',
        beater: '#000000',
        seeker: '#ffff00'
    };
    return roles[role] || fallback[role] || '#b6bfd3';
}

function setPlayerSlot(targetSlot) {
    if (!currentRoom || !currentPlayerId || !lobbySocket) return;

    lobbySocket.send(JSON.stringify({
        type: 'set_room_slot',
        room_id: currentRoom,
        player_id: currentPlayerId,
        target_slot: targetSlot
    }));
}

function toggleStartButton() {
    const startBtn = document.getElementById('startBtn');
    if (!startBtn) return;
    if (document.body.classList.contains('ingame')) {
        startBtn.classList.add('hidden');
        return;
    }

    if (isCreator) {
        startBtn.classList.remove('hidden');
    } else {
        startBtn.classList.add('hidden');
    }
}

function startGame() {
    if (!isCreator) {
        updateStatus('Only the room creator can start the game.', 'error');
        return;
    }

    if (!currentRoom || !currentPlayerId || !lobbySocket) return;

    lobbySocket.send(JSON.stringify({
        type: 'start_game',
        room_id: currentRoom,
        player_id: currentPlayerId
    }));
}

function copyRoomId() {
    if (!currentRoom) return;
    navigator.clipboard.writeText(currentRoom).then(() => {
        updateStatus('Room ID copied to clipboard!', 'success');
    }).catch((err) => {
        console.error('Copy failed', err);
        updateStatus('Failed to copy Room ID.', 'error');
    });
}

function goBackToLobby() {
    window.location.href = '/';
}

function updateStatus(message, type = 'info') {
    const status = document.getElementById('status');
    if (!status) return;

    status.textContent = message;
    status.className = `status ${type}`;
}

window.addEventListener('load', () => {
    const params = getRequiredParams();

    if (!params.roomId || !params.playerId) {
        updateStatus('Missing room_id or player_id in URL.', 'error');
        return;
    }

    // Embedded in the game's settings menu: positions only, no start or navigation.
    if (new URLSearchParams(window.location.search).get('ingame') === '1') {
        document.body.classList.add('ingame');
    }

    currentRoom = params.roomId;
    currentPlayerId = params.playerId;
    isCreator = params.creatorFlag;
    renderRoomHeader();
    toggleStartButton();
    connectLobby();
});
