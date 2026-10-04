import { createApp } from './app.js';
import { SecurityBrain } from './brain.js';
import { config, DEMO_CONNECTIONS } from './config.js';
import { createConnectors } from './connectors/index.js';

const brain = new SecurityBrain({
  connectors: createConnectors({ latencyMs: config.connectorLatencyMs }),
  demoConnections: DEMO_CONNECTIONS,
  remediationDelayMs: config.remediationDelayMs,
});

await brain.init();

const app = createApp(brain, { staticDir: config.staticDir });
const server = app.listen(config.port, config.host, () => {
  const { score, grade, open } = brain.riskScore();
  console.log(`Veyra Security Brain API listening on http://${config.host}:${config.port}`);
  console.log(`Seeded demo tenant: score ${score} (${grade}), ${open} open findings`);
});

const shutdown = () => {
  brain.close();
  server.close(() => process.exit(0));
};
process.on('SIGINT', shutdown);
process.on('SIGTERM', shutdown);
