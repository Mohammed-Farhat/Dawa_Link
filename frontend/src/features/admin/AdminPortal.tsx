import { NavLink, Route, Routes } from 'react-router-dom'

import { useSession } from '../../api/session'
import { strings } from '../../strings/en'
import { NotFoundPage } from '../../app/NotFoundPage'
import { AuditPage, ClockPage } from './AuditPages'
import { ClientPage, ClientsPage } from './ClientsPages'
import { useOverview } from './data'
import { EscalationPage, EscalationsPage } from './EscalationsPages'
import { CatalogPage, FlagsPage, HealthPage } from './HealthPages'
import { PharmaciesPage, PharmacyPage } from './PharmaciesPages'
import { ReportPage, ReportsPage } from './ReportsPages'

const s = strings.admin

/**
 * The admin's console (docs/11 §3.3, docs/03 §3): a navy bar of pill tabs, each with
 * what waits behind it. Its code is loaded only for an admin.
 *
 * What an admin can do here is small on purpose: approve and correct pharmacies, answer
 * escalated clients, review reported answers, read the audit log. Nothing changes a
 * pharmacy's stock, a price, or who gets a box first.
 */
export default function AdminPortal() {
  const { logout } = useSession()
  const overview = useOverview()
  const waits = overview.data
  return (
    <div className="portal">
      <header className="bar bar--admin">
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span className="brand__mark" aria-hidden="true">
            D
          </span>
          <span style={{ fontSize: 16, fontWeight: 600 }}>{s.brand}</span>
        </div>
        <nav className="bar__tabs" aria-label={s.nav}>
          <NavLink to="/admin" end className="bar__tab">
            {s.count(s.tabs.pharmacies, (waits?.pharmacies_waiting ?? 0) + (waits?.pins_to_check ?? 0))}
          </NavLink>
          <NavLink to="/admin/escalations" className="bar__tab">
            {s.count(s.tabs.escalations, waits?.escalations_open ?? 0)}
          </NavLink>
          <NavLink to="/admin/reports" className="bar__tab">
            {s.count(s.tabs.reports, waits?.reports_new ?? 0)}
          </NavLink>
          <NavLink to="/admin/clients" className="bar__tab">
            {s.count(s.tabs.clients, waits?.contests_waiting ?? 0)}
          </NavLink>
          <NavLink to="/admin/flags" className="bar__tab">
            {s.count(s.tabs.flags, waits?.flags_open ?? 0)}
          </NavLink>
          <NavLink to="/admin/health" className="bar__tab">
            {s.tabs.health}
          </NavLink>
          <NavLink to="/admin/catalog" className="bar__tab">
            {s.tabs.catalog}
          </NavLink>
          <NavLink to="/admin/audit" className="bar__tab">
            {s.tabs.audit}
          </NavLink>
          {waits?.demo_mode && (
            <NavLink to="/admin/clock" className="bar__tab">
              {s.tabs.clock}
            </NavLink>
          )}
          <button type="button" className="bar__tab" onClick={() => void logout()}>
            {s.logOut}
          </button>
        </nav>
      </header>
      <div className="portal__body">
        <Routes>
          <Route index element={<PharmaciesPage />} />
          <Route path="pharmacies/:id" element={<PharmacyPage />} />
          <Route path="escalations" element={<EscalationsPage />} />
          <Route path="escalations/:id" element={<EscalationPage />} />
          <Route path="reports" element={<ReportsPage />} />
          <Route path="reports/:id" element={<ReportPage />} />
          <Route path="clients" element={<ClientsPage />} />
          <Route path="clients/:id" element={<ClientPage />} />
          <Route path="flags" element={<FlagsPage />} />
          <Route path="health" element={<HealthPage />} />
          <Route path="catalog" element={<CatalogPage />} />
          <Route path="audit" element={<AuditPage />} />
          {/* Outside demo mode the clock's screen doesn't exist (R-DEMO). */}
          {waits?.demo_mode && <Route path="clock" element={<ClockPage />} />}
          <Route path="*" element={<NotFoundPage />} />
        </Routes>
      </div>
    </div>
  )
}
