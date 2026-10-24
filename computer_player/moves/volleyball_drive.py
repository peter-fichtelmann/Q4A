from typing import TYPE_CHECKING, List, Optional, Set, Tuple

from core.entities import Hoop, Player, Vector2
from core.game_logic.utility_logic import UtilityLogic
from computer_player.base_strategy import StepContext
from computer_player.computer_player_utility.computer_player_utility import PassOption
from computer_player.moves.move import Move, MoveStatus

if TYPE_CHECKING:
    from computer_player.computer_player_orchestrator import ComputerPlayerOrchestrator


class VolleyballDrive(Move):
    """
    Attack move: the carrier drives straight at the opponent hoop with the lowest risk of interception.

    Start: the attacking team holds the volleyball with a CPU carrier in the opponent's half, at least
    `min_chaser_keepers` chasers/keepers of the team are not knocked out, and the carrier is
    neither tackled nor close to an opponent live dodgeball (otherwise it would pass at once).
    The carrier is the only participant.

    The carrier runs at full stick input straight to the target hoop, without evade vectors.
    It shoots exactly like the base strategy. If it is tackled or an opponent live dodgeball is
    closer than `dodgeball_pass_distance`, it passes to the best good pass option among its
    team's chasers/keepers. All other players stay with the base strategies.

    Success: the team scores or a teammate holds the volleyball after the carrier passed.
    Failure: turnover, timeout, the carrier losing the ball without passing (e.g. beaten),
    a missed shot, or the pass coming back to the carrier.
    Aborted: human takeover of the carrier/receiver, or a restart (inbounding, turnover ball).
    """
    name = "volleyball_drive"
    side = "attack"
    exclusive_group = "volleyball_carrier"

    def __init__(self,
                 orchestrator: 'ComputerPlayerOrchestrator',
                 team: int,
                 participant_ids: List[str],
                 start_time: float,
                 max_duration: float = 15,
                 min_chaser_keepers: int = 3,
                 dodgeball_pass_distance: float = 3,
                 tackle_window: float = 1.0,
                 pass_interception_threshold: float = 0.95,
                 hoop_switch_margin: float = 0.2,
                 logger=None):
        """Store the carrier and the pass criteria."""
        super().__init__(orchestrator, team, participant_ids, start_time, max_duration, logger)
        self.carrier_id = participant_ids[0]
        self.min_chaser_keepers = min_chaser_keepers
        self.squared_dodgeball_pass_distance = dodgeball_pass_distance**2
        self.tackle_window = tackle_window
        self.pass_interception_threshold = pass_interception_threshold
        self.hoop_switch_margin = hoop_switch_margin
        self.target_hoop_id: Optional[str] = None
        self.released_by_pass = False # the carrier let go of the volleyball with a move pass
        self.shot_taken = False
        self.intended_receiver_id: Optional[str] = None
        self.pass_reason: Optional[str] = None

    @staticmethod
    def in_opponent_half(state, team: int, player: Player) -> bool:
        """Whether `player` of `team` is past the midline, towards the opponent hoops."""
        x_min, x_max = state.boundaries_x
        midline_x = (x_min + x_max) / 2
        return player.position.x > midline_x if team == 0 else player.position.x < midline_x

    @classmethod
    def try_start(cls,
                  orchestrator: 'ComputerPlayerOrchestrator',
                  ctx: StepContext,
                  team: int,
                  available_cpu_ids: Set[str],
                  min_chaser_keepers: int = 3,
                  **params) -> Optional['VolleyballDrive']:
        """Start if a free CPU carrier holds the volleyball in the opponent's half with enough chasers/keepers on stick."""
        state = orchestrator.logic.state
        volleyball = state.volleyball
        if ctx.attack_team != team or volleyball is None:
            return None
        if volleyball.holder_id is None or volleyball.is_dead or volleyball.inbounder is not None or volleyball.turnover_to_player is not None:
            return None
        carrier = state.players[volleyball.holder_id]
        if carrier.team != team or carrier.id not in available_cpu_ids or carrier.is_knocked_out:
            return None
        if not cls.in_opponent_half(state, team, carrier):
            return None
        roster = ctx.rosters[team]
        on_stick = sum(1 for player_id in roster.chaser_keeper_ids if not state.players[player_id].is_knocked_out)
        if on_stick < min_chaser_keepers:
            return None
        move = cls(orchestrator, team, [carrier.id], ctx.game_time, min_chaser_keepers=min_chaser_keepers, **params)
        if move.pass_trigger(carrier) is not None:
            return None
        return move

    def pass_trigger(self, carrier: Player) -> Optional[str]:
        """Why the carrier has to pass now ('tackled' or 'dodgeball_close'), or None."""
        state = self.logic.state
        if state.volleyball.time_since_carrier_tackled <= self.tackle_window:
            return "tackled"
        opponent_team = 1 - self.team
        for dodgeball in state.dodgeballs:
            if dodgeball.possession_team != opponent_team:
                continue # dead or own dodgeball
            if UtilityLogic._squared_distance(carrier.position, dodgeball.position) < self.squared_dodgeball_pass_distance:
                return "dodgeball_close"
        return None

    def hoop_scores(self, carrier: Player, opponent_hoops: List[Hoop], opponent_chaser_keeper_ids: List[str]) -> List[Tuple[float, Hoop]]:
        """Interception score of the carrier running at full speed to each opponent hoop; the larger, the safer."""
        interception_calculator = self.orchestrator.interception_calculator
        scores = []
        for hoop in opponent_hoops:
            run_vector = Vector2(hoop.position.x - carrier.position.x, hoop.position.y - carrier.position.y)
            if run_vector.x == 0 and run_vector.y == 0:
                scores.append((float('inf'), hoop))
                continue
            beam_cosine_angle, beam_cosine_angle_player_id, _ = interception_calculator.beam_cosine_angle(
                moving_entity=carrier,
                intercepting_player_ids=opponent_chaser_keeper_ids,
                target_position=hoop.position,
                moving_entity_target_vector=run_vector,
            )
            score = interception_calculator.interception_score_from_beam_cosine_angle(
                beam_cosine_angle=beam_cosine_angle,
                beam_angle_player_id=beam_cosine_angle_player_id,
                mag_moving_entity_velocity=carrier.max_speed,
            )
            scores.append((score, hoop))
        return scores

    def target_hoop(self, carrier: Player, opponent_hoops: List[Hoop], opponent_chaser_keeper_ids: List[str]) -> Hoop:
        """Opponent hoop with the highest interception score; the current target is kept unless another is better by the switch margin."""
        scores = self.hoop_scores(carrier, opponent_hoops, opponent_chaser_keeper_ids)
        best_score, best_hoop = max(scores, key=lambda item: item[0])
        current = next(((score, hoop) for score, hoop in scores if hoop.id == self.target_hoop_id), None)
        if current is not None and best_score - current[0] <= self.hoop_switch_margin:
            return current[1]
        if self.target_hoop_id is not None:
            self.logger.debug("VolleyballDrive player %s switches target hoop to %s (score %.2f)", carrier.id, best_hoop.id, best_score)
        self.target_hoop_id = best_hoop.id
        return best_hoop

    def best_good_pass(self, ctx: StepContext, carrier: Player) -> Optional[Tuple[PassOption, float]]:
        """
        Best good pass option of `carrier` as (pass option, receiver penalty), or None.

        Candidates are the team's chasers/keepers other than the carrier, on stick and within the base
        strategy's maximum passing distance, ranked by the pass-to-player score (position penalty).
        The first that is reachable, not through own hoops, and has an interception score
        >= `pass_interception_threshold` is taken.
        """
        state = self.logic.state
        volleyball = state.volleyball
        roster = ctx.rosters[self.team]
        diamond = self.orchestrator.diamond_attack_chaser_keeper
        pass_evaluator = self.orchestrator.pass_evaluator
        zero = Vector2(0, 0)
        ball_distances = state.squared_distances_ball_player_dicts[volleyball.id]
        candidates = []
        for player_id in roster.chaser_keeper_ids:
            if player_id == carrier.id:
                continue
            player = state.players[player_id]
            if player.is_knocked_out:
                continue
            if ball_distances.get(player_id, float('inf')) > diamond.passing_squared_max_distance:
                continue
            penalty = pass_evaluator.position_penalty(player, roster.opponent_hoops, diamond.evade_vectors.get(player_id, zero))
            candidates.append((penalty, player_id))
        candidates.sort()
        for penalty, player_id in candidates:
            pass_option = pass_evaluator.evaluate(volleyball, carrier, state.players[player_id], roster.own_hoops, roster.opponent_chaser_keeper_ids)
            if pass_option is not None and pass_evaluator.is_safe(pass_option, self.pass_interception_threshold):
                return pass_option, penalty
        return None

    def _update_status(self, ctx: StepContext) -> None:
        """Check the success and failure criteria of the drive."""
        state = self.logic.state
        volleyball = state.volleyball
        if ctx.events.goal_scored_by == self.team:
            self.end(MoveStatus.SUCCESS, "goal")
            return
        if ctx.events.turnover_from == self.team: # actual possession, a predicted interception of a pass in flight is no turnover
            self.end(MoveStatus.FAILURE, "turnover")
            return
        if volleyball.is_dead or volleyball.inbounder is not None or volleyball.turnover_to_player is not None:
            self.end(MoveStatus.ABORTED, "restart")
            return
        holder_id = volleyball.holder_id
        if holder_id is None:
            # volleyball in flight or loose
            if self.shot_taken:
                return # wait for the goal (or the turnover/timeout)
            if not self.released_by_pass:
                self.end(MoveStatus.FAILURE, "carrier_lost_ball") # e.g. beaten
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
        if holder_id == self.carrier_id:
            if self.released_by_pass:
                self.end(MoveStatus.FAILURE, "pass_back")
            elif holder_id not in ctx.cpu_player_id_set:
                self.end(MoveStatus.ABORTED, "human_holder")
            return
        if self.released_by_pass:
            self.end(MoveStatus.SUCCESS, "pass_caught")
        else:
            self.end(MoveStatus.FAILURE, "carrier_lost_ball")

    def controlled_player_ids(self, ctx: StepContext) -> Set[str]:
        """Only the carrier, while it is CPU controlled and holds the volleyball."""
        holder_id = self.logic.state.volleyball.holder_id
        if self.status == MoveStatus.RUNNING and holder_id == self.carrier_id and holder_id in ctx.cpu_player_id_set:
            return {holder_id}
        return set()

    def step(self, ctx: StepContext) -> None:
        """Shoot like the base attack, pass when tackled or a dodgeball is close, otherwise drive at the target hoop."""
        if not self.controlled_player_ids(ctx):
            return
        state = self.logic.state
        volleyball = state.volleyball
        carrier = state.players[self.carrier_id]
        roster = ctx.rosters[self.team]
        if self.orchestrator.score_attempter.attempt(volleyball, carrier, roster.opponent_hoops, roster.opponent_chaser_keeper_ids):
            self.shot_taken = True
            return
        hoop = self.target_hoop(carrier, roster.opponent_hoops, roster.opponent_chaser_keeper_ids)
        run_vector = Vector2(hoop.position.x - carrier.position.x, hoop.position.y - carrier.position.y)
        mag_run_vector = UtilityLogic._magnitude(run_vector)
        carrier.direction = Vector2(run_vector.x / mag_run_vector, run_vector.y / mag_run_vector) if mag_run_vector > 0 else Vector2(0, 0)
        trigger = self.pass_trigger(carrier)
        if trigger is None:
            return
        best = self.best_good_pass(ctx, carrier)
        if best is None:
            return # keep driving (or standing in the tackle) and look again next step
        pass_option, receiver_penalty = best
        if not self.logic.process_action_logic.process_throw_action(carrier.id, throw_direction=pass_option.throw_direction):
            return # refused e.g. right after receiving a turnover ball, try again next step
        self.logger.info(
            "VolleyballDrive pass (%s) from player %s to player %s, position penalty %.1f, interception score %.2f",
            trigger, carrier.id, pass_option.receiver_id, receiver_penalty, pass_option.interception_score,
        )
        self.released_by_pass = True
        self.intended_receiver_id = pass_option.receiver_id
        self.pass_reason = trigger

    def describe(self) -> str:
        """Target hoop and pass reason."""
        return f"carrier={self.carrier_id[-4:]} hoop={self.target_hoop_id} pass={self.pass_reason}"
