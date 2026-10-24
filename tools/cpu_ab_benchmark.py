"""
Headless CPU-vs-CPU A/B benchmark for the computer player.

Each team is driven by its own ComputerPlayerOrchestrator built from Config.COMPUTER_PLAYER_KWARGS
deep-merged with an override (config A or B). Every seed is played twice with A and B on swapped
sides, so pitch side and team order do not bias the comparison. Each instance only steers its own
team, i.e. it treats the opponents like humans, which is the CPU-vs-human situation of a real game.
The instance of the defending team runs first, as defence runs before attack inside one orchestrator.

Reported per config: goal difference per game (mean +- standard error), goals per possession,
shots, passes, knockouts suffered, volleyball turnovers suffered by rule, move endings, and the
cost of make_move.

Usage (from anywhere, with the q4a conda env):
    python tools/cpu_ab_benchmark.py --seeds 1-5 --ticks 6000 --a '{}' --b '{"box_defence_probability": 1}'
    python tools/cpu_ab_benchmark.py --b overrides.json --jobs 4
Overrides are JSON strings or paths to JSON files; a null value removes the key (e.g. to disable a move).
"""
import argparse
import copy
import itertools
import json
import logging
import math
import os
import random
import sys
import time
import uuid
from collections import Counter
from multiprocessing import Pool

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
os.chdir(REPO_ROOT) # main.py mounts client/ relative to the working directory

# reproducible player ids, so set iteration orders and traces repeat per seed
_uuid_counter = itertools.count()
uuid.uuid4 = lambda: uuid.UUID(int=next(_uuid_counter))

import main
from config import Config
from core.game_logic.game_logic import GameLogic

ROLES = ['keeper', 'chaser', 'chaser', 'chaser', 'beater', 'beater', 'seeker']


def deep_merge(base: dict, override: dict) -> dict:
    """Merge `override` into a copy of `base`; nested dicts are merged, None removes the key."""
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if value is None:
            merged.pop(key, None)
        elif isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def load_override(text: str) -> dict:
    """JSON string or path to a JSON file."""
    if os.path.isfile(text):
        with open(text, encoding='utf-8') as file:
            return json.load(file)
    return json.loads(text)


class LogCounter(logging.Handler):
    """Counts the computer player log lines that matter for the comparison, per team."""

    def __init__(self, state):
        super().__init__(logging.INFO)
        self.state = state
        self.counts = Counter() # (team, key) -> count

    def _player_team(self, player_id):
        player = self.state.players.get(player_id)
        return player.team if player is not None else None

    def emit(self, record):
        msg, args = record.msg, record.args
        if msg.startswith('Scoring on hoop'):
            hoop = self.state.hoops.get(args[0])
            if hoop is not None:
                self.counts[(1 - hoop.team, 'shots')] += 1
        elif msg.startswith('Passing from player'):
            self.counts[(self._player_team(args[0]), 'passes')] += 1
        elif msg.startswith('VolleyballShift pass') or msg.startswith('VolleyballDrive pass'):
            self.counts[(self._player_team(args[1]), 'passes')] += 1
        elif msg.startswith('Move ended'):
            name, team, status, reason = args[:4]
            self.counts[(team, f'move {name}:{status}:{reason}')] += 1


