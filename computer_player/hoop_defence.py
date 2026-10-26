import logging
import math
from typing import Dict, List, Optional, Tuple
from core.entities import Hoop, Player, VolleyBall, Vector2, PlayerRole
from core.game_logic.game_logic import GameLogic
from computer_player.base_strategy import BaseStrategy, StepContext, TeamRoster
from computer_player.computer_player_utility.move_around_hoop_blockage import MoveAroundHoopBlockage
from computer_player.computer_player_utility.computer_player_utility import MoveUtility, BeaterThrowDecider

from core.game_logic.utility_logic import UtilityLogic


class HoopDefenceChaserKeeper(BaseStrategy):
    """
    Chaser/keeper part of the hoop defence where all chasers stand in front the hoops.
    The position (in front or behind hoops) changes when the volleyball moves over the hoop baseline.
    Hoop chasers tackle a carrier they get in contact with.

    The keeper is moving towards the volleyball, but stays within the keeper zone.

    Hoop chaser positions, relative to the volleyball (with `anticipate_volleyball` during a pass where it
    will be caught, so the hoop assignment and the side change start with the pass):
        - default: straight in front of / behind the hoop
        - `orient_to_volleyball`: on the line from the hoop to the volleyball, just outside the hoop blockage
          zone, which closes the side of the hoop nearer to the volleyball
        - `between_hoops_fraction`: if the volleyball's y is between the y of this hoop and a neighbouring
          hoop, this fraction of the way from the hoop's y to the volleyball's y, so the chaser can cover
          both hoops
    """
    def __init__(self,
                 logic: GameLogic,
                 move_around_hoop_blockages: Dict[int, MoveAroundHoopBlockage], # per team, around the team's own hoops
                 anticipate_volleyball: bool = False,
                 orient_to_volleyball: bool = False,
                 between_hoops_fraction: Optional[float] = None, # None: always in front of the own hoop
                 logger: Optional[logging.Logger] = None
                 ):
        """Store the hoop blockage helpers and the positioning options."""
        super().__init__(logic, logger)
        self.move_around_hoop_blockages = move_around_hoop_blockages
        self.anticipate_volleyball = anticipate_volleyball
        self.orient_to_volleyball = orient_to_volleyball
        self.between_hoops_fraction = between_hoops_fraction

    def reference_position(self, ctx: StepContext) -> Vector2:
        """Volleyball position the defence positions against: where it will be caught with `anticipate_volleyball`."""
        if self.anticipate_volleyball and ctx.anticipated_volleyball_position is not None:
            return ctx.anticipated_volleyball_position
        return self.logic.state.volleyball.position

    def __call__(self,
                 ctx: StepContext,
                 team: int,
                 controlled_ids: List[str],
                 assigned_beater_ids: List[str]):
        """Run one defence update tick for the keeper and chasers in `controlled_ids`."""
        volleyball = self.logic.state.volleyball
        defence_hoops = ctx.rosters[team].own_hoops
        controlled_id_set = set(controlled_ids)
        reference_position = self.reference_position(ctx)

        volleyball_hoop_distances = {
            hoop.id: (reference_position.x - hoop.position.x) ** 2 + (reference_position.y - hoop.position.y) ** 2
            for hoop in defence_hoops
        }
        sorted_hoop_distances = sorted(volleyball_hoop_distances.items(), key=lambda item: item[1])
        closest_hoop_id, closest_hoop_distance = sorted_hoop_distances[0]
        closest_hoop = self.logic.state.hoops[closest_hoop_id]
        chaser_hoop_squared_distances = {hoop.id: {} for hoop in defence_hoops}

        for player in self.logic.state.players.values():
            if player.team != team:
                continue
            if player.role == PlayerRole.KEEPER and player.id in controlled_id_set:
                self.keeper_action(player, volleyball, closest_hoop, team)
            elif player.role == PlayerRole.CHASER:
                # get positions of chasers to hoops
                if not player.is_knocked_out:
                    for hoop in defence_hoops:
                        chaser_hoop_squared_distances[hoop.id][player.id] = (player.position.x - hoop.position.x) ** 2 + (player.position.y - hoop.position.y) ** 2
        self.chasers_action(sorted_hoop_distances, chaser_hoop_squared_distances, volleyball, ctx.dt, team, controlled_id_set,
                            reference_position if self.anticipate_volleyball else None)

    def chasers_action(self, sorted_hoop_distances, chaser_hoop_squared_distances, volleyball: VolleyBall, dt: float, team: int, controlled_id_set: set,
                       reference_position: Optional[Vector2] = None):
        """Assign and steer chasers to defend hoop lanes based on proximity order."""
        # move chaser closest to hoop with closest distance volleyball first; then move next closest chaser to next closest hoop and so on, but only if they are not already directed towards a hoop by a closer chaser
        move_around_hoop_blockage = self.move_around_hoop_blockages[team]
        directed_chasers = []
        for hoop_id, _ in sorted_hoop_distances:
            sorted_chaser_distances = sorted(chaser_hoop_squared_distances[hoop_id].items(), key=lambda item: item[1])
            for chaser_id, _ in sorted_chaser_distances:
                if chaser_id not in directed_chasers:
                    chaser = self.logic.state.get_player(chaser_id)
                    target_hoop = self.logic.state.hoops[hoop_id]
                    directed_chasers.append(chaser_id)
                    if chaser_id in controlled_id_set:
                        # TODO: chasers move with volleyball movement (between hoop x +/-) and chasers acknowledge hoop blockage and move around it if volleyball less than hoop x
                        add_hoop_blockage_x = chaser.radius + volleyball.radius
                        next_chaser_position_x, next_chaser_position_y = self.logic.basic_logic.get_update_position(chaser, dt)
                        if reference_position is not None:
                            reference_x, reference_y = reference_position.x, reference_position.y
                        else:
                            reference_x, reference_y = self.logic.basic_logic.get_update_position(volleyball, dt)
                        target_position, add_target_x_buffer = self._hoop_position(
                            chaser, target_hoop, reference_x, reference_y, add_hoop_blockage_x, move_around_hoop_blockage)
                        next_direction_to_hoop = Vector2(
                            target_position.x - next_chaser_position_x,
                            target_position.y - next_chaser_position_y
                        )
                        chaser.direction = move_around_hoop_blockage(
                            player=chaser,
                            target_position=target_position,
                            target_hoop=target_hoop,
                            add_hoop_blockage_x=add_hoop_blockage_x,
                            lookahead_to_target=next_direction_to_hoop,
                            add_target_x_buffer=add_target_x_buffer
                        )
                        # tackle a carrier running into the hoop defender, every frame until the next CPU move (no-op without contact)
                        chaser.is_holding_tackle = True
                    break

    def _hoop_position(self,
                       chaser: Player,
                       hoop: Hoop,
                       reference_x: float,
                       reference_y: float,
                       add_hoop_blockage_x: float,
                       move_around_hoop_blockage: MoveAroundHoopBlockage) -> Tuple[Vector2, bool]:
        """Where the chaser defends `hoop` against a volleyball at the reference position, and whether the x buffer is still to be added."""
        side = 1 if reference_x > hoop.position.x else -1 # in front of or behind the hoop, towards the volleyball
        # the blockage zone widened by the buffer factors, like the corners of MoveAroundHoopBlockage
        buffered_x = add_hoop_blockage_x * move_around_hoop_blockage.move_buffer_factor_x
        buffered_y = (hoop.radius + chaser.radius) * move_around_hoop_blockage.move_buffer_factor_y
        if self.between_hoops_fraction is not None:
            offset_y = reference_y - hoop.position.y
            if any(0 < abs(offset_y) < abs(other.position.y - hoop.position.y) and (other.position.y - hoop.position.y) * offset_y > 0
                   for other in move_around_hoop_blockage.defence_hoops if other is not hoop):
                return Vector2(hoop.position.x + side * buffered_x, hoop.position.y + self.between_hoops_fraction * offset_y), False
        if self.orient_to_volleyball:
            dx = reference_x - hoop.position.x
            dy = reference_y - hoop.position.y
            distance = math.hypot(dx, dy)
            if distance > 0:
                # first point on the line hoop -> volleyball outside the buffered zone
                ux, uy = dx / distance, dy / distance
                exit_distance = min(buffered_x / abs(ux) if ux != 0 else float('inf'),
                                    buffered_y / abs(uy) if uy != 0 else float('inf'))
                return Vector2(hoop.position.x + ux * exit_distance, hoop.position.y + uy * exit_distance), False
        return Vector2(hoop.position.x + side * add_hoop_blockage_x, hoop.position.y), True

    def _is_volleyball_in_keeper_zone(self, volleyball: VolleyBall, team: int) -> bool:
        """Return whether the ball is currently inside this team's keeper zone."""
        if volleyball is not None:
            if team == self.logic.state.team_0:
                return volleyball.position.x < self.logic.state.keeper_zone_x_0
            else:
                return volleyball.position.x > self.logic.state.keeper_zone_x_1

    def keeper_action(self, player: Player, volleyball: VolleyBall, closest_hoop: Hoop, team: int):
        """Move keeper to ball in-zone, otherwise to projected hoop-line crossing."""
        # TODO: keeper anticipates next volleyball position by velocitiy
        # if volleyball is in keeper zone, move towards the volleyball, else move towards the crossing point of volleyball-closest hoop and keeper zone line
        if self._is_volleyball_in_keeper_zone(volleyball, team):
            # Move towards the volleyball
            direction_to_ball = Vector2(
                volleyball.position.x - player.position.x,
                volleyball.position.y - player.position.y
            )
            player.direction = direction_to_ball
        else:
            # calculate crossing point of volleyball-closest hoop and keeper zone line
            closest_hoop_volleyball_vector = Vector2(
                closest_hoop.position.x - volleyball.position.x,
                closest_hoop.position.y - volleyball.position.y
            )
            crossing_point_x = self.logic.state.keeper_zone_x_0 if team == self.logic.state.team_0 else self.logic.state.keeper_zone_x_1
            crossing_point_y = volleyball.position.y + ((crossing_point_x - volleyball.position.x) / closest_hoop_volleyball_vector.x) * closest_hoop_volleyball_vector.y
            player.direction.x = crossing_point_x - player.position.x
            player.direction.y = crossing_point_y - player.position.y
        # always try to tackle if not throwing, every frame until the next CPU move
        player.is_holding_tackle = True


