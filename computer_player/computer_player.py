from abc import ABC, abstractmethod
from dataclasses import dataclass
import logging
from time import perf_counter_ns
from typing import Dict, List, Tuple
from core.game_logic.game_logic import GameLogic
from core.entities import Player, Ball, VolleyBall, DodgeBall, Vector2, PlayerRole, BallType
from computer_player.hoop_defence import HoopDefence
from computer_player.diamond_attack import DiamondAttack
from computer_player.computer_player_utility import InterceptionRatioCalculator, MoveAroundHoopBlockage, BeaterThrowDecider, ThrowDirector
import random

from core.game_logic.utility_logic import UtilityLogic


@dataclass
class _StepProfileStats:
    calls: int = 0
    total_ns: int = 0
    max_ns: int = 0

    def add(self, elapsed_ns: int) -> None:
        self.calls += 1
        self.total_ns += elapsed_ns
        if elapsed_ns > self.max_ns:
            self.max_ns = elapsed_ns


class _ComputerPlayerStepProfiler:
    """Low-overhead optional profiler for computer-player steps."""

    def __init__(self):
        self.enabled: bool = False
        self.stats: dict[str, _StepProfileStats] = {}

    def reset(self) -> None:
        self.stats.clear()

    def time_call(self, step_name: str, fn, *args, **kwargs):
        if not self.enabled:
            return fn(*args, **kwargs)

        stats = self.stats.setdefault(step_name, _StepProfileStats())
        start_ns = perf_counter_ns()
        try:
            return fn(*args, **kwargs)
        finally:
            stats.add(perf_counter_ns() - start_ns)

    def report(self) -> list[dict[str, float | int | str]]:
        rows = []
        for step_name, stats in self.stats.items():
            avg_ms = (stats.total_ns / stats.calls / 1e6) if stats.calls else 0.0
            rows.append({
                'step': step_name,
                'calls': stats.calls,
                'avg_ms': avg_ms,
                'max_ms': stats.max_ns / 1e6,
                'total_ms': stats.total_ns / 1e6,
            })
        rows.sort(key=lambda item: float(item['total_ms']), reverse=True)
        return rows

class ComputerPlayer(ABC):
    """
    Abstract base class for a computer player in a game. 
    It defines the interface for changing the direction and actions of the computer-controlled players.
    """
    def __init__(self, game_logic: GameLogic, cpu_player_ids: List[str], computer_player_log_level: int = logging.INFO):
        self.logic = game_logic
        self.cpu_player_ids = cpu_player_ids
        self.cpu_players = [self.logic.state.players[player_id] for player_id in cpu_player_ids]
        self.logger = logging.getLogger("computer_player")
        self.logger.setLevel(computer_player_log_level)
        self._step_profiler = _ComputerPlayerStepProfiler()

    def enable_step_profiling(self, reset_stats: bool = True) -> None:
        if reset_stats:
            self._step_profiler.reset()
        self._step_profiler.enabled = True

    def disable_step_profiling(self) -> None:
        self._step_profiler.enabled = False

    def get_step_profile_report(self) -> list[dict[str, float | int | str]]:
        return self._step_profiler.report()

    def reset_step_profile(self) -> None:
        self._step_profiler.reset()

    def _profile_call(self, step_name: str, fn, *args, **kwargs):
        return self._step_profiler.time_call(step_name, fn, *args, **kwargs)

    @abstractmethod
    def make_move(self, dt: float):
        pass


class RandomComputerPlayer(ComputerPlayer):
    def __init__(self,
                 game_logic: GameLogic,
                 cpu_player_ids: List[str],
                 throwing_probability: float = 0.1,
                 computer_player_log_level: int = logging.INFO):
        super().__init__(game_logic, cpu_player_ids, computer_player_log_level=computer_player_log_level)
        self.throwing_probability = throwing_probability

    def make_move(self, dt: float):
        # add random number between -1 and 1 to the x and y direction of each CPU player
        # print(f'[CPU Player] Making move for {len(self.cpu_players)} CPU players')
        for player in self.cpu_players:
            player.direction.x += random.uniform(-1, 1)
            player.direction.y += random.uniform(-1, 1)
            throwing_decision = random.random() < self.throwing_probability
            if throwing_decision:
                self._profile_call('random.process_throw_action', self.logic.process_action_logic.process_throw_action, player.id)
            # always try to tackle if not throwing
            self.logic.process_action_logic.process_tackle_action(player.id)

            
