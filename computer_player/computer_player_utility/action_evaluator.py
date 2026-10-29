import logging
import math
import random
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from config import Config
from core.entities import Hoop, Player, Vector2, VolleyBall
from core.game_logic.game_logic import GameLogic
from core.game_logic.process_action_logic import ProcessActionLogic
from computer_player.base_strategy import TeamRoster
from computer_player.dodgeball_dodger import dodgeball_approach
from computer_player.computer_player_utility.computer_player_utility import PassEvaluator, PassOption, ScoreAttempter
from computer_player.computer_player_utility.interception_calculator import InterceptionCalculator
from computer_player.computer_player_utility.kinematics import TICK_DT, decay_table, player_position_at, terminal_speed


def logistic_risk(margin: float, time_scale: float) -> float:
    """Interception risk of a time margin (game seconds): 0.5 at 0, towards 0 for large and 1 for negative margins."""
    exponent = margin / time_scale
    if exponent > 50:
        return 0.0
    if exponent < -50:
        return 1.0
    return 1 / (1 + math.exp(exponent))


@dataclass
class CarrierOption:
    """One option of the volleyball carrier with its value (estimated probability that it leads to a goal)."""
    kind: str # 'shoot', 'pass' or 'hold'
    value: float
    hoop: Optional[Hoop] = None
    score: Optional[float] = None # shot time margin / interception score, for the log
    pass_option: Optional[PassOption] = None
    details: Dict[str, float] = field(default_factory=dict)


