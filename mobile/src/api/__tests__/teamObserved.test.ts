import { httpClient } from '../http';
import { DEMO_OWNER, DEMO_SUPERVISOR, mockClient } from '../mock';
import { saveToken } from '../token';

// Observed team figures: the route the backend serves, and the mock's contract.

const realFetch = globalThis.fetch;
afterEach(async () => {
  globalThis.fetch = realFetch;
  await saveToken(null);
});

it('calls the backend route', async () => {
  const calls: string[] = [];
  globalThis.fetch = jest.fn(async (url: string) => {
    calls.push(url.replace('http://api.test', ''));
    return new Response(JSON.stringify({ figures: [], minimumMembers: 5 }), { status: 200 });
  }) as unknown as typeof fetch;
  await httpClient('http://api.test', mockClient).getTeamObserved('t 1');
  expect(calls).toEqual(['/teams/t%201/observed']);
});

it('gives a supervisor sentences from five people or more, and nobody else', async () => {
  await saveToken((await mockClient.logIn(DEMO_SUPERVISOR)).token);
  const team = await mockClient.createTeam('Design');
  const observed = await mockClient.getTeamObserved(team.id);
  expect(observed.figures.length).toBeGreaterThan(0);
  for (const figure of observed.figures) {
    expect(figure.members).toBeGreaterThanOrEqual(observed.minimumMembers);
    expect(figure.text).toMatch(/^Median .+, based on \d+ members\.$/);
    expect(figure.text).not.toMatch(/usual|fell|rose|higher|lower/);
  }
  await saveToken((await mockClient.logIn(DEMO_OWNER)).token);
  await expect(mockClient.getTeamObserved(team.id)).rejects.toMatchObject({ status: 403 });
});
