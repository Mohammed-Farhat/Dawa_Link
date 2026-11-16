import { Link } from 'react-router-dom'

import { ShieldIcon, WalkIcon } from '../../components/icons'
import { strings } from '../../strings/en'

const s = strings.welcome

/** CS-1: the public landing. No stock is shown before login (decision log D1). */
export function WelcomePage() {
  return (
    <main className="screen screen--plain screen--white">
      {/* An illustration of what the app does: invented numbers, read by nobody's screen reader. */}
      <section className="hero" aria-hidden="true">
        <div className="brand">
          <span className="brand__mark">D</span>
          {strings.appName}
        </div>
        <div className="hero__card hero__price">
          <span className="hint">{s.exampleProduct}</span>
          <span style={{ fontSize: 22, fontWeight: 600 }}>{s.examplePrice}</span>
          <span className="saving" style={{ fontSize: 13, padding: '4px 10px' }}>
            {s.exampleSaving}
          </span>
        </div>
        <div className="hero__card hero__ticket">
          <span className="today__label" style={{ fontSize: 11 }}>
            {s.exampleTicket}
          </span>
          <span className="order-ref" style={{ fontSize: 18 }}>
            {s.exampleRef}
          </span>
        </div>
        <div className="hero__card hero__walk">
          <span style={{ color: 'var(--blue)', display: 'flex' }}>
            <WalkIcon small />
          </span>
          {s.exampleWalk}
        </div>
      </section>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 8 }}>
        <h1 className="page-title" style={{ fontSize: 30 }}>
          {s.title}
        </h1>
        <p className="soft" style={{ margin: 0, fontSize: 17, lineHeight: 1.5 }}>
          {s.intro}
        </p>
      </div>

      <ol className="steps">
        {s.steps.map((step, index) => (
          <li key={step}>
            <span className="steps__number">{index + 1}</span>
            {step}
          </li>
        ))}
      </ol>

      <div className="banner banner--green">
        <ShieldIcon />
        <span className="banner__text">{s.safe}</span>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 'auto' }}>
        <Link to="/signup" className="pill-button pill-button--wide">
          {s.signUp}
        </Link>
        <Link to="/login" className="pill-button pill-button--wide pill-button--grey">
          {s.logIn}
        </Link>
        <Link to="/pharmacy/signup" className="text-button" style={{ alignSelf: 'center' }}>
          {s.pharmacy}
        </Link>
      </div>
    </main>
  )
}
