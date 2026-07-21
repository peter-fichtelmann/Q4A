import logging
from typing import List, Optional

from core.entities import Player, Ball, VolleyBall, Vector2, PlayerRole

logger = logging.getLogger('quadball.tutorial')


class TutorialDirector:
    """
    Server-side scenario controller for the tutorial room.

    The client requests a scenario via a `tutorial_step` game-socket message.
    `start_scenario` stages the pitch (teleports entities, hands out balls,
    parks unused CPUs, switches the trainee's role where needed) and configures
    the ScriptedComputerPlayer mode. `tick` runs once per game tick BEFORE
    game_logic.update (so short-lived flags like tackling_player_ids are still
    visible) and returns tutorial_event messages to broadcast.
    """

    def __init__(self, room):
        self.room = room
        self.scenario: Optional[str] = None
        self._phase = 0
        self._baseline = {}
        # Zero the delay-of-game timer every tick (no penalty, no clock icon)
        # except while the delay rule itself is being demonstrated / in free play.
        self.suppress_delay_of_game = True

    # ---- accessors ----

    @property
    def state(self):
        return self.room.game_state

    @property
    def trainee(self) -> Optional[Player]:
        player_id = getattr(self.room, 'creator_player_id', None)
        if player_id is None:
            return None
        return self.state.get_player(player_id)

    def _set_ai(self, mode: str, **kwargs):
        computer_player = self.room.computer_player
        if computer_player is not None and hasattr(computer_player, 'set_mode'):
            computer_player.set_mode(mode, **kwargs)

    def _cpu(self, team: int, role: PlayerRole, exclude=()) -> Optional[Player]:
        for player_id in self.room.cpu_player_ids:
            player = self.state.get_player(player_id)
            if player is not None and player.team == team and player.role == role and player.id not in exclude:
                return player
        return None

    def _cpu_players(self) -> List[Player]:
        players = []
        for player_id in self.room.cpu_player_ids:
            player = self.state.get_player(player_id)
            if player is not None:
                players.append(player)
        return players

    # ---- entity staging helpers ----

    def _teleport(self, entity, x: float, y: float):
        entity.position = Vector2(x, y)
        entity.previous_position = Vector2(x, y)
        entity.velocity = Vector2(0, 0)
        if isinstance(entity, Player):
            entity.direction = Vector2(0, 0)

    def _strip_ball(self, ball: Ball):
        """Release a ball from its holder and null transient possession state."""
        if ball.holder_id is not None:
            holder = self.state.get_player(ball.holder_id)
            if holder is not None and holder.has_ball == ball.id:
                holder.has_ball = False
        if ball.turnover_to_player is not None:
            receiver = self.state.get_player(ball.turnover_to_player)
            if receiver is not None:
                receiver.is_receiving_turnover_ball = False
        # An in-flight inbounding procedure keeps auto-steering the inbounder;
        # cancel it on the player side too.
        for player in self.state.players.values():
            if player.inbounding == ball.id:
                player.inbounding = None
                player.dodgeball_immunity = False
        ball.holder_id = None
        ball.velocity = Vector2(0, 0)
        ball.previous_thrower_id = None
        ball.turnover_to_player = None
        if isinstance(ball, VolleyBall):
            ball.crossed_hoop = None
            ball.inbounder = None
            ball.delay_of_game_timer = 0.0

    def _free_ball(self, ball: Ball, x: float, y: float):
        self._strip_ball(ball)
        self._teleport(ball, x, y)
        ball.possession_team = None
        if isinstance(ball, VolleyBall):
            ball.is_dead = False

    def _give_ball(self, player: Player, ball: Ball, alive: bool = True):
        """Hand a ball to a player, mirroring the possession invariants of game logic."""
        self._strip_ball(ball)
        if player.has_ball:
            other_ball = self.state.get_ball(player.has_ball)
            if other_ball is not None:
                self._strip_ball(other_ball)
        ball.holder_id = player.id
        ball.possession_team = player.team
        player.has_ball = ball.id
        player.catch_cooldown = 0.0
        self._teleport(ball, player.position.x, player.position.y)
        if isinstance(ball, VolleyBall):
            ball.is_dead = not alive

    def _strip_all_balls(self):
        for ball in self.state.balls.values():
            self._strip_ball(ball)

    def _reset_balls_default(self):
        pitch_length = self.state.boundaries_x[1]
        pitch_width = self.state.boundaries_y[1]
        self._free_ball(self.state.volleyball, pitch_length / 2, pitch_width / 2)
        dodgeball_spots = [
            (pitch_length / 2, pitch_width / 4),
            (self.state.keeper_zone_x_0, pitch_width / 2),
            (self.state.keeper_zone_x_1, pitch_width / 2),
        ]
        for dodgeball, spot in zip(self.state.dodgeballs, dodgeball_spots):
            self._free_ball(dodgeball, spot[0], spot[1])

    def _clear_knockouts(self):
        for player in self.state.players.values():
            player.is_knocked_out = False
            player.catch_cooldown = 0.0
            player.tackling_player_ids = []

    def _park_others(self, active_ids=()):
        """Bench every CPU not needed by the current scenario at the pitch edges."""
        pitch_length = self.state.boundaries_x[1]
        pitch_width = self.state.boundaries_y[1]
        bench_index = {0: 0, 1: 0}
        for player in self._cpu_players():
            if player.id in active_ids:
                continue
            index = bench_index[player.team]
            bench_index[player.team] += 1
            if player.team == 0:
                self._teleport(player, 3 + index * 2.5, 2)
            else:
                self._teleport(player, pitch_length - 3 - index * 2.5, pitch_width - 2)

    # ---- role switching ----

    def _role_change_event(self, player: Player) -> dict:
        return {
            "type": "tutorial_event",
            "event": "role_change",
            "player_id": player.id,
            "role": player.role.value,
        }

    def _set_role(self, player: Player, role: PlayerRole):
        old_role = player.role
        if old_role == role:
            return
        if old_role == PlayerRole.KEEPER:
            if player.team == self.state.team_0 and self.state.keeper_team_0 is player:
                self.state.keeper_team_0 = None
            elif player.team == self.state.team_1 and self.state.keeper_team_1 is player:
                self.state.keeper_team_1 = None
        player.role = role
        if role == PlayerRole.KEEPER:
            if player.team == self.state.team_0:
                self.state.keeper_team_0 = player
            else:
                self.state.keeper_team_1 = player
        room_entry = self.room.players.get(player.id)
        if room_entry is not None:
            room_entry["role"] = role.value

    def _swap_trainee_role(self, target_role: PlayerRole) -> List[dict]:
        """Swap roles between the trainee and a same-team CPU so team composition stays valid."""
        trainee = self.trainee
        if trainee is None or trainee.role == target_role:
            return []
        cpu = self._cpu(trainee.team, target_role)
        if cpu is None:
            return []
        old_trainee_role = trainee.role
        self._set_role(trainee, target_role)
        self._set_role(cpu, old_trainee_role)
        logger.info("Tutorial role swap: trainee -> %s, cpu %s -> %s",
                    target_role.value, cpu.id, old_trainee_role.value)
        return [self._role_change_event(trainee), self._role_change_event(cpu)]

    # ---- scenario lifecycle ----

    def start_scenario(self, name: str) -> List[dict]:
        """Stage a named scenario. Returns tutorial_event messages to broadcast."""
        if not self.room.game_started or self.trainee is None:
            return []
        setup = getattr(self, f'_setup_{name}', None)
        if setup is None:
            logger.warning("Unknown tutorial scenario requested: %s", name)
            return []
        self.scenario = name
        self._phase = 0
        self._baseline = {}
        self.suppress_delay_of_game = name not in ('delay_demo', 'free_play')
        self._common_reset()
        events = setup() or []
        logger.info("Tutorial scenario started: %s (room=%s)", name, self.room.room_id)
        return events

    def _retry(self) -> List[dict]:
        """Re-stage the active scenario (e.g. after the practice ball went out of bounds)."""
        name = self.scenario
        setup = getattr(self, f'_setup_{name}')
        self._phase = 0
        self._baseline = {}
        self._common_reset()
        events = setup() or []
        logger.info("Tutorial scenario retried: %s (room=%s)", name, self.room.room_id)
        return events + [{"type": "tutorial_event", "event": "progress", "step": name, "detail": "retry"}]

    def _volleyball_out_of_play(self) -> bool:
        """True when the volleyball left the practice flow (inbounding or turnover started)."""
        volleyball = self.state.volleyball
        if volleyball is None:
            return False
        return volleyball.inbounder is not None or volleyball.turnover_to_player is not None

    def _ball_resting_at_boundary(self, ball: Ball, eps: float = 0.05) -> bool:
        if ball.holder_id is not None:
            return False
        min_x, max_x = self.state.boundaries_x
        min_y, max_y = self.state.boundaries_y
        r = ball.radius
        return (ball.position.x <= min_x + r + eps or ball.position.x >= max_x - r - eps
                or ball.position.y <= min_y + r + eps or ball.position.y >= max_y - r - eps)

    def _common_reset(self):
        self._clear_knockouts()
        if self.state.volleyball is not None:
            self.state.volleyball.delay_of_game_timer = 0.0
        self.state.delay_of_game_warnings = {0: 0, 1: 0}

    def tick(self) -> List[dict]:
        """Evaluate the active scenario's success predicate. Runs before game_logic.update."""
        if self.suppress_delay_of_game and self.state.volleyball is not None:
            self.state.volleyball.delay_of_game_timer = 0.0
        if self.scenario is None:
            return []
        checker = getattr(self, f'_check_{self.scenario}', None)
        if checker is None:
            return []
        try:
            return checker() or []
        except Exception:
            logger.exception("Tutorial scenario check failed: %s", self.scenario)
            return []

    def _success(self, outcome: str = 'default') -> List[dict]:
        """Complete the active scenario. `outcome` lets the client pick an alternative message."""
        step = self.scenario
        self.scenario = None
        self._set_ai('idle')
        return [{"type": "tutorial_event", "event": "success", "step": step, "outcome": outcome}]

    def _progress(self, detail: str) -> dict:
        return {"type": "tutorial_event", "event": "progress", "step": self.scenario, "detail": detail}

    # ---- scenarios ----

    def _setup_idle_all(self):
        events = self._swap_trainee_role(PlayerRole.CHASER)
        self._set_ai('idle')
        return events

    def _own_hoops(self, team: int) -> List:
        return [hoop for hoop in self.state.hoops.values() if hoop.team == team]

    def _setup_hoop_blockage_demo(self):
        events = self._swap_trainee_role(PlayerRole.CHASER)
        trainee = self.trainee
        self._strip_all_balls()
        self._park_others()
        hoops = self._own_hoops(trainee.team)
        if hoops:
            hoop_x = hoops[0].position.x  # all own hoops share the same x
            # Face the hoops from the pitch side, clear of the blockage band.
            approach = 1 if hoop_x < self.state.midline_x else -1
            self._teleport(trainee, hoop_x + approach * 6.0, self.state.boundaries_y[1] / 2)
        self._set_ai('idle')
        return events

    def _check_hoop_blockage_demo(self):
        """Succeed once _enforce_hoop_blockage is pinning the trainee at the band edge."""
        trainee = self.trainee
        volleyball = self.state.volleyball
        if trainee is None or volleyball is None:
            return []
        # Same geometry as BoundaryLogic._enforce_hoop_blockage, which resets the
        # chaser's x to exactly hoop.x +/- margin while they push against it.
        margin = trainee.radius + volleyball.radius
        for hoop in self._own_hoops(trainee.team):
            if (abs(trainee.position.x - hoop.position.x) <= margin + 0.1
                    and abs(trainee.position.y - hoop.position.y) < hoop.radius + trainee.radius):
                return self._success()
        return []

    def _setup_pass_practice(self):
        trainee = self.trainee
        events = self._swap_trainee_role(PlayerRole.CHASER)
        self._strip_all_balls()
        receiver = self._cpu(trainee.team, PlayerRole.CHASER)
        self._park_others({receiver.id} if receiver else ())
        self._teleport(trainee, 24, 16.5)
        self._free_ball(self.state.volleyball, 27, 16.5)
        if receiver is not None:
            self._teleport(receiver, 34, 16.5)
            self._baseline['receiver_id'] = receiver.id
            self._set_ai('pass_receiver', receiver_id=receiver.id, trainee_id=trainee.id, home=(34, 16.5))
        return events

    def _check_pass_practice(self):
        receiver_id = self._baseline.get('receiver_id')
        volleyball = self.state.volleyball
        if receiver_id is not None and volleyball is not None and volleyball.holder_id == receiver_id:
            return self._success()
        if self._volleyball_out_of_play():
            return self._retry()
        return []

    def _setup_scoring_practice(self):
        return self._stage_scoring(behind=False)

    def _setup_scoring_behind_practice(self):
        """Same drill, but the trainee starts on the far side of the hoops."""
        return self._stage_scoring(behind=True)

    def _stage_scoring(self, behind: bool):
        trainee = self.trainee
        events = self._swap_trainee_role(PlayerRole.CHASER)
        self._strip_all_balls()
        self._park_others()
        hoop = self.state.hoops.get(f'hoop_{1 - trainee.team}_center')
        if hoop is None:
            self._teleport(trainee, 40, 16.5)
        elif behind:
            # Deep behind the hoop line, between the hoops and the end boundary.
            pitch_length = self.state.boundaries_x[1]
            x = 55.0 if hoop.position.x > self.state.midline_x else pitch_length - 55.0
            self._teleport(trainee, x, self.state.boundaries_y[1] / 2)
        else:
            # The normal attacking side faces the midline.
            toward_midline = -1 if hoop.position.x > self.state.midline_x else 1
            self._teleport(trainee, hoop.position.x + 6.5 * toward_midline, hoop.position.y)
        self._give_ball(trainee, self.state.volleyball)
        self._baseline['score'] = self.state.score[trainee.team]
        self._set_ai('idle')
        return events

    def _check_scoring_practice(self):
        trainee = self.trainee
        if trainee is not None and self.state.score[trainee.team] > self._baseline.get('score', 0):
            return self._success()
        if self._volleyball_out_of_play():
            return self._retry()
        return []

    def _check_scoring_behind_practice(self):
        return self._check_scoring_practice()

    def _setup_tackle_practice(self):
        trainee = self.trainee
        events = self._swap_trainee_role(PlayerRole.CHASER)
        self._strip_all_balls()
        carrier = self._cpu(1 - trainee.team, PlayerRole.CHASER)
        self._park_others({carrier.id} if carrier else ())
        self._teleport(trainee, 30, 16.5)
        if carrier is not None:
            self._teleport(carrier, 34, 12)
            self._give_ball(carrier, self.state.volleyball)
            self._baseline['carrier_id'] = carrier.id
            self._set_ai('walk_waypoints', walker_id=carrier.id, waypoints=[(34, 21), (34, 12)])
        return events

    def _check_tackle_practice(self):
        trainee = self.trainee
        carrier_id = self._baseline.get('carrier_id')
        if trainee is None or carrier_id is None:
            return []
        # tackling_player_ids is set by the tackle action and cleared inside the
        # next game_logic.update; this tick runs before the update so it is visible.
        if carrier_id in trainee.tackling_player_ids:
            return self._success()
        return []

    def _setup_lineup(self):
        events = self._swap_trainee_role(PlayerRole.CHASER)
        self._strip_all_balls()
        self._reset_balls_default()
        trainee = self.trainee
        self._teleport(trainee, 30, 27)
        role_order = [PlayerRole.KEEPER, PlayerRole.CHASER, PlayerRole.CHASER,
                      PlayerRole.CHASER, PlayerRole.BEATER, PlayerRole.BEATER]
        targets = {}
        used = set()
        for team, line_x in ((trainee.team, 27.0), (1 - trainee.team, 33.0)):
            y = 8.0
            for role in role_order:
                cpu = self._cpu(team, role, exclude=used)
                if cpu is None:
                    continue
                used.add(cpu.id)
                targets[cpu.id] = (line_x, y)
                y += 3.0
        self._set_ai('hold_positions', targets=targets)
        return events

    def _setup_beat_practice(self):
        events = self._swap_trainee_role(PlayerRole.BEATER)
        trainee = self.trainee
        self._strip_all_balls()
        target = self._cpu(1 - trainee.team, PlayerRole.CHASER)
        self._park_others({target.id} if target else ())
        self._teleport(trainee, 30, 16.5)
        if self.state.dodgeballs:
            self._give_ball(trainee, self.state.dodgeballs[0])
            self._baseline['dodgeball_id'] = self.state.dodgeballs[0].id
        if target is not None:
            self._teleport(target, 35, 12)
            self._baseline['target_id'] = target.id
            self._set_ai('walk_waypoints', walker_id=target.id, waypoints=[(35, 21), (35, 12)])
        return events

    def _check_beat_practice(self):
        target = self.state.get_player(self._baseline.get('target_id'))
        if target is not None and target.is_knocked_out:
            return self._success()
        dodgeball = self.state.get_ball(self._baseline.get('dodgeball_id'))
        if dodgeball is not None and self._ball_resting_at_boundary(dodgeball):
            return self._retry()
        return []

    def _setup_get_beaten(self):
        events = self._swap_trainee_role(PlayerRole.CHASER)
        trainee = self.trainee
        self._strip_all_balls()
        beater = self._cpu(1 - trainee.team, PlayerRole.BEATER)
        self._park_others({beater.id} if beater else ())
        self._teleport(trainee, 38, 16.5)
        if beater is not None:
            self._teleport(beater, 52, 16.5)
            if self.state.dodgeballs:
                self._give_ball(beater, self.state.dodgeballs[0])
            # Hold fire until the trainee closes 1 m nearer than the default range.
            self._set_ai('throw_at_trainee', beater_id=beater.id, trainee_id=trainee.id, throw_range=3.0)
        return events

    def _check_get_beaten(self):
        trainee = self.trainee
        if trainee is None:
            return []
        if self._phase == 0:
            if trainee.is_knocked_out:
                self._phase = 1
                self._set_ai('idle')
                return [self._progress('knocked_out')]
        elif not trainee.is_knocked_out:
            return self._success()
        return []

    def _setup_keeper_immunity_demo(self):
        events = self._swap_trainee_role(PlayerRole.KEEPER)
        trainee = self.trainee
        self._strip_all_balls()
        opponent_team = 1 - trainee.team
        beater_1 = self._cpu(opponent_team, PlayerRole.BEATER)
        beater_2 = self._cpu(opponent_team, PlayerRole.BEATER, exclude={beater_1.id} if beater_1 else set())
        beaters = [b for b in (beater_1, beater_2) if b is not None]
        self._park_others({b.id for b in beaters})
        pitch_width = self.state.boundaries_y[1]
        # Deep inside the own keeper zone, with the beaters posted just outside it.
        if trainee.team == self.state.team_0:
            zone_x, outside_x = self.state.keeper_zone_x_0, self.state.keeper_zone_x_0 + 2.5
        else:
            zone_x, outside_x = self.state.keeper_zone_x_1, self.state.keeper_zone_x_1 - 2.5
        self._teleport(trainee, (zone_x + self.state.hoops[f'hoop_{trainee.team}_center'].position.x) / 2, pitch_width / 2)
        for index, beater in enumerate(beaters):
            self._teleport(beater, outside_x, pitch_width / 2 + (2 if index else -2))
            if index < len(self.state.dodgeballs):
                self._give_ball(beater, self.state.dodgeballs[index])
        self._set_ai('barrage_trainee', beater_ids=[b.id for b in beaters], trainee_id=trainee.id)
        return events

    def _setup_goal_restart_demo(self):
        events = self._swap_trainee_role(PlayerRole.KEEPER)
        trainee = self.trainee
        self._strip_all_balls()
        scorer = self._cpu(1 - trainee.team, PlayerRole.CHASER)
        self._park_others({scorer.id} if scorer else ())
        self._teleport(trainee, 10, 11)
        if scorer is not None:
            self._teleport(scorer, 26, 16.5)
            self._give_ball(scorer, self.state.volleyball)
            self._set_ai('score_and_restart', scorer_id=scorer.id, hoop_team=trainee.team)
        self._baseline['opponent_score'] = self.state.score[1 - trainee.team]
        return events

    def _check_goal_restart_demo(self):
        trainee = self.trainee
        volleyball = self.state.volleyball
        if trainee is None or volleyball is None:
            return []
        if self._phase == 0:
            if self.state.score[1 - trainee.team] > self._baseline.get('opponent_score', 0):
                self._phase = 1
                self._set_ai('idle')
                return [self._progress('goal_scored')]
        elif volleyball.holder_id == trainee.id and not volleyball.is_dead:
            return self._success()
        return []

    def _setup_delay_demo(self):
        events = self._swap_trainee_role(PlayerRole.CHASER)
        trainee = self.trainee
        self._strip_all_balls()
        # Park everyone far away so opponent-proximity exemptions cannot cancel the timer.
        self._park_others()
        # Spawn east of the own hoops (x=13.5): a chaser walking toward the midline
        # must never enter the own-hoop blockage band or they get stuck.
        self._teleport(trainee, 17, 16.5)
        self._give_ball(trainee, self.state.volleyball)
        self._set_ai('idle')
        return events

    def _check_delay_demo(self):
        trainee = self.trainee
        volleyball = self.state.volleyball
        if trainee is None or volleyball is None:
            return []
        # The trainee may dawdle long enough to actually concede the penalty:
        # the volleyball is then turned over to an opponent and cannot be
        # recovered, so end the step with the turnover message instead.
        if self._delay_turnover_conceded(trainee, volleyball):
            return self._success(outcome='turnover')
        if self._phase == 0:
            limit = self.state.delay_of_game_time_limit or 15
            if volleyball.delay_of_game_timer > limit * 0.25:
                self._phase = 1
                return [self._progress('delay_ticking')]
        elif trainee.position.x > self.state.midline_x:
            return self._success()
        return []

    def _delay_turnover_conceded(self, trainee: Player, volleyball: VolleyBall) -> bool:
        """True once a delay-of-game penalty has handed the volleyball to the opponents."""
        warnings = self.state.delay_of_game_warnings.get(trainee.team, 0)
        if warnings <= self.state.max_delay_of_game_warnings:
            return False  # no penalty issued yet, only warnings
        if volleyball.turnover_to_player is not None:
            receiver = self.state.get_player(volleyball.turnover_to_player)
            return receiver is not None and receiver.team != trainee.team
        # The designated opponent may already have collected the ball.
        holder = self.state.get_player(volleyball.holder_id) if volleyball.holder_id else None
        return holder is not None and holder.team != trainee.team

    def _setup_oob_demo(self):
        events = self._swap_trainee_role(PlayerRole.CHASER)
        trainee = self.trainee
        self._strip_all_balls()
        self._park_others()
        self._teleport(trainee, 30, 4)
        self._give_ball(trainee, self.state.volleyball)
        self._set_ai('idle')
        return events

    def _check_oob_demo(self):
        volleyball = self.state.volleyball
        if volleyball is not None and volleyball.inbounder is not None:
            return self._success()
        return []

    def _setup_third_dodgeball_demo(self):
        """Both enemy dodgeballs held, the third free and ours — then they grab for it anyway."""
        events = self._swap_trainee_role(PlayerRole.BEATER)
        trainee = self.trainee
        self._strip_all_balls()
        opponent_team = 1 - trainee.team
        cheater = self._cpu(opponent_team, PlayerRole.BEATER)
        partner = self._cpu(opponent_team, PlayerRole.BEATER, exclude={cheater.id} if cheater else set())
        active = {b.id for b in (cheater, partner) if b is not None}
        self._park_others(active)
        # The trainee watches from a distance: the free dodgeball is legally
        # theirs, and collecting it would end the situation before the foul.
        self._teleport(trainee, 4, 16.5)
        if cheater is not None:
            self._teleport(cheater, 34, 4)
            if len(self.state.dodgeballs) > 0:
                self._give_ball(cheater, self.state.dodgeballs[0])
            self._baseline['cheater_id'] = cheater.id
        if partner is not None:
            self._teleport(partner, 42, 20)
            if len(self.state.dodgeballs) > 1:
                self._give_ball(partner, self.state.dodgeballs[1])
        if len(self.state.dodgeballs) > 2:
            self._free_ball(self.state.dodgeballs[2], 35, 25)
        if cheater is not None:
            self._set_ai('third_dodgeball_cheat', cheater_id=cheater.id)
        else:
            self._set_ai('idle')
        return events

    def _check_third_dodgeball_demo(self):
        cheater = self.state.get_player(self._baseline.get('cheater_id'))
        if cheater is None:
            return []
        # The interference penalty sends the offender back to their hoops.
        if cheater.is_knocked_out:
            return self._success()
        if self._phase == 0:
            if not cheater.has_ball:
                self._phase = 1
                return [self._progress('ball_dumped')]
        elif self.state.third_dodgeball is None:
            # Somebody (most likely the trainee) collected the free dodgeball,
            # which legally ends the third-dodgeball situation — stage it again.
            return self._retry()
        return []

    def _setup_free_play(self):
        events = self._swap_trainee_role(PlayerRole.CHASER)
        trainee = self.trainee
        self._strip_all_balls()
        self._reset_balls_default()
        pitch_length = self.state.boundaries_x[1]
        self._teleport(trainee, 8, 16.5)
        offsets = {0: 0, 1: 0}
        for player in self._cpu_players():
            index = offsets[player.team]
            offsets[player.team] += 1
            x = 6 + index * 2.0
            if player.team != trainee.team:
                x = pitch_length - x
            self._teleport(player, x, 8 + (index % 6) * 3.5)
        self._set_ai('free_play')
        self.scenario = None
        return events
