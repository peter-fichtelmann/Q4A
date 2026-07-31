from enum import Flag
import logging
from core.game_logic.utility_logic import UtilityLogic
from core.game_state import GameState
from core.entities import Vector2

BASE_LOGGER = logging.getLogger('quadball.game_logic')

class PhysicalContactLogic:
    """
    Resolves player-to-player collision physics.

    Attributes:
        state: Shared GameState instance for player access.
    """

    def __init__(self, game_state: GameState, logger: logging.Logger | None = None):
        """
        Initialize collision handling.

        Args:
            game_state: The active GameState instance.
        """
        self.state = game_state
        self.logger = logger or BASE_LOGGER

    def _enforce_tackle(self) -> None:
        """
        Enforce tackling effects on players: no movement when tackling or being tackled.
        """
        # TODO add player dependent tackle strength -> probability for enforcing tackle and stealing ball if close enough to steal
        for player in self.state.players.values():
            if len(player.tackling_player_ids) > 0:
                player.direction = Vector2(0, 0) # stop movement when being tackled or tackling
                player.velocity = Vector2(0, 0) # stop movement when being tackled or tackling
                player.tackling_player_ids = []

    def _check_player_collisions(self) -> None:
        """
        Detect and resolve collisions between players.

        Models as elastic collisions where players absorb their momentums along their axis.
        
        When two active (non-knocked-out) players of similar positions collide:
        - Separates their velocity components along and perpendicular to collision normal
        - Averages the velocity component along the collision line
        - Preserves each player's perpendicular (tangential) velocity
        
        This creates realistic elastic collisions where players don't stick together
        but bounce off each other naturally.
        """
        # TODO punish or prevent contact from behind (when enough velocity)
        # TODO prevent any contact with protected keeper

        # reset in contact player ids from last update (in separate loop because in other loop attributes of other players set)
        players = list(self.state.players.values())
        n_players = len(players)
        for player in players:
            # resetting each update and adding back if still persisting
            player.in_contact_player_ids = []
        # for i, player in enumerate(players[:-1]):
        for i in range(n_players - 1):
            player = players[i]
            if player.is_knocked_out:
                continue
            # for other_id, distance in self._get_sorted_distances(player.id).items():
            # for other_id, distance in self.state.squared_distances.get(player.id, []):
            #     if other_id in list(self.state.players.keys())[i+1:]: # only check each pair once
            #         other_player = self.state.players[other_id]
            for j in range(i + 1, n_players):
                other_player = players[j]
                distance = self.state.squared_distances_player_player_dicts.get(player.id, {}).get(other_player.id)
                if distance is None:
                    continue
                if other_player.is_knocked_out:
                    continue
                collision_dist_sq = (player.radius + other_player.radius) ** 2
                if distance < collision_dist_sq:
                    # Collision occurred
                    player.in_contact_player_ids.append(other_player.id)
                    other_player.in_contact_player_ids.append(player.id)
                    UtilityLogic._resolve_elastic_entity_collisions(player, other_player)
