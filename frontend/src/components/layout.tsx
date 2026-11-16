import type { ReactNode } from 'react'
import { NavLink } from 'react-router-dom'

import { strings } from '../strings/en'
import { ChatIcon, HomeIcon, PersonIcon, PillIcon } from './icons'

const n = strings.nav

/** The floating menu of the client's portal: Home · Medicines · Ask · Me (docs/11 §3.1). */
export function NavBar() {
  const tabs = [
    { to: '/', label: n.home, icon: <HomeIcon /> },
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

/** A screen of the client's portal with the menu under it. */
export function Screen({ children }: { children: ReactNode }) {
  return (
    <>
      <main className="screen">{children}</main>
      <NavBar />
    </>
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
