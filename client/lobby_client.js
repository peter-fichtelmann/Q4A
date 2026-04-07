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
        currentPlayerId = message.player_id;
        isCreator = true;
        document.getElementById('roomId').textContent = message.room_id;
        document.getElementById('roomStatus').classList.remove('hidden');
        updateStatus(`Room created! Room ID: ${message.room_id}`);
        redirectToRoomLobby(message.room_id, message.player_id, true);
    } else if (message.type === 'join_successful') {
        currentRoom = message.room_id;
        currentPlayerId = message.player_id;
        updateStatus('Joined room successfully!');
        redirectToRoomLobby(message.room_id, message.player_id, false);
    } else if (message.type === 'join_failed') {
        updateStatus('Failed to join room: ' + message.error, 'error');
    } else if (message.type === 'rooms_list') {
        displayAvailableRooms(message.rooms);
    }
}

function redirectToRoomLobby(roomId, playerId, creator) {
    if (!roomId || !playerId) {
        updateStatus('Missing room or player id from server.', 'error');
        return;
    }

    const params = new URLSearchParams({
        room_id: roomId,
        player_id: playerId,
        creator: creator ? '1' : '0'
    });
    window.location.href = `/room?${params.toString()}`;
}

function createRoom() {
    if (!lobbySocket) connectLobby();
    
    lobbySocket.send(JSON.stringify({
        type: 'create_room',
        player_name: 'Player'
    }));
}

function showJoinRoom() {
    // Show inline quick-join form below the buttons.
    if (!lobbySocket) connectLobby();

    const inline = document.getElementById('inlineJoinForm');
    if (inline) {
        inline.classList.remove('hidden');
        loadAvailableRooms();
        const rid = document.getElementById('joinRoomIdInline');
        if (rid) rid.focus();
        return;
    }

    // Fallback to modal if inline form not present
    const modal = document.getElementById('joinRoomModal');
    if (modal) {
        modal.classList.remove('hidden');
        loadAvailableRooms();
    }
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
    if (!container) return;

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
    const inlineId = document.getElementById('joinRoomIdInline');
    const modalId = document.getElementById('joinRoomId');
    if (inlineId) inlineId.value = roomId;
    if (modalId) modalId.value = roomId;
}

function joinRoom() {
    // Prefer inline input (shown after clicking Join). Fall back to modal input.
    const roomIdEl = document.getElementById('joinRoomIdInline') || document.getElementById('joinRoomId');

    const roomId = roomIdEl ? roomIdEl.value.trim() : '';

    console.log('Attempting to join room', { roomId });

    if (!roomId) {
        updateStatus('Please enter room ID', 'error');
        return;
    }
    
    if (!lobbySocket) connectLobby();
    
    lobbySocket.send(JSON.stringify({
        type: 'join_room',
        room_id: roomId,
        player_name: 'Player'
    }));
    
    // Hide inline form if present, otherwise close modal.
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

function updateStatus(message, type = 'info') {
    const status = document.getElementById('status');
    status.textContent = message;
    status.className = `status ${type}`;
}

// Connect to lobby on page load
window.addEventListener('load', () => {
    connectLobby();
});
