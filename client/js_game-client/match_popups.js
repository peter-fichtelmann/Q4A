// The two white boxes that see a match out: the catch-review box, up while the
// server holds the game on a flag catch, and the game over box that follows it.
//
// The server freezes the match for `flag_catch_continue_timer_total` game seconds
// when a seeker catches the flag runner (flag_runner_logic.resolve_flag_catch) and
// counts `flag_catch_continue_timer` down to zero. This module reads that countdown
// out of the state and stages the message off it:
//
//   full .. half   "was it a good catch?"
//   half .. zero   the verdict, then either the overtime note (fading out as play
//                  is about to resume) or the final score
//   zero           `is_game_over` puts the game over box up instead
//
// Built in JS with inline styles like the rest of the game-page chrome (fullscreen,
// player switch, mute buttons). The match state arrives as an argument, so the only
// imports are for the game over box's return-to-lobby button; neither module reaches
// back here, so there is no cycle.

import { returnToLobby } from './network.js';
import { onActivate } from './utils.js';

const TEAM_LABELS = ['Team A', 'Team B'];

let reviewBox = null;
let gameOverBox = null;

// Slightly transparent white, centred over the pitch. It only ever shows while
// play is stopped, so covering the middle costs nothing.
const BOX_STYLE = 'position: fixed; top: 50%; left: 50%; transform: translate(-50%, -50%); '
  + 'z-index: 1100; max-width: min(560px, 80vw); padding: 18px 26px; '
  + 'background: rgba(255,255,255,0.82); color: #14181f; '
  + 'border: 1px solid rgba(255,255,255,0.9); border-radius: 12px; '
  + 'box-shadow: 0 6px 24px rgba(0,0,0,0.35); '
  + 'font-family: sans-serif; font-size: 18px; line-height: 1.45; text-align: center; '
  + 'pointer-events: none; user-select: none;';

// Dark on the white box, and the one thing in either popup that takes clicks back
// (the boxes themselves let them through to the pitch).
const LOBBY_BUTTON_STYLE = 'margin-top: 16px; pointer-events: auto; cursor: pointer; '
  + 'padding: 8px 18px; font-family: inherit; font-size: 16px; '
  + 'background: rgba(20,24,31,0.9); color: #ffffff; '
  + 'border: 1px solid rgba(20,24,31,0.35); border-radius: 8px; '
  + 'transition: all 0.2s ease; user-select: none; touch-action: manipulation;';

function lobbyButton() {
  const button = document.createElement('button');
  button.id = 'returnToLobbyButton';
  button.textContent = 'Return to lobby';
  button.style.cssText = LOBBY_BUTTON_STYLE;
  button.addEventListener('mouseenter', () => { button.style.transform = 'scale(1.05)'; });
  button.addEventListener('mouseleave', () => { button.style.transform = 'scale(1)'; });
  onActivate(button, () => returnToLobby());
  return button;
}

// The text sits in its own child so `setLines` can rebuild it without taking the
// return-to-lobby button (a sibling) with it.
function ensureBox(existing, id, withLobbyButton = false) {
  if (existing) return existing;
  const box = document.createElement('div');
  box.id = id;
  box.style.cssText = BOX_STYLE;
  box.hidden = true;
  const lines = document.createElement('div');
  lines.className = 'popup-lines';
  box.appendChild(lines);
  if (withLobbyButton) box.appendChild(lobbyButton());
  document.body.appendChild(box);
  return box;
}

/** Put `lines` in the box, one per row, rebuilding only when the text changed. */
function setLines(box, lines) {
  const text = lines.join('\n');
  if (box.dataset.text === text) return;
  box.dataset.text = text;
  box.querySelector('.popup-lines').replaceChildren(...lines.map((line) => {
    const row = document.createElement('div');
    row.textContent = line;
    return row;
  }));
}

/**
 * A team's score, with a star after it when that team caught the flag.
 *
 * Exported because the scorebug carries the same star as the popups.
 */
export function teamScoreText(gameState, teamIndex) {
  const score = Number(gameState && gameState.score && gameState.score[teamIndex]) || 0;
  const caughtTeam = gameState ? gameState.flag_catched_team : null;
  return `${score}${caughtTeam === teamIndex ? '*' : ''}`;
}

function scoreLine(gameState) {
  return `A ${teamScoreText(gameState, 0)} - ${teamScoreText(gameState, 1)} B`;
}

/** Stage both boxes for the current state. Safe to call on every frame. */
export function updateMatchPopups(gameState) {
  reviewBox = ensureBox(reviewBox, 'flagCatchReviewBox');
  gameOverBox = ensureBox(gameOverBox, 'gameOverBox', true);
  if (!gameState) return;

  const caughtTeam = gameState.flag_catched_team;
  const hasCatch = caughtTeam === 0 || caughtTeam === 1;
  const isGameOver = gameState.is_game_over === true;

  if (isGameOver) {
    setLines(gameOverBox, [`Game over! The final score is ${scoreLine(gameState)}.`]);
    gameOverBox.style.opacity = '1';
    gameOverBox.hidden = false;
  } else {
    gameOverBox.hidden = true;
  }

  // Only up while the server actually has the match stopped on a catch: in overtime
  // play resumes with `flag_catched_team` still set (the star has to stay), and the
  // game over box takes over once the countdown has run out.
  if (!hasCatch || gameState.is_game_live !== false || isGameOver) {
    reviewBox.hidden = true;
    return;
  }

  const total = Number(gameState.flag_catch_continue_timer_total) || 0;
  const remaining = Math.max(0, Number(gameState.flag_catch_continue_timer) || 0);
  const half = total / 2;

  const lines = [`The flag was caught by ${TEAM_LABELS[caughtTeam]}, but was it a good catch?`];
  let opacity = 1;
  if (total > 0 && remaining <= half) {
    lines.push('The catch is good!');
    if (gameState.is_overtime) {
      const setScore = (gameState.set_score === null || gameState.set_score === undefined)
        ? '-' : gameState.set_score;
      lines.push(`Continuing to overtime. Set score is ${setScore}. `
        + `Current score is ${scoreLine(gameState)}.`);
      // Fade across the second half, so the box is gone exactly as play resumes.
      opacity = half > 0 ? Math.max(0, Math.min(1, remaining / half)) : 0;
    } else {
      lines.push(`Game over! The final score is ${scoreLine(gameState)}.`);
    }
  }

  setLines(reviewBox, lines);
  reviewBox.style.opacity = String(opacity);
  reviewBox.hidden = false;
}
