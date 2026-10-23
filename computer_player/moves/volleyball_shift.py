from typing import TYPE_CHECKING, Dict, List, Optional, Set, Tuple

from core.entities import Player, Vector2
from core.game_logic.utility_logic import UtilityLogic
from computer_player.base_strategy import StepContext
from computer_player.computer_player_utility.computer_player_utility import PassOption
from computer_player.moves.move import Move, MoveStatus

if TYPE_CHECKING:
    from computer_player.computer_player_orchestrator import ComputerPlayerOrchestrator


class VolleyballShift(Move):
    """
    Attack move: shift the volleyball with two quick passes to open up the other side of the hoops.

    Start: the attacking team holds the volleyball and at least `min_participants` of its
    on-stick CPU chasers/keepers, the carrier included, are past `attack_line_fraction` of the
    pitch (towards the opponent hoops). These players are the participants.

    The move only steers the current carrier (if a participant): it positions it like the
    diamond attack, shoots exactly like the base strategy, and otherwise passes to the best
    good pass option among the participants, excluding the previous carrier.
    All other players stay with the base strategies.

    Success: the third participant holds the volleyball (second pass caught) or the team scores.
    Failure: turnover, no good pass option, timeout, delay of game building up, the carrier
    losing the ball without passing, a missed shot, or a non-participant teammate picking the ball up.
    Aborted: human takeover of the carrier/receiver, or a restart (inbounding, turnover ball).
    """
    name = "volleyball_shift"
    side = "attack"

    def __init__(self,
                 orchestrator: 'ComputerPlayerOrchestrator',
                 team: int,
                 participant_ids: List[str],
                 start_time: float,
                 carrier_id: str,
                 max_duration: float = 12,
                 attack_line_fraction: float = 0.6,
                 min_participants: int = 3,
                 pass_interception_threshold: float = 1.0,
                 loaded_beater_radius: float = 7,
                 max_pass_penalty_worsening: float = 100,
                 delay_of_game_fraction: float = 0.5,
                 logger=None):
        """Store the participants, the first carrier and the pass criteria."""
        super().__init__(orchestrator, team, participant_ids, start_time, max_duration, logger)
        self.attack_line_fraction = attack_line_fraction
        self.min_participants = min_participants
        self.pass_interception_threshold = pass_interception_threshold
        self.squared_loaded_beater_radius = loaded_beater_radius**2
        self.max_pass_penalty_worsening = max_pass_penalty_worsening
        self.delay_of_game_fraction = delay_of_game_fraction
        self.participant_id_set = set(participant_ids)
        self.holder_chain: List[str] = [carrier_id] # distinct participants that held the volleyball, in order
        self.passes = 0
        self.released_by_pass = False # the last carrier let go of the volleyball with a move pass
        self.shot_taken = False
        self.intended_receiver_id: Optional[str] = None

    @staticmethod
    def attack_line_x(state, team: int, attack_line_fraction: float) -> float:
        """x of the line a participant has to be past, `attack_line_fraction` of the pitch seen from the team's own end."""
        x_min, x_max = state.boundaries_x
        if team == 0:
            return x_min + attack_line_fraction * (x_max - x_min)
        return x_max - attack_line_fraction * (x_max - x_min)

    @classmethod
    def try_start(cls,
                  orchestrator: 'ComputerPlayerOrchestrator',
                  ctx: StepContext,
                  team: int,
                  available_cpu_ids: Set[str],
                  attack_line_fraction: float = 0.6,
                  min_participants: int = 3,
                  **params) -> Optional['VolleyballShift']:
        """Start if the team holds the volleyball with enough CPU chasers/keepers past the attack line and a good pass exists."""
        state = orchestrator.logic.state
        volleyball = state.volleyball
        if ctx.attack_team != team or volleyball is None:
            return None
        if volleyball.holder_id is None or volleyball.is_dead or volleyball.inbounder is not None or volleyball.turnover_to_player is not None:
            return None
        carrier = state.players[volleyball.holder_id]
        if carrier.team != team or carrier.id not in available_cpu_ids:
            return None
        line_x = cls.attack_line_x(state, team, attack_line_fraction)
        roster = ctx.rosters[team]
        participant_ids = []
        for player_id in roster.chaser_keeper_ids:
            player = state.players[player_id]
            if player_id not in available_cpu_ids or player.is_knocked_out:
                continue
            if (team == 0 and player.position.x >= line_x) or (team == 1 and player.position.x <= line_x):
                participant_ids.append(player_id)
        if carrier.id not in participant_ids or len(participant_ids) < min_participants:
            return None
        move = cls(orchestrator, team, participant_ids, ctx.game_time, carrier.id,
                   attack_line_fraction=attack_line_fraction, min_participants=min_participants, **params)
        # the base strategies have not run yet in this step, so compute this step's evade vectors here
        evade_vectors = orchestrator.diamond_attack_chaser_keeper.evade_vectors_chaser_keeper_calculation(roster)
        if move.best_good_pass(ctx, carrier, evade_vectors) is None:
            return None
        return move

    def _loaded_opponent_beater_close(self, player: Player, opponent_beater_ids: List[str]) -> bool:
        """Whether a loaded, on-stick opponent beater is within the loaded beater radius of `player`."""
        for beater_id in opponent_beater_ids:
            beater = self.logic.state.players[beater_id]
            if beater.is_knocked_out or not beater.has_ball:
                continue
            if UtilityLogic._squared_distance(player.position, beater.position) < self.squared_loaded_beater_radius:
                return True
        return False

    def best_good_pass(self, ctx: StepContext, carrier: Player, evade_vectors: Dict[str, Vector2]) -> Optional[Tuple[PassOption, float, float]]:
        """
        Best good pass option of `carrier` as (pass option, receiver penalty, carrier penalty), or None.

        Candidates are participants other than the carrier and the previous carrier, ranked by the
        pass-to-player score (position penalty). A good option:
            - is CPU controlled and on stick
            - is within the base strategy's maximum passing distance
            - has no loaded opponent beater within the loaded beater radius
            - worsens the position penalty by at most `max_pass_penalty_worsening` compared to the carrier
            - is reachable, not through own hoops, and has an interception score >= `pass_interception_threshold`
        """
        state = self.logic.state
        volleyball = state.volleyball
        roster = ctx.rosters[self.team]
        diamond = self.orchestrator.diamond_attack_chaser_keeper
        pass_evaluator = self.orchestrator.pass_evaluator
        zero = Vector2(0, 0)
        carrier_penalty = pass_evaluator.position_penalty(carrier, roster.opponent_hoops, evade_vectors.get(carrier.id, zero))
        previous_carrier_id = self.holder_chain[-2] if len(self.holder_chain) >= 2 else None
        ball_distances = state.squared_distances_ball_player_dicts[volleyball.id]
        candidates = []
        for player_id in self.participant_ids:
            if player_id == carrier.id or player_id == previous_carrier_id or player_id not in ctx.cpu_player_id_set:
                continue
            player = state.players[player_id]
            if player.is_knocked_out:
                continue
            if ball_distances.get(player_id, float('inf')) > diamond.passing_squared_max_distance:
                continue
            if self._loaded_opponent_beater_close(player, roster.opponent_beater_ids):
                continue
            penalty = pass_evaluator.position_penalty(player, roster.opponent_hoops, evade_vectors.get(player_id, zero))
            if penalty - carrier_penalty > self.max_pass_penalty_worsening:
                continue
            candidates.append((penalty, player_id))
        candidates.sort()
        for penalty, player_id in candidates:
            pass_option = pass_evaluator.evaluate(volleyball, carrier, state.players[player_id], roster.own_hoops, roster.opponent_chaser_keeper_ids)
            if pass_option is not None and pass_option.interception_score >= self.pass_interception_threshold:
                return pass_option, penalty, carrier_penalty
        return None

    def _update_status(self, ctx: StepContext) -> None:
        """Check the success and failure criteria of the shift."""
        state = self.logic.state
        volleyball = state.volleyball
        if ctx.events.goal_scored_by == self.team:
            self.end(MoveStatus.SUCCESS, "goal")
            return
        if ctx.events.turnover_from == self.team or ctx.attack_team != self.team:
            self.end(MoveStatus.FAILURE, "turnover")
            return
        if volleyball.is_dead or volleyball.inbounder is not None or volleyball.turnover_to_player is not None:
            self.end(MoveStatus.ABORTED, "restart")
            return
        if volleyball.delay_of_game_timer >= self.delay_of_game_fraction * state.delay_of_game_time_limit:
            self.end(MoveStatus.FAILURE, "delay_of_game")
            return
        holder_id = volleyball.holder_id
        if holder_id is None:
            # volleyball in flight or loose
            if self.shot_taken:
                return # wait for the goal (or the turnover/timeout)
            if not self.released_by_pass:
                self.end(MoveStatus.FAILURE, "carrier_lost_ball") # e.g. beaten or tackled
            elif self.intended_receiver_id is not None and self.intended_receiver_id not in ctx.cpu_player_id_set:
                self.end(MoveStatus.ABORTED, "human_receiver")
            return
        holder = state.players[holder_id]
        if holder.team != self.team:
            self.end(MoveStatus.FAILURE, "turnover")
            return
        if self.shot_taken:
            self.end(MoveStatus.FAILURE, "shot_missed")
            return
        if holder_id not in self.participant_id_set:
            self.end(MoveStatus.FAILURE, "non_participant_holder")
            return
        if holder_id not in ctx.cpu_player_id_set:
            self.end(MoveStatus.ABORTED, "human_holder")
            return
        if holder_id != self.holder_chain[-1]:
            if holder_id in self.holder_chain:
                self.end(MoveStatus.FAILURE, "pass_back") # e.g. a dropped pass picked up by an earlier carrier
                return
            self.holder_chain.append(holder_id)
            self.released_by_pass = False
            self.intended_receiver_id = None
            if len(self.holder_chain) >= 3:
                self.end(MoveStatus.SUCCESS, "second_pass_caught")

    def controlled_player_ids(self, ctx: StepContext) -> Set[str]:
        """Only the current carrier, if it is a CPU participant."""
        holder_id = self.logic.state.volleyball.holder_id
        if self.status == MoveStatus.RUNNING and holder_id in self.participant_id_set and holder_id in ctx.cpu_player_id_set:
            return {holder_id}
        return set()

    def step(self, ctx: StepContext) -> None:
        """Position the carrier like the base attack, shoot like the base attack, otherwise shift the volleyball."""
        controlled_ids = self.controlled_player_ids(ctx)
        if not controlled_ids:
            return
        state = self.logic.state
        volleyball = state.volleyball
        carrier = state.players[volleyball.holder_id]
        roster = ctx.rosters[self.team]
        diamond = self.orchestrator.diamond_attack_chaser_keeper
        diamond.position_player(carrier)
        if self.orchestrator.score_attempter.attempt(volleyball, carrier, roster.opponent_hoops, roster.opponent_chaser_keeper_ids):
            self.shot_taken = True
            return
        best = self.best_good_pass(ctx, carrier, diamond.evade_vectors)
        if best is None:
            self.end(MoveStatus.FAILURE, "no_good_pass_option")
            return
        pass_option, receiver_penalty, carrier_penalty = best
        self.logger.info(
            "VolleyballShift pass %s from player %s to player %s, position penalty %.1f -> %.1f, interception score %.2f",
            self.passes + 1, carrier.id, pass_option.receiver_id, carrier_penalty, receiver_penalty, pass_option.interception_score,
        )
        self.logic.process_action_logic.process_throw_action(carrier.id, throw_direction=pass_option.throw_direction)
        self.passes += 1
        self.released_by_pass = True
        self.intended_receiver_id = pass_option.receiver_id

    def describe(self) -> str:
        """Pass count and carrier chain."""
        return f"passes={self.passes} chain={[player_id[-4:] for player_id in self.holder_chain]}"
