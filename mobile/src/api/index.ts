import { httpClient } from './http';
import { mockClient } from './mock';
import type { ApiClient } from './types';

// Set EXPO_PUBLIC_API_URL to use the real backend; without it the app runs on mock data.
// Endpoints the backend does not serve yet keep using the mock.
const apiUrl = process.env.EXPO_PUBLIC_API_URL;

export const api: ApiClient = apiUrl ? httpClient(apiUrl, mockClient) : mockClient;
export const usingMock = !apiUrl;
// Where a harness (Claude Code, Codex) connects to Patterns over MCP (docs/mcp.md).
export const mcpUrl = apiUrl ? `${apiUrl.replace(/\/$/, '')}/mcp/` : 'https://<your Patterns API>/mcp/';

export type * from './types';
