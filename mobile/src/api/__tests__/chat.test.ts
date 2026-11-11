import { QueryClient } from '@tanstack/react-query';

import { storeAnswer, withAnswer, withRating } from '../hooks';
import type { ChatMessage } from '../types';

function message(id: string, role: ChatMessage['role'] = 'user', conversationId = 'c1') {
  return { id, role, text: id, evidenceIds: [], conversationId } as unknown as ChatMessage;
}

const ids = (messages?: ChatMessage[]) => messages?.map((m) => m.id);

// No garbage-collection timers, so Jest can exit as soon as the tests end.
const clients: QueryClient[] = [];
function newClient() {
  const client = new QueryClient({ defaultOptions: { queries: { gcTime: Infinity } } });
  clients.push(client);
  return client;
}
afterEach(() => clients.splice(0).forEach((client) => client.clear()));

describe('adding an answer to a chat', () => {
  it('keeps what was there and adds the new exchange', () => {
    const old = [message('q1'), message('a1', 'assistant')];
    expect(ids(withAnswer(old, [message('q2'), message('a2', 'assistant')]))).toEqual([
      'q1',
      'a1',
      'q2',
      'a2',
    ]);
  });

  it('replaces an edited question and everything after it', () => {
    const old = [
      message('q1'),
      message('a1', 'assistant'),
      message('q2'),
      message('a2', 'assistant'),
    ];
    expect(ids(withAnswer(old, [message('q2b'), message('a2b', 'assistant')], 'q2'))).toEqual([
      'q1',
      'a1',
      'q2b',
      'a2b',
    ]);
  });
});

describe('storing an answer in the cache', () => {
  it('keeps the earlier messages when the latest chat is opened by its id (after a reload)', () => {
    const client = newClient();
    client.setQueryData(['chat', 'latest'], [message('q1'), message('a1', 'assistant')]);
    storeAnswer(client, [message('q2'), message('a2', 'assistant')], 'latest');
    expect(ids(client.getQueryData(['chat', 'c1']))).toEqual(['q1', 'a1', 'q2', 'a2']);
    expect(ids(client.getQueryData(['chat', 'latest']))).toEqual(['q1', 'a1', 'q2', 'a2']);
  });

  it('appends to a chat already open by its id, and never mixes in the latest chat', () => {
    const client = newClient();
    client.setQueryData(['chat', 'latest'], [message('x1', 'user', 'other')]);
    client.setQueryData(['chat', 'c1'], [message('q1')]);
    storeAnswer(client, [message('q2'), message('a2', 'assistant')], 'c1');
    expect(ids(client.getQueryData(['chat', 'c1']))).toEqual(['q1', 'q2', 'a2']);
    expect(ids(client.getQueryData(['chat', 'latest']))).toEqual(['x1']);
  });

  it('starts a new chat with only its first exchange', () => {
    const client = newClient();
    client.setQueryData(['chat', 'latest'], [message('x1', 'user', 'other')]);
    storeAnswer(client, [message('q1', 'user', 'c2'), message('a1', 'assistant', 'c2')], 'new');
    expect(ids(client.getQueryData(['chat', 'c2']))).toEqual(['q1', 'a1']);
  });
});

describe('withRating', () => {
  const chat = [message('q1'), message('a1', 'assistant'), message('a2', 'assistant')];

  it('sets one answer and leaves the rest as they were', () => {
    const rated = withRating(chat, 'a1', 'up');
    expect(rated?.map((m) => m.rating)).toEqual([undefined, 'up', undefined]);
    expect(rated?.[0]).toBe(chat[0]);
    expect(chat[1].rating).toBeUndefined(); // the cached chat is not changed in place
  });

  it('clears a rating with null, and leaves an empty cache empty', () => {
    const rated = withRating(withRating(chat, 'a2', 'down'), 'a2', null);
    expect(rated?.[2].rating).toBeUndefined();
    expect(withRating(undefined, 'a1', 'up')).toBeUndefined();
  });
});