class HoopDefenceBeater(BaseStrategy):
    """
    Beater part of the hoop defence.

    Beaters are sticking to the hoops and throw at the volleyball holder if the volleyball holder is close enough.

    With `anticipate_volleyball`, during a pass the pull to the volleyball goes to where it will be caught.
    With `throw_at_receiver`, the expected receiver of an opponent pass in flight is thrown at like a holder.
    """
    def __init__(self,
                 logic: GameLogic,
                 beater_throw_decider: BeaterThrowDecider,
                 beater_evade_beater_buddy_weight: float,
                 beater_evade_volleyball_weight: float,
                 beater_evade_chaser_keeper_weight: float,
                 loaded_beater_evade_beater_weight: float,
                 unloaded_beater_evade_beater_weight: float,
                 unloaded_beater_max_x_to_midline: float,
                 positioning_boundary_buffer_distance: float = 2, # distance from boundary at which to start evading boundary
                 anticipate_volleyball: bool = False,
                 throw_at_receiver: bool = False,
                 logger: Optional[logging.Logger] = None
                 ):
        """Initialize beater steering configuration."""
        super().__init__(logic, logger)
        self.beater_throw_decider = beater_throw_decider
        self.cherry_picker = None # optional CherryPicker, set by the orchestrator
        self.beater_evade_beater_buddy_weight = beater_evade_beater_buddy_weight
        self.beater_evade_volleyball_weight = beater_evade_volleyball_weight
        self.beater_evade_chaser_keeper_weight = beater_evade_chaser_keeper_weight
        self.loaded_beater_evade_beater_weight = loaded_beater_evade_beater_weight
        self.unloaded_beater_evade_beater_weight = unloaded_beater_evade_beater_weight
        self.unloaded_beater_max_x_to_midline = unloaded_beater_max_x_to_midline
        self.positioning_boundary_buffer_distance = positioning_boundary_buffer_distance
        self.anticipate_volleyball = anticipate_volleyball
        self.throw_at_receiver = throw_at_receiver

    def __call__(self,
                 ctx: StepContext,
                 team: int,
                 controlled_ids: List[str],
                 assigned_beater_ids: List[str]):
        """Move and throw for the defending beaters in `controlled_ids` not fetching a dodgeball."""
        volleyball = self.logic.state.volleyball
        own_hoops = ctx.rosters[team].own_hoops
        center_hoop = own_hoops[1] if len(own_hoops) == 3 else own_hoops[0]
        controlled_id_set = set(controlled_ids)
        defence_beaters = [player for player in self.logic.state.players.values() if player.team == team and player.role == PlayerRole.BEATER]
        attack_players = [player for player in self.logic.state.players.values() if player.team != team]
        volleyball_position = volleyball.position
        if self.anticipate_volleyball and ctx.anticipated_volleyball_position is not None:
            volleyball_position = ctx.anticipated_volleyball_position
        receiver = None
        if self.throw_at_receiver and volleyball.holder_id is None and not volleyball.is_dead and ctx.anticipated_carrier_id is not None:
            receiver = self.logic.state.players[ctx.anticipated_carrier_id]
            if receiver.team == team or receiver.is_knocked_out:
                receiver = None
        for beater in defence_beaters:
            # beater action if beater cpu player and not already assigned to get a dodgeball
            if beater.id in controlled_id_set and beater.id not in assigned_beater_ids:
                self.beater_move_action(beater, volleyball_position, center_hoop, defence_beaters, attack_players)
                self.beater_throw_action(beater, volleyball, ctx.rosters[team], receiver)

    def beater_move_action(self, beater: Player, volleyball_position: Vector2, center_hoop: Hoop, defence_beaters: List[Player], attack_players: List[Player]):
        """
        if loaded beater:
            Move beaters to center hoop and directing them with evade and -evade vectors (the closer the more impactful).

            Then check if beater should throw
        """
        move_vector = Vector2(
            center_hoop.position.x - beater.position.x,
            center_hoop.position.y - beater.position.y
        )
        move_vector_mag = UtilityLogic._magnitude(move_vector)
        if move_vector_mag == 0:
            move_vector = Vector2(0, 0)
        else:
            move_vector = Vector2(
                move_vector.x / move_vector_mag,
                move_vector.y / move_vector_mag
            )
        evade_vectors = []
        for beater_buddy in defence_beaters:
            # if loaded beater buddy
            if beater_buddy.id != beater.id and beater_buddy.has_ball:
                evade_vectors.append(MoveUtility.evade(beater.position, beater_buddy.position, weight=self.beater_evade_beater_buddy_weight))

        if beater.has_ball: # loaded beater
            for opponent in attack_players:
                if opponent.role in [PlayerRole.CHASER, PlayerRole.KEEPER]:
                    # negative weight
                    evade_vectors.append(MoveUtility.evade(beater.position, opponent.position, weight=self.beater_evade_chaser_keeper_weight))
                elif opponent.role == PlayerRole.BEATER:
                    evade_vectors.append(MoveUtility.evade(beater.position, opponent.position, weight=self.loaded_beater_evade_beater_weight))
            # negative weight to volleyball
            evade_vectors.append(MoveUtility.evade(beater.position, volleyball_position, weight=self.beater_evade_volleyball_weight))
        else: # unloaded beater
            # try to make contact with opponent beater if not x position to close to midline
            x_to_midline = abs(beater.position.x - self.logic.state.midline_x)
            if x_to_midline > self.unloaded_beater_max_x_to_midline:
                for opponent in attack_players:
                    if opponent.role == PlayerRole.BEATER:
                        # negative weight
                        evade_vectors.append(MoveUtility.evade(beater.position, opponent.position, weight=self.unloaded_beater_evade_beater_weight))
                beater.is_holding_tackle = True # unloaded beaters try to make contact with other close opponent beaters
        for evade_vector in evade_vectors:
            move_vector.x += evade_vector.x
            move_vector.y += evade_vector.y
        move_vector = MoveUtility.adjust_move_vector_to_avoid_boundary(
            beater.position,
            move_vector,
            boundary_x_min = self.logic.state.boundaries_x[0],
            boundary_x_max = self.logic.state.boundaries_x[1],
            boundary_y_min = self.logic.state.boundaries_y[0],
            boundary_y_max = self.logic.state.boundaries_y[1],
            buffer = self.positioning_boundary_buffer_distance
        )
        beater.direction = move_vector

    def beater_throw_action(self, beater: Player, volleyball: VolleyBall, roster: TeamRoster, receiver: Optional[Player] = None):
        """Throw at the volleyball holder (or the expected `receiver` of a pass) when distance-based criteria are satisfied, otherwise look for a cherry pick."""
        if not beater.has_ball:
            return
        volleyball_holder = self.logic.state.players[volleyball.holder_id] if volleyball.holder_id is not None else receiver
        if volleyball_holder is not None:
            if self.beater_throw_decider.should_throw_at_volleyball_holder(beater, volleyball_holder):
                if self.beater_throw_decider.throw_at(self.logic.process_action_logic, beater, volleyball_holder):
                    return
        if self.cherry_picker is not None:
            self.cherry_picker.try_pick(beater, roster, on_attack=False)
