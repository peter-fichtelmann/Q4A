// Tutorial loader (classic script, included on lobby/room/game pages).
// No-op unless the tutorial is active; on the lobby it only wires the entry button.
(function () {
    function tutorialState() {
        try {
            return JSON.parse(sessionStorage.getItem('q4a_tutorial'));
        } catch (e) {
            return null;
        }
    }

    function injectCss() {
        if (document.querySelector('link[href="/client/tutorial/tutorial.css"]')) return;
        var link = document.createElement('link');
        link.rel = 'stylesheet';
        link.href = '/client/tutorial/tutorial.css';
        document.head.appendChild(link);
    }

    var path = window.location.pathname;
    var params = new URLSearchParams(window.location.search);
    var state = tutorialState();
    var active = (state && state.active) || params.get('tutorial') === '1';

    function start() {
        if (path === '/' || path === '/index.html') {
            // The tutorial never passes through the lobby (its button saves fresh state
            // only once its room exists), so state here is left over from a tutorial
            // abandoned without Exit and would take over the next normal room.
            try {
                sessionStorage.removeItem('q4a_tutorial');
            } catch (e) { /* ignore */ }
            injectCss();
            import('/client/tutorial/lobby_tutorial.js');
        } else if (path.indexOf('/room') === 0 && active) {
            injectCss();
            import('/client/tutorial/steps_room.js');
        } else if (path.indexOf('/game') === 0 && active) {
            injectCss();
            import('/client/tutorial/steps_game.js');
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', start);
    } else {
        start();
    }
})();
