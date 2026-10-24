import itertools
import logging
from typing import Dict, Optional, List, Tuple

from computer_player.base_strategy import BaseStrategy, StepContext, TeamRoster
from computer_player.computer_player_utility.move_around_hoop_blockage import MoveAroundHoopBlockage
from computer_player.computer_player_utility.computer_player_utility import BeaterThrowDecider, MoveUtility, PassEvaluator, ScoreAttempter
from core.entities import Player, PlayerRole, Vector2, VolleyBall
from core.game_logic.game_logic import GameLogic
from core.game_logic.utility_logic import UtilityLogic


class DiamondAttackChaserKeeper(BaseStrategy):
    """
    Chaser/keeper part of the diamond attack formation.

    Players are motivated to form a square around opponent hoops,
    with two players on the sides, one in front, and one behind.

    This is achieved via a move vector towards the hoops and evade vectors to evade:
        - opponent loaded beaters
        - opponent chasers/keeper
        - own chasers/keeper (to keep distance and form square)
    and a quadratic anti evade (pull) vector towards own chasers/keeper, negligible up close
    but outweighing the teammate evasion beyond the max passing distance.

    If they are under pressure, they pass.

    If there is a scoring opportunity, they score.

    Hoop assignment and evade vectors are computed for all attacking chasers/keepers
    and cached for the step, so moves can position their players the same way
    via `position_player`.
    """

    def __init__(self,
                logic: GameLogic,
                move_around_hoop_blockages: Dict[int, MoveAroundHoopBlockage], # per team, around the team's own hoops
                score_attempter: ScoreAttempter,
                pass_evaluator: PassEvaluator,
                chaser_evade_beater_weight: float = 4,
                chaser_evade_chaser_keeper_weight: float = 2,
                chaser_evade_teamate_chaser_keeper_weight: float = 1,
                chaser_pull_teammate_chaser_keeper_distance: Optional[float] = None, # distance at which the quadratic pull to a teammate cancels the teammate evasion, default max passing distance
                volleyball_holder_evade_own_hoop_weight: float|Tuple[float, float] = (1, 2),
                positioning_boundary_buffer_distance: float = 2, # distance from boundary at which to start evading boundary
                passing_threshold: float = 0.8, # minimum interception score (chance of not being intercepted) to attempt a pass
                passing_squared_max_distance: float = 400,
                logger: Optional[logging.Logger] = None
                ):
        """Configure attack-team positioning, passing, and scoring heuristics."""
        super().__init__(logic, logger)
        self.move_around_hoop_blockages = move_around_hoop_blockages
        self.score_attempter = score_attempter
        self.pass_evaluator = pass_evaluator
        self.chaser_evade_beater_weight = chaser_evade_beater_weight
        self.chaser_evade_chaser_keeper_weight = chaser_evade_chaser_keeper_weight
        self.chaser_evade_teamate_chaser_keeper_weight = chaser_evade_teamate_chaser_keeper_weight
        self.volleyball_holder_evade_own_hoop_weight = volleyball_holder_evade_own_hoop_weight
        self.positioning_boundary_buffer_distance = positioning_boundary_buffer_distance
        self.passing_threshold = passing_threshold
        self.passing_squared_max_distance = passing_squared_max_distance
        if chaser_pull_teammate_chaser_keeper_distance is None:
            chaser_pull_teammate_chaser_keeper_distance = passing_squared_max_distance ** 0.5
        # pull weight * d^2 equals evade weight / d at the pull distance: push dominates below it, pull above it
        self.chaser_pull_teammate_chaser_keeper_weight = chaser_evade_teamate_chaser_keeper_weight / chaser_pull_teammate_chaser_keeper_distance ** 3
        # cached per step by __call__
        self.roster: Optional[TeamRoster] = None
        self.move_vectors: Dict[str, Vector2] = {}
        self.evade_vectors: Dict[str, Vector2] = {}

    def move_to_volleyball(self,
                           volleyball: VolleyBall,
                           next_volleyball_holder_id: str,
                           intercepting_position: Optional[Vector2] = None
                           ):
            """Direct the predicted next holder toward the ball or intercept point."""
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

    def chaser_keeper_positioning(self, player: Player, total_evade_vector: Vector2, move_vector: Optional[Vector2] = None):
        """
        Blend formation movement with evade vectors and boundary protection.

        The following evade vectors are considered:
            - opponent loaded beaters
            - opponent chasers/keeper
            - own chasers/keeper (to keep distance and form square)
            - own hoops when carrying the volleyball (to avoid running through own hoops)
        """
        team = self.roster.team
        if move_vector is None:
            move_vector = Vector2(
                1 - 2 * team, # 1 for team 0 attacking, -1 for team 1 attacking
                0
            )
        move_vector.x += total_evade_vector.x
        move_vector.y += total_evade_vector.y
        if player.has_ball:
            for hoop in self.roster.own_hoops:
                evade_vector = MoveUtility.evade(player.position, hoop.position, weight=self.volleyball_holder_evade_own_hoop_weight)
                move_vector.x += evade_vector.x
                move_vector.y += evade_vector.y
        move_vector = MoveUtility.adjust_move_vector_to_avoid_boundary(
            player.position,
            move_vector,
            boundary_x_min = self.logic.state.boundaries_x[0],
            boundary_x_max = self.logic.state.boundaries_x[1],
            boundary_y_min = self.logic.state.boundaries_y[0],
            boundary_y_max = self.logic.state.boundaries_y[1],
            buffer = self.positioning_boundary_buffer_distance
        )
        player.direction = Vector2(move_vector.x, move_vector.y)

    def position_player(self, player: Player):
        """Position one attacking chaser/keeper with the move and evade vectors cached in this step."""
        self.chaser_keeper_positioning(player, self.evade_vectors.get(player.id, Vector2(0, 0)), self.move_vectors.get(player.id, None))

    def move_chaser_keeper_hoops(self, players: List[Player]) -> Dict[str, Vector2]:
        """
        Assign attacking chasers/keepers to attack hoops based on total proximity.
        Solving an Assignment Problem but since there are so few players and hoops we can just do it with a brute force approach.
        """
        move_vectors_dict = {}
        player_positions = [player.position for player in players]
        attack_hoops = self.roster.opponent_hoops
        hoops = attack_hoops + [attack_hoops[1]] # add center hoop as additional "hoop"
        target_positions = [hoop.position for hoop in hoops]
        best_permutation, _ = self.solve_assignment_problem(player_positions, target_positions)
        max_player_index = len(player_positions) - 1
        move_around_hoop_blockage = self.move_around_hoop_blockages[self.roster.team]
        for i, player_index in enumerate(best_permutation):
            if player_index > max_player_index:
                continue
            player = players[player_index]
            hoop = hoops[i]
            if player.role == PlayerRole.CHASER:
                move_vector = move_around_hoop_blockage(player, hoop.position)
            else:
                move_vector = Vector2(
                    hoop.position.x - player.position.x,
                    hoop.position.y - player.position.y
                )
            move_vector_mag = UtilityLogic._magnitude(move_vector)
            if move_vector_mag == 0:
                move_vector = Vector2(0, 0)
            else:
                move_vector = Vector2(
                    move_vector.x / move_vector_mag,
                    move_vector.y / move_vector_mag
                )
            move_vectors_dict[player.id] = move_vector
        return move_vectors_dict

    def evade_vectors_chaser_keeper_calculation(self, roster: Optional[TeamRoster] = None) -> Dict[str, Vector2]:
        """Aggregate evade vectors for attacking chasers/keeper versus nearby players (of `roster`, default the current step's)."""
        roster = roster or self.roster
        evade_vectors_dict = {}
        team = roster.team
        for player_id in roster.chaser_keeper_ids:
            player = self.logic.state.players[player_id]
            total_evade_vector = Vector2(0, 0)
            for other_player in self.logic.state.players.values():
                if other_player.team != team:
                    if other_player.role == PlayerRole.BEATER and other_player.has_ball:
                        evade_vector = MoveUtility.evade(player.position, other_player.position, weight=self.chaser_evade_beater_weight)
                        total_evade_vector.x += evade_vector.x
                        total_evade_vector.y += evade_vector.y
                    elif other_player.role in [PlayerRole.CHASER, PlayerRole.KEEPER]: # if chaser or keeper, also check distance and evade if too close
                        evade_vector = MoveUtility.evade(player.position, other_player.position, weight=self.chaser_evade_chaser_keeper_weight)
                        total_evade_vector.x += evade_vector.x
                        total_evade_vector.y += evade_vector.y
                elif other_player.role in [PlayerRole.CHASER, PlayerRole.KEEPER] and other_player.id != player.id: # also evade teammates who are chasers or keepers to avoid clustering
                    evade_vector = MoveUtility.evade(player.position, other_player.position, weight=self.chaser_evade_teamate_chaser_keeper_weight)
                    total_evade_vector.x += evade_vector.x
                    total_evade_vector.y += evade_vector.y
                    if not other_player.is_knocked_out: # anti evade: keep teammates within passing distance
                        pull_vector = MoveUtility.attract_quadratic(player.position, other_player.position, weight=self.chaser_pull_teammate_chaser_keeper_weight)
                        total_evade_vector.x += pull_vector.x
                        total_evade_vector.y += pull_vector.y
            evade_vectors_dict[player.id] = total_evade_vector
        return evade_vectors_dict

    def position_penalty(self, player: Player) -> float:
        """Pass-to-player score of an attacking chaser/keeper in this step, the lower the better."""
        return self.pass_evaluator.position_penalty(player, self.roster.opponent_hoops, self.evade_vectors.get(player.id, Vector2(0, 0)))

    def player_passing(self, volleyball: VolleyBall, volleyball_holder: Player):
        """
         For each teammate chaser/keeper, which is:
            - not knocked out
            - within passing distance of the volleyball

         calculate position penalty  based on:
            - their squared distance to the closest attack hoop (the closer the better, since they can receive the ball and have a better chance to score or draw opponents when closer to the hoops)
            - their total_evade_vector magnitude (the higher the more pressure on that player, so the less likely we want to pass to them)

        Sort teammates by lowest position penalty. If the lowest score is the volleyball_holder keep the ball. Otherwise, check that the own hoops are not in between and check with beam interception if passing to that teammate is an option.
        """
        if volleyball.is_dead:
            return # don't pass if ball is dead, just try to get it back to life
        position_penalty_dict = {}
        for player_id in self.roster.chaser_keeper_ids:
            player = self.logic.state.players[player_id]
            if player.is_knocked_out:
                continue
            if self.logic.state.squared_distances_ball_player_dicts[volleyball.id][player_id] > self.passing_squared_max_distance:
                continue
            position_penalty_dict[player.id] = self.position_penalty(player)
        sorted_position_penalty = sorted(position_penalty_dict.items(), key=lambda x: x[1])

        # loop through sorted position penalty and pass to the first teammate that has a good enough interception score, if there is no such teammate then keep the ball
        for best_player_id, best_position_penalty in sorted_position_penalty:
            if best_player_id == volleyball_holder.id:
                self.logger.debug("Best player to pass to is current holder %s with position penalty %s, so keeping the ball", best_player_id, best_position_penalty)
                return
            best_player = self.logic.state.players[best_player_id]
            pass_option = self.pass_evaluator.evaluate(volleyball, volleyball_holder, best_player, self.roster.own_hoops, self.roster.opponent_chaser_keeper_ids)
            if pass_option is None:
                continue # unreachable or through own hoops, look for next best player
            if self.pass_evaluator.is_safe(pass_option, self.passing_threshold, strict=True):
                if self.logic.process_action_logic.process_throw_action(volleyball_holder.id, throw_direction=pass_option.throw_direction):
                    self.logger.info("Passing from player %s to player %s with position penalty %s and interception score %s", volleyball_holder.id, best_player_id, best_position_penalty, pass_option.interception_score)
                return

    def solve_assignment_problem(self, player_positions: List[Vector2], target_positions: List[Vector2]):
        """Return minimum-cost assignment permutation using squared-distance cost."""
        if len(player_positions) == 0 or len(target_positions) == 0:
            return [], float('inf')
        best_cost = float('inf')
        best_perm = None
        max_player_index = len(player_positions) - 1
        for perm in itertools.permutations(range(len(target_positions))):
            cost = 0
            for i, player_index in enumerate(perm):
                if player_index > max_player_index: # if there are more target positions than players, some target positions will not be assigned a player
                    continue
                cost += UtilityLogic._squared_distance(player_positions[player_index], target_positions[i])
            if cost < best_cost:
                best_cost = cost
                best_perm = perm
        return list(best_perm), float(best_cost)

    def __call__(self,
                 ctx: StepContext,
                 team: int,
                 controlled_ids: List[str],
                 assigned_beater_ids: List[str]):
        """Execute one diamond-attack tick for the attacking chasers/keepers in `controlled_ids`."""
        self.roster = ctx.rosters[team]
        volleyball = self.logic.state.volleyball
        not_knocked_out_chaser_keeper = [
            player for player in (self.logic.state.players[player_id] for player_id in self.roster.chaser_keeper_ids)
            if not player.is_knocked_out
        ]
        self.move_vectors = self.move_chaser_keeper_hoops(not_knocked_out_chaser_keeper)
        self.evade_vectors = self.evade_vectors_chaser_keeper_calculation()

        next_volleyball_holder_id = ctx.possession.player_id
        controlled_id_set = set(controlled_ids)
        if next_volleyball_holder_id in controlled_id_set:
            if volleyball.holder_id is None:
                self.move_to_volleyball(volleyball, next_volleyball_holder_id, ctx.possession.intercepting_position)
            else: # already hold of volleyball
                volleyball_holder = self.logic.state.players[volleyball.holder_id]
                self.position_player(volleyball_holder) # position volleyball holder to evade opponents while holding the ball
                tries_to_score = self.score_attempter.attempt(volleyball, volleyball_holder, self.roster.opponent_hoops, self.roster.opponent_chaser_keeper_ids)
                if not tries_to_score:
                    self.player_passing(volleyball=volleyball, volleyball_holder=volleyball_holder)
        for player_id in controlled_ids:
            if player_id != next_volleyball_holder_id: # dealing with volleyball holder before
                player = self.logic.state.players[player_id]
                if player.role in [PlayerRole.CHASER, PlayerRole.KEEPER]:
                    # not if knocked out, inbounding, or if keeper and volleyball is dead and in their possession (since in that case they should be trying to get the ball back to life instead of positioning for attack)
                    if not player.is_knocked_out and not player.inbounding and not (player.role == PlayerRole.KEEPER and volleyball.is_dead and volleyball.possession_team == player.team):
                        self.position_player(player)


