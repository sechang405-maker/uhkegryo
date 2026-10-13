import { DEMO_SCENARIOS } from './portfolio-demo-fixtures.mjs';

// Opt-in at build time; absent remains live.
export const uiDemoEnabled = process.env.NEXT_PUBLIC_UI_DEMO === '1';
export const DEMO_REQUEST_TEXT = DEMO_SCENARIOS[0].request;
export const DEMO_JOB = DEMO_SCENARIOS[0].job;
