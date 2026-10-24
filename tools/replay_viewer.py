"""Interactive replay of a room state.jsonl log: pause, play forward/backward, jump to a tick.

    python tools/replay_viewer.py [state.jsonl] [--start TICK]

Without a file the newest *_state.jsonl in game_data/logs is used. Keys:
    space play/pause   r reverse direction   left/right step 1 tick (shift: 20)
    up/down speed (x0.25 to x16, also the speed slider)   [ / ] jump 10 game s   home/end start/end   g jump to tick (type, enter)
    click or drag the slider to scrub.
"""
import argparse
import sys
import time
from pathlib import Path

import numpy as np
import matplotlib

if __name__ == '__main__':
    matplotlib.use('TkAgg')
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, Rectangle
from matplotlib.widgets import Slider

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config import Config
from room_jsonl_logger import RoomJsonlStateReader

TEAM_COLORS = {0: '#8e44ad', 1: '#e67e22'}  # purple / orange
ROLE_MARKERS = {'KEEPER': 's', 'CHASER': 'o', 'BEATER': '^', 'SEEKER': 'D'}


def latest_state_log() -> Path:
    logs = [p for p in (ROOT / 'game_data' / 'logs').glob('*_state.jsonl') if p.stat().st_size > 0]
    if not logs:
        raise SystemExit('no state.jsonl found in game_data/logs')
    return max(logs, key=lambda p: p.stat().st_mtime)


class Replay:
    """Per-tick compact frames of a log, held in memory for instant random access."""

    def __init__(self, path: Path):
        self.path = path
        ticks = []
        self.frames = []
        reader = RoomJsonlStateReader(path)
        state = None
        for tick, state in reader.iter_game_states():
            ticks.append(tick)
            self.frames.append(self._frame(state))
            if state.is_game_over:
                break
        self.ticks = np.array(ticks)
        self.times = np.array([f['time'] for f in self.frames])
        self.hoops = [(h.position.x, h.position.y, h.radius, h.team) for h in state.hoops.values()]
        self.bounds = (state.boundaries_x, state.boundaries_y)
        self.midline_x = state.midline_x

    @staticmethod
    def _frame(state):
        players = [(p.id, p.team, p.role.name, p.position.x, p.position.y, p.is_knocked_out, p.has_ball)
                   for p in state.players.values()]
        balls = [(b.id, b.ball_type.name, b.position.x, b.position.y, b.holder_id) for b in state.balls.values()]
        flag = state.flag_runner
        flag_pos = (flag.position.x, flag.position.y) if flag is not None and state.flag_runner_on_pitch else None
        return dict(time=state.game_time, score=tuple(state.score), players=players, balls=balls, flag=flag_pos,
                    live=state.is_game_live, over=state.is_game_over, overtime=state.is_overtime)


