import { useQuery, useQueryClient } from '@tanstack/react-query'
import { type FormEvent, type ReactNode, useEffect, useRef, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'

import { type ChatEvent, sendMessage } from '../../../api/chatStream'
import { api, ApiFailure, newKey, type Schemas, unwrap } from '../../../api/client'
import { useSession } from '../../../api/session'
import { BackIcon, PinIcon, PlusIcon, SendIcon } from '../../../components/icons'
import { Banner, Screen } from '../../../components/layout'
import { errorMessage, strings } from '../../../strings/en'
import { usePublicConfig } from '../data'
import { UnverifiedBanner } from '../HomePage'
import { MessageCards } from './Cards'
import { LocationSheet } from './LocationSheet'

const s = strings.chat

type Card = Schemas['Card']
type Notice = { tone: 'green' | 'red' | 'amber'; text: string }

const BUSY_TRIES = 5
// These mean the message was not kept: it goes back into the box (docs/11 §7).
const NOT_STORED = new Set(['UNREACHABLE', 'ASSISTANT_UNAVAILABLE', 'TOKEN_BUDGET_EXCEEDED', 'RATE_LIMITED'])

function wait(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

function locationLabel(location: Schemas['LocationSummary']): string | null {
  if (location.source === 'none') return null
  if (location.source === 'shared') return s.location.yours
  if (location.source === 'profile' && location.label) return s.location.home(location.label)
  return location.label ?? null
}

/** CS-9: the assistant. It needs a confirmed email (R-AU5). */
export function AssistantPage() {
  const { me } = useSession()
  const verified = Boolean(me?.email_verified)
  const chat = useQuery({
    queryKey: ['active-chat'],
    queryFn: () => unwrap(api.GET('/api/v1/conversations/active-chat')),
    enabled: verified,
    retry: false,
  })

  if (!verified) {
    return (
      <Screen>
        <h1 className="page-title">{s.title}</h1>
        <UnverifiedBanner />
      </Screen>
    )
  }
  if (chat.isError) {
    const code = chat.error instanceof ApiFailure ? chat.error.code : 'INTERNAL_ERROR'
    return (
      <Screen>
        <h1 className="page-title">{s.title}</h1>
        <Banner tone="red" alert>
          {errorMessage(code)}
        </Banner>
      </Screen>
    )
  }
  if (!chat.data) {
    return (
      <Screen>
        <p className="soft">{strings.common.loading}</p>
      </Screen>
    )
  }
  return <Conversation key={chat.data.conversation_id} conversationId={chat.data.conversation_id} />
}

/**
 * One conversation: its messages, the box to write in, and the cards' taps.
 *
 * - A reply arrives **whole**, after the server's checks; while the agent works, a
 *   progress line shows its step (docs/11 §6, rule 1).
 * - The page asks for new messages every few seconds while it is visible, so what the
 *   worker posts later (a pharmacy marked a box not available) appears by itself.
 * - The agent's text is shown as plain text: React never treats it as HTML.
 *
 * The same component is the chat and a request's thread (`thread`). In a thread the
 * worker answers, so the reply arrives by polling; the request's own page stands above
 * the messages; and the location can't be changed (it was fixed when the request
 * started, R-RQ4).
 */
export type ThreadFrame = {
  title: string
  subtitle: string
  backTo: string
  above: ReactNode
  /** False once the request is closed: there is nobody to write to any more. */
  canWrite: boolean
}

export function Conversation({
  conversationId,
  thread,
}: {
  conversationId: string
  thread?: ThreadFrame
}) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const config = usePublicConfig()
  const pollMs = (config.data?.poll_every_s ?? 3) * 1000
  const maxChars = config.data?.max_message_chars ?? 1000
  const page = useQuery({
    queryKey: ['messages', conversationId],
    queryFn: () =>
      unwrap(
        api.GET('/api/v1/conversations/{conversation_id}/messages', {
          params: { path: { conversation_id: conversationId } },
        }),
      ),
    // Only while the page is visible (N-28): a hidden tab asks for nothing.
    refetchInterval: pollMs,
    refetchIntervalInBackground: false,
  })

  const { state } = useLocation() as { state: { draft?: string } | null }
  const [draft, setDraft] = useState(state?.draft ?? '')
  const [pending, setPending] = useState<string | null>(null)
  // The newest message when the client pressed send: what came after is theirs.
  const [pendingAfter, setPendingAfter] = useState(0)
  const [progress, setProgress] = useState<string | null>(null)
  const [notice, setNotice] = useState<Notice | null>(null)
  const [degraded, setDegraded] = useState(false)
  const [acting, setActing] = useState(false)
  const [choosingPlace, setChoosingPlace] = useState(false)
  // In a thread: the newest message when the client wrote. The agent's answer is the
  // first of its messages after it.
  const [awaitingAfter, setAwaitingAfter] = useState<number | null>(null)
  const end = useRef<HTMLDivElement>(null)

  const messages = page.data?.messages ?? []
  const last = messages[messages.length - 1]
  const answered =
    awaitingAfter === null ||
    messages.some((message) => message.author === 'agent' && message.seq > awaitingAfter)
  const working = pending !== null || Boolean(page.data?.busy) || !answered
  // A poll during the turn already brought the client's own message back.
  const stored = messages.some((message) => message.author === 'client' && message.seq > pendingAfter)

  useEffect(() => {
    end.current?.scrollIntoView?.({ block: 'end' })
  }, [messages.length, pending, progress])

  // A worker that is slow or switched off must not leave "Working on it…" forever.
  useEffect(() => {
    if (awaitingAfter === null) return
    const timer = setTimeout(() => setAwaitingAfter(null), 90_000)
    return () => clearTimeout(timer)
  }, [awaitingAfter])

  useEffect(() => {
    if (!notice) return
    const timer = setTimeout(() => setNotice(null), 6000)
    return () => clearTimeout(timer)
  }, [notice])

  function refused(code: string, text: string) {
    if (NOT_STORED.has(code)) setDraft(text)
    if (code === 'ASSISTANT_UNAVAILABLE') setDegraded(true)
    else setNotice({ tone: 'red', text: errorMessage(code) })
  }

  async function send(raw: string) {
    const text = raw.trim()
    if (!text || pending !== null) return
    if (text.length > maxChars) {
      setNotice({ tone: 'red', text: s.tooLong(maxChars) })
      return
    }
    // The same ID on every retry: the server stores the message once (docs/06 §6.6).
    const messageId = newKey()
    const newest = page.data?.last_seq ?? 0
    setPendingAfter(newest)
    setPending(text)
    setDraft('')
    setNotice(null)
    try {
      for (let attempt = 0; attempt < BUSY_TRIES; attempt += 1) {
        let failure: { code: string; details?: Record<string, unknown> } | null = null
        try {
          await sendMessage(conversationId, text, messageId, (event: ChatEvent) => {
            if (event.name === 'progress') setProgress(event.data.label)
            if (event.name === 'error') failure = event.data.error
          })
        } catch (error) {
          failure =
            error instanceof ApiFailure
              ? { code: error.code, details: error.details }
              : { code: 'INTERNAL_ERROR' }
        }
        const found = failure as { code: string; details?: Record<string, unknown> } | null
        if (found === null) {
          setDegraded(false)
          if (thread) setAwaitingAfter(newest)
          break
        }
        if (found.code === 'CONVERSATION_BUSY' && attempt < BUSY_TRIES - 1) {
          // The agent is already working here: wait, then send again (API-D8).
          setProgress(s.oneMoment)
          await wait(Number(found.details?.retry_after_ms ?? 2000))
          continue
        }
        refused(found.code, text)
        break
      }
    } finally {
      await page.refetch()
      setPending(null)
      setProgress(null)
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault()
    void send(draft)
  }

  /** A tap on an agent card: only the card's ID is sent, and the server checks everything. */
  async function act(card: Card, selectedItemKeys: string[] | null) {
    setActing(true)
    setNotice(null)
    try {
      const done = await unwrap(
        api.POST('/api/v1/proposals/{proposal_id}/execute', {
          params: { path: { proposal_id: card.card_id }, header: { 'Idempotency-Key': newKey() } },
          body: { selected_item_keys: selectedItemKeys },
        }),
      )
      setNotice({ tone: 'green', text: done.message })
      await Promise.all(
        ['reservations', 'requests', 'request', 'offers'].map((key) =>
          queryClient.invalidateQueries({ queryKey: [key] }),
        ),
      )
      // [Start sourcing]: the request has a page of its own, with its thread (BLD-D30).
      if (done.request_id && !thread) navigate(`/requests/${done.request_id}`)
    } catch (error) {
      const code = error instanceof ApiFailure ? error.code : 'INTERNAL_ERROR'
      setNotice({ tone: 'red', text: errorMessage(code) })
    } finally {
      await page.refetch()
      setActing(false)
    }
  }

  async function startNewChat() {
    const fresh = await unwrap(api.POST('/api/v1/conversations/new-chat')).catch(() => null)
    if (fresh) queryClient.setQueryData(['active-chat'], fresh)
  }

  return (
    <div className="chat">
      <header className="chat__header">
        <Link to={thread?.backTo ?? '/'} className="round-button" aria-label={strings.common.back}>
          <BackIcon />
        </Link>
        <span className="chat__mark" aria-hidden="true">
          D
        </span>
        <div className="chat__names">
          <h1 className="chat__title">{thread?.title ?? s.title}</h1>
          <span className="chat__subtitle">{thread?.subtitle ?? s.subtitle}</span>
        </div>
        {!thread && (
          <button
            type="button"
            className="round-button round-button--grey"
            aria-label={s.newChat}
            onClick={() => void startNewChat()}
          >
            <PlusIcon small />
          </button>
        )}
      </header>

      {/* Always visible, and it can't be dismissed (UI-D14). */}
      <div className="chat__notice">
        <span>{s.aiNotice}</span>
        {page.data && !thread && (
          <button type="button" className="chat__location" onClick={() => setChoosingPlace(true)}>
            <PinIcon small />
            {s.location.button(locationLabel(page.data.location))}
          </button>
        )}
      </div>

      <div className="chat__messages" aria-live="polite">
        {degraded && <Banner tone="amber">{strings.banner.degraded}</Banner>}
        {page.isError && <Banner tone="amber">{strings.banner.offline}</Banner>}
        {thread?.above}
        {page.isSuccess && messages.length === 0 && pending === null && !thread && (
          <div className="empty">
            <span>{s.empty}</span>
            <div className="chips">
              {s.emptyExamples.map((example) => (
                <button key={example} type="button" className="chip" dir="auto" onClick={() => void send(example)}>
                  {example}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((message) => (
          <MessageView key={message.seq} message={message} busy={acting} onAct={act} />
        ))}
        {pending !== null && !stored && (
          <p className="bubble bubble--mine bubble--waiting" dir="auto">
            {pending}
          </p>
        )}
        {working && <div className="progress-line">{progress ?? s.working}</div>}

        {!working && last?.author === 'agent' && last.quick_replies.length > 0 && (
          <div className="chips" role="group" aria-label={s.quickReplies}>
            {last.quick_replies.map((chip) => (
              <button key={chip} type="button" className="chip" dir="auto" onClick={() => void send(chip)}>
                {chip}
              </button>
            ))}
          </div>
        )}
        {notice && (
          <Banner tone={notice.tone} alert={notice.tone === 'red'}>
            {notice.text}
          </Banner>
        )}
        <div ref={end} />
      </div>

      <form className="chat__form" onSubmit={submit} hidden={thread ? !thread.canWrite : false}>
        <label htmlFor="chat-message" className="sr-only">
          {s.messageLabel}
        </label>
        <input
          id="chat-message"
          className="chat__input"
          type="text"
          dir="auto"
          autoComplete="off"
          placeholder={s.placeholder}
          value={draft}
          onChange={(event) => setDraft(event.currentTarget.value)}
        />
        <button
          type="submit"
          className="chat__send"
          aria-label={s.send}
          disabled={!draft.trim() || pending !== null}
        >
          <SendIcon />
        </button>
      </form>

      <LocationSheet
        opened={choosingPlace}
        onClose={() => setChoosingPlace(false)}
        onChoose={async (place) => {
          await unwrap(
            api.PUT('/api/v1/conversations/{conversation_id}/location', {
              params: { path: { conversation_id: conversationId } },
              body: 'lat' in place ? place : { district_id: place.district_id },
            }),
          )
          await page.refetch()
        }}
      />
    </div>
  )
}

function MessageView({
  message,
  busy,
  onAct,
}: {
  message: Schemas['ChatMessage']
  busy: boolean
  onAct: (card: Card, selectedItemKeys: string[] | null) => void
}) {
  const mine = message.author === 'client'
  return (
    <>
      {message.text && (
        // dir="auto": Arabic runs right to left, Arabizi and English left to right.
        <p className={`bubble ${mine ? 'bubble--mine' : 'bubble--theirs'}`} dir="auto">
          {message.text}
        </p>
      )}
      {message.cards.length > 0 && <MessageCards cards={message.cards} busy={busy} onAct={onAct} />}
    </>
  )
}
