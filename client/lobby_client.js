let lobbySocket = null;
let currentRoom = null;
let currentPlayerId = null;
let isCreator = false;

function connectLobby() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    lobbySocket = new WebSocket(`${protocol}//${window.location.host}/ws/lobby`);
    
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
    console.log('Lobby message:', message);
    
    if (message.type === 'room_created') {
        currentRoom = message.room_id;
        isCreator = true;
        document.getElementById('roomId').textContent = message.room_id;
        // passkey is no longer used
        document.getElementById('roomStatus').classList.remove('hidden');
        document.getElementById('waitingRoom').classList.remove('hidden');
        // store creator's player id and update players list if provided
        if (message.player_id) currentPlayerId = message.player_id;
        if (message.players) updatePlayersList(message.players);
        updateStatus(`Room created! Room ID: ${message.room_id}`);
    } else if (message.type === 'join_successful') {
        currentRoom = message.room_id;
        currentPlayerId = message.player_id;
        document.getElementById('waitingRoom').classList.remove('hidden');
        updatePlayersList(message.players);
        updateStatus('Joined room successfully!');
    } else if (message.type === 'start_successful') {
        // Server acknowledged game start and returned a player id for the creator
        currentRoom = message.room_id || currentRoom;
        if (message.player_id) currentPlayerId = message.player_id;
        // Redirect to game page with room and player id
        if (currentRoom && currentPlayerId) {
            window.location.href = `/game?room=${currentRoom}&player=${currentPlayerId}`;
        } else if (currentRoom) {
            // fallback (shouldn't normally happen)
            window.location.href = `/game?room=${currentRoom}`;
        }
    } else if (message.type === 'join_failed') {
        updateStatus('Failed to join room: ' + message.error, 'error');
    } else if (message.type === 'rooms_list') {
        displayAvailableRooms(message.rooms);
    } else if (message.type === 'player_updated' || message.type === 'players_updated') {
        // Server sent updated players list after a save/update
        if (message.players) updatePlayersList(message.players);
    }
}

function createRoom() {
    const playerName = document.getElementById('playerName').value;
    if (!playerName) {
        updateStatus('Please enter your name', 'error');
        return;
    }
    
    if (!lobbySocket) connectLobby();
    
    lobbySocket.send(JSON.stringify({
        type: 'create_room',
        player_name: playerName
    }));
}

function showJoinRoom() {
    // Show inline quick-join form below the buttons
        // Ensure we have a lobby connection available (connect if not)
        if (!lobbySocket) connectLobby();

        const inline = document.getElementById('inlineJoinForm');
        if (inline) {
            inline.classList.remove('hidden');
            populateJoinModalDefaults();
            loadAvailableRooms();
            // focus the room id input for quicker typing
            const rid = document.getElementById('joinRoomIdInline');
            if (rid) rid.focus();
            return;
    }

    // Fallback to modal if inline form not present
    const modal = document.getElementById('joinRoomModal');
    if (modal) {
        modal.classList.remove('hidden');
        populateJoinModalDefaults();
        loadAvailableRooms();
    }
}

// Populate join modal fields from the main player setup when opening
function populateJoinModalDefaults() {
    const mainName = document.getElementById('playerName').value;
    // Fill inline inputs first (if present)
    const inlineName = document.getElementById('joinPlayerNameInline');
    if (inlineName && mainName) inlineName.value = mainName;

    // Also fill modal input if it exists
    const modalName = document.getElementById('joinPlayerName');
    if (modalName && mainName) modalName.value = mainName;
}

function closeJoinRoom() {
    document.getElementById('joinRoomModal').classList.add('hidden');
}

function loadAvailableRooms() {
    if (!lobbySocket) connectLobby();
    
    lobbySocket.send(JSON.stringify({
        type: 'list_rooms'
    }));
}

