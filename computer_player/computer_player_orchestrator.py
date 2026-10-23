from dataclasses import dataclass
import logging
import random
from typing import Dict, List, Optional, Tuple

from core.game_logic.game_logic import GameLogic
from computer_player.computer_player import ComputerPlayer
from computer_player.base_strategy import BaseStrategy, PossessionEvents, StepContext, TeamRoster
from computer_player.diamond_attack import DiamondAttackBeater, DiamondAttackChaserKeeper
from computer_player.hoop_defence import HoopDefenceBeater, HoopDefenceChaserKeeper
from computer_player.box_defence import BoxDefenceChaserKeeper
from computer_player.dodgeball_assigner import DodgeballAssigner
from computer_player.seeker_director import SeekerDirector
from computer_player.volleyball_possession_calculator import VolleyballPossession, VolleyballPossessionCalculator
from computer_player.moves.move import Move, MoveStatus
from computer_player.moves.volleyball_shift import VolleyballShift
from computer_player.computer_player_utility.move_around_hoop_blockage import MoveAroundHoopBlockage
from computer_player.computer_player_utility.interception_calculator import InterceptionCalculator
from computer_player.computer_player_utility.computer_player_utility import BeaterThrowDecider, PassEvaluator, ScoreAttempter


@dataclass
class MoveSpec:
    """A registered move type with its sampling configuration."""
    move_class: type
    start_probability_per_second: float # probability that the move is tried within one game second
    cooldown: float # game seconds after a move ended before the same team may start it again
    params: dict # passed to move_class.try_start


