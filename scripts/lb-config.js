(function (global) {
  const RTDB = 'https://ai-model-leaderboard-default-rtdb.europe-west1.firebasedatabase.app';

  const LB = global.LB = global.LB || {};
  const overrides = global.LB_CONFIG || {};
  LB.config = {
    configBase: overrides.configBase || '.',
    dataBase:   overrides.dataBase   || RTDB,
    dataMode:   overrides.dataMode   || 'rtdb'
  };
})(typeof window !== 'undefined' ? window : globalThis);
