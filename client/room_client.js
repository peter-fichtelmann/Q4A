let lobbySocket = null;
let currentRoom = null;
let currentPlayerId = null;
let isCreator = false;
let roomPlayers = [];
let roomSlots = {};

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
        applyRoomState(message.players || [], message.slots || {});
        toggleStartButton();
        updateStatus('Connected to room lobby.', 'success');
    } else if (message.type === 'players_updated') {
        applyRoomState(message.players || [], message.slots || {});
    } else if (message.type === 'attach_failed') {
        updateStatus(`Unable to attach to room: ${message.error}`, 'error');
    } else if (message.type === 'update_failed') {
        updateStatus(message.error || 'Failed to update room assignment.', 'error');
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

function applyRoomState(players, slots) {
    roomPlayers = players;
    roomSlots = slots;
    renderBoard();
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

    spectatorEl.addEventListener('dragover', (event) => {
        event.preventDefault();
        spectatorEl.classList.add('slot-hover');
    });
    spectatorEl.addEventListener('dragleave', () => spectatorEl.classList.remove('slot-hover'));
    spectatorEl.addEventListener('drop', (event) => {
        event.preventDefault();
        spectatorEl.classList.remove('slot-hover');
        const draggedPlayerId = event.dataTransfer.getData('text/plain');
        if (draggedPlayerId !== currentPlayerId) return;
        setPlayerSlot(null);
    });

    const slottedPlayerIds = new Set(Object.values(roomSlots).filter((pid) => pid));
    roomPlayers
        .filter((p) => !slottedPlayerIds.has(p.id))
        .forEach((p) => spectatorEl.appendChild(buildPlayerCard(p)));
}

function buildSlotElement(slotId, playersById) {
    const wrapper = document.createElement('div');
    wrapper.className = 'slot-box';
    wrapper.dataset.slotId = slotId;

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

    wrapper.addEventListener('dragover', (event) => {
        event.preventDefault();
        wrapper.classList.add('slot-hover');
    });
    wrapper.addEventListener('dragleave', () => wrapper.classList.remove('slot-hover'));
    wrapper.addEventListener('drop', (event) => {
        event.preventDefault();
        wrapper.classList.remove('slot-hover');
        const draggedPlayerId = event.dataTransfer.getData('text/plain');
        if (draggedPlayerId !== currentPlayerId) return;
        if (roomSlots[slotId] && roomSlots[slotId] !== draggedPlayerId) {
            updateStatus('That slot is already occupied.', 'error');
            return;
        }
        setPlayerSlot(slotId);
    });

    return wrapper;
}

function buildPlayerCard(player) {
    const card = document.createElement('div');
    card.className = 'player-card';
    if (player.id === currentPlayerId) card.classList.add('me');

    const draggable = player.id === currentPlayerId;
    card.draggable = draggable;

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
        card.addEventListener('dragstart', (event) => {
            event.dataTransfer.setData('text/plain', player.id);
            card.classList.add('dragging');
        });
        card.addEventListener('dragend', () => card.classList.remove('dragging'));
    }

    return card;
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

function formatSlotLabel(slotId) {
    const parts = slotId.split('_');
    if (parts.length !== 4) return slotId;
    const role = parts[2];
    const idx = parts[3];
    return `${role.charAt(0).toUpperCase()}${role.slice(1)} ${idx}`;
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

    currentRoom = params.roomId;
    currentPlayerId = params.playerId;
    isCreator = params.creatorFlag;
    renderRoomHeader();
    toggleStartButton();
    connectLobby();
});
