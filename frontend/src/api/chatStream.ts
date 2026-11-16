import { API_URL } from './address'
import { ApiFailure, failureFrom, getToken, type Schemas, UNREACHABLE } from './client'

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
 * Throws an `ApiFailure` when the message was refused.
 */
export async function sendMessage(
  conversationId: string,
  text: string,
  clientMessageId: string,
  onEvent: (event: ChatEvent) => void,
): Promise<void> {
  let response: Response
  try {
    response = await globalThis.fetch(
      `${API_URL}/api/v1/conversations/${conversationId}/messages`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${getToken() ?? ''}`,
        },
        body: JSON.stringify({ text, client_message_id: clientMessageId }),
      },
    )
  } catch {
    throw new ApiFailure(UNREACHABLE, 0)
  }
  if (!response.ok) {
    throw failureFrom(await response.json().catch(() => null), response.status)
  }
  if (!response.headers.get('Content-Type')?.startsWith('text/event-stream') || !response.body) {
    return
  }
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let waiting = ''
  for (;;) {
    const { done, value } = await reader.read()
    waiting += decoder.decode(value, { stream: !done })
    const blocks = waiting.split('\n\n')
    waiting = blocks.pop() ?? ''
    for (const block of blocks) {
      const event = parseEvent(block)
      if (event) onEvent(event)
    }
    if (done) return
  }
}