function displayAvailableRooms(rooms) {
    const container = document.getElementById('availableRooms');
    container.innerHTML = '';
    
    if (rooms.length === 0) {
        container.innerHTML = '<p>No available rooms</p>';
        return;
    }
    
    rooms.forEach(room => {
        const div = document.createElement('div');
        div.className = 'room-item';
        div.innerHTML = `
            <p><strong>${room.creator_name}'s Room</strong> (${room.players_count}/${room.max_players})</p>
            <button onclick="selectRoom('${room.room_id}')" class="btn btn-small">Select</button>
        `;
        container.appendChild(div);
    });
}

function selectRoom(roomId) {
    document.getElementById('joinRoomId').value = roomId;
}

function joinRoom() {
    // Prefer inline inputs (shown after clicking Join). Fall back to modal inputs, then main player name.
    const roomIdEl = document.getElementById('joinRoomIdInline') || document.getElementById('joinRoomId');
    const joinNameEl = document.getElementById('joinPlayerNameInline') || document.getElementById('joinPlayerName');

        const roomId = roomIdEl ? roomIdEl.value.trim() : '';
        const playerName = (joinNameEl && joinNameEl.value) ? joinNameEl.value : document.getElementById('playerName').value;

        console.log('Attempting to join room', { roomId, playerName });

        if (!roomId) {
            updateStatus('Please enter room ID', 'error');
            return;
        }
    
    if (!lobbySocket) connectLobby();
    
    lobbySocket.send(JSON.stringify({
        type: 'join_room',
        room_id: roomId,
        player_name: playerName
    }));
    
    // Hide inline form if present, otherwise close modal
    const inline = document.getElementById('inlineJoinForm');
    if (inline) inline.classList.add('hidden');
    else closeJoinRoom();
}

function copyRoomId() {
    const roomIdEl = document.getElementById('roomId');
    if (!roomIdEl) {
        updateStatus('No Room ID to copy', 'error');
        return;
    }
    const roomId = roomIdEl.textContent || roomIdEl.innerText || '';
    if (!roomId) {
        updateStatus('No Room ID to copy', 'error');
        return;
    }

    navigator.clipboard.writeText(roomId).then(() => {
        updateStatus('Room ID copied to clipboard!', 'success');
    }).catch((err) => {
        console.error('Copy failed', err);
        updateStatus('Failed to copy Room ID', 'error');
    });
}

function hideInlineJoin() {
    const inline = document.getElementById('inlineJoinForm');
    if (inline) inline.classList.add('hidden');
}

function updatePlayersList(players) {
    const list = document.getElementById('playersList');
    list.innerHTML = '';
    
    players.forEach(player => {
        const div = document.createElement('div');
        div.className = 'player-item';
        div.textContent = `${player.name} - Team ${player.team} (${player.role})`;
        list.appendChild(div);
    });
    
    if (isCreator && players.length > 0) {
        document.getElementById('startBtn').classList.remove('hidden');
    }
}

function updatePlayerSelection() {
    if (!currentRoom || !currentPlayerId) return;

    const teamEl = document.getElementById('waitingTeamSelect');
    const roleEl = document.getElementById('waitingRoleSelect');
    const team = teamEl ? parseInt(teamEl.value) : 0;
    const role = roleEl ? roleEl.value : 'chaser';

    if (!lobbySocket) connectLobby();

    lobbySocket.send(JSON.stringify({
        type: 'update_player',
        room_id: currentRoom,
        player_id: currentPlayerId,
        team: team,
        role: role
    }));

    updateStatus('Saving selection...');
}

function startGame() {
    if (!currentRoom) return;

    if (!lobbySocket) connectLobby();

    // Tell the server (room creator) to start the game. Server will reply with
    // a `start_successful` message that includes a player_id for the creator.
    lobbySocket.send(JSON.stringify({
        type: 'start_game',
        room_id: currentRoom
    }));
}

function copyToClipboard() {
    const passkey = document.getElementById('passkey').textContent;
    navigator.clipboard.writeText(passkey).then(() => {
        updateStatus('Passkey copied to clipboard!', 'success');
    });
}

function updateStatus(message, type = 'info') {
    const status = document.getElementById('status');
    status.textContent = message;
    status.className = `status ${type}`;
}

// Connect to lobby on page load
window.addEventListener('load', () => {
    connectLobby();
});
