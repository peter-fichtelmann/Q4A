// Lobby entry point: renders the tutorial button above Create/Join Room and
// creates a private tutorial room via its own lobby websocket.

function updateStatus(message, type) {
    const status = document.getElementById('status');
    if (!status) return;
    status.textContent = message;
    status.className = `status ${type || 'info'}`;
}

function startTutorial(button) {
    button.disabled = true;
    updateStatus('Summoning Coach Donatella…', 'info');
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const socket = new WebSocket(`${protocol}//${window.location.host}/ws/lobby`);

    socket.onopen = () => {
        socket.send(JSON.stringify({ type: 'create_tutorial_room' }));
    };

    socket.onmessage = (event) => {
        let message;
        try {
            message = JSON.parse(event.data);
        } catch (e) {
            return;
        }
        if (message.type === 'room_created') {
            try {
                sessionStorage.setItem('q4a_tutorial', JSON.stringify({
                    active: true,
                    section: 'introduction',
                    step: 0,
                }));
            } catch (e) { /* ignore */ }
            const params = new URLSearchParams({
                room_id: message.room_id,
                player_id: message.player_id,
                creator: '1',
                tutorial: '1',
            });
            window.location.href = `/room?${params.toString()}`;
        }
    };

    socket.onerror = () => {
        button.disabled = false;
        updateStatus('Could not start the tutorial. Please try again.', 'error');
    };
}

function renderButton() {
    const actions = document.querySelector('.actions');
    if (!actions || document.querySelector('.tutorial-entry')) return;

    const wrapper = document.createElement('div');
    wrapper.className = 'tutorial-entry';

    const button = document.createElement('button');
    button.className = 'tut-lobby-btn';
    button.innerHTML = '🐾 Play the Tutorial';
    button.addEventListener('click', () => startTutorial(button));

    const hint = document.createElement('div');
    hint.className = 'tut-lobby-hint';
    hint.textContent = 'New to Q4A? Mascot Donatella will show you the ropes.';

    wrapper.appendChild(button);
    wrapper.appendChild(hint);
    actions.parentNode.insertBefore(wrapper, actions);
}

renderButton();
