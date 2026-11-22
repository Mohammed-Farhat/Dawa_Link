import { API_URL } from './address'
import {
  ApiFailure,
  failureFrom,
  getToken,
  type Schemas,
  sessionEnded,
  UNAUTHENTICATED,
  UNREACHABLE,
} from './client'

// A chat message's answer arrives as a short stream of events (docs/06 §6.6.1):
// progress lines while the agent works, then the complete, already-checked reply.
// It is a POST with the login header, so the browser's own EventSource can't be used:
// the stream is read with fetch.

export type ChatEvent =
  | { name: 'turn_started'; data: { client_message_seq: number } }
  | { name: 'progress'; data: { label: string } }
  | { name: 'message'; data: Schemas['ChatMessage'] }
  | { name: 'turn_completed'; data: { agent_message_seq: number | null; outcome: string } }
  | { name: 'error'; data: { error: { code: string; details?: Record<string, unknown> }; status?: number } }

/**
 * The stream of an answer broke before its end. **The message was kept**: the API stores
 * it before the stream opens, and the agent's turn runs on without anyone listening. Its
 * reply arrives by the page's polling (A#12, docs/09 FX-16), so this is not a refusal.
 */
export class StreamDropped extends Error {
  constructor() {
    super('The answer stream ended early')
    this.name = 'StreamDropped'
  }
}

/** One block of the stream ("event: …" and "data: …" lines), or null for a heartbeat. */
export function parseEvent(block: string): ChatEvent | null {
  let name = ''
  let data = ''
  for (const line of block.split('\n')) {
    if (line.startsWith('event: ')) name = line.slice('event: '.length)
    if (line.startsWith('data: ')) data += line.slice('data: '.length)
  }
  if (!name || !data) return null
  return { name, data: JSON.parse(data) } as ChatEvent
}

/**
 * Sends a message in a conversation and reports each event of the answer.
 *
 * In a chat the answer is the stream. In a request's thread the API answers at once
 * (202) and the reply arrives later by polling: then no event is reported.
 *
 * - Throws an `ApiFailure` when the message was refused: **nothing was stored**.
 * - Throws `StreamDropped` when the answer's stream broke after it opened: the message
 *   **was** stored. An `error` event inside the stream also comes after the message was
 *   stored.
 */
export async function sendMessage(
  conversationId: string,
  text: string,
  clientMessageId: string,
  onEvent: (event: ChatEvent) => void,
): Promise<void> {
  const token = getToken()
  let response: Response
  try {
    response = await globalThis.fetch(
      `${API_URL}/api/v1/conversations/${conversationId}/messages`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token ?? ''}`,
        },
        body: JSON.stringify({ text, client_message_id: clientMessageId }),
      },
    )
  } catch {
    throw new ApiFailure(UNREACHABLE, 0)
  }
  if (!response.ok) {
    const failure = failureFrom(await response.json().catch(() => null), response.status)
    // This call bypasses the API client, so it ends the session the same way (A#11).
    if (failure.code === UNAUTHENTICATED) sessionEnded(token)
    throw failure
  }
  if (!response.headers.get('Content-Type')?.startsWith('text/event-stream') || !response.body) {
    return
  }
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let waiting = ''
  // The last event of an answer: its reply, or why there is none.
  let finished = false
  for (;;) {
    let chunk: ReadableStreamReadResult<Uint8Array>
    try {
      chunk = await reader.read()
    } catch {
      throw new StreamDropped()
    }
    const { done, value } = chunk
    waiting += decoder.decode(value, { stream: !done })
    const blocks = waiting.split('\n\n')
    waiting = blocks.pop() ?? ''
    for (const block of blocks) {
      const event = parseEvent(block)
      if (!event) continue
      if (event.name === 'turn_completed' || event.name === 'error') finished = true
      onEvent(event)
    }
    if (done) {
      // A stream closed before its last event (a proxy that cut it) is a dropped one.
      if (!finished) throw new StreamDropped()
      return
    }
  }
}