class Viewer:
    SPEEDS = [0.25, 0.5, 1, 2, 4, 8, 16]

    def __init__(self, replay: Replay, start: int = 0):
        self.r = replay
        self.i = min(int(np.searchsorted(replay.ticks, start)), len(replay.ticks) - 1)
        self.playing = False
        self.direction = 1
        self.speed_idx = 2
        self.goto_buffer = None
        self._updating_slider = False
        self._last = time.perf_counter()
        self._build()

    def _build(self):
        (x0, x1), (y0, y1) = self.r.bounds
        self.fig = plt.figure(figsize=(13, 7.5))
        self.ax = self.fig.add_axes([0.03, 0.14, 0.94, 0.80])
        self.ax.set_xlim(x0 - 1, x1 + 1)
        self.ax.set_ylim(y1 + 1, y0 - 1)  # y down like the client
        self.ax.set_aspect('equal')
        self.ax.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0, fill=False, ec='k'))
        self.ax.axvline(self.r.midline_x, color='0.8', lw=1)
        for hx, hy, hr, team in self.r.hoops:
            self.ax.add_patch(Circle((hx, hy), max(hr, 0.3), fill=False, ec=TEAM_COLORS.get(team, 'k'), lw=2))
        self.artists = []
        self.title = self.ax.set_title('')
        sax = self.fig.add_axes([0.08, 0.04, 0.84, 0.03])
        self.slider = Slider(sax, 'tick', int(self.r.ticks[0]), int(self.r.ticks[-1]),
                             valinit=int(self.r.ticks[self.i]), valstep=1)
        self.slider.on_changed(self._on_slider)
        spax = self.fig.add_axes([0.08, 0.09, 0.2, 0.03])
        self.speed_slider = Slider(spax, 'speed', 0, len(self.SPEEDS) - 1, valinit=self.speed_idx, valstep=1,
                                   valfmt='%d')
        self.speed_slider.valtext.set_text(f'x{self.SPEEDS[self.speed_idx]}')
        self.speed_slider.on_changed(self._on_speed_slider)
        self.fig.canvas.mpl_connect('key_press_event', self._on_key)
        self.timer = self.fig.canvas.new_timer(interval=30)
        self.timer.add_callback(self._on_timer)
        self.timer.start()
        self.draw()

    def draw(self):
        for a in self.artists:
            a.remove()
        self.artists = []
        f = self.r.frames[self.i]
        for pid, team, role, x, y, ko, has_ball in f['players']:
            color = TEAM_COLORS.get(team, 'k')
            self.artists.append(self.ax.scatter([x], [y], s=150, marker=ROLE_MARKERS.get(role, 'o'),
                                                c='none' if ko else color, edgecolors=color,
                                                linewidths=3 if has_ball else 1, zorder=3))
            self.artists.append(self.ax.text(x, y - 0.8, pid[-3:], fontsize=7, ha='center', color=color))
        for bid, btype, x, y, holder in f['balls']:
            volley = btype == 'VOLLEYBALL'
            self.artists.append(self.ax.scatter([x], [y], s=60 if volley else 35, c='#f1c40f' if volley else '#222',
                                                edgecolors='k', zorder=4))
        if f['flag'] is not None:
            self.artists.append(self.ax.scatter([f['flag'][0]], [f['flag'][1]], s=90, marker='*', c='g', zorder=4))
        status = 'PLAY' if self.playing and self.direction > 0 else 'REVERSE' if self.playing else 'PAUSED'
        self.title.set_text(
            f"tick {self.r.ticks[self.i]}  |  game time {f['time']:.1f}s  |  "
            f"score purple {f['score'][0]} : {f['score'][1]} orange"
            f"{'  | overtime' if f['overtime'] else ''}{'  | not live' if not f['live'] else ''}"
            f"  |  {status} x{self.SPEEDS[self.speed_idx]}")
        self.fig.canvas.draw_idle()

    def seek(self, index):
        self.i = int(min(max(index, 0), len(self.r.ticks) - 1))
        self._updating_slider = True
        self.slider.set_val(int(self.r.ticks[self.i]))
        self._updating_slider = False
        self.draw()

    def seek_time(self, delta_game_seconds):
        target = self.r.times[self.i] + delta_game_seconds
        self.seek(int(np.argmin(np.abs(self.r.times - target))))

    def _on_slider(self, value):
        if not self._updating_slider:
            self.i = min(int(np.searchsorted(self.r.ticks, value)), len(self.r.ticks) - 1)
            self.draw()

    def _set_speed(self, idx):
        self.speed_idx = int(min(max(idx, 0), len(self.SPEEDS) - 1))
        if int(self.speed_slider.val) != self.speed_idx:
            self.speed_slider.eventson = False  # avoid re-entering _on_speed_slider
            self.speed_slider.set_val(self.speed_idx)
            self.speed_slider.eventson = True
        self.speed_slider.valtext.set_text(f'x{self.SPEEDS[self.speed_idx]}')
        self.draw()

    def _on_speed_slider(self, value):
        self._set_speed(int(value))

    def _on_timer(self):
        now = time.perf_counter()
        elapsed, self._last = now - self._last, now
        if not self.playing:
            return
        step = max(1, int(round(elapsed * Config.FPS * self.SPEEDS[self.speed_idx]))) * self.direction
        j = self.i + step
        if j < 0 or j >= len(self.r.ticks):
            self.playing = False
        self.seek(j)

    def _on_key(self, e):
        k = e.key
        if self.goto_buffer is not None:
            if k == 'enter':
                if self.goto_buffer:
                    self.seek(int(np.searchsorted(self.r.ticks, int(self.goto_buffer))))
                self.goto_buffer = None
                return
            if k == 'escape':
                self.goto_buffer = None
                self.draw()
                return
            if k.isdigit():
                self.goto_buffer += k
            elif k == 'backspace':
                self.goto_buffer = self.goto_buffer[:-1]
            self.title.set_text(f'go to tick: {self.goto_buffer}')
            self.fig.canvas.draw_idle()
            return
        if k == ' ':
            self.playing = not self.playing
        elif k == 'r':
            self.direction *= -1
            self.playing = True
        elif k in ('left', 'right', 'shift+left', 'shift+right'):
            self.playing = False
            self.seek(self.i + (20 if k.startswith('shift') else 1) * (1 if k.endswith('right') else -1))
            return
        elif k == 'up':
            self._set_speed(self.speed_idx + 1)
            return
        elif k == 'down':
            self._set_speed(self.speed_idx - 1)
            return
        elif k in ('[', ']'):
            self.seek_time(-10 if k == '[' else 10)
            return
        elif k == 'home':
            self.seek(0)
            return
        elif k == 'end':
            self.seek(len(self.r.ticks) - 1)
            return
        elif k == 'g':
            self.goto_buffer = ''
            self.title.set_text('go to tick: ')
            self.fig.canvas.draw_idle()
            return
        self.draw()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('state_file', nargs='?', type=Path)
    ap.add_argument('--start', type=int, default=0)
    args = ap.parse_args()
    path = args.state_file or latest_state_log()
    print(f'loading {path} ...', flush=True)
    t0 = time.perf_counter()
    replay = Replay(path)
    print(f'{len(replay.ticks)} ticks (tick {replay.ticks[0]}-{replay.ticks[-1]}) in {time.perf_counter() - t0:.1f}s')
    Viewer(replay, args.start)
    plt.show()


if __name__ == '__main__':
    main()
