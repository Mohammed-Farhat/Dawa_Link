import { MantineProvider } from '@mantine/core'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { lazy, type ReactNode, Suspense, useState } from 'react'
import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom'

import { accountDeletedNoted, useSession } from '../api/session'
import { SessionProvider } from '../api/SessionProvider'
import { useFocusOnArrival, useNamedPage } from '../components/arrival'
import { PageError } from '../components/PageError'
import { SkipLink } from '../components/SkipLink'
import { Waiting } from '../components/Waiting'
import { strings } from '../strings/en'
import {
  CheckEmailPage,
  ForgotPasswordPage,
  LoginPage,
  ResetPasswordPage,
  SignUpPage,
  VerifyEmailPage,
} from '../features/client/AccountPages'
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
import { cssVariablesResolver, theme } from '../theme/theme'
import { NotFoundPage } from './NotFoundPage'

// Loaded only for a pharmacist: a client's phone never downloads the pharmacy's portal
// (docs/11 §10).
const PharmacyPortal = lazy(() => import('../features/pharmacy/PharmacyPortal'))
const RegisterPharmacyPage = lazy(() => import('../features/pharmacy/RegisterPharmacyPage'))
// And the admin's console only for an admin.
const AdminPortal = lazy(() => import('../features/admin/AdminPortal'))

/** The admin's console: it needs a logged-in admin, who logs in on a page of its own. */
function ForAdmins() {
  const { me, unreachable } = useSession()
  const location = useLocation()
  if (me === undefined) return <Waiting unreachable={unreachable} />
  if (me === null) return <Navigate to="/admin/login" replace state={{ from: location.pathname }} />
  if (me.role !== 'admin') return <Navigate to="/" replace />
  return (
    <Suspense fallback={<Waiting />}>
      <AdminPortal />
    </Suspense>
  )
}

/** The pharmacy's portal: it needs a logged-in pharmacist. */
function ForPharmacists() {
  const { me, unreachable } = useSession()
  const location = useLocation()
  if (me === undefined) return <Waiting unreachable={unreachable} />
  if (me === null) return <Navigate to="/login" replace state={{ from: location.pathname }} />
  if (me.role !== 'pharmacist') return <Navigate to="/" replace />
  return (
    <Suspense fallback={<Waiting />}>
      <PharmacyPortal />
    </Suspense>
  )
}

/** A page of the client's portal: it needs a logged-in client. */
function ForClients({ children }: { children: ReactNode }) {
  const { me, unreachable } = useSession()
  const location = useLocation()
  // Still asking the API who we are, or it can't be reached: never the login for that.
  if (me === undefined) return <Waiting unreachable={unreachable} />
  if (me === null) {
    // After logging in, the client comes back to the screen they wanted (docs/11 §7).
    // Someone who just deleted their account goes to the welcome page, which says so.
    const wanted = location.pathname === '/' || accountDeletedNoted() ? '/welcome' : '/login'
    return <Navigate to={wanted} replace state={{ from: location.pathname }} />
  }
  if (me.role === 'pharmacist') return <Navigate to="/pharmacy" replace />
  if (me.role === 'admin') return <Navigate to="/admin" replace />
  return (
    <SearchChoicesProvider>{children}</SearchChoicesProvider>
  )
}

/** A public screen: someone already logged in goes straight to Home. */
function ForVisitors({ children }: { children: ReactNode }) {
  const { me, unreachable } = useSession()
  const { state } = useLocation() as { state: { from?: string } | null }
  if (me === undefined) return <Waiting unreachable={unreachable} />
  // Someone who just logged in goes back to the screen that asked for the login (a page
  // of ours, kept by the router: never an address taken from a link).
  if (me !== null) return <Navigate to={state?.from ?? '/'} replace />
  return <>{children}</>
}

/** The browser tab's name of a page while it shows no heading of its own (B#19). */
function nameWithoutHeading(pathname: string): string | null {
  if (pathname === '/search') return strings.nav.search
  if (pathname.startsWith('/reservations/')) return strings.shell.reservationTitle
  return null
}

export function AppRoutes() {
  const { pathname } = useLocation()
  useNamedPage(nameWithoutHeading(pathname))
  // In the three portals alike: a tab of the pharmacy's or the admin's bar too (B#19).
  useFocusOnArrival()
  const clients = (page: ReactNode) => <ForClients>{page}</ForClients>
  const visitors = (page: ReactNode) => <ForVisitors>{page}</ForVisitors>
  return (
    <>
      <SkipLink />
      {/* A part that fails to load or to show leaves a page that says so (A#4). */}
      <PageError at={pathname}>
        <Routes>
          <Route path="/welcome" element={visitors(<WelcomePage />)} />
          <Route path="/signup" element={visitors(<SignUpPage />)} />
          <Route path="/login" element={visitors(<LoginPage />)} />
          {/* "Forgot my password" (R-AU9): for anyone, logged in or not. Asking reveals
              nothing (the answer is the same for every email), and the reset page's
              [Send me a new link] leads here for someone logged in too. */}
          <Route path="/forgot-password" element={<ForgotPasswordPage />} />
          {/* The reset link is for anyone who opens it, logged in or not: it proves the
              mailbox, not the login. A logged-in person is logged out when it is used. */}
          <Route path="/reset-password" element={<ResetPasswordPage />} />
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
              <Suspense fallback={<Waiting />}>
                <RegisterPharmacyPage />
              </Suspense>,
            )}
          />
          <Route path="/pharmacy/*" element={<ForPharmacists />} />
          {/* The admins' login asks for the code of their authenticator app (R-AU6). */}
          <Route path="/admin/login" element={visitors(<LoginPage withCode />)} />
          <Route path="/admin/*" element={<ForAdmins />} />
          {/* These two pages have no main area of their own: it is given here (B#34). */}
          <Route
            path="/status"
            element={
              <main>
                <StatusPage />
              </main>
            }
          />
          <Route
            path="*"
            element={
              <main>
                <NotFoundPage />
              </main>
            }
          />
        </Routes>
      </PageError>
    </>
  )
}

export function App() {
  const [queryClient] = useState(() => new QueryClient())
  return (
    <MantineProvider theme={theme} cssVariablesResolver={cssVariablesResolver} forceColorScheme="light">
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