def play(seed: int, ticks: int, configs: dict, a_team: int) -> dict:
    """One game; config 'A' drives `a_team`, 'B' the other team. Returns counters keyed by config label."""
    global _uuid_counter
    _uuid_counter = itertools.count()
    random.seed(seed)
    room = main.GameRoom('benchmark', '', 'benchmark', 'benchmark')
    for team in (0, 1):
        for role in ROLES:
            room.add_cpu_player(team, role)
    room.game_started = True
    room.game_logic = GameLogic(room.game_state, log_level=logging.CRITICAL)
    state = room.game_state

    counter = LogCounter(state)
    cp_logger = logging.getLogger('computer_player')
    cp_logger.handlers = [counter]
    cp_logger.propagate = False
    label_of_team = {a_team: 'A', 1 - a_team: 'B'}
    team_ids = {team: [pid for pid in room.cpu_player_ids if state.players[pid].team == team] for team in (0, 1)}
    controllers = {
        team: room.computer_player_class(room.game_logic, computer_player_log_level=logging.INFO, **configs[label_of_team[team]])
        for team in (0, 1)
    }

    dt = 1 / Config.FPS * Config.GAME_TIME_TO_REAL_TIME_RATIO
    result = {label: Counter() for label in ('A', 'B')}
    times = {label: [] for label in ('A', 'B')}
    knocked = {pid: False for pid in state.players}
    previous_possession = None
    for tick in range(ticks):
        room.game_logic.update(dt)
        for announcement in room.game_logic.penalty_logic.pop_announcements():
            if announcement.get('type') != 'penalty_turnover':
                continue
            volleyball = state.volleyball
            if 'volleyball' in announcement['balls'] or announcement['rule'] in ('stalled_volleyball', 'delay_of_game'):
                # the receiver may have picked the volleyball up within the same update already
                receiver_id = volleyball.turnover_to_player
                receiving_team = state.players[receiver_id].team if receiver_id is not None else volleyball.possession_team
                result[label_of_team[1 - receiving_team]][f'turnover {announcement["rule"]}'] += 1
            else:
                result['A'][f'other penalty {announcement["rule"]} (both)'] += 1
        for pid, player in state.players.items():
            if player.is_knocked_out and not knocked[pid]:
                result[label_of_team[player.team]][f'knocked out {player.role.value}'] += 1
            knocked[pid] = player.is_knocked_out
        possession = state.volleyball.possession_team
        if possession is not None and possession != previous_possession:
            result[label_of_team[possession]]['possessions'] += 1
            previous_possession = possession
        if tick % Config.COMPUTER_PLAYER_TICK_RATE == 0:
            # the defending team first, like defence before attack within one orchestrator
            first = 1 - possession if possession is not None else 0
            for team in (first, 1 - first):
                start = time.perf_counter_ns()
                controllers[team].make_move(dt * Config.COMPUTER_PLAYER_TICK_RATE, team_ids[team])
                times[label_of_team[team]].append((time.perf_counter_ns() - start) / 1e6)
    for team in (0, 1):
        label = label_of_team[team]
        result[label]['goals for'] += state.score[team]
        result[label]['goals against'] += state.score[1 - team]
    for (team, key), count in counter.counts.items():
        if team in label_of_team:
            result[label_of_team[team]][key] += count
    return {'seed': seed, 'a_team': a_team, 'result': result, 'times': times}


def _play_job(job):
    return play(*job)


def parse_seeds(text: str):
    seeds = []
    for part in text.split(','):
        if '-' in part:
            low, high = part.split('-')
            seeds += range(int(low), int(high) + 1)
        else:
            seeds.append(int(part))
    return seeds


def percentile(values, q):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


def main_cli():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--a', default='{}', help='override of config A (JSON or file)')
    parser.add_argument('--b', default='{}', help='override of config B (JSON or file)')
    parser.add_argument('--seeds', default='1-3')
    parser.add_argument('--ticks', type=int, default=6000)
    parser.add_argument('--jobs', type=int, default=1, help='parallel processes (timings get noisier)')
    args = parser.parse_args()

    configs = {label: deep_merge(Config.COMPUTER_PLAYER_KWARGS, load_override(text)) for label, text in (('A', args.a), ('B', args.b))}
    jobs = [(seed, args.ticks, configs, a_team) for seed in parse_seeds(args.seeds) for a_team in (0, 1)]
    if args.jobs > 1:
        with Pool(args.jobs) as pool:
            games = pool.map(_play_job, jobs)
    else:
        games = [_play_job(job) for job in jobs]

    totals = {label: Counter() for label in ('A', 'B')}
    times = {label: [] for label in ('A', 'B')}
    diffs = []
    for game in games:
        a, b = game['result']['A'], game['result']['B']
        diffs.append(a['goals for'] - b['goals for'])
        print(f"seed {game['seed']} A=team{game['a_team']}: A {a['goals for']} - {b['goals for']} B")
        for label in ('A', 'B'):
            totals[label].update(game['result'][label])
            times[label] += game['times'][label]

    n = len(diffs)
    mean = sum(diffs) / n
    stderr = math.sqrt(sum((d - mean) ** 2 for d in diffs) / (n - 1) / n) if n > 1 else float('nan')
    wins, draws = sum(d > 0 for d in diffs), sum(d == 0 for d in diffs)
    print(f'\ngames {n}: goal difference A-B per game {mean:+.2f} +- {stderr:.2f} (stderr); A wins {wins}, draws {draws}, losses {n - wins - draws}')
    for label in ('A', 'B'):
        t = totals[label]
        per_possession = t['goals for'] / t['possessions'] if t['possessions'] else float('nan')
        conversion = t['goals for'] / t['shots'] if t['shots'] else float('nan')
        ms = times[label]
        print(f'\n[{label}] goals {t["goals for"]}, possessions {t["possessions"]}, goals/possession {per_possession:.3f}, '
              f'shots {t["shots"]}, goals/shot {conversion:.2f}, passes {t["passes"]}')
        print(f'    make_move: mean {sum(ms)/len(ms):.3f} ms  p95 {percentile(ms, .95):.3f}  p99 {percentile(ms, .99):.3f}  max {max(ms):.3f}')
        for key in sorted(t):
            if key.startswith(('knocked out', 'turnover', 'other penalty')):
                print(f'    {key}: {t[key]}')
        for key in sorted(t):
            if key.startswith('move '):
                print(f'    {key[5:]}: {t[key]}')


if __name__ == '__main__':
    main_cli()
