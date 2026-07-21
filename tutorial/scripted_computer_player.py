import logging
from typing import List

from core.game_logic.game_logic import GameLogic
from core.entities import Vector2, BallType
from computer_player.computer_player import ComputerPlayer, RuleBasedComputerPlayer
from config import Config


class ScriptedComputerPlayer(ComputerPlayer):
    """
    Predictable CPU controller for the tutorial room.

    Behavior is selected by named modes set by the TutorialDirector. The default
    mode keeps every CPU player fully stopped (CPU players have min_dir=0 and
    min_speed=0, so a zero direction halts them completely).
    """

    def __init__(self,
                 game_logic: GameLogic,
                 cpu_player_ids: List[str],
                 computer_player_log_level: int = logging.INFO,
                 **_ignored_kwargs):
        # Swallows Config.COMPUTER_PLAYER_KWARGS passed by the generic room setup.
        super().__init__(game_logic, cpu_player_ids, computer_player_log_level=computer_player_log_level)
        self.mode = 'idle'
        self.mode_kwargs = {}
        self._free_play_delegate = None

    def set_mode(self, mode: str, **kwargs):
        """Switch the scripted behavior mode; kwargs parameterize the mode."""
        self.mode = mode
        self.mode_kwargs = kwargs
        if mode != 'free_play':
            self._free_play_delegate = None
        self.logger.debug("ScriptedComputerPlayer mode set to %s %s", mode, kwargs)

    def make_move(self, dt: float):
        handler = getattr(self, f'_mode_{self.mode}', None)
        if handler is None:
            handler = self._mode_idle
        handler(dt)

    # ---- helpers ----

    def _stop(self, player):
        player.direction.x = 0
        player.direction.y = 0

    def _steer(self, player, x: float, y: float, stop_distance: float = 0.6, speed: float = None) -> bool:
        """
        Steer a player toward (x, y). Returns True once within stop_distance.

        speed: optional 0..1 direction magnitude — sub-1 values make the player
        move slower (steady-state velocity scales with direction magnitude).
        """
        dx = x - player.position.x
        dy = y - player.position.y
        distance = (dx * dx + dy * dy) ** 0.5
        if distance <= stop_distance:
            self._stop(player)
            return True
        if speed is not None and distance > 0:
            player.direction = Vector2(dx / distance * speed, dy / distance * speed)
        else:
            player.direction = Vector2(dx, dy)
        return False

    def _stop_all_except(self, active_ids):
        for player in self.cpu_players:
            if player.id not in active_ids:
                self._stop(player)

    def _get_player(self, player_id):
        return self.logic.state.players.get(player_id)

    # ---- modes ----

    def _mode_idle(self, dt: float):
        for player in self.cpu_players:
            self._stop(player)

    def _mode_hold_positions(self, dt: float):
        """Steer each CPU to its assigned target position; targets: {player_id: (x, y)}."""
        targets = self.mode_kwargs.get('targets', {})
        for player in self.cpu_players:
            target = targets.get(player.id)
            if target is None:
                self._stop(player)
            else:
                self._steer(player, target[0], target[1])

    def _mode_pass_receiver(self, dt: float):
        """One teammate waits at home and catches a volleyball thrown by the trainee."""
        receiver_id = self.mode_kwargs.get('receiver_id')
        trainee_id = self.mode_kwargs.get('trainee_id')
        home = self.mode_kwargs.get('home')
        self._stop_all_except({receiver_id})
        receiver = self._get_player(receiver_id)
        if receiver is None:
            return
        volleyball = self.logic.state.volleyball
        if receiver.has_ball:
            self._stop(receiver)
            return
        thrown_by_trainee = (
            volleyball is not None
            and volleyball.holder_id is None
            and volleyball.previous_thrower_id == trainee_id
        )
        if thrown_by_trainee:
            # Chase the throw (also recovers wayward passes).
            self._steer(receiver, volleyball.position.x, volleyball.position.y, stop_distance=0.1)
        elif home is not None:
            self._steer(receiver, home[0], home[1])
        else:
            self._stop(receiver)

    def _mode_walk_waypoints(self, dt: float):
        """One CPU strolls back and forth along waypoints (used as tackle/beat target)."""
        walker_id = self.mode_kwargs.get('walker_id')
        waypoints = self.mode_kwargs.get('waypoints', [])
        speed = self.mode_kwargs.get('speed', 0.25)  # slow stroll so the trainee can catch/hit them
        self._stop_all_except({walker_id})
        walker = self._get_player(walker_id)
        if walker is None or not waypoints or walker.is_knocked_out:
            return
        index = self.mode_kwargs.get('_index', 0) % len(waypoints)
        x, y = waypoints[index]
        if self._steer(walker, x, y, stop_distance=1.0, speed=speed):
            self.mode_kwargs['_index'] = (index + 1) % len(waypoints)

    def _mode_throw_at_trainee(self, dt: float):
        """One enemy beater hunts the trainee with a dodgeball until the trainee is beaten."""
        beater_id = self.mode_kwargs.get('beater_id')
        trainee_id = self.mode_kwargs.get('trainee_id')
        throw_range = self.mode_kwargs.get('throw_range', 3.0)
        self._stop_all_except({beater_id})
        beater = self._get_player(beater_id)
        trainee = self._get_player(trainee_id)
        if beater is None or trainee is None or beater.is_knocked_out:
            return
        if trainee.is_knocked_out:
            self._stop(beater)
            return
        if beater.has_ball:
            dx = trainee.position.x - beater.position.x
            dy = trainee.position.y - beater.position.y
            if (dx * dx + dy * dy) <= throw_range * throw_range:
                self._stop(beater)
                self.logic.process_action_logic.process_throw_action(beater.id, Vector2(dx, dy))
            else:
                self._steer(beater, trainee.position.x, trainee.position.y, stop_distance=throw_range * 0.8)
        else:
            # Fetch the nearest free dodgeball and try again.
            free_dodgeball = None
            for dodgeball in self.logic.state.dodgeballs:
                if dodgeball.ball_type == BallType.DODGEBALL and dodgeball.holder_id is None:
                    free_dodgeball = dodgeball
                    break
            if free_dodgeball is not None:
                self._steer(beater, free_dodgeball.position.x, free_dodgeball.position.y, stop_distance=0.1)
            else:
                self._stop(beater)

    def _arm(self, player, ball) -> bool:
        """
        Put a free dodgeball straight into a beater's hands.

        The barrage demo keeps its beaters posted at fixed spots, so they never
        walk over to fetch what they threw; scripted re-arming keeps the rhythm
        steady and the keeper zone clear of loitering beaters.
        """
        if ball.holder_id is not None or player.has_ball:
            return False
        ball.holder_id = player.id
        ball.possession_team = player.team
        ball.velocity = Vector2(0, 0)
        ball.previous_thrower_id = None
        ball.position = Vector2(player.position.x, player.position.y)
        ball.previous_position = Vector2(player.position.x, player.position.y)
        player.has_ball = ball.id
        player.catch_cooldown = 0.0
        return True

    def _mode_barrage_trainee(self, dt: float):
        """
        Posted enemy beaters take turns pelting the trainee, one throw per interval.

        Used for the keeper-immunity demo: they hold fire whenever the trainee
        steps out of their keeper zone, so the "you are safe here" promise holds.
        """
        beater_ids = [pid for pid in self.mode_kwargs.get('beater_ids', []) if self._get_player(pid)]
        trainee_id = self.mode_kwargs.get('trainee_id')
        interval = self.mode_kwargs.get('interval', 2.0 * Config.GAME_TIME_TO_REAL_TIME_RATIO)
        self._stop_all_except(set(beater_ids))
        trainee = self._get_player(trainee_id)
        for beater_id in beater_ids:
            self._stop(self._get_player(beater_id))  # they throw from their posts
        if trainee is None or not beater_ids:
            return

        cooldown = self.mode_kwargs.get('_cooldown', 0.0) - dt
        self.mode_kwargs['_cooldown'] = cooldown
        if cooldown > 0 or not trainee.dodgeball_immunity:
            return

        index = self.mode_kwargs.get('_next', 0) % len(beater_ids)
        beater = self._get_player(beater_ids[index])
        if beater is None or beater.is_knocked_out:
            self.mode_kwargs['_next'] = index + 1
            return
        if not beater.has_ball:
            for dodgeball in self.logic.state.dodgeballs:
                if self._arm(beater, dodgeball):
                    break
        if not beater.has_ball:
            return  # every dodgeball still in flight; try again next tick
        self.logic.process_action_logic.process_throw_action(beater.id, Vector2(
            trainee.position.x - beater.position.x,
            trainee.position.y - beater.position.y,
        ))
        self.mode_kwargs['_next'] = index + 1
        self.mode_kwargs['_cooldown'] = interval

    def _mode_score_and_restart(self, dt: float):
        """One enemy chaser carries the volleyball to the hoops and scores."""
        scorer_id = self.mode_kwargs.get('scorer_id')
        hoop_team = self.mode_kwargs.get('hoop_team', 0)
        self._stop_all_except({scorer_id})
        scorer = self._get_player(scorer_id)
        if scorer is None or scorer.is_knocked_out:
            return
        volleyball = self.logic.state.volleyball
        if volleyball is None:
            return
        hoop = self.logic.state.hoops.get(f'hoop_{hoop_team}_center')
        if hoop is None:
            return
        if scorer.has_ball == volleyball.id:
            dx = hoop.position.x - scorer.position.x
            dy = hoop.position.y - scorer.position.y
            if (dx * dx + dy * dy) <= 5.0 * 5.0:
                self._stop(scorer)
                self.logic.process_action_logic.process_throw_action(scorer.id, Vector2(dx, dy))
            else:
                self._steer(scorer, hoop.position.x, hoop.position.y, stop_distance=4.0)
        elif volleyball.holder_id is None and not volleyball.is_dead:
            # Missed shot: fetch the ball and retry.
            self._steer(scorer, volleyball.position.x, volleyball.position.y, stop_distance=0.1)
        else:
            self._stop(scorer)

    def _mode_third_dodgeball_cheat(self, dt: float):
        """
        An enemy beater commits third-dodgeball interference on cue.

        After a short pause they lob their own dodgeball back at their hoops —
        aimed at nobody, so it is no beat attempt — and then walk onto the free
        third dodgeball, which is what triggers the penalty. Had the dumped ball
        been a genuine beat attempt, seizing the third one would have been legal
        until that attempt failed.
        """
        cheater_id = self.mode_kwargs.get('cheater_id')
        delay = self.mode_kwargs.get('delay', 4.0 * Config.GAME_TIME_TO_REAL_TIME_RATIO)
        self._stop_all_except({cheater_id})
        cheater = self._get_player(cheater_id)
        if cheater is None or cheater.is_knocked_out:
            return
        elapsed = self.mode_kwargs.get('_elapsed', 0.0) + dt
        self.mode_kwargs['_elapsed'] = elapsed
        if elapsed < delay:
            self._stop(cheater)
            return
        if cheater.has_ball:
            hoop = self.logic.state.hoops.get(f'hoop_{cheater.team}_center')
            if hoop is None:
                return
            self._stop(cheater)
            self.logic.process_action_logic.process_throw_action(cheater.id, Vector2(
                hoop.position.x - cheater.position.x,
                hoop.position.y - cheater.position.y,
            ))
            return
        # Only the assigned third dodgeball draws the penalty; the ball they
        # just dumped is fair game and must not be picked up by mistake.
        third = self.logic.state.balls.get(self.logic.state.third_dodgeball)
        if third is not None and third.holder_id is None:
            self._steer(cheater, third.position.x, third.position.y, stop_distance=0.1)
        else:
            self._stop(cheater)

    def _mode_free_play(self, dt: float):
        """Graduation free play: delegate to the normal rule-based AI."""
        if self._free_play_delegate is None:
            self._free_play_delegate = RuleBasedComputerPlayer(
                self.logic,
                self.cpu_player_ids,
                computer_player_log_level=self.logger.level,
                **Config.COMPUTER_PLAYER_KWARGS
            )
        self._free_play_delegate.make_move(dt)
