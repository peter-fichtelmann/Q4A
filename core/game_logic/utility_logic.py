from core.game_state import GameState
from core.entities import Player, Ball, VolleyBall, DodgeBall, Vector2, PlayerRole, BallType
from operator import itemgetter
# from numba import jit

class UtilityLogic:
    """
    Provides shared utility calculations for game logic systems.

    Attributes:
        state: Shared GameState instance for entity lists and caches.
    """

    def __init__(self, game_state: GameState):
        """
        Initialize utility logic helpers.

        Args:
            game_state: The active GameState instance.
        """
        self.state = game_state

    def _calculate_distances(self) -> None:
        """
        Precompute squared distances between all relevant entity pairs.
        
        Builds two representations of entity distances:
        1. squared_distances_dicts: Nested dict for O(1) lookups between two specific entities: dict[str, dict[str, float]]
        2. squared_distances: Sorted list of nearby entities for each entity (nearest-first): dict[str, List[Tuple[str, float]]]
        
        Skips distance calculations for:
        - Knocked out players
        - Keeper-Beater and Chaser-Beater pairs (no collision yet)
        - Beater-Volleyball pairs (beaters don't interact with volleyball)
        
        This precomputation enables efficient collision detection in subsequent methods.
        """
        entities_list = list(list(self.state.players.values()) + list(self.state.balls.values()))
        for entity in entities_list:
            if entity.id not in self.state.squared_distances_dicts:
                self.state.squared_distances_dicts[entity.id] = {}
        for i, entity_1 in enumerate(entities_list):
            if i+1 == len(entities_list):
                break
            # If entity_1 is knocked out skip pairs involving it
            if hasattr(entity_1, 'is_knocked_out'):
                if entity_1.is_knocked_out:
                    continue

            for entity_2 in entities_list[i+1:]:
                # Skip pairs where entity_2 is knocked out
                if hasattr(entity_2, 'is_knocked_out'):
                    if entity_2.is_knocked_out:
                        continue
                # Skip keeper-beater and chaser-beater combinations (any order)
                if isinstance(entity_1, Player) and isinstance(entity_2, Player):
                    if ((entity_1.role == PlayerRole.BEATER and entity_2.role in (PlayerRole.KEEPER, PlayerRole.CHASER)) or
                        (entity_2.role == PlayerRole.BEATER and entity_1.role in (PlayerRole.KEEPER, PlayerRole.CHASER))):
                        continue
                # Skip beater-volleyball combinations (any order)
                if isinstance(entity_1, Player) and isinstance(entity_2, Ball):
                    if entity_1.role == PlayerRole.BEATER and entity_2.ball_type == BallType.VOLLEYBALL:
                        continue
                if isinstance(entity_2, Player) and isinstance(entity_1, Ball):
                    if entity_2.role == PlayerRole.BEATER and entity_1.ball_type == BallType.VOLLEYBALL:
                        continue
                # if isinstance(entity_2, Ball) and isinstance(entity_1, Ball): # Ball-Ball collisions checked in separate method
                #     continue

                # Store squared distance for the pair
                # self.state.squared_distances[(entity_1.id, entity_2.id)] = UtilityLogic._squared_distance(entity_1.position, entity_2.position)
                squared_distance = UtilityLogic._squared_distance(entity_1.position, entity_2.position)
                self.state.squared_distances_dicts[entity_1.id][entity_2.id] = squared_distance
                self.state.squared_distances_dicts[entity_2.id][entity_1.id] = squared_distance
                # Store or use the distance as needed
        for entity in entities_list:
            # sort the inner dict by distance ascending
            self.state.squared_distances[entity.id] = sorted(self.state.squared_distances_dicts[entity.id].items(), key=itemgetter(1))
    # def _get_sorted_distances(self, entity_id: str) -> Tuple[str, float]:
    #     """Return a dict mapping the other-entity id -> squared distance sorted nearest-first.
    #     """

    #     # The internal `self.state.squared_distances` stores distances keyed by a tuple
    #     # of two entity ids (id1, id2). Filter entries that include `entity_id`,
    #     # sort them by distance (ascending) and return a dict where keys are the
    #     # other entity id and values are the squared distances.

    #     # # Build a filtered dict of pair -> distance where the given entity_id is part of the pair
    #     # pair_distances = {
    #     #     pair: dist
    #     #     for pair, dist in self.state.squared_distances.items()
    #     #     if entity_id in pair
    #     # }

    #     # # Sort pairs by distance (nearest first). This produces a list of
    #     # # ((id1, id2), distance) tuples.
    #     # sorted_pairs = sorted(pair_distances.items(), key=lambda item: item[1])

    #     # Convert to other_id -> distance mapping preserving the sorted order
    #     # other_dict: dict = {}
    #     # for (id1, id2), distance in sorted_pairs:
    #     #     other_id = id2 if id1 == entity_id else id1
    #     #     other_dict[other_id] = distance
    #     sorted_tuples = sorted(self.state.squared_distances[entity_id].items(), key=itemgetter(1))
    #     # other_dict: dict = {}
    #     # for other_id, distance in sorted_tuples:
    #     #     other_dict[other_id] = distance
    #     # print(other_dict)
    #     return sorted_tuples

    @staticmethod
    def _distance(pos1: Vector2, pos2: Vector2) -> float:
        """
        Calculate Euclidean distance between two positions.
        
        Args:
            pos1: First position vector
            pos2: Second position vector
            
        Returns:
            The distance between the two positions
        """
        dx = pos1.x - pos2.x
        dy = pos1.y - pos2.y
        return (dx**2 + dy**2)**0.5

    @staticmethod
    def _squared_distance(pos1: Vector2, pos2: Vector2) -> float:
        """
        Calculate squared Euclidean distance between two positions.
        
        Returns the squared distance (avoids expensive square root) for use in
        collision detection comparisons where only relative distances matter.
        
        Args:
            pos1: First position vector
            pos2: Second position vector
            
        Returns:
            The squared distance between the two positions
        """
        dx = pos1.x - pos2.x
        dy = pos1.y - pos2.y
        return dx**2 + dy**2
    
    @staticmethod
    def _magnitude(vector: Vector2) -> float:
        """Calculate magnitude of a vector."""
        return (vector.x**2 + vector.y**2)**0.5
    
    @staticmethod
    def _squared_sum(value_1: float, value_2: float) -> float:
        return value_1**2 + value_2**2
    

    # numba more useful if more complex calculations, more looping
    # @jit(fastmath=True, cache=True)
    # def _distance_numba(pos1_x: float, pos1_y: float, pos2_x: float, pos2_y: float) -> float:
    #     """Calculate Euclidean distance between two positions."""
    #     return ((pos1_x - pos2_x)**2 + (pos1_y - pos2_y)**2)**0.5
    
    # @jit(fastmath=True, cache=True)
    # def _squared_distance_numba(pos_1_x: float, pos_1_y: float, pos_2_x: float, pos_2_y: float) -> float:
    #     return (pos_1_x - pos_2_x)**2 + (pos_1_y - pos_2_y)**2

    # # numba about double as fast with square root than python if compiled before
    # @jit(fastmath=True, cache=True)
    # def _magnitude_numba(value_1: float, value_2: float) -> float:
    #     """Calculate magnitude of a vector."""
    #     return (value_1**2 + value_2**2)**0.5

    # @jit(fastmath=True, cache=True)
    # def _square_sum(value_1: float, value_2: float) -> float:
    #     return value_1**2 + value_2**2

    # @staticmethod
    # def _square_sum(value_1: float, value_2: float) -> float:
    #     return value_1**2 + value_2**2
    
    # def _magnitude_python(value_1: float, value_2: float) -> float:
    #     """Calculate magnitude of a vector."""
    #     return (value_1**2 + value_2**2)**0.5

        # @staticmethod
    # def _magnitude(vector: Vector2) -> float:
    #     """Calculate magnitude of a vector."""
    #     return UtilityLogic._square_sum(vector.x, vector.y)**0.5