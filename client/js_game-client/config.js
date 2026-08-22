export const Config = {
  CANVAS_WIDTH: 1280,
  CANVAS_HEIGHT: 720,
  PITCH_LENGTH: 60,
  PITCH_WIDTH: 33,
  KEEPER_ZONE_X: 19,
  HOOP_RADIUS: 0.86,
  HOOP_THICKNESS: 0.1,
  PLAYER_RADIUS: 1.6,
  VOLLEYBALL_RADIUS: 0.1,
  DODGEBALL_RADIUS: 0.1,
  FLAG_RUNNER_RADIUS: 0.4,
  // Overwritten from the server's initial_state config payload; this default matches
  // config.py's GAME_TIME_TO_REAL_TIME_RATIO in case a client ever renders before it arrives.
  GAME_TIME_TO_REAL_TIME_RATIO: 3,
  // PLAYER_MAX_SPEED: 3,
  // PLAYER_MIN_DIR: 0.2,
};