class ComputerPlayerOrchestrator(ComputerPlayer):
    """
    Top-level CPU controller that holds the strings.

    Every step it
        1. asks the VolleyballPossessionCalculator which team possesses the volleyball (attack) and derives
           possession events (goal, turnover),
        2. ends moves whose stop criteria are met and samples new moves for the attack and defence team,
        3. runs the base strategies (chasers+keeper and beaters, for attack and defence) for all CPU players
           that no move controls,
        4. runs the moves for their players, and the seeker director.
    """
    MOVE_CLASSES: Dict[str, type] = {
        VolleyballShift.name: VolleyballShift,
    }

    def __init__(self,
                 game_logic: GameLogic,
                 move_buffer_factor_x: float = 1.2,
                 move_buffer_factor_y: float = 1.2,
                 diamond_attack_kwargs: Optional[Dict] = None,
                 hoop_defence_kwargs: Optional[Dict] = None,
                 box_defence_kwargs: Optional[Dict] = None,
                 box_defence_probability: float = 0.5,
                 scoring_kwargs: Optional[Dict] = None,
                 passing_kwargs: Optional[Dict] = None,
                 moves: Optional[Dict[str, Dict]] = None,
                 beater_throw_threshold_volleyball_holder: float = 5,
                 beater_throw_threshold_loaded_beater: float = 4,
                 computer_player_log_level: int = logging.INFO
                 ):
        """Build the possession calculator, base strategies and move registry once."""
        super().__init__(game_logic, computer_player_log_level=computer_player_log_level)
        diamond_attack_kwargs = diamond_attack_kwargs or {}
        hoop_defence_kwargs = hoop_defence_kwargs or {}
        box_defence_kwargs = box_defence_kwargs or {}
        state = self.logic.state

        volleyball_radius = state.volleyball.radius if state.volleyball is not None else 0
        # per team, around the team's own hoops
        move_around_hoop_blockages = {
            team: MoveAroundHoopBlockage(
                defence_hoops=[hoop for hoop in state.hoops.values() if (hoop.team == 0) == (team == 0)],
                move_buffer_factor_x=move_buffer_factor_x,
                move_buffer_factor_y=move_buffer_factor_y,
                volleyball_radius=volleyball_radius,
                logger=self.logger
            )
            for team in (0, 1)
        }
        self.rosters = {team: TeamRoster.build(state, team) for team in (0, 1)}
        self.interception_calculator = InterceptionCalculator(logic=self.logic)
        self.possession_calculator = VolleyballPossessionCalculator(self.logic, self.interception_calculator)
        beater_throw_decider = BeaterThrowDecider(
            throw_threshold_volleyball_holder=beater_throw_threshold_volleyball_holder,
            throw_threshold_loaded_beater=beater_throw_threshold_loaded_beater
        )
        self.score_attempter = ScoreAttempter(
            self.interception_calculator,
            self.logic.process_action_logic,
            logger=self.logger,
            **(scoring_kwargs or {})
        )
        self.pass_evaluator = PassEvaluator(self.interception_calculator, **(passing_kwargs or {}))
        self.dodgeball_assigner = DodgeballAssigner(self.logic, self.interception_calculator, beater_throw_decider, logger=self.logger)

        # base strategies
        self.diamond_attack_chaser_keeper = DiamondAttackChaserKeeper(
            self.logic, move_around_hoop_blockages, self.score_attempter, self.pass_evaluator,
            logger=self.logger, **diamond_attack_kwargs.get('chaser_keeper', {})
        )
        self.diamond_attack_beater = DiamondAttackBeater(
            self.logic, beater_throw_decider, logger=self.logger, **diamond_attack_kwargs.get('beater', {})
        )
        self.hoop_defence_chaser_keeper = HoopDefenceChaserKeeper(
            self.logic, move_around_hoop_blockages, logger=self.logger, **hoop_defence_kwargs.get('chaser_keeper', {})
        )
        self.hoop_defence_beater = HoopDefenceBeater(
            self.logic, beater_throw_decider, logger=self.logger, **hoop_defence_kwargs.get('beater', {})
        )
        self.box_defence_chaser_keeper = BoxDefenceChaserKeeper(
            self.logic, move_around_hoop_blockages, logger=self.logger, **box_defence_kwargs.get('chaser_keeper', {})
        )
        self.attack_strategies = [self.diamond_attack_chaser_keeper, self.diamond_attack_beater]
        # the chaser/keeper defence strategy is chosen each time a team starts defending
        self.box_defence_probability = box_defence_probability
        self.defence_chaser_keeper_strategies: Dict[int, BaseStrategy] = {}
        self._previous_defence_team: Optional[int] = None
        self.seeker_director = SeekerDirector(state)

        # moves
        self.move_specs: List[MoveSpec] = []
        for move_name, move_kwargs in (moves or {}).items():
            move_kwargs = dict(move_kwargs)
            self.move_specs.append(MoveSpec(
                move_class=self.MOVE_CLASSES[move_name],
                start_probability_per_second=move_kwargs.pop('start_probability_per_second', 0.0),
                cooldown=move_kwargs.pop('cooldown', 0.0),
                params=move_kwargs,
            ))
        self.active_moves: List[Move] = []
        self._move_cooldown_until: Dict[Tuple[str, int], float] = {}

        # possession tracking for events
        self.game_time = 0.0 # accumulated dt of the computer player steps
        self._previous_attack_team: Optional[int] = None
        self._previous_score: List[int] = list(state.score)

    def make_move(self, dt: float, cpu_player_ids: List[str]):
        """Run one decision cycle for all controlled players."""
        self._bind_cpu_players(cpu_player_ids)
        self.game_time += dt
        possession = self._profile_call('orchestrator.possession_calculator', self.possession_calculator, dt)
        events = self._possession_events(possession)
        attack_team = possession.team
        # with no attacking team (all chasers/keepers knocked out) team 0 defends
        defence_team = 1 - attack_team if attack_team is not None else 0
        ctx = StepContext(
            dt=dt,
            game_time=self.game_time,
            possession=possession,
            attack_team=attack_team,
            defence_team=defence_team,
            events=events,
            cpu_player_id_set=self.cpu_player_id_set,
            rosters=self.rosters,
        )
        self._select_defence_strategy(ctx)
        self._profile_call('orchestrator.update_moves', self._update_moves, ctx)
        self._profile_call('orchestrator.sample_moves', self._sample_moves, ctx)

        move_controlled_ids = set()
        for move in self.active_moves:
            move_controlled_ids |= move.controlled_player_ids(ctx)
        steerable_ids = [player.id for player in self.cpu_players if player.id not in move_controlled_ids]
        steerable_id_set = set(steerable_ids)

        assigned_beater_ids = self._profile_call('orchestrator.dodgeball_assigner', self.dodgeball_assigner, attack_team, steerable_id_set)
        defence_ids = [player_id for player_id in steerable_ids if self.logic.state.players[player_id].team != attack_team]
        defence_strategies = [self.defence_chaser_keeper_strategies[defence_team], self.hoop_defence_beater]
        for strategy in defence_strategies:
            self._profile_call(f'orchestrator.{type(strategy).__name__}', strategy, ctx, defence_team, defence_ids, assigned_beater_ids)
        if attack_team is not None:
            attack_ids = [player_id for player_id in steerable_ids if self.logic.state.players[player_id].team == attack_team]
            for strategy in self.attack_strategies:
                self._profile_call(f'orchestrator.{type(strategy).__name__}', strategy, ctx, attack_team, attack_ids, assigned_beater_ids)
        # TODO: with no attacking team (all chasers/keepers knocked out), only team 0 defends

        for move in self.active_moves:
            self._profile_call(f'orchestrator.move.{move.name}', move.step, ctx)
        self.seeker_director.update_seeker_direction(dt, self.cpu_seekers)

    def _possession_events(self, possession: VolleyballPossession) -> PossessionEvents:
        """Goal and turnover since the previous step. A goal flips possession too, so it is checked first."""
        events = PossessionEvents()
        score = self.logic.state.score
        for team in (0, 1):
            if score[team] > self._previous_score[team]:
                events.goal_scored_by = team
        if (events.goal_scored_by is None
                and possession.team is not None
                and self._previous_attack_team is not None
                and possession.team != self._previous_attack_team):
            events.turnover_from = self._previous_attack_team
        self._previous_score = list(score)
        if possession.team is not None:
            self._previous_attack_team = possession.team
        return events

    def _select_defence_strategy(self, ctx: StepContext) -> None:
        """Choose hoop or box defence for the chasers/keeper when a team starts defending."""
        team = ctx.defence_team
        if team == self._previous_defence_team and team in self.defence_chaser_keeper_strategies:
            return
        self._previous_defence_team = team
        # no random draw for probability 0 or 1, so traces stay reproducible
        if self.box_defence_probability <= 0:
            use_box_defence = False
        elif self.box_defence_probability >= 1:
            use_box_defence = True
        else:
            use_box_defence = random.random() < self.box_defence_probability
        strategy = self.box_defence_chaser_keeper if use_box_defence else self.hoop_defence_chaser_keeper
        strategy.reset(team)
        self.defence_chaser_keeper_strategies[team] = strategy
        self.logger.info("Defence strategy: team=%s %s", team, type(strategy).__name__)

    def _update_moves(self, ctx: StepContext) -> None:
        """Remove moves whose stop criteria are met and start their cooldown."""
        still_running = []
        for move in self.active_moves:
            status = move.update_status(ctx)
            if status == MoveStatus.RUNNING:
                still_running.append(move)
                continue
            spec = next(spec for spec in self.move_specs if spec.move_class is type(move))
            self._move_cooldown_until[(move.name, move.team)] = ctx.game_time + spec.cooldown
            self.logger.info(
                "Move ended: %s team=%s status=%s reason=%s duration=%.1f %s",
                move.name, move.team, status.value, move.end_reason, ctx.game_time - move.start_time, move.describe(),
            )
        self.active_moves = still_running

    def _sample_moves(self, ctx: StepContext) -> None:
        """Roll each registered move for the attack and defence team, and start it if its start condition holds."""
        for team, side in ((ctx.attack_team, 'attack'), (ctx.defence_team, 'defence')):
            if team is None:
                continue
            for spec in self.move_specs:
                move_class = spec.move_class
                if move_class.side != side or spec.start_probability_per_second <= 0:
                    continue
                if any(type(move) is move_class and move.team == team for move in self.active_moves):
                    continue
                if ctx.game_time < self._move_cooldown_until.get((move_class.name, team), float('-inf')):
                    continue
                # probability per step for a probability per game second, independent of dt
                step_probability = 1 - (1 - spec.start_probability_per_second) ** ctx.dt
                if random.random() >= step_probability:
                    continue
                taken_ids = set()
                for move in self.active_moves:
                    taken_ids |= set(move.participant_ids)
                available_cpu_ids = {player.id for player in self.cpu_players if player.id not in taken_ids}
                move = move_class.try_start(self, ctx, team, available_cpu_ids, logger=self.logger, **spec.params)
                if move is not None:
                    self.active_moves.append(move)
                    self.logger.info(
                        "Move started: %s team=%s participants=%s carrier=%s",
                        move.name, team, [player_id[-4:] for player_id in move.participant_ids],
                        (self.logic.state.volleyball.holder_id or '')[-4:],
                    )
