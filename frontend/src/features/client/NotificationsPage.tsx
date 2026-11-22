import { useInfiniteQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'

import { api, unwrap } from '../../api/client'
import { Screen } from '../../components/layout'
import { Placeholder } from '../../components/Placeholder'
import { dateAndClock, langOf } from '../../format'
import { strings } from '../../strings/en'

const s = strings.notifications

/**
 * What happened, the newest first (docs/03 CS-12, PS-11). Each line is one event, said
 * by a template: the same words as its email. A tap goes where the event is.
 * Used by the client's portal and by the pharmacy's.
 */
export function NotificationsList() {
  const queryClient = useQueryClient()
  const pages = useInfiniteQuery({
    queryKey: ['notifications'],
    queryFn: ({ pageParam }) =>
      unwrap(api.GET('/api/v1/notifications', { params: { query: { cursor: pageParam ?? undefined, limit: 20 } } })),
    initialPageParam: null as number | null,
    getNextPageParam: (last) => (last.next_cursor ? Number(last.next_cursor) : undefined),
    refetchInterval: 30_000,
  })
  const items = pages.data?.pages.flatMap((page) => page.items) ?? []
  const unread = pages.data?.pages[0]?.unread ?? 0

  async function read(body: { ids: number[]; all: boolean }) {
    await api.POST('/api/v1/notifications/read', { body })
    await queryClient.invalidateQueries({ queryKey: ['notifications'] })
  }

  return (
    <>
      <div className="row-card__top">
        <h1 className="page-title">{s.title}</h1>
        {unread > 0 && (
          <button type="button" className="text-button" onClick={() => void read({ ids: [], all: true })}>
            {s.markAll}
          </button>
        )}
      </div>
      {pages.isPending && <Placeholder height={72} />}
      {pages.isSuccess && items.length === 0 && <div className="empty">{s.none}</div>}
      <ul className="plain-list" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        {items.map((note) => {
          const body = (
            <>
              <div className="row-card__top">
                <span style={{ fontSize: 17, fontWeight: note.read ? 500 : 700 }}>{note.title}</span>
                {!note.read && <span className="status-pill status-pill--blue">{s.unread}</span>}
              </div>
              {note.lines.map((line) => (
                <span key={line} className="soft" style={{ fontSize: 15 }} dir="auto" lang={langOf(line)}>
                  {line}
                </span>
              ))}
              <span className="hint">{dateAndClock(note.created_at)}</span>
            </>
          )
          return (
            <li key={note.id} className="row-card">
              {note.link ? (
                <Link
                  to={note.link}
                  className="row-link"
                  onClick={() => !note.read && void read({ ids: [note.id], all: false })}
                >
                  {body}
                </Link>
              ) : (
                <div className="row-link">{body}</div>
              )}
            </li>
          )
        })}
      </ul>
      {pages.hasNextPage && (
        <button type="button" className="text-button" onClick={() => void pages.fetchNextPage()}>
          {s.more}
        </button>
      )}
    </>
  )
}

/** CS-12: the client's notifications, reached from Me. */
export function NotificationsPage() {
  return (
    <Screen>
      <NotificationsList />
    </Screen>
  )
}
