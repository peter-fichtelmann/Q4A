"""
Collect features and outcomes of every CPU pass and shot in headless games, for fitting the ActionEvaluator's
shot success and pass completion models (tools/fit_cpu_throw_models.py).

usage: python tools/collect_cpu_throws.py <out.csv> <first seed> <number of seeds> <jobs>
Each seed is played with three configs: the rules, exploratory rules (low pass/shot thresholds, so risky
actions are observed too) and the value model. A pass succeeds if the own team gets the volleyball next,
a shot if the team scores.
"""
import os, sys, itertools, uuid, random, logging, copy, csv, math
from multiprocessing import Pool

ROOT = os.environ.get('Q4A_ROOT', os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
os.chdir(ROOT) # main.py mounts client/ relative to the working directory
_counter = itertools.count()
uuid.uuid4 = lambda: uuid.UUID(int=next(_counter))
logging.disable(logging.CRITICAL)
import main
from config import Config
from core.game_logic.game_logic import GameLogic
from computer_player.computer_player_utility import computer_player_utility as cpu

TICKS = 6000
FIELDS = ['config', 'seed', 'kind', 'team', 'time_margin', 'distance', 'sin_angle', 'catch_time', 'strength_ratio', 'tackled', 'success']


def configs():
    base = copy.deepcopy(Config.COMPUTER_PLAYER_KWARGS)
    explore = copy.deepcopy(base)
    explore['passing_kwargs']['pass_time_margin'] = -1.5
    explore['scoring_kwargs']['shot_time_margin'] = -1.0
    value = copy.deepcopy(base)
    value['action_evaluator_kwargs']['decision_model'] = 'value'
    return {'rules': base, 'explore': explore, 'value': value}


def play(job):
    name, kwargs, seed = job
    global _counter
    _counter = itertools.count()
    random.seed(seed)
    room = main.GameRoom('r', 'p', 'c', 'n')
    for team in (0, 1):
        for role in ['keeper', 'chaser', 'chaser', 'chaser', 'beater', 'beater']:
            room.add_cpu_player(team, role)
    room.game_started = True
    room.game_logic = GameLogic(room.game_state, log_level=logging.CRITICAL)
    state = room.game_state
    pending = {} # team -> row dict while the outcome is open
    rows = []

    original_shoot = cpu.ScoreAttempter.shoot
    original_throw = cpu.PassEvaluator.throw

    def shoot(self, volleyball, holder, hoop, score):
        ok = original_shoot(self, volleyball, holder, hoop, score)
        if ok:
            dx, dy = hoop.position.x - volleyball.position.x, hoop.position.y - volleyball.position.y
            distance = math.hypot(dx, dy)
            pending[holder.team] = dict(config=name, seed=seed, kind='shot', team=holder.team, time_margin=score, distance=distance,
                                        sin_angle=abs(dx) / distance if distance else 0.0, catch_time='', strength_ratio=1.0,
                                        tackled=int(bool(holder.tackling_player_ids)), _score=list(state.score), _carrier=holder.id, _start=state.game_time)
        return ok

    def throw(process_action_logic, holder, pass_option):
        ok = original_throw(process_action_logic, holder, pass_option)
        if ok:
            vb = state.volleyball
            target = pass_option.predicted_receiver_position
            pending[holder.team] = dict(config=name, seed=seed, kind='pass', team=holder.team, time_margin=pass_option.time_margin,
                                        distance=math.hypot(target.x - vb.position.x, target.y - vb.position.y), sin_angle='',
                                        catch_time=pass_option.catch_time, strength_ratio=pass_option.strength_ratio,
                                        tackled=int(bool(holder.tackling_player_ids)), _score=list(state.score), _carrier=holder.id, _start=state.game_time)
        return ok

    cpu.ScoreAttempter.shoot = shoot
    cpu.PassEvaluator.throw = staticmethod(throw)
    try:
        cp = room.computer_player_class(room.game_logic, computer_player_log_level=logging.CRITICAL, **copy.deepcopy(kwargs))
        dt = 1 / Config.FPS * Config.GAME_TIME_TO_REAL_TIME_RATIO
        for tick in range(TICKS):
            room.game_logic.update(dt)
            vb = state.volleyball
            for team, row in list(pending.items()):
                success = None
                if state.score[team] > row['_score'][team]:
                    success = 1
                elif vb.holder_id is not None and vb.holder_id != row['_carrier']:
                    success = int(row['kind'] == 'pass' and state.players[vb.holder_id].team == team)
                elif vb.holder_id is None and (vb.is_dead or vb.turnover_to_player is not None or vb.inbounder is not None):
                    success = 0
                elif state.game_time - row['_start'] > 30:
                    del pending[team] # unresolved
                    continue
                if success is not None:
                    row['success'] = success
                    rows.append({key: row[key] for key in FIELDS})
                    del pending[team]
            if tick % Config.COMPUTER_PLAYER_TICK_RATE == 0:
                cp.make_move(dt * Config.COMPUTER_PLAYER_TICK_RATE, room.get_cpu_controlled_player_ids())
    finally:
        cpu.ScoreAttempter.shoot = original_shoot
        cpu.PassEvaluator.throw = original_throw
    return rows


if __name__ == '__main__':
    out, first, n, jobs = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4])
    job_list = [(name, kwargs, seed) for seed in range(first, first + n) for name, kwargs in configs().items()]
    with Pool(jobs) as pool:
        results = pool.map(play, job_list)
    with open(out, 'w', newline='', encoding='utf-8') as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS)
        writer.writeheader()
        for rows in results:
            writer.writerows(rows)
    print('rows', sum(len(rows) for rows in results))
