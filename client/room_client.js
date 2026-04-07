let lobbySocket = null;
let currentRoom = null;
let currentPlayerId = null;
let isCreator = false;

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
    console.log('Room lobby message:', message);

    if (message.type === 'attach_successful') {
        currentRoom = message.room_id;
        currentPlayerId = message.player_id;
        isCreator = Boolean(message.is_creator);
        renderRoomHeader();
        if (message.players) {
            updatePlayersList(message.players);
            syncOwnSelection(message.players);
        }
        toggleStartButton();
        updateStatus('Connected to room lobby.', 'success');
    } else if (message.type === 'attach_failed') {
        updateStatus(`Unable to attach to room: ${message.error}`, 'error');
    } else if (message.type === 'players_updated') {
        if (message.players) {
            updatePlayersList(message.players);
            syncOwnSelection(message.players);
        }
    } else if (message.type === 'update_failed') {
        updateStatus(message.error || 'Failed to update player selection.', 'error');
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

function updatePlayersList(players) {
    const list = document.getElementById('playersList');
    if (!list) return;

    list.innerHTML = '';

    players.forEach((player) => {
        const div = document.createElement('div');
        div.className = 'player-item';
        div.textContent = `${player.name} - Team ${player.team} (${player.role})`;
        list.appendChild(div);
    });
}

function syncOwnSelection(players) {
    const me = players.find((p) => p.id === currentPlayerId);
    if (!me) return;

    const nameEl = document.getElementById('waitingPlayerName');
    const teamEl = document.getElementById('waitingTeamSelect');
    const roleEl = document.getElementById('waitingRoleSelect');
    if (nameEl) nameEl.value = String(me.name || '');
    if (teamEl) teamEl.value = String(me.team);
    if (roleEl) roleEl.value = String(me.role);
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

function updatePlayerSelection() {
    if (!currentRoom || !currentPlayerId || !lobbySocket) return;

    const nameEl = document.getElementById('waitingPlayerName');
    const teamEl = document.getElementById('waitingTeamSelect');
    const roleEl = document.getElementById('waitingRoleSelect');
    const name = (nameEl && nameEl.value) ? nameEl.value.trim() : 'Player';
    const team = teamEl ? parseInt(teamEl.value, 10) : 0;
    const role = roleEl ? roleEl.value : 'chaser';

    if (!name) {
        updateStatus('Please enter a player name.', 'error');
        return;
    }

    lobbySocket.send(JSON.stringify({
        type: 'update_player',
        room_id: currentRoom,
        player_id: currentPlayerId,
        name,
        team,
        role
    }));

    updateStatus('Saving selection...');
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
