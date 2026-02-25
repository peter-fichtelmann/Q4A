import logging
from typing import Optional, List

from computer_player.computer_player_utility import InterceptionRatioCalculator, MoveAroundHoopBlockage
from core.entities import Player, PlayerRole, Vector2, VolleyBall
from core.game_logic.game_logic import GameLogic


class DiamondAttack:

    def __init__(self,
                logic: GameLogic,
                move_around_hoop_blockage: MoveAroundHoopBlockage,
                interception_ratio_calculator: InterceptionRatioCalculator,
                attack_cpu_player_ids: List[str],
                attack_team: int,
                score_interception_max_dt_steps: int = 10,
                score_interception_max_distance_per_step: Optional[float] = None,
                score_interception_max_dt_per_step: Optional[int] = None,
                scoring_threshold: float = 0.8,
                logger: Optional[logging.Logger] = None
                ):
        self.logic = logic
        self.move_around_hoop_blockage = move_around_hoop_blockage
        self.interception_ratio_calculator = interception_ratio_calculator
        self.attack_cpu_player_ids = attack_cpu_player_ids
        self.score_interception_max_dt_steps = score_interception_max_dt_steps
        self.score_interception_max_distance_per_step = score_interception_max_distance_per_step
        self.score_interception_max_dt_per_step = score_interception_max_dt_per_step

        self.scoring_threshold = scoring_threshold
        self.logger = logger or logging.getLogger("computer_player")

        self.attack_hoops = [hoop for hoop in self.logic.state.hoops.values() if hoop.team != attack_team]
        self.defending_chaser_keeper_ids = [player.id for player in self.logic.state.players.values() if player.team != attack_team and player.role in [PlayerRole.CHASER, PlayerRole.KEEPER]]

    def move_to_volleyball(self,
                           volleyball: VolleyBall,
                           next_volleyball_holder_id: str,
                           intercepting_position: Optional[Vector2] = None
                           ):
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

    def get_intercepting_scores_for_hoops(self, dt: float, volleyball: VolleyBall, volleyball_holder: Player):
        intercepting_scores_dict = {}
        for hoop in self.attack_hoops:
            copy_volleyball = volleyball.copy()
            volleyball_hoop_vector = Vector2(
                hoop.position.x - copy_volleyball.position.x,
                hoop.position.y - copy_volleyball.position.y
            )
            mag_volleyball_hoop_vector = (volleyball_hoop_vector.x**2 + volleyball_hoop_vector.y**2) ** 0.5
            if mag_volleyball_hoop_vector == 0:
                continue
            copy_volleyball.velocity = Vector2(
                volleyball_holder.throw_velocity * volleyball_hoop_vector.x / mag_volleyball_hoop_vector,
                volleyball_holder.throw_velocity * volleyball_hoop_vector.y / mag_volleyball_hoop_vector
            )
            intercepting_score, scores_info = self.interception_ratio_calculator(
                 dt=dt,
                 moving_entity=copy_volleyball,
                 intercepting_player_ids=self.defending_chaser_keeper_ids,
                 max_dt_steps=self.score_interception_max_dt_steps,
                 target_position=hoop.position,
                 only_first_intercepting=False,
                 max_distance_per_step=self.score_interception_max_distance_per_step,
                 max_dt_per_step=self.score_interception_max_dt_per_step
            )
            intercepting_scores_dict[hoop.id] = intercepting_score
            # self.logger.debug("Interception info per hoop %s: %s, %s", hoop.id, intercepting_score, scores_info)
        self.logger.debug("intercepting_scores_dict %s", intercepting_scores_dict)
        return intercepting_scores_dict

    def score_attempt(self, dt: float, volleyball: VolleyBall, volleyball_holder: Player):
        intercepting_scores_dict = self.get_intercepting_scores_for_hoops(dt, volleyball, volleyball_holder)
        # get hoop with highest interception score (lowest chance of being intercepted)
        best_hoop_id = min(intercepting_scores_dict, key=intercepting_scores_dict.get)
        best_score = intercepting_scores_dict[best_hoop_id]
        if best_score > self.scoring_threshold:
            self.logger.info("Scoring on hoop %s with interception score %s", best_hoop_id, best_score)
            best_hoop = self.logic.state.hoops[best_hoop_id]
            volleyball_holder.direction = Vector2(
                best_hoop.position.x - volleyball_holder.position.x,
                best_hoop.position.y - volleyball_holder.position.y
            )
            self.logic.process_action_logic.process_throw_action(volleyball_holder.id)


    def __call__(self,
                dt: float,
                next_volleyball_holder_id: str,
                intercepting_position: Optional[Vector2] = None
                ):
        volleyball = self.logic.state.get_volleyball()
        if next_volleyball_holder_id in self.attack_cpu_player_ids:
            if volleyball.holder_id is None:
                self.move_to_volleyball(volleyball, next_volleyball_holder_id, intercepting_position)
            else: # already hold of volleyball
                volleyball_holder = self.logic.state.players[volleyball.holder_id]
                self.score_attempt(dt, volleyball, volleyball_holder)
        elif volleyball.holder_id is not None:
            self.get_intercepting_scores_for_hoops(dt, volleyball, self.logic.state.players[volleyball.holder_id])
