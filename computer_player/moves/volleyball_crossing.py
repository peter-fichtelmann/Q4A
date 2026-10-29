import math
from typing import TYPE_CHECKING, List, Optional, Set, Tuple

from core.entities import Player, Vector2
from core.game_logic.utility_logic import UtilityLogic
from computer_player.base_strategy import StepContext, TeamRoster
from computer_player.computer_player_utility.computer_player_utility import MoveUtility
from computer_player.computer_player_utility.kinematics import terminal_speed
from computer_player.moves.move import Move, MoveStatus

if TYPE_CHECKING:
    from computer_player.computer_player_orchestrator import ComputerPlayerOrchestrator


class VolleyballCrossing(Move):
    """
    Attack move: carrier and a teammate cross paths in front of an opponent (scissors).

    Start: the attacking team holds a live volleyball with a free (not tackled) CPU carrier, and
    there is a pair of
        - a CPU teammate chaser/keeper (the receiver), on stick, within `teammate_max_distance` of the
          carrier and at least `teammate_min_lateral` to its side,
        - an on-stick opponent chaser/keeper (the defender) closer to the opponent hoops than both,
          within `opponent_max_distance` of their midpoint and laterally between them,
    such that the crossing point, `crossing_distance` in front of the defender, is at least
    `min_approach_distance` ahead of both runners, no loaded opponent beater is within
    `loaded_beater_path_distance` and no other opponent chaser/keeper within `blocking_path_distance`
    of their paths to it. Of several pairs the one with the shortest paths is taken.

    Approach: the carrier runs at the crossing point, which follows the defender sideways and towards
    the attackers, never away from them. The receiver runs at a point `receiver_behind_distance`
    behind it and arrives `receiver_time_gap` after the carrier, so it passes behind the carrier
    without contact; whoever is early slows down. The carrier shoots like the base strategy.

    Crossing: when the carrier reaches the crossing point (or is tackled), both turn to their exit
    lines, `exit_angle` from the attack direction, each towards the side the other came from.
    The defender's position in `opponent_prediction_time` (from its velocity) decides: if it will be
    closer to the carrier than to the receiver, the carrier passes to the receiver, otherwise it
    keeps the volleyball (dummy). An unsafe pass becomes a dummy.

    Exit: the holder runs its exit line for `exit_duration` (shooting like the base strategy).

    Success: the exit run ends with the volleyball (`pass_exit_done`, `dummy_exit_done`) or the team scores.
    Failure: turnover, timeout, a loaded beater or another opponent on the paths, the defender knocked
    out, the receiver too far away for the pass (`out_of_sync`), a participant knocked out, the
    carrier losing the ball without passing, a missed shot, or a pass back / to a third teammate.
    Aborted: human takeover of the carrier/receiver, or a restart (inbounding, turnover ball).
    """
    name = "volleyball_crossing"
    side = "attack"
    exclusive_group = "volleyball_carrier"

    def __init__(self,
                 orchestrator: 'ComputerPlayerOrchestrator',
                 team: int,
                 participant_ids: List[str],
                 start_time: float,
                 max_duration: float = 15,
                 teammate_max_distance: float = 20,
                 teammate_min_lateral: float = 2,
                 opponent_max_distance: float = 10,
                 crossing_distance: float = 1.0,
                 min_approach_distance: float = 1.5,
                 hoop_clearance: float = 2.0,
                 receiver_behind_distance: float = 1.0,
                 receiver_time_gap: float = 0.5,
                 min_stick_input: float = 0.2,
                 loaded_beater_path_distance: float = 4,
                 blocking_path_distance: float = 1.5,
                 exit_angle: float = 45,
                 opponent_prediction_time: float = 1.0,
                 pass_interception_threshold: float = 0.95,
                 max_pass_distance: float = 4,
                 exit_duration: float = 2.0,
                 tackle_window: float = 1.0,
                 logger=None):
        """Store the crossing geometry and the pass criteria; carrier, receiver and defender are set by `try_start`."""
        super().__init__(orchestrator, team, participant_ids, start_time, max_duration, logger)
        self.teammate_max_distance = teammate_max_distance
        self.teammate_min_lateral = teammate_min_lateral
        self.opponent_max_distance = opponent_max_distance
        self.crossing_distance = crossing_distance
        self.min_approach_distance = min_approach_distance
        self.hoop_clearance = hoop_clearance
        self.receiver_behind_distance = receiver_behind_distance
        self.receiver_time_gap = receiver_time_gap
        self.min_stick_input = min_stick_input
        self.squared_loaded_beater_path_distance = loaded_beater_path_distance**2
        self.squared_blocking_path_distance = blocking_path_distance**2
        self.exit_angle = math.radians(exit_angle)
        self.opponent_prediction_time = opponent_prediction_time
        self.pass_interception_threshold = pass_interception_threshold
        self.max_pass_distance = max_pass_distance
        self.exit_duration = exit_duration
        self.tackle_window = tackle_window
        self.attack_sign = 1 - 2 * team # +x for team 0, -x for team 1
        self.carrier_id = participant_ids[0]
        self.receiver_id: Optional[str] = None
        self.defender_id: Optional[str] = None
        self.lateral_sign = 1 # y direction from the carrier to the receiver at the start
        self.crossing: Optional[Vector2] = None
        self.phase = "approach" # 'approach', then 'exit'
        self.decision: Optional[str] = None # 'pass' or 'dummy'
        self.decision_reason: Optional[str] = None
        self.exit_start_time: Optional[float] = None # set when the holder starts its exit run with the volleyball
        self.released_by_pass = False
        self.shot_taken = False

    @classmethod
    def try_start(cls,
                  orchestrator: 'ComputerPlayerOrchestrator',
                  ctx: StepContext,
                  team: int,
                  available_cpu_ids: Set[str],
                  **params) -> Optional['VolleyballCrossing']:
        """Start if a free CPU carrier, a CPU teammate and a defender in front of them allow a crossing with free paths."""
        state = orchestrator.logic.state
        volleyball = state.volleyball
        if ctx.attack_team != team or volleyball is None:
            return None
        if volleyball.holder_id is None or volleyball.is_dead or volleyball.inbounder is not None or volleyball.turnover_to_player is not None:
            return None
        roster = ctx.rosters[team]
        carrier = state.players[volleyball.holder_id]
        if carrier.id not in roster.chaser_keeper_ids or carrier.id not in available_cpu_ids or carrier.is_knocked_out:
            return None
        move = cls(orchestrator, team, [carrier.id], ctx.game_time, **params)
        if volleyball.time_since_carrier_tackled <= move.tackle_window:
            return None
        squared_teammate_max_distance = move.teammate_max_distance**2
        squared_opponent_max_distance = move.opponent_max_distance**2
        best: Optional[Tuple[float, str, str]] = None
        for receiver_id in roster.chaser_keeper_ids:
            if receiver_id == carrier.id or receiver_id not in available_cpu_ids:
                continue
            receiver = state.players[receiver_id]
            if receiver.is_knocked_out:
                continue
            if UtilityLogic._squared_distance(carrier.position, receiver.position) > squared_teammate_max_distance:
                continue
            lateral = receiver.position.y - carrier.position.y
            if abs(lateral) < move.teammate_min_lateral:
                continue
            middle = Vector2((carrier.position.x + receiver.position.x) / 2, (carrier.position.y + receiver.position.y) / 2)
            for defender_id in roster.opponent_chaser_keeper_ids:
                defender = state.players[defender_id]
                if defender.is_knocked_out:
                    continue
                if UtilityLogic._squared_distance(middle, defender.position) > squared_opponent_max_distance:
                    continue
                if abs(defender.position.y - middle.y) > abs(lateral) / 2 + 1:
                    continue # not between the runners
                crossing = move.crossing_position(defender, roster)
                receiver_crossing = move.receiver_crossing_position(crossing)
                if (move._ahead(crossing, carrier.position) < move.min_approach_distance
                        or move._ahead(receiver_crossing, receiver.position) < move.min_approach_distance):
                    continue
                if move.path_problem(roster, carrier, receiver, defender, crossing) is not None:
                    continue
                cost = (UtilityLogic._distance(carrier.position, crossing)
                        + UtilityLogic._distance(receiver.position, receiver_crossing))
                if best is None or cost < best[0]:
                    best = (cost, receiver_id, defender_id)
        if best is None:
            return None
        _, move.receiver_id, move.defender_id = best
        move.participant_ids = [carrier.id, move.receiver_id]
        move.lateral_sign = 1 if state.players[move.receiver_id].position.y > carrier.position.y else -1
        move.crossing = move.crossing_position(state.players[move.defender_id], roster)
        return move

    def _ahead(self, position: Vector2, other_position: Vector2) -> float:
        """How far `position` is ahead of `other_position` in the attack direction."""
        return (position.x - other_position.x) * self.attack_sign

    def crossing_position(self, defender: Player, roster: TeamRoster) -> Vector2:
        """
        `crossing_distance` in front of the defender, at least `hoop_clearance` before the opponent hoop line
        and 1 m inside the side lines. Once set, it never moves further ahead, so a retreating defender
        cannot drag it away from the runners.
        """
        state = self.logic.state
        hoop_x = roster.opponent_hoops[0].position.x
        x = defender.position.x - self.attack_sign * self.crossing_distance
        if (hoop_x - x) * self.attack_sign < self.hoop_clearance:
            x = hoop_x - self.attack_sign * self.hoop_clearance
        if self.crossing is not None and (x - self.crossing.x) * self.attack_sign > 0:
            x = self.crossing.x
        y_min, y_max = state.boundaries_y
        y = min(max(defender.position.y, y_min + 1), y_max - 1)
        return Vector2(x, y)

    def receiver_crossing_position(self, crossing: Vector2) -> Vector2:
        """Where the receiver crosses: `receiver_behind_distance` behind the carrier's crossing point."""
        return Vector2(crossing.x - self.attack_sign * self.receiver_behind_distance, crossing.y)

    @staticmethod
    def _point_segment_squared_distance(point: Vector2, start: Vector2, end: Vector2) -> float:
        """Squared distance of `point` to the segment from `start` to `end`."""
        dx = end.x - start.x
        dy = end.y - start.y
        squared_length = dx * dx + dy * dy
        fraction = 0.0
        if squared_length > 0:
            fraction = min(1.0, max(0.0, ((point.x - start.x) * dx + (point.y - start.y) * dy) / squared_length))
        ex = start.x + fraction * dx - point.x
        ey = start.y + fraction * dy - point.y
        return ex * ex + ey * ey

    def path_problem(self, roster: TeamRoster, carrier: Player, receiver: Player, defender: Player, crossing: Vector2) -> Optional[str]:
        """Why the paths of carrier and receiver to the crossing point are not free ('loaded_beater', 'path_blocked'), or None."""
        players = self.logic.state.players
        segments = ((carrier.position, crossing), (receiver.position, self.receiver_crossing_position(crossing)))
        for beater_id in roster.opponent_beater_ids:
            beater = players[beater_id]
            if beater.is_knocked_out or not beater.has_ball:
                continue
            for start, end in segments:
                if self._point_segment_squared_distance(beater.position, start, end) < self.squared_loaded_beater_path_distance:
                    return "loaded_beater"
        for opponent_id in roster.opponent_chaser_keeper_ids:
            if opponent_id == defender.id:
                continue
            opponent = players[opponent_id]
            if opponent.is_knocked_out:
                continue
            for start, end in segments:
                if self._point_segment_squared_distance(opponent.position, start, end) < self.squared_blocking_path_distance:
                    return "path_blocked"
        return None

    def exit_direction(self, lateral_sign: int) -> Vector2:
        """Unit exit line, `exit_angle` from the attack direction towards `lateral_sign` (y)."""
        return Vector2(self.attack_sign * math.cos(self.exit_angle), lateral_sign * math.sin(self.exit_angle))

    def _min_stick(self, player: Player) -> float:
        """Smallest stick input used to slow down, still counted as input."""
        return max(self.min_stick_input, player.min_dir + 0.05)

    def _steer(self, player: Player, target: Vector2, stick: float) -> None:
        """Steer `player` at `target` with stick input `stick`."""
        dx = target.x - player.position.x
        dy = target.y - player.position.y
        mag = UtilityLogic._magnitude_without_vector(dx, dy)
        player.direction = Vector2(dx / mag * stick, dy / mag * stick) if mag > 0 else Vector2(0, 0)

    def _run_exit(self, player: Player, exit_direction: Vector2) -> None:
        """Full stick input along the exit line, kept off the side lines like the diamond attack."""
        state = self.logic.state
        player.direction = MoveUtility.adjust_move_vector_to_avoid_boundary(
            player.position,
            Vector2(exit_direction.x, exit_direction.y),
            boundary_x_min=state.boundaries_x[0],
            boundary_x_max=state.boundaries_x[1],
            boundary_y_min=state.boundaries_y[0],
            boundary_y_max=state.boundaries_y[1],
            buffer=self.orchestrator.diamond_attack_chaser_keeper.positioning_boundary_buffer_distance,
        )

    def _exit_holder_id(self) -> str:
        """The player running the exit line: the receiver after a pass, otherwise the carrier."""
        return self.receiver_id if self.released_by_pass else self.carrier_id

    def _update_status(self, ctx: StepContext) -> None:
        """Check the success and failure criteria of the crossing."""
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
        steered_ids = [self.carrier_id, self.receiver_id] if self.phase == "approach" else [self._exit_holder_id()]
        for player_id in steered_ids:
            if player_id not in ctx.cpu_player_id_set:
                self.end(MoveStatus.ABORTED, "human_takeover")
                return
            if state.players[player_id].is_knocked_out:
                self.end(MoveStatus.FAILURE, "knocked_out")
                return
        holder_id = volleyball.holder_id
        if holder_id is None:
            # volleyball in flight or loose
            if not self.shot_taken and not self.released_by_pass:
                self.end(MoveStatus.FAILURE, "carrier_lost_ball") # e.g. beaten
            return # otherwise wait for the goal or the catch (or the turnover/timeout)
        holder = state.players[holder_id]
        if holder.team != self.team:
            self.end(MoveStatus.FAILURE, "turnover")
            return
        if self.logic.process_action_logic.is_charging_throw(holder_id):
            return # the carrier is winding up a throw (charging), wait for the release
        if self.shot_taken:
            self.end(MoveStatus.FAILURE, "shot_missed")
            return
        if holder_id != self._exit_holder_id():
            if self.released_by_pass:
                self.end(MoveStatus.FAILURE, "pass_back" if holder_id == self.carrier_id else "non_participant_holder")
            else:
                self.end(MoveStatus.FAILURE, "carrier_lost_ball")
            return
        if self.phase == "approach":
            defender = state.players[self.defender_id]
            if defender.is_knocked_out:
                self.end(MoveStatus.FAILURE, "opponent_gone")
                return
            roster = ctx.rosters[self.team]
            self.crossing = self.crossing_position(defender, roster)
            problem = self.path_problem(roster, state.players[self.carrier_id], state.players[self.receiver_id], defender, self.crossing)
            if problem is not None:
                self.end(MoveStatus.FAILURE, problem)
            return
        if self.exit_start_time is None:
            self.exit_start_time = ctx.game_time # the receiver caught the pass
        if (ctx.game_time - self.exit_start_time >= self.exit_duration
                or volleyball.time_since_carrier_tackled <= self.tackle_window):
            self.end(MoveStatus.SUCCESS, f"{self.decision}_exit_done")

    def controlled_player_ids(self, ctx: StepContext) -> Set[str]:
        """Carrier and receiver during the approach, then only the exit runner."""
        if self.status != MoveStatus.RUNNING:
            return set()
        if self.phase == "approach":
            return {player_id for player_id in (self.carrier_id, self.receiver_id) if player_id in ctx.cpu_player_id_set}
        holder_id = self._exit_holder_id()
        return {holder_id} if holder_id in ctx.cpu_player_id_set else set()

    def step(self, ctx: StepContext) -> None:
        """Approach the crossing point in sync, decide at the crossing, then run the exit line."""
        if not self.controlled_player_ids(ctx):
            return
        state = self.logic.state
        volleyball = state.volleyball
        roster = ctx.rosters[self.team]
        if volleyball.holder_id is not None and self.logic.process_action_logic.is_charging_throw(volleyball.holder_id):
            return # winding up the shot or pass, keep the input it was aimed with
        if self.phase == "exit":
            holder = state.players[self._exit_holder_id()]
            exit_direction = self.exit_direction(-self.lateral_sign if self.released_by_pass else self.lateral_sign)
            if volleyball.holder_id == holder.id and self.orchestrator.score_attempter.attempt(
                    volleyball, holder, roster.opponent_hoops, roster.opponent_chaser_keeper_ids):
                self.shot_taken = True
                return
            # while the pass is in flight the receiver keeps the input the throw was aimed with
            self._run_exit(holder, exit_direction)
            return
        carrier = state.players[self.carrier_id]
        receiver = state.players[self.receiver_id]
        if self.orchestrator.score_attempter.attempt(volleyball, carrier, roster.opponent_hoops, roster.opponent_chaser_keeper_ids):
            self.shot_taken = True
            return
        crossing = self.crossing
        carrier_speed = terminal_speed(carrier)
        carrier_distance = UtilityLogic._distance(carrier.position, crossing)
        # decide within half a computer player step of the crossing point, or when level with it or tackled
        if (carrier_distance <= 0.5 * carrier_speed * ctx.dt
                or self._ahead(crossing, carrier.position) <= 0
                or volleyball.time_since_carrier_tackled <= self.tackle_window):
            self._cross(ctx, carrier, receiver, roster)
            return
        receiver_crossing = self.receiver_crossing_position(crossing)
        carrier_time = carrier_distance / carrier_speed
        receiver_time = UtilityLogic._distance(receiver.position, receiver_crossing) / terminal_speed(receiver)
        carrier_stick = receiver_stick = 1.0
        if receiver_time < carrier_time + self.receiver_time_gap:
            receiver_stick = receiver_time / (carrier_time + self.receiver_time_gap)
        elif receiver_time - self.receiver_time_gap > carrier_time:
            carrier_stick = carrier_time / (receiver_time - self.receiver_time_gap)
        if UtilityLogic._distance(carrier.position, receiver.position) < carrier.radius + receiver.radius + 0.3:
            receiver_stick = 0.0 # yield
        self._steer(carrier, crossing, max(carrier_stick, self._min_stick(carrier)))
        self._steer(receiver, receiver_crossing, max(receiver_stick, self._min_stick(receiver)))

    def _cross(self, ctx: StepContext, carrier: Player, receiver: Player, roster: TeamRoster) -> None:
        """Turn both runners to their exit lines and pass or keep the volleyball depending on the defender."""
        state = self.logic.state
        volleyball = state.volleyball
        defender = state.players[self.defender_id]
        self.phase = "exit"
        carrier_exit = self.exit_direction(self.lateral_sign)
        receiver_exit = self.exit_direction(-self.lateral_sign)
        # the receiver's input has to be set before the throw is aimed
        self._run_exit(carrier, carrier_exit)
        self._run_exit(receiver, receiver_exit)
        time = self.opponent_prediction_time
        defender_x = defender.position.x + defender.velocity.x * time
        defender_y = defender.position.y + defender.velocity.y * time
        carrier_step = terminal_speed(carrier) * time
        receiver_step = terminal_speed(receiver) * time
        defender_carrier = UtilityLogic._magnitude_without_vector(
            carrier.position.x + carrier_exit.x * carrier_step - defender_x, carrier.position.y + carrier_exit.y * carrier_step - defender_y)
        defender_receiver = UtilityLogic._magnitude_without_vector(
            receiver.position.x + receiver_exit.x * receiver_step - defender_x, receiver.position.y + receiver_exit.y * receiver_step - defender_y)
        if defender_carrier <= defender_receiver:
            pass_distance = UtilityLogic._distance(carrier.position, receiver.position)
            if pass_distance > self.max_pass_distance:
                self.end(MoveStatus.FAILURE, "out_of_sync")
                return
            pass_evaluator = self.orchestrator.pass_evaluator
            pass_option = pass_evaluator.evaluate(volleyball, carrier, receiver, roster.own_hoops, roster.opponent_chaser_keeper_ids)
            if pass_option is not None and pass_evaluator.is_safe(pass_option, self.pass_interception_threshold):
                if pass_evaluator.throw(self.logic.process_action_logic, carrier, pass_option):
                    self.decision = "pass"
                    self.released_by_pass = True
                    self.logger.info(
                        "VolleyballCrossing pass from player %s to player %s, defender %s to carrier %.1f m / receiver %.1f m, pass %.1f m, interception score %.2f",
                        carrier.id, receiver.id, defender.id, defender_carrier, defender_receiver, pass_distance, pass_option.interception_score,
                    )
                    return
                self.decision_reason = "pass_refused"
            else:
                self.decision_reason = "pass_unsafe"
        self.decision = "dummy"
        self.exit_start_time = ctx.game_time
        self.logger.info(
            "VolleyballCrossing dummy by player %s (%s), defender %s to carrier %.1f m / receiver %.1f m",
            carrier.id, self.decision_reason or "defender_on_receiver", defender.id, defender_carrier, defender_receiver,
        )

    def describe(self) -> str:
        """Participants, defender and decision."""
        return (f"carrier={self.carrier_id[-4:]} receiver={(self.receiver_id or '')[-4:]} "
                f"defender={(self.defender_id or '')[-4:]} decision={self.decision} {self.decision_reason or ''}").rstrip()
