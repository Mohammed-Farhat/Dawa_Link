import { Modal } from '@mantine/core'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { type FormEvent, type ReactNode, useEffect, useRef, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'

import { type ChatEvent, sendMessage, StreamDropped } from '../../../api/chatStream'
import { api, ApiFailure, newKey, type Schemas, unwrap } from '../../../api/client'
import { useSession } from '../../../api/session'
import { BackIcon, HistoryIcon, PinIcon, PlusIcon, SendIcon } from '../../../components/icons'
import { Banner, Screen, Shell } from '../../../components/layout'
import { useWide } from '../../../components/wide'
import { beirutHour, dayAndClock, dayWord, langOf } from '../../../format'
import { errorMessage, strings } from '../../../strings/en'
import { type Failure, failureMessage } from '../../../strings/failure'
import { usePublicConfig } from '../data'
import { UnverifiedBanner } from '../HomePage'
import { MessageCards, type OffersKnown } from './Cards'
import { LocationSheet } from './LocationSheet'
import { ReportAnswer } from './ReportAnswer'

const s = strings.chat

type Card = Schemas['Card']
type Notice = { tone: 'green' | 'red' | 'amber'; text: string }

/** How often a message refused as busy is sent again, with "One moment…" meanwhile: at
 * the API's 2 s, about 30 s. A message is also refused as busy while every one of the
 * server's agent turns is taken, and a turn may last that long. */
const BUSY_TRIES = 15
// A green notice ("Reserved") may fade; a red or amber one is the only explanation of
// what failed, so it stays until the next send or tap, or until it is closed (B#35).
const GREEN_NOTICE_MS = 6000

/** How a send ended. `kept`: the API stored the message, whatever came after. */
type Sent =
  | { outcome: 'answered'; withTeam: boolean }
  | { outcome: 'dropped' }
  | { outcome: 'refused'; failure: Failure; kept: boolean }

function wait(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

function locationLabel(location: Schemas['LocationSummary']): string | null {
  if (location.source === 'none') return null
  if (location.source === 'shared') return s.location.yours
  if (location.source === 'place') return s.location.savedPlace
  if (location.source === 'profile' && location.label) return s.location.home(location.label)
  // Named in this chat as where the client is: it never changes the saved place.
  if (location.source === 'area' && location.label) return s.location.named(location.label)
  return location.label ?? null
}

/** CS-9: the assistant. It needs a confirmed email (R-AU5).
 *
 * The assistant has a page of its own, opened from [Ask DawaLink] (the owner, 2026-11-18,
 * BLD-D42: no panel beside the other pages). On it the client also finds their earlier
 * chats (D9: kept 30 days): a list beside the conversation on a computer, behind a
 * button on a phone. An earlier chat is read, never continued. */
export function AssistantPage() {
  const { me } = useSession()
  const wide = useWide()
  const Frame = Screen
  // The earlier chat being read, or null for the chat the client writes in now.
  const [reading, setReading] = useState<string | null>(null)
  const [listOpen, setListOpen] = useState(false)
  const verified = Boolean(me?.email_verified)
  const chat = useQuery({
    queryKey: ['active-chat'],
    queryFn: () => unwrap(api.GET('/api/v1/conversations/active-chat')),
    enabled: verified,
    retry: false,
  })

  if (!verified) {
    return (
      <Frame>
        <h1 className="page-title">{s.title}</h1>
        <UnverifiedBanner />
      </Frame>
    )
  }
  if (chat.isError) {
    const code = chat.error instanceof ApiFailure ? chat.error.code : 'INTERNAL_ERROR'
    return (
      <Frame>
        <h1 className="page-title">{s.title}</h1>
        <Banner tone="red" alert>
          {errorMessage(code)}
        </Banner>
      </Frame>
    )
  }
  if (!chat.data) {
    return (
      <Frame>
        <p className="soft">{strings.common.loading}</p>
      </Frame>
    )
  }
  const current = chat.data.conversation_id
  const shown = reading ?? current
  const list = (
    <ChatList
      current={current}
      shown={shown}
      titled={wide}
      onOpen={(id) => {
        setReading(id === current ? null : id)
        setListOpen(false)
      }}
    />
  )
  const conversation = (
    <Conversation
      key={shown}
      conversationId={shown}
      framed={wide}
      earlier={reading !== null ? { onBack: () => setReading(null) } : undefined}
      onNewChat={() => setReading(null)}
      tools={
        wide ? null : (
          <button
            type="button"
            className="chat__tool"
            aria-label={s.history}
            onClick={() => setListOpen(true)}
          >
            <HistoryIcon small />
          </button>
        )
      }
    />
  )
  if (wide) {
    return (
      <Shell>
        <aside className="wide__chats" aria-label={s.chats}>
          {list}
        </aside>
        <div className="wide__chat">{conversation}</div>
      </Shell>
    )
  }
  return (
    <>
      {conversation}
      <Modal opened={listOpen} onClose={() => setListOpen(false)} title={s.chats} centered radius="xl">
        {list}
      </Modal>
    </>
  )
}

/** The client's chats, the newest first: the one they write in, then the earlier ones. */
function ChatList({
  current,
  shown,
  onOpen,
  titled = true,
}: {
  current: string
  shown: string
  onOpen: (conversationId: string) => void
  /** False in the phone's sheet, whose own title already says "Your chats". */
  titled?: boolean
}) {
  const chats = useQuery({
    queryKey: ['chats', current],
    queryFn: () => unwrap(api.GET('/api/v1/conversations/chats')),
  })
  const items = chats.data?.items ?? []
  return (
    <>
      {titled && <h2 className="section-title">{s.chats}</h2>}
      <ul className="chat-list">
        {items.map((chat) => (
          <li key={chat.conversation_id}>
            <button
              type="button"
              className="chat-list__item"
              aria-current={chat.conversation_id === shown ? 'true' : undefined}
              onClick={() => onOpen(chat.conversation_id)}
            >
              <span className="chat-list__title" dir="auto" lang={langOf(chat.title)}>
                {chat.title ?? s.untitled}
              </span>
              <span className="hint">
                {chat.active
                  ? s.current
                  : dayWord(chat.last_activity_at, chats.data?.server_now ?? chat.last_activity_at)}
              </span>
            </button>
          </li>
        ))}
      </ul>
      <span className="hint">{s.chatsHint}</span>
    </>
  )
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
  framed = false,
  earlier,
  onNewChat,
  tools,
}: {
  conversationId: string
  thread?: ThreadFrame
  /** Under the top bar of a computer: the bar is the way back. */
  framed?: boolean
  /** An earlier chat: it is read, and this is the way back to the current one. */
  earlier?: { onBack: () => void }
  onNewChat?: () => void
  /** More buttons for the header: the list of chats, on a phone. */
  tools?: ReactNode
}) {
  const queryClient = useQueryClient()
  // The chat's own page on a phone.
  const compact = !thread && !framed
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
  // The answer's stream dropped after the message was kept: its reply comes by polling.
  const [dropped, setDropped] = useState(false)
  // A message the API refused before keeping it, with its ID: sent again unchanged, it
  // carries the same ID, so the API never keeps it twice (A#12, docs/06 §6.6).
  const unsent = useRef<{ text: string; id: string } | null>(null)
  const end = useRef<HTMLDivElement>(null)

  const messages = page.data?.messages ?? []
  const last = messages[messages.length - 1]
  // Said in the chat too (docs/11 §4): a client who asks the assistant to keep looking at
  // night, or while paused, should know before asking. The hour is the app's own
  // (`server_now`), never this device's: the demo clock moves it.
  const { me } = useSession()
  const paused = me?.client?.status === 'PAUSED'
  const hour = page.data ? beirutHour(new Date(page.data.server_now)) : null
  const opens = Number(config.data?.request_hours_start.slice(0, 2) ?? 8)
  const closes = Number(config.data?.request_hours_end.slice(0, 2) ?? 20)
  const night = hour !== null && (hour < opens || hour >= closes)
  const answered =
    awaitingAfter === null ||
    messages.some((message) => message.author === 'agent' && message.seq > awaitingAfter)
  const working = pending !== null || Boolean(page.data?.busy) || !answered
  // DawaLink's team has this chat (the owner, 2026-11-22): what the client writes goes to
  // the team, and the assistant answers again when the team closes the case. Nothing here
  // says the assistant is working, and its quick replies are not offered.
  const withTeam = Boolean(page.data?.with_team) && !earlier
  // The box to write in: never under an earlier chat or a closed request.
  const writable = thread ? thread.canWrite : !earlier && !page.data?.archived
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
    if (notice?.tone !== 'green') return
    const timer = setTimeout(() => setNotice(null), GREEN_NOTICE_MS)
    return () => clearTimeout(timer)
  }, [notice])

  /** A refused message. Kept by the API (the refusal came inside the answer's stream):
   * it is in the thread, and is not put back in the box, or a resend would store it
   * twice. Not kept: it goes back in the box, and keeps its ID for a resend (A#12). */
  function refused(failure: Failure, text: string, messageId: string, kept: boolean) {
    if (!kept) {
      unsent.current = { text, id: messageId }
      // Never over words the client started to type meanwhile.
      setDraft((typed) => typed || text)
    }
    if (failure.code === 'ASSISTANT_UNAVAILABLE') setDegraded(true)
    // Still busy after every try: "One moment…" would promise an answer that isn't coming.
    else if (failure.code === 'CONVERSATION_BUSY') setNotice({ tone: 'red', text: strings.limits.busy })
    else setNotice({ tone: 'red', text: failureMessage(failure, { chat: true, now: page.data?.server_now }) })
  }

  /** Sends once, and says how it ended. */
  async function sendOnce(text: string, messageId: string): Promise<Sent> {
    // Anything inside the stream comes after the API stored the message.
    let kept = false
    let failure: Failure | null = null
    // The message went to DawaLink's team, which has this chat: no answer is coming.
    let withTeam = false
    try {
      const accepted = await sendMessage(conversationId, text, messageId, (event: ChatEvent) => {
        kept = true
        if (event.name === 'progress') setProgress(event.data.label)
        if (event.name === 'error') failure = event.data.error
      })
      withTeam = accepted.withTeam
    } catch (error) {
      if (error instanceof StreamDropped) return { outcome: 'dropped' }
      failure =
        error instanceof ApiFailure ? { code: error.code, details: error.details } : { code: 'INTERNAL_ERROR' }
    }
    const found = failure as Failure | null
    return found === null ? { outcome: 'answered', withTeam } : { outcome: 'refused', failure: found, kept }
  }

  async function send(raw: string) {
    const text = raw.trim()
    if (!text || pending !== null) return
    if (text.length > maxChars) {
      setNotice({ tone: 'red', text: s.tooLong(maxChars) })
      return
    }
    // The same ID on every retry, and on a resend of a message the API refused before
    // keeping it: the server stores a message once (docs/06 §6.6).
    const messageId = unsent.current?.text === text ? unsent.current.id : newKey()
    unsent.current = null
    const newest = page.data?.last_seq ?? 0
    setPendingAfter(newest)
    setPending(text)
    setDraft('')
    setNotice(null)
    setDropped(false)
    // Stored on one try, it stays stored when a later try is refused.
    let keptBefore = false
    try {
      for (let attempt = 0; attempt < BUSY_TRIES; attempt += 1) {
        const sent = await sendOnce(text, messageId)
        if (sent.outcome === 'answered') {
          setDegraded(false)
          // A message to DawaLink's team gets no answer of the assistant: nothing to wait for.
          if (thread && !sent.withTeam) setAwaitingAfter(newest)
          break
        }
        if (sent.outcome === 'dropped') {
          // The turn goes on without the stream: "Working on it…" until its reply is
          // polled in (docs/09 FX-16). Not an error: nothing failed for the client.
          setDropped(true)
          setAwaitingAfter(newest)
          break
        }
        const { failure } = sent
        const kept = sent.kept || keptBefore
        keptBefore = kept
        if (failure.code === 'CONVERSATION_BUSY' && attempt < BUSY_TRIES - 1) {
          // The agent is already working here: wait, then send again (API-D8).
          setProgress(s.oneMoment)
          await wait(Number(failure.details?.retry_after_ms ?? 2000))
          continue
        }
        refused(failure, text, messageId, kept)
        break
      }
    } finally {
      await page.refetch()
      setPending(null)
      setProgress(null)
      // The list of chats names a chat by its first message.
      if (!thread) void queryClient.invalidateQueries({ queryKey: ['chats'] })
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
      const failure = error instanceof ApiFailure ? { code: error.code, details: error.details } : { code: 'INTERNAL_ERROR' }
      // [Start sourcing] at night: when requests open again, by the server's clock (B#37).
      setNotice({ tone: 'red', text: failureMessage(failure, { now: page.data?.server_now }) })
    } finally {
      await page.refetch()
      setActing(false)
    }
  }

  async function startNewChat() {
    setNotice(null)
    const fresh = await unwrap(api.POST('/api/v1/conversations/new-chat')).catch(() => null)
    if (!fresh) {
      // Said, never silent: the client would otherwise go on writing in the old chat.
      setNotice({ tone: 'red', text: s.newChatFailed })
      return
    }
    queryClient.setQueryData(['active-chat'], fresh)
    onNewChat?.()
  }

  // The reservations still waiting, for the chat's "Reserved" cards: one that is no
  // longer waiting links to its ticket in plain words (A#36). Asked only when a chat
  // shows such a card; the same list as Home's, so it is shared.
  const showsReserved = messages.some((message) => message.cards.some((card) => card.type === 'reserved'))
  const active = useQuery({
    queryKey: ['reservations', 'active'],
    queryFn: () => unwrap(api.GET('/api/v1/reservations', { params: { query: { view: 'active' } } })),
    enabled: showsReserved,
  })
  const waiting = active.data ? new Set(active.data.items.map((reservation) => reservation.id)) : null
  // The same for a box held for the client (B#15): its card points to the offer only
  // while the offer still waits for a tap. The list Home shows, so it is shared.
  const showsOffer = messages.some((message) => message.cards.some((card) => card.type === 'offer'))
  const openOffers = useQuery({
    queryKey: ['offers'],
    queryFn: () => unwrap(api.GET('/api/v1/offers')),
    enabled: showsOffer,
  })
  const offers: OffersKnown | null = page.data
    ? {
        // Not known while it is read again: a card that just arrived isn't in the list
        // yet, and must not be called over for that.
        open:
          openOffers.data && !openOffers.isFetching
            ? new Set(openOffers.data.items.map((offer) => offer.id))
            : null,
        now: page.data.server_now,
        here: Boolean(thread),
      }
    : null
  // A card that says a reservation ended ("Picked up", "Cancelled") arrives by polling:
  // the list is asked again, so its "Reserved" card stops offering the counter. An offer
  // accepted, declined or over is told by a card too.
  const systemCards = messages.filter((message) => message.author === 'system').length
  const seenSystemCards = useRef(systemCards)
  useEffect(() => {
    if (systemCards === seenSystemCards.current) return
    seenSystemCards.current = systemCards
    if (showsReserved) void queryClient.invalidateQueries({ queryKey: ['reservations', 'active'] })
    if (showsOffer) void queryClient.invalidateQueries({ queryKey: ['offers'] })
  }, [systemCards, showsReserved, showsOffer, queryClient])

  return (
    <main className="chat">
      <header className="chat__header">
        {!(framed && !thread) && (
          <Link to={thread?.backTo ?? '/'} className="round-button" aria-label={strings.common.back}>
            <BackIcon />
          </Link>
        )}
        {/* On a phone the chat's header also holds the list of chats and [New chat]: the
            mark and the second line give them the room. */}
        {!compact && (
          <span className="chat__mark" aria-hidden="true">
            D
          </span>
        )}
        <div className="chat__names">
          <h1 className="chat__title">{thread?.title ?? s.title}</h1>
          {!compact && (
            <span className="chat__subtitle">{thread?.subtitle ?? s.subtitle}</span>
          )}
        </div>
        {!thread && tools}
        {!thread && (
          <button type="button" className="chat__new" onClick={() => void startNewChat()}>
            <PlusIcon small />
            {s.newChat}
          </button>
        )}
      </header>

      {/* Always visible, and it can't be dismissed (UI-D14). */}
      <div className="chat__notice">
        <span>{s.aiNotice}</span>
        {page.data && !thread && !earlier && (
          <button type="button" className="chat__location" onClick={() => setChoosingPlace(true)}>
            <PinIcon small />
            {s.location.button(locationLabel(page.data.location))}
          </button>
        )}
      </div>

      {/* The scroller. Only the list of messages in it is read out as it grows (B#11):
          not the banners, the cards' forms or the quick replies. */}
      <div className="chat__messages">
        {paused && me?.client?.paused_until && page.data && (
          <Banner tone="amber">
            {strings.banner.paused(dayAndClock(me.client.paused_until, page.data.server_now))}
          </Banner>
        )}
        {night && config.data && <Banner tone="grey">{strings.banner.night(config.data.request_hours_start)}</Banner>}
        {page.isError && <Banner tone="amber">{strings.banner.offline}</Banner>}
        {thread?.above}
        {page.isSuccess && messages.length === 0 && pending === null && !thread && !earlier && (
          <div className="empty">
            <span>{s.empty}</span>
            <div className="chips">
              {s.emptyExamples.map((example) => (
                <button
                  key={example}
                  type="button"
                  className="chip"
                  dir="auto"
                  lang={langOf(example)}
                  onClick={() => void send(example)}
                >
                  {example}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* The messages. It appears with the first page already in it, so the history is
            never read out when the page opens; only what arrives later is. An earlier chat
            is only read: nothing in it is announced. The client's own message is announced
            once, when it is stored (the bubble shown while sending is outside). */}
        {page.data && (
          <div
            className="chat__log"
            role={earlier ? undefined : 'log'}
            aria-label={earlier ? undefined : s.messagesLabel}
          >
            {messages.map((message) => (
              <MessageView
                key={message.seq}
                message={message}
                conversationId={conversationId}
                busy={acting}
                earlier={Boolean(earlier)}
                waiting={waiting}
                offers={offers}
                onAct={act}
              />
            ))}
          </div>
        )}
        {pending !== null && !stored && (
          <p className="bubble bubble--mine bubble--waiting" dir="auto">
            <Speaker author="client" />
            <span lang={langOf(pending)}>{pending}</span>
          </p>
        )}

        {/* What the page itself says while and after a send: read out as it changes. */}
        <div className="chat__status" role="status">
          {/* After a send the assistant refused: at the end of the chat, where the client
              looks, never above a long history (A#12). It stays until a send works. */}
          {degraded && (
            <Banner tone="amber" alert>
              {strings.banner.degraded}
            </Banner>
          )}
          {working && !withTeam && <div className="progress-line">{progress ?? s.working}</div>}
          {dropped && working && <Banner tone="grey">{s.replyComing}</Banner>}
          {notice && (
            <Banner
              tone={notice.tone}
              alert={notice.tone === 'red'}
              action={
                notice.tone === 'green' ? undefined : (
                  <button type="button" className="text-button" onClick={() => setNotice(null)}>
                    {strings.common.close}
                  </button>
                )
              }
            >
              {notice.text}
            </Banner>
          )}
        </div>

        {/* They only write an answer for the client: what reserves is a card's button,
            so they look like words to say, not like buttons that do something (B#8). */}
        {!working && !earlier && !withTeam && last?.author === 'agent' && last.quick_replies.length > 0 && (
          <div className="chat__replies">
            <span id={`replies-${conversationId}`} className="hint">
              {s.quickRepliesIntro}
            </span>
            <div className="chips" role="group" aria-labelledby={`replies-${conversationId}`}>
              {last.quick_replies.map((chip) => (
                <button
                  key={chip}
                  type="button"
                  className="chip chip--reply"
                  dir="auto"
                  lang={langOf(chip)}
                  onClick={() => void send(chip)}
                >
                  {chip}
                </button>
              ))}
            </div>
          </div>
        )}
        <div ref={end} />
      </div>

      {/* An earlier chat is read: where the box to write in would be, it says so. */}
      {earlier && (
        <div className="chat__form chat__closed" role="status">
          <span>{s.earlier}</span>
          <button type="button" className="chat__new" onClick={earlier.onBack}>
            {s.backToCurrent}
          </button>
        </div>
      )}
      {withTeam && writable && <Banner tone="grey">{s.withTeam}</Banner>}
      <form className="chat__form" onSubmit={submit} hidden={!writable}>
        <label htmlFor="chat-message" className="sr-only">
          {s.messageLabel}
        </label>
        <input
          id="chat-message"
          className="chat__input"
          type="text"
          dir="auto"
          lang={langOf(draft)}
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
    </main>
  )
}

/**
 * Who speaks, for a screen reader only: the bubbles differ by side and colour alone (B#9).
 * Its own `dir` keeps it out of the bubble's `dir="auto"`, which would otherwise take this
 * English word for the direction of an Arabic message.
 */
function Speaker({ author }: { author: string }) {
  return (
    <span className="sr-only" dir="ltr">
      {`${s.speaker[author] ?? s.speaker.system} `}
    </span>
  )
}

function MessageView({
  message,
  conversationId,
  busy,
  earlier,
  waiting,
  offers,
  onAct,
}: {
  message: Schemas['ChatMessage']
  conversationId: string
  busy: boolean
  earlier: boolean
  waiting: Set<string> | null
  offers: OffersKnown | null
  onAct: (card: Card, selectedItemKeys: string[] | null) => void
}) {
  const mine = message.author === 'client'
  return (
    <>
      {/* A person from DawaLink answered: it must not read as the AI's words. A screen
          reader hears it from the bubble itself. */}
      {message.author === 'admin' && (
        <span className="bubble-label" aria-hidden="true">
          {s.team}
        </span>
      )}
      {message.text && (
        // dir="auto": Arabic runs right to left, Arabizi and English left to right. The
        // language is on the words alone, so "You:" keeps the page's voice (B#10).
        <p className={`bubble ${mine ? 'bubble--mine' : 'bubble--theirs'}`} dir="auto">
          <Speaker author={message.author} />
          <span lang={langOf(message.text)}>{message.text}</span>
        </p>
      )}
      {message.cards.length > 0 && (
        <MessageCards
          cards={message.cards}
          busy={busy}
          earlier={earlier}
          waiting={waiting}
          offers={offers}
          onAct={onAct}
        />
      )}
      {message.reportable && message.text && (
        // Opening the report form is the client's own doing: not read out as news.
        <div aria-live="off" className="chat__report">
          <ReportAnswer conversationId={conversationId} seq={message.seq} reported={message.reported} />
        </div>
      )}
    </>
  )
}