class ActionEvaluator:
    """
    Rate the carrier's options shoot, pass and hold on one scale and act on the best one.

    All values estimate the probability that the option leads to a goal soon.

    Shot at hoop h:  S = (1 - risk(shot time margin, tau_shot)) * sin(angle to the hoop line)
        (`min_shot_angle` and the shooting range of the ScoreAttempter apply).

    Value of having the volleyball at a position, V, in two tiers by the distance to the closest
    opponent hoop:
        near (<= `near_hoop_distance`): max over hoops of
            P_reach * (1 - risk(shot time margin from the shooting spot)) * sin(angle) * travel * pressure * (1 - B)
        far: max over hoops of `far_shot_success` * sin(angle) * travel * pressure * (1 - B), no interception
            solves and no race to the spot (the defence is set long before a far player gets there).
      The shooting spot is the position itself within shooting range, otherwise the closest point at
      shooting range towards the hoop. P_reach = 1 - risk(fastest defender's time to the spot - own run
      time, tau_reach), 1 within range. travel = exp(-distance to the spot / `approach_decay`).
      pressure = min(1, closest opponent chaser/keeper distance / `pressure_distance`).

    Dodgeball risk B at a position and time: opponent dodgeballs held by on-stick opponent beaters
    (logistic in the distance, 0.5 at `held_risk_distance`) and opponent dodgeballs flying at it
    (`flying_risk_undodgeable` if the needed sidestep cannot be run in time, else `flying_risk_dodgeable`).
    Immune players (keeper in its zone) have B = 0.

    Keeping the volleyball is worth K(V) = `possession_value` + (1 - `possession_value`) * V: the baseline goal
    probability of a possession plus the position's upside. A missed shot or a lost pass ends the possession.

    Options:
        shoot:  S of the carrier's position
        pass:   (1 - risk(pass time margin, tau_pass)) * (1 - B(receiver at catch)) * K(V(receiver at its catch position and time))
        hold:   (1 - P_lose) * K(`hold_discount` * V(carrier one CPU step ahead)), with
                P_lose from the carrier's dodgeball risk, the stalled volleyball timer and the delay of game timer.
    A shot or pass is only taken if its value exceeds hold * (1 + `decision_margin_relative`) + `decision_margin`.
    """
    def __init__(self,
                 logic: GameLogic,
                 interception_calculator: InterceptionCalculator,
                 score_attempter: ScoreAttempter,
                 pass_evaluator: PassEvaluator,
                 decision_model: str = 'rules', # 'rules': the base attack's shoot-then-pass rules; 'value': this evaluator
                 near_hoop_distance: float = 12.0, # m, detailed modelling closer than this to an opponent hoop
                 pass_risk_time_scale: float = 0.25, # game seconds, logistic scale of the pass time margin
                 reach_risk_time_scale: float = 0.5, # game seconds, logistic scale of the race to the shooting spot
                 approach_decay: float = 8.0, # m, value decay with the distance to the shooting spot
                 far_shot_success: float = 0.7, # assumed shot success from the shooting spot for far positions
                 tier_blend_width: float = 2.0, # m, the near and far values are blended over this band around near_hoop_distance
                 pressure_distance: float = 4.0, # m, a closer opponent chaser/keeper lowers the value
                 held_risk_distance: float = 5.0, # m, distance of a loaded opponent beater with dodgeball risk 0.5
                 held_risk_width: float = 1.0, # m, logistic width of the held dodgeball risk
                 flying_risk_horizon: float = 2.0, # game seconds, flying dodgeballs arriving later are ignored
                 flying_risk_undodgeable: float = 1.0,
                 flying_risk_dodgeable: float = 0.3,
                 flying_hit_buffer: float = 0.3, # m added to the hit distance (player radius + ball radius)
                 hold_discount: float = 0.9,
                 possession_value: float = 0.45, # goal probability of a possession anywhere (about the measured goals per possession)
                 decision_margin: float = 0.005,
                 decision_margin_relative: float = 0.1,
                 decision_temperature: float = 0.0, # > 0: softmax among the options within decision_margin of the best
                 max_pass_candidates: int = 3, # receivers evaluated in detail, chosen by an optimistic cheap value
                 passing_squared_max_distance: float = 400,
                 passing_threshold: float = 0.95, # beam model only: pass completion is 1 above, 0 below this score
                 profile_call: Optional[Callable] = None,
                 logger: Optional[logging.Logger] = None):
        """Store the evaluation parameters and the shared interception, shot and pass models."""
        self.logic = logic
        self.interception_calculator = interception_calculator
        self.score_attempter = score_attempter
        self.pass_evaluator = pass_evaluator
        self.decision_model = decision_model
        self.near_hoop_distance = near_hoop_distance
        self.pass_risk_time_scale = pass_risk_time_scale
        self.reach_risk_time_scale = reach_risk_time_scale
        self.approach_decay = approach_decay
        self.far_shot_success = far_shot_success
        self.tier_blend_width = tier_blend_width
        self.pressure_distance = pressure_distance
        self.held_risk_distance = held_risk_distance
        self.held_risk_width = held_risk_width
        self.flying_risk_horizon = flying_risk_horizon
        self.flying_risk_undodgeable = flying_risk_undodgeable
        self.flying_risk_dodgeable = flying_risk_dodgeable
        self.flying_hit_buffer = flying_hit_buffer
        self.hold_discount = hold_discount
        self.possession_value = possession_value
        self.decision_margin = decision_margin
        self.decision_margin_relative = decision_margin_relative
        self.decision_temperature = decision_temperature
        self.max_pass_candidates = max_pass_candidates
        self.passing_squared_max_distance = passing_squared_max_distance
        self.passing_threshold = passing_threshold
        self.shooting_range = math.sqrt(score_attempter.score_squared_max_distance) - 0.05
        self.profile_call = profile_call or (lambda name, fn, *args: fn(*args))
        self.logger = logger or logging.getLogger("computer_player")

    @property
    def enabled(self) -> bool:
        """Whether the carrier decides with this evaluator."""
        return self.decision_model == 'value'

    # ---- decision ----

    def decide_and_act(self, volleyball: VolleyBall, carrier: Player, roster: TeamRoster) -> Optional[CarrierOption]:
        """Evaluate the carrier's options, shoot or pass if that beats holding, and return the chosen option."""
        options = self.profile_call('orchestrator.action_evaluator', self.evaluate_options, volleyball, carrier, roster)
        if not options:
            return None
        chosen = self._choose(options)
        self.logger.debug(
            "Carrier %s options: %s -> %s",
            carrier.id, ", ".join(f"{option.kind}{'@' + (option.hoop.id if option.hoop else option.pass_option.receiver_id[-4:]) if option.kind != 'hold' else ''}={option.value:.2f}" for option in options),
            chosen.kind,
        )
        if chosen.kind == 'shoot':
            self.score_attempter.shoot(volleyball, carrier, chosen.hoop, chosen.score)
        elif chosen.kind == 'pass':
            pass_option = chosen.pass_option
            if self.pass_evaluator.throw(self.logic.process_action_logic, carrier, pass_option):
                self.logger.info("Passing from player %s to player %s with position penalty %s and interception score %s",
                                 carrier.id, pass_option.receiver_id, round(chosen.value, 3), pass_option.interception_score)
        return chosen

    def _choose(self, options: List[CarrierOption]) -> CarrierOption:
        """Hold unless a shot or pass beats holding by the decision margin; optionally a softmax among the close ones."""
        hold = next(option for option in options if option.kind == 'hold')
        threshold = hold.value * (1 + self.decision_margin_relative) + self.decision_margin
        actions = [option for option in options if option.kind != 'hold' and option.value > threshold]
        if not actions:
            return hold
        best = max(actions, key=lambda option: option.value)
        if self.decision_temperature <= 0:
            return best
        close = [option for option in actions if option.value >= best.value - self.decision_margin]
        weights = [math.exp((option.value - best.value) / self.decision_temperature) for option in close]
        return random.choices(close, weights=weights)[0]

    def evaluate_options(self, volleyball: VolleyBall, carrier: Player, roster: TeamRoster) -> List[CarrierOption]:
        """Shoot options (one per hoop in range), the detailed pass candidates and hold, with their values."""
        state = self.logic.state
        defenders = [state.players[player_id] for player_id in roster.opponent_chaser_keeper_ids if not state.players[player_id].is_knocked_out]
        options = []

        # shoot
        for hoop, score, value in self._shot_values(volleyball, carrier, roster, volleyball.position):
            options.append(CarrierOption('shoot', value, hoop=hoop, score=score))

        # pass: cheap optimistic value for every receiver in range, details for the best few
        candidates = []
        ball_distances = state.squared_distances_ball_player_dicts[volleyball.id]
        for player_id in roster.chaser_keeper_ids:
            if player_id == carrier.id:
                continue
            receiver = state.players[player_id]
            if receiver.is_knocked_out or ball_distances.get(player_id, float('inf')) > self.passing_squared_max_distance:
                continue
            cheap = self.position_value(receiver, receiver.position, 0.0, roster, defenders, detailed=False)
            candidates.append((cheap, player_id))
        candidates.sort(reverse=True)
        for _, player_id in candidates[:self.max_pass_candidates]:
            receiver = state.players[player_id]
            pass_option = self.pass_evaluator.evaluate(volleyball, carrier, receiver, roster.own_hoops, roster.opponent_chaser_keeper_ids)
            if pass_option is None:
                continue
            completion = self._pass_completion(pass_option)
            if completion <= 0:
                continue
            catch_position = pass_option.predicted_receiver_position
            catch_time = pass_option.catch_time # charge + flight
            if catch_time is None: # legacy motion model
                catch_time = self.interception_calculator.arrival_time(
                    volleyball, ProcessActionLogic.effective_throw_velocity(carrier),
                    math.hypot(catch_position.x - volleyball.position.x, catch_position.y - volleyball.position.y))
            if catch_time == float('inf'):
                continue
            receiver_value = self.position_value(receiver, catch_position, catch_time, roster, defenders, detailed=True, ignore_dodgeballs=True)
            beat = self.dodgeball_risk(receiver, catch_position, Vector2(0, 0), catch_time, roster)
            value = completion * (1 - beat) * self._possession_value(receiver_value)
            options.append(CarrierOption('pass', value, pass_option=pass_option,
                                         details={'completion': completion, 'beat': beat, 'receiver_value': receiver_value}))

        # hold
        ticks_ahead = Config.COMPUTER_PLAYER_TICK_RATE
        ahead_x, ahead_y = player_position_at(carrier, ticks_ahead)
        carrier_value = self.position_value(carrier, Vector2(ahead_x, ahead_y), ticks_ahead * TICK_DT, roster, defenders, detailed=True,
                                            ignore_dodgeballs=True)
        lose = self._lose_probability(volleyball, carrier, roster)
        options.append(CarrierOption('hold', (1 - lose) * self._possession_value(self.hold_discount * carrier_value),
                                     details={'lose': lose, 'carrier_value': carrier_value}))
        return options

    def _possession_value(self, position_value: float) -> float:
        """Value of keeping the volleyball: the baseline goal probability of a possession plus the position's upside."""
        return self.possession_value + (1 - self.possession_value) * position_value

    def _pass_completion(self, pass_option: PassOption) -> float:
        """Probability that the pass reaches the receiver."""
        if pass_option.time_margin is not None:
            return 1 - logistic_risk(pass_option.time_margin, self.pass_risk_time_scale)
        return 1.0 if pass_option.interception_score > self.passing_threshold else 0.0

    def _lose_probability(self, volleyball: VolleyBall, carrier: Player, roster: TeamRoster) -> float:
        """Probability of losing the volleyball while holding it: dodgeballs, stalled volleyball and delay of game."""
        state = self.logic.state
        beat = self.dodgeball_risk(carrier, carrier.position, carrier.velocity, 0.0, roster)
        stall = 0.0
        if volleyball.time_since_carrier_tackled <= state.stalled_volleyball_tackle_grace and state.stalled_volleyball_time_limit > 0:
            stall = min(1.0, volleyball.stalled_timer / state.stalled_volleyball_time_limit)
        delay = 0.0
        if state.delay_of_game_time_limit > 0:
            delay = min(1.0, volleyball.delay_of_game_timer / state.delay_of_game_time_limit)
        return 1 - (1 - beat) * (1 - stall) * (1 - delay)

    # ---- shots and position values ----

    def _shot_values(self, volleyball: VolleyBall, shooter: Player, roster: TeamRoster, position: Vector2,
                     hoops: Optional[List[Hoop]] = None) -> List[Tuple[Hoop, float, float]]:
        """(hoop, shot score, shot value S) for each of `hoops` (default all opponent hoops) the shooter could shoot at from `position`."""
        hoops = roster.opponent_hoops if hoops is None else hoops
        shot_ball = volleyball
        if position is not volleyball.position:
            shot_ball = volleyball.copy()
            shot_ball.position = Vector2(position.x, position.y)
        attempter = self.score_attempter
        if attempter.use_time_margin:
            scores = attempter.get_time_margins_for_hoops(shot_ball, shooter, hoops, roster.opponent_chaser_keeper_ids)
        else:
            scores = attempter.get_intercepting_scores_for_hoops(shot_ball, shooter, hoops, roster.opponent_chaser_keeper_ids)
        values = []
        for hoop in hoops:
            if hoop.id not in scores:
                continue
            score = scores[hoop.id]
            dx, dy = hoop.position.x - position.x, hoop.position.y - position.y
            sin_angle = abs(dx) / math.hypot(dx, dy)
            if attempter.use_time_margin:
                success = 1 - logistic_risk(score, attempter.shot_risk_time_scale)
            else:
                success = min(1.0, max(0.0, score))
            values.append((hoop, score, success * sin_angle))
        return values

    def position_value(self,
                       player: Player,
                       position: Vector2,
                       time: float,
                       roster: TeamRoster,
                       defenders: List[Player],
                       detailed: bool,
                       ignore_dodgeballs: bool = False) -> float:
        """
        Value of `player` having the volleyball at `position` at `time` game seconds from now.

        Far from the opponent hoops (and without `detailed`) the cheap estimate; with `detailed` and within
        `near_hoop_distance` the detailed one, which rates the shot from the shooting spot with its time margin.
        Within `tier_blend_width` around `near_hoop_distance` both are blended linearly, so the value is continuous.
        """
        hoop_distance = min(math.hypot(position.x - hoop.position.x, position.y - hoop.position.y) for hoop in roster.opponent_hoops)
        half_band = self.tier_blend_width / 2
        far_weight = 1.0
        if detailed:
            far_weight = min(1.0, max(0.0, (hoop_distance - (self.near_hoop_distance - half_band)) / self.tier_blend_width)) if self.tier_blend_width > 0                 else (0.0 if hoop_distance <= self.near_hoop_distance else 1.0)
        run_speed = terminal_speed(player)
        closest_defender = min((math.hypot(defender.position.x - position.x, defender.position.y - position.y) for defender in defenders), default=float('inf'))
        pressure = min(1.0, closest_defender / self.pressure_distance) if self.pressure_distance > 0 else 1.0
        best_far = 0.0
        best_near = 0.0
        for hoop in roster.opponent_hoops:
            dx, dy = hoop.position.x - position.x, hoop.position.y - position.y
            distance = math.hypot(dx, dy)
            if distance == 0:
                continue
            if distance <= self.shooting_range:
                spot, run = position, 0.0
            else:
                run = distance - self.shooting_range
                spot = Vector2(position.x + dx * run / distance, position.y + dy * run / distance)
            sx, sy = hoop.position.x - spot.x, hoop.position.y - spot.y
            if self.score_attempter.is_too_far_to_the_side(sx, sy):
                continue
            sin_angle = abs(sx) / math.hypot(sx, sy)
            travel = math.exp(-run / self.approach_decay) * pressure
            best_far = max(best_far, self.far_shot_success * sin_angle * travel)
            if far_weight >= 1.0:
                continue
            reach = 1.0
            if run > 0:
                run_time = run / run_speed if run_speed > 0 else float('inf')
                defender_time = min((math.hypot(d.position.x - spot.x, d.position.y - spot.y) / terminal_speed(d) for d in defenders), default=float('inf'))
                reach = 1 - logistic_risk(defender_time - (time + run_time), self.reach_risk_time_scale)
            if reach * sin_angle * travel <= best_near:
                continue # cannot beat the best hoop even with a sure shot
            shot = self._shot_values(self.logic.state.volleyball, player, roster, spot, hoops=[hoop])
            best_near = max(best_near, reach * (shot[0][2] if shot else 0.0) * travel)
        best = far_weight * best_far + (1 - far_weight) * best_near
        if not ignore_dodgeballs and best > 0:
            best *= 1 - self.dodgeball_risk(player, position, Vector2(0, 0), time, roster)
        return best

    def dodgeball_risk(self, player: Player, position: Vector2, velocity: Vector2, time: float, roster: TeamRoster) -> float:
        """
        Probability that `player` at `position` around `time` game seconds from now is beaten: opponent dodgeballs
        held by on-stick opponent beaters (by distance) and flying at the position.
        """
        if player.dodgeball_immunity:
            return 0.0
        state = self.logic.state
        safe = 1.0
        for beater_id in roster.opponent_beater_ids:
            beater = state.players[beater_id]
            if beater.is_knocked_out or not beater.has_ball:
                continue
            distance = math.hypot(beater.position.x - position.x, beater.position.y - position.y)
            safe *= 1 - logistic_risk(distance - self.held_risk_distance, self.held_risk_width) # 0.5 at held_risk_distance, -> 1 when close
        opponent_team = 1 - roster.team
        hit_distance = player.radius + self.flying_hit_buffer
        for dodgeball in state.dodgeballs:
            if dodgeball.holder_id is not None or dodgeball.possession_team != opponent_team:
                continue
            approach = dodgeball_approach(position, velocity, player.deacceleration_rate, dodgeball)
            if approach is None:
                continue
            arrival_time, lateral, _, _ = approach
            # the player is at the position from `time` on; a ball passing it long before does not matter
            if arrival_time < time - 0.5 * self.flying_risk_horizon or arrival_time > time + self.flying_risk_horizon:
                continue
            if abs(lateral) > hit_distance + dodgeball.radius:
                continue
            dodge_time = max(0.0, arrival_time - time)
            sidestep = terminal_speed(player) * (dodge_time - decay_table(player.deacceleration_rate).tau_at(dodge_time / TICK_DT))
            needed = hit_distance + dodgeball.radius - abs(lateral)
            safe *= 1 - (self.flying_risk_undodgeable if sidestep < needed else self.flying_risk_dodgeable)
        return 1 - safe
