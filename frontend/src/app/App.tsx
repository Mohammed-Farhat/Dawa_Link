import { MantineProvider } from '@mantine/core'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { lazy, type ReactNode, Suspense, useState } from 'react'
import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom'

import { useSession } from '../api/session'
import { SessionProvider } from '../api/SessionProvider'
import { SidePanelContext } from '../components/wide'
import { CheckEmailPage, LoginPage, SignUpPage, VerifyEmailPage } from '../features/client/AccountPages'
import { AssistantPage } from '../features/client/assistant/AssistantPage'
import { HomePage } from '../features/client/HomePage'
import { MedicinesPage } from '../features/client/MedicinesPage'
import { NotificationsPage } from '../features/client/NotificationsPage'
import { MePage } from '../features/client/ProfilePage'
import { RequestPage } from '../features/client/requests/RequestPage'
import { OfferPage } from '../features/client/search/OfferPage'
import { SearchChoicesProvider } from '../features/client/search/place'
import { SearchPage } from '../features/client/search/SearchPage'
import { TicketPage } from '../features/client/TicketPage'
import { WelcomePage } from '../features/client/WelcomePage'
import { StatusPage } from '../features/status/StatusPage'
import { theme } from '../theme/theme'
import { NotFoundPage } from './NotFoundPage'

// Loaded only for a pharmacist: a client's phone never downloads the pharmacy's portal
// (docs/11 §10).
const PharmacyPortal = lazy(() => import('../features/pharmacy/PharmacyPortal'))
const RegisterPharmacyPage = lazy(() => import('../features/pharmacy/RegisterPharmacyPage'))
// And the admin's console only for an admin.
const AdminPortal = lazy(() => import('../features/admin/AdminPortal'))

/** The admin's console: it needs a logged-in admin, who logs in on a page of its own. */
function ForAdmins() {
  const { me } = useSession()
  const location = useLocation()
  if (me === undefined) return null
  if (me === null) return <Navigate to="/admin/login" replace state={{ from: location.pathname }} />
  if (me.role !== 'admin') return <Navigate to="/" replace />
  return (
    <Suspense fallback={null}>
      <AdminPortal />
    </Suspense>
  )
}

/** The pharmacy's portal: it needs a logged-in pharmacist. */
function ForPharmacists() {
  const { me } = useSession()
  const location = useLocation()
  if (me === undefined) return null
  if (me === null) return <Navigate to="/login" replace state={{ from: location.pathname }} />
  if (me.role !== 'pharmacist') return <Navigate to="/" replace />
  return (
    <Suspense fallback={null}>
      <PharmacyPortal />
    </Suspense>
  )
}

/** A page of the client's portal: it needs a logged-in client. */
function ForClients({ children }: { children: ReactNode }) {
  const { me } = useSession()
  const location = useLocation()
  if (me === undefined) return null // still asking the API who we are
  if (me === null) {
    // After logging in, the client comes back to the screen they wanted (docs/11 §7).
    const wanted = location.pathname === '/' ? '/welcome' : '/login'
    return <Navigate to={wanted} replace state={{ from: location.pathname }} />
  }
  if (me.role === 'pharmacist') return <Navigate to="/pharmacy" replace />
  if (me.role === 'admin') return <Navigate to="/admin" replace />
  return (
    <SearchChoicesProvider>
      {/* Beside a page on a wide screen: the assistant (docs/11 §3.1). */}
      <SidePanelContext.Provider value={<AssistantPage embedded />}>{children}</SidePanelContext.Provider>
    </SearchChoicesProvider>
  )
}

/** A public screen: someone already logged in goes straight to Home. */
function ForVisitors({ children }: { children: ReactNode }) {
  const { me } = useSession()
  if (me === undefined) return null
  if (me !== null) return <Navigate to="/" replace />
  return <>{children}</>
}

export function AppRoutes() {
  const clients = (page: ReactNode) => <ForClients>{page}</ForClients>
  const visitors = (page: ReactNode) => <ForVisitors>{page}</ForVisitors>
  return (
    <Routes>
      <Route path="/welcome" element={visitors(<WelcomePage />)} />
      <Route path="/signup" element={visitors(<SignUpPage />)} />
      <Route path="/login" element={visitors(<LoginPage />)} />
      <Route path="/check-email" element={<CheckEmailPage />} />
      <Route path="/verify-email" element={<VerifyEmailPage />} />
      <Route path="/" element={clients(<HomePage />)} />
      <Route path="/search" element={clients(<SearchPage />)} />
      <Route path="/listings/:id" element={clients(<OfferPage />)} />
      <Route path="/assistant" element={clients(<AssistantPage />)} />
      <Route path="/requests/:id" element={clients(<RequestPage />)} />
      <Route path="/medicines" element={clients(<MedicinesPage />)} />
      <Route path="/reservations/:id" element={clients(<TicketPage />)} />
      <Route path="/me" element={clients(<MePage />)} />
      <Route path="/notifications" element={clients(<NotificationsPage />)} />
      <Route
        path="/pharmacy/signup"
        element={visitors(
          <Suspense fallback={null}>
            <RegisterPharmacyPage />
          </Suspense>,
        )}
      />
      <Route path="/pharmacy/*" element={<ForPharmacists />} />
      {/* The admins' login asks for the code of their authenticator app (R-AU6). */}
      <Route path="/admin/login" element={visitors(<LoginPage withCode />)} />
      <Route path="/admin/*" element={<ForAdmins />} />
      <Route path="/status" element={<StatusPage />} />
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  )
}

export function App() {
  const [queryClient] = useState(() => new QueryClient())
  return (
    <MantineProvider theme={theme} forceColorScheme="light">
      <QueryClientProvider client={queryClient}>
        <SessionProvider>
          <BrowserRouter>
            <AppRoutes />
          </BrowserRouter>
        </SessionProvider>
      </QueryClientProvider>
    </MantineProvider>
  )
}