class DiamondAttackBeater(BaseStrategy):
    """
    Beater part of the attack: making pressure similar to getting bludger control / ready go.

    Beaters move to the volleyball, evade loaded opponent beaters when loaded,
    and throw at loaded opponent beaters in range.
    """
    def __init__(self,
                 logic: GameLogic,
                 beater_throw_decider: BeaterThrowDecider,
                 unloaded_beater_evade_loaded_opponent_beater_weight: float = -3, # if opponent beater is loaded, we want to be closer to them to try to get the ball from them, so negative weight for evade vector, but if they are unloaded then we want to be farther away from them to avoid getting hit, so positive weight for evade vector
                 loaded_beater_evade_loaded_opponent_beater_weight: float = -2,
                 loaded_beater_evade_unloaded_opponent_beater_weight: float = 2,
                 logger: Optional[logging.Logger] = None
                 ):
        """Configure beater pressure weights."""
        super().__init__(logic, logger)
        self.beater_throw_decider = beater_throw_decider
        self.cherry_picker = None # optional CherryPicker, set by the orchestrator
        self.unloaded_beater_evade_loaded_opponent_beater_weight = unloaded_beater_evade_loaded_opponent_beater_weight
        self.loaded_beater_evade_loaded_opponent_beater_weight = loaded_beater_evade_loaded_opponent_beater_weight
        self.loaded_beater_evade_unloaded_opponent_beater_weight = loaded_beater_evade_unloaded_opponent_beater_weight

    def beater_move_action(self, beater: Player, volleyball: VolleyBall, opponent_beater_ids: List[str]):
        """
        Move to volleyball.

        If loaded, evade unloaded opponent beaters.

        Anti-evade towards loaded opponent beaters, the closer the more aggressive towards them.

        Different weights depending on if our beater is loaded.
        """
        move_vector = Vector2(
            volleyball.position.x - beater.position.x,
            volleyball.position.y - beater.position.y
        )
        evade_vectors = []
        if beater.has_ball:
            weight_loaded_opponent_beater = self.loaded_beater_evade_loaded_opponent_beater_weight
        else:
            weight_loaded_opponent_beater = self.unloaded_beater_evade_loaded_opponent_beater_weight
        for opponent_beater_id in opponent_beater_ids:
            opponent_beater = self.logic.state.players[opponent_beater_id]
            if opponent_beater.is_knocked_out:
                continue
            if opponent_beater.has_ball:
                evade_vector = MoveUtility.evade(beater.position, opponent_beater.position, weight=weight_loaded_opponent_beater)
            elif beater.has_ball:
                evade_vector = MoveUtility.evade(beater.position, opponent_beater.position, weight=self.loaded_beater_evade_unloaded_opponent_beater_weight)
            else: # unloaded opponent only matters if beater has ball
                continue
            evade_vectors.append(evade_vector)
        for evade_vector in evade_vectors:
            move_vector.x += evade_vector.x
            move_vector.y += evade_vector.y
        beater.direction = move_vector

    def beater_throw_action(self, beater: Player, roster: TeamRoster):
        """Throw at a loaded opposing beater when the throw policy allows it, otherwise look for a cherry pick."""
        if not beater.has_ball:
            return
        for opponent_beater_id in roster.opponent_beater_ids:
            opponent_beater = self.logic.state.players[opponent_beater_id]
            if opponent_beater.is_knocked_out:
                continue
            if opponent_beater.has_ball:
                if self.beater_throw_decider.should_throw_at_loaded_beater(beater, opponent_beater):
                    # throw at first egligble loaded opponent beater
                    if self.beater_throw_decider.throw_at(self.logic.process_action_logic, beater, opponent_beater):
                        return
                    break
        if self.cherry_picker is not None:
            self.cherry_picker.try_pick(beater, roster, on_attack=True)

    def __call__(self,
                 ctx: StepContext,
                 team: int,
                 controlled_ids: List[str],
                 assigned_beater_ids: List[str]):
        """Move and throw for the attacking beaters in `controlled_ids` not fetching a dodgeball."""
        volleyball = self.logic.state.volleyball
        roster = ctx.rosters[team]
        for player_id in controlled_ids:
            player = self.logic.state.players[player_id]
            if player.role == PlayerRole.BEATER and player.id not in assigned_beater_ids:
                self.beater_move_action(player, volleyball, roster.opponent_beater_ids)
                self.beater_throw_action(player, roster)
