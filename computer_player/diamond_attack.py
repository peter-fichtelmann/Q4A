

from typing import Optional, List

from core.entities import Vector2
from core.game_logic.game_logic import GameLogic


class DiamondAttack:

    def __init__(self,
                logic: GameLogic,
                attack_cpu_player_ids: List[str]
                ):
        self.logic = logic
        self.attack_cpu_player_ids = attack_cpu_player_ids


    def __call__(self,
                dt: float,
                next_volleyball_holder_id: str,
                intercepting_position: Optional[Vector2] = None
                ):
        volleyball = self.logic.state.get_volleyball()
        if volleyball.holder_id is None and next_volleyball_holder_id in self.attack_cpu_player_ids:
            next_holder = self.logic.state.players[next_volleyball_holder_id]
            if intercepting_position is not None:
                next_holder.direction = Vector2(
                    intercepting_position.x - next_holder.position.x,
                    intercepting_position.y - next_holder.position.y
                )
            else:
                next_holder.direction = Vector2(
                    volleyball.position.x - next_holder.position.x,
                    volleyball.position.y - next_holder.position.y
                )

    