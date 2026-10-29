import math
from typing import TYPE_CHECKING, List, Optional, Set, Tuple

from core.entities import Hoop, Player, Vector2
from core.game_logic.utility_logic import UtilityLogic
from computer_player.base_strategy import StepContext, TeamRoster
from computer_player.computer_player_utility.computer_player_utility import MoveUtility
from computer_player.computer_player_utility.kinematics import terminal_speed
from computer_player.moves.move import Move, MoveStatus
from computer_player.moves.volleyball_crossing import VolleyballCrossing
from computer_player.moves.volleyball_drive import VolleyballDrive

if TYPE_CHECKING:
    from computer_player.computer_player_orchestrator import ComputerPlayerOrchestrator


class VolleyballBlock(Move):
    """
    Attack move: a teammate screens the defender who could intercept the carrier's drive (pick).

    Start: the attacking team holds a live volleyball with a free (not tackled) CPU carrier in the
    opponent's half, no hoop is free of interceptors, and for an opponent hoop
        - the first on-stick opponent chaser/keeper (the defender) that can intercept the carrier running
          straight at the hoop does so at least `second_interceptor_margin` before any other one (0: any),
        - the defender is at least `min_defender_hoop_distance` from the hoop (no hoop guard), at least
          `min_defender_distance` from the carrier, and not running at the carrier faster than
          `max_defender_closing_speed` (a pressing defender cannot be caught by a screen),
        - a CPU teammate chaser/keeper (the blocker) within `blocker_max_distance` reaches the screen spot
          within `max_setup_time`,
        - no loaded opponent beater is within `loaded_beater_path_distance` of the carrier's run to the lane.
    Of several hoop/blocker pairs the one with the fastest screen is taken.

    The screen side is the side of the carrier-defender line the blocker comes from. The screen spot is
    `block_offset` beside the defender on that side (perpendicular to the carrier-defender line), and the
    lane `screen_clearance` beyond it. The blocker runs to the screen spot, leading it by the defender's
    velocity over its arrival time (at most `max_lead_time`); the block is set once it is within
    `block_set_width` of the spot. The carrier runs through the lane, then at the hoop. Until the block is
    set it slows down (at most to `unset_stick_input`) so that it reaches the lane when the screen stands.
    The carrier shoots like the base strategy.

    Success: the defender is behind the carrier or can no longer intercept its run to the hoop
    (`defender_passed`), the defender is knocked out (`defender_gone`), or the team scores.
    Failure: turnover, timeout, the carrier reaching the defender before the block is set
    (`block_too_late`), the defender back at the target hoop (`defender_at_hoop`), the carrier tackled,
    losing the ball, or missing a shot, a participant knocked out.
    Aborted: human takeover of the carrier/blocker, or a restart (inbounding, turnover ball).
    """
    name = "volleyball_block"
    side = "attack"
    exclusive_group = "volleyball_carrier"

    def __init__(self,
                 orchestrator: 'ComputerPlayerOrchestrator',
                 team: int,
                 participant_ids: List[str],
                 start_time: float,
                 max_duration: float = 10,
                 blocker_max_distance: float = 20,
                 block_offset: float = 0.9,
                 block_set_width: float = 0.8,
                 max_lead_time: float = 1.5,
                 max_setup_time: float = 4.0,
                 unset_stick_input: float = 0.2,
                 screen_clearance: float = 1.5,
                 loaded_beater_path_distance: float = 4,
                 second_interceptor_margin: float = 0.0,
                 min_defender_hoop_distance: float = 3.0,
                 min_defender_distance: float = 4.0,
                 max_defender_closing_speed: float = 0.5,
                 tackle_window: float = 1.0,
                 logger=None):
        """Store the screen geometry; carrier, blocker, defender, hoop and side are set by `try_start`."""
        super().__init__(orchestrator, team, participant_ids, start_time, max_duration, logger)
        self.blocker_max_distance = blocker_max_distance
        self.block_offset = block_offset
        self.block_set_width = block_set_width
        self.max_lead_time = max_lead_time
        self.max_setup_time = max_setup_time
        self.unset_stick_input = unset_stick_input
        self.screen_clearance = screen_clearance
        self.squared_loaded_beater_path_distance = loaded_beater_path_distance**2
        self.second_interceptor_margin = second_interceptor_margin
        self.min_defender_hoop_distance = min_defender_hoop_distance
        self.min_defender_distance = min_defender_distance
        self.max_defender_closing_speed = max_defender_closing_speed
        self.tackle_window = tackle_window
        self.carrier_id = participant_ids[0]
        self.blocker_id: Optional[str] = None
        self.defender_id: Optional[str] = None
        self.target_hoop_id: Optional[str] = None
        self.screen_side = 1 # +1 / -1: side of the carrier-defender line the screen is set on
        self.block_set_time: Optional[float] = None
        self.shot_taken = False

    @staticmethod
    def interception_time(carrier: Player, run_velocity: Vector2, defender: Player) -> float:
        """
        First time the defender, running at its terminal speed, can touch the carrier running with the
        constant `run_velocity`, or inf. Solves |d + v t| = w t + r for d = carrier - defender.
        """
        dx = carrier.position.x - defender.position.x
        dy = carrier.position.y - defender.position.y
        speed = terminal_speed(defender)
        reach = carrier.radius + defender.radius
        c = dx * dx + dy * dy - reach * reach
        if c <= 0:
            return 0.0
        a = run_velocity.x**2 + run_velocity.y**2 - speed**2
        b = 2 * (dx * run_velocity.x + dy * run_velocity.y - speed * reach)
        if abs(a) < 1e-9:
            return -c / b if b < 0 else float('inf')
        discriminant = b * b - 4 * a * c
        if discriminant < 0:
            return float('inf')
        root = math.sqrt(discriminant)
        for time in sorted(((-b - root) / (2 * a), (-b + root) / (2 * a))):
            if time >= 0:
                return time
        return float('inf')

    @staticmethod
    def run_velocity(carrier: Player, hoop: Hoop) -> Tuple[Vector2, float]:
        """Velocity of the carrier running straight at `hoop` at its terminal speed, and the time it needs."""
        dx = hoop.position.x - carrier.position.x
        dy = hoop.position.y - carrier.position.y
        distance = UtilityLogic._magnitude_without_vector(dx, dy)
        speed = terminal_speed(carrier)
        if distance == 0:
            return Vector2(0, 0), 0.0
        return Vector2(dx / distance * speed, dy / distance * speed), distance / speed

    def interceptors(self, carrier: Player, hoop: Hoop, roster: TeamRoster) -> List[Tuple[float, Player]]:
        """(interception time, player) of the on-stick opponent chasers/keepers that can intercept the carrier's straight run at `hoop` before it arrives, earliest first."""
        run_velocity, run_time = self.run_velocity(carrier, hoop)
        players = self.logic.state.players
        result = []
        for opponent_id in roster.opponent_chaser_keeper_ids:
            opponent = players[opponent_id]
            if opponent.is_knocked_out:
                continue
            time = self.interception_time(carrier, run_velocity, opponent)
            if time <= run_time:
                result.append((time, opponent))
        result.sort(key=lambda item: item[0])
        return result

    def loaded_beater_on_run(self, carrier: Player, end: Vector2, roster: TeamRoster) -> bool:
        """Whether a loaded, on-stick opponent beater is within `loaded_beater_path_distance` of the carrier's run to `end`."""
        for beater_id in roster.opponent_beater_ids:
            beater = self.logic.state.players[beater_id]
            if beater.is_knocked_out or not beater.has_ball:
                continue
            if VolleyballCrossing._point_segment_squared_distance(beater.position, carrier.position, end) < self.squared_loaded_beater_path_distance:
                return True
        return False

    @staticmethod
    def _side_normal(carrier: Player, defender: Player) -> Vector2:
        """Unit normal of the carrier-defender line (rotated +90 degrees)."""
        dx = defender.position.x - carrier.position.x
        dy = defender.position.y - carrier.position.y
        distance = UtilityLogic._magnitude_without_vector(dx, dy)
        if distance == 0:
            return Vector2(0, 1)
        return Vector2(-dy / distance, dx / distance)

    def screen_points(self, carrier: Player, defender: Player, side: int) -> Tuple[Vector2, Vector2]:
        """(screen spot beside the defender, lane beyond the screen) on `side`."""
        normal = self._side_normal(carrier, defender)
        spot = Vector2(defender.position.x + side * normal.x * self.block_offset,
                       defender.position.y + side * normal.y * self.block_offset)
        lane_offset = self.block_offset + self.screen_clearance
        lane = Vector2(defender.position.x + side * normal.x * lane_offset,
                       defender.position.y + side * normal.y * lane_offset)
        return spot, lane

    @staticmethod
    def _behind_carrier(carrier: Player, player: Player, hoop: Hoop) -> bool:
        """Whether `player` is not ahead of the carrier on its way to `hoop`."""
        return ((player.position.x - carrier.position.x) * (hoop.position.x - carrier.position.x)
                + (player.position.y - carrier.position.y) * (hoop.position.y - carrier.position.y)) <= 0

    @classmethod
    def try_start(cls,
                  orchestrator: 'ComputerPlayerOrchestrator',
                  ctx: StepContext,
                  team: int,
                  available_cpu_ids: Set[str],
                  **params) -> Optional['VolleyballBlock']:
        """Start if a defender threatens a drive at a hoop and a CPU teammate can screen it in time."""
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
        if not VolleyballDrive.in_opponent_half(state, team, carrier):
            return None
        move = cls(orchestrator, team, [carrier.id], ctx.game_time, **params)
        if volleyball.time_since_carrier_tackled <= move.tackle_window:
            return None
        threats = []
        for hoop in roster.opponent_hoops:
            interceptors = move.interceptors(carrier, hoop, roster)
            if not interceptors:
                return None # a free drive needs no block
            if len(interceptors) >= 2 and interceptors[1][0] - interceptors[0][0] < move.second_interceptor_margin:
                continue
            defender = interceptors[0][1]
            if UtilityLogic._distance(defender.position, hoop.position) < move.min_defender_hoop_distance:
                continue
            carrier_distance = UtilityLogic._distance(carrier.position, defender.position)
            if carrier_distance < move.min_defender_distance:
                continue
            closing_speed = ((carrier.position.x - defender.position.x) * defender.velocity.x
                             + (carrier.position.y - defender.position.y) * defender.velocity.y) / carrier_distance
            if closing_speed > move.max_defender_closing_speed:
                continue # already pressing the carrier, a screen cannot catch it
            threats.append((hoop, defender))
        squared_blocker_max_distance = move.blocker_max_distance**2
        best: Optional[Tuple[float, str, str, str, int]] = None
        for hoop, defender in threats:
            normal = cls._side_normal(carrier, defender)
            for blocker_id in roster.chaser_keeper_ids:
                if blocker_id == carrier.id or blocker_id not in available_cpu_ids:
                    continue
                blocker = state.players[blocker_id]
                if blocker.is_knocked_out:
                    continue
                if UtilityLogic._squared_distance(carrier.position, blocker.position) > squared_blocker_max_distance:
                    continue
                # screen on the side the blocker comes from
                side = 1 if ((blocker.position.x - defender.position.x) * normal.x
                             + (blocker.position.y - defender.position.y) * normal.y) >= 0 else -1
                spot, lane = move.screen_points(carrier, defender, side)
                setup_time = UtilityLogic._distance(blocker.position, spot) / terminal_speed(blocker)
                if setup_time > move.max_setup_time:
                    continue
                if move.loaded_beater_on_run(carrier, lane, roster):
                    continue
                if best is None or setup_time < best[0]:
                    best = (setup_time, hoop.id, blocker_id, defender.id, side)
        if best is None:
            return None
        _, move.target_hoop_id, move.blocker_id, move.defender_id, move.screen_side = best
        move.participant_ids = [carrier.id, move.blocker_id]
        return move

    def _update_status(self, ctx: StepContext) -> None:
        """Check the success and failure criteria of the block."""
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
        for player_id in (self.carrier_id, self.blocker_id):
            if player_id not in ctx.cpu_player_id_set:
                self.end(MoveStatus.ABORTED, "human_takeover")
                return
            if state.players[player_id].is_knocked_out:
                self.end(MoveStatus.FAILURE, "knocked_out")
                return
        holder_id = volleyball.holder_id
        if holder_id is None:
            # volleyball in flight or loose
            if not self.shot_taken:
                self.end(MoveStatus.FAILURE, "carrier_lost_ball") # e.g. beaten
            return # otherwise wait for the goal (or the turnover/timeout)
        if state.players[holder_id].team != self.team:
            self.end(MoveStatus.FAILURE, "turnover")
            return
        if self.logic.process_action_logic.is_charging_throw(holder_id):
            return # the carrier is winding up a throw (charging), wait for the release
        if self.shot_taken:
            self.end(MoveStatus.FAILURE, "shot_missed")
            return
        if holder_id != self.carrier_id:
            self.end(MoveStatus.FAILURE, "carrier_lost_ball")
            return
        if volleyball.time_since_carrier_tackled <= self.tackle_window:
            self.end(MoveStatus.FAILURE, "tackled")
            return
        defender = state.players[self.defender_id]
        if defender.is_knocked_out:
            self.end(MoveStatus.SUCCESS, "defender_gone")
            return
        carrier = state.players[self.carrier_id]
        hoop = state.hoops[self.target_hoop_id]
        run_velocity, run_time = self.run_velocity(carrier, hoop)
        if self._behind_carrier(carrier, defender, hoop) or self.interception_time(carrier, run_velocity, defender) > run_time:
            self.end(MoveStatus.SUCCESS, "defender_passed")
            return
        if UtilityLogic._distance(defender.position, hoop.position) < self.min_defender_hoop_distance:
            self.end(MoveStatus.FAILURE, "defender_at_hoop")
            return
        if (self.block_set_time is None
                and UtilityLogic._distance(carrier.position, defender.position) < self.block_offset + self.screen_clearance):
            self.end(MoveStatus.FAILURE, "block_too_late")

    def controlled_player_ids(self, ctx: StepContext) -> Set[str]:
        """Carrier (while holding the volleyball) and blocker, while CPU controlled."""
        if self.status != MoveStatus.RUNNING:
            return set()
        ids = {self.blocker_id} if self.blocker_id in ctx.cpu_player_id_set else set()
        if self.logic.state.volleyball.holder_id == self.carrier_id and self.carrier_id in ctx.cpu_player_id_set:
            ids.add(self.carrier_id)
        return ids

    def step(self, ctx: StepContext) -> None:
        """Move the blocker beside the defender, and the carrier through the lane beyond the screen to the hoop."""
        controlled_ids = self.controlled_player_ids(ctx)
        if self.carrier_id not in controlled_ids or self.blocker_id not in controlled_ids:
            return
        state = self.logic.state
        volleyball = state.volleyball
        roster = ctx.rosters[self.team]
        carrier = state.players[self.carrier_id]
        blocker = state.players[self.blocker_id]
        defender = state.players[self.defender_id]
        hoop = state.hoops[self.target_hoop_id]
        if self.logic.process_action_logic.is_charging_throw(carrier.id):
            return # winding up the shot, keep the input it was aimed with
        if self.orchestrator.score_attempter.attempt(volleyball, carrier, roster.opponent_hoops, roster.opponent_chaser_keeper_ids):
            self.shot_taken = True
            return
        spot, lane = self.screen_points(carrier, defender, self.screen_side)
        blocker_time = UtilityLogic._distance(blocker.position, spot) / terminal_speed(blocker)
        # lead the screen spot by the defender's motion until the blocker gets there
        lead = min(blocker_time, self.max_lead_time)
        self._steer(blocker, Vector2(spot.x + defender.velocity.x * lead, spot.y + defender.velocity.y * lead), 1.0)
        if self.block_set_time is None and UtilityLogic._distance(blocker.position, spot) <= self.block_set_width:
            self.block_set_time = ctx.game_time
            self.logger.info("VolleyballBlock set by player %s against player %s for carrier %s", blocker.id, defender.id, carrier.id)
        carrier_stick = 1.0
        if self.block_set_time is None and blocker_time > 0:
            # reach the lane when the screen stands
            carrier_time = UtilityLogic._distance(carrier.position, lane) / terminal_speed(carrier)
            carrier_stick = min(1.0, max(self.unset_stick_input, carrier_time / blocker_time))
        self._steer(carrier, lane, carrier_stick)
        carrier.direction = MoveUtility.adjust_move_vector_to_avoid_boundary(
            carrier.position,
            carrier.direction,
            boundary_x_min=state.boundaries_x[0],
            boundary_x_max=state.boundaries_x[1],
            boundary_y_min=state.boundaries_y[0],
            boundary_y_max=state.boundaries_y[1],
            buffer=self.orchestrator.diamond_attack_chaser_keeper.positioning_boundary_buffer_distance,
        )

    def _steer(self, player: Player, target: Vector2, stick: float) -> None:
        """Steer `player` at `target` with stick input `stick`."""
        dx = target.x - player.position.x
        dy = target.y - player.position.y
        mag = UtilityLogic._magnitude_without_vector(dx, dy)
        player.direction = Vector2(dx / mag * stick, dy / mag * stick) if mag > 0 else Vector2(0, 0)

    def describe(self) -> str:
        """Participants, defender, hoop and when the block was set."""
        block_set = f"{self.block_set_time - self.start_time:.1f}s" if self.block_set_time is not None else "never"
        return (f"carrier={self.carrier_id[-4:]} blocker={(self.blocker_id or '')[-4:]} "
                f"defender={(self.defender_id or '')[-4:]} hoop={self.target_hoop_id} set={block_set}")
