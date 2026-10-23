import logging
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
        The two other chasers defend the hoops like in the hoop defence.

    Volleyball behind the own hoops:
        The two hoop chasers move around the hoops towards the volleyball; the closer one presses it,
        the other marks. The keeper and the box chaser take over defending the hoops.
    """
    def __init__(self,
                 logic: GameLogic,
                 move_around_hoop_blockages: Dict[int, MoveAroundHoopBlockage], # per team, around the team's own hoops
                 marking_distance: float = 1.5, # m from the marked opponent towards the volleyball
                 marking_max_distance: float = 10, # m, only opponents this close to the volleyball are marked
                 hoop_clearance_x: float = 1.0, # m, minimum x distance in front of the hoops for the box players
                 max_y_offset: float = 7.0, # m, pressers and markers stay within this y distance of the centre hoop
                 logger: Optional[logging.Logger] = None
                 ):
        """Store the hoop blockage helpers and marking parameters."""
        super().__init__(logic, move_around_hoop_blockages, logger=logger)
        self.marking_distance = marking_distance
        self.marking_max_distance = marking_max_distance
        self.hoop_clearance_x = hoop_clearance_x
        self.max_y_offset = max_y_offset
        self._box_chaser_ids: Dict[int, Optional[str]] = {}

    def reset(self, team: int):
        """Forget the box chaser so a new one is chosen when this team starts box defending."""
        self._box_chaser_ids.pop(team, None)

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
            elif player.role == PlayerRole.CHASER and not player.is_knocked_out:
                chasers.append(player)
        box_chaser = self._box_chaser(team, chasers, volleyball)
        hoop_chasers = [chaser for chaser in chasers if chaser is not box_chaser]
        box_players = [player for player in (keeper, box_chaser) if player is not None and not player.is_knocked_out]

        sorted_hoop_distances = sorted(
            ((hoop.id, (volleyball.position.x - hoop.position.x) ** 2 + (volleyball.position.y - hoop.position.y) ** 2) for hoop in defence_hoops),
            key=lambda item: item[1]
        )
        closest_hoop = state.hoops[sorted_hoop_distances[0][0]]
        forward = 1 if team == state.team_0 else -1 # x direction from the own hoops towards the midline
        volleyball_in_front = (volleyball.position.x - closest_hoop.position.x) * forward > 0

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
        self.chasers_action(sorted_hoop_distances, hoop_defender_squared_distances, volleyball, ctx.dt, team, controlled_id_set)
        center_hoop = defence_hoops[1] if len(defence_hoops) == 3 else defence_hoops[0]
        y_limits = (center_hoop.position.y - self.max_y_offset, center_hoop.position.y + self.max_y_offset)
        self.press_and_mark_action(pressing_players, volleyball, closest_hoop, team, ctx, controlled_id_set, x_limits, y_limits)

        # the keeper always tries to tackle, like in the hoop defence
        if keeper is not None and keeper.id in controlled_id_set:
            self.logic.process_action_logic.process_tackle_action(keeper.id)

    def _box_chaser(self, team: int, chasers: List[Player], volleyball: VolleyBall) -> Optional[Player]:
        """Keep the box chaser of the team; choose the chaser closest to the volleyball if there is none (anymore)."""
        box_chaser_id = self._box_chaser_ids.get(team)
        for chaser in chasers:
            if chaser.id == box_chaser_id:
                return chaser
        if not chasers:
            return None
        box_chaser = min(chasers, key=lambda chaser: self._squared_distance(chaser.position, volleyball.position))
        self._box_chaser_ids[team] = box_chaser.id
        return box_chaser

    def press_and_mark_action(self,
                              players: List[Player],
                              volleyball: VolleyBall,
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
        players = sorted(players, key=lambda player: self._squared_distance(player.position, volleyball.position))
        presser, markers = players[0], players[1:]

        if presser.id in controlled_id_set:
            target_position = self._clamp(Vector2(volleyball.position.x, volleyball.position.y), x_limits, y_limits)
            presser.direction = move_around_hoop_blockage(presser, target_position, target_hoop=closest_hoop)
            self.logic.process_action_logic.process_tackle_action(presser.id)

        opponents = [
            self.logic.state.players[player_id] for player_id in ctx.rosters[team].opponent_chaser_keeper_ids
            if player_id != volleyball.holder_id
            and not self.logic.state.players[player_id].is_knocked_out
            and y_limits[0] <= self.logic.state.players[player_id].position.y <= y_limits[1]
            and self._squared_distance(self.logic.state.players[player_id].position, volleyball.position) <= self.marking_max_distance ** 2
        ]
        opponents.sort(key=lambda opponent: self._squared_distance(opponent.position, volleyball.position))
        for i, marker in enumerate(markers):
            if marker.id not in controlled_id_set:
                continue
            if i < len(opponents):
                target_position = self._marking_position(opponents[i], volleyball)
            else:
                # nobody to mark: cover the volleyball's way to the closest hoop
                target_position = Vector2(
                    (volleyball.position.x + closest_hoop.position.x) / 2,
                    (volleyball.position.y + closest_hoop.position.y) / 2
                )
            target_position = self._clamp(target_position, x_limits, y_limits)
            marker.direction = move_around_hoop_blockage(marker, target_position, target_hoop=closest_hoop)

    def _marking_position(self, opponent: Player, volleyball: VolleyBall) -> Vector2:
        """Point in the passing lane, `marking_distance` from the opponent towards the volleyball."""
        dx = volleyball.position.x - opponent.position.x
        dy = volleyball.position.y - opponent.position.y
        distance = (dx ** 2 + dy ** 2) ** 0.5
        if distance == 0:
            return Vector2(opponent.position.x, opponent.position.y)
        fraction = min(1.0, self.marking_distance / distance)
        return Vector2(opponent.position.x + fraction * dx, opponent.position.y + fraction * dy)

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
