import type { ReactNode } from 'react'

// Simple line icons, drawn here so the website loads no icon library (docs/11 §10).
// An icon always stands next to a word, or its button has an aria-label (docs/11 §2.2).

function Icon({ children, small }: { children: ReactNode; small?: boolean }) {
  return (
    <svg className={small ? 'icon icon--small' : 'icon'} viewBox="0 0 24 24" aria-hidden="true">
      {children}
    </svg>
  )
}

type Props = { small?: boolean }

export const BackIcon = (p: Props) => (
  <Icon {...p}>
    <path d="M15 6l-6 6 6 6" />
  </Icon>
)
export const CloseIcon = (p: Props) => (
  <Icon {...p}>
    <path d="M6 6l12 12M18 6L6 18" />
  </Icon>
)
export const PlusIcon = (p: Props) => (
  <Icon {...p}>
    <path d="M12 5v14M5 12h14" />
  </Icon>
)
export const SendIcon = (p: Props) => (
  <Icon {...p}>
    <path d="M4 12l16-8-6 16-3-7z" />
  </Icon>
)
export const CheckIcon = (p: Props) => (
  <Icon {...p}>
    <path d="M5 12l5 5 9-10" />
  </Icon>
)
export const SearchIcon = (p: Props) => (
  <Icon {...p}>
    <circle cx="11" cy="11" r="7" />
    <path d="M20 20l-4-4" />
  </Icon>
)
export const HomeIcon = (p: Props) => (
  <Icon {...p}>
    <path d="M3 11l9-7 9 7" />
    <path d="M5 10v10h5v-6h4v6h5V10" />
  </Icon>
)
export const PillIcon = (p: Props) => (
  <Icon {...p}>
    <rect x="3" y="8.5" width="18" height="7" rx="3.5" transform="rotate(-45 12 12)" />
    <path d="M9.5 9.5l5 5" />
  </Icon>
)
export const ChatIcon = (p: Props) => (
  <Icon {...p}>
    <path d="M4 5h16v11H9l-5 4z" />
  </Icon>
)
export const PersonIcon = (p: Props) => (
  <Icon {...p}>
    <circle cx="12" cy="8" r="4" />
    <path d="M4 21c1.5-4 4.5-6 8-6s6.5 2 8 6" />
  </Icon>
)
export const TicketIcon = (p: Props) => (
  <Icon {...p}>
    <path d="M4 7h16v3a2 2 0 0 0 0 4v3H4v-3a2 2 0 0 0 0-4z" />
  </Icon>
)
export const PinIcon = (p: Props) => (
  <Icon {...p}>
    <path d="M12 21s-7-6.2-7-11a7 7 0 0 1 14 0c0 4.8-7 11-7 11z" />
    <circle cx="12" cy="10" r="2.5" />
  </Icon>
)
export const MapIcon = (p: Props) => (
  <Icon {...p}>
    <path d="M3 6l6-3 6 3 6-3v15l-6 3-6-3-6 3z" />
    <path d="M9 3v15M15 6v15" />
  </Icon>
)
export const PhoneIcon = (p: Props) => (
  <Icon {...p}>
    <path d="M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a1 1 0 0 1-1 1A15 15 0 0 1 4 5a1 1 0 0 1 1-1z" />
  </Icon>
)
export const PrescriptionIcon = (p: Props) => (
  <Icon {...p}>
    <path d="M7 3h7l5 5v13H7z" />
    <path d="M14 3v5h5" />
    <path d="M10 13h6M10 17h6" />
  </Icon>
)
export const ShieldIcon = (p: Props) => (
  <Icon {...p}>
    <path d="M12 3l8 3v6c0 4.5-3.4 8.3-8 9-4.6-.7-8-4.5-8-9V6z" />
    <path d="M8.5 12l2.5 2.5 4.5-5" />
  </Icon>
)
export const WalkIcon = (p: Props) => (
  <Icon {...p}>
    <circle cx="13" cy="4" r="2" />
    <path d="M10 21l2-6-2-3 1-4 3 3h3" />
    <path d="M12 15l3 2v4" />
    <path d="M8 12l3-4" />
  </Icon>
)
export const AlertIcon = (p: Props) => (
  <Icon {...p}>
    <path d="M12 4l9 16H3z" />
    <path d="M12 10v4M12 17.5v.5" />
  </Icon>
)
export const InfoIcon = (p: Props) => (
  <Icon {...p}>
    <circle cx="12" cy="12" r="9" />
    <path d="M12 11v6M12 7.5v.5" />
  </Icon>
)
export const ThumbDownIcon = (p: Props) => (
  <Icon {...p}>
    <path d="M10 15v4a2 2 0 0 0 2 2l4-8V4H7.2a2 2 0 0 0-2 1.6l-1.2 7A2 2 0 0 0 6 15h4zM16 4h3v9h-3" />
  </Icon>
)
