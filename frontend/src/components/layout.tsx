import { type ReactNode, useContext } from 'react'
import { NavLink } from 'react-router-dom'

import { strings } from '../strings/en'
import { ChatIcon, HomeIcon, PersonIcon, PillIcon } from './icons'
import { SidePanelContext, useWide } from './wide'

const n = strings.nav

/** The menu of the client's portal: Home · Medicines · Ask · Me (docs/11 §3.1). It
 * floats at the bottom of a phone, and is a bar at the top of a wide screen. */
export function NavBar({ top = false }: { top?: boolean }) {
  const tabs = [
    { to: '/', label: n.home, icon: <HomeIcon /> },
    { to: '/medicines', label: n.medicines, icon: <PillIcon /> },
    { to: '/assistant', label: n.ask, icon: <ChatIcon /> },
    { to: '/me', label: n.me, icon: <PersonIcon /> },
  ]
  return (
    <nav className={top ? 'nav nav--top' : 'nav'} aria-label={n.label}>
      {tabs.map((tab) => (
        <NavLink key={tab.to} to={tab.to} end className="nav__tab">
          {tab.icon}
          {tab.label}
        </NavLink>
      ))}
    </nav>
  )
}

/** A screen of the client's portal with its menu. On a wide screen the menu is a top
 * bar and the assistant stands beside the page, so a client on a computer searches and
 * asks without changing page. On a phone nothing of the panel exists: it is not hidden,
 * it is not mounted, so it asks the API for nothing. */
export function Screen({ children }: { children: ReactNode }) {
  const wide = useWide()
  const beside = useContext(SidePanelContext)
  if (!wide) {
    return (
      <>
        <main className="screen">{children}</main>
        <NavBar />
      </>
    )
  }
  return (
    <div className="wide">
      <NavBar top />
      <div className="wide__body">
        <main className="screen screen--wide">{children}</main>
        {beside && (
          <aside className="wide__beside" aria-label={strings.chat.title}>
            {beside}
          </aside>
        )}
      </div>
    </div>
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
