import { createApp } from './app.js';
import { SecurityBrain } from './brain.js';
import { config, DEMO_CONNECTIONS } from './config.js';
import { createConnectors } from './connectors/index.js';
import { createAIService } from './services/aiService.js';
import { AutoFixEngine } from './services/autoFix.js';

const brain = new SecurityBrain({
  connectors: createConnectors({ latencyMs: config.connectorLatencyMs }),
  demoConnections: DEMO_CONNECTIONS,
  remediationDelayMs: config.remediationDelayMs,
  tenantName: config.tenantName,
});

await brain.init();

const ai = createAIService({ timeoutMs: config.aiTimeoutMs });
const autoFix = new AutoFixEngine({ brain, stepMs: config.autoFixStepMs });

const app = createApp(brain, { staticDir: config.staticDir, ai, autoFix });
const server = app.listen(config.port, config.host, async () => {
  const { score, grade, open } = brain.riskScore();
  const engine = await ai.status();
  console.log(`Veyra Security Brain API listening on http://${config.host}:${config.port}`);
  console.log(`Seeded demo tenant: score ${score} (${grade}), ${open} open findings`);
  console.log(`AI engine: ${engine.live ? `${engine.label} (${engine.model})` : `rules engine (${engine.reason})`}`);
});

const shutdown = () => {
  brain.close();
  server.close(() => process.exit(0));
};
process.on('SIGINT', shutdown);
process.on('SIGTERM', shutdown);