class RuleBasedComputerPlayer(ComputerPlayer):
    def __init__(self,
                 game_logic: GameLogic,
                 cpu_player_ids: List[str],
                 move_buffer_factor: float = 1.2,
                 determine_attacking_team_max_dt_steps: int = 10,
                 determine_attacking_team_max_distance_per_step: float = None,
                 determine_attacking_team_max_dt_per_step: int = None,
                 hoop_defence_kwargs: Dict = None,
                 diamond_attack_kwargs: Dict = None,
                 beater_throw_threshold_volleyball_holder: float = 5,
                 simulation_game_logic_log_level: int = None,
                 computer_player_log_level: int = logging.INFO
                 ):
        super().__init__(game_logic, cpu_player_ids, computer_player_log_level=computer_player_log_level)
        self.move_buffer_factor = move_buffer_factor
        self.determine_attacking_team_max_dt_steps = determine_attacking_team_max_dt_steps
        self.determine_attacking_team_max_distance_per_step = determine_attacking_team_max_distance_per_step
        self.determine_attacking_team_max_dt_per_step = determine_attacking_team_max_dt_per_step
        self.hoop_defence_kwargs = hoop_defence_kwargs

        self.diamond_attack_kwargs = diamond_attack_kwargs

        self.beater_throw_threshold_volleyball_holder = beater_throw_threshold_volleyball_holder

        self.beaters = [player for player in self.logic.state.players.values() if player.role == PlayerRole.BEATER]

        self.defence_hoops_0 = []
        self.defence_hoops_1 = []
        for hoop in self.logic.state.hoops.values():
            if hoop.team == 0:
                self.defence_hoops_0.append(hoop)
            else:
                self.defence_hoops_1.append(hoop)
        volleyball_radius = self.logic.state.volleyball.radius if self.logic.state.volleyball is not None else 0
        self.move_around_hoop_blockage_team_0 = MoveAroundHoopBlockage(
            defence_hoops=self.defence_hoops_0,
            move_buffer_factor=self.move_buffer_factor,
            volleyball_radius=volleyball_radius,
            logger=self.logger
            )
        self.move_around_hoop_blockage_team_1 = MoveAroundHoopBlockage(
            defence_hoops=self.defence_hoops_1,
            move_buffer_factor=self.move_buffer_factor,
            volleyball_radius=volleyball_radius,
            logger=self.logger
            )
        self.interception_ratio_calculator_team_0 = InterceptionRatioCalculator(
            logic=self.logic,
            move_around_hoop_blockage=self.move_around_hoop_blockage_team_0,
            log_level=simulation_game_logic_log_level,
            logger=self.logger
            )
        self.interception_ratio_calculator_team_1 = InterceptionRatioCalculator(
            logic=self.logic,
            move_around_hoop_blockage=self.move_around_hoop_blockage_team_1,
            log_level=simulation_game_logic_log_level,
            logger=self.logger
            )
        self.beater_throw_decider = BeaterThrowDecider(
            throw_threshold_volleyball_holder=beater_throw_threshold_volleyball_holder
        )

    def make_move(self, dt: float):
        # self._hoop_defence([cpu_player.id for cpu_player in self.cpu_players if cpu_player.team == self.logic.state.team_0], self.logic.state.team_0)
        attacking_team, next_volleyball_holder_id, intercepting_position = self._profile_call(
            'rule_based._determine_attacking_team',
            self._determine_attacking_team,
            dt,
        )
        assigned_beater_ids = self._profile_call(
            'rule_based._determine_beater_ball_getting',
            self._determine_beater_ball_getting,
            dt,
            attacking_team,
        )
        if attacking_team is None:
            # both teams in attacking mode
            # TODO implement
            pass
        hoop_defence = self._profile_call(
            'rule_based.HoopDefence.init',
            HoopDefence,
            logic = self.logic,
            defence_cpu_player_ids=[cpu_player.id for cpu_player in self.cpu_players if cpu_player.team != attacking_team],
            defence_team=self.logic.state.team_0 if attacking_team != 0 else self.logic.state.team_1,
            move_around_hoop_blockage=self.move_around_hoop_blockage_team_0 if attacking_team != 0 else self.move_around_hoop_blockage_team_1,
            beater_throw_decider=self.beater_throw_decider,
            **self.hoop_defence_kwargs,
        )
        self._profile_call('rule_based.HoopDefence.__call__', hoop_defence, dt, assigned_beater_ids)

        diamond_attack = self._profile_call(
            'rule_based.DiamondAttack.init',
            DiamondAttack,
            logic=self.logic,
            move_around_hoop_blockage=self.move_around_hoop_blockage_team_0 if attacking_team == 0 else self.move_around_hoop_blockage_team_1,
            interception_ratio_calculator_opponent=self.interception_ratio_calculator_team_1 if attacking_team == 0 else self.interception_ratio_calculator_team_0, # inverse because we need hoop blockage of opponent team
            attack_cpu_player_ids=[cpu_player.id for cpu_player in self.cpu_players if cpu_player.team == attacking_team],
            attack_team=attacking_team,
            **self.diamond_attack_kwargs,
            logger=self.logger
        )
        self._profile_call(
            'rule_based.DiamondAttack.__call__',
            diamond_attack,
            dt=dt,
            next_volleyball_holder_id=next_volleyball_holder_id,
            intercepting_position=intercepting_position,
        )
        # self._hoop_defence([cpu_player.id for cpu_player in self.cpu_players if cpu_player.team == self.logic.state.team_1], self.logic.state.team_1)

    def _determine_beater_ball_getting(self, dt: float, attacking_team: int) -> List[str]:
        """
        Determine if any beater should attempt to get a dodgeball. Return list of beater ids assigned to get a dodgeball, and set their direction towards the assigned dodgeball.
        
        We deal with different scenarios in the following order:
        1. If there is a third dodgeball team, assign beater players to get the dodgeball for that team. The other team is very likely in possesion of two dodgeballs.
        2. If there is no third dodgeball team, assign beater players to get any dead dodgeballs:
            a. Assignment based on interception:
               First perform an interception ratio calculation for close plays where the dodgeball velocity could have an impact on whether the beater can get the dodgeball before the opponent.
               Only assign one beater per dodgeball in this step to avoid issues with one beater being assigned to multiple dodgeballs due to the same interception ratio.
               If the same player would be assigned to multiple dodgeballs due to the same interception ratio, the player is only assigned to the closest dodgeball (least steps) and we perform another interception ratio calculation for the remaining unassigned dodgeballs without the already assigned beater until all dodgeballs are processed or all beaters are assigned.
            b. Assignbement based on proximity:
                For any remaining unassigned dodgeballs (e.g. larger distance than previous interception ratio calculation simulation permits), assign the closest beater to get the dodgeball based on proximity.
        """
        assigned_beater_ids = []
        third_dodgeball_team = self.logic.state.third_dodgeball_team
        if third_dodgeball_team is not None:
            # TODO implement the rare case when control beater missed throw and wants to run to get thrown dodgeball back/oppenent tries to get this one
            # If there is a third dodgeball team, assign beater players to get the dodgeball
            self.logger.debug(
                "Third dodgeball on team %s, determining beater assignment to get the dodgeball",
                third_dodgeball_team,
            )
            third_dodgeball = self.logic.state.balls[self.logic.state.third_dodgeball]
            squared_distance_and_direction_to_dodgeball_dict = {}
            for beater in self.beaters:
                if beater.team == third_dodgeball_team and not beater.is_knocked_out:
                    direction_to_dodgeball = Vector2(
                            third_dodgeball.position.x - beater.position.x,
                            third_dodgeball.position.y - beater.position.y
                        )
                    squared_distance_to_dodgeball = UtilityLogic._squared_sum(direction_to_dodgeball.x, direction_to_dodgeball.y)
                    squared_distance_and_direction_to_dodgeball_dict[beater.id] = (squared_distance_to_dodgeball, direction_to_dodgeball)
            if len(squared_distance_and_direction_to_dodgeball_dict) > 0:
                # assign beater with lowest squared distance to dodgeball to get the dodgeball
                beater_id = min(squared_distance_and_direction_to_dodgeball_dict.keys(), key=lambda k: squared_distance_and_direction_to_dodgeball_dict[k][0])
                beater = self.logic.state.players[beater_id]
                self.logger.debug("Beater %s assigned to get third dodgeball for team %s", beater.id, third_dodgeball_team)
                assigned_beater_ids.append(beater_id)
                    # move towards the dodgeball
                if beater.id in self.cpu_player_ids:
                    beater.direction = squared_distance_and_direction_to_dodgeball_dict[beater.id][1]
        else: # no third dodgeball, so no team already has two dodgeballs in possesion
            # step_ratio_dicts = {}
            sorted_interception_per_dodgeball_dict = {}
            min_interception_time_dodgeball_dict = {}
            for dodgeball in self.logic.state.balls.values():
                if dodgeball.ball_type == BallType.DODGEBALL:
                    if dodgeball.possession_team is None:
                        # If there is a dead dodgeball which is not the third dodgeball, assign beater players to get the dodgeball
                        # does not matter which interception ratio calculator as beaters are not blocked by hoops
                        min_interception_time, _, interception_info_dict = self.interception_ratio_calculator_team_0.line_interception(
                            moving_entity=dodgeball,
                            intercepting_player_ids=[beater.id for beater in self.beaters],
                        )
                        sorted_info_dict = sorted(interception_info_dict.items(), key=lambda item: item[1]) # sort by interception time
                        print('sorted_info_dict for dodgeball id ', dodgeball.id, ': ', sorted_info_dict)
                        sorted_interception_per_dodgeball_dict[dodgeball.id] = sorted_info_dict
                        min_interception_time_dodgeball_dict[dodgeball.id] = min_interception_time


                        # _, step_ratio_dict = self.interception_ratio_calculator_team_0(
                        #     dt=dt,
                        #     moving_entity=dodgeball,
                        #     intercepting_player_ids=[beater.id for beater in self.beaters if not beater.is_knocked_out],
                        #     target_position=None,
                        #     only_first_intercepting=True, # in rare cases if one beater would get two dodgeball, this could cause issues so only assign one beater per dodgeball
                        #     max_dt_steps=self.determine_attacking_team_max_dt_steps,
                        #     max_distance_per_step=self.determine_attacking_team_max_distance_per_step,
                        #     max_dt_per_step=self.determine_attacking_team_max_dt_per_step
                        # )
                        # step_ratio_dicts[dodgeball.id] = step_ratio_dict
            # sort step_ratio_dicts by lowest step in step_ratio_dicts[dodgeball_id][beater_id] = (step, step_ratio, intercepting_position)
            # each step_ratio_dict has only one beater_id entry due to only_first_intercepting=True, so we can sort by step directly
            unassigned_dodgeball_ids = []
            sorted_dodgeball_ids = sorted(min_interception_time_dodgeball_dict.keys(), key=lambda dodgeball_id: min_interception_time_dodgeball_dict[dodgeball_id]) 
            # print('sorted dodgeball ids by interception time: ', sorted_dodgeball_ids)
            # print('sorted interception info dicts: ', sorted_interception_per_dodgeball_dict)
            for dodgeball_id in sorted_dodgeball_ids:
                if len(sorted_interception_per_dodgeball_dict[dodgeball_id]) > 0:
                    for beater_id, interception_time in sorted_interception_per_dodgeball_dict[dodgeball_id]:
                        if beater_id not in assigned_beater_ids:
                            beater = self.logic.state.players[beater_id]
                            dodgeball = self.logic.state.balls[dodgeball_id]
                            assigned_beater_ids.append(beater_id)
                            # move towards the dodgeball
                            if beater.id in self.cpu_player_ids:
                                interception_position = Vector2(
                                    dodgeball.position.x + dodgeball.velocity.x * interception_time,
                                    dodgeball.position.y + dodgeball.velocity.y * interception_time
                                )
                                beater.direction = Vector2(
                                        interception_position.x - beater.position.x,
                                        interception_position.y - beater.position.y
                                    )
                                self.logger.debug(f"CPU Beater {beater.id} positioned at {beater.position} assigned to get dodgeball {dodgeball.id} with interception time {interception_time}")

                            break
            # while len(step_ratio_dicts) > 0:
            #     # assign beaters to dodgeballs based on interception ratio calculation, if beater already assigned, perform another interception ratio calculation without the assigned beater until all step_ratio_dicts are processed or all beaters are assigned, then assign remaining dodgeballs based on proximity
            #     step_ratio_dicts, assigned_beater_ids, unassigned_dodgeball_ids = self._interception_based_beater_assignment(dt, step_ratio_dicts, assigned_beater_ids, unassigned_dodgeball_ids)
            #     # self.logger.debug(f"Assigned beater ids after interception based assignment: {assigned_beater_ids}, unassigned dodgeball ids: {unassigned_dodgeball_ids}, remaining step ratio dicts: {len(step_ratio_dicts.keys())}")
            if len(unassigned_dodgeball_ids) > 0:
                assigned_beater_ids = self._distance_based_beater_assignment(unassigned_dodgeball_ids, assigned_beater_ids)

            # check if assigned beater has ball to throw to teammate or back to hoops
            for beater_id in assigned_beater_ids:
                beater = self.logic.state.players[beater_id]
                if beater.has_ball and beater.id in self.cpu_player_ids:
                    # check if in defence and volleyball holding chaser close, if so throw at volleyball holder and get the assigned ball
                    if beater.team != attacking_team:
                        volleyball = self.logic.state.volleyball
                        if volleyball.holder_id is not None:
                            volleyball_holder = self.logic.state.players[volleyball.holder_id]
                            if self.beater_throw_decider.should_throw_at_volleyball_holder(beater, volleyball_holder):
                                throw_direction = ThrowDirector.get_throw_direction_moving_receiver(beater, volleyball_holder)
                                self.logic.process_action_logic.process_throw_action(beater.id, throw_direction)
                                continue
                    # check for pass to beater buddy, else pass back to hoops   
                    beater_buddy = [player for player in self.beaters if player.id != beater_id and player.team == beater.team][0]
                    if not (beater_buddy.is_knocked_out) and not (beater_buddy.id in assigned_beater_ids) and not (beater_buddy.has_ball):
                        # pass to teammate if they not knocked out, not assigned a dodgeball or already having a dodgeball
                        # self.logger.debug("Beater %s has ball and is passing to teammate %s", beater.id, beater_buddy.id)
                        throw_direction = ThrowDirector.get_throw_direction_moving_receiver(beater, beater_buddy)
                        self.logic.process_action_logic.process_throw_action(beater.id, throw_direction)
                        # move beater buddy to throwing player (at the moment only for one dt step)
                        beater_buddy.direction = Vector2(
                            - throw_direction.x,
                            - throw_direction.y
                        )
                        assigned_beater_ids.append(beater_buddy.id)
                    else:
                        # pass back to central hoop
                        # self.logger.debug(
                        #     "Beater %s has ball but teammate %s is not available, passing back to hoops",
                        #     beater.id,
                        #     beater_buddy.id,
                        # )
                        if beater.team == 0:
                            central_hoop = self.defence_hoops_0[1]
                        else:
                            central_hoop = self.defence_hoops_1[1]
                        throw_direction = Vector2(
                            central_hoop.position.x - beater.position.x,
                            central_hoop.position.y - beater.position.y
                        )
                        self.logic.process_action_logic.process_throw_action(beater.id, throw_direction)
        return assigned_beater_ids

    def _interception_based_beater_assignment(self, dt, step_ratio_dicts: dict, assigned_beater_ids: List[str], unassigned_dodgeball_ids: List[str]):
        sorted_dodgeball_ids = sorted(step_ratio_dicts.keys(), key=lambda dodgeball_id: list(step_ratio_dicts[dodgeball_id].values())[0][0] if len(step_ratio_dicts[dodgeball_id]) > 0 else float('inf'))
        step_ratio_dicts_2 = {}
        for dodgeball_id in sorted_dodgeball_ids:
            if len(step_ratio_dicts[dodgeball_id]) > 0:
                beater_id = list(step_ratio_dicts[dodgeball_id].keys())[0]
                if beater_id not in assigned_beater_ids:
                    beater = self.logic.state.players[beater_id]
                    dodgeball = self.logic.state.balls[dodgeball_id]
                    # self.logger.debug(f"Beater {beater.id} assigned to get dodgeball {dodgeball.id} which is not currently possessed by any team")
                    assigned_beater_ids.append(beater_id)
                    # move towards the dodgeball
                    if beater.id in self.cpu_player_ids:
                        # if beater has ball, pass to teammate or back to hoops
                        intercepting_position = step_ratio_dicts[dodgeball_id][beater_id][2]
                        beater.direction = Vector2(
                                intercepting_position.x - beater.position.x,
                                intercepting_position.y - beater.position.y
                            )
                else: # perform another interception ratio calculation
                    unassigned_beater_ids = [beater.id for beater in self.beaters if beater.id not in assigned_beater_ids]
                    _, step_ratio_dict = self.interception_ratio_calculator_team_0(
                        dt=dt,
                        moving_entity=dodgeball,
                        intercepting_player_ids=unassigned_beater_ids,
                        target_position=None,
                        only_first_intercepting=True, # in rare cases if one beater would get two dodgeball, this could cause issues so only assign one beater per dodgeball
                        max_dt_steps=self.determine_attacking_team_max_dt_steps,
                        max_distance_per_step=self.determine_attacking_team_max_distance_per_step,
                        max_dt_per_step=self.determine_attacking_team_max_dt_per_step
                    )
                    step_ratio_dicts_2[dodgeball_id] = step_ratio_dict
            else: # no intercepting beater found, these dodgeballs will be assigned based on proximity in the next step, so add them to unassigned_dodgeball_ids
                    unassigned_dodgeball_ids.append(dodgeball_id)
        return step_ratio_dicts_2, assigned_beater_ids, unassigned_dodgeball_ids

    def _distance_based_beater_assignment(self, unassigned_dodgeball_ids: List[str], assigned_beater_ids: List[str]):
        # calculate distances to unassigned beaters for unassigned dodgeballs and assign closest beater to each unassigned dodgeball
        squared_distances_dict = {}
        for dodgeball_id in unassigned_dodgeball_ids:
            dodgeball = self.logic.state.balls[dodgeball_id]
            for beater in self.beaters:
                if not beater.is_knocked_out and beater.id not in assigned_beater_ids:
                    direction_to_dodgeball = Vector2(
                            dodgeball.position.x - beater.position.x,
                            dodgeball.position.y - beater.position.y
                        )
                    squared_distance_to_dodgeball = UtilityLogic._squared_sum(direction_to_dodgeball.x, direction_to_dodgeball.y)
                    squared_distances_dict[(beater.id, dodgeball_id)] = (squared_distance_to_dodgeball, direction_to_dodgeball)
        sorted_squared_distances = sorted(squared_distances_dict.keys(), key=lambda k: squared_distances_dict[k][0])
        for beater_id, dodgeball_id in sorted_squared_distances:
            if beater_id not in assigned_beater_ids and dodgeball_id in unassigned_dodgeball_ids:
                beater = self.logic.state.players[beater_id]
                dodgeball = self.logic.state.balls[dodgeball_id]
                # self.logger.debug(f"Beater {beater.id} assigned to get unassigned dodgeball {dodgeball.id} based on proximity")
                assigned_beater_ids.append(beater_id)
                unassigned_dodgeball_ids.remove(dodgeball_id)
                # move towards the dodgeball
                if beater.id in self.cpu_player_ids:
                    direction_to_dodgeball = squared_distances_dict[(beater_id, dodgeball_id)][1]
                    beater.direction = direction_to_dodgeball
                    self.logger.debug("CPU Beater %s positioned at %s assigned to get dodgeball %s based on proximity", beater.id, beater.position, dodgeball.id)
        return assigned_beater_ids

    def _determine_attacking_team(self, dt: float) -> Tuple[int, str, Vector2]:
        """Return the attacking team and player id of the chaser/keeper assigned to the volleyball"""
        volleyball  = self.logic.state.volleyball
        if volleyball.turnover_to_player is not None:
            player = self.logic.state.players[volleyball.turnover_to_player]
            return player.team, player.id, None
        if volleyball.inbounder is not None:
            player = self.logic.state.players[volleyball.inbounder]
            return player.team, player.id, None
        if volleyball.holder_id is not None:
            return volleyball.possession_team, volleyball.holder_id, None
        if volleyball.is_dead:
            volleyball_holder_id = None
            # get keeper who might get control of dead volleyball
            for player in self.logic.state.players.values():
                if player.has_ball == volleyball.id:
                    volleyball_holder_id = player.id
                    break
            return volleyball.possession_team, volleyball_holder_id, None
        else:
            lowest_interception_time, assigned_player_id, _ = self.interception_ratio_calculator_team_0.line_interception(
                moving_entity=volleyball,
                intercepting_player_ids=[player.id for player in self.logic.state.players.values() if player.role in [PlayerRole.CHASER, PlayerRole.KEEPER]],
            )
            if assigned_player_id is not None:
                assigned_player = self.logic.state.players[assigned_player_id]
                attacking_team = assigned_player.team
                interception_position = Vector2(
                volleyball.position.x + volleyball.velocity.x * lowest_interception_time,
                volleyball.position.y + volleyball.velocity.y * lowest_interception_time
            )
                return attacking_team, assigned_player_id, interception_position
            # # elif volleyball.velocity.x > 0 or volleyball.velocity.y > 0:
            # potential_intercepting_players_0 = [player.id for player in self.logic.state.players.values() if player.role in [PlayerRole.CHASER, PlayerRole.KEEPER] and player.team == 0]
            # potential_intercepting_players_1 = [player.id for player in self.logic.state.players.values() if player.role in [PlayerRole.CHASER, PlayerRole.KEEPER] and player.team == 1]
            # # need to consider two cases due to different move_hoop_blockage
            # _, step_ratio_dict_team_0 = self.interception_ratio_calculator_team_0(
            #     dt=dt,
            #     moving_entity=volleyball,
            #     intercepting_player_ids=potential_intercepting_players_0,
            #     target_position=None,
            #     only_first_intercepting=True,
            #     max_dt_steps=self.determine_attacking_team_max_dt_steps,
            #     max_distance_per_step=self.determine_attacking_team_max_distance_per_step,
            #     max_dt_per_step=self.determine_attacking_team_max_dt_per_step

            # )
            # _, step_ratio_dict_team_1 = self.interception_ratio_calculator_team_1(
            #     dt=dt,
            #     moving_entity=volleyball,
            #     intercepting_player_ids=potential_intercepting_players_1,
            #     target_position=None,
            #     only_first_intercepting=True,
            #     max_dt_steps=self.determine_attacking_team_max_dt_steps,
            #     max_distance_per_step=self.determine_attacking_team_max_distance_per_step,
            #     max_dt_per_step=self.determine_attacking_team_max_dt_per_step
            # )
            # step_ratio_dict = {**step_ratio_dict_team_0, **step_ratio_dict_team_1}
            # step_ratio_dict = {}
            # if len(step_ratio_dict) > 0:
            #     if len(step_ratio_dict) > 1:
            #         # get player with lowest step in step_ratio_dict[player_id] = (step, step_ratio)
            #         min_step = float('inf')
            #         min_player_id = None
            #         for player_id, (step, step_ratio, _) in step_ratio_dict.items():
            #             if step < min_step:
            #                 min_step = step
            #                 min_player_id = player_id
            #         player_id = min_player_id

            #     else:
            #         player_id = list(step_ratio_dict.keys())[0]
            #     player = self.logic.state.players[player_id]               
            #     intercepting_position = step_ratio_dict[player_id][2]
            #     self.logger.debug(
            #         "Ball potentially intercepted by player %s from position %s in team %s with details %s",
            #         player_id,
            #         player.position,
            #         player.team,
            #         step_ratio_dict[player_id],
            #     )
            #     return player.team, player_id, intercepting_position
            # If no intercepting players, determine attacking team based on proximity to volleyball
            for other_id, distance in self.logic.state.squared_distances_ball_player.get(volleyball.id, []):
                player = self.logic.state.players[other_id]
                if not player.is_knocked_out:
                    if player.role in [PlayerRole.CHASER, PlayerRole.KEEPER]:
                        return player.team, player.id, None
            # if all players are knocked out
            return None, None, None