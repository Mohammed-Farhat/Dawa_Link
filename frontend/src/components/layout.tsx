import { type ReactNode, useEffect, useRef, useState } from 'react'
import { Link, NavLink, useLocation } from 'react-router-dom'

import { useSession } from '../api/session'
import { strings } from '../strings/en'
import { ChatIcon, HomeIcon, PersonIcon, PillIcon, SearchIcon } from './icons'
import { useWide } from './wide'

const n = strings.nav

/** The floating menu of the client's portal on a phone: Home · Search · Medicines · Ask ·
 * Me (docs/11 §3.1; Search since BLD-D42, when Home lost its search box). */
export function NavBar() {
  const tabs = [
    { to: '/', label: n.home, icon: <HomeIcon /> },
    { to: '/search', label: n.search, icon: <SearchIcon /> },
    { to: '/medicines', label: n.medicines, icon: <PillIcon /> },
    { to: '/assistant', label: n.ask, icon: <ChatIcon /> },
    { to: '/me', label: n.me, icon: <PersonIcon /> },
  ]
  return (
    <nav className="nav" aria-label={n.label}>
      {tabs.map((tab) => (
        <NavLink key={tab.to} to={tab.to} end className="nav__tab">
          {tab.icon}
          {tab.label}
        </NavLink>
      ))}
    </nav>
  )
}

/**
 * The bar at the top of a computer's screen: the pages on the left; on the right the way
 * to the assistant, which has a page of its own, and the account's menu with [Log out]
 * (decision log BLD-D40; the assistant beside every page was removed by BLD-D42).
 */
function TopBar() {
  const { me, logout } = useSession()
  const { pathname } = useLocation()
  const pages = [
    { to: '/', label: n.home, icon: <HomeIcon small /> },
    { to: '/search', label: n.search, icon: <SearchIcon small /> },
    { to: '/medicines', label: n.myMedicines, icon: <PillIcon small /> },
  ]
  const onAssistant = pathname.startsWith('/assistant')
  return (
    <header className="topbar">
      <Link to="/" className="brand topbar__brand">
        <span className="brand__mark" aria-hidden="true">
          D
        </span>
        {strings.appName}
      </Link>
      <nav className="topbar__nav" aria-label={n.label}>
        {pages.map((page) => (
          <NavLink key={page.to} to={page.to} end className="topbar__link">
            {page.icon}
            {page.label}
          </NavLink>
        ))}
      </nav>
      <Link to="/assistant" className="topbar__ask" aria-current={onAssistant ? 'page' : undefined}>
        <ChatIcon small />
        {n.askAssistant}
      </Link>
      <AccountMenu name={me?.client?.first_name ?? me?.full_name ?? n.me} onLogOut={() => void logout()} />
    </header>
  )
}

/**
 * The account's menu of the top bar: the profile, the notifications, [Log out].
 *
 * A small menu of our own, so that the start-up script stays light (docs/11 §10). It
 * opens with a click, Enter or the space bar; Escape or a click elsewhere closes it and
 * the arrows move through it.
 */
function AccountMenu({ name, onLogOut }: { name: string; onLogOut: () => void }) {
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  const button = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!open) return
    const outside = (event: PointerEvent) => {
      if (!box.current?.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('pointerdown', outside)
    // The first choice takes the focus, so the keyboard goes on from there.
    box.current?.querySelector<HTMLElement>('[role="menuitem"]')?.focus()
    return () => document.removeEventListener('pointerdown', outside)
  }, [open])

  function keys(event: React.KeyboardEvent) {
    if (event.key === 'Escape') {
      setOpen(false)
      button.current?.focus()
      return
    }
    if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return
    const items = Array.from(box.current?.querySelectorAll<HTMLElement>('[role="menuitem"]') ?? [])
    const at = items.indexOf(document.activeElement as HTMLElement)
    const next = event.key === 'ArrowDown' ? at + 1 : at - 1
    items[(next + items.length) % items.length]?.focus()
    event.preventDefault()
  }

  const close = () => setOpen(false)
  return (
    <div className="menu" ref={box} onKeyDown={keys}>
      <button
        ref={button}
        type="button"
        className="topbar__account"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`${n.account}: ${name}`}
        onClick={() => setOpen(!open)}
      >
        <PersonIcon small />
        <span className="topbar__name">{name}</span>
      </button>
      {open && (
        <div className="menu__list" role="menu" aria-label={n.account}>
          <Link to="/me" role="menuitem" className="menu__item" onClick={close}>
            {n.profile}
          </Link>
          <Link to="/notifications" role="menuitem" className="menu__item" onClick={close}>
            {strings.notifications.title}
          </Link>
          <button
            type="button"
            role="menuitem"
            className="menu__item menu__item--last"
            onClick={() => {
              close()
              onLogOut()
            }}
          >
            {strings.me.logOut}
          </button>
        </div>
      )}
    </div>
  )
}

/**
 * The frame of the client's portal on a computer: the top bar, and the page under it.
 * A page that is a conversation fills what is left of the window.
 */
export function Shell({ children }: { children: ReactNode }) {
  return (
    <div className="wide">
      <TopBar />
      <div className="wide__body">{children}</div>
    </div>
  )
}

/**
 * A screen of the client's portal.
 *
 * - **On a phone** it is one column with the floating menu under it; a `plain` screen (a
 *   page reached from another one, with its own back arrow) has no menu.
 * - **On a computer** every screen stands in the same frame: the top bar, and the page
 *   using the window's width.
 *
 * `narrow`: a page that is one card or one form, kept to a readable width.
 *
 * Its main area is where "Skip to content" goes, and its h1 names the browser's tab and
 * takes the focus after a move from another page (`components/arrival.ts`, B#19, B#34).
 */
export function Screen({
  children,
  plain = false,
  narrow = false,
}: {
  children: ReactNode
  plain?: boolean
  narrow?: boolean
}) {
  const wide = useWide()
  if (!wide) {
    return (
      <>
        <main className={plain ? 'screen screen--plain' : 'screen'} id="main">
          {children}
        </main>
        {!plain && <NavBar />}
      </>
    )
  }
  return (
    <Shell>
      <main className={narrow ? 'page page--narrow' : 'page'} id="main">
        {children}
      </main>
    </Shell>
  )
}

type Tone = 'grey' | 'amber' | 'green' | 'red'

/** A line at the top of a screen: paused, night, unverified, degraded (docs/11 §4). */
export function Banner({
  tone,
  children,
  action,
  alert,
}: {
  tone: Tone
  children: ReactNode
  action?: ReactNode
  alert?: boolean
}) {
  return (
    <div className={`banner banner--${tone}`} role={alert ? 'alert' : 'status'}>
      <span className="banner__text">{children}</span>
      {action}
    </div>
  )
}
