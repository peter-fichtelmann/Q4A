import logging
import math
from typing import Dict, List, Optional, Tuple
from core.entities import Hoop, Player, VolleyBall, Vector2, PlayerRole
from core.game_logic.game_logic import GameLogic
from computer_player.base_strategy import StepContext
from computer_player.hoop_defence import HoopDefenceChaserKeeper
from computer_player.computer_player_utility.move_around_hoop_blockage import MoveAroundHoopBlockage


class BoxDefenceChaserKeeper(HoopDefenceChaserKeeper):
    """
    Chaser/keeper part of the box defence.

    Volleyball in front of the own hoops:
        The keeper and one chaser (the box chaser) move up to the keeper zone line. Of these two,
        the one closer to the volleyball presses it (moves towards it and tackles), the other marks
        the opponent chaser/keeper closest to the volleyball by standing in its passing lane.
        Both stay between the hoops and the keeper zone line.
        Pressers and markers stay within `max_y_offset` of the centre hoop; opponents further out to the
        sides are less dangerous and not marked.
        The marker keeps at least `min_defender_distance` from the presser.
        The two other chasers defend the hoops like in the hoop defence.

    Knocked out box players:
        If the box chaser or the keeper is knocked out, the hoop chaser closest to them at that moment takes
        their box role. The keeper gets it back once they are no longer knocked out; a replaced box chaser
        becomes a hoop chaser.

    Volleyball behind the own hoops:
        The two hoop chasers move around the hoops towards the volleyball; the closer one presses it,
        the other marks. The keeper and the box chaser take over defending the hoops.

    With `assign_by_total_distance`, presser and marker are not chosen by the distance to the volleyball
    alone: of the two ways to assign them, the one with the smaller sum of the presser's distance to the
    volleyball and the marker's distance to its marking position is taken.
    With `anticipate_volleyball`, the defence positions against where a pass in flight will be caught,
    and the expected receiver is pressed instead of marked.
    """
    def __init__(self,
                 logic: GameLogic,
                 move_around_hoop_blockages: Dict[int, MoveAroundHoopBlockage], # per team, around the team's own hoops
                 marking_distance: float = 1.5, # m from the marked opponent towards the volleyball
                 marking_max_distance: float = 10, # m, only opponents this close to the volleyball are marked
                 hoop_clearance_x: float = 1.0, # m, minimum x distance in front of the hoops for the box players
                 max_y_offset: float = 7.0, # m, pressers and markers stay within this y distance of the centre hoop
                 min_defender_distance: float = 3.0, # m, the marker keeps at least this distance from the presser
                 assign_by_total_distance: bool = False,
                 anticipate_volleyball: bool = False,
                 orient_to_volleyball: bool = False,
                 between_hoops_fraction: Optional[float] = None,
                 logger: Optional[logging.Logger] = None
                 ):
        """Store the hoop blockage helpers and marking parameters."""
        super().__init__(logic, move_around_hoop_blockages, anticipate_volleyball=anticipate_volleyball,
                         orient_to_volleyball=orient_to_volleyball, between_hoops_fraction=between_hoops_fraction, logger=logger)
        self.assign_by_total_distance = assign_by_total_distance
        self.marking_distance = marking_distance
        self.marking_max_distance = marking_max_distance
        self.hoop_clearance_x = hoop_clearance_x
        self.max_y_offset = max_y_offset
        self.min_defender_distance = min_defender_distance
        self._box_chaser_ids: Dict[int, Optional[str]] = {}
        self._keeper_substitute_ids: Dict[int, Optional[str]] = {} # chaser taking the knocked out keeper's box role

    def reset(self, team: int):
        """Forget the box chaser and keeper substitute so new ones are chosen when this team starts box defending."""
        self._box_chaser_ids.pop(team, None)
        self._keeper_substitute_ids.pop(team, None)

    def __call__(self,
                 ctx: StepContext,
                 team: int,
                 controlled_ids: List[str],
                 assigned_beater_ids: List[str]):
        """Run one box defence update tick for the keeper and chasers in `controlled_ids`."""
        state = self.logic.state
        volleyball = state.volleyball
        defence_hoops = ctx.rosters[team].own_hoops
        controlled_id_set = set(controlled_ids)

        keeper = None
        chasers = []
        for player in state.players.values():
            if player.team != team:
                continue
            if player.role == PlayerRole.KEEPER:
                keeper = player
            elif player.role == PlayerRole.CHASER:
                chasers.append(player)
        box_chaser = self._box_chaser(team, chasers, volleyball)
        keeper_substitute = self._keeper_substitute(team, keeper, chasers, box_chaser)
        box_players = [
            player for player in (keeper, keeper_substitute, box_chaser)
            if player is not None and not player.is_knocked_out
        ]
        hoop_chasers = [chaser for chaser in chasers if not chaser.is_knocked_out and chaser not in box_players]

        reference_position = self.reference_position(ctx)
        sorted_hoop_distances = sorted(
            ((hoop.id, (reference_position.x - hoop.position.x) ** 2 + (reference_position.y - hoop.position.y) ** 2) for hoop in defence_hoops),
            key=lambda item: item[1]
        )
        closest_hoop = state.hoops[sorted_hoop_distances[0][0]]
        forward = 1 if team == state.team_0 else -1 # x direction from the own hoops towards the midline
        volleyball_in_front = (reference_position.x - closest_hoop.position.x) * forward > 0

        if volleyball_in_front:
            hoop_defenders, pressing_players = hoop_chasers, box_players
            keeper_zone_x = state.keeper_zone_x_0 if team == state.team_0 else state.keeper_zone_x_1
            # stay out of the hoop blockage band in front of the hoops
            x_limits = tuple(sorted((closest_hoop.position.x + forward * self.hoop_clearance_x, keeper_zone_x)))
        else:
            hoop_defenders, pressing_players = box_players, hoop_chasers
            x_limits = None

        hoop_defender_squared_distances = {hoop.id: {} for hoop in defence_hoops}
        for player in hoop_defenders:
            for hoop in defence_hoops:
                hoop_defender_squared_distances[hoop.id][player.id] = (player.position.x - hoop.position.x) ** 2 + (player.position.y - hoop.position.y) ** 2
        self.chasers_action(sorted_hoop_distances, hoop_defender_squared_distances, volleyball, ctx.dt, team, controlled_id_set,
                            reference_position if self.anticipate_volleyball else None)
        center_hoop = defence_hoops[1] if len(defence_hoops) == 3 else defence_hoops[0]
        y_limits = (center_hoop.position.y - self.max_y_offset, center_hoop.position.y + self.max_y_offset)
        carrier_id = ctx.anticipated_carrier_id if self.anticipate_volleyball else volleyball.holder_id
        self.press_and_mark_action(pressing_players, reference_position, carrier_id, closest_hoop, team, ctx, controlled_id_set, x_limits, y_limits)

        # the keeper always tries to tackle, like in the hoop defence
        if keeper is not None and keeper.id in controlled_id_set:
            keeper.is_holding_tackle = True

    def _box_chaser(self, team: int, chasers: List[Player], volleyball: VolleyBall) -> Optional[Player]:
        """
        Keep the box chaser of the team. If it is knocked out, the chaser closest to it takes over;
        if there is none yet, the chaser closest to the volleyball.
        """
        box_chaser = next((chaser for chaser in chasers if chaser.id == self._box_chaser_ids.get(team)), None)
        if box_chaser is not None and not box_chaser.is_knocked_out:
            return box_chaser
        reference_position = box_chaser.position if box_chaser is not None else volleyball.position
        available = [
            chaser for chaser in chasers
            if not chaser.is_knocked_out and chaser.id != self._keeper_substitute_ids.get(team)
        ]
        if not available:
            return None
        box_chaser = min(available, key=lambda chaser: self._squared_distance(chaser.position, reference_position))
        self._box_chaser_ids[team] = box_chaser.id
        return box_chaser

    def _keeper_substitute(self, team: int, keeper: Optional[Player], chasers: List[Player], box_chaser: Optional[Player]) -> Optional[Player]:
        """While the keeper is knocked out, the chaser closest to the keeper at the knockout takes the keeper's box role."""
        if keeper is None or not keeper.is_knocked_out:
            self._keeper_substitute_ids.pop(team, None)
            return None
        available = [chaser for chaser in chasers if not chaser.is_knocked_out and chaser is not box_chaser]
        substitute = next((chaser for chaser in available if chaser.id == self._keeper_substitute_ids.get(team)), None)
        if substitute is None and available:
            substitute = min(available, key=lambda chaser: self._squared_distance(chaser.position, keeper.position))
        self._keeper_substitute_ids[team] = substitute.id if substitute is not None else None
        return substitute

    def press_and_mark_action(self,
                              players: List[Player],
                              volleyball_position: Vector2,
                              carrier_id: Optional[str],
                              closest_hoop: Hoop,
                              team: int,
                              ctx: StepContext,
                              controlled_id_set: set,
                              x_limits: Optional[Tuple[float, float]],
                              y_limits: Tuple[float, float]):
        """The player closest to the volleyball presses it, the other marks the opponent closest to the volleyball."""
        if not players:
            return
        move_around_hoop_blockage = self.move_around_hoop_blockages[team]
        opponents = [
            self.logic.state.players[player_id] for player_id in ctx.rosters[team].opponent_chaser_keeper_ids
            if player_id != carrier_id
            and not self.logic.state.players[player_id].is_knocked_out
            and y_limits[0] <= self.logic.state.players[player_id].position.y <= y_limits[1]
            and self._squared_distance(self.logic.state.players[player_id].position, volleyball_position) <= self.marking_max_distance ** 2
        ]
        opponents.sort(key=lambda opponent: self._squared_distance(opponent.position, volleyball_position))
        press_position = self._clamp(Vector2(volleyball_position.x, volleyball_position.y), x_limits, y_limits)
        players = sorted(players, key=lambda player: self._squared_distance(player.position, volleyball_position))
        if self.assign_by_total_distance and len(players) == 2 and opponents:
            mark_position = self._clamp(self._marking_position(opponents[0], volleyball_position), x_limits, y_limits)
            def cost(presser: Player, marker: Player) -> float:
                return (math.dist((presser.position.x, presser.position.y), (press_position.x, press_position.y))
                        + math.dist((marker.position.x, marker.position.y), (mark_position.x, mark_position.y)))
            if cost(players[1], players[0]) < cost(players[0], players[1]):
                players = [players[1], players[0]]
        presser, markers = players[0], players[1:]

        if presser.id in controlled_id_set:
            presser.direction = move_around_hoop_blockage(presser, press_position, target_hoop=closest_hoop)
            presser.is_holding_tackle = True

        for i, marker in enumerate(markers):
            if marker.id not in controlled_id_set:
                continue
            if i < len(opponents):
                target_position = self._marking_position(opponents[i], volleyball_position)
            else:
                # nobody to mark: cover the volleyball's way to the closest hoop
                target_position = Vector2(
                    (volleyball_position.x + closest_hoop.position.x) / 2,
                    (volleyball_position.y + closest_hoop.position.y) / 2
                )
            target_position = self._keep_away_from(target_position, presser.position, x_limits, y_limits)
            marker.direction = move_around_hoop_blockage(marker, target_position, target_hoop=closest_hoop)

    def _marking_position(self, opponent: Player, volleyball_position: Vector2) -> Vector2:
        """Point in the passing lane, `marking_distance` from the opponent towards the volleyball."""
        dx = volleyball_position.x - opponent.position.x
        dy = volleyball_position.y - opponent.position.y
        distance = (dx ** 2 + dy ** 2) ** 0.5
        if distance == 0:
            return Vector2(opponent.position.x, opponent.position.y)
        fraction = min(1.0, self.marking_distance / distance)
        return Vector2(opponent.position.x + fraction * dx, opponent.position.y + fraction * dy)

    def _keep_away_from(self,
                        target_position: Vector2,
                        other_position: Vector2,
                        x_limits: Optional[Tuple[float, float]],
                        y_limits: Tuple[float, float]) -> Vector2:
        """
        Clamp `target_position` into the limits and keep it at least `min_defender_distance` from `other_position`:
        first pushed radially away, and if the limits pull it back too close (e.g. both at the keeper zone line),
        moved sideways in y next to `other_position`.
        """
        target_position = self._clamp(target_position, x_limits, y_limits)
        if self._squared_distance(target_position, other_position) >= self.min_defender_distance ** 2:
            return target_position
        dx = target_position.x - other_position.x
        dy = target_position.y - other_position.y
        distance = (dx ** 2 + dy ** 2) ** 0.5
        if distance == 0:
            dx, dy, distance = 0.0, 1.0, 1.0
        factor = self.min_defender_distance / distance
        pushed = self._clamp(Vector2(other_position.x + dx * factor, other_position.y + dy * factor), x_limits, y_limits)
        if self._squared_distance(pushed, other_position) >= self.min_defender_distance ** 2:
            return pushed
        # sidestep in y, on the side of the original target if it fits within the y limits
        x_offset = pushed.x - other_position.x
        y_offset = max(0.0, self.min_defender_distance ** 2 - x_offset ** 2) ** 0.5
        side = 1 if dy >= 0 else -1
        for sign in (side, -side):
            y = other_position.y + sign * y_offset
            if y_limits[0] <= y <= y_limits[1]:
                return Vector2(pushed.x, y)
        return pushed

    @staticmethod
    def _clamp(position: Vector2, x_limits: Optional[Tuple[float, float]], y_limits: Tuple[float, float]) -> Vector2:
        """Clamp x into `x_limits` (between the hoops and the keeper zone line) and y into `y_limits` (around the centre hoop)."""
        if x_limits is not None:
            position.x = min(max(position.x, x_limits[0]), x_limits[1])
        position.y = min(max(position.y, y_limits[0]), y_limits[1])
        return position

    @staticmethod
    def _squared_distance(a: Vector2, b: Vector2) -> float:
        """Squared euclidean distance."""
        return (a.x - b.x) ** 2 + (a.y - b.y) ** 2
